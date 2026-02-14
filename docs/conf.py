"""Sphinx configuration for WineBox documentation."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(".."))

from winebox import __version__

# Project information
project = "WineBox"
copyright = "2024, WineBox Team"
author = "WineBox Team"
version = __version__
release = __version__

# General configuration
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Options for HTML output
# Use Read the Docs theme if available, otherwise fall back to alabaster
try:
    import sphinx_rtd_theme
    html_theme = "sphinx_rtd_theme"
    html_theme_options = {
        "navigation_depth": 4,
        "collapse_navigation": False,
    }
except ImportError:
    html_theme = "alabaster"
    html_theme_options = {
        "description": "Wine Cellar Management Application",
        "github_user": "jdrumgoole",
        "github_repo": "winebox",
    }

html_static_path = ["_static"]

# MyST parser settings
myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

# Autodoc settings
autodoc_member_order = "bysource"
autodoc_typehints = "description"

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
