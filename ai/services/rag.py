from __future__ import annotations
import re
import json
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI
from cfg import settings
from services.cache import cache_get, cache_set_json

BASE = Path(__file__).resolve().parents[1]

OPENAI_API_KEY = settings.OPENAI_API_KEY

DB_PATH = BASE / "data" / "rag_db"
CSV_PATH = BASE / "data" / "crime_mapping_worklist.csv"

COLLECTION_NAME = "criminal_cases"
LLM_MODEL = settings.OPENAI_COMPOSE_MODEL

# Lazy initialization
_chroma_client = None
_collection = None
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def _case_summary_cache_key(case_no: str) -> str:
    normalized = (case_no or "unknown").strip()
    version = (settings.RAG_CASE_SUMMARY_VERSION or "v1").strip()
    return f"baro:rag:case-summary:{version}:{normalized}"


def _similarity_fallback(user_text: str, case: dict) -> str:
    label = case.get("label") or "해당 범죄"
    return f"사용자 사건과 {label} 관련 사실관계의 유사성을 검토할 수 있습니다."


def get_collection():
    """ChromaDB collection을 lazy하게 초기화"""
    global _chroma_client, _collection

    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=str(DB_PATH))
        openai_ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small",
        )
        _collection = _chroma_client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=openai_ef,
        )

    return _collection

def load_offense_names(csv_path: str):
    offense_names: list[str] = []

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()

    for line in lines[1:]:
        if not line.strip():
            continue
        name = line.split(",", 1)[0].strip()
        if name:
            offense_names.append(name)

    return offense_names


MAJOR_OFFENSES = load_offense_names(str(CSV_PATH))
OFFENSE_LIST_STR = ", ".join(MAJOR_OFFENSES)


# 사건 개요 → 죄목 키워드 
def predict_crime_keyword(user_query: str) -> str:
    prompt = f"""
    너는 형사 사건 고소장을 분류하는 보조 도구야.

    [규칙]
    - 아래 '죄목 리스트'에 있는 항목들 중에서 **가장 관련성이 높은 죄목 하나만** 골라서 출력해라.
    - 애매하더라도, 리스트 중에서 가장 가까운 죄목을 하나 선택해라.
    - '기타', '모름' 같은 단어는 절대 쓰지 말고, 죄목 이름만 딱 한 단어(또는 한 구절)로 출력해라.

    [죄목 리스트]
    {OFFENSE_LIST_STR}

    [사용자 사건 개요]
    {user_query}
    """

    resp = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


# 벡터 검색 + 죄명 필터
SEARCH_CANDIDATES = 100  # 서술과 가까운 판례를 이만큼 가져와 그 안에서 고른다


def crime_names(label: str) -> list[str]:
    """판례 라벨(쉼표로 이은 죄명들)을 죄명 목록으로 나눈다."""
    return [c.strip() for c in (label or "").split(",") if c.strip()]


def is_crime(name: str, keyword: str) -> bool:
    """죄명이 찾는 죄목인가. '상습사기', '업무상횡령'처럼 앞에 말이 붙은 것도 같은 죄목으로 본다.

    글자가 들어 있는지로만 보면 '군사기밀보호법위반'이 '사기'로 잡힌다.
    라벨에는 '사기{인정된죄명:...}'처럼 괄호로 덧붙인 말이나, 가운뎃점으로 이은 죄명('...법률위반·사기')도 있다.
    괄호 뒤는 떼고, 가운뎃점으로 나눈 조각도 따로 본다.
    """
    key = keyword.replace(" ", "")
    whole = re.split(r"[\[{(（]", name, maxsplit=1)[0].replace(" ", "")
    return any(part.endswith(key) for part in [whole] + whole.split("·") if part)


def search_similar_cases_filtered(query_text: str, keyword: str, k: int = 3) -> list[dict]:
    """서술과 가까운 판례 가운데 찾는 죄목의 판례를 고른다.

    판례 하나에 죄명이 여럿 붙은 경우가 많고, 라벨에는 어느 것이 주된 죄명인지가 없다.
    그래서 죄명이 모두 찾는 죄목인 판례를 먼저 고르고, 모자라면 다른 죄명이 섞인 판례로 채운다.
    같은 묶음 안에서는 서술과 가까운 순서다.
    """
    collection = get_collection()
    results = collection.query(
        query_texts=[query_text],
        n_results=SEARCH_CANDIDATES,
    )

    filtered_cases: list[dict] = []

    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        label = meta.get("label", "")
        names = crime_names(label)

        if keyword != "기타" and not any(is_crime(n, keyword) for n in names):
            continue

        case_info = {
            "case_no": meta.get("case_no", ""),
            "label": label,
            "summary": meta.get("summary", ""),
            "facts": meta.get("facts", ""),
            "score": results["distances"][0][i],
            # 찾는 죄목이 아닌 죄명이 섞여 있는가
            "mixed": keyword != "기타" and not all(is_crime(n, keyword) for n in names),
        }
        filtered_cases.append(case_info)

    if not filtered_cases:
        return []

    filtered_cases.sort(key=lambda c: (c["mixed"], c["score"]))

    return filtered_cases[:k]


# 판례 요약 정보 생성
def summarize_cases_for_ui(user_text: str, cases: list[dict]) -> list[dict]:
    """
    입력:
      - user_text: 사용자가 쓴 사건 개요
      - cases: Chroma에서 뽑힌 raw 판례들
        (각 원소: {"case_no", "label", "summary", "facts", "score"})

    출력:
      - [
          {
            "case_no": "...",
            "label": "...",
            "summary": "사건 요약",
            "result": "판결 결과 및 적용 죄목",
            "similarity": "내 사건과의 공통점"
          },
          ...
        ]
    """
    if not cases:
        return []

    summarized: list[dict] = []
    for case in cases:
        case_summary = get_or_create_case_summary(case)
        summarized.append(
            {
                **case_summary,
                "similarity": _similarity_fallback(user_text, case),
            }
        )
    return summarized


def get_or_create_case_summary(case: dict) -> dict:
    case_no = case.get("case_no", "")
    cache_key = _case_summary_cache_key(case_no)

    cached = cache_get(cache_key)
    if cached:
        try:
            data = json.loads(cached)
            print(f"[RAG CACHE] hit version={settings.RAG_CASE_SUMMARY_VERSION} case_no={case_no}")
            return _normalize_case_summary(case, data)
        except Exception as e:
            print(f"[RAG CACHE] invalid cache version={settings.RAG_CASE_SUMMARY_VERSION} case_no={case_no}: {e}")

    print(f"[RAG CACHE] miss version={settings.RAG_CASE_SUMMARY_VERSION} case_no={case_no}")
    summary = summarize_single_case(case)
    cache_set_json(
        cache_key,
        json.dumps(summary, ensure_ascii=False),
        settings.RAG_CASE_CACHE_TTL_SECONDS,
    )
    return summary


def summarize_single_case(case: dict) -> dict:
    system_prompt = """
    너는 형사 사건 판례 검색 엔진의 결과 요약 봇이야.
    감정적인 공감이나 서론, 결론, 면책 문구(법적 효력이 없다는 경고 등)를 절대 붙이지 마.
    사용자가 원하는 포맷에 맞춰서 필요한 정보만 기계적으로 채워.
    """

    user_prompt = f"""
    [후보 판례]
    - 사건번호: {case.get('case_no', '')}
    - 죄목(label): {case.get('label', '')}
    - 사실관계(facts): {case.get('facts', '')[:1200]}

    위 정보를 참고해서, 아래 형식의 JSON만 출력해라.

    {{
      "case_no": "<해당 판례 사건번호 그대로>",
      "label": "<해당 판례 label 그대로>",
      "summary": "<해당 판례의 사건 요약(1~2문장)>",
      "result": "<유죄/무죄 여부 및 적용 죄목, 형량 등 판결 결과 요약>"
    }}

    주의:
    - JSON 이외의 텍스트는 출력하지 마라.
    - 요약은 1~3문장 정도로 간결하게 작성해라.
    """

    try:
        resp = openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",  "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content or ""
        data = json.loads(raw)
        return _normalize_case_summary(case, data)
    except Exception as e:
        print(f"[RAG CACHE] summarize failed case_no={case.get('case_no', '')}: {e}")
        return _fallback_case_summary(case)


def _normalize_case_summary(fallback: dict, data: dict) -> dict:
    return {
        # 사건번호와 죄명은 검색 결과의 값을 쓴다. LLM이 돌려준 값은 쓰지 않는다 (다른 번호를 적을 수 있다).
        "case_no": fallback.get("case_no", ""),
        "label": fallback.get("label", ""),
        "summary": (data.get("summary") or "").strip()
        or fallback.get("summary", "")[:200]
        or fallback.get("facts", "")[:200],
        "result": (data.get("result") or "").strip()
        or "(판결 결과는 판례 원문을 참고해야 합니다.)",
    }


def _fallback_case_summary(case: dict) -> dict:
    return {
        "case_no": case.get("case_no", ""),
        "label": case.get("label", ""),
        "summary": case.get("facts", "")[:200],
        "result": "(판결 결과는 판례 원문을 참고해야 합니다.)",
    }



# offense 매핑
def map_keyword_to_offense(keyword: str) -> str:
    k = (keyword or "").strip()

    # 임시로 지정
    if "모욕" in k or "명예훼손" in k or "명예 훼손" in k or "정보통신망" in k:
        return "insult"

    # 일단 나머지는 전부 fraud 템플릿 사용
    return "fraud"

def run_rag_preview(user_text: str, k: int = 2) -> dict:
    """
    - user_text 기반으로 CSV 죄목 리스트에서 keyword 추정
    - Chroma에서 유사 판례 k개 검색
    - 각 판례에 대해 UI에 바로 쓸 수 있는 요약 문자열 생성

    반환 예시:
    {
      "keyword": "사기",
      "cases": [
        { "case_no": "...", "label": "...", "text": "(1) [...] ..." },
        { "case_no": "...", "label": "...", "text": "(2) [...] ..." },
      ]
    }
    """
    keyword = predict_crime_keyword(user_text)
    raw_cases = search_similar_cases_filtered(user_text, keyword, k=k)
    summarized = summarize_cases_for_ui(user_text, raw_cases)

    return {
        "keyword": keyword, 
        "cases": summarized, 
    }
