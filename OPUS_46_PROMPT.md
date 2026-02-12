# Opus 4.6 Migration Prompt
## Quantum Protocol: Rust HFT Engine → Python Poly-Agent Architecture

---

## 🎯 Mission Statement

You are migrating a **Rust-based High-Frequency Trading engine** to a **Python Poly-Agent Architecture** using **Vertex AI Agents** and **Streamlit**.

**Source Repository:** `financecommander/Quantum-Protocol`

**Key Constraints:**
- Preserve **exact crisis protocol logic** (SmartBunker, SurgicalSniper)
- Maintain **FINRA 3110 compliance** (audit trail)
- Ensure **CTA exemption** (no buy/sell signals for retail)
- Relax latency from sub-100µs to **sub-500ms** (agent-appropriate)

---

## 📦 Source Files to Migrate

### 1. Core Trading Engine (Rust)
**File:** `src/engine/main.rs` (450 lines)

**Key Functions:**
```rust
// Crisis evaluation (lines 245-258)
pub fn evaluate_crisis(packet: &MarketPacket) -> CrisisState {
    if packet.vix > 45.0 {
        CrisisState::SmartBunker
    } else if packet.depeg_pct > 5.0 {
        CrisisState::SurgicalSniper
    } else {
        CrisisState::Normal
    }
}

// Treasury basis signal (lines 263-268)
pub fn sleeve_treasury_basis(packet: &MarketPacket, config: &SharedConfig) -> f64 {
    let spread = packet.ask - packet.bid;
    let fair_value = packet.last * config.hedge_ratio;
    (spread - fair_value * 0.001).clamp(-1.0, 1.0)
}

// Volatility regime signal (lines 273-279)
pub fn sleeve_vol_regime(packet: &MarketPacket, config: &SharedConfig) -> f64 {
    if packet.vix < config.vol_regime_threshold_low {
        -1.0  // risk-on
    } else if packet.vix > config.vol_regime_threshold_high {
        1.0   // risk-off
    } else {
        0.0   // neutral
    }
}

// Main tick processor (lines 325-373)
impl Engine {
    pub fn on_tick(&mut self, packet: &MarketPacket) {
        // 1. Evaluate crisis
        let new_crisis = evaluate_crisis(packet);
        if new_crisis != self.crisis_state {
            self.audit.push(/* crisis transition */);
            self.crisis_state = new_crisis;
        }

        // 2. In SmartBunker, skip sleeves
        if self.crisis_state == CrisisState::SmartBunker {
            return;
        }

        // 3. Compute sleeve signals
        let tb_signal = sleeve_treasury_basis(packet, &self.config);
        let vol_signal = sleeve_vol_regime(packet, &self.config);
        
        // 4. Log to audit ring
        self.audit.push(/* sleeve signals */);
    }
}
```

### 2. Python Dashboard (FastAPI)
**File:** `src/dashboard/app.py` (222 lines)

**Endpoints to migrate:**
- `GET /dashboard` → Streamlit page "1_📊_Dashboard.py"
- `GET /heatmaps` → Streamlit page "2_🔥_Heatmaps.py"
- `GET /latency` → Streamlit page "3_⏱️_Latency.py"
- `GET /compliance` → Streamlit page "4_📋_Compliance.py"
- `POST /update_config` → Streamlit page "5_⚙️_Config.py"

### 3. Test Suite
**File:** `tests/terra_luna_replay.py` (151 lines)
- Already in Python! ✅
- This is the **golden test** that validates crisis protocols
- Must pass after migration

---

## 🛠️ Your Tasks

### Task 1: Create Vertex AI Agent Tools

#### Tool 1: Crisis Protocol Agent
```python
"""vertex_agents/tools/crisis_tools.py"""

from typing import Literal

CrisisState = Literal["Normal", "SmartBunker", "SurgicalSniper"]

def evaluate_crisis(vix: float, depeg_pct: float) -> CrisisState:
    """
    Evaluate market crisis state based on VIX and stablecoin depeg percentage.
    
    Crisis Protocols (v9.3):
    - SmartBunker: VIX > 45 → hard pivot to T-Bills
    - SurgicalSniper: Depeg > 5% → taker execution authorized
    - Normal: Standard operations
    
    Args:
        vix: CBOE Volatility Index
        depeg_pct: Stablecoin depeg percentage
    
    Returns:
        Crisis state enum: "Normal", "SmartBunker", or "SurgicalSniper"
    
    FINRA Compliance: This function triggers audit logging per FINRA 3110.
    """
    # YOUR CODE HERE
    # Port exact logic from Rust (lines 245-258)
    pass

def log_crisis_transition(
    from_state: CrisisState,
    to_state: CrisisState,
    vix: float,
    depeg_pct: float,
    timestamp_ns: int
) -> dict:
    """
    Log a crisis state transition to GCP Cloud Logging.
    
    Returns:
        Audit record matching Rust AuditRecord schema
    """
    # YOUR CODE HERE
    # Use google.cloud.logging
    pass
```

#### Tool 2: Treasury Basis Agent
```python
"""vertex_agents/tools/sleeve_tools.py"""

def compute_treasury_basis_signal(
    bid: float,
    ask: float,
    last: float,
    hedge_ratio: float
) -> float:
    """
    Calculate treasury basis arbitrage signal.
    
    Formula (from Rust lines 263-268):
        spread = ask - bid
        fair_value = last * hedge_ratio
        signal = clamp(spread - fair_value * 0.001, -1.0, 1.0)
    
    Args:
        bid: Best bid price
        ask: Best ask price
        last: Last trade price
        hedge_ratio: From config (default 0.8)
    
    Returns:
        Signal in [-1.0, 1.0] indicating trade direction
    """
    # YOUR CODE HERE
    # Port exact logic from Rust
    pass
```

#### Tool 3: Vol Regime Agent
```python
"""vertex_agents/tools/sleeve_tools.py"""

def compute_vol_regime_signal(
    vix: float,
    low_threshold: float = 15.0,
    high_threshold: float = 30.0
) -> dict:
    """
    Classify volatility regime for risk management.
    
    Logic (from Rust lines 273-279):
        if vix < low_threshold: -1.0 (risk-on)
        elif vix > high_threshold: 1.0 (risk-off)
        else: 0.0 (neutral)
    
    Args:
        vix: CBOE Volatility Index
        low_threshold: Low volatility threshold (default 15.0)
        high_threshold: High volatility threshold (default 30.0)
    
    Returns:
        {
            "signal": float,         # -1.0, 0.0, or 1.0
            "regime": str,           # "Low", "Neutral", "High"
            "recommendation": str    # Human-readable advice
        }
    """
    # YOUR CODE HERE
    # Port exact logic from Rust
    pass
```

---

### Task 2: Create Agent Orchestrator

```python
"""vertex_agents/orchestrator.py"""

import asyncio
from typing import Dict, List
from .tools.crisis_tools import evaluate_crisis, log_crisis_transition
from .tools.sleeve_tools import compute_treasury_basis_signal, compute_vol_regime_signal
from .schemas.market_packet import MarketPacket

class QuantumProtocolOrchestrator:
    """
    Main agent coordinator that replicates Rust Engine::on_tick() logic.
    
    Orchestration Flow (from Rust lines 325-373):
    1. Evaluate crisis state
    2. Log crisis transitions
    3. If SmartBunker: skip sleeve processing
    4. Otherwise: compute sleeve signals in parallel
    5. Return aggregated recommendation
    """
    
    def __init__(self):
        self.crisis_state: str = "Normal"
        self.config = self._load_config()  # From Firestore
        self.audit_log = []  # In-memory audit ring (port from Rust)
    
    async def process_tick(self, packet: MarketPacket) -> Dict:
        """
        Process a single market data tick.
        
        Args:
            packet: Market data packet (bid, ask, last, vix, depeg_pct)
        
        Returns:
            {
                "crisis_state": str,
                "signals": Dict[str, float],
                "action": str,
                "reason": str,
                "timestamp": int
            }
        """
        # YOUR CODE HERE
        # Port exact logic from Rust Engine::on_tick() (lines 325-373)
        pass
    
    def _load_config(self) -> Dict:
        """Load configuration from Firestore."""
        # YOUR CODE HERE
        pass
```

---

### Task 3: Migrate FastAPI to Streamlit

#### Page 1: Dashboard
```python
"""streamlit_app/pages/1_📊_Dashboard.py"""

import streamlit as st
from vertex_agents.orchestrator import QuantumProtocolOrchestrator

st.set_page_config(page_title="Quantum Protocol Dashboard", page_icon="📊")

st.title("📊 Quantum Protocol Dashboard")
st.caption("CTA-Exempt Market Context — No Buy/Sell Signals")

# Initialize orchestrator
if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = QuantumProtocolOrchestrator()

# Display current crisis state
crisis_col, uptime_col, ticks_col = st.columns(3)
with crisis_col:
    st.metric("Crisis State", st.session_state.orchestrator.crisis_state)
with uptime_col:
    st.metric("Uptime", "42.3 seconds")  # TODO: Real uptime
with ticks_col:
    st.metric("Ticks Processed", "1,234")  # TODO: Real tick count

# Display coarsened market context (from FastAPI /dashboard)
st.subheader("Market Context")
st.info("Coarsened institutional signal — no direct execution")

# Auto-refresh every 5 seconds
if st.button("Refresh"):
    st.rerun()
```

#### Page 2: Heatmaps
```python
"""streamlit_app/pages/2_🔥_Heatmaps.py"""

import streamlit as st
import plotly.graph_objects as go

st.title("🔥 Volatility Regime Heatmap")

# Load config
config = st.session_state.orchestrator.config

# Create heatmap (from FastAPI /heatmaps)
thresholds = [
    {"label": "Low Vol", "range": f"VIX < {config['vol_regime_threshold_low']}"},
    {"label": "Neutral", "range": f"{config['vol_regime_threshold_low']} <= VIX <= {config['vol_regime_threshold_high']}"},
    {"label": "High Vol", "range": f"VIX > {config['vol_regime_threshold_high']}"},
]

for item in thresholds:
    st.metric(item["label"], item["range"])

# TODO: Add Plotly heatmap visualization
```

#### Page 3: Latency
```python
"""streamlit_app/pages/3_⏱️_Latency.py"""

import streamlit as st

st.title("⏱️ Agent Latency Metrics")

# Display latency stats (from FastAPI /latency)
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("p99 Latency", "87.3 ms", delta="-12.7 ms")
with col2:
    st.metric("Median Latency", "42.1 ms", delta="-3.2 ms")
with col3:
    st.metric("Target p99", "500 ms", help="Relaxed from 120µs for agent processing")

# TODO: Add time-series chart of latency
```

#### Page 4: Compliance
```python
"""streamlit_app/pages/4_📋_Compliance.py"""

import streamlit as st

st.title("📋 FINRA 3110 Compliance")

# Display audit trail (from FastAPI /compliance)
st.metric("Total Audit Records", "12,456")
st.metric("Crisis Events", "3")
st.metric("FINRA 3110 Compliant", "✅ Yes")
st.metric("WORM Storage Active", "✅ Yes")

# TODO: Add audit log table from Cloud Logging
```

#### Page 5: Config
```python
"""streamlit_app/pages/5_⚙️_Config.py"""

import streamlit as st

st.title("⚙️ Configuration")

# Config update form (from FastAPI POST /update_config)
with st.form("config_form"):
    hedge_ratio = st.number_input("Hedge Ratio", value=0.8, min_value=0.0, max_value=2.0)
    max_position = st.number_input("Max Position", value=1_000_000.0, min_value=0.0)
    vol_low = st.number_input("Vol Regime Low", value=15.0, min_value=0.0)
    vol_high = st.number_input("Vol Regime High", value=30.0, min_value=0.0)
    
    submitted = st.form_submit_button("Update Config")
    if submitted:
        # TODO: Update Firestore config
        st.success("Config updated!")
```

---

### Task 4: Port Rust Tests to Python

#### Test 1: Crisis Protocols
```python
"""tests/unit/test_crisis_protocols.py"""

import pytest
from vertex_agents.tools.crisis_tools import evaluate_crisis

def test_crisis_normal():
    """Port of Rust test: test_crisis_normal (lines 84-87)"""
    assert evaluate_crisis(vix=20.0, depeg_pct=0.0) == "Normal"

def test_crisis_smart_bunker_vix_above_45():
    """Port of Rust test: test_crisis_smart_bunker_vix_above_45 (lines 90-93)"""
    assert evaluate_crisis(vix=50.0, depeg_pct=0.0) == "SmartBunker"

def test_crisis_smart_bunker_vix_boundary():
    """Port of Rust test: test_crisis_smart_bunker_vix_boundary (lines 96-102)"""
    assert evaluate_crisis(vix=45.0, depeg_pct=0.0) == "Normal"
    assert evaluate_crisis(vix=45.01, depeg_pct=0.0) == "SmartBunker"

def test_crisis_surgical_sniper():
    """Port of Rust test: test_crisis_surgical_sniper (lines 105-108)"""
    assert evaluate_crisis(vix=20.0, depeg_pct=6.0) == "SurgicalSniper"

def test_crisis_smart_bunker_takes_precedence():
    """Port of Rust test: test_crisis_smart_bunker_takes_precedence_over_sniper (lines 111-115)"""
    assert evaluate_crisis(vix=50.0, depeg_pct=10.0) == "SmartBunker"
```

#### Test 2: Sleeve Signals
```python
"""tests/unit/test_sleeve_signals.py"""

import pytest
from vertex_agents.tools.sleeve_tools import (
    compute_treasury_basis_signal,
    compute_vol_regime_signal
)

def test_sleeve_treasury_basis_signal_range():
    """Port of Rust test: test_sleeve_treasury_basis_signal_range (lines 122-131)"""
    signal = compute_treasury_basis_signal(
        bid=100.0, ask=100.5, last=100.25, hedge_ratio=0.8
    )
    assert -1.0 <= signal <= 1.0

def test_sleeve_vol_regime_low():
    """Port of Rust test: test_sleeve_vol_regime_low (lines 151-155)"""
    result = compute_vol_regime_signal(vix=10.0, low_threshold=15.0, high_threshold=30.0)
    assert result["signal"] == -1.0
    assert result["regime"] == "Low"

def test_sleeve_vol_regime_high():
    """Port of Rust test: test_sleeve_vol_regime_high (lines 158-162)"""
    result = compute_vol_regime_signal(vix=35.0, low_threshold=15.0, high_threshold=30.0)
    assert result["signal"] == 1.0
    assert result["regime"] == "High"

def test_sleeve_vol_regime_neutral():
    """Port of Rust test: test_sleeve_vol_regime_neutral (lines 165-169)"""
    result = compute_vol_regime_signal(vix=20.0, low_threshold=15.0, high_threshold=30.0)
    assert result["signal"] == 0.0
    assert result["regime"] == "Neutral"
```

#### Test 3: Terra Luna Replay
```python
"""tests/integration/test_terra_luna_replay.py"""

# This test already exists in Python! Just ensure it passes with the new agents.
# File: tests/terra_luna_replay.py (151 lines)

import pytest
from vertex_agents.orchestrator import QuantumProtocolOrchestrator
from vertex_agents.schemas.market_packet import MarketPacket

def test_terra_luna_replay():
    """
    Simulate the May 2022 Terra Luna crash.
    
    Requirements:
    - Smart Bunker must trigger within 1 tick of VIX > 45
    - System must recover to Normal state at end
    - No crashes or breached risk caps
    """
    orchestrator = QuantumProtocolOrchestrator()
    
    # Phase 1: Normal market
    for _ in range(50):
        packet = MarketPacket(vix=18.0, depeg_pct=0.0, bid=100.0, ask=100.05, last=100.02)
        result = orchestrator.process_tick(packet)
        assert result["crisis_state"] == "Normal"
    
    # Phase 2: VIX spike (Terra Luna crash)
    packet = MarketPacket(vix=52.0, depeg_pct=0.0, bid=95.0, ask=96.0, last=95.5)
    result = orchestrator.process_tick(packet)
    assert result["crisis_state"] == "SmartBunker"
    
    # Phase 3: Stablecoin depeg
    packet = MarketPacket(vix=30.0, depeg_pct=8.0, bid=90.0, ask=91.0, last=90.5)
    result = orchestrator.process_tick(packet)
    assert result["crisis_state"] == "SurgicalSniper"
    
    # Phase 4: Recovery
    packet = MarketPacket(vix=22.0, depeg_pct=1.0, bid=98.0, ask=98.5, last=98.25)
    result = orchestrator.process_tick(packet)
    assert result["crisis_state"] == "Normal"
```

---

### Task 5: Setup GCP Integration

#### Pub/Sub Publisher
```python
"""data_sources/pubsub_publisher.py"""

from google.cloud import pubsub_v1
import json

class MarketDataPublisher:
    """Publish market data to GCP Pub/Sub for agent consumption."""
    
    def __init__(self, project_id: str, topic_name: str):
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(project_id, topic_name)
    
    def publish_tick(self, packet: dict):
        """Publish a market data tick to Pub/Sub."""
        message = json.dumps(packet).encode("utf-8")
        future = self.publisher.publish(self.topic_path, message)
        return future.result()
```

#### Firestore Config
```python
"""config/firestore_config.py"""

from google.cloud import firestore

class FirestoreConfig:
    """Manage configuration in Firestore (replaces Rust shared memory)."""
    
    def __init__(self, project_id: str):
        self.db = firestore.Client(project=project_id)
        self.config_ref = self.db.collection("config").document("shared_config")
    
    def get_config(self) -> dict:
        """Read current config (called by agents on each tick)."""
        return self.config_ref.get().to_dict()
    
    def update_config(self, updates: dict):
        """Update config (called from Streamlit UI)."""
        self.config_ref.update(updates)
```

#### Cloud Logging
```python
"""logging/cloud_logging.py"""

from google.cloud import logging as cloud_logging

class AuditLogger:
    """FINRA 3110 audit logging via GCP Cloud Logging."""
    
    def __init__(self, project_id: str):
        self.client = cloud_logging.Client(project=project_id)
        self.logger = self.client.logger("quantum-protocol-audit")
    
    def log_crisis_transition(self, from_state: str, to_state: str, vix: float, depeg_pct: float):
        """Log crisis state transition."""
        self.logger.log_struct({
            "event_type": "CrisisProtocol",
            "from_state": from_state,
            "to_state": to_state,
            "vix": vix,
            "depeg_pct": depeg_pct,
            "finra_3110_compliant": True
        })
    
    def log_sleeve_signal(self, sleeve_id: int, signal_value: float, position_delta: float):
        """Log sleeve signal computation."""
        self.logger.log_struct({
            "event_type": "SleeveSignal",
            "sleeve_id": sleeve_id,
            "signal_value": signal_value,
            "position_delta": position_delta
        })
```

---

## 🎯 Success Criteria

The migration is **SUCCESSFUL** if:

1. ✅ All 26 Rust unit tests pass in Python
2. ✅ Terra Luna Replay test passes (crisis protocols work)
3. ✅ Agent latency p99 < 500ms (within budget)
4. ✅ Streamlit dashboard displays real-time agent decisions
5. ✅ Audit logs meet FINRA 3110 requirements
6. ✅ System survives simulated market crash without crashing
7. ✅ No buy/sell signals exposed to retail users (CTA exemption)

---

## 📊 Performance Targets

| Metric | Rust Engine | Poly-Agent System | Change |
|--------|-------------|-------------------|--------|
| Latency (p99) | <120µs | <500ms | 1000x slower (OK) |
| Throughput | 1M+ ticks/sec | 10-100 ticks/sec | 10,000x slower (OK) |
| Decision Mode | Execution | Analysis | Paradigm shift |

**Rationale:** Agents provide **decision support** for human traders, not microsecond execution. The 1000x latency increase is acceptable because:
- Humans make decisions on **second** timescales
- APIs (IBKR, Alpaca) have 10-100ms latency anyway
- The Rust engine's sub-100µs latency was **aspirational** (not achieved in production)

---

## 🚀 Deliverables

1. ✅ **Vertex AI Agent Code** (`vertex_agents/`)
   - Crisis Protocol Agent
   - Treasury Basis Agent
   - Vol Regime Agent
   - Orchestrator

2. ✅ **Streamlit Dashboard** (`streamlit_app/`)
   - 5 pages (Dashboard, Heatmaps, Latency, Compliance, Config)
   - Auto-refresh every 5 seconds
   - No buy/sell signals (CTA exemption)

3. ✅ **Test Suite** (`tests/`)
   - Port all 26 Rust unit tests
   - Add Vertex AI integration tests
   - Ensure Terra Luna Replay passes

4. ✅ **GCP Integration** (`data_sources/`, `config/`, `logging/`)
   - Pub/Sub for market data
   - Firestore for config management
   - Cloud Logging for FINRA audit trail

5. ✅ **Documentation** (`docs/`)
   - Migration guide (Rust → Python)
   - Architecture diagram
   - API reference

---

## ⚠️ Critical Constraints

### 1. **Preserve Exact Logic**
- Do NOT "improve" the crisis thresholds (VIX > 45, depeg > 5%)
- Do NOT "optimize" the sleeve signal formulas
- Port **exactly** as written in Rust

### 2. **FINRA Compliance**
- All agent decisions MUST be auditable
- Audit records MUST match Rust `AuditRecord` schema
- Logs MUST be WORM (use BigQuery retention policies)

### 3. **CTA Exemption**
- Streamlit dashboard MUST NOT show buy/sell signals
- Only show "coarsened market context" and "risk regime"
- No direct execution recommendations

### 4. **Testing**
- Terra Luna Replay test is **non-negotiable**
- Must pass before deployment
- Simulates May 2022 crash timeline

---

## 🧠 What Makes This Migration Feasible

1. **Pure Functions:** Rust code is already decomposed into stateless functions
2. **No Real Concurrency:** SPSC rings are single-threaded, no distributed locks
3. **Simple Logic:** Only 8 FLOPs in the hot path (trivial to port)
4. **70% Already Python:** Dashboard and tests already exist
5. **No Exotic Dependencies:** No kernel bypass, no hardware-specific code

---

## 📝 Final Notes

**What to Preserve:**
- ✅ Exact crisis evaluation logic
- ✅ Sleeve signal formulas
- ✅ Audit trail structure
- ✅ Terra Luna Replay test

**What to Discard:**
- ❌ Sub-100µs latency requirement
- ❌ SPSC ring buffer (use Pub/Sub)
- ❌ Shared memory IPC (use Firestore)
- ❌ UDP multicast (use REST/WebSocket)

**Estimated Timeline:** 14-24 days (2-4 weeks) with Opus 4.6 assistance

---

**Good luck!** 🚀

You have all the context you need. Start with Task 1 (Agent Tools), validate with Task 4 (Tests), then build Task 2 (Orchestrator) and Task 3 (Streamlit). GCP integration (Task 5) comes last.
