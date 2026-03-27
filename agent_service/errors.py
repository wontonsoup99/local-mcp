"""Format nested async/TaskGroup failures for logs and HTTP responses."""

from __future__ import annotations


def format_exception_chain(exc: BaseException) -> str:
    """Flatten ExceptionGroup / TaskGroup wrappers to the underlying messages."""
    if isinstance(exc, BaseExceptionGroup):
        parts = [format_exception_chain(e) for e in exc.exceptions]
        return "; ".join(p for p in parts if p)
    return f"{type(exc).__name__}: {exc}"
