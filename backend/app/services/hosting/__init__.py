"""Hosting services package.

Import concrete services from their modules directly, e.g.
``from app.services.hosting.files import FileManagerService``.
This package intentionally avoids re-exporting services at import time
to prevent circular imports with application discovery.
"""
