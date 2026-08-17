"""AI description generator (provider-agnostic, OpenAI-compatible).

For each merchant:
  1. Read profile data (bio, listing titles) from the fetch cache.
  2. If the profile is sparse (short/no bio, no listing titles), search the web
     for the business by name to gather richer context.
  3. Pass everything to an LLM to write a punchy 40-50 word VVIP description.

Works with ANY OpenAI-compatible endpoint — pick whichever is cheapest/free:

  • Ollama Cloud (free tier):
        AI_BASE_URL=https://ollama.com/v1
        AI_API_KEY=<your ollama key>          (from ollama.com settings)
        AI_MODEL=gpt-oss:120b
  • Local Ollama (free, offline — `ollama serve`):
        AI_BASE_URL=http://localhost:11434/v1
        AI_MODEL=llama3.2                       (no key needed)
  • Google Gemini (free tier):
        AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
        AI_API_KEY=<your gemini key>            (aistudio.google.com/app/apikey)
        AI_MODEL=gemini-1.5-flash

Results cached to <cache_dir>/descriptions/<handle>.txt.
Delete that file to force a fresh generation.
"""
from __future__ import annotations

import json
import os
from html.parser import HTMLParser
from pathlib import Path

import httpx

from .models import MerchantData

# Default to local Ollama so the app works offline with no key once a model is
# pulled. Override any of these via env vars to use a cloud provider.
_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_MODEL = "llama3.2"

_CLIENT = None


def ai_configured() -> bool:
    """True only when the user has explicitly configured an AI provider — a
    cloud key (AI_API_KEY), or an explicit local base URL they opted into. With
    nothing set, descriptions stay off and cards use the generic fallback."""
    if os.environ.get("AI_API_KEY"):
        return True
    base = os.environ.get("AI_BASE_URL", "")
    return bool(base and ("localhost" in base or "127.0.0.1" in base))


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI
        base_url = os.environ.get("AI_BASE_URL", _DEFAULT_BASE_URL)
        # Local Ollama ignores the key but the client still requires a non-empty
        # string, so fall back to a placeholder for keyless local endpoints.
        api_key = os.environ.get("AI_API_KEY") or "local"
        _CLIENT = OpenAI(base_url=base_url, api_key=api_key)
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
    model: str | None = None,
) -> str:
    """Generate and cache a 40-50 word description.

    Reads listing titles from the profile JSON cache (written by fetcher.py).
    If the profile is sparse, searches the web for richer context before
    calling the configured LLM.
    """
    model = model or os.environ.get("AI_MODEL", _DEFAULT_MODEL)
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
    # Generous ceiling: reasoning models (e.g. nemotron) spend most of their
    # budget "thinking" and only then emit the answer, so a low cap returns an
    # empty string. Non-reasoning models just stop early — no extra cost.
    resp = client.chat.completions.create(
        model=model,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    description = (resp.choices[0].message.content or "").strip()
    if description:
        cache_file.write_text(description)
    return description
