"""Shared library for the NBE GB10 demos."""
from nbe_core.app import create_app
from nbe_core.settings import settings

__all__ = ["create_app", "settings"]
