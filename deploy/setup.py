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
import tempfile
from pathlib import Path

from deploy.common import (
    get_env_config,
    run_ssh,
    upload_file,
)


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
use_claude_vision = true
tesseract_lang = "eng"

[auth]
enabled = true
registration_enabled = true
email_verification_required = false

[email]
backend = "console"
from_address = "support@winebox.app"
frontend_url = "https://{domain}"
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

# APT packages to install
APT_PACKAGES = [
    "curl",
    "git",
    "nginx",
    "certbot",
    "python3-certbot-nginx",
    "gnupg",
    "tesseract-ocr",
    "tesseract-ocr-eng",
    "build-essential",
    "python3-dev",
]


# =============================================================================
# Setup Functions
# =============================================================================

def step(message: str) -> None:
    """Print a setup step message."""
    print(f"\n{'='*60}")
    print(f"  {message}")
    print(f"{'='*60}")


def update_system(host: str, user: str) -> None:
    """Update system packages."""
    step("Updating system packages")
    run_ssh(host, user, "apt-get update")
    run_ssh(host, user, "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y")


def install_packages(host: str, user: str) -> None:
    """Install required apt packages."""
    step("Installing system packages")
    packages = " ".join(APT_PACKAGES)
    run_ssh(host, user, f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages}")


def install_mongodb(host: str, user: str) -> None:
    """Install MongoDB 7.0."""
    step("Installing MongoDB 7.0")

    # Check if MongoDB repo is already configured
    result = run_ssh(
        host, user,
        "test -f /usr/share/keyrings/mongodb-server-7.0.gpg && echo 'exists'",
        check=False, capture=True
    )

    if "exists" not in result:
        # Add MongoDB GPG key
        run_ssh(
            host, user,
            "curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | "
            "gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor"
        )

        # Add MongoDB repository
        repo_line = (
            "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] "
            "https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse"
        )
        run_ssh(host, user, f"echo '{repo_line}' | tee /etc/apt/sources.list.d/mongodb-org-7.0.list")
        run_ssh(host, user, "apt-get update")

    # Install MongoDB
    run_ssh(host, user, "DEBIAN_FRONTEND=noninteractive apt-get install -y mongodb-org")
    run_ssh(host, user, "systemctl enable mongod")
    run_ssh(host, user, "systemctl start mongod")
    print("MongoDB installed and started")


def install_uv(host: str, user: str) -> None:
    """Install uv package manager."""
    step("Installing uv package manager")

    # Check if uv is already installed
    result = run_ssh(host, user, "test -f /usr/local/bin/uv && echo 'exists'", check=False, capture=True)

    if "exists" not in result:
        # Install uv
        run_ssh(host, user, "curl -LsSf https://astral.sh/uv/install.sh | sh")
        # Copy to system path
        run_ssh(host, user, "cp /root/.local/bin/uv /usr/local/bin/")
        run_ssh(host, user, "chmod 755 /usr/local/bin/uv")
        print("uv installed to /usr/local/bin/uv")
    else:
        print("uv already installed")


def create_winebox_user(host: str, user: str) -> None:
    """Create the winebox system user."""
    step("Creating winebox user")

    # Check if user exists
    result = run_ssh(host, user, "id -u winebox 2>/dev/null && echo 'exists'", check=False, capture=True)

    if "exists" not in result:
        run_ssh(host, user, "useradd -r -m -d /opt/winebox -s /bin/bash winebox")
        print("Created winebox user")
    else:
        print("winebox user already exists")


def setup_directories(host: str, user: str) -> None:
    """Create application directory structure."""
    step("Setting up directories")

    run_ssh(host, user, "mkdir -p /opt/winebox/data /opt/winebox/logs")
    run_ssh(host, user, "chown -R winebox:winebox /opt/winebox")
    # Allow nginx to traverse to static files
    run_ssh(host, user, "chmod o+x /opt/winebox")
    print("Directories created: /opt/winebox/{data,logs}")


def create_virtualenv(host: str, user: str) -> None:
    """Create Python virtual environment and install winebox."""
    step("Creating virtual environment")

    # Create venv as winebox user
    run_ssh(
        host, user,
        'su -s /bin/bash winebox -c "HOME=/opt/winebox /usr/local/bin/uv venv /opt/winebox/.venv"'
    )
    print("Virtual environment created")

    # Install pip and winebox
    step("Installing winebox from PyPI")
    run_ssh(
        host, user,
        'su -s /bin/bash winebox -c "'
        'HOME=/opt/winebox /usr/local/bin/uv pip install pip winebox '
        '--python /opt/winebox/.venv/bin/python"'
    )
    print("winebox installed")

    # Create symlink for static files
    run_ssh(
        host, user,
        "ln -sf /opt/winebox/.venv/lib/python3.*/site-packages/winebox/static /opt/winebox/static"
    )
    print("Static files symlink created")


def setup_config_files(host: str, user: str, domain: str) -> None:
    """Create config.toml and secrets.env on remote host."""
    step("Setting up configuration files")

    # Check if config.toml exists
    result = run_ssh(
        host, user,
        "test -f /opt/winebox/config.toml && echo 'exists'",
        check=False, capture=True
    )

    if "exists" not in result:
        # Create config.toml locally and upload
        config_content = CONFIG_TOML_TEMPLATE.format(domain=domain)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write(config_content)
            temp_config = Path(f.name)

        upload_file(host, user, temp_config, "/tmp/config.toml")
        run_ssh(host, user, "mv /tmp/config.toml /opt/winebox/config.toml")
        run_ssh(host, user, "chown winebox:winebox /opt/winebox/config.toml")
        run_ssh(host, user, "chmod 644 /opt/winebox/config.toml")
        temp_config.unlink()
        print("Created config.toml")
    else:
        print("config.toml already exists, skipping")

    # Check if secrets.env exists
    result = run_ssh(
        host, user,
        "test -f /opt/winebox/secrets.env && echo 'exists'",
        check=False, capture=True
    )

    if "exists" not in result:
        # Generate secret key and create secrets.env
        secret_key = secrets.token_urlsafe(32)
        secrets_content = SECRETS_ENV_TEMPLATE.format(secret_key=secret_key)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write(secrets_content)
            temp_secrets = Path(f.name)

        upload_file(host, user, temp_secrets, "/tmp/secrets.env")
        run_ssh(host, user, "mv /tmp/secrets.env /opt/winebox/secrets.env")
        run_ssh(host, user, "chown winebox:winebox /opt/winebox/secrets.env")
        run_ssh(host, user, "chmod 600 /opt/winebox/secrets.env")
        temp_secrets.unlink()
        print("Created secrets.env with generated secret key")
    else:
        print("secrets.env already exists, skipping")


def setup_service_files(host: str, user: str) -> None:
    """Upload and configure systemd and nginx files."""
    deploy_dir = Path(__file__).parent

    # Upload systemd service file
    step("Setting up systemd service")
    upload_file(host, user, deploy_dir / "winebox.service", "/tmp/winebox.service")
    run_ssh(host, user, "mv /tmp/winebox.service /etc/systemd/system/")
    run_ssh(host, user, "systemctl daemon-reload")
    run_ssh(host, user, "systemctl enable winebox")
    print("systemd service configured")

    # Upload nginx config
    step("Setting up nginx")
    upload_file(host, user, deploy_dir / "nginx-winebox.conf", "/tmp/nginx-winebox.conf")
    run_ssh(host, user, "mv /tmp/nginx-winebox.conf /etc/nginx/sites-available/winebox")
    run_ssh(host, user, "ln -sf /etc/nginx/sites-available/winebox /etc/nginx/sites-enabled/")
    run_ssh(host, user, "rm -f /etc/nginx/sites-enabled/default")

    # Test nginx config (may fail if SSL certs don't exist yet)
    result = run_ssh(host, user, "nginx -t 2>&1", check=False, capture=True)
    if "test is successful" in result:
        print("nginx configuration valid")
    else:
        print("nginx config uploaded (SSL certs needed before it will work)")


def setup_firewall(host: str, user: str) -> None:
    """Configure UFW firewall."""
    step("Configuring firewall")

    run_ssh(host, user, "ufw allow 22/tcp")
    run_ssh(host, user, "ufw allow 80/tcp")
    run_ssh(host, user, "ufw allow 443/tcp")
    run_ssh(host, user, "echo 'y' | ufw enable", check=False)

    # Show status
    result = run_ssh(host, user, "ufw status", capture=True)
    print(result)


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
   A record: winebox.app -> {host}
   A record: www.winebox.app -> {host}
   A record: booze.winebox.app -> {host}

3. Set up SSL certificates for both domains (after DNS propagates):
   ssh root@{host} "certbot --nginx -d winebox.app -d www.winebox.app"
   ssh root@{host} "certbot --nginx -d booze.winebox.app"

4. Start the application:
   ssh root@{host} "systemctl start winebox"

5. Check status:
   ssh root@{host} "systemctl status winebox"
   ssh root@{host} "journalctl -u winebox -f"

6. Deploy updates in the future:
   python -m deploy.app --host {host}

7. Install X-Wines dataset (optional):
   python -m deploy.xwines --host {host}

URLs:
  Landing page: https://winebox.app
  Application:  https://{domain}
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

    # Run setup steps
    update_system(host, user)
    install_packages(host, user)
    install_mongodb(host, user)
    install_uv(host, user)
    create_winebox_user(host, user)
    setup_directories(host, user)
    create_virtualenv(host, user)
    setup_config_files(host, user, domain)
    setup_service_files(host, user)
    setup_firewall(host, user)

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
        default="booze.winebox.app",
        help="Domain name for the app (default: booze.winebox.app)",
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
