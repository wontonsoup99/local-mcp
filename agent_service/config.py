"""Environment-driven configuration (no secrets in code)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _format_authorization_header(token: str, style: Literal["bearer", "raw"]) -> str:
    t = token.strip()
    if style == "raw":
        return t
    if t.lower().startswith("bearer "):
        return t
    return f"Bearer {t}"


class Settings(BaseSettings):
    """Application and integration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- HTTP API ---
    bind_host: str = Field(default="0.0.0.0", validation_alias="AGENT_BIND_HOST")
    bind_port: int = Field(default=8080, validation_alias="AGENT_PORT")

    # --- Ollama (OpenAI-compatible API) ---
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        validation_alias="OLLAMA_BASE_URL",
    )
    ollama_api_key: str = Field(
        default="ollama",
        validation_alias="OLLAMA_API_KEY",
        description="Dummy key; Ollama ignores it but OpenAI client requires a string.",
    )
    ollama_model: str = Field(default="llama3.2", validation_alias="OLLAMA_MODEL")

    # --- Remote MCP ---
    mcp_url: str = Field(
        ...,
        validation_alias="MCP_URL",
        description="Full URL to the MCP endpoint (streamable HTTP or SSE entry URL).",
    )
    mcp_transport: Literal["streamable-http", "sse"] = Field(
        default="streamable-http",
        validation_alias="MCP_TRANSPORT",
    )
    mcp_bearer_token: str | None = Field(default=None, validation_alias="MCP_BEARER_TOKEN")
    mcp_auth_style: Literal["bearer", "raw"] = Field(
        default="bearer",
        validation_alias="MCP_AUTH_STYLE",
        description=(
            "bearer: send Authorization: Bearer <MCP_BEARER_TOKEN>. "
            "raw: send Authorization: <MCP_BEARER_TOKEN> exactly (no Bearer prefix). "
            "If the token already starts with 'Bearer ', duplicate prefix is avoided."
        ),
    )
    mcp_store_slug: str | None = Field(
        default=None,
        validation_alias="MCP_STORE_SLUG",
        description=(
            "OpenShop: store slug from the 'Connect Your OpenShop Store' OAuth page. "
            "Sent as X-Store-Slug unless you override via MCP_HEADERS_JSON."
        ),
    )
    mcp_store_slug_header: str = Field(
        default="X-Store-Slug",
        validation_alias="MCP_STORE_SLUG_HEADER",
        description="HTTP header name for the store slug (if OpenShop uses a different name).",
    )
    mcp_headers_json: str | None = Field(
        default=None,
        validation_alias="MCP_HEADERS_JSON",
        description='Optional JSON object of extra headers, e.g. {"X-Custom": "v"}',
    )
    mcp_cookie: str | None = Field(
        default=None,
        validation_alias="MCP_COOKIE",
        description="Optional Cookie header if the MCP site authenticates via session cookie (see README).",
    )
    mcp_disable_bearer: bool = Field(
        default=False,
        validation_alias="MCP_DISABLE_BEARER",
        description="If true, do not send Authorization (test cookie-only auth).",
    )
    mcp_disable_store_slug: bool = Field(
        default=False,
        validation_alias="MCP_DISABLE_STORE_SLUG",
        description="If true, do not send X-Store-Slug (or MCP_STORE_SLUG_HEADER).",
    )

    # --- Agent loop ---
    max_tool_rounds: int = Field(default=16, validation_alias="MAX_TOOL_ROUNDS")
    system_prompt: str | None = Field(
        default=None,
        validation_alias="SYSTEM_PROMPT",
        description="Default system prompt used when /chat request omits 'system'.",
    )

    expose_mcp_healthcheck: bool = Field(
        default=False,
        validation_alias="EXPOSE_MCP_HEALTHCHECK",
        description="If true, GET /health/mcp probes MCP connect (for debugging only).",
    )

    @field_validator("mcp_cookie", "system_prompt", mode="before")
    @classmethod
    def strip_optional_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("mcp_bearer_token", "mcp_store_slug", mode="before")
    @classmethod
    def strip_optional_strings(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("mcp_headers_json")
    @classmethod
    def parse_headers(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        json.loads(v)
        return v

    def merged_mcp_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.mcp_headers_json:
            extra: dict[str, Any] = json.loads(self.mcp_headers_json)
            for key, val in extra.items():
                headers[str(key)] = str(val)
        if self.mcp_bearer_token and not self.mcp_disable_bearer:
            headers["Authorization"] = _format_authorization_header(
                self.mcp_bearer_token,
                self.mcp_auth_style,
            )
        if self.mcp_store_slug and not self.mcp_disable_store_slug:
            headers[self.mcp_store_slug_header.strip() or "X-Store-Slug"] = self.mcp_store_slug
        if self.mcp_cookie:
            headers["Cookie"] = self.mcp_cookie
        return headers


@lru_cache
def get_settings() -> Settings:
    return Settings()
