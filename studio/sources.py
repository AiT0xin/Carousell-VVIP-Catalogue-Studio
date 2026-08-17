"""Wire the unified Studio to the two proven engine packages.

This is the ONLY place that knows where the engine code lives. Everything else
imports the re-exported names from here, so if the engines move we change one
file.

  - qrcheck     (vendored at repo root)  — extraction, master ingest, live verify
  - catbuilder  (vendored at repo root)  — profile fetch, describe, QR gen, render

Heavy / native-backed entry points (QR decode → cv2+pyzbar, live verify + profile
fetch → Playwright) are **lazy**: the underlying module is imported the first time
the wrapper is *called*, not at import time. That keeps a worker stage from
loading libraries it doesn't use — e.g. an offline QR check pulls in neither
OpenCV nor Playwright — which also avoids segfaulting native libs in a freshly
spawned subprocess.

Importing the `qrcheck` package first installs its zbar shared-library shim
(required for pyzbar on Homebrew/Apple-Silicon) before anything touches pyzbar.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Lightweight + shim only. (The shim just sets ctypes search paths; it does not
# import pyzbar or OpenCV, so this stays cheap.)
import qrcheck  # noqa: E402,F401

# ── Eager: pure-python / no native or browser deps ──────────────────────────
from qrcheck.ingest import load_master, category_from_pdf_name, MasterTable  # noqa: E402
from qrcheck.normalize import (  # noqa: E402
    normalize_handle,
    profile_url_for,
    classify_url,
    handle_from_profile_url,
)
from qrcheck.models import QRClass, ExtractedRow, PrintedHandle, VerifyResult  # noqa: E402

from catbuilder.models import (  # noqa: E402
    MerchantData,
    CatalogueSection,
    CatalogueJob,
    colour_for_category,
)
from catbuilder.describer import generate_description, ai_configured  # noqa: E402  (OpenAI-compatible, no native)
from catbuilder.qrgen import generate_qr  # noqa: E402            (imports qrcode, no native)
from catbuilder.pdf_render import render_pdf  # noqa: E402         (imports reportlab, no native)


# ── Lazy: heavy native (OpenCV/pyzbar) or browser (Playwright) ──────────────
def extract_pdf(*args, **kwargs):
    """QR + handle extraction (loads OpenCV + pyzbar + pdfplumber on first call)."""
    from qrcheck.extract import extract_pdf as _f
    return _f(*args, **kwargs)


def get_verifier(*args, **kwargs):
    """Live profile verifier (loads Playwright on first call)."""
    from qrcheck.verify import get_verifier as _f
    return _f(*args, **kwargs)


def VerifierConfig(*args, **kwargs):
    from qrcheck.verify.base import VerifierConfig as _f
    return _f(*args, **kwargs)


def fetch_and_cache(*args, **kwargs):
    """Scrape + cache a Carousell profile.

    Uses the pure-httpx fetcher (static `<head>` parse) so it runs in any
    environment, including sandboxes where Chromium can't launch. The Playwright
    scraper in catbuilder is no longer used by the Studio.
    """
    from .profile_http import fetch_and_cache_http as _f
    return _f(*args, **kwargs)


def download_listing_images(*args, **kwargs):
    """Download listing thumbnail images for a merchant (pure httpx, no browser)."""
    from catbuilder.fetcher import download_listing_images as _f
    return _f(*args, **kwargs)


__all__ = [
    "extract_pdf",
    "load_master",
    "category_from_pdf_name",
    "MasterTable",
    "normalize_handle",
    "profile_url_for",
    "classify_url",
    "handle_from_profile_url",
    "QRClass",
    "ExtractedRow",
    "PrintedHandle",
    "VerifyResult",
    "get_verifier",
    "VerifierConfig",
    "MerchantData",
    "CatalogueSection",
    "CatalogueJob",
    "colour_for_category",
    "fetch_and_cache",
    "generate_description",
    "ai_configured",
    "generate_qr",
    "render_pdf",
]
