# Quantum Protocol Documentation

Welcome to the Quantum Protocol documentation! This directory contains comprehensive guides for deploying, operating, and testing the system.

## Quick Start Guide

If you're new to Quantum Protocol, follow this sequence:

1. **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** - Set up and deploy the system
2. **[API_KEYS_SETUP.md](./API_KEYS_SETUP.md)** - Configure all required API keys
3. **[TESTING_PLAN.md](./TESTING_PLAN.md)** - Validate with paper trading
4. **[OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md)** - Daily operations reference

## Core Documentation

### 🚀 [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)
**How to deploy the Quantum Protocol system**

- **Docker Compose deployment** (recommended for production)
- **Direct binary deployment** (for specialized hardware)
- **Cloud deployment** (GCP with GPU support)
- Environment variables reference
- Configuration checklist
- Post-deployment verification
- Security considerations

**Key Topics**: Docker setup, environment variables, configuration, hot reload, troubleshooting deployment issues

---

### 🔧 [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md)
**Day-to-day operations and troubleshooting**

- System start/stop procedures
- Monitoring endpoints and dashboards
- Troubleshooting common issues
- Emergency procedures
- Daily operations checklists
- Performance optimization
- Compliance and audit

**Key Topics**: Start/stop procedures, monitoring (Prometheus, Grafana), troubleshooting (latency, kill switch, feeds), emergency procedures, FINRA compliance

---

### 🔑 [API_KEYS_SETUP.md](./API_KEYS_SETUP.md)
**Configure API keys and credentials**

- Alpaca API keys (market data & execution)
- Interactive Brokers master account
- Market data feed providers
- Slack webhooks for alerts
- Email alerts (SMTP)
- Security best practices
- Cost breakdown

**Key Topics**: API key setup for Alpaca, IBKR, Polygon.io, Slack, email; security best practices; key rotation

---

### ✅ [TESTING_PLAN.md](./TESTING_PLAN.md)
**Validate system before production**

- 5-phase testing approach
- Terra Luna replay test
- Latency benchmarks (p99 < 120µs)
- Paper trading protocol
- Metrics to monitor
- Go/no-go decision criteria
- Live trading scaling

**Key Topics**: Unit tests, integration tests, paper trading (79% win rate target), go/no-go decision framework, live trading protocol

---

## Technical Documentation

### 📚 [INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)
Complete integration guide for all system components

### 📋 [INTEGRATION_CHECKLIST.md](./INTEGRATION_CHECKLIST.md)
Step-by-step integration checklist

### 📊 [FILE_INVENTORY.md](./FILE_INVENTORY.md)
Inventory of all codebase files

## Trading Sleeves Documentation

### 🎯 [SLEEVES_README.md](./SLEEVES_README.md)
Overview of all 5 trading sleeves

### 📈 [PROP_SCALING_GUIDE.md](./PROP_SCALING_GUIDE.md)
Proprietary account scaling (Sleeve 3)

### ⚡ [RWA_CRYPTO_HFT_GUIDE.md](./RWA_CRYPTO_HFT_GUIDE.md)
RWA/Crypto HFT arbitrage (Sleeve 4)

### 🛡️ [TAIL_HEDGING_GUIDE.md](./TAIL_HEDGING_GUIDE.md)
Tail hedging and crisis protocols (Sleeve 5)

## Document Index by Use Case

### "I want to deploy the system"
→ [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)

### "I need to set up API keys"
→ [API_KEYS_SETUP.md](./API_KEYS_SETUP.md)

### "I need to start/stop the system"
→ [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md#system-startstop-procedures)

### "I want to monitor the system"
→ [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md#monitoring-endpoints)

### "Something is broken, how do I fix it?"
→ [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md#troubleshooting-common-issues)

### "I need to test before going live"
→ [TESTING_PLAN.md](./TESTING_PLAN.md)

### "How do I know if the system is ready for production?"
→ [TESTING_PLAN.md](./TESTING_PLAN.md#phase-4-production-validation-gono-go-decision)

### "What are the crisis protocols?"
→ [TAIL_HEDGING_GUIDE.md](./TAIL_HEDGING_GUIDE.md)

### "How does prop account scaling work?"
→ [PROP_SCALING_GUIDE.md](./PROP_SCALING_GUIDE.md)

## Key Metrics and Targets

| Metric | Target | Source |
|--------|--------|--------|
| **Win Rate** | ≥ 79% | [TESTING_PLAN.md](./TESTING_PLAN.md) |
| **p99 Latency** | < 100µs (120µs max) | [TESTING_PLAN.md](./TESTING_PLAN.md) |
| **Uptime** | 99.9% | [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md) |
| **Audit Retention** | 2555 days (7 years) | [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md#compliance-and-audit) |

## Quick Reference Commands

### Check System Health
```bash
docker-compose ps
curl http://localhost:9090/metrics | grep quantum_
curl http://localhost:8000/latency
```

### View Logs
```bash
docker-compose logs -f engine
tail -f /var/log/quantum/audit_$(date +%Y-%m-%d).jsonl
```

### Run Tests
```bash
cargo test                          # Unit tests
python tests/terra_luna_replay.py  # Crisis protocol test
cargo bench --bench latency_bench  # Latency benchmark
```

### Emergency Stop
```bash
docker-compose stop engine
```

## Support Resources

- **Main README**: [../README.md](../README.md)
- **GitHub Issues**: Report bugs and feature requests
- **Architecture Docs**: See main README for system architecture

## Document Versions

All documentation is version-controlled with the codebase. The documentation reflects the current state of the system.

**Last Updated**: See Git commit history

## Contributing to Documentation

When updating documentation:

1. Keep examples up-to-date with code
2. Test all command examples
3. Update version numbers and dates
4. Cross-reference related documents
5. Maintain consistent formatting
6. Include realistic examples

---

**Need help?** Start with the [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) and [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md) for most common tasks.
