"""
Quantum Protocol — Shared test fixtures.

Provides reusable fixtures for MarketState, Orchestrator, AuditLogger,
KillSwitch, and mock IBKR client. Import-free: pytest discovers this
automatically for all tests in brain/tests/.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from orchestrator import Orchestrator, MarketState
from risk.kill_switch import KillSwitch
from compliance.audit_logger import AuditLogger


# ---------------------------------------------------------------------------
# MarketState factory
# ---------------------------------------------------------------------------


def make_market(
    vix: float = 18.0,
    spx: float = 5000.0,
    tnx: float = 42.0,
    dxy: float = 104.0,
    es: float = 5000.0,
    zn: float = 110.0,
    zf: float = 108.0,
    **kwargs,
) -> MarketState:
    """Create a MarketState with sensible defaults. Override any field via kwargs."""
    defaults = dict(
        timestamp=datetime.now(timezone.utc),
        vix=vix,
        spx=spx,
        tnx=tnx,
        dxy=dxy,
        es_price=es,
        zn_price=zn,
        zf_price=zf,
    )
    defaults.update(kwargs)
    return MarketState(**defaults)


@pytest.fixture
def market():
    """Default neutral market state."""
    return make_market()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@pytest.fixture
def orchestrator():
    """Fresh Orchestrator with default allocation."""
    return Orchestrator()


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_logger(tmp_path):
    """AuditLogger writing to a temp directory."""
    return AuditLogger(log_dir=str(tmp_path / "audit_logs"))


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------


@pytest.fixture
def kill_switch():
    """Fresh KillSwitch instance."""
    return KillSwitch()


# ---------------------------------------------------------------------------
# Mock IBKR Client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ibkr():
    """MagicMock IBKR client with sensible defaults."""
    client = MagicMock()
    client.is_connected.return_value = True
    client.get_positions = AsyncMock(return_value=[])
    client.get_account_summary = AsyncMock(return_value=None)
    return client
