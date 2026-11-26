"""식별정보 치환(S05) 테스트. LLM은 가짜 서버가 대신하고, 가짜 서버가 받은 요청을 훑어 원문이 없는지 본다."""
import json

from cfg import settings
from services import pii

NAME, ADDRESS = "남가상", "서울 가상구 가상로 5"
PHONE, PHONE_DIGITS, ACCOUNT = "010-1111-2222", "01033334444", "3333-01-2345678"
NARRATIVE = f"집주인 {NAME}이 보증금을 안 돌려줍니다. 연락처는 {PHONE}이고 {ADDRESS}에 삽니다."
MESSAGE = f"2026-02-01에 카뱅 {ACCOUNT}로 보냈고 다른 번호는 {PHONE_DIGITS}입니다."
RAW = [NAME, ADDRESS, PHONE, PHONE_DIGITS, ACCOUNT]
KNOWN = {"names": [NAME], "addresses": [ADDRESS]}


# ---------- 치환 규칙 ----------
def test_mask_and_unmask_round_trip():
    state = pii.new_state(KNOWN)
    text = NARRATIVE + " " + MESSAGE
    masked = pii.mask(text, state)
    assert not any(v in masked for v in RAW)
    assert masked.count("[전화번호") == 2 and "[계좌번호1]" in masked and "[이름1]" in masked and "[주소1]" in masked
    assert pii.unmask(masked, state) == text


def test_dates_and_amounts_are_kept():
    state = pii.new_state()
    text = "2026-02-01에 1,200,000원을 보냈고 2026. 5. 3.에 30만원을 더 보냈습니다."
    assert pii.mask(text, state) == text and state["tokens"] == {}


def test_same_value_gets_the_same_token():
    state = pii.new_state()
    first = pii.mask(f"번호는 {PHONE}", state)
    second = pii.mask(f"다시 말하면 {PHONE}요", state)
    assert "[전화번호1]" in first and "[전화번호1]요" in second and len(state["tokens"]) == 1


def test_unmask_goes_into_lists_and_dicts():
    state = pii.new_state()
    pii.mask(PHONE, state)
    assert pii.unmask({"a": ["[전화번호1]로 연락", 3], "b": None}, state) == {"a": [f"{PHONE}로 연락", 3], "b": None}


def test_unknown_token_is_left_alone():
    assert pii.unmask("[이름9]에게", {"known": {}, "tokens": {"[이름1]": NAME}}) == "[이름9]에게"


# ---------- API: LLM 요청에는 표식만, 응답에는 원래 값 ----------
def _sent_to_llm(fake) -> str:
    return json.dumps([r["body"] for r in fake.requests], ensure_ascii=False)


def _conversation(client, fake):
    sid = client.post("/chat/init", json={"text": NARRATIVE, "offense": "사기", "known_pii": KNOWN}).json()["session_id"]
    assert client.post("/chat/send", json={"session_id": sid, "message": MESSAGE}).status_code == 200
    fake.compose_text = ("=== 범죄사실 ===\n○ 고소인은 [이름1]의 계좌 [계좌번호1]로 송금하였습니다.\n\n"
                         "=== 고소이유 ===\n○ [이름1]의 연락처는 [전화번호1]입니다.\n")
    return sid, client.post("/chat/compose", json={"session_id": sid}).json()


def test_llm_requests_carry_tokens_not_raw_values(client, fake):
    _conversation(client, fake)
    sent = _sent_to_llm(fake)
    assert len(fake.requests) >= 3  # 죄명 키워드, 추출, 작성 등
    assert [v for v in RAW if v in sent] == []
    assert "[이름1]" in sent and "[전화번호1]" in sent and "[계좌번호1]" in sent and "[주소1]" in sent
    assert "표식은 가려 둔 실제 값" in sent


def test_response_gets_the_original_values_back(client, fake):
    _, draft = _conversation(client, fake)
    assert draft["sections"]["criminal_facts"] == f"○ 고소인은 {NAME}의 계좌 {ACCOUNT}로 송금하였습니다."
    assert draft["sections"]["accusation_reason"] == f"○ {NAME}의 연락처는 {PHONE}입니다."


def test_session_state_holds_tokens_only(client, fake):
    import baroai
    from flow.checkpoint import chat_config

    sid, _ = _conversation(client, fake)
    state = baroai.CHAT_GRAPH.get_state(chat_config(sid)).values
    without_map = {k: v for k, v in state.items() if k != "pii"}
    assert [v for v in RAW if v in json.dumps(without_map, ensure_ascii=False)] == []
    assert set(state["pii"]["tokens"].values()) == set(RAW)


def test_failed_turn_does_not_break_token_numbering(client, fake):
    """추출이 실패한 발화의 표식은 저장되지 않는다. 다시 보내면 같은 표식이 붙는다."""
    sid = client.post("/chat/init", json={"text": "사건 개요", "offense": "사기"}).json()["session_id"]
    fake.fail_extract = True
    assert client.post("/chat/send", json={"session_id": sid, "message": MESSAGE}).status_code == 502
    fake.fail_extract = False
    assert client.post("/chat/send", json={"session_id": sid, "message": MESSAGE}).status_code == 200
    sent = fake.requests[-1]["body"]["messages"][-1]["content"]
    assert "[계좌번호1]" in sent and "[계좌번호2]" not in sent and ACCOUNT not in sent


def test_masking_can_be_turned_off(client, fake, monkeypatch):
    """끄면 원문이 그대로 나간다 (위 검사가 실제로 원문을 찾아낸다는 확인이기도 하다)."""
    monkeypatch.setattr(settings, "PII_MASKING", False)
    client.post("/chat/init", json={"text": NARRATIVE, "offense": "사기", "known_pii": KNOWN})
    assert PHONE in _sent_to_llm(fake) and "[전화번호1]" not in _sent_to_llm(fake)


def test_verify_and_rewrite_requests_carry_tokens_and_quotes_are_restored(client, fake):
    """초안 검증과 재작성 호출에도 표식만 나가고, 응답의 검증 결과에서는 원래 값으로 돌아온다."""
    sid = client.post("/chat/init", json={"text": NARRATIVE, "offense": "사기", "known_pii": KNOWN}).json()["session_id"]
    client.post("/chat/send", json={"session_id": sid, "message": MESSAGE})
    fake.compose_text = ("=== 범죄사실 ===\n○ 고소인은 [이름1]의 계좌 [계좌번호1]로 송금하였습니다.\n\n"
                         "=== 고소이유 ===\n○ 수사를 요청합니다.\n")
    fake.verify_results = [["[이름1]의 계좌 [계좌번호1]로"]]
    fake.requests.clear()
    body = client.post("/chat/compose", json={"session_id": sid}).json()
    sent = _sent_to_llm(fake)
    assert len(fake.requests) == 3  # 작성, 검증, 재작성
    assert [v for v in RAW if v in sent] == []
    assert body["verification"]["status"] == "rewritten"
    assert body["verification"]["removed"][0]["quote"] == f"{NAME}의 계좌 {ACCOUNT}로"
