#!/usr/bin/env python3
"""Initial setup script for WineBox on Digital Ocean droplet.

Run this once on a fresh Ubuntu 22.04/24.04 droplet to install
all dependencies and configure the server.

Usage:
    # From local machine:
    python deploy/setup_droplet.py --host YOUR_DROPLET_IP

    # Or set in .env:
    WINEBOX_DROPLET_IP=your-ip
    python deploy/setup_droplet.py
"""

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Commands to run on the droplet
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

# Clone repository (as winebox user)
echo "Cloning WineBox repository..."
if [ ! -d /opt/winebox/.git ]; then
    sudo -u winebox git clone https://github.com/jdrumgoole/winebox.git /opt/winebox
else
    echo "Repository already exists, pulling latest..."
    cd /opt/winebox
    sudo -u winebox git pull
fi

# Install Python dependencies
echo "Installing Python dependencies..."
cd /opt/winebox
sudo -u winebox /root/.local/bin/uv sync --frozen

# Install systemd service
echo "Installing systemd service..."
cp /opt/winebox/deploy/winebox.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable winebox

# Configure nginx
echo "Configuring nginx..."
cp /opt/winebox/deploy/nginx-winebox.conf /etc/nginx/sites-available/winebox
ln -sf /etc/nginx/sites-available/winebox /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t || echo "Nginx config test failed - SSL certs may not exist yet"

# Configure firewall
echo "Configuring firewall..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo ""
echo "=== Base Setup Complete ==="
"""

ENV_TEMPLATE = """\
# WineBox Configuration
WINEBOX_SECRET_KEY={secret_key}
WINEBOX_MONGODB_URL=mongodb://localhost:27017
WINEBOX_MONGODB_DATABASE=winebox
WINEBOX_USE_CLAUDE_VISION=false

# Optional: Anthropic API key for Claude Vision OCR
# WINEBOX_ANTHROPIC_API_KEY=your-key-here

# Optional: AWS SES for email
# WINEBOX_EMAIL_BACKEND=ses
# AWS_REGION=us-east-1
# AWS_ACCESS_KEY_ID=your-key
# AWS_SECRET_ACCESS_KEY=your-secret
"""


def run_ssh(
    host: str,
    user: str,
    command: str,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command on remote host via SSH."""
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        command,
    ]

    result = subprocess.run(ssh_cmd, check=False, text=True)

    if check and result.returncode != 0:
        print(f"Error: Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)

    return result


def run_ssh_script(host: str, user: str, script: str) -> int:
    """Run a multi-line script on remote host via SSH."""
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        "bash -s",
    ]

    result = subprocess.run(
        ssh_cmd,
        input=script,
        text=True,
        check=False,
    )

    return result.returncode


def setup_env_file(host: str, user: str) -> None:
    """Create .env file on remote host if it doesn't exist."""
    print("\nChecking for .env file...")

    # Check if .env exists
    check_result = run_ssh(
        host, user,
        "test -f /opt/winebox/.env && echo 'exists' || echo 'missing'",
        check=False,
    )

    # Create .env if missing
    secret_key = secrets.token_urlsafe(32)
    env_content = ENV_TEMPLATE.format(secret_key=secret_key)

    create_cmd = f"""
if [ ! -f /opt/winebox/.env ]; then
    cat > /opt/winebox/.env << 'ENVEOF'
{env_content}
ENVEOF
    chown winebox:winebox /opt/winebox/.env
    chmod 600 /opt/winebox/.env
    echo "Created .env file with generated secret key"
else
    echo ".env file already exists, skipping"
fi
"""
    run_ssh(host, user, create_cmd.strip(), check=False)


def print_next_steps(host: str, domain: str) -> None:
    """Print next steps after setup."""
    print(f"""
{'=' * 60}
Setup Complete!
{'=' * 60}

Next steps:

1. Review and edit the .env file if needed:
   ssh root@{host} "nano /opt/winebox/.env"

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
   python deploy/deploy.py --host {host}
""")


def main() -> None:
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

    # Load .env file
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    # Get host
    host = args.host or os.environ.get("WINEBOX_DROPLET_IP")
    if not host:
        print("Error: No host specified.")
        print("Set WINEBOX_DROPLET_IP in .env or use --host flag")
        sys.exit(1)

    user = args.user
    domain = args.domain

    print(f"Setting up WineBox on {host}...")
    print(f"Domain: {domain}")
    print("=" * 60)

    # Run setup commands
    print("\nRunning setup script on droplet...")
    returncode = run_ssh_script(host, user, SETUP_COMMANDS)
    if returncode != 0:
        print(f"Setup failed with exit code {returncode}")
        sys.exit(returncode)

    # Set up .env file
    setup_env_file(host, user)

    # Print next steps
    print_next_steps(host, domain)


if __name__ == "__main__":
    main()
