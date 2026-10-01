"""Structured logging with automatic secret redaction."""
import logging
import re
import structlog

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"isc_pat_[A-Za-z0-9]{8,}"),  # personal access tokens
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
]
SECRET_KEYS = {"password", "api_key", "apikey", "secret", "token", "authorization", "x-api-key", "cookie"}


def redact_text(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


def redact(obj, extra_values: list[str] | None = None):
    """Recursively redacts secret-looking keys, known key formats and any explicit secret values."""
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if str(k).lower() in SECRET_KEYS else redact(v, extra_values)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v, extra_values) for v in obj]
    if isinstance(obj, str):
        out = redact_text(obj)
        for val in extra_values or []:
            if val and len(val) >= 6:
                out = out.replace(val, "[REDACTED]")
        return out
    return obj


def _redact_processor(_, __, event_dict):
    return redact(event_dict)


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.format_exc_info,  # include the traceback of log.exception(...) in the JSON line
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
    )


log = structlog.get_logger("isocline")
