"""Catalogue QR & Merchant Verifier.

Importing this package installs the zbar shared-library shim (see _zbar_shim)
so that `from pyzbar import pyzbar` works on Homebrew/Apple-Silicon setups where
the dylib lives in /opt/homebrew/lib and ctypes' find_library cannot see it.
"""
from . import _zbar_shim  # noqa: F401  (side effect: make libzbar importable)

__version__ = "0.1.0"
