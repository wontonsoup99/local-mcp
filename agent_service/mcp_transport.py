"""Connect to a remote MCP server over streamable HTTP or SSE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from agent_service.config import Settings
from agent_service.errors import exception_chain_contains_401


@asynccontextmanager
async def mcp_client_session(settings: Settings) -> AsyncIterator[ClientSession]:
    """Initialize MCP and yield a connected ``ClientSession``.

    On HTTP 401 with ``MCP_REFRESH_TOKEN`` set, invalidates the access-token cache and retries once.
    """
    from agent_service.oauth_refresh import invalidate_cache

    for attempt in range(2):
        try:
            headers = settings.merged_mcp_headers()

            if settings.mcp_transport == "streamable-http":
                timeout = httpx.Timeout(60.0, read=300.0)
                async with httpx.AsyncClient(
                    timeout=timeout,
                    headers=headers if headers else None,
                ) as http_client:
                    async with streamable_http_client(
                        settings.mcp_url,
                        http_client=http_client,
                    ) as streams:
                        read_stream, write_stream, _ = streams
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            yield session
                return

            async with sse_client(
                settings.mcp_url,
                headers=headers or None,
                timeout=60.0,
                sse_read_timeout=300.0,
            ) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
            return

        except Exception as exc:
            if (
                attempt == 0
                and settings.mcp_refresh_token
                and str(settings.mcp_refresh_token).strip()
                and exception_chain_contains_401(exc)
            ):
                invalidate_cache()
                continue
            raise
