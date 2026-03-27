#!/usr/bin/env python3
"""
Probe OpenShop / remote MCP auth: try several header patterns and report HTTP status.

Run from repo root with venv active:
  export $(grep -v '^#' .env | xargs)  # optional: load .env in shell
  python scripts/probe_mcp_auth.py

Or pass secrets via env for one-off tests (do not commit):
  OPENSHOP_PROBE_KEY=... OPENSHOP_PROBE_SLUG=... python scripts/probe_mcp_auth.py

Does not print header values, only names and status codes.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Repo root on path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx

# Minimal JSON-RPC initialize (streamable HTTP servers often expect POST + JSON)
_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-probe", "version": "0.1"},
    },
}


async def _post(url: str, headers: dict[str, str]) -> tuple[int, str | None, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **headers,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=h, json=_INIT_BODY)
        www = r.headers.get("www-authenticate")
        return r.status_code, www, (r.text or "")[:200]


async def main() -> None:
    os.chdir(_ROOT)
    from agent_service.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    url = settings.mcp_url
    key = os.environ.get("OPENSHOP_PROBE_KEY", "").strip()
    slug = os.environ.get("OPENSHOP_PROBE_SLUG", "").strip()

    print(f"MCP_URL={url}")
    print(f"Transport hint: {settings.mcp_transport}")
    merged = settings.merged_mcp_headers()
    print(f"Current merged headers (from .env): {list(merged.keys()) or '(none)'}")

    variants: list[tuple[str, dict[str, str]]] = []

    if merged:
        variants.append(("merged_mcp_headers (from Settings)", merged))

    if key:
        variants.extend(
            [
                ("Bearer OPENSHOP_PROBE_KEY", {"Authorization": f"Bearer {key}"}),
                ("X-API-Key", {"X-API-Key": key}),
                ("x-api-key lowercase", {"x-api-key": key}),
                ("Authorization: ApiKey", {"Authorization": f"ApiKey {key}"}),
                ("Authorization: Token", {"Authorization": f"Token {key}"}),
            ]
        )
        if slug:
            base = [
                ("Bearer + X-Store-Slug", {"Authorization": f"Bearer {key}", "X-Store-Slug": slug}),
                ("X-API-Key + X-Store-Slug", {"X-API-Key": key, "X-Store-Slug": slug}),
                ("X-API-Key + X-OpenShop-Store", {"X-API-Key": key, "X-OpenShop-Store": slug}),
                ("Bearer + store slug alternate", {"Authorization": f"Bearer {key}", "X-OpenShop-Store-Slug": slug}),
            ]
            variants.extend(base)

    if not variants:
        print(
            "\nNo headers to try. Set MCP_* in .env or export OPENSHOP_PROBE_KEY=... (and optionally OPENSHOP_PROBE_SLUG=...).",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nPOST initialize:\n")
    for name, hdrs in variants:
        code, www, body = await _post(url, hdrs)
        extra = f"  www-authenticate: {www}" if www else ""
        print(f"  {code}  {name}{extra}")
        if code != 401 and body:
            print(f"       body: {body.replace(chr(10), ' ')[:200]}")

    print(
        "\nIf you see www-authenticate: Bearer resource_metadata=... the MCP server is "
        "RFC 9728 OAuth-protected: it expects Authorization: Bearer <access_token> from "
        "https://mcp.openshopgo.com/oauth/token (authorization_code + PKCE), not X-API-Key alone. "
        "Use MCP_BEARER_TOKEN=<access_token>. If only Claude's redirect_uri is registered for "
        "client_id=openshop-claude, ask OpenShop for a client_id + redirect_uri for your VPS "
        "or a refresh token / M2M credential."
    )


if __name__ == "__main__":
    asyncio.run(main())
