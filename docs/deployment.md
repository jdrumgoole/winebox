# Deployment

This guide covers deploying WineBox to a production server using Digital Ocean.

## Architecture

WineBox uses a standard production stack:

```
Internet → nginx (HTTPS) → uvicorn (Python) → MongoDB Atlas
```

- **nginx**: Reverse proxy with SSL termination
- **uvicorn**: ASGI server running FastAPI
- **MongoDB Atlas**: Cloud-hosted document database
- **systemd**: Process management

## Prerequisites

- Digital Ocean account
- Domain name (e.g., `winebox.app`)
- Local development environment with WineBox installed
- MongoDB Atlas cluster (connection string in `.env`)

## One-Command Deployment

The recommended way to set up a fresh droplet is with `initialise-droplet`, which
runs all steps in sequence:

```bash
# Full initialisation (setup + DNS + firewall + SSL + deploy + X-Wines)
uv run python -m invoke initialise-droplet

# Preview without making changes
uv run python -m invoke initialise-droplet --dry-run

# Skip X-Wines dataset import
uv run python -m invoke initialise-droplet --skip-xwines

# Specify a particular version
uv run python -m invoke initialise-droplet --version 0.5.6
```

This runs the following steps automatically:

1. **Server setup** — installs packages, creates user/directories, uploads configs
2. **Cloud firewall** — ensures ports 22/80/443 are open via DO API
3. **DNS configuration** — creates A records for `@`, `www`, `booze` on `winebox.app`
4. **DNS propagation** — waits until all domains resolve to the droplet IP
5. **SSL certificates** — obtains Let's Encrypt certs via certbot
6. **Start nginx** — starts the reverse proxy
7. **Application deployment** — installs WineBox from PyPI, syncs secrets, starts service
8. **X-Wines import** — imports the wine dataset (skippable with `--skip-xwines`)

### Required Environment Variables

Set these in your local `.env` file before running:

```bash
WINEBOX_DO_TOKEN=your-digital-ocean-api-token
WINEBOX_DROPLET_IP=your-droplet-ip
WINEBOX_MONGODB_URL=mongodb+srv://user:pass@cluster.mongodb.net
WINEBOX_ANTHROPIC_API_KEY=sk-ant-...
WINEBOX_SECRET_KEY=your-secret-key
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

## Step-by-Step Deployment

If you prefer to run each step individually:

### 1. Initial Server Setup

Run the setup script on a fresh Ubuntu 22.04/24.04 droplet:

```bash
# Set your droplet IP
export WINEBOX_DROPLET_IP=your-droplet-ip

# Run setup (installs nginx, creates directories)
uv run python -m invoke deploy-setup --host $WINEBOX_DROPLET_IP

# Or run directly:
uv run python -m deploy.setup --host $WINEBOX_DROPLET_IP
```

This installs:
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
- `booze` → `<droplet-ip>`

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
ssh root@<droplet-ip> "certbot --nginx -d booze.winebox.app"
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
├── __init__.py        # Package exports
├── common.py          # Shared utilities (SSH, DO API, secrets)
├── app.py             # Application deployment
├── setup.py           # Initial server setup
├── initialise.py      # Full droplet initialisation
├── xwines.py          # X-Wines dataset deployment
├── winebox.service    # systemd service file
└── nginx-winebox.conf # nginx configuration
```

### deploy.initialise

Full droplet initialisation. Combines all steps into a single command.

```bash
# Via invoke task
uv run python -m invoke initialise-droplet [options]

# Or directly
uv run python -m deploy.initialise [options]

Options:
  --host TEXT          Droplet IP (auto-discovered if not set)
  --domain TEXT        App domain (default: booze.winebox.app)
  --version TEXT       Package version (default: latest)
  --skip-xwines       Skip X-Wines dataset import
  --dry-run            Preview without applying
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
Supports download caching — if CSVs already exist on the droplet from a
previous run, the download step is skipped automatically.

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
1. Checks for cached CSVs on the droplet
2. If not cached: installs gdown, downloads X-Wines dataset (~500MB)
3. Imports wines into MongoDB
4. Cleans up temporary files

## OAT Admin Panel

The OAT environment runs the admin panel as a separate FastAPI app on its own subdomain (`oatadmin.winebox.app`, port 8001), distinct from the main wine app on `oat.winebox.app` (port 8000). Both ship from the same `winebox` PyPI wheel — there is no separate admin package.

### Architecture

```
Internet ─┬─► oat.winebox.app       → nginx → uvicorn winebox.main:app       (port 8000)
          │
          └─► oatadmin.winebox.app  → nginx (IP allowlist) → uvicorn winebox.admin.main:app (port 8001)
                                       │
                                       └─ both share the same /opt/winebox/.venv and secrets.env
```

The admin host is fully IP-restricted at the nginx layer — every path on `oatadmin.winebox.app` requires a source IP in the allowlist.

### Allowlist

The single source of truth is **`deploy/winebox-admin.toml`**:

```toml
[oat]
allow = [
    "109.255.27.13",  # operator — home
]

[production]
allow = [
    "109.255.27.13",
]
```

Edit and re-run `invoke deploy-oat`. The renderer in `deploy/common.py:render_nginx_config` substitutes each standalone `# __ADMIN_ALLOWLIST__` line in the nginx template with `allow ...; deny all;` directives, indented to the placeholder's own column. Empty sections are rejected so a typo can't silently ship an open admin panel.

### One-time bring-up

Run once per droplet, in order:

```bash
# 1. Add the A record at DigitalOcean (idempotent).
invoke oat-admin-dns

# 2. Wait for DNS to propagate.
dig +short oatadmin.winebox.app

# 3. Issue the Let's Encrypt cert. Briefly stops nginx for the standalone
#    HTTP-01 challenge — the same approach as `oat-ssl`.
invoke oat-admin-ssl

# 4. Roll out the nginx config that references the new cert and start the
#    admin systemd unit.
invoke deploy-oat
```

After step 4, the admin panel is live at `https://oatadmin.winebox.app`.

### Routine deploys

`invoke deploy-oat` (with or without `--release`) ships both services:

1. Installs the new `winebox` wheel from PyPI (contains `winebox.main` AND `winebox.admin`).
2. Uploads `deploy/winebox-oat.service` → `/etc/systemd/system/winebox.service`.
3. Uploads `deploy/winebox-admin-oat.service` → `/etc/systemd/system/winebox-admin.service`.
4. Renders `deploy/nginx-winebox-oat.conf` against the `[oat]` allowlist and uploads it.
5. Restarts `winebox` (port 8000), then `winebox-admin` (port 8001).
6. Health-checks both services. The admin curl talks to `http://localhost:8001/health` from the droplet, so the allowlist is bypassed for this internal probe.

### Smoke test (post-deploy)

Run from a machine whose IP is in the OAT allowlist (typically the same machine that ran `invoke deploy-oat`):

```bash
uv run python -m pytest tests/test_oat_admin_smoke.py -v
```

The test module auto-skips on machines that can't reach `/health` — CI and unallowlisted dev environments don't see it as a failure.

### Service status / logs

```bash
invoke oat-status                                       # both services + both health endpoints
ssh root@<oat-ip> "journalctl -u winebox-admin -n 50"   # admin logs
```

## Database Migrations

### Text Index Migration (v0.5.12)

Version 0.5.12 added `sub_region` and `appellation` to the MongoDB text search index.
MongoDB does not allow creating a new text index when one already exists with different
fields, so the old index must be dropped before deploying v0.5.12 or later.

A migration script is provided:

```bash
# Run locally
uv run python scripts/migrations/drop_old_text_index.py [MONGODB_URL]

# Run on production
scp scripts/migrations/drop_old_text_index.py root@<droplet-ip>:/tmp/
ssh root@<droplet-ip> "sudo -u winebox /opt/winebox/.venv/bin/python /tmp/drop_old_text_index.py \$WINEBOX_MONGODB_URL"
```

If `MONGODB_URL` is not provided, the script falls back to the `WINEBOX_MONGODB_URL`
environment variable, then defaults to `mongodb://localhost:27017`.

## Database

### MongoDB Atlas

WineBox uses MongoDB Atlas as its cloud database. The connection string is
stored in `WINEBOX_MONGODB_URL` in your local `.env` file and synced to
production `secrets.env` on deploy.

The `config.toml` on the server only sets the database name:

```toml
[database]
mongodb_database = "winebox"
# mongodb_url is set via WINEBOX_MONGODB_URL in secrets.env
```

The environment variable `WINEBOX_MONGODB_URL` overrides any URL in config.toml.

## Configuration

### Environment Variables

Set these in your local `.env` file:

```bash
# Required for deployment
WINEBOX_DO_TOKEN=your-digital-ocean-api-token

# Optional: Override droplet lookup
WINEBOX_DROPLET_IP=your-droplet-ip
WINEBOX_DROPLET_NAME=winebox-production

# MongoDB Atlas connection string
WINEBOX_MONGODB_URL=mongodb+srv://user:pass@cluster.mongodb.net

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
mongodb_database = "winebox"
# mongodb_url is set via WINEBOX_MONGODB_URL in secrets.env

[storage]
data_dir = "/opt/winebox/data"
log_dir = "/opt/winebox/logs"

[email]
backend = "ses"
from_address = "support@winebox.app"
frontend_url = "https://booze.winebox.app"
```

**`/opt/winebox/secrets.env`**:
```bash
WINEBOX_SECRET_KEY=<auto-generated>
WINEBOX_ANTHROPIC_API_KEY=<synced-from-local>
WINEBOX_MONGODB_URL=<synced-from-local>
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
| `WINEBOX_MONGODB_URL` | MongoDB Atlas connection |
| `AWS_ACCESS_KEY_ID` | AWS SES email |
| `AWS_SECRET_ACCESS_KEY` | AWS SES email |
| `AWS_REGION` | AWS SES region |

These are **never synced** (local-only):
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

With MongoDB Atlas, database backups are handled by the Atlas service.
You can also use `mongodump` with the Atlas connection string:

```bash
mongodump --uri "mongodb+srv://user:pass@cluster.mongodb.net/winebox" --out ./backups/

# Backup images
ssh root@<droplet-ip> "tar -czf /opt/winebox/backups/images-$(date +%Y%m%d).tar.gz /opt/winebox/data/images"

# Download backups
scp -r root@<droplet-ip>:/opt/winebox/backups/ ./backups/
```

### Restore

```bash
# Restore MongoDB
mongorestore --uri "mongodb+srv://user:pass@cluster.mongodb.net" /path/to/backup/winebox/

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
# Test Atlas connectivity from the droplet
ssh root@<droplet-ip> "sudo -u winebox /opt/winebox/.venv/bin/python -c \"
from winebox.config import settings
print(f'MongoDB URL: {settings.database.mongodb_url[:30]}...')
\""

# Check if the WINEBOX_MONGODB_URL is set in secrets.env
ssh root@<droplet-ip> "grep WINEBOX_MONGODB_URL /opt/winebox/secrets.env"
```

## Security

### Firewall

The initialisation script configures both UFW (host-level) and a DO cloud
firewall (network-level):

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
