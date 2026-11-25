"""Structured standard-library logging and request correlation ID utilities for AIRWISE AI.

Design rules:
- Uses Python standard library only (`logging`, `contextvars`, `re`, `traceback`, `uuid`).
- Propagates a validated per-request correlation ID (`X-Request-ID`) via `contextvars`
  so concurrent requests never leak IDs into one another.
- Applies defense-in-depth redaction on both child loggers and handlers so API keys,
  tokens, or secrets are never emitted in log messages or formatted exception tracebacks.
"""

from __future__ import annotations

import contextvars
import logging
import re
import traceback
import uuid

REQUEST_ID_HEADER = "X-Request-ID"

# Allow safe, bounded correlation IDs (alphanumeric, dot, underscore, hyphen, 4..64 chars).
# Rejects whitespace, control characters, CRLF log-injection sequences, and overly long strings.
_VALID_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{4,64}$")

# Defense-in-depth patterns for accidental secret redaction in log output.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)([^\s,;\"']+)"
        ),
        r"\1[REDACTED]",
    ),
)

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "airwise_request_id",
    default="-",
)


def is_valid_request_id(value: str | None) -> bool:
    """Return True if the supplied correlation ID is safe and well-formed."""
    if not value:
        return False
    return bool(_VALID_REQUEST_ID_RE.fullmatch(value))


def generate_request_id() -> str:
    """Generate a unique, URL- and log-safe correlation ID."""
    return uuid.uuid4().hex


def resolve_request_id(incoming_value: str | None) -> str:
    """Return the validated incoming correlation ID, or a newly generated ID if invalid/absent."""
    if incoming_value is not None and is_valid_request_id(incoming_value):
        return incoming_value
    return generate_request_id()


def get_request_id() -> str:
    """Return the active request correlation ID for the current execution context."""
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> contextvars.Token[str]:
    """Bind a correlation ID to the current execution context and return its reset token."""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Restore the previous correlation ID context safely."""
    _request_id_ctx.reset(token)


def redact_secrets(text: str) -> str:
    """Redact common credential/token patterns from a log string."""
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class RequestIdFilter(logging.Filter):
    """Attach the active contextvars correlation ID to every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id()
        return True


class SecretRedactingFilter(logging.Filter):
    """Defense-in-depth filter that redacts secret-like patterns from messages and tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)

        try:
            redacted = redact_secrets(rendered)
            if redacted != rendered:
                record.msg = redacted
                record.args = ()
        except Exception:
            # Never break logging if a record contains unexpected/malformed values.
            pass

        try:
            if record.exc_info:
                formatted_exc = "".join(
                    traceback.format_exception(*record.exc_info)
                ).rstrip()
                record.exc_text = redact_secrets(formatted_exc)
                record.exc_info = None
            elif record.exc_text:
                record.exc_text = redact_secrets(record.exc_text)
        except Exception:
            # If exception formatting fails, ensure raw exc_info does not bypass redaction.
            record.exc_text = "[EXCEPTION_FORMATTING_FAILED]"
            record.exc_info = None

        return True


class SecretRedactingFormatter(logging.Formatter):
    """Formatter applying final secret redaction across formatted messages and exceptions."""

    def formatException(self, ei) -> str:  # type: ignore[override]
        return redact_secrets(super().formatException(ei))

    def format(self, record: logging.LogRecord) -> str:
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id()
        return redact_secrets(super().format(record))


_LOG_FORMAT = "%(asctime)s %(levelname)s [req=%(request_id)s] %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%dT%H:%M:%S"


def _attach_airwise_filters(target: logging.Logger | logging.Handler) -> None:
    """Attach RequestIdFilter and SecretRedactingFilter idempotently."""
    if not any(isinstance(f, RequestIdFilter) for f in target.filters):
        target.addFilter(RequestIdFilter())
    if not any(isinstance(f, SecretRedactingFilter) for f in target.filters):
        target.addFilter(SecretRedactingFilter())


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure the `airwise` root logger hierarchy idempotently."""
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger("airwise")
    root_logger.setLevel(resolved_level)

    if not getattr(root_logger, "_airwise_configured", False):
        handler = logging.StreamHandler()
        handler.setFormatter(
            SecretRedactingFormatter(fmt=_LOG_FORMAT, datefmt=_LOG_DATEFMT)
        )
        _attach_airwise_filters(handler)
        root_logger.addHandler(handler)
        root_logger.propagate = True
        setattr(root_logger, "_airwise_configured", True)

    _attach_airwise_filters(root_logger)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under `airwise` with correlation and redaction filters attached."""
    clean_name = name.removeprefix("app.")
    child = logging.getLogger(f"airwise.{clean_name}")
    _attach_airwise_filters(child)
    return child
