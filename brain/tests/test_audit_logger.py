"""Tests for FINRA 3110 compliant audit logger."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from compliance.audit_logger import AuditLogger


@pytest.fixture
def tmp_audit_dir(tmp_path):
    return str(tmp_path / "audit_logs")


@pytest.fixture
def logger(tmp_audit_dir):
    return AuditLogger(log_dir=tmp_audit_dir)


class TestAuditLoggerInit:
    def test_creates_log_directory(self, tmp_audit_dir):
        AuditLogger(log_dir=tmp_audit_dir)
        assert os.path.isdir(tmp_audit_dir)

    def test_default_retention_7_years(self, logger):
        assert logger.retention_days == 2555


class TestOrderLogging:
    def test_log_order_basic(self, logger):
        logger.log_order(sleeve_id=1, symbol="IEF", side="BUY", qty=10.0,
                         order_type="MARKET", crisis_level="Normal",
                         portfolio_value=50000.0, daily_pnl=100.0)
        entries = logger.get_entries()
        assert len(entries) == 1
        assert entries[0]["event_type"] == "ORDER"
        assert entries[0]["symbol"] == "IEF"
        assert entries[0]["side"] == "BUY"
        assert entries[0]["qty"] == 10.0

    def test_log_order_writes_jsonl(self, logger, tmp_audit_dir):
        logger.log_order(sleeve_id=3, symbol="ES", side="SELL", qty=5.0,
                         order_type="MARKET")
        files = os.listdir(tmp_audit_dir)
        assert len(files) == 1
        assert files[0].startswith("audit_") and files[0].endswith(".jsonl")

        with open(os.path.join(tmp_audit_dir, files[0])) as f:
            line = f.readline()
            record = json.loads(line)
            assert record["event_type"] == "ORDER"
            assert record["symbol"] == "ES"

    def test_log_rejected_order(self, logger):
        logger.log_order(sleeve_id=1, symbol="IEF", side="REJECTED", qty=10.0,
                         order_type="N/A", crisis_level="SmartBunker")
        entries = logger.get_entries()
        assert entries[0]["side"] == "REJECTED"

    def test_kwargs_forwarded(self, logger):
        logger.log_order(sleeve_id=1, symbol="IEF", side="BUY", qty=1,
                         order_type="MARKET", custom_field="test_value")
        entries = logger.get_entries()
        assert entries[0]["custom_field"] == "test_value"


class TestRiskEventLogging:
    def test_log_crisis_transition(self, logger):
        logger.log_risk_event("CRISIS_TRANSITION", sleeve_id=0,
                              signal_value=52.0, risk_flag=2)
        entries = logger.get_entries()
        assert len(entries) == 1
        assert "RISK" in entries[0]["event_type"]
        assert entries[0]["signal_value"] == 52.0
        assert entries[0]["risk_flag"] == 2

    def test_log_circuit_breaker(self, logger):
        logger.log_risk_event("CIRCUIT_BREAKER", risk_flag=2)
        entries = logger.get_entries(event_type="RISK")
        assert len(entries) == 1


class TestKillSwitchLogging:
    def test_log_kill_switch(self, logger):
        logger.log_kill_switch(reason="PNL_LOSS", portfolio_value=50000.0,
                               daily_pnl=-1500.0)
        entries = logger.get_entries()
        assert entries[0]["event_type"] == "KILL_SWITCH"
        assert entries[0]["reason"] == "PNL_LOSS"
        assert entries[0]["daily_pnl"] == -1500.0

    def test_kill_switch_logged_to_file(self, logger, tmp_audit_dir):
        logger.log_kill_switch(reason="MANUAL", portfolio_value=50000.0)
        files = os.listdir(tmp_audit_dir)
        with open(os.path.join(tmp_audit_dir, files[0])) as f:
            record = json.loads(f.readline())
            assert record["event_type"] == "KILL_SWITCH"


class TestConfigChangeLogging:
    def test_log_config_change(self, logger):
        logger.log_config_change({"hedge_ratio": 0.9, "max_position": 2000000})
        entries = logger.get_entries()
        assert entries[0]["event_type"] == "CONFIG_CHANGE"
        assert entries[0]["changes"]["hedge_ratio"] == 0.9


class TestEntryQuerying:
    def test_filter_by_event_type(self, logger):
        logger.log_order(sleeve_id=1, symbol="IEF", side="BUY", qty=1)
        logger.log_risk_event("CRISIS")
        logger.log_kill_switch(reason="test")

        orders = logger.get_entries(event_type="ORDER")
        assert len(orders) == 1
        kills = logger.get_entries(event_type="KILL_SWITCH")
        assert len(kills) == 1
        risks = logger.get_entries(event_type="RISK")
        assert len(risks) == 1

    def test_all_entries_have_timestamp(self, logger):
        logger.log_order(sleeve_id=1, symbol="X", side="BUY", qty=1)
        logger.log_risk_event("TEST")
        for entry in logger.get_entries():
            assert "timestamp" in entry


class TestComplianceSummary:
    def test_summary_counts(self, logger):
        logger.log_order(sleeve_id=1, symbol="A", side="BUY", qty=1)
        logger.log_order(sleeve_id=2, symbol="B", side="SELL", qty=2)
        logger.log_risk_event("CRISIS")
        logger.log_kill_switch(reason="test")
        logger.log_config_change({"key": "val"})

        summary = logger.get_compliance_summary()
        assert summary["total_entries"] == 5
        assert summary["orders"] == 2
        assert summary["risk_events"] == 1
        assert summary["kill_switches"] == 1
        assert summary["config_changes"] == 1
        assert summary["finra_3110_compliant"] is True
        assert summary["worm_storage"] is True

    def test_empty_summary(self, logger):
        summary = logger.get_compliance_summary()
        assert summary["total_entries"] == 0


class TestJSONLFileFormat:
    def test_multiple_entries_one_per_line(self, logger, tmp_audit_dir):
        logger.log_order(sleeve_id=1, symbol="A", side="BUY", qty=1)
        logger.log_order(sleeve_id=2, symbol="B", side="SELL", qty=2)
        logger.log_risk_event("TEST")

        files = os.listdir(tmp_audit_dir)
        with open(os.path.join(tmp_audit_dir, files[0])) as f:
            lines = f.readlines()
            assert len(lines) == 3
            for line in lines:
                record = json.loads(line)
                assert "event_type" in record
                assert "timestamp" in record
