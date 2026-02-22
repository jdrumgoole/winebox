"""Common utilities for WineBox deployment.

This module provides shared functionality used by all deployment scripts:
- SSH command execution
- Digital Ocean API access
- Environment configuration loading
- File upload via SCP
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class DeployConfig:
    """Deployment configuration loaded from environment."""

    host: str | None
    user: str
    droplet_name: str
    do_token: str | None
    domain: str
    env_values: dict[str, str | None]


def get_env_config(
    host: str | None = None,
    user: str | None = None,
    droplet_name: str | None = None,
    domain: str | None = None,
) -> DeployConfig:
    """Load deployment configuration from environment and .env file.

    Args:
        host: Override host (droplet IP)
        user: Override SSH user
        droplet_name: Override droplet name for API lookup
        domain: Override domain name

    Returns:
        DeployConfig with all settings resolved.
    """
    # Load .env file
    env_file = Path(__file__).parent.parent / ".env"
    env_values: dict[str, str | None] = {}
    if env_file.exists():
        load_dotenv(env_file)
        env_values = dotenv_values(env_file)

    return DeployConfig(
        host=host or os.environ.get("WINEBOX_DROPLET_IP"),
        user=user or os.environ.get("WINEBOX_DROPLET_USER", "root"),
        droplet_name=droplet_name or os.environ.get("WINEBOX_DROPLET_NAME", "winebox-droplet"),
        do_token=os.environ.get("WINEBOX_DO_TOKEN"),
        domain=domain or os.environ.get("WINEBOX_DOMAIN", "booze.winebox.app"),
        env_values=env_values,
    )


def resolve_host(config: DeployConfig) -> str:
    """Resolve the droplet host IP, using API lookup if needed.

    Args:
        config: Deployment configuration

    Returns:
        The droplet IP address

    Raises:
        SystemExit: If host cannot be resolved
    """
    if config.host:
        return config.host

    if not config.do_token:
        print("Error: No host specified and WINEBOX_DO_TOKEN not set.")
        print("Either set WINEBOX_DROPLET_IP or WINEBOX_DO_TOKEN in .env")
        sys.exit(1)

    print(f"Looking up IP for droplet '{config.droplet_name}'...")
    host = get_droplet_ip(config.do_token, config.droplet_name)
    if not host:
        print(f"Error: Droplet '{config.droplet_name}' not found.")
        sys.exit(1)

    print(f"Found droplet IP: {host}")
    return host


# =============================================================================
# Digital Ocean API
# =============================================================================

class DigitalOceanAPI:
    """Digital Ocean API client."""

    BASE_URL = "https://api.digitalocean.com/v2"

    def __init__(self, token: str | None = None):
        """Initialize API client with token.

        Args:
            token: Digital Ocean API token. If not provided, reads from
                   WINEBOX_DO_TOKEN environment variable or .env file.
        """
        if token is None:
            token = os.environ.get("WINEBOX_DO_TOKEN")
            if not token:
                # Try loading from .env
                env_path = Path(".env")
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if line.startswith("WINEBOX_DO_TOKEN="):
                            token = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
        if not token:
            raise ValueError("Digital Ocean API token not provided")
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def list_droplets(self) -> list[dict]:
        """List all droplets."""
        response = requests.get(
            f"{self.BASE_URL}/droplets",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()["droplets"]

    # Alias for backwards compatibility
    get_droplets = list_droplets

    def get_droplet(self, droplet_id: int) -> dict | None:
        """Get a specific droplet by ID.

        Args:
            droplet_id: Droplet ID

        Returns:
            Droplet data dict or None if not found
        """
        response = requests.get(
            f"{self.BASE_URL}/droplets/{droplet_id}",
            headers=self.headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["droplet"]

    def get_droplet_ip(self, droplet_name: str) -> str | None:
        """Get public IPv4 address for a droplet by name."""
        for droplet in self.list_droplets():
            if droplet["name"] == droplet_name:
                for network in droplet["networks"]["v4"]:
                    if network["type"] == "public":
                        return network["ip_address"]
        return None

    def rebuild_droplet(self, droplet_id: int, image: str) -> dict | None:
        """Rebuild a droplet with a new image.

        This reinstalls the OS while keeping the same IP address.

        Args:
            droplet_id: Droplet ID to rebuild
            image: Image slug to rebuild with (e.g., 'ubuntu-24-04-x64')

        Returns:
            Action data dict or None on failure
        """
        response = requests.post(
            f"{self.BASE_URL}/droplets/{droplet_id}/actions",
            headers=self.headers,
            json={"type": "rebuild", "image": image},
        )
        if response.status_code not in (200, 201):
            print(f"Error rebuilding droplet: {response.status_code} {response.text}")
            return None
        return response.json()["action"]

    def get_droplet_action(self, droplet_id: int, action_id: int) -> dict | None:
        """Get the status of a droplet action.

        Args:
            droplet_id: Droplet ID
            action_id: Action ID

        Returns:
            Action data dict or None if not found
        """
        response = requests.get(
            f"{self.BASE_URL}/droplets/{droplet_id}/actions/{action_id}",
            headers=self.headers,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()["action"]

    def list_dns_records(self, domain: str) -> list[dict]:
        """List all DNS records for a domain."""
        response = requests.get(
            f"{self.BASE_URL}/domains/{domain}/records",
            headers=self.headers,
            params={"per_page": 100},
        )
        response.raise_for_status()
        return response.json()["domain_records"]

    def create_dns_record(self, domain: str, record: dict) -> dict:
        """Create a DNS record."""
        response = requests.post(
            f"{self.BASE_URL}/domains/{domain}/records",
            headers=self.headers,
            json=record,
        )
        response.raise_for_status()
        return response.json()["domain_record"]

    def update_dns_record(self, domain: str, record_id: int, record: dict) -> dict:
        """Update a DNS record."""
        response = requests.put(
            f"{self.BASE_URL}/domains/{domain}/records/{record_id}",
            headers=self.headers,
            json=record,
        )
        response.raise_for_status()
        return response.json()["domain_record"]

    def list_firewalls(self) -> list[dict]:
        """List all cloud firewalls."""
        response = requests.get(
            f"{self.BASE_URL}/firewalls",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()["firewalls"]

    def create_firewall(self, data: dict) -> dict:
        """Create a cloud firewall.

        Args:
            data: Firewall configuration dict

        Returns:
            Created firewall data
        """
        response = requests.post(
            f"{self.BASE_URL}/firewalls",
            headers=self.headers,
            json=data,
        )
        response.raise_for_status()
        return response.json()["firewall"]

    def update_firewall(self, firewall_id: str, data: dict) -> dict:
        """Update a cloud firewall.

        Args:
            firewall_id: Firewall ID
            data: Updated firewall configuration

        Returns:
            Updated firewall data
        """
        response = requests.put(
            f"{self.BASE_URL}/firewalls/{firewall_id}",
            headers=self.headers,
            json=data,
        )
        response.raise_for_status()
        return response.json()["firewall"]


def get_droplet_ip(token: str, droplet_name: str) -> str | None:
    """Get droplet IP address from Digital Ocean API.

    Args:
        token: Digital Ocean API token
        droplet_name: Name of the droplet

    Returns:
        Public IPv4 address or None if not found
    """
    return DigitalOceanAPI(token).get_droplet_ip(droplet_name)


# =============================================================================
# SSH Utilities
# =============================================================================

def run_ssh(
    host: str,
    user: str,
    command: str | list[str],
    check: bool = True,
    verbose: bool = True,
    capture: bool = False,
) -> int | str:
    """Run command(s) on remote host via SSH.

    Args:
        host: Remote host IP or hostname
        user: SSH username
        command: Single command string or list of commands to chain with &&
        check: If True, exit on command failure
        verbose: If True, print command being run
        capture: If True, capture and return stdout as string instead of return code

    Returns:
        Command return code (int) if capture=False, stdout (str) if capture=True
    """
    if isinstance(command, list):
        remote_cmd = " && ".join(command)
    else:
        remote_cmd = command

    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        f"{user}@{host}",
        remote_cmd,
    ]

    if verbose and not capture:
        display_cmd = remote_cmd[:80] + "..." if len(remote_cmd) > 80 else remote_cmd
        print(f"  $ {display_cmd}")

    if capture:
        result = subprocess.run(ssh_cmd, check=False, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"Error: Command failed with exit code {result.returncode}")
            sys.exit(result.returncode)
        return result.stdout
    else:
        result = subprocess.run(ssh_cmd, check=False)
        if check and result.returncode != 0:
            print(f"Error: Command failed with exit code {result.returncode}")
            sys.exit(result.returncode)
        return result.returncode


def upload_file(host: str, user: str, local_path: Path, remote_path: str) -> None:
    """Upload a file to remote host via SCP.

    Args:
        host: Remote host IP or hostname
        user: SSH username
        local_path: Local file path
        remote_path: Remote destination path

    Raises:
        SystemExit: If upload fails
    """
    scp_cmd = [
        "scp",
        "-o", "StrictHostKeyChecking=accept-new",
        str(local_path),
        f"{user}@{host}:{remote_path}",
    ]

    result = subprocess.run(scp_cmd, check=False)
    if result.returncode != 0:
        print(f"Error uploading {local_path} to {remote_path}")
        sys.exit(result.returncode)


# =============================================================================
# Secrets Management
# =============================================================================

# Secrets that should be synced to production
SYNCABLE_SECRETS = [
    "WINEBOX_ANTHROPIC_API_KEY",
    "WINEBOX_SECRET_KEY",
    "WINEBOX_MONGODB_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "WINEBOX_POSTHOG_ENABLED",
    "WINEBOX_POSTHOG_API_KEY",
]

# Secrets that should NEVER be synced (production-specific)
NEVER_SYNC = [
    "WINEBOX_DROPLET_IP",
    "WINEBOX_DO_TOKEN",
]


def sync_secrets(
    host: str,
    user: str,
    env_values: dict[str, str | None],
    secrets_file: str = "/opt/winebox/secrets.env",
    skip: bool = False,
) -> None:
    """Sync secrets from local environment to production.

    Args:
        host: Remote host IP
        user: SSH username
        env_values: Local environment values dict
        secrets_file: Remote secrets file path
        skip: If True, skip syncing
    """
    if skip:
        print("  Skipping secrets sync (--no-secrets)")
        return

    # Build updates dict from syncable secrets
    updates = {}
    for key in SYNCABLE_SECRETS:
        value = env_values.get(key)
        if value:
            updates[key] = value

    if not updates:
        print("  No secrets to sync")
        return

    print(f"  Syncing {len(updates)} secret(s) to {secrets_file}:")
    for key in updates:
        value = updates[key]
        masked = value[:4] + "..." + value[-4:] if len(value) > 12 else "****"
        print(f"    {key}={masked}")

    # Build sed commands to update or append each key
    commands = []
    for key, value in updates.items():
        escaped_value = value.replace("'", "'\\''")
        commands.append(
            f"grep -q '^{key}=' {secrets_file} && "
            f"sed -i 's|^{key}=.*|{key}={escaped_value}|' {secrets_file} || "
            f"echo '{key}={escaped_value}' >> {secrets_file}"
        )

    full_command = " && ".join(commands)
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"{user}@{host}", full_command],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Warning: Error syncing secrets: {result.stderr}")
    else:
        print("  Secrets synced successfully")
