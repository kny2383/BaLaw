"""판례 검색에서 판례를 고르는 규칙. 벡터 DB는 대역이다."""
import services.rag as rag


class _Collection:
    """서술과 가까운 순서로 정해진 판례를 돌려준다."""

    def __init__(self, labels):
        self.metas = [{"case_no": f"case-{i}", "label": label, "summary": "", "facts": f"사실 {i}"}
                      for i, label in enumerate(labels)]

    def query(self, query_texts, n_results):
        metas = self.metas[:n_results]
        return {"ids": [[m["case_no"] for m in metas]], "metadatas": [metas],
                "distances": [[0.1 * (i + 1) for i in range(len(metas))]]}


def _search(monkeypatch, labels, keyword="사기", k=2):
    monkeypatch.setattr(rag, "get_collection", lambda: _Collection(labels))
    return [c["label"] for c in rag.search_similar_cases_filtered("서술", keyword, k=k)]


def test_crime_name_is_matched_as_a_name_not_as_letters():
    assert rag.is_crime("사기", "사기") and rag.is_crime("상습사기", "사기") and rag.is_crime("컴퓨터등사용사기", "사기")
    assert rag.is_crime("업무상횡령", "횡령") and rag.is_crime("상관 명예훼손", "명예훼손")
    assert not rag.is_crime("군사기밀보호법위반", "사기"), "글자만 보면 '사기'가 들어 있다"
    assert not rag.is_crime("조세를 포탈한 행위는 사기나 그 밖의 부정한 행위에 해당함", "사기")
    # 라벨에 실제로 있는 형태: 괄호로 덧붙인 말, 가운뎃점으로 이은 죄명
    assert rag.is_crime("사기{인정된죄명:특정경제범죄가중처벌등에관한법률위반}", "사기") and rag.is_crime("사기[피고인1", "사기")
    assert rag.is_crime("특정경제범죄가중처벌등에관한법률위반·사기", "사기")
    assert rag.is_crime("아동·청소년의성보호에관한법률위반", "아동·청소년의성보호에관한법률위반")
    assert not rag.is_crime("보험사기방지특별법위반", "사기"), "다른 법 위반이다. 의도한 제외"


def test_cases_about_only_that_crime_come_first(monkeypatch):
    """예전에는 가까운 순서대로만 골라, 마약·교통 사건에 사기가 덧붙은 판례가 앞에 왔다."""
    labels = ["마약류관리에관한법률위반, 사기", "교통사고처리특례법위반, 도로교통법위반, 사기", "사기", "상습사기", "사기"]
    assert _search(monkeypatch, labels) == ["사기", "상습사기"]


def test_mixed_cases_fill_in_when_pure_ones_run_out(monkeypatch):
    labels = ["배임, 사기", "사기", "유기치사, 사기"]
    assert _search(monkeypatch, labels) == ["사기", "배임, 사기"]  # 모자라면 섞인 판례 중 가까운 것


def test_look_alike_labels_are_not_returned(monkeypatch):
    assert _search(monkeypatch, ["군사기밀보호법위반", "횡령"]) == []


def test_keyword_etc_keeps_similarity_order(monkeypatch):
    labels = ["횡령", "사기", "폭행"]
    assert _search(monkeypatch, labels, keyword="기타") == ["횡령", "사기"]


def test_keyword_candidates_that_matter_still_find_cases():
    """죄명 키워드와 판례 라벨의 죄명이 같은 말로 끝나야 걸린다. 지원 죄목과 평가 사례의 죄명으로 확인한다."""
    assert rag.is_crime("사기", "사기") and rag.is_crime("모욕", "모욕") and rag.is_crime("명예 훼손", "명예훼손")
    assert not rag.is_crime("사기", "컴퓨터등사용사기"), "더 좁은 죄명을 찾을 때 넓은 죄명의 판례는 고르지 않는다"


def test_middle_dot_label_with_other_crimes_is_not_pure(monkeypatch):
    """가운뎃점으로 여러 죄명을 이은 라벨은 쉼표가 없어도 한 죄목만 다룬 판례가 아니다."""
    joined = "특정금융거래정보의보고및이용등에관한법률위반·외국환거래법위반·사기·배상명령신청"
    assert rag.is_crime(joined, "사기") and not rag.is_only_crime(joined, "사기")
    assert rag.is_only_crime("사기·상습사기", "사기") and rag.is_only_crime("사기{인정된죄명:특경법위반}", "사기")
    assert rag.is_only_crime("아동·청소년의성보호에관한법률위반", "아동·청소년의성보호에관한법률위반")
    assert _search(monkeypatch, [joined, "사기"], k=2) == ["사기", joined]


def test_summary_keeps_the_retrieved_case_number_and_label():
    """LLM이 다른 사건번호나 죄명을 돌려줘도 검색 결과의 값을 쓴다."""
    case = {"case_no": "2020도1", "label": "사기", "summary": "", "facts": "사실"}
    out = rag._normalize_case_summary(case, {"case_no": "9999도9999", "label": "살인", "summary": "요약", "result": "유죄"})
    assert out == {"case_no": "2020도1", "label": "사기", "summary": "요약", "result": "유죄"}
