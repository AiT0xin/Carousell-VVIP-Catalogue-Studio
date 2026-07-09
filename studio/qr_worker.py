"""Isolated QR verifier — spawned as a subprocess by studio/qr.py.

Uses httpx (no browser) so it runs in any environment, including the preview
sandbox where Chromium can't initialise its renderer process.

Reads JSON from stdin:
  {"targets": [{"handle": "...", "decoded_url": "...", "decoded_handle": "..."}, ...]}

Writes one JSON line per verified merchant to stdout.
Exits 0 always (individual errors are reported per-merchant, not as a crash).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

for root in [Path.home() / "qr-catalogue-checker", Path.home() / "catalogue-builder"]:
    if root.exists() and str(root) not in sys.path:
        sys.path.insert(0, str(root))

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_NOT_FOUND = re.compile(r"404 page|can'?t find the page|page not found", re.I)
_CANONICAL = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I)
_OG_URL    = re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_GENERIC_TITLE = "carousell - snap to list, chat to buy"


def _handle_from_url(url: str) -> str:
    """Extract lowercase handle from a Carousell profile URL."""
    if not url:
        return ""
    parts = urlparse(url).path.rstrip("/").split("/")
    for i, p in enumerate(parts):
        if p == "u" and i + 1 < len(parts):
            return parts[i + 1].lstrip("@").lower()
    return ""


def _verify_http(url: str) -> dict:
    try:
        import httpx
    except ImportError:
        import requests as _req
        class _compat:
            @staticmethod
            def get(u, **kw):
                r = _req.get(u, **kw)
                r.text  # already a property
                return r
        httpx = _compat

    # Validate URL scheme before fetching (prevent file://, data://, etc.)
    parsed_input = urlparse(url)
    if parsed_input.scheme not in ("http", "https"):
        return {"is_live": False, "qr_status": "error", "resolves_to": "", "detail": "invalid URL scheme"}

    try:
        with httpx.Client(
            follow_redirects=True,
            max_redirects=5,
            timeout=20,
            headers={"User-Agent": _UA},
        ) as _client:
            resp = _client.get(url)
    except Exception as e:
        return {"is_live": False, "qr_status": "error", "resolves_to": "", "detail": str(e)}

    final_url = str(resp.url)
    # Limit HTML body size before running regex (prevent ReDoS on pathological input)
    text = (resp.text or "")[:1_000_000]

    # Bounced to homepage → dead
    parsed = urlparse(final_url)
    if parsed.path in ("", "/") and "carousell" in parsed.netloc.lower():
        return {"is_live": False, "qr_status": "dead", "resolves_to": "", "detail": "redirected to homepage"}

    # 404 copy in body → dead
    if _NOT_FOUND.search(text):
        return {"is_live": False, "qr_status": "dead", "resolves_to": "", "detail": "404 / handle not found"}

    # Canonical / og:url → ground-truth handle
    canon_url = ""
    m = _CANONICAL.search(text) or _OG_URL.search(text)
    if m:
        canon_url = m.group(1)
    resolves_to = _handle_from_url(canon_url) or _handle_from_url(final_url)

    if resp.status_code == 200 and resolves_to:
        return {"is_live": True, "qr_status": "live", "resolves_to": resolves_to, "detail": f"http 200, handle={resolves_to}"}

    return {"is_live": False, "qr_status": "dead", "resolves_to": resolves_to, "detail": f"http {resp.status_code}"}


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception as e:
        sys.stderr.write(f"bad stdin: {e}\n")
        sys.exit(1)

    targets = data.get("targets", [])
    throttle = 1.0  # seconds between requests (ToS-friendly)
    last = 0.0

    for t in targets:
        handle = t["handle"]
        url = t.get("decoded_url", "")
        if not url:
            print(json.dumps({"handle": handle, "skipped": True}), flush=True)
            continue

        wait = throttle - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.monotonic()

        result = _verify_http(url)
        result["handle"] = handle
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
