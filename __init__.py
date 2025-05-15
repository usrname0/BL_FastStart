# __init__.py
# This file makes the 'ffmpeg_fast_start' directory a Python package
# and serves as the entry point for Blender to find register/unregister functions.

# Ensure that relative imports work correctly if this file is somehow run directly
# (less common for extensions as Blender handles their loading).
# The __package__ variable should be automatically set by Python when Blender imports this extension.
# It should match the 'id' from your blender_manifest.toml (e.g., "ffmpeg_fast_start").

from .extension_logic import register, unregister

# If you had other modules or sub-packages within your extension,
# you could organize their imports here as well.

# The presence of this __init__.py (even if almost empty but for imports)
# signals to Python that this directory is a package. Blender's extension
# system relies on this to correctly load your code.
