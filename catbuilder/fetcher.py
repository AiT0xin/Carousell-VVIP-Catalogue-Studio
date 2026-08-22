"""Carousell profile scraper.

Uses Playwright headless Chromium to fetch:
  - display_name
  - bio / tagline
  - avatar image URL
  - category (seller type shown on profile)
  - seller tier (Professional seller, Certified Partner, etc.)

Results are cached to <cache_dir>/profiles/<handle>.json.
Avatar images are cached to <cache_dir>/avatars/<handle>.png.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

from .models import MerchantData

# ── Carousell DOM signal patterns ────────────────────────────────────────────

_404_PATTERNS = [
    "404 page",
    "can't find the page",
    "page not found",
    "this page doesn't exist",
]

_DEFAULT_TITLE = "carousell - snap to list, chat to buy"


def _is_dead(page: Page) -> bool:
    body = page.inner_text("body").lower()
    for p in _404_PATTERNS:
        if p in body:
            return True
    title = page.title().lower()
    if title == _DEFAULT_TITLE or "page not found" in title:
        return True
    return False


def _extract_profile(page: Page) -> dict:
    """Extract profile fields from a loaded Carousell profile page."""
    data: dict = {}

    # Display name - look for h1 or og:title
    try:
        h1 = page.query_selector("h1")
        if h1:
            data["display_name"] = h1.inner_text().strip()
    except Exception:
        pass

    if not data.get("display_name"):
        try:
            meta = page.query_selector("meta[property='og:title']")
            if meta:
                og_title = meta.get_attribute("content") or ""
                # og:title is usually "Handle (@handle) on Carousell" - strip suffix
                og_title = re.sub(r"\s*\(@[^)]+\)\s*on Carousell.*$", "", og_title).strip()
                if og_title:
                    data["display_name"] = og_title
        except Exception:
            pass

    # Bio / tagline
    try:
        # Try common Carousell bio selector patterns
        for sel in [
            "[data-testid='user-bio']",
            "[class*='UserBio']",
            "[class*='bio']",
            "p[class*='D_']",
        ]:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if len(text) > 10:
                    data["bio"] = text
                    break
    except Exception:
        pass

    # Seller tier
    tier = ""
    try:
        body_text = page.inner_text("body")
        for t in ["Certified Partner", "Professional Seller", "Professional seller"]:
            if t.lower() in body_text.lower():
                tier = t
                break
    except Exception:
        pass
    data["seller_tier"] = tier

    # Listing titles + thumbnail image URLs - scraped while page is open
    listing_titles: list[str] = []
    listing_image_urls: list[str] = []
    try:
        cards = page.query_selector_all("a[href*='/p/']")
        seen_titles: set[str] = set()
        seen_imgs: set[str] = set()
        for card in cards[:24]:
            try:
                title_found = False
                for sel in ["p", "span[class*='D_']", "span[class*='title' i]", "div[class*='title' i]"]:
                    el = card.query_selector(sel)
                    if el:
                        t = el.inner_text().strip()
                        if len(t) > 4 and t not in seen_titles:
                            seen_titles.add(t)
                            listing_titles.append(t)
                            title_found = True
                            break

                # Grab the thumbnail image from the same card
                img_el = card.query_selector("img")
                if img_el:
                    src = (img_el.get_attribute("src") or
                           img_el.get_attribute("data-src") or "")
                    if src.startswith("http") and src not in seen_imgs:
                        seen_imgs.add(src)
                        listing_image_urls.append(src)
            except Exception:
                pass
            if len(listing_titles) >= 6:
                break
    except Exception:
        pass
    data["listing_titles"] = listing_titles
    data["listing_image_urls"] = listing_image_urls[:4]

    # Avatar URL - try og:image first, then profile image elements
    avatar_url = ""
    try:
        meta = page.query_selector("meta[property='og:image']")
        if meta:
            url = meta.get_attribute("content") or ""
            if url and "carousell" in url.lower() or "avatar" in url.lower() or url.startswith("http"):
                avatar_url = url
    except Exception:
        pass

    if not avatar_url:
        try:
            for sel in [
                "img[alt*='avatar']",
                "img[class*='avatar']",
                "img[class*='Avatar']",
                "img[class*='profile']",
            ]:
                el = page.query_selector(sel)
                if el:
                    src = el.get_attribute("src") or ""
                    if src.startswith("http"):
                        avatar_url = src
                        break
        except Exception:
            pass

    data["avatar_url"] = avatar_url
    return data


def fetch_profile(
    handle: str,
    cache_dir: Path,
    throttle: float = 2.0,
) -> Optional[dict]:
    """Fetch and cache profile data for a given handle.

    Returns a dict with keys: handle, display_name, bio, avatar_url, seller_tier.
    Returns None if the profile is dead/not found.
    """
    cache_dir = Path(cache_dir)
    profiles_dir = cache_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    cache_file = profiles_dir / f"{handle}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    profile_url = f"https://www.carousell.sg/u/{handle}/"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        try:
            page.goto(profile_url, wait_until="networkidle", timeout=30_000)
        except PWTimeout:
            page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)

        if _is_dead(page):
            browser.close()
            return None

        data = _extract_profile(page)
        data["handle"] = handle
        data["profile_url"] = profile_url
        browser.close()

    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    time.sleep(throttle)
    return data


def download_avatar(
    avatar_url: str,
    handle: str,
    cache_dir: Path,
) -> Optional[Path]:
    """Download and cache avatar image, returning local path.

    Converts to PNG if needed. Returns None on failure.
    """
    if not avatar_url:
        return None

    avatars_dir = Path(cache_dir) / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    out_path = avatars_dir / f"{handle}.png"

    if out_path.exists():
        return out_path

    try:
        resp = httpx.get(avatar_url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return None

    from PIL import Image
    import io

    try:
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img.save(out_path, "PNG")
        return out_path
    except Exception:
        return None


def download_listing_images(
    handle: str,
    image_urls: list[str],
    cache_dir: Path,
) -> list[Path]:
    """Download and cache up to 4 listing thumbnail images."""
    listings_dir = Path(cache_dir) / "listings" / handle
    listings_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, url in enumerate(image_urls[:4]):
        out = listings_dir / f"{i}.jpg"
        if out.exists():
            paths.append(out)
            continue
        try:
            resp = httpx.get(url, timeout=12, follow_redirects=True)
            resp.raise_for_status()
            out.write_bytes(resp.content)
            paths.append(out)
        except Exception:
            pass
    return paths


def fetch_and_cache(
    merchant: MerchantData,
    cache_dir: Path,
    throttle: float = 2.0,
) -> MerchantData:
    """Fetch profile + download avatar for a MerchantData, mutating it in place."""
    data = fetch_profile(merchant.handle, cache_dir, throttle)
    if data is None:
        print(f"  @{merchant.handle} - profile not found, skipping")
        return merchant

    merchant.display_name = data.get("display_name") or merchant.handle.title()
    merchant.bio = data.get("bio") or ""
    merchant.profile_url = data.get("profile_url") or f"https://www.carousell.sg/u/{merchant.handle}/"

    avatar_url = data.get("avatar_url") or ""
    if avatar_url:
        path = download_avatar(avatar_url, merchant.handle, cache_dir)
        if path:
            merchant.avatar_path = path

    return merchant
