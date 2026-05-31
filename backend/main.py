"""ASGI entry point.

The application is assembled in the ``backend.app`` package; this module only
re-exports it so the well-known import path ``backend.main:app`` (uvicorn,
gunicorn, systemd, run.py and the tests) keeps working.
"""

from backend.app import app

__all__ = ["app"]
