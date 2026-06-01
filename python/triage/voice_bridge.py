"""
TriageAide Voice Bridge — FastAPI server (port 8003).

Exposes an OpenAI-compatible /v1/chat/completions endpoint that ElevenLabs
calls as a "Custom LLM". Handles session state, language detection, and
markdown stripping so TTS output sounds natural.
"""
import os
import re
import json
import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from agent import create_triage_agent, extract_ai_response
from voice_session import VoiceSessionStore, detect_language

_agent = None
_mcp_client = None
_store = VoiceSessionStore()

VOICE_BRIDGE_SECRET = os.getenv("VOICE_BRIDGE_SECRET", "changeme")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent, _mcp_client
    print("[VoiceBridge] Initializing triage agent (language=auto, voice_mode=True)...")
    _agent, _mcp_client = await create_triage_agent(language="auto", voice_mode=True)
    print("[VoiceBridge] Agent ready — listening on port 8003.")
    evict_task = asyncio.create_task(_evict_loop())
    yield
    evict_task.cancel()
    try:
        await evict_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="TriageAide Voice Bridge", lifespan=lifespan)
_bearer = HTTPBearer()


def _verify_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    if credentials.credentials != VOICE_BRIDGE_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.credentials


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax so ElevenLabs TTS reads clean natural text."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _evict_loop():
    while True:
        await asyncio.sleep(300)
        evicted = await _store.evict_expired()
        if evicted:
            print(f"[VoiceBridge] Evicted {evicted} expired session(s).")


class _CompletionRequest(BaseModel):
    messages: list
    stream: bool = True
    model: Optional[str] = None
    user: Optional[str] = None  # ElevenLabs passes conversation ID here


async def _sse_stream(completion_id: str, text: str):
    """Yield SSE chunks in OpenAI delta format."""
    chunk_size = 30
    for i in range(0, len(text), chunk_size):
        chunk = text[i: i + chunk_size]
        data = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "choices": [{"delta": {"content": chunk}, "index": 0, "finish_reason": None}],
        }
        yield f"data: {json.dumps(data)}\n\n"
        await asyncio.sleep(0)
    finish = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(finish)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/health")
def health():
    return {"status": "ok", "service": "triageaide-voice-bridge"}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: _CompletionRequest,
    _token: str = Depends(_verify_token),
):
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not yet initialized")

    # Resolve session ID from ElevenLabs headers or body
    session_id = (
        request.headers.get("X-EL-Conversation-Id")
        or request.headers.get("X-Conversation-Id")
        or body.user
        or str(uuid.uuid4())
    )

    session = await _store.get_or_create(session_id)

    user_msgs = [m for m in body.messages if isinstance(m, dict) and m.get("role") == "user"]
    if not user_msgs:
        raise HTTPException(status_code=400, detail="No user message in request")

    last_text = user_msgs[-1].get("content", "").strip()[:2000]

    # Detect and persist language on first user message
    if not session.language:
        detected = detect_language(last_text)
        await _store.update_language(session_id, detected)
        session.language = detected

    messages = list(session.messages)
    messages.append(HumanMessage(content=last_text))

    try:
        result = await _agent.ainvoke({"messages": messages})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(exc)[:200]}")

    updated = result.get("messages", [])
    await _store.update_messages(session_id, updated)

    ai_text = extract_ai_response(updated) or "I'm sorry, I couldn't process that request."
    ai_text = _strip_markdown(ai_text)

    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if body.stream:
        return StreamingResponse(
            _sse_stream(cid, ai_text),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return JSONResponse({
        "id": cid,
        "object": "chat.completion",
        "model": "triageaide-agent",
        "choices": [{
            "message": {"role": "assistant", "content": ai_text},
            "finish_reason": "stop",
            "index": 0,
        }],
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")
