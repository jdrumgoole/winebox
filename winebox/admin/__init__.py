"""WineBox admin panel — standalone FastAPI application.

Ships inside the main `winebox` package and shares its version. The admin
server is launched separately (different port, different systemd unit) but
imports the same wine domain models, services, and auth.
"""

from winebox import __version__

__all__ = ["__version__"]
