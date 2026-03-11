"""
Quantum Protocol — Alert Dispatcher

Sends alerts to Slack (and optionally email) on critical events:
  - Kill switch activation
  - Crisis level transitions
  - Human approval gates
  - Heartbeat timeouts

Graceful no-op if QP_SLACK_WEBHOOK is not configured.
"""

import json
import logging
import os
import time
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("matrix.alerts")

# Default cooldown: 5 minutes between duplicate alerts
_DEFAULT_COOLDOWN_SECS = 300


class AlertDispatcher:
    """Simple alert bridge — Slack webhook + cooldown."""

    def __init__(self, cooldown_secs: float = _DEFAULT_COOLDOWN_SECS):
        self._webhook_url = os.environ.get("QP_SLACK_WEBHOOK", "")
        self._email_to = os.environ.get("QP_ALERT_EMAIL", "")
        self._cooldown_secs = cooldown_secs
        self._last_sent: dict[str, float] = {}  # key -> timestamp

    @property
    def is_configured(self) -> bool:
        return bool(self._webhook_url)

    def send_alert(self, level: str, message: str, *, dedup_key: Optional[str] = None) -> bool:
        """
        Send an alert. Returns True if sent, False if suppressed or unconfigured.

        Args:
            level: "INFO", "WARNING", "CRITICAL"
            message: Alert body text
            dedup_key: Optional key for cooldown deduplication.
                       If omitted, uses level+message hash.
        """
        key = dedup_key or f"{level}:{message}"

        # Cooldown check
        now = time.time()
        last = self._last_sent.get(key, 0.0)
        if now - last < self._cooldown_secs:
            logger.debug(f"Alert suppressed (cooldown): {key}")
            return False

        if not self._webhook_url:
            logger.info(f"Alert (no webhook configured): [{level}] {message}")
            return False

        # Build Slack payload
        emoji = {"INFO": ":information_source:", "WARNING": ":warning:", "CRITICAL": ":rotating_light:"}.get(level, ":bell:")
        payload = {
            "text": f"{emoji} *[{level}] Quantum Protocol*\n{message}",
        }

        try:
            req = Request(
                self._webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    self._last_sent[key] = now
                    logger.info(f"Alert sent: [{level}] {message}")
                    return True
                else:
                    logger.warning(f"Slack webhook returned {resp.status}")
                    return False
        except (URLError, OSError) as e:
            logger.error(f"Failed to send alert: {e}")
            return False

    def send_kill_switch_alert(self, reason: str) -> bool:
        return self.send_alert(
            "CRITICAL",
            f"Kill switch activated: {reason}",
            dedup_key="kill_switch",
        )

    def send_crisis_transition(self, old_level: str, new_level: str) -> bool:
        return self.send_alert(
            "WARNING",
            f"Crisis transition: {old_level} → {new_level}",
            dedup_key=f"crisis_{new_level}",
        )

    def send_heartbeat_timeout(self, sleeve: str, elapsed_min: float) -> bool:
        return self.send_alert(
            "CRITICAL",
            f"Heartbeat timeout on {sleeve}: {elapsed_min:.0f} min silent",
            dedup_key=f"heartbeat_{sleeve}",
        )


# Module-level singleton
_dispatcher: Optional[AlertDispatcher] = None


def get_dispatcher(cooldown_secs: float = _DEFAULT_COOLDOWN_SECS) -> AlertDispatcher:
    """Get or create the global alert dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AlertDispatcher(cooldown_secs=cooldown_secs)
    return _dispatcher
