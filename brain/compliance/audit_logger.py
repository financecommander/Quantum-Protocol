"""Audit Logger stub — compliance logging for all trade actions."""

import logging

logger = logging.getLogger("matrix.compliance.audit")


class AuditLogger:
    """Logs all trade actions for compliance. v1.0: file-based. v2.0: immutable ledger."""

    def __init__(self, log_dir: str = "./audit_logs"):
        self._entries = []
        self.log_dir = log_dir

    def log_order(self, action: str, **kwargs):
        entry = {"action": action, **kwargs}
        self._entries.append(entry)
        logger.info(f"AUDIT: {action} | {kwargs}")

    def log_risk_event(self, event: str, **kwargs):
        entry = {"event": event, **kwargs}
        self._entries.append(entry)
        logger.warning(f"AUDIT RISK: {event} | {kwargs}")

    def get_entries(self) -> list:
        return list(self._entries)
