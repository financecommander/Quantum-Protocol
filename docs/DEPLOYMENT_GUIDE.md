# Quantum Protocol - Deployment Guide

## Overview

This guide covers deployment of the Quantum Protocol hybrid HFT system, including both Layer 1 (Rust Engine) and Layer 2 (Python Platform), along with the full monitoring stack (Prometheus + Grafana).

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Quantum Protocol Stack                    │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Rust Engine          (Port 9999 UDP, 9090 HTTP)   │
│  Layer 2: Python Platform       (Port 8000)                  │
│  Monitoring: Prometheus         (Port 9091)                  │
│  Visualization: Grafana         (Port 3000)                  │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

### Required Software
- **Docker**: Version 20.10+ with Docker Compose v2
- **Rust**: 1.77+ (for building from source)
- **Python**: 3.11+ (for platform development)
- **Git**: For repository management

### System Requirements
- **CPU**: 8+ cores recommended (pinning core 12 for Splunk Forwarder)
- **RAM**: 16GB minimum, 32GB recommended
- **Network**: Low-latency network interface (Solarflare/Arista for production)
- **Storage**: 500GB minimum (for audit logs with 7-year retention)

## Deployment Methods

### Method 1: Docker Compose (Recommended)

This is the simplest and recommended method for production deployment.

#### Step 1: Clone Repository
```bash
git clone https://github.com/financecommander/Quantum-Protocol.git
cd Quantum-Protocol
```

#### Step 2: Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Required API Keys
QP_API_KEY=your_market_data_api_key
QP_SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
QP_ALERT_EMAIL=alerts@yourcompany.com
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
IBKR_MASTER_ACCOUNT=your_ibkr_master_account_id

# Grafana credentials
GRAFANA_PASSWORD=your_secure_password

# Optional: Rust logging level
RUST_LOG=info
```

**Security Note**: Never commit the `.env` file to version control. It's already in `.gitignore`.

#### Step 3: Review Configuration

Edit `config/quantum_protocol.toml` to adjust trading parameters:

```toml
[engine]
udp_addr = "0.0.0.0:9999"
max_position = 1000000.0
hedge_ratio = 0.8
circuit_breaker_enabled = true

[risk]
max_daily_loss = 50000.0
max_position_per_symbol = 100000.0
max_portfolio_position = 5000000.0
```

See the [Configuration Checklist](#configuration-checklist) below for details.

#### Step 4: Deploy the Stack

```bash
docker-compose up -d
```

This starts:
- **engine**: Rust HFT engine on UDP port 9999, metrics on HTTP port 9090
- **prometheus**: Metrics database on port 9091
- **grafana**: Visualization dashboard on port 3000

#### Step 5: Verify Deployment

```bash
# Check all services are running
docker-compose ps

# Check engine health
curl http://localhost:9090/metrics

# Check engine logs
docker-compose logs -f engine

# Access Grafana dashboard
# Navigate to http://localhost:3000
# Login: admin / <GRAFANA_PASSWORD from .env>
```

### Method 2: Direct Binary Deployment

For advanced users or specialized hardware (e.g., kernel bypass with OpenOnload).

#### Step 1: Build the Engine

```bash
cargo build --release
```

The binary will be at `target/release/quantum-engine`.

#### Step 2: Deploy to Target Host

```bash
# Local deployment
./scripts/deploy.sh localhost

# Remote deployment
./scripts/deploy.sh user@production-host
```

#### Step 3: Run the Engine

On the target host:

```bash
export QP_UDP_ADDR=0.0.0.0:9999
export RUST_LOG=info
export QP_API_KEY=your_api_key
export QP_SLACK_WEBHOOK=your_webhook
export QP_ALERT_EMAIL=your_email
export ALPACA_API_KEY=your_alpaca_key
export ALPACA_SECRET_KEY=your_alpaca_secret
export IBKR_MASTER_ACCOUNT=your_ibkr_account

./quantum-engine
```

### Method 3: Cloud Deployment (GCP)

For GPU-enabled quantum oracle development (Layer 3).

```bash
# Provision GCP VM with GPU support
./scripts/setup_gcp_vm.sh

# SSH to the instance and deploy via Docker Compose
```

## Configuration Checklist

Review and configure all sections in `config/quantum_protocol.toml`:

### Engine Settings
- [ ] `udp_addr`: Network address for UDP market data ingestion
- [ ] `max_position`: Maximum position size
- [ ] `hedge_ratio`: Default hedging ratio (0.0-2.0)
- [ ] `circuit_breaker_enabled`: Enable/disable circuit breaker
- [ ] `heartbeat_max_lag_us`: Maximum heartbeat lag in microseconds (target: <100µs)

### Trading Sleeves
- [ ] `sleeves.treasury_basis.enabled`: Enable treasury basis arbitrage
- [ ] `sleeves.vol_regime.enabled`: Enable volatility regime trading
- [ ] `sleeves.prop_scaling.enabled`: Enable prop account scaling
- [ ] `sleeves.rwa_crypto.enabled`: Enable RWA/crypto HFT
- [ ] `sleeves.tail_hedging.enabled`: Enable tail hedging

### Risk Management
- [ ] `risk.max_position_per_symbol`: Per-symbol position limit
- [ ] `risk.max_portfolio_position`: Total portfolio position limit
- [ ] `risk.max_daily_loss`: Daily loss limit (triggers kill switch)
- [ ] `risk.max_consecutive_rejections`: Rejection count before kill switch
- [ ] `risk.heartbeat_timeout_ms`: Heartbeat timeout in milliseconds

### Monitoring
- [ ] `monitoring.metrics_port`: HTTP port for Prometheus metrics (default: 9090)
- [ ] `monitoring.audit_log_dir`: Directory for FINRA 3110 audit logs
- [ ] `monitoring.audit_retention_days`: Audit log retention (default: 2555 days = 7 years)

### Data Feeds
- [ ] `feeds.ws_url`: WebSocket URL for market data feed
- [ ] `feeds.api_key`: API key (use `${QP_API_KEY}` for env var substitution)
- [ ] `feeds.symbols`: List of symbols to track
- [ ] `feeds.alpaca_api_key`: Alpaca API key
- [ ] `feeds.alpaca_secret_key`: Alpaca secret key

### Alerts
- [ ] `alerts.slack_webhook_url`: Slack webhook for notifications
- [ ] `alerts.email_to`: Email address for critical alerts
- [ ] `alerts.cooldown_secs`: Alert deduplication cooldown (default: 300s)

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `QP_API_KEY` | Market data feed API key | `abc123xyz...` |
| `QP_SLACK_WEBHOOK` | Slack webhook URL for alerts | `https://hooks.slack.com/...` |
| `QP_ALERT_EMAIL` | Email address for critical alerts | `alerts@company.com` |
| `ALPACA_API_KEY` | Alpaca API key | `PKXXX...` |
| `ALPACA_SECRET_KEY` | Alpaca secret key | `xxx...` |
| `IBKR_MASTER_ACCOUNT` | Interactive Brokers master account ID | `U1234567` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `QP_UDP_ADDR` | UDP address for market data | `0.0.0.0:9999` |
| `RUST_LOG` | Logging level | `info` |
| `GRAFANA_PASSWORD` | Grafana admin password | `admin` |

## Post-Deployment Verification

### 1. Check Engine Health

```bash
# Metrics endpoint should return Prometheus metrics
curl http://localhost:9090/metrics | grep quantum_

# Expected output includes:
# quantum_ticks_processed
# quantum_latency_microseconds
# quantum_crisis_state
```

### 2. Test Dashboard Access

```bash
# Platform health check
curl http://localhost:8000/health

# Dashboard endpoint
curl http://localhost:8000/dashboard
```

### 3. Verify Grafana

1. Navigate to `http://localhost:3000`
2. Login with `admin` / `<GRAFANA_PASSWORD>`
3. Add Prometheus datasource: `http://prometheus:9090`
4. Import dashboard or create custom panels

### 4. Review Audit Logs

```bash
# Check audit log directory
ls -la /var/log/quantum/

# View recent audit entries (in Docker)
docker-compose exec engine ls -la /var/log/quantum/
```

Expected files: `audit_YYYY-MM-DD.jsonl`

### 5. Test Crisis Protocol

Verify that crisis protocols are working by checking the Terra Luna replay test:

```bash
python tests/terra_luna_replay.py
```

Expected output: `✅ TERRA LUNA REPLAY: PASSED`

## Hot Reload Configuration

The engine supports hot-reload of configuration changes without restart:

1. Edit `config/quantum_protocol.toml`
2. Save the file
3. Engine automatically detects changes and reloads within ~1 second
4. Monitor logs for: `INFO: Config reloaded successfully`

**Note**: Some changes (like UDP address) require a full restart.

## Troubleshooting Deployment

### Issue: Docker containers not starting

**Solution**:
```bash
# Check Docker daemon is running
systemctl status docker

# Check logs
docker-compose logs engine

# Rebuild images if needed
docker-compose build --no-cache
docker-compose up -d
```

### Issue: Port conflicts

**Solution**:
```bash
# Check what's using the port
sudo lsof -i :9999
sudo lsof -i :9090

# Either stop the conflicting service or change ports in docker-compose.yml
```

### Issue: Permission denied for audit logs

**Solution**:
```bash
# In Docker deployment, ensure volume has correct permissions
docker-compose down
docker volume rm quantum-protocol_audit-logs
docker-compose up -d

# For direct deployment, create directory with proper permissions
sudo mkdir -p /var/log/quantum
sudo chown -R $(whoami):$(whoami) /var/log/quantum
```

### Issue: Missing environment variables

**Solution**:
```bash
# Verify .env file exists and has all required variables
cat .env

# Check variables are loaded
docker-compose config | grep -A 20 environment
```

## Security Considerations

1. **Never commit secrets**: Keep `.env` file out of version control
2. **Restrict file permissions**: `chmod 600 .env`
3. **Use strong passwords**: Especially for Grafana admin account
4. **Network isolation**: Use firewall rules to restrict access to ports
5. **Audit logs**: Ensure `/var/log/quantum` is on secure, backed-up storage
6. **TLS/SSL**: Use reverse proxy (nginx/traefik) for HTTPS in production
7. **Regular updates**: Keep Docker images and dependencies updated

## Scaling Considerations

### Horizontal Scaling

The engine is designed as a single-instance hot path for ultra-low latency. For scaling:

1. **Multiple instances**: Run multiple engines with different symbol sets
2. **Load balancing**: Use UDP multicast for market data distribution
3. **Sharding**: Partition symbols across instances

### Vertical Scaling

1. **CPU affinity**: Pin engine to dedicated cores
2. **Kernel bypass**: Use Solarflare OpenOnload for production
3. **NUMA awareness**: Ensure memory is local to CPU

## Backup and Recovery

### Configuration Backup

```bash
# Backup configuration
cp config/quantum_protocol.toml config/quantum_protocol.toml.backup

# Backup environment variables (SECURE THIS FILE!)
cp .env .env.backup
chmod 600 .env.backup
```

### Audit Log Backup

```bash
# Backup audit logs (7-year retention required by FINRA 3110)
rsync -avz /var/log/quantum/ backup-server:/quantum-backups/audit/
```

### Kill Switch State

The kill switch state is persisted to `/var/tmp/quantum_kill_switch.json`:

```bash
# Backup kill switch state
cp /var/tmp/quantum_kill_switch.json /var/tmp/quantum_kill_switch.json.backup
```

## Next Steps

After successful deployment:

1. Review [OPERATIONS_MANUAL.md](./OPERATIONS_MANUAL.md) for daily operations
2. Set up API keys per [API_KEYS_SETUP.md](./API_KEYS_SETUP.md)
3. Review [TESTING_PLAN.md](./TESTING_PLAN.md) before going live
4. Configure monitoring alerts in Grafana
5. Test paper trading with small positions

## Support and Resources

- **Main README**: [../README.md](../README.md)
- **Integration Guide**: [INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)
- **Sleeves Documentation**: [SLEEVES_README.md](./SLEEVES_README.md)
- **Crisis Protocols**: See Developer Handbook in [../README.md](../README.md)
