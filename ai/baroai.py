from fastapi import BackgroundTasks, HTTPException, Response
from uuid import uuid4
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal, Optional
from cfg import settings
from flow.chat_graph import build_chat_graph
from flow.checkpoint import chat_config, delete_session, prune_session, rag_config
from flow.rag_graph import build_rag_graph, failed_result
from services.openai_client import StructuredOutputError
from services.rag import map_keyword_to_offense
from services.rag_bootstrap import ensure_rag_resources

app = FastAPI(title="BARO-AI: Complaint Draft API", version="0.1.0")


@app.on_event("startup")
async def startup_event():
    """서비스 시작 시 RAG DB 준비"""
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

class ChatInitRequest(BaseModel):
    text: str
    offense: Optional[str] = None

class ChatMessageRequest(BaseModel):
    session_id: str
    message: str

class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRestoreRequest(BaseModel):
    history: list[ChatHistoryItem]

@app.get("/")
def health():
    return {"ok": True, "service": app.title, "model": settings.OPENAI_CHAT_MODEL}


def _normalize_offense(offense: Optional[str]) -> Optional[str]:
    if not offense:
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

    return offense_map.get(normalized, "fraud")


def _session(session_id: str) -> dict:
    """세션의 현재 대화 상태. 없으면 404."""
    values = CHAT_GRAPH.get_state(chat_config(session_id)).values
    if not values:
        raise HTTPException(404, "세션을 찾을 수 없습니다. /chat/init 먼저 호출하세요.")
    return values


def _rag(session_id: str) -> dict:
    """판례 검색 상태. 아직 끝나지 않았으면 pending."""
    result = RAG_GRAPH.get_state(rag_config(session_id)).values.get("result") or {}
    return {
        "rag_status": result.get("status", "pending"),
        "rag_keyword": result.get("keyword"),
        "rag_cases": result.get("cases") or [],
    }


def _offense_from_rag(session_id: str, state: dict):
    """죄목을 직접 고르지 않은 세션은 판례 검색이 끝나면 그 키워드로 양식을 정한다."""
    if state.get("offense_selected"):
        return None
    rag = _rag(session_id)
    if rag["rag_status"] != "ready":
        return None
    return map_keyword_to_offense(rag["rag_keyword"])


def _create_session(session_id: str, text: str, offense: Optional[str] = None) -> dict:
    selected_offense = _normalize_offense(offense)
    return CHAT_GRAPH.invoke(
        {"request": {
            "action": "init",
            "text": text,
            "offense": selected_offense or "fraud",
            "offense_selected": bool(selected_offense),
        }},
        chat_config(session_id),
    )


def _load_rag_preview(session_id: str, text: str) -> None:
    config = rag_config(session_id)
    try:
        RAG_GRAPH.invoke({"request": {"text": text}}, config)
    except Exception as e:
        # 어느 단계에서 실패했든 마지막 노드의 결과로 실패 상태를 남긴다 (실행을 이어 가지 않는다).
        print(f"[RAG] 판례 검색 실패 session={session_id} reason={type(e).__name__}")
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
    request = {"action": "message", "message": message, "offense": _offense_from_rag(session_id, state)}

    # 추출이 실패하면 그래프는 이번 발화를 저장하지 않는다. 오류로 알리고, 다시 보내면 같은 상태에서 이어진다.
    try:
        out = CHAT_GRAPH.invoke({"request": request}, chat_config(session_id))
    except StructuredOutputError as e:
        print(f"[EXTRACT] 정보 추출 실패 session={session_id} reason={e}")
        raise HTTPException(502, "답변을 처리하지 못했습니다. 잠시 후 다시 보내 주세요.")

    prune_session(session_id)
    collected, result = out["collected"], out["result"]
    return {
        "session_id": session_id,
        "reply": result["reply"],
        "caution": result["caution"],
        "progress": {"complete": result["complete"], "elements": collected["elements"], "details": collected["details"]},
    }

@app.post("/chat/init")
def chat_init(req: ChatInitRequest, background_tasks: BackgroundTasks):
    sid = str(uuid4())
    state = _create_session(sid, req.text, req.offense)
    background_tasks.add_task(_load_rag_preview, sid, req.text)

    return {"session_id": sid, "offense": state["offense"], **_rag(sid)}


@app.get("/chat/rag/{session_id}")
def chat_rag(session_id: str):
    _session(session_id)
    return {"session_id": session_id, **_rag(session_id)}


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
    state = _create_session(sid, user_messages[0])
    background_tasks.add_task(_load_rag_preview, sid, user_messages[0])

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
        **_rag(sid),
        "progress": last_response["progress"] if last_response else _progress_from_session(state),
    }


@app.post("/chat/compose")
def chat_compose(req: ComposeRequest):
    state = _session(req.session_id)
    request = {"action": "compose", "offense": _offense_from_rag(req.session_id, state)}
    out = CHAT_GRAPH.invoke({"request": request}, chat_config(req.session_id))
    prune_session(req.session_id)
    return out["draft"]


@app.delete("/chat/{session_id}", status_code=204)
def chat_delete(session_id: str):
    """세션의 대화와 판례 검색 상태를 모두 지운다. 없는 세션이어도 성공으로 답한다."""
    delete_session(session_id)
    return Response(status_code=204)
