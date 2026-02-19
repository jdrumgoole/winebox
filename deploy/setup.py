#!/usr/bin/env python3
"""Initial setup script for WineBox on Digital Ocean droplet.

Run this once on a fresh Ubuntu 22.04/24.04 droplet to install
all dependencies and configure the server.

Usage:
    # From local machine:
    python -m deploy.setup --host YOUR_DROPLET_IP

    # Or set in .env:
    WINEBOX_DROPLET_IP=your-ip
    python -m deploy.setup
"""

import argparse
import secrets
from pathlib import Path

from deploy.common import (
    get_env_config,
    run_ssh,
    run_ssh_script,
    upload_file,
)


# =============================================================================
# Setup Scripts
# =============================================================================

SETUP_COMMANDS = """
set -euo pipefail

echo "=== WineBox Droplet Setup ==="

# Update system
echo "Updating system packages..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

# Install dependencies
echo "Installing dependencies..."
DEBIAN_FRONTEND=noninteractive apt-get install -y \\
    curl \\
    git \\
    nginx \\
    certbot \\
    python3-certbot-nginx \\
    gnupg \\
    tesseract-ocr \\
    tesseract-ocr-eng \\
    build-essential \\
    python3-dev

# Install MongoDB 7.0
echo "Installing MongoDB..."
if [ ! -f /usr/share/keyrings/mongodb-server-7.0.gpg ]; then
    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \\
        gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \\
        tee /etc/apt/sources.list.d/mongodb-org-7.0.list
    apt-get update
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y mongodb-org
systemctl enable mongod
systemctl start mongod

# Install uv (Python package manager)
echo "Installing uv..."
if [ ! -f /root/.local/bin/uv ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="/root/.local/bin:$PATH"

# Create winebox user
echo "Creating winebox user..."
if ! id -u winebox &>/dev/null; then
    useradd -r -m -d /opt/winebox -s /bin/bash winebox
fi

# Create directory structure
echo "Setting up directories..."
mkdir -p /opt/winebox/{data,logs}
chown -R winebox:winebox /opt/winebox

# Create virtual environment and install from PyPI
echo "Creating virtual environment..."
sudo -u winebox /root/.local/bin/uv venv /opt/winebox/.venv

echo "Installing winebox from PyPI..."
sudo -u winebox /opt/winebox/.venv/bin/pip install winebox

echo ""
echo "=== Base Setup Complete ==="
"""

FIREWALL_COMMANDS = """
# Configure firewall
echo "Configuring firewall..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
"""


# =============================================================================
# Configuration Templates
# =============================================================================

CONFIG_TOML_TEMPLATE = """\
# WineBox Configuration - Production
# See config/config.toml.example for all options

[server]
host = "127.0.0.1"
port = 8000
workers = 2
debug = false
enforce_https = true

[database]
mongodb_url = "mongodb://localhost:27017"
mongodb_database = "winebox"

[storage]
data_dir = "/opt/winebox/data"
log_dir = "/opt/winebox/logs"
max_upload_mb = 10

[ocr]
use_claude_vision = false
tesseract_lang = "eng"

[auth]
enabled = true
registration_enabled = true
email_verification_required = true

[email]
backend = "console"
from_address = "noreply@winebox.app"
frontend_url = "https://winebox.app"
"""

SECRETS_ENV_TEMPLATE = """\
# WineBox Secrets - Production
# IMPORTANT: Keep this file secure (chmod 600)

# Required: Secret key for JWT signing
WINEBOX_SECRET_KEY={secret_key}

# Optional: Anthropic API key for Claude Vision OCR
# WINEBOX_ANTHROPIC_API_KEY=sk-ant-...

# Optional: AWS SES for email (when email.backend = "ses")
# AWS_ACCESS_KEY_ID=AKIA...
# AWS_SECRET_ACCESS_KEY=...
"""


# =============================================================================
# Setup Functions
# =============================================================================

def setup_config_files(host: str, user: str) -> None:
    """Create config.toml and secrets.env on remote host if they don't exist."""
    print("\nSetting up configuration files...")

    # Generate secret key for new installations
    secret_key = secrets.token_urlsafe(32)

    # Create config.toml
    config_content = CONFIG_TOML_TEMPLATE
    create_config_cmd = f"""
if [ ! -f /opt/winebox/config.toml ]; then
    cat > /opt/winebox/config.toml << 'CONFIGEOF'
{config_content}
CONFIGEOF
    chown winebox:winebox /opt/winebox/config.toml
    chmod 644 /opt/winebox/config.toml
    echo "Created config.toml"
else
    echo "config.toml already exists, skipping"
fi
"""
    run_ssh(host, user, create_config_cmd.strip(), check=False, verbose=False)

    # Create secrets.env
    secrets_content = SECRETS_ENV_TEMPLATE.format(secret_key=secret_key)
    create_secrets_cmd = f"""
if [ ! -f /opt/winebox/secrets.env ]; then
    cat > /opt/winebox/secrets.env << 'SECRETSEOF'
{secrets_content}
SECRETSEOF
    chown winebox:winebox /opt/winebox/secrets.env
    chmod 600 /opt/winebox/secrets.env
    echo "Created secrets.env with generated secret key"
else
    echo "secrets.env already exists, skipping"
fi
"""
    run_ssh(host, user, create_secrets_cmd.strip(), check=False, verbose=False)


def setup_service_files(host: str, user: str) -> None:
    """Upload and configure systemd and nginx files."""
    deploy_dir = Path(__file__).parent

    # Upload systemd service file
    print("\nUploading systemd service file...")
    upload_file(host, user, deploy_dir / "winebox.service", "/tmp/winebox.service")
    run_ssh(host, user, "mv /tmp/winebox.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable winebox", verbose=False)

    # Upload nginx config
    print("Uploading nginx configuration...")
    upload_file(host, user, deploy_dir / "nginx-winebox.conf", "/tmp/nginx-winebox.conf")
    run_ssh(host, user, """
        mv /tmp/nginx-winebox.conf /etc/nginx/sites-available/winebox
        ln -sf /etc/nginx/sites-available/winebox /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
        nginx -t || echo "Nginx config test failed - SSL certs may not exist yet"
    """, verbose=False)


def print_next_steps(host: str, domain: str) -> None:
    """Print next steps after setup."""
    print(f"""
{'=' * 60}
Setup Complete!
{'=' * 60}

Configuration files created:
  /opt/winebox/config.toml   - Main configuration (TOML format)
  /opt/winebox/secrets.env   - Secrets (API keys, etc.)

Next steps:

1. Review and edit configuration if needed:
   ssh root@{host} "nano /opt/winebox/config.toml"
   ssh root@{host} "nano /opt/winebox/secrets.env"

2. Point your domain DNS to this server:
   A record: {domain} -> {host}

3. Set up SSL certificate (after DNS propagates):
   ssh root@{host} "certbot --nginx -d {domain} -d www.{domain}"

4. Start the application:
   ssh root@{host} "systemctl start winebox"

5. Check status:
   ssh root@{host} "systemctl status winebox"
   ssh root@{host} "journalctl -u winebox -f"

6. Deploy updates in the future:
   python -m deploy.app --host {host}

7. Install X-Wines dataset (optional):
   python -m deploy.xwines --host {host}
""")


def setup(host: str, user: str, domain: str) -> None:
    """Run initial setup on a Digital Ocean droplet.

    Args:
        host: Droplet IP address
        user: SSH username
        domain: Domain name for the application
    """
    print(f"Setting up WineBox on {host}...")
    print(f"Domain: {domain}")
    print("=" * 60)

    # Run setup commands
    print("\nRunning setup script on droplet...")
    returncode = run_ssh_script(host, user, SETUP_COMMANDS)
    if returncode != 0:
        print(f"Setup failed with exit code {returncode}")
        raise SystemExit(returncode)

    # Set up config files
    setup_config_files(host, user)

    # Upload and configure systemd/nginx
    setup_service_files(host, user)

    # Configure firewall
    print("\nConfiguring firewall...")
    run_ssh_script(host, user, FIREWALL_COMMANDS)

    # Print next steps
    print_next_steps(host, domain)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Set up WineBox on a Digital Ocean droplet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        help="Droplet IP address (or set WINEBOX_DROPLET_IP in .env)",
    )
    parser.add_argument(
        "--user",
        default="root",
        help="SSH user (default: root)",
    )
    parser.add_argument(
        "--domain",
        default="winebox.app",
        help="Domain name (default: winebox.app)",
    )

    args = parser.parse_args()

    # Load configuration
    config = get_env_config(
        host=args.host,
        user=args.user,
        domain=args.domain,
    )

    # Host is required for setup
    host = config.host
    if not host:
        print("Error: No host specified.")
        print("Set WINEBOX_DROPLET_IP in .env or use --host flag")
        raise SystemExit(1)

    setup(
        host=host,
        user=config.user,
        domain=config.domain,
    )


if __name__ == "__main__":
    main()
