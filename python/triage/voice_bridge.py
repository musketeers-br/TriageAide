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
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from agent import create_triage_agent, extract_ai_response
from voice_session import VoiceSessionStore, detect_language
from logging_config import setup_logging

logger = setup_logging("voice_bridge", "voice_bridge.log")

_agent = None
_mcp_client = None
_store = VoiceSessionStore()

VOICE_BRIDGE_SECRET = os.getenv("VOICE_BRIDGE_SECRET", "changeme")
logger.info("VOICE_BRIDGE_SECRET loaded (%s)", "default" if VOICE_BRIDGE_SECRET == "changeme" else f"{len(VOICE_BRIDGE_SECRET)} chars")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent, _mcp_client
    logger.info("Initializing triage agent (language=auto, voice_mode=True)...")
    max_retries = 6
    for attempt in range(1, max_retries + 1):
        try:
            _agent, _mcp_client = await create_triage_agent(language="auto", voice_mode=True, cache_namespace="voice")
            logger.info("Agent ready — listening on port 8003.")
            break
        except Exception as e:
            logger.warning("Agent init attempt %d/%d failed: %s", attempt, max_retries, str(e)[:300])
            if attempt == max_retries:
                logger.error("Agent init failed after %d attempts — voice bridge will return 503", max_retries)
                break
            await asyncio.sleep(5)
    evict_task = asyncio.create_task(_evict_loop())
    yield
    evict_task.cancel()
    try:
        await evict_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="TriageAide Voice Bridge", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.now(timezone.utc)
    req_id = uuid.uuid4().hex[:8]
    logger.info("[%s] --> %s %s", req_id, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("[%s] !!! Unhandled exception", req_id)
        raise
    elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000
    logger.info("[%s] <-- %s %s => %d (%.0fms)", req_id, request.method, request.url.path, response.status_code, elapsed)
    return response

_bearer = HTTPBearer()


def _verify_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    if credentials.credentials != VOICE_BRIDGE_SECRET:
        logger.warning("Auth failed: provided=%s..., expected=%s chars",
                       credentials.credentials[:6] if len(credentials.credentials) >= 6 else credentials.credentials,
                       len(VOICE_BRIDGE_SECRET))
        raise HTTPException(status_code=401, detail="Unauthorized")
    logger.debug("Auth OK")
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
            logger.info("Evicted %d expired session(s).", evicted)


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


_WIDGET_HTML = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TriageAide Voice</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f172a;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      font-family: system-ui, -apple-system, sans-serif;
      color: #f1f5f9;
    }}
    .header {{
      text-align: center;
      margin-bottom: 24px;
    }}
    .header h1 {{ font-size: 18px; font-weight: 600; color: #94a3b8; }}
    .widget-container {{ width: 100%; max-width: 480px; padding: 0 16px; }}
    .no-agent {{
      text-align: center;
      padding: 48px 24px;
      color: #64748b;
      border: 1px dashed #334155;
      border-radius: 12px;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>🏥 TriageAide Voice / Triagem por Voz</h1>
  </div>
  <div class="widget-container">
    {widget_content}
  </div>
  <script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async type="text/javascript"></script>
</body>
</html>
"""


@app.get("/widget", response_class=HTMLResponse)
async def widget_page(agent_id: str = ""):
    """Standalone HTML page containing the ElevenLabs widget — safe for iframe embedding."""
    if not agent_id:
        agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")

    if agent_id:
        widget_content = f'<elevenlabs-convai agent-id="{agent_id}" style="width:100%;"></elevenlabs-convai>'
    else:
        widget_content = (
            '<div class="no-agent">'
            '<p>No Agent ID configured.<br>Set <code>ELEVENLABS_AGENT_ID</code> or pass <code>?agent_id=</code></p>'
            '</div>'
        )

    return HTMLResponse(content=_WIDGET_HTML.format(widget_content=widget_content))


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: _CompletionRequest,
    _token: str = Depends(_verify_token),
):
    if _agent is None:
        logger.error("Agent not initialized — returning 503")
        raise HTTPException(status_code=503, detail="Agent not yet initialized")

    session_id = (
        request.headers.get("X-EL-Conversation-Id")
        or request.headers.get("X-Conversation-Id")
        or body.user
        or str(uuid.uuid4())
    )
    logger.info("session=%s | user_msg_count=%d | stream=%s | model=%s",
                session_id[:12], len(body.messages), body.stream, body.model)

    session = await _store.get_or_create(session_id)

    user_msgs = [m for m in body.messages if isinstance(m, dict) and m.get("role") == "user"]
    if not user_msgs:
        logger.warning("session=%s | No user message in request body", session_id[:12])
        raise HTTPException(status_code=400, detail="No user message in request")

    last_text = user_msgs[-1].get("content", "").strip()[:2000]
    logger.debug("session=%s | User text: %.80s%s", session_id[:12], last_text, "..." if len(last_text) > 80 else "")

    if not session.language:
        detected = detect_language(last_text)
        await _store.update_language(session_id, detected)
        session.language = detected
        logger.info("session=%s | Language detected: %s", session_id[:12], detected)

    messages = list(session.messages)
    messages.append(HumanMessage(content=last_text))
    logger.debug("session=%s | Invoking agent with %d messages", session_id[:12], len(messages))

    try:
        result = await _agent.ainvoke({"messages": messages})
    except Exception as exc:
        logger.exception("session=%s | Agent invocation failed", session_id[:12])
        raise HTTPException(status_code=500, detail=f"Agent error: {str(exc)[:200]}")

    updated = result.get("messages", [])
    await _store.update_messages(session_id, updated)

    ai_text = extract_ai_response(updated) or "I'm sorry, I couldn't process that request."
    ai_text = _strip_markdown(ai_text)
    logger.info("session=%s | Agent response: %d chars", session_id[:12], len(ai_text))

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
    logger.info("Starting Voice Bridge on port 8003...")
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")
