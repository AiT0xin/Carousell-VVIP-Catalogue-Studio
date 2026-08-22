"""Verifier interface + shared HTTP redirect resolver and caching.

The resolver (cheap, no browser) follows redirects so we learn a shortlink's
destination and catch obviously-dead links before paying for a headless render.
The browser render (subclass responsibility) is what actually proves a *live*
profile - an HTTP 200 is explicitly *not* a pass (a renamed/deleted handle still
200s with a blank shell).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from ..models import VerifyResult

# A desktop UA; some platforms serve a degraded shell to obvious bots.
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass
class VerifierConfig:
    throttle_seconds: float = 1.5      # min delay between network hits (ToS-friendly)
    timeout_seconds: float = 20.0
    blank_retries: int = 3             # retry consistent blanks before flagging
    retry_backoff: float = 2.0
    user_agent: str = _DEFAULT_UA
    screenshot_dir: Optional[str] = None  # if set, save evidence per flagged row
    headless: bool = True


@dataclass
class ResolveResult:
    final_url: Optional[str]
    status_code: Optional[int]
    ok: bool
    error: str = ""
    redirect_chain: list = field(default_factory=list)


class Verifier:
    """Base class: owns the resolver, throttling, and a per-run URL cache.

    Subclasses implement `_render_profile(url) -> VerifyResult` using a browser.
    """

    def __init__(self, config: Optional[VerifierConfig] = None):
        self.config = config or VerifierConfig()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = self.config.user_agent
        self._cache: dict[str, VerifyResult] = {}
        self._last_hit = 0.0

    # -- throttling ------------------------------------------------------- #
    def _throttle(self):
        wait = self.config.throttle_seconds - (time.monotonic() - self._last_hit)
        if wait > 0:
            time.sleep(wait)
        self._last_hit = time.monotonic()

    # -- redirect resolution (cheap) -------------------------------------- #
    def resolve(self, url: str) -> ResolveResult:
        self._throttle()
        try:
            resp = self._session.get(
                url, allow_redirects=True,
                timeout=self.config.timeout_seconds,
            )
            chain = [r.url for r in resp.history] + [resp.url]
            return ResolveResult(
                final_url=resp.url, status_code=resp.status_code,
                ok=resp.ok, redirect_chain=chain,
            )
        except requests.RequestException as e:
            return ResolveResult(final_url=None, status_code=None, ok=False,
                                 error=str(e))

    # -- public API ------------------------------------------------------- #
    def verify(self, url: str) -> VerifyResult:
        """Resolve + render a single URL, with caching (handles rarely change
        within one editing pass)."""
        if url in self._cache:
            return self._cache[url]
        result = self._verify_uncached(url)
        self._cache[url] = result
        return result

    def _verify_uncached(self, url: str) -> VerifyResult:
        raise NotImplementedError

    def _render_profile(self, url: str) -> VerifyResult:
        raise NotImplementedError

    def close(self):
        try:
            self._session.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
