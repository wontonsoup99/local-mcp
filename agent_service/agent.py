"""Tool-use loop: Ollama (OpenAI-compatible) + MCP tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.types import CallToolResult, TextContent
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from agent_service.config import Settings

logger = logging.getLogger(__name__)


def _mcp_tools_to_openai(tools_response: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tools_response.tools:
        schema = t.inputSchema if t.inputSchema else {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "").strip() or f"MCP tool {t.name}",
                    "parameters": schema,
                },
            }
        )
    return out


def _format_tool_result(result: CallToolResult) -> str:
    lines: list[str] = []
    if result.isError:
        lines.append("Error from tool execution.")
    for block in result.content:
        if isinstance(block, TextContent):
            lines.append(block.text)
        else:
            lines.append(str(block))
    if result.structuredContent:
        lines.append(json.dumps(result.structuredContent, default=str))
    return "\n".join(lines) if lines else "(empty tool result)"


async def run_agent_turn(
    *,
    settings: Settings,
    session: ClientSession,
    user_message: str,
    system_prompt: str | None = None,
) -> str:
    """One user turn: chat completions with MCP tools until the model responds without tool calls."""
    oai = AsyncOpenAI(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
    )

    listed = await session.list_tools()
    tools = _mcp_tools_to_openai(listed)
    if not tools:
        logger.warning("MCP server returned no tools; model will run without tools.")

    messages: list[ChatCompletionMessageParam] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message})

    for round_idx in range(settings.max_tool_rounds):
        kwargs: dict[str, Any] = {
            "model": settings.ollama_model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        completion = await oai.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            return (msg.content or "").strip() or ""

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
        )

        for tc in msg.tool_calls:
            fn = tc.function
            name = fn.name
            raw = fn.arguments or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON tool arguments from model; using empty dict.")
                args = {}
            try:
                tr = await session.call_tool(name, args)
                text = _format_tool_result(tr)
            except Exception as exc:
                logger.exception("MCP tool call failed: %s", name)
                text = f"Tool error: {exc!s}"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": text,
                }
            )

        if round_idx == settings.max_tool_rounds - 1:
            final = await oai.chat.completions.create(
                model=settings.ollama_model,
                messages=messages,
            )
            return (final.choices[0].message.content or "").strip() or ""

    return ""
