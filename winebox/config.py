"""Configuration settings for WineBox application.

This module re-exports the settings from the new config package
for backward compatibility. New code should import from winebox.config
directly.

Example:
    from winebox.config import settings
    print(settings.mongodb_url)
"""

# Re-export from the new config package
from winebox.config.settings import Settings, get_settings, reset_settings, settings

__all__ = [
    "Settings",
    "get_settings",
    "reset_settings",
    "settings",
]
