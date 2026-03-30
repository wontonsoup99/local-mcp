"""HTTP API: POST /chat runs one agent turn (Ollama + remote MCP)."""

from __future__ import annotations

import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent_service.agent import run_agent_turn
from agent_service.config import get_settings
from agent_service.errors import format_exception_chain
from agent_service.mcp_transport import mcp_client_session

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Ollama MCP Agent", version="0.1.0")


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, description="User message for this turn.")
    system: str | None = Field(
        default=None,
        description="Optional system prompt for this request only.",
    )


class ChatResponse(BaseModel):
    reply: str


@app.get("/", response_class=None)
async def index() -> str:
    """Very basic web UI (no auth, calls POST /chat)."""
    return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ollama MCP Agent</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 24px; }
      textarea { width: 100%; max-width: 900px; min-height: 120px; padding: 10px; }
      button { padding: 10px 14px; margin-top: 12px; cursor: pointer; }
      pre { background: #0b1020; color: #e6edf3; padding: 12px; border-radius: 8px; max-width: 900px; overflow-x: auto; }
      .row { margin-top: 10px; }
      .muted { color: #667085; font-size: 14px; }
    </style>
  </head>
  <body>
    <h1>Ollama MCP Agent</h1>
    <p class="muted">POSTs to <code>/chat</code>. Uses your configured MCP + Ollama.</p>

    <div class="row">
      <label for="message"><b>Message</b></label><br/>
      <textarea id="message" placeholder="e.g. What are my most active customers, and their most recent purchase history?"></textarea>
    </div>

    <div class="row">
      <button onclick="send()">Send</button>
      <div id="status" class="muted"></div>
    </div>

    <div class="row">
      <b>Reply</b>
      <pre id="reply">(no response yet)</pre>
    </div>

    <script>
      async function send() {
        const msg = document.getElementById('message').value.trim();
        const status = document.getElementById('status');
        const reply = document.getElementById('reply');
        if (!msg) { status.textContent = 'Enter a message first.'; return; }
        status.textContent = 'Thinking...';
        reply.textContent = '(working...)';
        try {
          const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
          });
          const data = await res.json();
          if (!res.ok) {
            reply.textContent = (data && data.detail) ? data.detail : 'Request failed';
          } else {
            reply.textContent = data.reply;
          }
          status.textContent = res.ok ? '' : 'Error';
        } catch (e) {
          status.textContent = 'Network/error';
          reply.textContent = String(e);
        }
      }
    </script>
  </body>
</html>
"""


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/mcp")
async def health_mcp() -> dict[str, str | list[str]]:
    """Optional MCP probe. Set EXPOSE_MCP_HEALTHCHECK=1. Does not print secret values."""
    settings = get_settings()
    if not settings.expose_mcp_healthcheck:
        raise HTTPException(status_code=404, detail="Set EXPOSE_MCP_HEALTHCHECK=1 to enable")
    hdrs = settings.merged_mcp_headers()
    keys = sorted(hdrs.keys())
    try:
        async with mcp_client_session(settings) as mcp_session:
            tools = await mcp_session.list_tools()
            names = [t.name for t in tools.tools]
    except Exception as exc:
        detail = format_exception_chain(exc)
        logger.exception("MCP healthcheck failed: %s", detail)
        raise HTTPException(
            status_code=503,
            detail={"error": detail, "header_keys_sent": keys},
        ) from exc
    return {"status": "ok", "tools": names, "header_keys_sent": keys}


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatBody) -> ChatResponse:
    settings = get_settings()
    try:
        async with mcp_client_session(settings) as mcp_session:
            reply = await run_agent_turn(
                settings=settings,
                session=mcp_session,
                user_message=body.message,
                system_prompt=body.system,
            )
    except Exception as exc:
        detail = format_exception_chain(exc)
        logger.exception(
            "Chat request failed: %s (MCP header keys: %s)",
            detail,
            sorted(settings.merged_mcp_headers().keys()),
        )
        raise HTTPException(status_code=502, detail=detail) from exc
    return ChatResponse(reply=reply)


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "agent_service.main:app",
        host=settings.bind_host,
        port=settings.bind_port,
        factory=False,
        log_level=os.environ.get("UVICORN_LOG_LEVEL", "info"),
    )


def main() -> None:
    run()


if __name__ == "__main__":
    main()
