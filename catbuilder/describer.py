"""Claude API description generator.

For each merchant:
  1. Read profile data (bio, listing titles) from the fetch cache.
  2. If the profile is sparse (short/no bio, no listing titles), search the web
     for the business by name to gather richer context.
  3. Pass everything to Claude to write a punchy 40-50 word VVIP description.

Results cached to <cache_dir>/descriptions/<handle>.txt.
Delete that file to force a fresh generation.
"""
from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import anthropic
import httpx

from .models import MerchantData

_CLIENT: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic()
    return _CLIENT


_SYSTEM = """\
You write concise, punchy 40-50 word business descriptions for merchants on the \
Carousell VVIP e-catalogue. The tone is confident and professional but approachable. \
Always mention what the business sells or does, and end with something that makes \
the reader want to visit the profile. Never use phrases like "Look no further", \
"One-stop shop", or "your go-to". Output ONLY the description text — no quotes, \
no prefix, no trailing newline."""


# ── Sparseness check ─────────────────────────────────────────────────────────

def _is_sparse(bio: str, listing_titles: list[str]) -> bool:
    """True when the Carousell profile doesn't give us enough to write from."""
    useful_bio = len(bio.strip()) >= 30
    has_listings = len(listing_titles) >= 2
    return not useful_bio and not has_listings


# ── Web search fallback ───────────────────────────────────────────────────────

class _SnippetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in = False
        self._buf: list[str] = []
        self.snippets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        cls = dict(attrs).get("class", "")
        if "result__snippet" in cls or "result__body" in cls:
            self._in = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if self._in:
            self._in = False
            text = "".join(self._buf).strip()
            if text:
                self.snippets.append(text)

    def handle_data(self, data: str) -> None:
        if self._in:
            self._buf.append(data)


def _web_search(query: str) -> str:
    """Return up to 3 DuckDuckGo result snippets as a single string."""
    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=12,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return ""
        parser = _SnippetParser()
        parser.feed(resp.text)
        snippets = parser.snippets[:3]
        return " | ".join(snippets)
    except Exception:
        return ""


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    merchant: MerchantData,
    listing_titles: list[str],
    web_context: str,
) -> str:
    lines = [
        f"Handle: @{merchant.handle}",
        f"Display name: {merchant.display_name or merchant.handle}",
        f"Category: {merchant.category or 'General'}",
        f"Profile URL: {merchant.profile_url}",
    ]
    if merchant.bio:
        lines.append(f"Carousell bio: {merchant.bio[:500]}")
    if listing_titles:
        lines.append("Listings on their profile:")
        for t in listing_titles[:6]:
            lines.append(f"  - {t}")
    if web_context:
        lines.append(f"\nAdditional context from the web:\n{web_context[:800]}")
    lines.append(
        "\nWrite a 40-50 word Carousell VVIP catalogue description for this merchant. "
        "Draw on all the context above — what they actually sell, their speciality, "
        "and anything that makes them stand out. Be specific; avoid generic phrases."
    )
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_description(
    merchant: MerchantData,
    cache_dir: Path,
    model: str = "claude-haiku-4-5",
) -> str:
    """Generate and cache a 40-50 word description.

    Reads listing titles from the profile JSON cache (written by fetcher.py).
    If the profile is sparse, searches the web for richer context before
    calling Claude.
    """
    cache_dir = Path(cache_dir)
    desc_dir = cache_dir / "descriptions"
    desc_dir.mkdir(parents=True, exist_ok=True)
    cache_file = desc_dir / f"{merchant.handle}.txt"

    if cache_file.exists():
        return cache_file.read_text().strip()

    # Pull listing titles from the profile JSON cache
    profile_cache = cache_dir / "profiles" / f"{merchant.handle}.json"
    listing_titles: list[str] = []
    if profile_cache.exists():
        try:
            data = json.loads(profile_cache.read_text())
            listing_titles = data.get("listing_titles") or []
        except Exception:
            pass

    # Web search if the Carousell profile alone is too sparse
    web_context = ""
    if _is_sparse(merchant.bio, listing_titles):
        name = merchant.display_name or merchant.handle
        query = f"{name} Singapore {merchant.category or ''}".strip()
        web_context = _web_search(query)

    client = _get_client()
    prompt = _build_prompt(merchant, listing_titles, web_context)
    msg = client.messages.create(
        model=model,
        max_tokens=200,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    description = msg.content[0].text.strip()
    cache_file.write_text(description)
    return description
