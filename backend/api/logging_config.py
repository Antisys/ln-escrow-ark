"""
Structured JSON logging for production and a financial audit logger.

Usage:
    from backend.api.logging_config import setup_logging, audit_log
    setup_logging()  # called once at startup in main.py
    audit_log.info("payout_completed", deal_id=..., amount_sats=...)
"""
import json
import logging
import os
import sys
import time
from contextvars import ContextVar

# Per-request ID (set by RequestIdMiddleware)
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line — machine-parseable for journalctl/Loki."""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        req_id = request_id_var.get("")
        if req_id:
            obj["request_id"] = req_id
        if record.exc_info and record.exc_info[0]:
            obj["exception"] = self.formatException(record.exc_info)
        # Extra fields from audit_log
        for key in ("deal_id", "amount_sats", "fee_sat", "payout_type",
                     "payment_preimage", "escrow_id", "event"):
            val = getattr(record, key, None)
            if val is not None:
                obj[key] = val
        return json.dumps(obj, default=str)


class HumanFormatter(logging.Formatter):
    """Readable format for local dev (non-JSON)."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = request_id_var.get("")
        prefix = f"[{req_id[:8]}] " if req_id else ""
        base = f"{record.levelname} {record.name}: {prefix}{record.getMessage()}"
        if record.exc_info and record.exc_info[0]:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging():
    """Configure root logger. Call once at import time in main.py."""
    use_json = os.getenv("LOG_FORMAT", "").lower() == "json"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter() if use_json else HumanFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Quiet noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class _AuditLogger:
    """
    Financial audit logger. All payout-related events go through here
    so they can be grepped/filtered separately.

    Usage:
        audit_log.info("payout_completed", deal_id="abc", amount_sats=50000)
    """

    def __init__(self):
        self._logger = logging.getLogger("audit")

    def _log(self, level: int, event: str, **kwargs):
        extra = {"event": event, **kwargs}
        self._logger.log(level, event, extra=extra)

    def info(self, event: str, **kwargs):
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs):
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs):
        self._log(logging.ERROR, event, **kwargs)


audit_log = _AuditLogger()
