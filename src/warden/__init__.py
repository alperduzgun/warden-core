"""
Warden - AI Code Guardian

Global code analyzer with project-level architectural validation.
"""

try:
    from ._version import __version__
except ImportError:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("warden-core")
    except PackageNotFoundError:
        __version__ = "0.0.0+unknown"
__author__ = "Warden Team"

__all__ = ["__version__", "__author__"]
