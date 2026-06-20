"""Feature 3 — generate the corrected catalogue.

Takes the loaded catalogue's merchant set, applies the *approved* changes from
Features 1 & 2, and renders the next edition:

    final = (in-catalogue VVIPs)  −  approved removals  +  approved additions

Every card is rebuilt fresh — profile re-fetched, description regenerated, and a
new QR minted from the canonical profile URL — so any broken QR flagged in
Feature 2 is corrected by construction. Profiles that no longer resolve are
skipped and reported rather than printed as dead cards.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import json

from .sources import (
    MerchantData,
    CatalogueSection,
    CatalogueJob,
    colour_for_category,
    fetch_and_cache,
    download_listing_images,
    generate_description,
    generate_qr,
    render_pdf,
    profile_url_for,
)
from .state import StudioSession


def build_final_handles(session: StudioSession) -> list[str]:
    """The merchant handles that belong in the corrected catalogue."""
    removed = {c.handle for c in session.approved_changes("remove")}
    added = [c.handle for c in session.approved_changes("add")]

    final: list[str] = []
    seen: set[str] = set()
    for m in session.in_catalogue():
        if m.handle in removed or m.handle in seen:
            continue
        seen.add(m.handle)
        final.append(m.handle)
    for h in added:
        if h in seen:
            continue
        seen.add(h)
        final.append(h)
    return final


def _fallback_description(m: MerchantData) -> str:
    """Build a description from scraped profile data — no AI needed."""
    import json
    from pathlib import Path as _P

    name = m.display_name or m.handle
    bio = (m.bio or "").strip()
    listing_titles: list[str] = []

    # Try to load listing titles from profile cache
    cache_file = _P(m.profile_url.replace("https://www.carousell.sg/u/", "").rstrip("/")) if m.profile_url else None
    profile_json = _P(f"/tmp/catbuilder_cache/profiles/{m.handle}.json")
    if profile_json.exists():
        try:
            data = json.loads(profile_json.read_text())
            listing_titles = data.get("listing_titles") or []
            if not bio:
                bio = data.get("bio") or ""
        except Exception:
            pass

    parts: list[str] = []

    # Use bio if it's meaningful
    if len(bio) >= 30:
        # Trim to ~120 chars for the description
        bio_snippet = bio[:150].rsplit(" ", 1)[0] if len(bio) > 150 else bio
        parts.append(bio_snippet.rstrip(".") + ".")

    # Add listing context
    if listing_titles:
        titles = listing_titles[:3]
        if len(titles) == 1:
            parts.append(f"Specialising in {titles[0].lower()}.")
        else:
            joined = ", ".join(t.lower() for t in titles[:-1]) + f" and {titles[-1].lower()}"
            parts.append(f"Offerings include {joined}.")

    # Fallback if nothing scraped
    if not parts:
        cat = m.category or "products and services"
        parts.append(f"{name} is a VVIP merchant on Carousell specialising in {cat}.")

    # Add CTA
    parts.append(f"Scan to explore @{m.handle} on Carousell.")

    description = " ".join(parts)
    # Trim to ~200 chars
    if len(description) > 220:
        description = description[:220].rsplit(" ", 1)[0].rstrip(".") + "."
    return description


def generate(
    session: StudioSession,
    do_describe: bool = True,
    model: str = "claude-haiku-4-5",
    progress_cb: Optional[Callable[[int, int, str, str], None]] = None,
) -> dict:
    """Build and render the corrected catalogue. Returns a result summary."""
    cache_dir = session.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    handles = build_final_handles(session)
    category = session.category or "Autos"

    merchants: list[MerchantData] = []
    skipped: list[str] = []

    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    for i, h in enumerate(handles):
        m = MerchantData(handle=h, category=category, profile_url=profile_url_for(h))

        # Re-fetch profile (display name + avatar). Empty display_name == dead.
        fetch_and_cache(m, cache_dir)
        if not m.display_name:
            skipped.append(h)
            if progress_cb:
                progress_cb(i + 1, len(handles), h, "skipped (profile not found)")
            continue

        avatar = cache_dir / "avatars" / f"{h}.png"
        if avatar.exists():
            m.avatar_path = avatar

        # Download listing product thumbnails (URLs stored in profile cache JSON)
        profile_cache = cache_dir / "profiles" / f"{h}.json"
        if profile_cache.exists():
            try:
                img_urls = json.loads(profile_cache.read_text()).get("listing_image_urls") or []
                if img_urls:
                    m.listing_image_paths = download_listing_images(h, img_urls, cache_dir)
            except Exception:
                pass

        if do_describe and have_key:
            try:
                m.description = generate_description(m, cache_dir, model=model)
            except Exception:
                m.description = _fallback_description(m)
        else:
            m.description = _fallback_description(m)

        # Always mint a fresh QR from the canonical profile URL — this is what
        # fixes every broken QR flagged in Feature 2.
        m.qr_path = generate_qr(m, cache_dir)
        merchants.append(m)
        if progress_cb:
            progress_cb(i + 1, len(handles), h, m.display_name)

    section = CatalogueSection(
        category=category,
        merchants=merchants,
        colour=colour_for_category(category),
    )

    if session.output_path:
        out = session.output_path
    elif session.catalogue_path:
        stem = Path(session.catalogue_path).stem
        out = str(Path.home() / "Desktop" / f"{stem}_corrected.pdf")
    else:
        out = str(Path.home() / "Desktop" / "catalogue_corrected.pdf")

    job = CatalogueJob(
        title=category,
        sections=[section],
        output_path=Path(out),
        cache_dir=cache_dir,
    )
    render_pdf(job)
    session.output_path = out

    return {
        "output": out,
        "built": len(merchants),
        "skipped": skipped,
        "requested": len(handles),
    }


def generate_plan(session: StudioSession) -> dict:
    """A dry-run summary of what Generate will do, for the confirm screen."""
    final = build_final_handles(session)
    return {
        "final_count": len(final),
        "kept":    len([m for m in session.in_catalogue()
                        if m.handle in final and m.is_vvip]),
        "added":   len(session.approved_changes("add")),
        "removed": len(session.approved_changes("remove")),
        "qr_fixes": len(session.approved_changes("replace_qr")),
        "final_handles": final,
    }
