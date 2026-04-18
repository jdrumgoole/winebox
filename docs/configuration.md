# Configuration

WineBox uses TOML-based configuration with separate secrets management. This provides a clean, readable format for settings while keeping sensitive credentials secure.

## Configuration Files

WineBox uses two configuration files:

| File | Purpose | Permissions |
|------|---------|-------------|
| `config.toml` | Main configuration (server, database, features) | 644 (readable) |
| `secrets.env` | Sensitive credentials (API keys, secrets) | 600 (owner only) |

## File Locations

Configuration files are searched in order of priority:

### Development
```
./config.toml          # Project root (highest priority)
./secrets.env
```

### User Configuration
```
~/.config/winebox/config.toml
~/.config/winebox/secrets.env
```

### System Configuration (Production)
```
/etc/winebox/config.toml
/etc/winebox/secrets.env
```

The first file found is used. Environment variables can override any setting.

## Quick Setup

### Development

Create configuration files in your project root:

```bash
# Copy example files
cp config/config.toml.example config.toml
cp config/secrets.env.example secrets.env

# Edit secrets (required)
nano secrets.env
```

### Production

Configuration is created automatically by the setup script. See [Deployment](deployment.md) for details.

## Configuration Reference

### config.toml

```toml
# Application name displayed in UI
app_name = "WineBox"

[server]
# Server binding address
host = "127.0.0.1"

# Server port
port = 8000

# Number of uvicorn workers (production)
workers = 2

# Enable debug mode (disable in production!)
debug = false

# Enable HSTS header (enable in production)
enforce_https = false

# Rate limit per IP per minute
rate_limit_per_minute = 60

[database]
# MongoDB connection URL
mongodb_url = "mongodb://localhost:27017"

# MongoDB database name
mongodb_database = "winebox"

[storage]
# Data directory for uploads
data_dir = "data"

# Log directory
log_dir = "data/logs"

# Maximum upload size in MB
max_upload_mb = 10

[ocr]
# Use Claude Vision for OCR (recommended)
# Falls back to Tesseract if disabled or no API key
use_claude_vision = true

# Tesseract language code
tesseract_lang = "eng"

# Path to tesseract executable (uses system default if not set)
# tesseract_cmd = "/usr/local/bin/tesseract"

[auth]
# Enable authentication
enabled = true

# Allow new user registration
registration_enabled = true

# Require email verification for new accounts
email_verification_required = true

# Rate limit for auth endpoints per minute
auth_rate_limit_per_minute = 30

[email]
# Email backend: "console" (dev) or "ses" (production)
backend = "console"

# From address for emails
from_address = "support@winebox.app"

# From name for emails
from_name = "WineBox"

# Frontend URL for email links
frontend_url = "http://localhost:8000"

# AWS region for SES (only used when backend = "ses")
aws_region = "eu-west-1"
```

### secrets.env

```bash
# Required: Secret key for JWT signing
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
WINEBOX_SECRET_KEY=your-secret-key-here

# Optional: Anthropic API key for Claude Vision OCR
# Get your key from: https://console.anthropic.com/
WINEBOX_ANTHROPIC_API_KEY=sk-ant-api03-...

# Optional: AWS credentials for SES email
# Only needed when email.backend = "ses"
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

## Environment Variable Overrides

Any configuration value can be overridden with environment variables. The naming convention is:

```
WINEBOX_{SECTION}_{KEY}
```

### Examples

| Config Path | Environment Variable |
|-------------|---------------------|
| `server.host` | `WINEBOX_HOST` or `WINEBOX_SERVER_HOST` |
| `server.port` | `WINEBOX_PORT` or `WINEBOX_SERVER_PORT` |
| `server.debug` | `WINEBOX_DEBUG` |
| `database.mongodb_url` | `WINEBOX_MONGODB_URL` |
| `database.mongodb_database` | `WINEBOX_DATABASE` |
| `ocr.use_claude_vision` | `WINEBOX_USE_CLAUDE_VISION` |
| `auth.registration_enabled` | `WINEBOX_REGISTRATION_ENABLED` |
| `email.backend` | `WINEBOX_EMAIL_BACKEND` |

### Boolean Values

For boolean settings, use: `true`, `false`, `1`, `0`, `yes`, `no`

```bash
export WINEBOX_DEBUG=true
export WINEBOX_USE_CLAUDE_VISION=false
```

## All Environment Variables

A full reference of every `WINEBOX_*` variable the code reads, where it's
used, and whether it's required.

### Runtime — required

| Variable | Used by | Purpose |
|----------|---------|---------|
| `WINEBOX_SECRET_KEY` | server | Signs JWT tokens. **Must be set in production** or JWTs are invalidated on every restart. |
| `WINEBOX_MONGODB_URL` | server | MongoDB connection string (e.g. `mongodb+srv://…`). |
| `WINEBOX_DATABASE` | server | Database name. Use `winebox-oat` for OAT and local dev; `winebox` for production. |

### Runtime — optional

| Variable | Used by | Purpose |
|----------|---------|---------|
| `WINEBOX_HOST` / `WINEBOX_SERVER_HOST` | server | Bind address (default `127.0.0.1`). |
| `WINEBOX_PORT` | server | Bind port (default `8000`). |
| `WINEBOX_DEBUG` | server | Enable debug mode. |
| `WINEBOX_USE_CLAUDE_VISION` | server | `false` disables Claude Vision and forces Tesseract (saves API spend in tests). |
| `WINEBOX_REGISTRATION_ENABLED` / `WINEBOX_AUTH_REGISTRATION_ENABLED` | server | Allow self-service registration. |
| `WINEBOX_AUTH_EMAIL_VERIFICATION_REQUIRED` | server | Require email verification before login. |
| `WINEBOX_ANTHROPIC_API_KEY` | Claude Vision, AI column mapping | Anthropic API key. Vision falls back to Tesseract when absent. |
| `WINEBOX_POSTHOG_API_KEY` | analytics | PostHog project key (no-op if empty). |
| `WINEBOX_POSTHOG_ENABLED` | analytics | Disable PostHog without removing the key. |
| `WINEBOX_RATE_LIMIT_DISABLED` | rate limiter | Disable per-IP/per-user limits (tests use this). |
| `WINEBOX_ALLOW_PRODUCTION_DB` | startup safety guard | Set to `1` to explicitly allow connecting to `winebox`. Without this, production-db connections from non-production hostnames raise. |

### Backups (S3)

| Variable | Used by | Purpose |
|----------|---------|---------|
| `WINEBOX_S3_BUCKET` | `scripts/mongodb_backup.py` | S3 bucket for mongodump tarballs. |
| `WINEBOX_S3_PREFIX` | `scripts/mongodb_backup.py` | Optional key prefix within the bucket. |

AWS credentials use the `winebox_backup` profile — see the backup script
for details.

### Deployment (DigitalOcean)

| Variable | Used by | Purpose |
|----------|---------|---------|
| `WINEBOX_DO_TOKEN` | `tasks.py` | DigitalOcean API token used to look up droplet IPs. |
| `WINEBOX_DROPLET_NAME` | `tasks.py` | Which droplet to target (e.g. `winebox-oat`). |
| `WINEBOX_DROPLET_IP` | `tasks.py` | Override the droplet IP lookup. |
| `WINEBOX_DROPLET_USER` | `tasks.py` | SSH user on the droplet (default `winebox`). |
| `WINEBOX_DOMAIN` | `tasks.py` | Public domain (e.g. `booze.winebox.app`). |
| `WINEBOX_NGINX_CONF` | `tasks.py` | Which nginx site config to sync. |

### Testing

| Variable | Used by | Purpose |
|----------|---------|---------|
| `WINEBOX_TEST_URL` | E2E tests | Base URL under test (when running E2E against remote servers like OAT). |
| `WINEBOX_TEST_USER` / `WINEBOX_TEST_PASSWORD` | E2E tests | Pre-provisioned account used when `WINEBOX_TEST_URL` is set. |
| `WINEBOX_PROD_TEST_USER` / `WINEBOX_PROD_TEST_PASSWORD` | `tests/test_production_login.py` | Production smoke-test credentials. |
| `WINEBOX_URL` | CLI scripts | Base URL for manual ad-hoc scripts in `scripts/`. |
| `WINEBOX_ADMIN` | CLI | Admin email for `winebox-admin` CLI. |

### Legacy / migration-only

| Variable | Used by | Purpose |
|----------|---------|---------|
| `WINEBOX_SQLITE_PATH` | `scripts/migrations/migrate_sqlite_to_mongo.py` | Path to the pre-migration SQLite database. Kept for historical migrations. |

## Configuration Sections

### Server

Controls the FastAPI/uvicorn server.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `host` | string | `127.0.0.1` | Bind address |
| `port` | int | `8000` | Bind port |
| `workers` | int | `2` | Uvicorn workers (production) |
| `debug` | bool | `false` | Enable debug mode |
| `enforce_https` | bool | `false` | Enable HSTS header |
| `rate_limit_per_minute` | int | `60` | Global rate limit |

### Database

MongoDB connection settings.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `mongodb_url` | string | `mongodb://localhost:27017` | Connection URL |
| `mongodb_database` | string | `winebox` | Database name |

### Storage

File storage paths and limits.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `data_dir` | path | `data` | Data directory |
| `log_dir` | path | `data/logs` | Log directory |
| `max_upload_mb` | int | `10` | Max upload size (MB) |

Images are stored in `{data_dir}/images/`.

### OCR

Optical Character Recognition settings.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `use_claude_vision` | bool | `true` | Use Claude Vision AI |
| `tesseract_lang` | string | `eng` | Tesseract language |
| `tesseract_cmd` | string | null | Tesseract executable path |

### Auth

Authentication settings.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `enabled` | bool | `true` | Enable authentication |
| `registration_enabled` | bool | `true` | Allow registration |
| `email_verification_required` | bool | `true` | Require email verification |
| `auth_rate_limit_per_minute` | int | `30` | Auth endpoint rate limit |

### Email

Email sending configuration.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `backend` | string | `console` | `console` or `ses` |
| `from_address` | string | `support@winebox.app` | Sender address |
| `from_name` | string | `WineBox` | Sender name |
| `frontend_url` | string | `http://localhost:8000` | URL for email links |
| `aws_region` | string | `eu-west-1` | AWS SES region |

## Common Configurations

### Development

```toml
# config.toml
[server]
debug = true

[database]
mongodb_url = "mongodb://localhost:27017"
mongodb_database = "winebox_dev"

[ocr]
use_claude_vision = false  # Use Tesseract to save API costs

[auth]
email_verification_required = false

[email]
backend = "console"
```

### Production

```toml
# config.toml
[server]
host = "127.0.0.1"
port = 8000
workers = 4
enforce_https = true

[database]
mongodb_url = "mongodb://localhost:27017"
mongodb_database = "winebox"

[storage]
data_dir = "/opt/winebox/data"
log_dir = "/opt/winebox/logs"

[ocr]
use_claude_vision = true

[auth]
email_verification_required = true

[email]
backend = "ses"
from_address = "support@winebox.app"
frontend_url = "https://winebox.app"
aws_region = "eu-west-1"
```

## Security Best Practices

1. **Never commit secrets.env** - Add to `.gitignore`
2. **Restrict file permissions** - `chmod 600 secrets.env`
3. **Generate strong secret keys** - Use `python -c "import secrets; print(secrets.token_urlsafe(32))"`
4. **Enable HTTPS in production** - Set `enforce_https = true`
5. **Use separate databases** - Different databases for dev/staging/prod
6. **Rotate API keys regularly** - Update `secrets.env` periodically

## Troubleshooting

### Configuration Not Loading

Check file locations:
```bash
# See which config file is being used
python -c "from winebox.config import settings; print(settings)"
```

### Environment Variables Not Working

Ensure correct naming:
```bash
# Debug environment
env | grep WINEBOX
```

### MongoDB Connection Issues

Test connectivity:
```bash
mongosh "mongodb://localhost:27017/winebox"
```

### Secret Key Warnings

If you see "SECURITY WARNING: No secret key configured", set:
```bash
export WINEBOX_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Or add to `secrets.env`:
```bash
WINEBOX_SECRET_KEY=your-generated-key
```
