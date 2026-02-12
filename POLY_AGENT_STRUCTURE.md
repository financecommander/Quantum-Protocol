# Quantum Protocol Poly-Agent Architecture
## Proposed Folder Structure

```
quantum-protocol-polyagent/
│
├── README.md                           # Architecture overview & quick start
├── requirements.txt                    # Python dependencies
├── pyproject.toml                      # Modern Python project config (Poetry/uv)
├── .env.example                        # Environment variables template
├── .gitignore                          # Ignore venv, __pycache__, secrets
│
├── vertex_agents/                      # 🤖 Vertex AI Agent Components
│   ├── __init__.py
│   ├── crisis_protocol_agent.py        # Autonomous crisis detection
│   ├── treasury_basis_agent.py         # Sleeve 1: Treasury arbitrage
│   ├── vol_regime_agent.py             # Sleeve 2: Volatility classification
│   ├── orchestrator.py                 # Main agent coordinator
│   │
│   ├── tools/                          # Agent tool implementations
│   │   ├── __init__.py
│   │   ├── crisis_tools.py             # evaluate_crisis(), log_transition()
│   │   ├── sleeve_tools.py             # compute_treasury_basis(), compute_vol_regime()
│   │   ├── audit_tools.py              # FINRA 3110 compliance logging
│   │   └── market_data_tools.py        # fetch_vix(), compute_depeg()
│   │
│   └── schemas/                        # Pydantic models for type safety
│       ├── __init__.py
│       ├── market_packet.py            # MarketPacket schema (port from Rust)
│       ├── audit_record.py             # AuditRecord schema
│       └── config.py                   # SharedConfig schema
│
├── streamlit_app/                      # 📊 Streamlit Dashboard (replaces FastAPI)
│   ├── app.py                          # Main entry point
│   │
│   ├── pages/                          # Multi-page Streamlit app
│   │   ├── 1_📊_Dashboard.py           # Coarsened market context (NO buy/sell signals)
│   │   ├── 2_🔥_Heatmaps.py           # Volatility regime visualizations
│   │   ├── 3_⏱️_Latency.py            # Agent processing time metrics
│   │   ├── 4_📋_Compliance.py         # FINRA 3110 audit trail viewer
│   │   └── 5_⚙️_Config.py             # Parameter tuning (hedge ratio, thresholds)
│   │
│   ├── components/                     # Reusable Streamlit components
│   │   ├── __init__.py
│   │   ├── crisis_state_badge.py       # Colored badge for crisis state
│   │   ├── signal_chart.py             # Time-series chart for signals
│   │   ├── audit_table.py              # Formatted audit log table
│   │   └── config_form.py              # Config update form
│   │
│   └── styles/                         # Custom CSS
│       └── dashboard.css               # Streamlit theme customization
│
├── data_sources/                       # 📡 Market Data Ingestion
│   ├── __init__.py
│   ├── polygon_client.py               # Polygon.io REST + WebSocket client
│   ├── alpaca_client.py                # Alpaca Markets API client
│   ├── simulator.py                    # Terra Luna crash simulator (for testing)
│   └── pubsub_publisher.py             # GCP Pub/Sub integration
│
├── config/                             # ⚙️ Configuration Management
│   ├── __init__.py
│   ├── firestore_config.py             # GCP Firestore backend
│   ├── local_config.py                 # Local JSON file fallback
│   ├── default_config.yaml             # Default parameter values
│   └── config_schema.py                # Pydantic validation
│
├── logging/                            # 📝 Audit & Compliance Logging
│   ├── __init__.py
│   ├── cloud_logging.py                # GCP Cloud Logging client
│   ├── bigquery_sink.py                # Stream audit logs to BigQuery (WORM)
│   └── audit_ring.py                   # In-memory ring buffer (port from Rust)
│
├── tests/                              # 🧪 Test Suite
│   ├── __init__.py
│   │
│   ├── unit/                           # Unit tests (port from Rust)
│   │   ├── test_crisis_protocols.py    # Port from src/engine/tests.rs:84-115
│   │   ├── test_sleeve_signals.py      # Port from src/engine/tests.rs:120-185
│   │   ├── test_audit_ring.py          # Port from src/engine/tests.rs:248-285
│   │   └── test_config.py              # Port from src/engine/tests.rs:315-322
│   │
│   ├── integration/                    # Integration tests
│   │   ├── test_terra_luna_replay.py   # Port from tests/terra_luna_replay.py
│   │   ├── test_agent_orchestration.py # Verify agent coordination
│   │   ├── test_pubsub_pipeline.py     # Pub/Sub → Agent → Logging
│   │   └── test_firestore_config.py    # Config updates propagate correctly
│   │
│   ├── e2e/                            # End-to-end tests
│   │   ├── test_streamlit_ui.py        # Selenium tests for dashboard
│   │   └── test_full_pipeline.py       # Market data → Agents → Dashboard
│   │
│   └── fixtures/                       # Test data
│       ├── market_data_normal.json     # Normal market conditions
│       ├── market_data_crisis.json     # Terra Luna crash scenario
│       └── audit_records_sample.json   # Sample audit trail
│
├── deployment/                         # ☁️ GCP Deployment
│   ├── cloudbuild.yaml                 # CI/CD pipeline config
│   ├── cloud_run/
│   │   ├── streamlit_service.yaml      # Cloud Run service definition
│   │   └── Dockerfile                  # Container for Streamlit app
│   ├── vertex_ai/
│   │   ├── agent_deploy.py             # Deploy agents to Vertex AI
│   │   └── agent_config.yaml           # Agent parameters
│   ├── terraform/                      # Infrastructure as Code
│   │   ├── main.tf                     # GCP resources (Pub/Sub, Firestore, etc.)
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── scripts/
│       ├── deploy_all.sh               # One-click deployment
│       └── rollback.sh                 # Rollback script
│
├── docs/                               # 📚 Documentation
│   ├── MIGRATION_GUIDE.md              # Rust → Python porting guide
│   ├── ARCHITECTURE.md                 # Poly-Agent design document
│   ├── COMPLIANCE.md                   # FINRA 3110 audit procedures
│   ├── API_REFERENCE.md                # Agent tool API documentation
│   ├── DEPLOYMENT.md                   # GCP deployment instructions
│   └── TESTING.md                      # Testing strategy & guidelines
│
├── notebooks/                          # 📓 Jupyter Notebooks (Analysis)
│   ├── 01_crisis_protocol_analysis.ipynb
│   ├── 02_sleeve_signal_backtesting.ipynb
│   └── 03_latency_profiling.ipynb
│
└── scripts/                            # 🔧 Utility Scripts
    ├── migrate_rust_tests.py           # Auto-generate Python tests from Rust
    ├── generate_agent_tools.py         # Scaffold Vertex AI Agent tools
    ├── benchmark_agents.py             # Measure agent latency
    └── simulate_market_data.py         # Generate test market data
```

---

## Key Design Principles

### 1. **Separation of Concerns**
- **Agents** (`vertex_agents/`) — Pure decision logic
- **Dashboard** (`streamlit_app/`) — Visualization & monitoring
- **Data Sources** (`data_sources/`) — Market data ingestion
- **Config** (`config/`) — Centralized parameter management
- **Logging** (`logging/`) — FINRA compliance audit trail

### 2. **Testability**
- Unit tests for every agent tool
- Integration tests for agent coordination
- E2E tests for full pipeline (market data → agents → dashboard)
- Port all 26 Rust unit tests to Python

### 3. **Observability**
- All agent decisions logged to GCP Cloud Logging
- Latency metrics tracked for each agent invocation
- Streamlit dashboard shows real-time agent state
- BigQuery sink for long-term audit trail storage

### 4. **Portability**
- Pure Python (no Rust compilation required)
- Docker containers for easy deployment
- Terraform for reproducible infrastructure
- Environment variables for secrets (no hardcoded credentials)

### 5. **Compliance**
- FINRA 3110: All decision logic auditable
- CTA Exemption: No buy/sell signals in dashboard
- WORM Storage: BigQuery retention policies
- Dual-key restart: Config updates require approval

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **Agents** | Vertex AI Agents | Managed AI execution environment |
| **Dashboard** | Streamlit | Interactive UI with minimal boilerplate |
| **Market Data** | Polygon.io / Alpaca | Production-grade market data APIs |
| **Message Queue** | GCP Pub/Sub | Managed message broker |
| **Config Store** | Firestore | Real-time NoSQL database |
| **Logging** | Cloud Logging + BigQuery | WORM compliance |
| **Deployment** | Cloud Run | Serverless container hosting |
| **IaC** | Terraform | Reproducible infrastructure |
| **Testing** | pytest + Selenium | Python-native testing |

---

## Migration Checklist

- [ ] **Phase 1: Core Logic Migration**
  - [ ] Port `evaluate_crisis()` to Python
  - [ ] Port `sleeve_treasury_basis()` to Python
  - [ ] Port `sleeve_vol_regime()` to Python
  - [ ] Port Rust unit tests to pytest

- [ ] **Phase 2: Agent Development**
  - [ ] Create Crisis Protocol Agent
  - [ ] Create Treasury Basis Agent
  - [ ] Create Vol Regime Agent
  - [ ] Implement Orchestrator

- [ ] **Phase 3: Data Pipeline**
  - [ ] Integrate Polygon.io WebSocket
  - [ ] Setup GCP Pub/Sub
  - [ ] Implement market data simulator
  - [ ] Configure Firestore for config management

- [ ] **Phase 4: Dashboard**
  - [ ] Migrate FastAPI endpoints to Streamlit pages
  - [ ] Implement real-time agent state visualization
  - [ ] Add latency metrics dashboard
  - [ ] Add FINRA audit trail viewer

- [ ] **Phase 5: Testing**
  - [ ] Port Terra Luna Replay test
  - [ ] Add agent integration tests
  - [ ] Add E2E pipeline tests
  - [ ] Verify FINRA compliance

- [ ] **Phase 6: Deployment**
  - [ ] Create Docker containers
  - [ ] Setup Cloud Run service
  - [ ] Deploy Vertex AI Agents
  - [ ] Configure monitoring & alerts

- [ ] **Phase 7: Documentation**
  - [ ] Write migration guide
  - [ ] Document agent API
  - [ ] Create deployment runbook
  - [ ] Update compliance procedures

---

## Estimated Timeline

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| 1. Core Logic | 3-5 days | Python functions + tests |
| 2. Agents | 3-5 days | Vertex AI Agent tools |
| 3. Data Pipeline | 2-4 days | Pub/Sub + Firestore |
| 4. Dashboard | 2-3 days | Streamlit app (5 pages) |
| 5. Testing | 2-3 days | Full test suite |
| 6. Deployment | 1-2 days | GCP infrastructure |
| 7. Documentation | 1-2 days | Migration guide + API docs |

**Total:** 14-24 days (2-4 weeks)

---

## Success Metrics

✅ **Migration is successful if:**
1. All 26 Rust unit tests pass in Python
2. Terra Luna Replay test validates crisis protocols
3. Agent latency p99 < 500ms
4. Streamlit dashboard displays real-time decisions
5. Audit logs meet FINRA 3110 requirements
6. System survives simulated market crash
7. No buy/sell signals exposed to retail users (CTA exemption)

---

## Next Steps

1. **Review** this structure with the development team
2. **Approve** the technology stack choices
3. **Allocate** resources (1-2 engineers + Opus 4.6)
4. **Kickoff** Phase 1: Core Logic Migration
5. **Iterate** on agent designs based on testing

---

**Prepared by:** Principal Software Architect & Rust Specialist  
**Date:** 2026-02-12  
**Status:** Ready for Implementation
