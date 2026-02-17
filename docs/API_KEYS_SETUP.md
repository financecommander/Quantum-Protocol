# Quantum Protocol - API Keys Setup Guide

## Overview

This guide covers all API keys and credentials required to run the Quantum Protocol system, including where to obtain them, how to configure them, and security best practices.

## Required API Keys

### Summary Table

| Provider | Purpose | Criticality | Cost |
|----------|---------|-------------|------|
| Alpaca | Market data feed & execution | **Critical** | Free tier available |
| Interactive Brokers (IBKR) | Master account execution | **Critical** | Account required |
| Market Data Provider | Real-time market data | **Critical** | Paid subscription |
| Slack | Alert notifications | High | Free |
| Email (SMTP) | Critical alerts | Medium | Free/Paid |

## 1. Alpaca API Keys

### What They're Used For

- Real-time market data for stocks, ETFs, and crypto
- Paper trading and live order execution
- Historical data for backtesting

### How to Get Them

1. **Sign up for Alpaca**:
   - Go to [https://alpaca.markets](https://alpaca.markets)
   - Click "Sign Up" and create an account
   - Choose "Individual" account type

2. **Enable Paper Trading**:
   - Log in to Alpaca dashboard
   - Navigate to "Paper Trading" section
   - Paper trading is automatically enabled for new accounts

3. **Generate API Keys**:
   - Go to "Your API Keys" in the dashboard
   - Click "Generate New Keys"
   - You'll receive:
     - **API Key ID** (e.g., `PKXXX...`)
     - **Secret Key** (e.g., `xxx...`)
   - **Important**: Save the secret key immediately - it's only shown once!

4. **Enable Live Trading** (Optional, for production):
   - Complete Alpaca's account verification
   - Fund your account
   - Generate separate live trading API keys

### Configuration

In `.env` file:
```bash
ALPACA_API_KEY=PKXXXXXXXXXXXXXXXXXXX
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

In `config/quantum_protocol.toml`:
```toml
[feeds]
alpaca_api_key = "${ALPACA_API_KEY}"
alpaca_secret_key = "${ALPACA_SECRET_KEY}"
```

### Testing

```bash
# Test Alpaca connection (using curl)
curl -X GET "https://paper-api.alpaca.markets/v2/account" \
  -H "APCA-API-KEY-ID: ${ALPACA_API_KEY}" \
  -H "APCA-API-SECRET-KEY: ${ALPACA_SECRET_KEY}"

# Expected: JSON with account information
```

### Endpoints

- **Paper Trading**: `https://paper-api.alpaca.markets`
- **Live Trading**: `https://api.alpaca.markets`
- **Market Data**: `https://data.alpaca.markets`

### Rate Limits

- **Free Tier**: 200 requests/minute
- **Unlimited Plan**: No rate limits
- **WebSocket**: Real-time streaming (no polling needed)

### Cost

- **Paper Trading**: Free
- **Live Trading**: Free (commission-free trading)
- **Market Data**: 
  - Basic (15-min delayed): Free
  - Real-time (IEX): Free
  - Real-time (All exchanges): $9/month

## 2. Interactive Brokers (IBKR) Master Account

### What It's Used For

- Master account for Prop Scaling (Sleeve 3)
- Institutional-grade execution
- Fan-out to 20+ prop accounts (Topstep/FTMO)

### How to Get It

1. **Open IBKR Account**:
   - Go to [https://www.interactivebrokers.com](https://www.interactivebrokers.com)
   - Click "Open Account"
   - Choose account type:
     - Individual (for personal trading)
     - Business/Institutional (for firm trading)

2. **Complete Application**:
   - Provide personal/business information
   - Complete suitability questionnaire
   - Submit financial information
   - Verification may take 1-3 business days

3. **Fund Account**:
   - Minimum: $0 (but $2,000+ recommended for pattern day trading)
   - Transfer funds via wire, ACH, or check

4. **Enable API Access**:
   - Log in to Client Portal
   - Go to Settings > API > Settings
   - Enable "API" checkbox
   - Note your **Master Account ID** (format: `U1234567`)

5. **Install TWS or IB Gateway** (Optional):
   - Download from IBKR website
   - Used for manual trading and monitoring
   - Can run alongside API

### Configuration

In `.env` file:
```bash
IBKR_MASTER_ACCOUNT=U1234567
```

In `config/quantum_protocol.toml`:
```toml
[sleeves.prop_scaling]
enabled = true
master_account_id = "${IBKR_MASTER_ACCOUNT}"
max_accounts = 32
min_equity = 2000.0
```

### API Integration

IBKR uses a different API model than Alpaca:

- **TWS API**: Java-based API (requires running TWS or IB Gateway)
- **Client Portal API**: REST API (newer, simpler)

**Note**: Current Quantum Protocol implementation uses TWS API model. You'll need to:

1. Run IB Gateway on the same host as the engine
2. Configure IB Gateway to accept connections on port 4001
3. Authenticate IB Gateway with your credentials

### Testing

```bash
# Verify IBKR connection (requires IB Gateway running)
# This test would be implemented in the engine

# Manual verification via TWS:
# 1. Open TWS/IB Gateway
# 2. Log in with credentials
# 3. Check connection status in upper-right corner
```

### Rate Limits

- **Message Rate**: 50 messages/second
- **Orders**: Unlimited (but subject to exchange rules)
- **Market Data Lines**: Depends on subscription tier

### Cost

- **Account Fees**: $0/month (with activity) or $10/month (waived with $100k+ balance)
- **Commissions**: $0.0035/share (min $0.35) for US stocks
- **Market Data**: 
  - US Securities Snapshot: $10/month
  - US Equity and Options: $10/month
  - Real-time futures: $10-$20/month per exchange

## 3. Market Data Feed API Key

### What It's Used For

- Primary real-time market data feed
- WebSocket streaming for BTC, ETH, SPY, QQQ, TLT
- Backup to Alpaca feed

### Recommended Providers

1. **Polygon.io**:
   - Real-time stocks, options, forex, crypto
   - WebSocket streaming
   - Historical data included
   - **Cost**: $99-$399/month

2. **IEX Cloud**:
   - Real-time US stocks
   - Simple REST + WebSocket API
   - **Cost**: $9-$999/month (tiered by usage)

3. **Alpha Vantage**:
   - Free tier available
   - Good for testing
   - **Cost**: Free (limited) to $49.99/month

### How to Get Them (Polygon.io Example)

1. **Sign Up**:
   - Go to [https://polygon.io](https://polygon.io)
   - Click "Get Started"
   - Choose a plan (Starter $99/month recommended)

2. **Get API Key**:
   - After signup, go to Dashboard
   - Find "API Keys" section
   - Copy your API key (format: `XXXXXXXXXXXXXXXXXXXXXX`)

3. **Test Connection**:
   ```bash
   curl "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2023-01-09/2023-01-09?apiKey=YOUR_API_KEY"
   ```

### Configuration

In `.env` file:
```bash
QP_API_KEY=your_polygon_api_key_here
```

In `config/quantum_protocol.toml`:
```toml
[feeds]
ws_url = "wss://socket.polygon.io/stocks"  # Or your provider's WebSocket URL
api_key = "${QP_API_KEY}"
symbols = ["BTC-USD", "ETH-USD", "SPY", "QQQ", "TLT"]
heartbeat_interval_ms = 1000
reconnect_max_delay_ms = 60000
```

### WebSocket Endpoints

| Provider | WebSocket URL |
|----------|---------------|
| Polygon.io | `wss://socket.polygon.io/stocks` |
| IEX Cloud | `wss://cloud-sse.iexapis.com/stable/[key]/stocksUS` |
| Alpaca | `wss://stream.data.alpaca.markets/v2/iex` |

## 4. Slack Webhook for Alerts

### What It's Used For

- Real-time alert notifications
- System status updates
- Crisis protocol notifications
- Kill switch triggers

### How to Get It

1. **Create Slack Workspace** (if you don't have one):
   - Go to [https://slack.com](https://slack.com)
   - Click "Create a new workspace"
   - Follow setup wizard

2. **Create Incoming Webhook**:
   - Go to [https://api.slack.com/apps](https://api.slack.com/apps)
   - Click "Create New App" > "From scratch"
   - Name it "Quantum Protocol Alerts"
   - Choose your workspace

3. **Enable Incoming Webhooks**:
   - In app settings, click "Incoming Webhooks"
   - Toggle "Activate Incoming Webhooks" to On
   - Click "Add New Webhook to Workspace"
   - Choose a channel (e.g., `#quantum-alerts`)
   - Click "Allow"

4. **Copy Webhook URL**:
   - Format: `https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX`
   - This is your `QP_SLACK_WEBHOOK`

### Configuration

In `.env` file:
```bash
QP_SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

In `config/quantum_protocol.toml`:
```toml
[alerts]
slack_webhook_url = "${QP_SLACK_WEBHOOK}"
cooldown_secs = 300  # Prevent alert spam
```

### Testing

```bash
# Test Slack webhook
curl -X POST "${QP_SLACK_WEBHOOK}" \
  -H "Content-Type: application/json" \
  -d '{"text": "Test alert from Quantum Protocol"}'

# Check your Slack channel for the message
```

### Alert Severity Levels

| Severity | Slack | Email | Example |
|----------|-------|-------|---------|
| Info | ✅ | ❌ | Config reloaded |
| Warning | ✅ | ❌ | Latency > 120µs |
| Error | ✅ | ❌ | Feed disconnected |
| Critical | ✅ | ✅ | Kill switch activated |
| Emergency | ✅ | ✅ | Position breach |

### Cost

- **Slack**: Free (up to 10,000 messages/month)
- **Unlimited Messages**: $8/user/month (Pro plan)

## 5. Email Alerts (SMTP)

### What They're Used For

- Critical and emergency alerts only
- Backup to Slack notifications
- Compliance notifications

### How to Configure

#### Option A: Gmail SMTP

1. **Enable 2FA** on your Google account
2. **Generate App Password**:
   - Go to Google Account settings
   - Security > 2-Step Verification > App passwords
   - Generate password for "Mail"
   - Save the 16-character password

3. **SMTP Settings**:
   - Server: `smtp.gmail.com`
   - Port: 587 (TLS) or 465 (SSL)
   - Username: Your Gmail address
   - Password: App password (not your regular password)

#### Option B: SendGrid

1. **Sign Up**: [https://sendgrid.com](https://sendgrid.com)
2. **Create API Key**: Settings > API Keys > Create API Key
3. **SMTP Settings**:
   - Server: `smtp.sendgrid.net`
   - Port: 587
   - Username: `apikey`
   - Password: Your API key

#### Option C: AWS SES

1. **Sign Up**: AWS Console > SES
2. **Verify Email**: Add and verify sender email
3. **Get SMTP Credentials**: SMTP Settings > Create My SMTP Credentials
4. **SMTP Settings**:
   - Server: `email-smtp.[region].amazonaws.com`
   - Port: 587
   - Username: From AWS console
   - Password: From AWS console

### Configuration

In `.env` file:
```bash
QP_ALERT_EMAIL=your-email@example.com
# For full SMTP config, you'd add:
# SMTP_SERVER=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USERNAME=your-email@gmail.com
# SMTP_PASSWORD=your-app-password
```

In `config/quantum_protocol.toml`:
```toml
[alerts]
email_to = "${QP_ALERT_EMAIL}"
```

**Note**: Current implementation uses a simplified email model. For production, you may need to configure full SMTP settings in the code.

### Testing

```bash
# Test email (requires configured SMTP)
# This would be tested via the alert system
curl -X POST http://localhost:8000/test_alert \
  -H "Content-Type: application/json" \
  -d '{"level": "critical", "message": "Test email alert"}'
```

### Cost

- **Gmail**: Free (with limits)
- **SendGrid**: Free (100 emails/day), $20/month (40k emails)
- **AWS SES**: $0.10 per 1,000 emails

## Security Best Practices

### 1. Environment Variables (Not Hardcoded)

**❌ Never do this**:
```toml
[feeds]
api_key = "abc123secret"  # WRONG!
```

**✅ Always do this**:
```toml
[feeds]
api_key = "${QP_API_KEY}"  # Reads from environment
```

### 2. File Permissions

Protect your `.env` file:

```bash
# Set restrictive permissions
chmod 600 .env

# Verify
ls -la .env
# Should show: -rw------- (owner read/write only)
```

### 3. Never Commit Secrets

The `.env` file should be in `.gitignore`:

```bash
# Verify .env is ignored
git status

# If you accidentally committed secrets:
git rm --cached .env
git commit -m "Remove .env from tracking"
# Then rotate all compromised keys immediately
```

### 4. Use Separate Keys for Environments

| Environment | Purpose | Keys |
|-------------|---------|------|
| Development | Local testing | Paper trading, test API keys |
| Staging | Pre-production | Paper trading, lower limits |
| Production | Live trading | Live trading, production keys |

### 5. Key Rotation

Rotate API keys regularly:

- **Alpaca**: Every 90 days
- **IBKR**: Password change every 90 days
- **Slack Webhook**: Regenerate if compromised
- **Market Data**: Per provider policy

### 6. Monitor for Leaks

```bash
# Check for accidentally committed secrets
git log -p | grep -i "api_key\|secret\|password" | grep -v "QP_API_KEY"

# Use tools like:
# - git-secrets (AWS)
# - truffleHog
# - gitleaks
```

### 7. Encrypt Backups

If you backup `.env` files:

```bash
# Encrypt with GPG
gpg -c .env
# Creates .env.gpg

# Decrypt
gpg .env.gpg
```

### 8. Use Secrets Manager (Production)

For production, consider using:

- **AWS Secrets Manager**: Auto-rotation, encryption
- **HashiCorp Vault**: Enterprise secrets management
- **Google Cloud Secret Manager**: GCP integration
- **Docker Secrets**: For Docker Swarm deployments

### 9. Least Privilege

- **Alpaca**: Use paper trading keys for testing
- **IBKR**: Set appropriate permissions per account
- **Slack**: Use workspace-specific webhooks
- **Market Data**: Use read-only API keys when possible

### 10. Audit Access

Regularly review:

```bash
# Check who has access to production environment
# Check AWS IAM users (if using AWS)
# Check Docker host access
# Review Slack workspace members

# Log all access to production credentials
echo "$(date): User $USER accessed production .env" >> /var/log/quantum/access.log
```

## Troubleshooting

### Invalid API Key

**Symptoms**:
- `401 Unauthorized` errors
- `Invalid API key` in logs

**Solutions**:
1. Verify key is copied correctly (no extra spaces)
2. Check key hasn't expired
3. Verify key is for correct environment (paper vs. live)
4. Regenerate key if necessary

### Rate Limit Exceeded

**Symptoms**:
- `429 Too Many Requests` errors
- Feed disconnections

**Solutions**:
1. Upgrade API plan
2. Reduce polling frequency (use WebSocket instead)
3. Implement request caching
4. Use multiple API keys (if allowed)

### WebSocket Connection Failed

**Symptoms**:
- `WebSocket disconnected` in logs
- No market data updates

**Solutions**:
1. Verify WebSocket URL is correct
2. Check firewall allows outbound WebSocket connections
3. Verify API key has WebSocket access
4. Check provider status page for outages

### IBKR Connection Issues

**Symptoms**:
- Cannot connect to IB Gateway
- `TWS not connected` errors

**Solutions**:
1. Verify IB Gateway is running
2. Check credentials are correct
3. Verify API access is enabled in TWS settings
4. Check IB Gateway accepts connections on port 4001
5. Restart IB Gateway if hung

## Checklist: Before Going Live

- [ ] All API keys obtained and tested
- [ ] Paper trading validated with real market data
- [ ] Alert notifications tested (Slack and email)
- [ ] Separate production keys generated
- [ ] `.env` file has restrictive permissions (600)
- [ ] Secrets are not in version control
- [ ] Key rotation schedule established
- [ ] Backup/recovery plan for credentials
- [ ] Team members have documented access procedures
- [ ] Emergency contact list prepared

## Summary of Costs

| Service | Free Tier | Paid Tier | Recommended |
|---------|-----------|-----------|-------------|
| Alpaca | Paper trading free | Live trading free | Free |
| IBKR | $10/month* | Same | ~$10/month |
| Polygon.io | - | $99-$399/month | $99/month |
| Slack | 10k messages/month | $8/user/month | Free OK |
| Email (Gmail) | Limited | $6/user/month | Free OK |

**Total Monthly**: ~$109-$409/month for API keys and data feeds

*Waived with trading activity or $100k+ balance

## Additional Resources

- **Alpaca Docs**: [https://alpaca.markets/docs](https://alpaca.markets/docs)
- **IBKR API**: [https://www.interactivebrokers.com/en/trading/ib-api.php](https://www.interactivebrokers.com/en/trading/ib-api.php)
- **Polygon.io Docs**: [https://polygon.io/docs](https://polygon.io/docs)
- **Slack API**: [https://api.slack.com](https://api.slack.com)
- **Quantum Protocol Main README**: [../README.md](../README.md)
