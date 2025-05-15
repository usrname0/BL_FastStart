# This file is: blender_faststart/libs/qtfaststart/__init__.py
# It makes the 'qtfaststart' directory a Python package and
# exposes its core modules.

# Import the key modules from this package so they are available
# when someone does 'import qtfaststart' and then 'qtfaststart.processor'

from . import processor
from . import exceptions

# Optionally, you could also expose specific functions or classes directly, e.g.:
# from .processor import process
# from .exceptions import FastStartSetupError, MalformedFileError, UnsupportedFormatError

# Keeping them as submodules (qtfaststart.processor, qtfaststart.exceptions)
# is a common and clean way, which the current extension_logic.py expects.

# You can also define package-level variables if needed, like __version__
# For example:
# __version__ = "1.8.0" # Or whatever version of qtfaststart you bundled