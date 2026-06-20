"""Feature 2 — QR check.

For every merchant card in the catalogue, prove its QR is trustworthy:

  1. decode-match  — the handle encoded in the QR equals the handle printed on
                     the card
  2. live          — the link resolves to a *live* profile (not a 404)
  3. right page    — it lands on the printed merchant, not a renamed/blank shell
                     (the "soft-404": a page that loads but isn't the merchant)

Each card ends up with one status:
  ok · mismatch · renamed · dead · soft-404 · no-qr

Anything broken emits a `replace_qr` ProposedChange that regenerates the QR from
the correct profile URL, for the user to approve.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .sources import (
    normalize_handle,
    profile_url_for,
)
from .state import (
    StudioSession,
    MerchantRecord,
    ProposedChange,
    QR_OK,
    QR_MISMATCH,
    QR_RENAMED,
    QR_DEAD,
    QR_SOFT404,
    QR_NONE,
    QR_UNKNOWN,
)

# Map the verifier's labels onto our broken-QR vocabulary.
_NOT_LIVE = {
    "dead": QR_DEAD,
    "error": QR_DEAD,
    "blank-shell": QR_SOFT404,
    "blank": QR_SOFT404,
}


def _classify(rec: MerchantRecord, res) -> str:
    """Decide a QR status from the printed handle + the verify result."""
    printed = rec.handle
    decoded = normalize_handle(rec.decoded_handle) if rec.decoded_handle else ""

    # A QR that plainly encodes a different handle than the card shows is a
    # mismatch regardless of whether that other handle happens to be live.
    if decoded and decoded != printed:
        return QR_MISMATCH

    if res is None:
        return QR_UNKNOWN

    if not res.is_live_profile:
        return _NOT_LIVE.get(res.qr_status, QR_DEAD)

    dest = normalize_handle(res.resolves_to_handle) if res.resolves_to_handle else ""
    if dest and dest != printed:
        return QR_RENAMED

    return QR_OK


_REASONS = {
    QR_MISMATCH: "QR encodes a different handle than the card shows",
    QR_RENAMED:  "QR lands on a renamed account, not the printed handle",
    QR_DEAD:     "QR link is dead (profile not found)",
    QR_SOFT404:  "QR loads a blank shell, not the merchant's profile",
    QR_NONE:     "Card has no QR code",
}


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_NOT_FOUND = re.compile(r"404 page|can'?t find the page|page not found", re.I)
_CANONICAL = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I)
_OG_URL = re.compile(
    r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I)


def _handle_from_url(url: str) -> str:
    if not url:
        return ""
    parts = urlparse(url).path.rstrip("/").split("/")
    for i, p in enumerate(parts):
        if p == "u" and i + 1 < len(parts):
            return parts[i + 1].lstrip("@").lower()
    return ""


def _http_verify(url: str) -> dict:
    try:
        import httpx
        resp = httpx.get(url, follow_redirects=True, timeout=20,
                         headers={"User-Agent": _UA})
    except Exception as e:
        return {"is_live": False, "qr_status": "error", "resolves_to": "", "detail": str(e)}

    final_url = str(resp.url)
    text = resp.text or ""
    parsed = urlparse(final_url)

    if parsed.path in ("", "/") and "carousell" in parsed.netloc.lower():
        return {"is_live": False, "qr_status": "dead", "resolves_to": "", "detail": "redirected to homepage"}
    if _NOT_FOUND.search(text):
        return {"is_live": False, "qr_status": "dead", "resolves_to": "", "detail": "404 / handle not found"}

    m = _CANONICAL.search(text) or _OG_URL.search(text)
    resolves_to = _handle_from_url(m.group(1) if m else "") or _handle_from_url(final_url)

    if resp.status_code == 200 and resolves_to:
        return {"is_live": True, "qr_status": "live", "resolves_to": resolves_to,
                "detail": f"http 200, handle={resolves_to}"}
    return {"is_live": False, "qr_status": "dead", "resolves_to": resolves_to,
            "detail": f"http {resp.status_code}"}


def _live_verify_inline(targets: list[MerchantRecord]) -> dict[str, dict]:
    """HTTP-based verification — no subprocess, no browser, works in any sandbox."""
    results: dict[str, dict] = {}
    for rec in targets:
        if not rec.decoded_url:
            continue
        time.sleep(0.8)  # ToS-friendly throttle
        row = _http_verify(rec.decoded_url)
        row["handle"] = rec.handle
        results[rec.handle] = row
    return results


def run_qrcheck(
    session: StudioSession,
    do_live: bool = True,
    progress_cb: Optional[Callable[[int, int, MerchantRecord], None]] = None,
) -> StudioSession:
    """Check every in-catalogue card's QR; emit replace_qr proposals."""
    targets = [m for m in session.in_catalogue()]
    n = len(targets)

    session.clear_changes("qrcheck")

    # ── Live verification via isolated subprocess ────────────────────────────
    live_results: dict[str, dict] = {}
    if do_live:
        live_results = _live_verify_inline(targets)

    # ── Classify each card ───────────────────────────────────────────────────
    class _Res:
        def __init__(self, row: dict) -> None:
            self.is_live_profile = row.get("is_live", False)
            self.resolves_to_handle = row.get("resolves_to", "")
            self.qr_status = row.get("qr_status", "error")
            self.detail = row.get("detail", "")

    for i, rec in enumerate(targets):
        if not rec.decoded_url:
            rec.qr_status = QR_NONE
            rec.qr_detail = "no QR found on card"
            rec.qr_live = None
        else:
            row = live_results.get(rec.handle, {})
            if row and "error" not in row and "skipped" not in row:
                res = _Res(row)
                rec.qr_live = res.is_live_profile
                rec.resolves_to = res.resolves_to_handle
                rec.qr_detail = res.detail
                rec.qr_status = _classify(rec, res)
            elif row.get("error"):
                rec.qr_status = QR_UNKNOWN
                rec.qr_detail = row["error"]
            else:
                rec.qr_status = _classify(rec, None)

        if progress_cb:
            progress_cb(i + 1, n, rec)

    # Emit replace-QR proposals for everything broken.
    for rec in targets:
        if rec.qr_broken:
            # For a renamed account the working destination is where it landed;
            # otherwise the canonical target is the printed handle's profile.
            target_handle = rec.handle
            tgt_url = profile_url_for(target_handle)
            session.set_change(ProposedChange(
                kind="replace_qr",
                handle=rec.handle,
                display_name=rec.display_name or rec.handle,
                reason=f"{_REASONS.get(rec.qr_status, rec.qr_status)} "
                       f"→ regenerate QR to {tgt_url}",
                source="qrcheck",
            ))

    session.qrcheck_done = True
    return session


def qrcheck_summary(session: StudioSession) -> dict:
    cards = session.in_catalogue()
    from collections import Counter
    counts = Counter(c.qr_status for c in cards)
    return {
        "total": len(cards),
        "ok":       counts.get(QR_OK, 0),
        "mismatch": counts.get(QR_MISMATCH, 0),
        "renamed":  counts.get(QR_RENAMED, 0),
        "dead":     counts.get(QR_DEAD, 0),
        "soft404":  counts.get(QR_SOFT404, 0),
        "no_qr":    counts.get(QR_NONE, 0),
    }
