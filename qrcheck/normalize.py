"""Handle / URL normalization shared by extraction, ingest, and verification.

Carousell-aware but written so other platforms can be added: the merchant-URL
parser lives here and is the single source of truth for "is this a profile link
and, if so, what's the handle?".
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

# Hosts whose /u/<handle> path is a real merchant profile.
PROFILE_HOSTS = {
    "carousell.sg", "www.carousell.sg",
    "carousell.com", "www.carousell.com",
    "carousell.com.my", "www.carousell.com.my",
    "carousell.ph", "www.carousell.ph",
}

# Hosts/paths that are calls-to-action, not merchant profiles.
CTA_HOST_HINTS = ("college.carousell.com", "wa.me", "api.whatsapp.com", "whatsapp.com")

# Carousell QR shortlinks. These hide their destination behind a redirect and
# must be resolved before we can tell merchant from CTA.
SHORTLINK_HOSTS = {"caro.sl", "www.caro.sl"}

# Canonical profile path: /u/<handle>.
_PROFILE_PATH_RE = re.compile(r"^/u/(?P<handle>[^/?#]+)/?$", re.IGNORECASE)
# Bare profile path some QRs use: carousell.com/<handle>. Exclude reserved
# first-segments that are site sections rather than usernames.
_BARE_PATH_RE = re.compile(r"^/(?P<handle>[^/?#]+)/?$", re.IGNORECASE)
_RESERVED_SEGMENTS = {
    "u", "p", "search", "categories", "category", "login", "signup", "help",
    "about", "careers", "blog", "support", "settings", "inbox", "notifications",
}


def normalize_handle(value: str | None) -> str:
    """Lowercase, strip a leading '@' and surrounding whitespace. Idempotent."""
    if not value:
        return ""
    return value.strip().lstrip("@").strip().lower()


def canonicalize_url(url: str | None) -> str:
    """Lowercase scheme/host, drop trailing slash and fragments, keep the path."""
    if not url:
        return ""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    host = p.netloc.lower()
    path = p.path.rstrip("/")
    return urlunparse((p.scheme.lower(), host, path, "", p.query, ""))


def is_cta_url(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    return any(hint in host or hint in url.lower() for hint in CTA_HOST_HINTS)


def is_shortlink(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    return host in SHORTLINK_HOSTS


def handle_from_profile_url(url: str | None) -> str | None:
    """Return the normalized handle if `url` is a merchant profile link, else None.

    >>> handle_from_profile_url("https://www.carousell.sg/u/motorydez/")
    'motorydez'
    >>> handle_from_profile_url("https://college.carousell.com/top-auto-merchants/")
    None
    """
    if not url:
        return None
    p = urlparse(url if "://" in url else "https://" + url)
    host = p.netloc.lower()
    if host not in PROFILE_HOSTS:
        return None
    m = _PROFILE_PATH_RE.match(p.path)
    if m:
        return normalize_handle(m.group("handle"))
    # Bare /<handle> form (carousell.com/thegamebrosg), excluding site sections.
    m = _BARE_PATH_RE.match(p.path)
    if m and m.group("handle").lower() not in _RESERVED_SEGMENTS:
        return normalize_handle(m.group("handle"))
    return None


def profile_url_for(handle: str, host: str = "www.carousell.sg") -> str:
    """Build the canonical profile URL for a (printed) handle so we can verify
    whether the printed slug itself resolves to a live profile."""
    return f"https://{host}/u/{normalize_handle(handle)}/"


def classify_url(url: str | None):
    """Return (QRClass, decoded_handle_or_None) for a *raw* decoded payload.

    Shortlinks resolve to SHORTLINK (destination unknown until we follow the
    redirect at verify time); known CTA hosts to CTA; profile links to MERCHANT.
    Anything else is treated as a shortlink-style unknown so it still gets paired
    and resolved rather than being silently dropped as CTA.
    """
    from .models import QRClass

    handle = handle_from_profile_url(url)
    if handle is not None:
        return QRClass.MERCHANT, handle
    if is_cta_url(url):
        return QRClass.CTA, None
    if is_shortlink(url):
        return QRClass.SHORTLINK, None
    return QRClass.SHORTLINK, None
