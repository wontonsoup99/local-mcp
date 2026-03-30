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
                system_prompt=body.system or settings.system_prompt,
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
