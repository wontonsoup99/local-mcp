#!/usr/bin/env python3
"""Print non-secret diagnostics: which MCP env vars load, header keys, string lengths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)


def main() -> None:
    from agent_service.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    h = s.merged_mcp_headers()
    print("MCP_URL:", s.mcp_url)
    print("MCP_TRANSPORT:", s.mcp_transport)
    print("Flags: disable_bearer=%s disable_store_slug=%s" % (s.mcp_disable_bearer, s.mcp_disable_store_slug))
    print("Header keys:", sorted(h.keys()))
    for name in sorted(h.keys()):
        v = h[name]
        print(f"  {name} length: {len(v)}")
    if "Cookie" not in h:
        print("  Cookie: (not set)")
    if s.mcp_cookie and len(s.mcp_cookie) < 20:
        print("WARNING: MCP_COOKIE looks very short — check .env quoting (use double quotes).", file=sys.stderr)


if __name__ == "__main__":
    main()
