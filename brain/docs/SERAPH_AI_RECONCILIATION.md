# SERAPH AI™ — Thesis vs Reality Reconciliation

## What the Thesis Describes (Full MARL Stack)

```
Orchestrator (Top-Level Brain)
├── Trend Agent (Sleeves 2/3: Momentum)
├── Vol Agent (Sleeve 5: Risk)  
├── Yield Agent (Sleeves 1/4: Income)
├── Eval Agent (Sleeve 3: Scaling)
└── Watcher Agent (1,000 Monte Carlo paths)
```

- Ray parallelization + Kafka message bus
- 128+ feature state space
- RF classifier (91% OOS accuracy)
- PuLP linear optimizer for weight allocation
- Daily walk-forward MARL training
- 1,000 sovereign simulation paths per cycle
- Pinecone RAG for compliance/rulebook
- SHAP explainability on every decision
- Human approval gate for >20% allocation shifts

## What v1.0 Actually Has

```
Orchestrator (deterministic)
├── SeraphAI regime classifier (VIX + trend → 4 regimes)
├── CrisisProtocol (5-level state machine from VIX thresholds)
├── KillSwitch (4 triggers, latching)
└── Sleeve strategies (hard-coded entry/exit rules)
```

- No Ray, no Kafka, no PuLP
- ~5 features (VIX, SPX, TNX, DXY, trend_strength)
- Threshold-based classifier (not RF/ML)
- Fixed allocation weights (not optimized per cycle)
- No Monte Carlo paths
- No RAG, no Pinecone
- No MARL training loop

## Gap Analysis: 8 SERAPH AI Features

| # | Feature | Thesis | v1.0 | Gap |
|---|---------|--------|------|-----|
| 1 | Master-Slave hierarchy | Hourly master → 1-min slave gating | Single tick loop, no dual timeframe | LARGE |
| 2 | PuLP weight optimizer | Optimal allocation per cycle | Fixed allocation table | MEDIUM |
| 3 | RAG tool integration | Pinecone for tax/rulebook | None | DEFER to v2.0 |
| 4 | KPI Guard (DD veto) | Shield Agent vetoes DD >5% | Kill switch at 2% daily | PARTIAL — enhance |
| 5 | Regime classifier | RF 91% accuracy, 128 features | VIX threshold + trend, ~4 features | MEDIUM |
| 6 | Watcher Agent | 1,000 Monte Carlo paths, >2σ drift flag | None | DEFER to v1.5 |
| 7 | Human approval loop | Manual gate for >20% shifts | None | EASY to add |
| 8 | ARIMA Oracle | Vol forecast → pre-emptive tail boost | VIX threshold only | DEFER to v1.5 |

## What We CAN Pull Into v1.0 (Low-Cost, High-Impact)

### 1. Regime-Based Allocation Shifts (from thesis §3)

The thesis defines specific allocation adjustments per regime:
- **Growth**: +15% to Prop/RWA (Sleeve 3 boost)
- **Stress**: +12% to Tail/Yield (Sleeve 5 + Sleeve 1)
- **Transition**: +5-10% to Curve (Sleeve 2)

Our SeraphAI module already does this with VIX + trend classification.
**Status: IMPLEMENTED** (seraph_ai.py)

### 2. Permission Vector Broadcast

The thesis describes hourly JSON broadcasts:
```json
{"regime": "growth", "prop_bias": 1.15, "tail_bias": 0.9}
```

We can implement this as a dataclass that the orchestrator passes to sleeves.
**Status: EASY — add to orchestrator tick cycle**

### 3. Enhanced KPI Guard

Thesis: "Veto if projected DD >5% monthly"
Current: Kill switch triggers at 2% daily loss

Enhancement: Track rolling 20-day P&L and veto new positions if on track
for >5% monthly drawdown. This is a SHIELD enforcement, not a kill switch.
**Status: MEDIUM — add DrawdownTracker to risk layer**

### 4. Human Approval Gate

Thesis: "Human approval for >20% allocation shifts"
Implementation: If SeraphAI recommends shifting >20% between sleeves,
log the recommendation and wait for CEO confirmation via dashboard.
**Status: EASY — add threshold check + dashboard notification**

## What Stays v1.5 / v2.0

### v1.5 (Month 3-6)
- Dual-timeframe gating (hourly master → 1-min slave)
- ARIMA volatility forecast (Oracle Agent)
- Monte Carlo simulator (start with 100 paths, not 1000)
- GARCH vol targeting (replace threshold-based sizing)

### v2.0 (Month 6-12)
- Full MARL training loop (Ray + Kafka)
- RF classifier trained on live data (replace thresholds)
- PuLP weight optimization (replace fixed allocations)
- Pinecone RAG for compliance
- SHAP explainability dashboard
- Sovereign simulation (1,000 paths)

## Honest Assessment

The thesis document describes a **target-state system** that would take 6-12 months
and significant compute budget to build properly. The key insight:

> "SERAPH AI™ is not execution ML; it's the regime-orchestrator that gates the Engine."

This means v1.0's deterministic regime classifier + threshold-based gating is a
**functionally correct approximation** of SERAPH AI's role. It does the same job
(classify regime → adjust allocations → gate sleeve execution) with simpler mechanics.

The 91% RF classifier accuracy claim needs validation — we don't have the training
data or feature set documented. But the regime shift concept (+14% uplift from
dynamic allocation) is sound and testable once we have live data.

**Bottom line**: The deterministic v1.0 captures ~70% of SERAPH's value. The remaining
30% (ML-driven optimization, Monte Carlo validation, MARL training) is the v2.0 moat
that justifies the thesis's institutional pitch.
