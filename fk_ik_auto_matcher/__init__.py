"""Standalone FK/IK Auto Matcher for Autodesk Maya."""

__version__ = "1.0.0"

def show():
    """Open the matcher UI inside Maya.

    The import is intentionally lazy so data models and unit tests can be used
    in a regular Python environment where PySide6 and Maya are unavailable.
    """
    from .main import show as _show

    return _show()

__all__ = ["show", "__version__"]
