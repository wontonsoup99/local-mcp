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
from agent_service.prompts import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

def _looks_like_store_data_question(user_message: str) -> bool:
    """Heuristic: if the user asks about store data, we should not answer without tool results."""
    msg = (user_message or "").lower()
    keywords = (
        "customer",
        "customers",
        "order",
        "orders",
        "purchase",
        "purchases",
        "history",
        "sales",
        "revenue",
        "product",
        "products",
        "inventory",
        "subscriber",
        "subscription",
        "active",
        "top",
    )
    return any(k in msg for k in keywords)

def _extract_json_tool_calls(text: str) -> list[dict[str, Any]] | None:
    """Parse a strict JSON object containing tool calls from model text."""
    if not text:
        return None
    raw = text.strip()
    if not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None

    # Accept a couple common keys.
    tool_calls = data.get("tool_calls") or data.get("toolCalls") or data.get("calls") or data.get("ToolCalls")
    if not isinstance(tool_calls, list):
        return None

    out: list[dict[str, Any]] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        args = item.get("arguments") if "arguments" in item else item.get("args")
        if not isinstance(name, str) or not name:
            continue
        if args is None:
            args = {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        out.append({"name": name, "arguments": args})
    return out or None


def resolve_system_prompt(settings: Settings, override: str | None) -> str:
    """Per-request override, then env SYSTEM_PROMPT, then default admin prompt."""
    if override is not None and override.strip():
        return override.strip()
    if settings.system_prompt and str(settings.system_prompt).strip():
        return str(settings.system_prompt).strip()
    return DEFAULT_SYSTEM_PROMPT


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
    available_tool_names = {t.name for t in listed.tools}
    tool_defs_by_name = {t.name: t for t in listed.tools}
    if not tools:
        logger.warning("MCP server returned no tools; model will run without tools.")

    messages: list[ChatCompletionMessageParam] = []
    messages.append(
        {"role": "system", "content": resolve_system_prompt(settings, system_prompt)},
    )
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
            # If the model didn't call tools on a data-heavy question, force one more try
            # with an explicit instruction to call the OpenShop `oshop_*` tools now.
            if round_idx == 0 and tools and _looks_like_store_data_question(user_message):
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You must use the provided OpenShop `oshop_*` tools to answer this store-data question. "
                            "Do not propose the plan. If you cannot use automatic tool calls, output a JSON object only:\n"
                            '{ "tool_calls": [ { "name": "oshop_list_customers", "arguments": { } } ] }\n'
                            "Then stop. I will execute the tools and provide results."
                        ),
                    }
                )
                continue
            # Second chance: if the model outputs JSON tool calls, execute them.
            if (
                round_idx == 1
                and tools
                and _looks_like_store_data_question(user_message)
                and msg.content
            ):
                parsed = _extract_json_tool_calls(msg.content)
                if parsed:
                    for idx, tc in enumerate(parsed):
                        name = tc["name"]
                        args = tc["arguments"]

                        if name not in available_tool_names:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": f"json-{idx}",
                                    "content": f"Invalid tool requested: '{name}'.",
                                }
                            )
                            continue

                        # Required arg validation (same as below).
                        tool_def = tool_defs_by_name.get(name)
                        required_fields: list[str] = []
                        if tool_def and getattr(tool_def, "inputSchema", None):
                            schema_obj = tool_def.inputSchema
                            if isinstance(schema_obj, dict):
                                req = schema_obj.get("required")
                                if isinstance(req, list):
                                    required_fields = [str(x) for x in req if x is not None]

                        missing_required = [
                            f
                            for f in required_fields
                            if (f not in args) or args.get(f) is None
                        ]
                        if missing_required:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": f"json-{idx}",
                                    "content": (
                                        f"Cannot call tool '{name}' because missing/null required argument(s): "
                                        f"{', '.join(missing_required)}."
                                    ),
                                }
                            )
                            continue

                        try:
                            tr = await session.call_tool(name, args)
                            text = _format_tool_result(tr)
                        except Exception as exc:
                            text = f"Tool error: {exc!s}"

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": f"json-{idx}",
                                "content": text,
                            }
                        )
                    # After executing tool calls (from JSON), ask the model to answer.
                    continue

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
            if name not in available_tool_names:
                # Keep the agent "in sync" with the MCP server's actual tool list.
                # If the model hallucinates a tool name, we do not execute it.
                text = (
                    f"Invalid tool requested by the model: '{name}'. "
                    f"Available tools are: {', '.join(sorted(available_tool_names))}"
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": text,
                    }
                )
                continue
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON tool arguments from model; using empty dict.")
                args = {}

            # Guardrail: validate required arguments using the tool's JSON schema.
            # This prevents calling get_* tools with missing/null IDs (a common failure mode).
            tool_def = tool_defs_by_name.get(name)
            required_fields: list[str] = []
            if tool_def and getattr(tool_def, "inputSchema", None):
                schema_obj = tool_def.inputSchema
                if isinstance(schema_obj, dict):
                    req = schema_obj.get("required")
                    if isinstance(req, list):
                        required_fields = [str(x) for x in req if x is not None]

            missing_required = [
                f
                for f in required_fields
                if (f not in args) or args.get(f) is None
            ]
            if missing_required:
                text = (
                    f"Cannot call tool '{name}' because required argument(s) are missing/null: "
                    f"{', '.join(missing_required)}. "
                    "Use the available list_* tools to obtain those IDs/values first, then retry."
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": text,
                    }
                )
                continue
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

    # Tool-round budget exhausted. Ask the model to produce an answer based on
    # the tool results we already have (without requesting further tool calls).
    final = await oai.chat.completions.create(
        model=settings.ollama_model,
        messages=messages,
    )
    return (final.choices[0].message.content or "").strip() or ""
