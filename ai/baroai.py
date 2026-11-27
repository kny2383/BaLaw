import copy
import hmac

from fastapi import BackgroundTasks, Depends, Header, HTTPException, Request, Response
from uuid import uuid4
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal, Optional
from cfg import settings
from flow.chat_graph import build_chat_graph, claims_to_confirm
from flow.checkpoint import chat_config, delete_session, prune_session, rag_config
from flow.rag_graph import build_rag_graph, failed_result
from services import llm, llm_stats, pii
from services.llm import LLMCallError, StructuredOutputError
from services.rag import map_keyword_to_offense
from services.rag_bootstrap import ensure_rag_resources
from langgraph.types import Command

# 토큰 없이 열어 두는 주소: 상태 확인(/)과, 자기 토큰을 따로 가진 호출 기록 집계(/llm/stats).
OPEN_PATHS = ("/", "/llm/stats")


def _bearer_matches(authorization: Optional[str], expected: str) -> bool:
    given = (authorization or "").removeprefix("Bearer ").strip()
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def require_service_token(request: Request, authorization: Optional[str] = Header(default=None)) -> None:
    """BARO_AI_TOKEN이 설정돼 있으면 `Authorization: Bearer <토큰>`이 맞는 요청만 받는다.

    이 서비스의 주소는 세션 값만 알면 그 세션의 대화를 이어 가고 초안을 만들 수 있다.
    서버만 부를 수 있게 하려는 것이다. 사용자 인증은 서버가 한다.
    """
    expected = settings.BARO_AI_TOKEN
    if not expected or request.url.path in OPEN_PATHS:
        return
    if not _bearer_matches(authorization, expected):
        raise HTTPException(401, "인증이 필요합니다.", headers={"WWW-Authenticate": "Bearer"})


app = FastAPI(title="BARO-AI: Complaint Draft API", version="0.1.0", dependencies=[Depends(require_service_token)])


@app.on_event("startup")
async def startup_event():
    """서비스 시작 시 RAG DB 준비"""
    if not settings.BARO_AI_TOKEN:
        print("[AUTH] BARO_AI_TOKEN이 없습니다. /chat/* 주소를 토큰 없이 부를 수 있습니다. 외부에서 닿지 않는 곳에서만 이렇게 씁니다.")
    print("[STARTUP] Ensuring RAG resources...")
    ensure_rag_resources()
    print("[STARTUP] RAG resources ready!")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# 세션 상태는 그래프의 체크포인터에 thread별로 남는다 (flow/checkpoint.py).
CHAT_GRAPH = build_chat_graph()
RAG_GRAPH = build_rag_graph()

class FollowupRequest(BaseModel):
    offense: Literal["fraud", "insult"]
    history: list[dict] # [{"role":"user"|"assistant","content":"..."}]

class ComposeRequest(BaseModel):
    session_id: str

class ComposeConfirmRequest(BaseModel):
    session_id: str
    # 확인을 요청받은 표현(verification.to_confirm)과 같은 순서. true = 사용자가 겪은 사실이 맞다.
    answers: list[bool]

class ChatInitRequest(BaseModel):
    text: str
    offense: Optional[str] = None
    # 호출하는 쪽이 이미 알고 있는 식별정보 (입력 화면의 이름, 주소 등). 서술에서 찾아 표식으로 바꾼다.
    # {"names": [...], "addresses": [...], "phones": [...], "accounts": [...]}
    known_pii: Optional[dict[str, list[str]]] = None

class ChatMessageRequest(BaseModel):
    session_id: str
    message: str

class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRestoreRequest(BaseModel):
    history: list[ChatHistoryItem]
    known_pii: Optional[dict[str, list[str]]] = None

@app.get("/")
def health():
    return {"ok": True, "service": app.title, "model": settings.OPENAI_CHAT_MODEL}


@app.get("/llm/stats")
def llm_call_stats(authorization: Optional[str] = Header(default=None)):
    """최근 LLM 호출을 작업별로 모은 수치. 프롬프트와 응답 내용은 들어 있지 않다.

    기본은 닫혀 있다. LLM_STATS_TOKEN을 설정하고 `Authorization: Bearer <토큰>`으로 불러야 열린다.
    토큰이 없거나 틀리면 주소가 있는지도 알리지 않는다 (404).
    """
    expected = settings.LLM_STATS_TOKEN
    if not expected or not _bearer_matches(authorization, expected):
        raise HTTPException(status_code=404, detail="Not Found")
    return {"window": llm.RECENT.maxlen, **llm_stats.summarize(llm.recent())}


UNSUPPORTED = "unsupported"


def _normalize_offense(offense: Optional[str]) -> Optional[str]:
    # 값이 없거나 공백뿐이면 죄목을 고르지 않은 것이다 (판례 검색 결과로 양식을 정한다).
    if not offense or not offense.strip():
        return None

    normalized = offense.strip().lower()
    offense_map = {
        "fraud": "fraud",
        "사기": "fraud",
        "사기죄": "fraud",
        "cyber_fraud": "fraud",
        "사이버사기": "fraud",
        "insult": "insult",
        "모욕": "insult",
        "모욕죄": "insult",
    }

    # 지원하지 않는 죄목을 사기 양식으로 바꾸지 않는다 (결정 0001 결정 2, 지표 M5).
    return offense_map.get(normalized, UNSUPPORTED)


def _session(session_id: str) -> dict:
    """세션의 현재 대화 상태. 없으면 404."""
    values = CHAT_GRAPH.get_state(chat_config(session_id)).values
    if not values:
        raise HTTPException(404, "세션을 찾을 수 없습니다. /chat/init 먼저 호출하세요.")
    return values


def _rag(session_id: str, pii_state: Optional[dict] = None) -> dict:
    """판례 검색 상태. 아직 끝나지 않았으면 pending. pii_state를 주면 판례 요약 안의 표식을 되돌린다."""
    result = RAG_GRAPH.get_state(rag_config(session_id)).values.get("result") or {}
    return {
        "rag_status": result.get("status", "pending"),
        "rag_keyword": result.get("keyword"),
        "rag_cases": pii.unmask(result.get("cases") or [], pii_state),
    }


def _offense_from_rag(session_id: str, state: dict):
    """죄목을 직접 고르지 않은 세션은 판례 검색이 끝나면 그 키워드로 양식을 정한다."""
    if state.get("offense_selected"):
        return None
    rag = _rag(session_id)
    if rag["rag_status"] != "ready":
        return None
    return map_keyword_to_offense(rag["rag_keyword"])


def _create_session(session_id: str, text: str, offense: Optional[str] = None,
                    known_pii: Optional[dict] = None) -> dict:
    """세션을 만든다. 서술의 식별정보는 표식으로 바꿔 저장한다 (돌려주는 상태의 history가 바뀐 글이다)."""
    selected_offense = _normalize_offense(offense)
    pii_state = pii.new_state(known_pii) if settings.PII_MASKING else {}
    if pii_state:
        text = pii.mask(text, pii_state)
    with llm.session(session_id):
        return CHAT_GRAPH.invoke(
            {"request": {
                "action": "init",
                "text": text,
                "offense": selected_offense or "fraud",
                "offense_selected": bool(selected_offense),
                "pii": pii_state,
            }},
            chat_config(session_id),
        )


def _load_rag_preview(session_id: str, text: str) -> None:
    config = rag_config(session_id)
    try:
        with llm.session(session_id):
            RAG_GRAPH.invoke({"request": {"text": text}}, config)
    except Exception as e:
        # 어느 단계에서 실패했든 마지막 노드의 결과로 실패 상태를 남긴다 (실행을 이어 가지 않는다).
        print(f"[RAG] 판례 검색 실패 session={llm.session_tag(session_id)} reason={type(e).__name__}")
        RAG_GRAPH.update_state(config, failed_result(e), as_node="summarize_cases")
    prune_session(session_id, rag=True)


def _progress_from_session(s: dict) -> dict:
    collected = s.get("collected") or {}
    elements = collected.get("elements") or {}
    details = collected.get("details") or {}

    return {
        "complete": False,
        "elements": elements,
        "details": details,
    }


def _send_to_session(session_id: str, message: str) -> dict:
    state = _session(session_id)
    # 발화의 식별정보를 표식으로 바꾼다. 새 표식은 추출이 성공해야 발화와 함께 저장된다.
    pii_state = copy.deepcopy(state.get("pii") or {})
    if pii_state:
        message = pii.mask(message, pii_state)
    request = {"action": "message", "message": message, "pii": pii_state,
               "offense": _offense_from_rag(session_id, state)}

    # 추출이 실패하면 그래프는 이번 발화를 저장하지 않는다. 오류로 알리고, 다시 보내면 같은 상태에서 이어진다.
    try:
        with llm.session(session_id):
            out = CHAT_GRAPH.invoke({"request": request}, chat_config(session_id))
    except StructuredOutputError as e:
        print(f"[EXTRACT] 정보 추출 실패 session={llm.session_tag(session_id)} reason={e}")
        raise HTTPException(502, "답변을 처리하지 못했습니다. 잠시 후 다시 보내 주세요.")

    prune_session(session_id)
    collected, result = out["collected"], out["result"]
    # 사용자에게 돌려주는 글에서는 표식을 원래 값으로 되돌린다.
    return pii.unmask({
        "session_id": session_id,
        "reply": result["reply"],
        "caution": result["caution"],
        "progress": {"complete": result["complete"], "elements": collected["elements"], "details": collected["details"]},
    }, out.get("pii"))

@app.post("/chat/init")
def chat_init(req: ChatInitRequest, background_tasks: BackgroundTasks):
    if _normalize_offense(req.offense) == UNSUPPORTED:
        # 세션을 만들지 않고 LLM도 부르지 않는다. 다른 죄목의 양식으로 질문하고 초안을 쓰지 않기 위해서다.
        return {"session_id": None, "offense": UNSUPPORTED, "rag_status": "skipped", "rag_keyword": None, "rag_cases": []}

    sid = str(uuid4())
    state = _create_session(sid, req.text, req.offense, req.known_pii)
    # 판례 검색에도 표식으로 바꾼 서술을 쓴다.
    background_tasks.add_task(_load_rag_preview, sid, state["history"][0]["content"])

    return {"session_id": sid, "offense": state["offense"], **_rag(sid)}


@app.get("/chat/rag/{session_id}")
def chat_rag(session_id: str):
    state = _session(session_id)
    return {"session_id": session_id, **_rag(session_id, state.get("pii"))}


@app.post("/chat/send")
def chat_send(req: ChatMessageRequest):
    return _send_to_session(req.session_id, req.message)


@app.post("/chat/restore")
def chat_restore(req: ChatRestoreRequest, background_tasks: BackgroundTasks):
    user_messages = [
        item.content.strip()
        for item in req.history
        if item.role == "user" and item.content and item.content.strip()
    ]

    if not user_messages:
        raise HTTPException(400, "복원할 사용자 메시지가 없습니다.")

    sid = str(uuid4())
    state = _create_session(sid, user_messages[0], known_pii=req.known_pii)
    background_tasks.add_task(_load_rag_preview, sid, state["history"][0]["content"])

    last_response = None
    try:
        for message in user_messages[1:]:
            last_response = _send_to_session(sid, message)
    except HTTPException:
        # 복원 중 실패하면 반쯤 만든 세션을 남기지 않는다. 클라이언트는 session_id를 받지 못한다.
        delete_session(sid)
        raise

    return {
        "session_id": sid,
        "offense": state["offense"],
        **_rag(sid, _session(sid).get("pii")),
        "progress": last_response["progress"] if last_response
        else pii.unmask(_progress_from_session(state), state.get("pii")),
    }


def _awaiting_confirmation(session_id: str) -> bool:
    """작성이 사용자 확인을 기다리며 멈춰 있는가."""
    return CHAT_GRAPH.get_state(chat_config(session_id)).next == ("confirm",)


def _compose_response(session_id: str, out: dict) -> dict:
    """작성 결과. 초안과 검증 결과(인용, 이유) 안의 표식을 원래 값으로 되돌린다.

    verification.status: passed(근거 없는 표현 없음) | rewritten(고쳐 씀) | flagged(남아 있음)
                         | unverified(검증 호출 실패) | rewrite_failed | off
                         | awaiting_confirmation(사용자 확인을 기다림) | confirmed(사용자가 모두 사실이라고 답함)
    verification.rechecked: 고쳐 쓴 초안을 다시 검증했는가. 기본 상한(1)에서는 다시 검증하지 않으므로 False다.
    verification.to_confirm: 확인을 기다릴 때만 있다. /chat/compose/confirm에 이 순서대로 답한다.
    """
    review = out["review"]
    if _awaiting_confirmation(session_id):
        # 아직 고치지 않은 초안을 함께 돌려준다. 화면은 표현이 놓인 문맥을 보여 줄 수 있다.
        review = {**review, "status": "awaiting_confirmation", "to_confirm": claims_to_confirm(review)}
    return pii.unmask({**out["draft"], "verification": review}, out.get("pii"))


@app.post("/chat/compose")
def chat_compose(req: ComposeRequest):
    state = _session(req.session_id)
    request = {"action": "compose", "offense": _offense_from_rag(req.session_id, state)}
    # 확인을 기다리던 중에 다시 작성을 요청하면 처음부터 새로 쓴다 (기다리던 확인은 버린다).
    # 작성 호출이 실패하면 그래프는 아무것도 저장하지 않는다. 빈 초안을 돌려주지 않고 오류로 알린다.
    try:
        with llm.session(req.session_id):
            out = CHAT_GRAPH.invoke({"request": request}, chat_config(req.session_id))
    except LLMCallError as e:
        print(f"[COMPOSE] 초안 작성 실패 session={llm.session_tag(req.session_id)} reason={e}")
        raise HTTPException(502, "초안을 작성하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    prune_session(req.session_id)
    return _compose_response(req.session_id, out)


@app.post("/chat/compose/confirm")
def chat_compose_confirm(req: ComposeConfirmRequest):
    """확인을 기다리며 멈춘 작성을 사용자의 답으로 이어 간다."""
    state = _session(req.session_id)
    if not _awaiting_confirmation(req.session_id):
        raise HTTPException(409, "확인을 기다리는 초안이 없습니다. /chat/compose 먼저 호출하세요.")
    expected = len(claims_to_confirm(state["review"]))
    if len(req.answers) != expected:
        raise HTTPException(400, f"답은 {expected}개여야 합니다.")
    with llm.session(req.session_id):
        out = CHAT_GRAPH.invoke(Command(resume=req.answers), chat_config(req.session_id))
    prune_session(req.session_id)
    return _compose_response(req.session_id, out)


@app.delete("/chat/{session_id}", status_code=204)
def chat_delete(session_id: str):
    """세션의 대화와 판례 검색 상태를 모두 지운다. 없는 세션이어도 성공으로 답한다."""
    delete_session(session_id)
    return Response(status_code=204)
