# QUANTUM PROTOCOL

**Owner:** Calculus Holdings LLC
**Status:** Post-Migration — Pure Async Python Engine
**Tests:** 545 passing

---

## Architecture

QUANTUM PROTOCOL is an autonomous multi-sleeve trading engine with crisis protocols, FINRA 3110 compliance, and regime-aware portfolio orchestration.

```
Market Data (Alpaca REST / IBKR)
        │
        ▼
┌─────────────────────────────────┐
│  QuantumEngine (brain/engine.py)│
│  ┌───────────────────────────┐  │
│  │ SERAPH AI Regime Detector │  │  Classifies: Growth / Compression / Volatile / Crisis
│  └───────────┬───────────────┘  │
│  ┌───────────▼───────────────┐  │
│  │ Permission Vector Broadcast│  │  Master → Slave bias per regime
│  └───────────┬───────────────┘  │
│  ┌───────────▼───────────────┐  │
│  │ Crisis Protocols v9.3     │  │  SmartBunker (VIX>45) / SurgicalSniper (VIX>35)
│  └───────────┬───────────────┘  │
│  ┌───────────▼───────────────┐  │
│  │ 5-Sleeve Signal Generation│  │  Treasury / Curve / Prop / RWA(deferred) / Hedge
│  └───────────┬───────────────┘  │
│  ┌───────────▼───────────────┐  │
│  │ Risk Overlay + Kill Switch│  │  Flattens/reduces signals per crisis level
│  └───────────┬───────────────┘  │
│              │                  │
│  Audit Logger (FINRA 3110 WORM)│
└──────────────┼──────────────────┘
               ▼
     IBKR Order Manager
     (Paper / Live execution)
```

### Layers

| Layer | Stack | Purpose |
|---|---|---|
| Engine | Python 3.11 + asyncio | Tick loop, orchestration, signal generation |
| Retail Dashboard | FastAPI (port 8000) | CTA-exempt coarsened signals for retail |
| Internal Dashboard | Streamlit (port 8501) | Full signals, risk monitor, SERAPH AI |
| Execution | ib_insync → IBKR | Paper + live order submission |
| Quantum Oracle | Python (offline) | QAOA/VQE weight optimization (2028 roadmap) |

---

## Trading Sleeves

| Sleeve | Name | Allocation | Status |
|---|---|---|---|
| 1 | Treasury Yield | 10% | Active |
| 2 | Compression & Curve | 15% | Active |
| 3 | Prop Scaling | 45% | Active (fan-out to 20+ prop accounts) |
| 4 | RWA Infrastructure | 0% | Deferred to v1.5 |
| 5 | Convexity Shield | 10% | Active (tail hedge) |
| — | Cash Reserve | 20% | — |

---

## Crisis Protocols (v9.3)

| Level | VIX Threshold | Action |
|---|---|---|
| Normal | < 20 | Full signal passthrough |
| Elevated | 20–28 | No adjustment (monitoring) |
| Severe | 28–35 | Reduce all signals 25% |
| SurgicalSniper | 35–45 | Reduce all signals 50% |
| SmartBunker | > 45 | Flatten all except Sleeve 5 (hedge) |

De-escalation requires 5 consecutive ticks below threshold.

---

## SERAPH AI

Deterministic regime classifier (no ML, no GPU, no external APIs).

- **Regimes:** Growth, Compression, Volatile, Crisis
- **Signals:** VIX level, ADX trend strength, SPX 20-day return
- **Output:** Quarterly rebalancing recommendations + permission vector biases
- **Confidence:** 0.0–1.0 based on signal alignment

---

## Latency Architecture

### Current Stack (Tier 1 Optimized)

```
Market Data Source (Alpaca/IBKR)     ~100-1500ms  (parallel fetch, 1.5s timeout)
        │
  QuantumEngine tick processing      ~0.5-1ms     (orchestrator + risk overlay)
        │
  IBKR Order Submission              ~50-100ms
        │
  Tick Interval                      10s default   (configurable)
```

**Signal latency (market move → order):** 0–12 seconds

### Optimizations Applied

| Optimization | Before | After |
|---|---|---|
| Price fetch | 5 sequential × 5s = 25s | 5 parallel × 1.5s = 1.5s |
| Contract qualification | Every request (100-200ms) | Cached per session (0ms) |
| Price timeout fallback | None (return null) | Last-known price returned |
| Tick interval | 60s | 10s |
| Latency logging | None | Per-tick feed/orch/total ms |

### Future Tiers (Not Yet Implemented)

- **Tier 2:** IBKR WebSocket streaming (30-100ms data latency, event-driven ticks)
- **Tier 3:** FIX protocol bridge, order pipelining (sub-500ms end-to-end)

---

## Kill Switch

Latching circuit breaker — stays active until manual operator reset.

| Trigger | Threshold |
|---|---|
| Daily PnL loss | > 2% of portfolio |
| Position concentration | > 25% in single symbol |
| Consecutive order rejections | > 5 |
| Heartbeat timeout | > 30 seconds |

---

## Project Structure

```
brain/                          # Core trading engine (Calculus IP)
├── engine.py                   # Main entry point (python -m brain.engine)
├── orchestrator.py             # Tick loop: SERAPH → signals → risk → positions
├── feeds/market_data.py        # Market data feeds (Mock, Alpaca, IBKR)
├── execution/
│   ├── ibkr_client.py          # IBKR TWS/Gateway connection
│   └── order_manager.py        # Position reconciliation + order submission
├── risk/
│   ├── crisis_protocols.py     # Crisis state machine (v9.3)
│   ├── kill_switch.py          # Latching kill switch
│   └── permission_vector.py    # Master→Slave regime gating
├── strategies/
│   ├── seraph_ai.py            # Regime classifier
│   ├── sleeve1_treasury_yield.py
│   ├── sleeve2_compression_curve.py
│   ├── sleeve3_prop_scaling.py
│   └── sleeve5_convexity_shield.py
├── compliance/audit_logger.py  # FINRA 3110 JSONL audit trail
├── dashboard/                  # Streamlit internal dashboard (5 pages)
│   ├── app.py
│   └── pages/
└── paper_trading_runner.py     # IBKR paper trading validation

src/dashboard/                  # FastAPI retail dashboard (CTA-exempt)
├── app.py
└── tests/

config/quantum_protocol.toml   # Engine configuration
tests/                          # Integration + parity tests
```

---

## Running

### Engine
```bash
# With mock data (development)
PYTHONPATH=. python -m brain.engine

# With IBKR paper trading
python brain/paper_trading_runner.py
```

### Dashboards
```bash
# FastAPI retail (CTA-exempt)
uvicorn src.dashboard.app:app --port 8000

# Streamlit internal
streamlit run brain/dashboard/app.py --server.port 8501
```

### Docker
```bash
docker-compose up --build
# Engine: localhost:8000, Dashboard: localhost:8501, Grafana: localhost:3000
```

### Tests
```bash
# Full suite (545 tests)
pytest tests/ src/dashboard/tests/ brain/tests/ -v

# Terra Luna crisis replay
pytest tests/test_terra_luna_full.py -v

# Integration tests
pytest tests/test_integration.py -v
```

---

## CI/CD

GitHub Actions runs 4 parallel jobs on every push/PR to main:

1. **Python Engine** — parity tests, engine state, market data, Terra Luna replay
2. **Python Platform** — FastAPI dashboard tests
3. **Brain Tests** — sleeve strategies, risk, dashboard state
4. **Quantum Oracle** — classical optimization fallback

---

## Compliance

- **CTA Exemption:** Retail dashboard shows heatmaps and latency metrics only — no Buy/Sell signals
- **FINRA 3110:** JSONL audit trail, WORM-style append-only, 7-year retention (2555 days)
- **Kill Switch:** Manual operator reset required (dual-key in production)

---

## GO/NO-GO Criteria (Paper Trading)

| Criteria | Threshold |
|---|---|
| Max drawdown | < 5% |
| Sharpe ratio | > 0.5 (annualized) |
| Kill switch fires | 0 (never needed) |
| All sleeves active | Every sleeve generates signals |
| Heartbeat timeouts | 0 |
| Connection drops | < 3/day |
| Validation period | 10 trading days |

---

## Ownership

All repositories under this organization are property of **Calculus Holdings LLC**.
Brain Layer / alpha-generation code is 100% Calculus exclusive IP.
