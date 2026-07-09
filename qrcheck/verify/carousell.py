"""Carousell-specific live-profile verifier.

Liveness contract (from the spec's hard-won lesson): HTTP 200 is NOT a pass. We
render the page with a real browser (JS executed) and assert the destination is
a *live merchant profile* — not a blank shell, not a "user doesn't exist" page.

Signals used (resilient-first, tuned against live DOM):
  * URL/canonical/og:url  -> the destination username (ground truth for matching)
  * "not found" / "doesn't exist" copy or a bounce to home -> DEAD/RENAMED
  * presence of profile chrome (listing cards, profile header, join date,
    review/feedback counts) -> live
Blank responses are retried (transient fetch glitches) before being trusted.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from ..models import VerifyResult
from ..normalize import normalize_handle, handle_from_profile_url
from .base import Verifier, VerifierConfig

# Body copy Carousell serves for a missing/orphaned handle. Tuned against the
# real 404 page ("You found our 404 page! We can't find the page you...").
_NOT_FOUND_PATTERNS = [
    re.compile(r"404 page", re.I),
    re.compile(r"can'?t find the page", re.I),
    re.compile(r"page not found", re.I),
]
# Generic homepage <title> Carousell serves on the 404; a real profile's title
# is "<Name>'s Profile Page on Carousell | ...".
_GENERIC_TITLE = "carousell - snap to list, chat to buy"

# Active-seller signals in the rendered body.
_REVIEWS_RE = re.compile(r"([\d,]+)\s+reviews", re.I)
_ORDERS_RE = re.compile(r"([\d,]+)\s+orders", re.I)
# Carousell seller tiers that act as the "verified / real account" badge.
_SELLER_TIER_RE = re.compile(
    r"(certified partner|professional seller|preferred seller|verified)", re.I)


class CarousellVerifier(Verifier):
    def __init__(self, config: Optional[VerifierConfig] = None):
        super().__init__(config)
        self._pw = None
        self._browser = None

    # -- browser lifecycle ------------------------------------------------ #
    def _ensure_browser(self):
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.config.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        finally:
            super().close()

    # -- core verify ------------------------------------------------------ #
    def _verify_uncached(self, url: str) -> VerifyResult:
        # Step 1: cheap redirect resolution (reveals shortlink destination,
        # hard dead links). Some hosts block HEAD/GET bots, so a failure here is
        # not conclusive — we still try a render.
        resolved = self.resolve(url)
        final_url = resolved.final_url or url

        # Step 2: render with retries on blank.
        result = None
        for attempt in range(self.config.blank_retries):
            result = self._render_profile(final_url)
            if not _looks_blank(result):
                break
            time.sleep(self.config.retry_backoff * (attempt + 1))

        if result is None:
            result = VerifyResult(final_url=final_url, qr_status="error",
                                  detail="no render result")
        # Only surface the cheap resolver's status when the browser also failed.
        # On Carousell, the python-requests UA is often 403'd by the edge while
        # Chromium loads fine; reporting that 403 next to a successful render
        # is misleading noise.
        if resolved.status_code and not result.is_live_profile and result.qr_status != "dead":
            result.detail = (result.detail + f" [http {resolved.status_code}]").strip()
        if not result.final_url:
            result.final_url = final_url
        return result

    # -- rendering -------------------------------------------------------- #
    def _render_profile(self, url: str) -> VerifyResult:
        self._ensure_browser()
        self._throttle()
        ctx = self._browser.new_context(
            user_agent=self.config.user_agent,
            viewport={"width": 1280, "height": 1600},
        )
        page = ctx.new_page()
        res = VerifyResult(final_url=url)
        try:
            try:
                page.goto(url, wait_until="domcontentloaded",
                          timeout=int(self.config.timeout_seconds * 1000))
            except Exception as e:
                res.qr_status = "error"
                res.detail = f"nav: {type(e).__name__}"
                return res
            # let client-side rendering settle
            try:
                page.wait_for_load_state("networkidle",
                                         timeout=int(self.config.timeout_seconds * 1000))
            except Exception:
                pass

            landed = page.url
            res.final_url = landed
            title = (page.title() or "").strip()
            body_text = (page.inner_text("body") if page.query_selector("body") else "") or ""

            # Ground-truth username comes from canonical/og:url — present only on
            # a real profile page; absent on the 404.
            canonical_handle = self._username_from_meta(page)
            res.resolves_to_handle = canonical_handle or handle_from_profile_url(landed)

            is_404 = (_is_not_found(body_text)
                      or title.lower() == _GENERIC_TITLE
                      or _bounced_home(landed))

            # DEAD: 404 page / orphaned slug — no canonical, generic title.
            if is_404 and canonical_handle is None:
                res.is_live_profile = False
                res.qr_status = "dead"
                res.detail = "404 / handle not found"
                self._maybe_screenshot(page, res, "dead")
                return res

            # Profile chrome exists (canonical present). Measure activity.
            reviews = _first_int(_REVIEWS_RE, body_text)
            orders = _first_int(_ORDERS_RE, body_text)
            listing_count = len(page.query_selector_all("a[href*='/p/']"))
            tier = _SELLER_TIER_RE.search(body_text)
            res.verified_badge = bool(tier)
            active = (reviews > 0) or (orders > 0) or (listing_count > 0) or bool(tier)

            if canonical_handle and active:
                res.is_live_profile = True
                res.qr_status = "live"
                bits = []
                if tier:
                    bits.append(tier.group(1).lower())
                if reviews:
                    bits.append(f"{reviews} reviews")
                if orders:
                    bits.append(f"{orders} orders")
                if listing_count:
                    bits.append(f"≈{listing_count} listings")
                res.detail = ", ".join(bits) or "profile rendered"
            else:
                # Canonical present but no listings/reviews/tier: empty placeholder
                # — the renamed-and-orphaned shell the spec warns about.
                res.is_live_profile = False
                res.qr_status = "blank-shell"
                res.detail = "profile shell, 0 listings/reviews, not verified"
                self._maybe_screenshot(page, res, "blankshell")
            return res
        finally:
            try:
                page.close(); ctx.close()
            except Exception:
                pass

    # -- helpers ---------------------------------------------------------- #
    @staticmethod
    def _username_from_meta(page) -> Optional[str]:
        for sel, attr in (("link[rel='canonical']", "href"),
                          ("meta[property='og:url']", "content")):
            el = page.query_selector(sel)
            if el:
                val = el.get_attribute(attr)
                h = handle_from_profile_url(val)
                if h:
                    return h
        return None

    def _maybe_screenshot(self, page, res: VerifyResult, tag: str):
        if not self.config.screenshot_dir:
            return
        try:
            d = Path(self.config.screenshot_dir)
            d.mkdir(parents=True, exist_ok=True)
            handle = res.resolves_to_handle or "unknown"
            path = d / f"{tag}_{handle}.png"
            page.screenshot(path=str(path), full_page=False)
            res.screenshot_path = str(path)
        except Exception:
            pass


# -- module-level predicates ---------------------------------------------- #
def _first_int(pattern: re.Pattern, text: str) -> int:
    m = pattern.search(text)
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except (ValueError, IndexError):
        return 0


def _is_not_found(body_text: str) -> bool:
    return any(p.search(body_text) for p in _NOT_FOUND_PATTERNS)


def _bounced_home(landed_url: str) -> bool:
    p = urlparse(landed_url)
    return p.path in ("", "/") and "carousell" in p.netloc.lower()


def _looks_blank(res: Optional[VerifyResult]) -> bool:
    return res is not None and res.qr_status in ("blank", "error")
