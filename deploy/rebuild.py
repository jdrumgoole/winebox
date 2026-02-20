#!/usr/bin/env python3
"""Rebuild Digital Ocean droplet for clean deploy testing.

Uses Digital Ocean's rebuild action to reinstall the OS while keeping
the same IP address (no DNS changes needed).

Usage:
    python -m deploy.rebuild [--droplet-name NAME] [--confirm]
"""

import argparse
import sys
import time

from deploy.common import DigitalOceanAPI, get_env_config


# Default image for rebuild
DEFAULT_IMAGE = "ubuntu-24-04-x64"


def wait_for_action_complete(
    api: DigitalOceanAPI,
    droplet_id: int,
    action_id: int,
    timeout: int = 300,
) -> bool:
    """Wait for a droplet action to complete.

    Args:
        api: Digital Ocean API instance
        droplet_id: Droplet ID
        action_id: Action ID to wait for
        timeout: Maximum seconds to wait

    Returns:
        True if action completed successfully
    """
    start = time.time()
    print("Waiting for rebuild to complete", end="", flush=True)

    while time.time() - start < timeout:
        action = api.get_droplet_action(droplet_id, action_id)
        if action:
            status = action.get("status")
            if status == "completed":
                print(" done!")
                return True
            elif status == "errored":
                print(" failed!")
                return False

        print(".", end="", flush=True)
        time.sleep(5)

    print(" timeout!")
    return False


def wait_for_droplet_active(api: DigitalOceanAPI, droplet_id: int, timeout: int = 300) -> bool:
    """Wait for droplet to become active.

    Args:
        api: Digital Ocean API instance
        droplet_id: Droplet ID
        timeout: Maximum seconds to wait

    Returns:
        True if droplet is active
    """
    start = time.time()
    print("Waiting for droplet to be active", end="", flush=True)

    while time.time() - start < timeout:
        droplet = api.get_droplet(droplet_id)
        if droplet and droplet.get("status") == "active":
            print(" ready!")
            return True

        print(".", end="", flush=True)
        time.sleep(5)

    print(" timeout!")
    return False


def rebuild_droplet(
    droplet_name: str,
    image: str = DEFAULT_IMAGE,
    confirm: bool = False,
) -> str | None:
    """Rebuild a Digital Ocean droplet.

    Args:
        droplet_name: Name of the droplet to rebuild
        image: OS image slug to rebuild with
        confirm: If True, skip confirmation prompt

    Returns:
        Droplet IP address or None on failure
    """
    api = DigitalOceanAPI()

    # Find existing droplet
    print(f"Looking for droplet '{droplet_name}'...")
    droplets = api.list_droplets()
    droplet = next((d for d in droplets if d["name"] == droplet_name), None)

    if not droplet:
        print(f"Error: Droplet '{droplet_name}' not found")
        sys.exit(1)

    droplet_id = droplet["id"]
    networks = droplet.get("networks", {}).get("v4", [])
    public_ips = [n["ip_address"] for n in networks if n.get("type") == "public"]
    ip_address = public_ips[0] if public_ips else "unknown"

    print(f"Found droplet: ID={droplet_id}, IP={ip_address}")
    print(f"Current image: {droplet.get('image', {}).get('slug', 'unknown')}")
    print(f"New image: {image}")

    if not confirm:
        print(f"\nThis will REBUILD droplet '{droplet_name}' with a fresh OS.")
        print("All data on the droplet will be DESTROYED.")
        print("The IP address will be preserved (no DNS changes needed).")
        response = input("\nType 'yes' to confirm: ")
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    # Rebuild the droplet
    print(f"\nRebuilding droplet with {image}...")
    action = api.rebuild_droplet(droplet_id, image)

    if not action:
        print("Error: Failed to start rebuild action")
        sys.exit(1)

    action_id = action["id"]
    print(f"Rebuild action started: {action_id}")

    # Wait for rebuild to complete
    if not wait_for_action_complete(api, droplet_id, action_id):
        print("Error: Rebuild action failed or timed out")
        sys.exit(1)

    # Wait for droplet to be active
    if not wait_for_droplet_active(api, droplet_id):
        print("Error: Droplet did not become active")
        sys.exit(1)

    # Wait a bit more for SSH to be ready
    print("Waiting for SSH to be ready...")
    time.sleep(30)

    print(f"\n{'='*60}")
    print("Droplet rebuilt successfully!")
    print(f"{'='*60}")
    print(f"  Name: {droplet_name}")
    print(f"  IP:   {ip_address}")
    print(f"  Image: {image}")
    print(f"\nNext steps:")
    print(f"  1. Run setup: python -m deploy.setup --host {ip_address}")
    print(f"  2. Deploy:    python -m deploy.app --host {ip_address}")

    return ip_address


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Rebuild Digital Ocean droplet for clean deploy testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--droplet-name",
        default="winebox-droplet",
        help="Droplet name (default: winebox-droplet)",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"OS image to rebuild with (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt",
    )

    args = parser.parse_args()

    # Check for API token
    config = get_env_config()
    if not config.do_token:
        print("Error: WINEBOX_DO_TOKEN not set in environment or .env file")
        sys.exit(1)

    rebuild_droplet(
        droplet_name=args.droplet_name,
        image=args.image,
        confirm=args.confirm,
    )


if __name__ == "__main__":
    main()
