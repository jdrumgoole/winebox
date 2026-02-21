"""WineBox deployment module.

This module provides tools for deploying WineBox to production servers.

Submodules:
    common: Shared utilities (SSH, Digital Ocean API, environment loading)
    app: Main application deployment
    setup: Initial server setup
    xwines: X-Wines dataset deployment
    initialise: Full droplet initialisation (setup + DNS + SSL + deploy)

Usage:
    # From command line
    python -m deploy.initialise   # Full droplet initialisation
    python -m deploy.app          # Deploy application
    python -m deploy.setup        # Initial server setup
    python -m deploy.xwines       # Deploy X-Wines dataset

    # From invoke tasks
    invoke initialise-droplet     # Full droplet initialisation
    invoke deploy                 # Deploy application
    invoke deploy-setup           # Initial server setup
    invoke deploy-xwines          # Deploy X-Wines dataset
"""

from deploy.common import (
    DigitalOceanAPI,
    get_droplet_ip,
    get_env_config,
    run_ssh,
    upload_file,
)

__all__ = [
    "DigitalOceanAPI",
    "get_droplet_ip",
    "get_env_config",
    "run_ssh",
    "upload_file",
]
