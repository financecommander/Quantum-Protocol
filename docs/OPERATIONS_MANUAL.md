# Quantum Protocol - Operations Manual

## Overview

This manual covers daily operations of the Quantum Protocol system, including startup/shutdown procedures, monitoring, troubleshooting, and emergency protocols.

## System Start/Stop Procedures

### Starting the System (Docker Compose)

#### Standard Startup

```bash
# Navigate to project directory
cd /path/to/Quantum-Protocol

# Start all services
docker-compose up -d

# Verify all services are running
docker-compose ps

# Expected output:
# NAME                STATUS          PORTS
# engine              Up (healthy)    9999/udp, 9090/tcp
# prometheus          Up              9091/tcp
# grafana             Up              3000/tcp
```

#### Startup Verification Checklist

- [ ] All Docker containers show "Up" status
- [ ] Engine health check passes: `curl http://localhost:9090/metrics`
- [ ] Prometheus is scraping metrics: Check Targets page at `http://localhost:9091/targets`
- [ ] Grafana is accessible: `http://localhost:3000`
- [ ] Audit logs are being written: `docker-compose exec engine ls /var/log/quantum/`
- [ ] No error messages in logs: `docker-compose logs --tail=50 engine`

### Stopping the System

#### Graceful Shutdown

```bash
# Stop all services gracefully
docker-compose down

# This will:
# - Send SIGTERM to engine (triggers graceful shutdown)
# - Flush all audit logs
# - Save kill switch state to /var/tmp/quantum_kill_switch.json
# - Stop Prometheus and Grafana
```

#### Emergency Shutdown

In case of immediate stop required:

```bash
# Hard stop (not recommended unless emergency)
docker-compose kill

# Or stop engine only
docker-compose kill engine
```

**Warning**: Emergency shutdown may result in:
- Unflushed audit logs
- Open positions not properly hedged
- Kill switch state not persisted

### Restarting the System

```bash
# Restart all services
docker-compose restart

# Restart engine only (if config changed)
docker-compose restart engine

# Full rebuild and restart (if code changed)
docker-compose down
docker-compose build
docker-compose up -d
```

### Direct Binary Operations

If running the engine as a direct binary:

#### Start Engine

```bash
# Start in foreground (for testing)
./quantum-engine

# Start in background with nohup
nohup ./quantum-engine > /var/log/quantum/engine.log 2>&1 &

# Start with systemd (recommended for production)
sudo systemctl start quantum-engine
```

#### Stop Engine

```bash
# Find PID
ps aux | grep quantum-engine

# Send SIGTERM for graceful shutdown
kill -TERM <PID>

# Or use systemd
sudo systemctl stop quantum-engine
```

## Monitoring Endpoints

### Engine Metrics (Port 9090)

#### `/metrics` - Prometheus Metrics

```bash
curl http://localhost:9090/metrics
```

**Key Metrics to Monitor**:

| Metric | Description | Target |
|--------|-------------|--------|
| `quantum_ticks_processed` | Total ticks processed | Increasing |
| `quantum_latency_microseconds_p99` | 99th percentile latency | < 120µs |
| `quantum_latency_microseconds_median` | Median latency | < 100µs |
| `quantum_crisis_state` | Current crisis state (0=Normal, 2=SmartBunker, 3=SurgicalSniper) | 0 (Normal) |
| `quantum_positions_open` | Number of open positions | < max_position |
| `quantum_daily_pnl` | Daily P&L | Monitor for max_daily_loss |
| `quantum_kill_switch_active` | Kill switch status (0=inactive, 1=active) | 0 |
| `quantum_rejections_consecutive` | Consecutive order rejections | < max_consecutive_rejections |
| `quantum_heartbeat_lag_us` | Heartbeat lag in microseconds | < 100µs |

#### `/health` - Health Check

```bash
curl http://localhost:9090/health

# Expected response: {"status": "healthy"}
```

### Platform Endpoints (Port 8000)

The Python platform provides CTA-exempt retail dashboards:

#### `/dashboard` - Market Context Dashboard

```bash
curl http://localhost:8000/dashboard
```

Returns coarsened market context (no Buy/Sell signals):
```json
{
  "market_context": "Moderate volatility regime",
  "crisis_state": "Normal",
  "vol_regime": "Medium",
  "ticks_processed": 15234,
  "uptime_seconds": 3600.5
}
```

#### `/heatmaps` - Volatility Heatmap Data

```bash
curl http://localhost:8000/heatmaps
```

Returns volatility regime data for visualization.

#### `/latency` - Latency Metrics

```bash
curl http://localhost:8000/latency
```

Returns engine latency performance:
```json
{
  "p99_latency_us": 95.3,
  "median_latency_us": 78.2,
  "ticks_processed": 15234,
  "target_p99_us": 120.0
}
```

**Alert if**: `p99_latency_us` > 120µs

#### `/compliance` - Compliance Dashboard

```bash
curl http://localhost:8000/compliance
```

Returns FINRA 3110 audit log summary.

#### `/update_config` - Update Shared Config

```bash
curl -X POST http://localhost:8000/update_config \
  -H "Content-Type: application/json" \
  -d '{"hedge_ratio": 0.85, "circuit_breaker_enabled": true}'
```

Updates shared memory config block (hot-reload without restart).

### Prometheus (Port 9091)

Access Prometheus UI: `http://localhost:9091`

#### Useful Queries

```promql
# Latency over time
quantum_latency_microseconds_p99

# Ticks per second
rate(quantum_ticks_processed[1m])

# Crisis state changes
changes(quantum_crisis_state[5m])

# Daily P&L
quantum_daily_pnl

# Kill switch triggers
increase(quantum_kill_switch_active[1d])
```

### Grafana (Port 3000)

Access Grafana: `http://localhost:3000`

**Default Login**: `admin` / `<GRAFANA_PASSWORD>`

#### Recommended Dashboards

1. **Engine Performance**:
   - Latency (p50, p99, p999)
   - Throughput (ticks/second)
   - Heartbeat lag

2. **Trading Activity**:
   - Open positions
   - Daily P&L
   - Order fill rate

3. **Risk Monitoring**:
   - Position limits
   - Daily loss
   - Kill switch status
   - Consecutive rejections

4. **Crisis Protocols**:
   - Crisis state timeline
   - VIX levels
   - Depeg percentages

## Monitoring Best Practices

### Regular Checks (Every 5 Minutes)

```bash
# Quick health check script
#!/bin/bash
echo "=== Quantum Protocol Health Check ==="

# 1. Check containers
docker-compose ps

# 2. Check latency
curl -s http://localhost:8000/latency | jq '.p99_latency_us'

# 3. Check crisis state
curl -s http://localhost:9090/metrics | grep quantum_crisis_state

# 4. Check kill switch
curl -s http://localhost:9090/metrics | grep quantum_kill_switch_active

# 5. Check recent logs for errors
docker-compose logs --tail=10 engine | grep -i error
```

### Alerts to Configure

Set up alerts in Grafana/Prometheus for:

1. **Critical (PagerDuty/SMS)**:
   - Kill switch activated
   - Crisis state != Normal for > 5 minutes
   - p99 latency > 200µs (degraded)
   - Daily loss approaching limit (80% of max_daily_loss)
   - Heartbeat timeout
   - Consecutive rejections > 8

2. **Warning (Slack/Email)**:
   - p99 latency > 120µs
   - Position approaching limits (80% of max)
   - Audit log disk usage > 80%
   - Container restart detected

3. **Info (Slack)**:
   - Crisis protocol activated/deactivated
   - Config hot-reload completed
   - Daily P&L milestones

## Troubleshooting Common Issues

### Issue: High Latency (p99 > 120µs)

**Symptoms**:
- `quantum_latency_microseconds_p99` > 120µs
- Slow order execution
- Increased heartbeat lag

**Diagnosis**:
```bash
# Check CPU usage
docker stats engine

# Check for network issues
docker-compose logs engine | grep -i "timeout\|disconnect"

# Check system load
top -b -n 1 | head -20
```

**Solutions**:
1. **CPU contention**: Pin engine to dedicated cores
2. **Network latency**: Check market data feed connection
3. **Memory pressure**: Increase container memory limit
4. **Disk I/O**: Move audit logs to faster storage
5. **GC pressure** (unlikely in Rust): Check for memory leaks

### Issue: Kill Switch Activated

**Symptoms**:
- `quantum_kill_switch_active` = 1
- All trading halted
- Logs show kill switch trigger reason

**Diagnosis**:
```bash
# Check kill switch state file
cat /var/tmp/quantum_kill_switch.json

# Check recent audit logs
tail -100 /var/log/quantum/audit_$(date +%Y-%m-%d).jsonl | grep -i "kill"

# Check which trigger fired
docker-compose logs engine | grep -i "kill switch"
```

**Recovery** (Requires Dual-Key Authentication):

1. **Identify root cause**: Check which limit was breached
   - Daily P&L loss exceeded `max_daily_loss`
   - Position breached `max_portfolio_position`
   - Consecutive rejections > `max_consecutive_rejections`
   - Heartbeat timeout exceeded `heartbeat_timeout_ms`

2. **Fix root cause**: 
   - If market issue: Wait for market recovery
   - If config issue: Adjust limits in `config/quantum_protocol.toml`
   - If code issue: Deploy hotfix

3. **Reset kill switch** (Dev + Compliance approval required):
   ```bash
   # Remove kill switch state file
   sudo rm /var/tmp/quantum_kill_switch.json
   
   # Restart engine
   docker-compose restart engine
   ```

4. **Monitor closely**: Watch for immediate re-trigger

### Issue: Crisis Protocol Not Triggering

**Symptoms**:
- VIX > 45 but crisis_state = Normal
- Depeg > 5% but no SurgicalSniper

**Diagnosis**:
```bash
# Check current VIX and depeg values
curl http://localhost:8000/dashboard

# Run Terra Luna replay test
python tests/terra_luna_replay.py

# Check crisis evaluation logic
docker-compose logs engine | grep -i crisis
```

**Solutions**:
1. Verify market data feed is providing VIX updates
2. Check `sleeves.tail_hedging.vix_critical_threshold` in config
3. Review crisis evaluation logic in `src/engine/mod.rs`

### Issue: Missing Audit Logs

**Symptoms**:
- No files in `/var/log/quantum/`
- Compliance dashboard shows 0 records

**Diagnosis**:
```bash
# Check directory permissions
docker-compose exec engine ls -la /var/log/quantum/

# Check volume mounts
docker-compose config | grep -A 5 volumes
```

**Solutions**:
```bash
# Recreate audit log volume with correct permissions
docker-compose down
docker volume rm quantum-protocol_audit-logs
docker-compose up -d

# Verify logs are being written
docker-compose exec engine ls -la /var/log/quantum/
```

### Issue: Prometheus Not Scraping Metrics

**Symptoms**:
- Grafana shows "No data"
- Prometheus Targets page shows engine as "Down"

**Diagnosis**:
```bash
# Check Prometheus targets
curl http://localhost:9091/targets

# Check engine metrics endpoint
curl http://localhost:9090/metrics

# Check network connectivity
docker-compose exec prometheus wget -O- http://engine:9090/metrics
```

**Solutions**:
1. Verify engine is running and healthy
2. Check `deploy/prometheus.yml` scrape config
3. Restart Prometheus: `docker-compose restart prometheus`

### Issue: WebSocket Feed Disconnected

**Symptoms**:
- No market data updates
- Logs show "WebSocket disconnected"
- Ticks processed stops increasing

**Diagnosis**:
```bash
# Check feed connection logs
docker-compose logs engine | grep -i "websocket\|feed"

# Verify feed credentials
echo $QP_API_KEY
```

**Solutions**:
1. Check API key is valid and not rate-limited
2. Verify `feeds.ws_url` is correct
3. Check network connectivity to feed provider
4. Engine will auto-reconnect with exponential backoff (up to 60s)

## Emergency Procedures

### Emergency Stop (Market Chaos)

If immediate halt is required due to market emergency:

```bash
# 1. Stop engine immediately
docker-compose stop engine

# 2. Verify no orders in flight
# (Check IBKR account, exchange connections)

# 3. Manually flatten positions if needed
# (Use IBKR Trader Workstation or API)

# 4. Document incident
echo "$(date): Emergency stop triggered - Reason: [DESCRIBE]" >> /var/log/quantum/incidents.log
```

### Data Recovery After Crash

If engine crashes:

```bash
# 1. Check if kill switch state is persisted
cat /var/tmp/quantum_kill_switch.json

# 2. Review audit logs for last known state
tail -200 /var/log/quantum/audit_$(date +%Y-%m-%d).jsonl

# 3. Verify position state with broker
# (Reconcile with IBKR/exchange records)

# 4. Restart with caution
docker-compose up -d

# 5. Monitor closely for 30 minutes
docker-compose logs -f engine
```

### Rollback to Previous Version

If new deployment has issues:

```bash
# 1. Stop current version
docker-compose down

# 2. Checkout previous version
git log --oneline  # Find previous commit
git checkout <previous-commit-hash>

# 3. Rebuild and deploy
docker-compose build
docker-compose up -d

# 4. Verify rollback
docker-compose ps
curl http://localhost:9090/metrics
```

### Database Corruption (Prometheus/Grafana)

If monitoring database is corrupted:

```bash
# 1. Stop services
docker-compose down

# 2. Remove corrupted volumes
docker volume rm quantum-protocol_prometheus-data
docker volume rm quantum-protocol_grafana-data

# 3. Restart (will create fresh databases)
docker-compose up -d

# 4. Reconfigure Grafana datasource and dashboards
```

**Note**: Engine and audit logs are unaffected.

## Daily Operations Checklist

### Morning Checklist (Before Market Open)

- [ ] Verify all services are running: `docker-compose ps`
- [ ] Check latency is nominal: `curl http://localhost:8000/latency`
- [ ] Verify kill switch is not active
- [ ] Review overnight audit logs for anomalies
- [ ] Check disk space for audit logs: `df -h /var/log/quantum`
- [ ] Verify API keys and credentials are valid
- [ ] Test market data feed connectivity
- [ ] Review any overnight alerts in Slack
- [ ] Verify backup systems are operational

### During Market Hours

- [ ] Monitor latency every 5 minutes
- [ ] Watch for crisis protocol activations
- [ ] Track daily P&L vs limits
- [ ] Monitor position sizes
- [ ] Review Grafana dashboards
- [ ] Respond to alerts within SLA

### End of Day Checklist

- [ ] Review daily P&L
- [ ] Archive daily audit logs (backup to S3/GCS)
- [ ] Check for any kill switch triggers
- [ ] Review compliance report: `curl http://localhost:8000/compliance`
- [ ] Verify all positions reconcile with broker
- [ ] Document any incidents or anomalies
- [ ] Update operational notes if config changed

## Performance Optimization

### Latency Optimization

If p99 latency is consistently > 100µs but < 120µs:

1. **CPU Pinning**: Pin engine to dedicated cores
   ```bash
   # In docker-compose.yml, add:
   cpuset: "0-3"  # Use cores 0-3
   ```

2. **Process Priority**: Increase engine priority
   ```bash
   docker-compose exec engine renice -n -10 -p $(pidof quantum-engine)
   ```

3. **Kernel Bypass**: For production, use Solarflare OpenOnload
   - Requires hardware support
   - See vendor documentation

4. **Disable Unnecessary Sleeves**: If not needed, disable sleeves in config
   ```toml
   [sleeves.tail_hedging]
   enabled = false  # Disables if not needed
   ```

### Resource Monitoring

```bash
# Monitor resource usage
docker stats

# Check for memory leaks
docker-compose exec engine ps aux

# Monitor disk I/O
iostat -x 1

# Network monitoring
docker-compose exec engine netstat -s
```

## Compliance and Audit

### FINRA 3110 Requirements

All trading decisions must be logged to audit trail:

```bash
# View audit logs
tail -f /var/log/quantum/audit_$(date +%Y-%m-%d).jsonl

# Example audit entry:
{
  "timestamp": "2024-01-15T14:30:22.123Z",
  "event_type": "OrderDecision",
  "crisis_state": "Normal",
  "sleeve": "treasury_basis",
  "signal": 0.75,
  "position": 50000.0
}
```

### Audit Log Retention

- **Retention**: 2555 days (7 years) per FINRA requirements
- **Format**: JSON Lines (.jsonl)
- **Rotation**: Daily
- **Backup**: Required (automated to S3/GCS)

### Log Archival

```bash
# Automated daily backup (add to cron)
#!/bin/bash
LOG_DIR="/var/log/quantum"
BACKUP_DIR="/backup/quantum-audit"
DATE=$(date +%Y-%m-%d)

rsync -avz "$LOG_DIR/audit_$DATE.jsonl" "$BACKUP_DIR/"
```

## Contacts and Escalation

### Support Tiers

1. **Tier 1 - Operational Issues**:
   - Container restart failures
   - Configuration questions
   - Monitoring setup

2. **Tier 2 - Performance Issues**:
   - High latency
   - Feed connectivity
   - Resource optimization

3. **Tier 3 - Trading Issues**:
   - Kill switch activation
   - Crisis protocol failures
   - Position reconciliation

### Escalation Path

1. Check this manual and troubleshooting guide
2. Review relevant documentation in `/docs`
3. Check GitHub issues for known problems
4. Contact Tier 1 support (if available)
5. Emergency: Execute emergency stop procedure

## Appendix: Log Locations

| Component | Log Location (Docker) | Log Location (Direct) |
|-----------|----------------------|----------------------|
| Engine | `docker-compose logs engine` | `/var/log/quantum/engine.log` |
| Audit | `/var/log/quantum/audit_YYYY-MM-DD.jsonl` | Same |
| Kill Switch State | `/var/tmp/quantum_kill_switch.json` | Same |
| Prometheus | `docker-compose logs prometheus` | System dependent |
| Grafana | `docker-compose logs grafana` | System dependent |

## Appendix: Useful Commands

```bash
# Quick status
docker-compose ps && curl -s http://localhost:8000/latency

# Watch logs
docker-compose logs -f engine

# Check metrics
watch -n 5 'curl -s http://localhost:9090/metrics | grep quantum_latency'

# Test crisis protocol
python tests/terra_luna_replay.py

# Backup today's audit log
cp /var/log/quantum/audit_$(date +%Y-%m-%d).jsonl ~/backup/

# View kill switch state
cat /var/tmp/quantum_kill_switch.json | jq .
```
