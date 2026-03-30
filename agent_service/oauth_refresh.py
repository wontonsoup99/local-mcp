"""OpenShop OAuth: refresh access tokens using MCP_REFRESH_TOKEN (≈1h access, rotating refresh)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached_access: str | None = None
_cached_expires_at: float = 0.0
_runtime_refresh: str | None = None


def invalidate_cache() -> None:
    """Force next request to call POST /oauth/token again."""
    global _cached_access, _cached_expires_at
    with _lock:
        _cached_access = None
        _cached_expires_at = 0.0


def _maybe_persist_refresh_token(path: str, token: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(token.strip())
        logger.info("Wrote rotated refresh token to MCP_REFRESH_TOKEN_FILE")
    except OSError as exc:
        logger.warning("Could not write MCP_REFRESH_TOKEN_FILE: %s", exc)


def get_or_refresh_access_token(settings: Any) -> str:
    """Return a valid access token, refreshing with refresh_token when near expiry."""
    global _cached_access, _cached_expires_at, _runtime_refresh

    rt = settings.mcp_refresh_token
    if not rt or not str(rt).strip():
        raise RuntimeError("MCP_REFRESH_TOKEN is required for refresh flow")

    with _lock:
        if _runtime_refresh is None:
            _runtime_refresh = str(rt).strip()

        now = time.time()
        margin = float(os.environ.get("MCP_OAUTH_REFRESH_MARGIN_SEC", "120"))
        if _cached_access and now < _cached_expires_at - margin:
            return _cached_access

        body = {
            "grant_type": "refresh_token",
            "refresh_token": _runtime_refresh,
            "client_id": settings.mcp_oauth_client_id,
        }
        logger.info("Refreshing OAuth access token at %s", settings.mcp_oauth_token_url)
        resp = httpx.post(
            settings.mcp_oauth_token_url,
            data=body,
            timeout=30.0,
        )
        if resp.is_error:
            logger.error("Token refresh failed: %s", resp.text)
            resp.raise_for_status()

        data = resp.json()
        access = data.get("access_token")
        if not access or not isinstance(access, str):
            raise RuntimeError("refresh response missing access_token")

        expires_in = int(data.get("expires_in", 3600))
        _cached_access = access.strip()
        _cached_expires_at = now + expires_in

        new_rt = data.get("refresh_token")
        if new_rt and isinstance(new_rt, str):
            new_rt = new_rt.strip()
            if new_rt != _runtime_refresh:
                logger.warning(
                    "OAuth issued a new refresh token (rotation). Update MCP_REFRESH_TOKEN in .env "
                    "or rely on MCP_REFRESH_TOKEN_FILE if set."
                )
                _runtime_refresh = new_rt
                path = settings.mcp_refresh_token_file
                if path:
                    _maybe_persist_refresh_token(path, new_rt)

        return _cached_access


def access_token_for_mcp(settings: Any) -> str | None:
    """Bearer token: from refresh flow if MCP_REFRESH_TOKEN set, else static MCP_BEARER_TOKEN."""
    if settings.mcp_disable_bearer:
        return None
    if settings.mcp_refresh_token and str(settings.mcp_refresh_token).strip():
        return get_or_refresh_access_token(settings)
    return settings.mcp_bearer_token.strip() if settings.mcp_bearer_token else None
