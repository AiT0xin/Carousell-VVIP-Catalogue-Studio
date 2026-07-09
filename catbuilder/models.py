"""Data models for the catalogue builder."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MerchantData:
    """All data needed to render one merchant card."""
    handle: str                          # e.g. "motordez" (no @)
    display_name: str = ""               # e.g. "Motordez"
    category: str = ""                   # e.g. "Car Parts & Accessories"
    bio: str = ""                        # raw Carousell bio (may be empty)
    description: str = ""               # generated 40-50 word description
    avatar_path: Optional[Path] = None           # local path to downloaded avatar PNG
    qr_path: Optional[Path] = None              # local path to generated QR PNG
    listing_image_paths: list[Path] = None      # up to 4 listing thumbnails  # type: ignore[assignment]
    profile_url: str = ""                        # e.g. "https://www.carousell.sg/u/motordez/"

    def __post_init__(self) -> None:
        if self.listing_image_paths is None:
            self.listing_image_paths = []

    @property
    def at_handle(self) -> str:
        return f"@{self.handle}"

    def is_ready(self) -> bool:
        """True when all assets and description are ready for rendering."""
        return bool(
            self.display_name
            and self.description
            and self.avatar_path and self.avatar_path.exists()
            and self.qr_path and self.qr_path.exists()
        )


@dataclass
class CatalogueSection:
    """A named category section containing ordered merchants."""
    category: str
    merchants: list[MerchantData] = field(default_factory=list)

    # Category display colour (hex, used for header background and pill bg)
    # Defaults are set per well-known category names in layout.py
    colour: str = "#C62828"


@dataclass
class CatalogueJob:
    """Top-level job: sections → PDF."""
    title: str                              # e.g. "Autos"
    sections: list[CatalogueSection] = field(default_factory=list)
    output_path: Path = Path("catalogue.pdf")
    cache_dir: Path = Path("/tmp/catbuilder_cache")
    # Optional user-supplied cover art (full-page image). When None, no cover
    # page is rendered — there is no auto-generated branded cover.
    cover_path: Optional[Path] = None
    back_cover_path: Optional[Path] = None

    @property
    def all_merchants(self) -> list[MerchantData]:
        return [m for s in self.sections for m in s.merchants]


# ── Category colours ────────────────────────────────────────────────────────

CATEGORY_COLOURS: dict[str, str] = {
    # Autos
    "used cars":                 "#B71C1C",
    "car rental":                "#B71C1C",
    "car parts & accessories":   "#B71C1C",
    "motorcycles":               "#B71C1C",
    "others":                    "#B71C1C",
    # Goods
    "mobile phones & gadgets":   "#1565C0",
    "hobbies & toys":            "#2E7D32",
    "flowers & plants":          "#558B2F",
    "food & beverages":          "#E65100",
    "home & living":             "#4527A0",
    "fashion":                   "#AD1457",
    # Services
    "home services":             "#00695C",
    "beauty & wellness":         "#AD1457",
    "education":                 "#1565C0",
    "events":                    "#6A1B9A",
    # Luxury
    "jewellery":                 "#4A148C",
    "watches":                   "#1A237E",
    "bags & accessories":        "#880E4F",
}


def colour_for_category(cat: str) -> str:
    return CATEGORY_COLOURS.get(cat.lower().strip(), "#C62828")
