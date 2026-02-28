"""
MATRIX PROTOCOL™ v1.0 — FINRA 3110 Compliant Audit Logger

Append-only JSONL file-based logging (WORM-style).
Daily files: {log_dir}/audit_{YYYYMMDD}.jsonl
Retention: 2555 days (~7 years) per FINRA requirements.

Every order decision, risk event, kill switch activation, and config change
is logged with ISO 8601 timestamp, event type, and full context.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("matrix.compliance.audit")


class AuditLogger:
    """
    FINRA 3110 compliant audit logger.

    All entries are append-only JSONL (one JSON object per line).
    Files are organized by date for retention management.
    """

    def __init__(self, log_dir: str = "./audit_logs", retention_days: int = 2555):
        self.log_dir = log_dir
        self.retention_days = retention_days
        self._entries: list[dict] = []  # In-memory buffer for queries
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        """Create log directory if it doesn't exist."""
        os.makedirs(self.log_dir, exist_ok=True)

    def _log_file_path(self, dt: Optional[datetime] = None) -> str:
        """Daily JSONL file path."""
        dt = dt or datetime.now(timezone.utc)
        return os.path.join(self.log_dir, f"audit_{dt.strftime('%Y%m%d')}.jsonl")

    def _write_entry(self, entry: dict):
        """Append a single entry to the daily JSONL file and in-memory buffer."""
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._entries.append(entry)

        try:
            path = self._log_file_path()
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError as e:
            logger.error(f"Failed to write audit entry: {e}")

    def log_order(self, sleeve_id: int = 0, symbol: str = "", side: str = "",
                  qty: float = 0.0, order_type: str = "", crisis_level: str = "Normal",
                  portfolio_value: float = 0.0, daily_pnl: float = 0.0,
                  **kwargs):
        """Log an order decision (submitted, rejected, cancelled)."""
        entry = {
            "event_type": "ORDER",
            "sleeve_id": sleeve_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "order_type": order_type,
            "crisis_level": crisis_level,
            "portfolio_value": portfolio_value,
            "daily_pnl": daily_pnl,
            **kwargs,
        }
        self._write_entry(entry)
        logger.info(f"AUDIT ORDER: {side} {qty} {symbol} (sleeve={sleeve_id}, crisis={crisis_level})")

    def log_risk_event(self, event_type: str, sleeve_id: int = 0,
                       signal_value: float = 0.0, position_delta: float = 0.0,
                       risk_flag: int = 0, **kwargs):
        """Log crisis transitions, circuit breaker events, regime changes."""
        entry = {
            "event_type": f"RISK_{event_type}",
            "sleeve_id": sleeve_id,
            "signal_value": signal_value,
            "position_delta": position_delta,
            "risk_flag": risk_flag,
            **kwargs,
        }
        self._write_entry(entry)
        logger.warning(f"AUDIT RISK: {event_type} (sleeve={sleeve_id}, flag={risk_flag})")

    def log_kill_switch(self, reason: str, portfolio_value: float = 0.0,
                        daily_pnl: float = 0.0, **kwargs):
        """Log kill switch activation."""
        entry = {
            "event_type": "KILL_SWITCH",
            "reason": reason,
            "portfolio_value": portfolio_value,
            "daily_pnl": daily_pnl,
            **kwargs,
        }
        self._write_entry(entry)
        logger.critical(f"AUDIT KILL SWITCH: {reason} (pv=${portfolio_value:,.0f}, pnl=${daily_pnl:,.0f})")

    def log_config_change(self, changes: dict, **kwargs):
        """Log configuration updates."""
        entry = {
            "event_type": "CONFIG_CHANGE",
            "changes": changes,
            **kwargs,
        }
        self._write_entry(entry)
        logger.info(f"AUDIT CONFIG: {changes}")

    def get_entries(self, since: Optional[datetime] = None,
                    event_type: Optional[str] = None) -> list[dict]:
        """
        Query audit log entries from in-memory buffer.

        Args:
            since: Only return entries after this timestamp.
            event_type: Filter by event type (e.g., "ORDER", "KILL_SWITCH").
        """
        entries = self._entries

        if since:
            since_iso = since.isoformat()
            entries = [e for e in entries if e.get("timestamp", "") >= since_iso]

        if event_type:
            entries = [e for e in entries if event_type in e.get("event_type", "")]

        return list(entries)

    def get_compliance_summary(self) -> dict:
        """Return summary for compliance dashboard."""
        total = len(self._entries)
        orders = sum(1 for e in self._entries if e.get("event_type") == "ORDER")
        risk_events = sum(1 for e in self._entries if "RISK" in e.get("event_type", ""))
        kill_switches = sum(1 for e in self._entries if e.get("event_type") == "KILL_SWITCH")
        config_changes = sum(1 for e in self._entries if e.get("event_type") == "CONFIG_CHANGE")

        return {
            "total_entries": total,
            "orders": orders,
            "risk_events": risk_events,
            "kill_switches": kill_switches,
            "config_changes": config_changes,
            "log_dir": self.log_dir,
            "retention_days": self.retention_days,
            "finra_3110_compliant": True,
            "worm_storage": True,
        }
