"""Pure-httpx Carousell profile fetcher — no browser, no fork, sandbox-safe.

Carousell server-renders the profile's `<head>` (og:title, og:image, the
description meta) even though the listing grid is client-side. That head is
enough to build a card: display name, avatar, and a seed description. This
replaces the Playwright scraper in `catbuilder.fetcher` for environments where
Chromium can't launch (e.g. the preview sandbox).

Listing thumbnails are JS-rendered and therefore not available here; cards fall
back to the avatar + brand tint, which the PDF renderer already handles.
"""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path
from typing import Optional

import httpx

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_META_RE = re.compile(r"<meta[^>]+>", re.I)
_CONTENT_RE = re.compile(r'content=["\']([^"\']*)["\']', re.I)
_TIER_RE = re.compile(r"(Certified Partner|Professional Seller|Verified)", re.I)


def _meta(html: str, needle: str) -> str:
    """Return the `content` of the first <meta> tag containing `needle`."""
    for tag in _META_RE.findall(html):
        if needle in tag:
            m = _CONTENT_RE.search(tag)
            if m:
                return m.group(1).strip()
    return ""


def _clean_name(og_title: str, handle: str) -> str:
    # og:title is "<name> is on Carousell"
    name = re.sub(r"\s+is on Carousell\s*$", "", og_title, flags=re.I).strip()
    if not name or name.lower() == handle.lower():
        return handle.title()
    return name


def fetch_profile_http(handle: str, cache_dir: Path, throttle: float = 1.0) -> Optional[dict]:
    """Fetch + cache profile fields via static HTML. None if the handle is dead."""
    cache_dir = Path(cache_dir)
    profiles_dir = cache_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    cache_file = profiles_dir / f"{handle}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    url = f"https://www.carousell.sg/u/{handle}/"
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": _UA})
    except Exception:
        return None

    if resp.status_code == 404:
        return None

    html = resp.text or ""
    og_title = _meta(html, "og:title")
    if not og_title:
        # No server-rendered profile head → treat as dead/unresolvable.
        return None

    description_meta = _meta(html, 'name="description"')
    tier_m = _TIER_RE.search(description_meta) or _TIER_RE.search(html[:20000])

    data = {
        "handle": handle,
        "profile_url": str(resp.url),
        "display_name": _clean_name(og_title, handle),
        "bio": description_meta,
        "avatar_url": _meta(html, "og:image"),
        "seller_tier": tier_m.group(1) if tier_m else "",
        "listing_titles": [],
        "listing_image_urls": [],
    }

    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    if throttle:
        time.sleep(throttle)
    return data


def download_avatar_http(avatar_url: str, handle: str, cache_dir: Path) -> Optional[Path]:
    if not avatar_url:
        return None
    avatars_dir = Path(cache_dir) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    out = avatars_dir / f"{handle}.png"
    if out.exists():
        return out
    try:
        resp = httpx.get(avatar_url, timeout=15, follow_redirects=True, headers={"User-Agent": _UA})
        resp.raise_for_status()
        from PIL import Image
        Image.open(io.BytesIO(resp.content)).convert("RGBA").save(out, "PNG")
        return out
    except Exception:
        return None


def fetch_and_cache_http(merchant, cache_dir: Path, throttle: float = 1.0):
    """Drop-in for catbuilder.fetcher.fetch_and_cache, mutating merchant in place."""
    data = fetch_profile_http(merchant.handle, cache_dir, throttle)
    if data is None:
        return merchant
    merchant.display_name = data.get("display_name") or merchant.handle.title()
    merchant.bio = data.get("bio") or ""
    merchant.profile_url = data.get("profile_url") or f"https://www.carousell.sg/u/{merchant.handle}/"
    avatar_url = data.get("avatar_url") or ""
    if avatar_url:
        path = download_avatar_http(avatar_url, merchant.handle, cache_dir)
        if path:
            merchant.avatar_path = path
    return merchant
