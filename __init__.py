"""BL Fast Start - package entry point; all logic lives in extension_logic."""

from .extension_logic import register, unregister

__all__ = ("register", "unregister")
