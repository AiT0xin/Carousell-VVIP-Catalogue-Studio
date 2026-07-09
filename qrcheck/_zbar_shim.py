"""Make Homebrew's libzbar discoverable by pyzbar.

pyzbar loads the zbar shared library via ``ctypes.util.find_library('zbar')``.
On macOS/Apple-Silicon, Homebrew installs the dylib under ``/opt/homebrew/lib``,
which is *not* on the default dyld search path, so find_library returns None and
``import pyzbar`` raises ``ImportError: Unable to find zbar shared library``.

We patch find_library so that a request for "zbar" resolves to the first dylib
we can locate, searching the common Homebrew prefixes. This runs at import time,
before pyzbar is imported anywhere, so callers never need to set
DYLD_LIBRARY_PATH by hand.
"""
from __future__ import annotations

import ctypes.util
import os
from pathlib import Path

# Candidate library directories, in priority order. Covers Apple-Silicon
# (/opt/homebrew), Intel Homebrew (/usr/local), and MacPorts.
_SEARCH_DIRS = [
    os.environ.get("ZBAR_LIB_DIR", ""),
    "/opt/homebrew/lib",
    "/usr/local/lib",
    "/opt/local/lib",
]
_LIB_NAMES = ["libzbar.dylib", "libzbar.0.dylib", "libzbar.so", "libzbar.so.0"]


def _locate_zbar() -> str | None:
    for d in _SEARCH_DIRS:
        if not d:
            continue
        for name in _LIB_NAMES:
            p = Path(d) / name
            if p.exists():
                return str(p)
    return None


_ZBAR_PATH = _locate_zbar()
_orig_find_library = ctypes.util.find_library


def _patched_find_library(name: str):
    if name == "zbar" and _ZBAR_PATH:
        return _ZBAR_PATH
    return _orig_find_library(name)


# Only patch if the default resolver can't already find it (don't override a
# working system install, e.g. when zbar is on the default path).
if _ZBAR_PATH and not _orig_find_library("zbar"):
    ctypes.util.find_library = _patched_find_library
