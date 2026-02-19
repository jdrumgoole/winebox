# Deployment

This guide covers deploying WineBox to a production server using Digital Ocean.

## Architecture

WineBox uses a standard production stack:

```
Internet → nginx (HTTPS) → uvicorn (Python) → MongoDB
```

- **nginx**: Reverse proxy with SSL termination
- **uvicorn**: ASGI server running FastAPI
- **MongoDB**: Document database
- **systemd**: Process management

## Prerequisites

- Digital Ocean account
- Domain name (e.g., `winebox.app`)
- Local development environment with WineBox installed

## Quick Deployment

### 1. Initial Server Setup

Run the setup script on a fresh Ubuntu 22.04/24.04 droplet:

```bash
# Set your droplet IP
export WINEBOX_DROPLET_IP=your-droplet-ip

# Run setup (installs MongoDB, nginx, creates directories)
uv run python -m invoke deploy-setup --host $WINEBOX_DROPLET_IP

# Or run directly:
uv run python -m deploy.setup --host $WINEBOX_DROPLET_IP
```

This installs:
- MongoDB 7.0
- nginx with SSL support
- Tesseract OCR
- Python with uv package manager
- WineBox from PyPI

### 2. Configure DNS

Point your domain to the droplet:

```bash
# Using the deploy script with DNS setup
uv run python -m invoke deploy --setup-dns
```

Or manually add A records:
- `@` → `<droplet-ip>`
- `www` → `<droplet-ip>`

### 3. Deploy Application

```bash
# Deploy latest version from PyPI
uv run python -m invoke deploy

# Deploy specific version
uv run python -m invoke deploy --version 0.4.0

# Preview changes without applying
uv run python -m invoke deploy --dry-run
```

### 4. Setup SSL

After DNS propagates (5-10 minutes):

```bash
ssh root@<droplet-ip> "certbot --nginx -d winebox.app -d www.winebox.app"
```

### 5. Create Admin User

```bash
ssh root@<droplet-ip> "sudo -u winebox /opt/winebox/.venv/bin/winebox-admin add admin --password <password> --admin"
```

### 6. Deploy X-Wines Dataset (Optional)

To enable wine autocomplete with 100K+ wines:

```bash
# Deploy full dataset (downloads ~500MB)
uv run python -m invoke deploy-xwines

# Or deploy test dataset (100 wines, for testing)
uv run python -m invoke deploy-xwines --test
```

## Deploy Module

The `deploy/` directory is a Python module with shared utilities and deployment scripts:

```
deploy/
├── __init__.py    # Package exports
├── common.py      # Shared utilities (SSH, DO API, secrets)
├── app.py         # Application deployment
├── setup.py       # Initial server setup
├── xwines.py      # X-Wines dataset deployment
├── winebox.service    # systemd service file
└── nginx-winebox.conf # nginx configuration
```

### deploy.setup

Initial server configuration. Run once on a fresh droplet.

```bash
# Via invoke task
uv run python -m invoke deploy-setup [options]

# Or directly
uv run python -m deploy.setup [options]

Options:
  --host TEXT     Droplet IP address
  --domain TEXT   Domain name (default: winebox.app)
```

Creates:
- `/opt/winebox/` - Application directory
- `/opt/winebox/data/` - Data storage
- `/opt/winebox/logs/` - Log files
- `/opt/winebox/config.toml` - Configuration
- `/opt/winebox/secrets.env` - Secrets
- `/etc/systemd/system/winebox.service` - Service file
- `/etc/nginx/sites-available/winebox` - nginx config

### deploy.app

Deploy updates to an existing server.

```bash
# Via invoke task
uv run python -m invoke deploy [options]

# Or directly
uv run python -m deploy.app [options]

Options:
  --host TEXT          Droplet IP (auto-discovered if not set)
  --droplet-name TEXT  Droplet name for API lookup
  --version TEXT       Package version (default: latest)
  --no-secrets         Skip syncing secrets
  --setup-dns          Configure DNS A records
  --dry-run            Preview without applying
```

Actions:
1. Discovers droplet IP from Digital Ocean API
2. Installs/upgrades WineBox from PyPI
3. Syncs secrets from local `.env` to production
4. Restarts the service
5. Verifies service is running

### deploy.xwines

Deploy the X-Wines dataset for wine autocomplete. Run once after setup.

```bash
# Via invoke task
uv run python -m invoke deploy-xwines [options]

# Or directly
uv run python -m deploy.xwines [options]

Options:
  --host TEXT          Droplet IP (auto-discovered if not set)
  --droplet-name TEXT  Droplet name for API lookup
  --test               Use test dataset (100 wines) instead of full
  --dry-run            Preview without applying
```

Actions:
1. Installs gdown for Google Drive downloads
2. Downloads X-Wines dataset (~500MB for full)
3. Imports wines into MongoDB
4. Cleans up temporary files

## Configuration

### Environment Variables

Set these in your local `.env` file:

```bash
# Required for deployment
WINEBOX_DO_TOKEN=your-digital-ocean-api-token

# Optional: Override droplet lookup
WINEBOX_DROPLET_IP=your-droplet-ip
WINEBOX_DROPLET_NAME=winebox-droplet

# Secrets to sync to production
WINEBOX_ANTHROPIC_API_KEY=sk-ant-...
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

### Production Configuration

The setup script creates these files on the server:

**`/opt/winebox/config.toml`**:
```toml
[server]
host = "127.0.0.1"
port = 8000
workers = 2
enforce_https = true

[database]
mongodb_url = "mongodb://localhost:27017"
mongodb_database = "winebox"

[storage]
data_dir = "/opt/winebox/data"
log_dir = "/opt/winebox/logs"

[email]
backend = "console"
frontend_url = "https://winebox.app"
```

**`/opt/winebox/secrets.env`**:
```bash
WINEBOX_SECRET_KEY=<auto-generated>
WINEBOX_ANTHROPIC_API_KEY=<synced-from-local>
AWS_ACCESS_KEY_ID=<synced-from-local>
AWS_SECRET_ACCESS_KEY=<synced-from-local>
```

## Server Management

### systemd Commands

```bash
# Start/stop/restart
sudo systemctl start winebox
sudo systemctl stop winebox
sudo systemctl restart winebox

# Check status
sudo systemctl status winebox

# View logs
sudo journalctl -u winebox -f
sudo journalctl -u winebox -n 100
```

### nginx Commands

```bash
# Test configuration
sudo nginx -t

# Reload configuration
sudo systemctl reload nginx

# View access logs
sudo tail -f /var/log/nginx/access.log
```

### MongoDB Commands

```bash
# Connect to MongoDB
mongosh winebox

# Backup database
mongodump --db winebox --out /opt/winebox/backups/

# Restore database
mongorestore --db winebox /opt/winebox/backups/winebox/
```

## File Locations

| Path | Purpose |
|------|---------|
| `/opt/winebox/` | Application root |
| `/opt/winebox/.venv/` | Python virtual environment |
| `/opt/winebox/config.toml` | Configuration |
| `/opt/winebox/secrets.env` | Secrets (600 permissions) |
| `/opt/winebox/data/` | Data directory |
| `/opt/winebox/data/images/` | Uploaded images |
| `/opt/winebox/logs/` | Application logs |
| `/etc/systemd/system/winebox.service` | systemd service |
| `/etc/nginx/sites-available/winebox` | nginx config |

## Synced Secrets

The deploy script syncs these secrets from local `.env`:

| Secret | Purpose |
|--------|---------|
| `WINEBOX_SECRET_KEY` | JWT signing key |
| `WINEBOX_ANTHROPIC_API_KEY` | Claude Vision API |
| `AWS_ACCESS_KEY_ID` | AWS SES email |
| `AWS_SECRET_ACCESS_KEY` | AWS SES email |
| `AWS_REGION` | AWS SES region |

These are **never synced** (production-specific):
- `WINEBOX_MONGODB_URL`
- `WINEBOX_DROPLET_IP`
- `WINEBOX_DO_TOKEN`

## Updating WineBox

### Standard Update

```bash
# Deploy latest from PyPI
uv run python -m invoke deploy

# The script will:
# 1. pip install winebox --upgrade
# 2. Sync secrets
# 3. Restart service
# 4. Verify health
```

### Specific Version

```bash
uv run python -m invoke deploy --version 0.4.1
```

### Manual Update

```bash
ssh root@<droplet-ip>
sudo -u winebox /opt/winebox/.venv/bin/pip install winebox --upgrade
sudo systemctl restart winebox
```

## Monitoring

### Health Check

```bash
curl https://winebox.app/health
```

### Service Status

```bash
ssh root@<droplet-ip> "systemctl status winebox"
```

### Recent Logs

```bash
ssh root@<droplet-ip> "journalctl -u winebox -n 50"
```

## Backup and Recovery

### Backup

```bash
# Backup MongoDB
ssh root@<droplet-ip> "mongodump --db winebox --out /opt/winebox/backups/$(date +%Y%m%d)"

# Backup images
ssh root@<droplet-ip> "tar -czf /opt/winebox/backups/images-$(date +%Y%m%d).tar.gz /opt/winebox/data/images"

# Download backups
scp -r root@<droplet-ip>:/opt/winebox/backups/ ./backups/
```

### Restore

```bash
# Restore MongoDB
mongorestore --db winebox /path/to/backup/winebox/

# Restore images
tar -xzf images-backup.tar.gz -C /opt/winebox/data/
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
journalctl -u winebox -n 100

# Check configuration
sudo -u winebox /opt/winebox/.venv/bin/python -c "from winebox.config import settings; print(settings)"

# Check MongoDB
mongosh --eval "db.serverStatus()"
```

### 502 Bad Gateway

nginx can't connect to uvicorn:

```bash
# Check if uvicorn is running
systemctl status winebox

# Check port binding
ss -tlnp | grep 8000

# Restart service
systemctl restart winebox
```

### SSL Certificate Issues

```bash
# Test SSL
openssl s_client -connect winebox.app:443

# Renew certificate
certbot renew

# Check certificate expiry
certbot certificates
```

### Database Connection Issues

```bash
# Check MongoDB status
systemctl status mongod

# Check connection
mongosh "mongodb://localhost:27017/winebox"

# Check logs
journalctl -u mongod -n 50
```

## Security

### Firewall

The setup script configures UFW:

```bash
sudo ufw status

# Should show:
# 22/tcp    ALLOW  (SSH)
# 80/tcp    ALLOW  (HTTP)
# 443/tcp   ALLOW  (HTTPS)
```

### Secrets

- `secrets.env` has 600 permissions (owner read/write only)
- Owned by `winebox` user
- Never synced: `WINEBOX_DO_TOKEN`, `WINEBOX_DROPLET_IP`

### Updates

Keep the system updated:

```bash
ssh root@<droplet-ip> "apt update && apt upgrade -y"
```
