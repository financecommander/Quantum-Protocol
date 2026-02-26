"""Tests ported from Rust test suite: kill switch behavior."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from risk.kill_switch import KillSwitch, KillReason


@pytest.fixture
def ks():
    return KillSwitch()


class TestKillSwitchPnL:
    def test_normal_loss_no_trigger(self, ks):
        assert ks.check_pnl(-500, 100_000) is False
        assert ks.is_active() is False

    def test_2pct_loss_triggers(self, ks):
        assert ks.check_pnl(-2_000, 100_000) is True
        assert ks.is_active() is True
        assert ks.kill_reason == KillReason.PNL_LOSS

    def test_positive_pnl_never_triggers(self, ks):
        assert ks.check_pnl(5_000, 100_000) is False


class TestKillSwitchPosition:
    def test_normal_position_no_trigger(self, ks):
        assert ks.check_position(10_000, 100_000) is False

    def test_concentrated_position_triggers(self, ks):
        assert ks.check_position(30_000, 100_000) is True
        assert ks.kill_reason == KillReason.POSITION_BREACH


class TestKillSwitchRejections:
    def test_single_rejection_no_trigger(self, ks):
        ks.record_rejection()
        assert ks.is_active() is False

    def test_five_rejections_triggers(self, ks):
        for _ in range(5):
            ks.record_rejection()
        assert ks.is_active() is True
        assert ks.kill_reason == KillReason.CONSECUTIVE_REJECTIONS

    def test_fill_resets_counter(self, ks):
        for _ in range(4):
            ks.record_rejection()
        ks.record_fill()
        ks.record_rejection()
        assert ks.is_active() is False


class TestKillSwitchLatching:
    def test_stays_killed_after_trigger(self, ks):
        ks.check_pnl(-5_000, 100_000)
        assert ks.is_active() is True
        ks.check_pnl(10_000, 100_000)
        assert ks.is_active() is True

    def test_manual_reset(self, ks):
        ks.check_pnl(-5_000, 100_000)
        ks.reset(operator="sean_grady")
        assert ks.is_active() is False

    def test_manual_kill(self, ks):
        ks.manual_kill()
        assert ks.is_active() is True
        assert ks.kill_reason == KillReason.MANUAL


class TestKillSwitchStatus:
    def test_status_when_active(self, ks):
        ks.check_pnl(-3_000, 100_000)
        status = ks.status()
        assert status["is_killed"] is True
        assert status["kill_reason"] == "pnl_loss"
        assert status["kill_time"] is not None
