"""Format nested async/TaskGroup failures for logs and HTTP responses."""

from __future__ import annotations


def exception_chain_contains_401(exc: BaseException) -> bool:
    """True if any nested exception looks like HTTP 401 (MCP/httpx wrapped)."""
    if isinstance(exc, BaseExceptionGroup):
        return any(exception_chain_contains_401(e) for e in exc.exceptions)
    return "401" in str(exc)


def format_exception_chain(exc: BaseException) -> str:
    """Flatten ExceptionGroup / TaskGroup wrappers to the underlying messages."""
    if isinstance(exc, BaseExceptionGroup):
        parts = [format_exception_chain(e) for e in exc.exceptions]
        return "; ".join(p for p in parts if p)
    return f"{type(exc).__name__}: {exc}"
