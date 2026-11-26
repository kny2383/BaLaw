"""판례 검색에서 판례를 고르는 규칙과 요약의 사건번호. 벡터 DB와 LLM은 대역이다."""
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


def test_summary_keeps_the_retrieved_case_number_and_label():
    """LLM이 다른 사건번호나 죄명을 돌려줘도 검색 결과의 값을 쓴다."""
    case = {"case_no": "2020도1", "label": "사기", "summary": "", "facts": "사실"}
    out = rag._normalize_case_summary(case, {"case_no": "9999도9999", "label": "살인", "summary": "요약", "result": "유죄"})
    assert out == {"case_no": "2020도1", "label": "사기", "summary": "요약", "result": "유죄"}
