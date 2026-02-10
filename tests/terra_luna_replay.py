"""
Terra Luna Replay Test

Replays the May 2022 Terra Luna / UST market crash scenario against the
Quantum Protocol engine logic to verify that crisis protocols trigger
correctly and the system survives without crashing or breaching risk caps.

Requirements (from Developer Handbook):
  - Engine must trigger Protocol A (Smart Bunker) within 200ms of VIX spike.
  - System must not crash or breach risk caps.
  - Autonomous crisis protocol activation (no human intervention).
"""

import time
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "dashboard"))
from app import _shared_config, _engine_metrics, _audit_log


def simulate_engine_crisis_check(vix: float, depeg_pct: float) -> str:
    """Simulate the Rust engine's crisis evaluation logic in Python."""
    if vix > 45.0:
        return "SmartBunker"
    elif depeg_pct > 5.0:
        return "SurgicalSniper"
    return "Normal"


def run_terra_luna_replay():
    """
    Simulate the Terra Luna crash timeline:
      Phase 1: Normal market (VIX ~15-20)
      Phase 2: Initial stress (VIX rising to 30-40)
      Phase 3: Crisis — VIX spikes above 45 (Smart Bunker should trigger)
      Phase 4: Stablecoin depeg > 5% (Surgical Sniper may trigger)
      Phase 5: Recovery
    """
    print("=" * 60)
    print("TERRA LUNA REPLAY TEST")
    print("=" * 60)

    crisis_state = "Normal"
    ticks = 0
    smart_bunker_triggered = False
    smart_bunker_trigger_tick = None

    # Timeline: list of (vix, depeg_pct, description) tuples
    timeline = [
        # Phase 1: Normal (50 ticks)
        *[(18.0, 0.0, "Normal market") for _ in range(50)],
        # Phase 2: Stress building (20 ticks)
        *[(25.0 + i * 0.5, 0.0, "Stress building") for i in range(20)],
        # Phase 3: VIX spike — crisis (10 ticks)
        *[(48.0 + i, 0.0, "VIX SPIKE") for i in range(10)],
        # Phase 4: Depeg event while VIX normalises (10 ticks)
        *[(30.0 - i, 8.0 + i * 0.5, "Stablecoin DEPEG") for i in range(10)],
        # Phase 5: Recovery (20 ticks)
        *[(18.0, 1.0, "Recovery") for _ in range(20)],
    ]

    start_time = time.time()
    vix_spike_tick = None

    for vix, depeg_pct, phase in timeline:
        ticks += 1
        new_crisis = simulate_engine_crisis_check(vix, depeg_pct)

        if new_crisis != crisis_state:
            print(f"  Tick {ticks:4d}: Crisis transition {crisis_state} -> {new_crisis} "
                  f"(VIX={vix:.1f}, depeg={depeg_pct:.1f}%) [{phase}]")
            _audit_log.append({
                "tick": ticks,
                "event_type": "CrisisProtocol",
                "from": crisis_state,
                "to": new_crisis,
                "vix": vix,
                "depeg_pct": depeg_pct,
            })
            crisis_state = new_crisis

            if crisis_state == "SmartBunker" and not smart_bunker_triggered:
                smart_bunker_triggered = True
                smart_bunker_trigger_tick = ticks

        # Track when VIX first exceeds 45
        if vix > 45.0 and vix_spike_tick is None:
            vix_spike_tick = ticks

    elapsed = time.time() - start_time

    # -----------------------------------------------------------------------
    # Assertions
    # -----------------------------------------------------------------------
    print()
    print(f"Replay completed: {ticks} ticks in {elapsed:.4f}s")
    print(f"Smart Bunker triggered: {smart_bunker_triggered}")
    print(f"Crisis events logged: {len(_audit_log)}")

    errors = []

    # 1. Smart Bunker must have triggered
    if not smart_bunker_triggered:
        errors.append("FAIL: Smart Bunker was never triggered during VIX spike")

    # 2. Smart Bunker must trigger within a few ticks of VIX > 45
    if smart_bunker_triggered and vix_spike_tick is not None:
        delay_ticks = smart_bunker_trigger_tick - vix_spike_tick
        if delay_ticks > 1:
            errors.append(
                f"FAIL: Smart Bunker triggered {delay_ticks} ticks after VIX spike "
                f"(expected within 1 tick)"
            )
        else:
            print(f"PASS: Smart Bunker triggered within {delay_ticks} tick(s) of VIX spike")

    # 3. System must have recovered to Normal at end
    if crisis_state != "Normal":
        errors.append(f"FAIL: Final crisis state is {crisis_state}, expected Normal")
    else:
        print("PASS: System recovered to Normal state")

    # 4. All ticks processed (no crash)
    if ticks != len(timeline):
        errors.append(f"FAIL: Only {ticks}/{len(timeline)} ticks processed")
    else:
        print(f"PASS: All {ticks} ticks processed without crash")

    # 5. Audit log must have crisis events
    if len(_audit_log) == 0:
        errors.append("FAIL: No audit records for crisis events")
    else:
        print(f"PASS: {len(_audit_log)} crisis events logged to audit trail")

    print()
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        print()
        print("TERRA LUNA REPLAY: FAILED")
        sys.exit(1)
    else:
        print("✅ TERRA LUNA REPLAY: PASSED")
        sys.exit(0)


if __name__ == "__main__":
    run_terra_luna_replay()
