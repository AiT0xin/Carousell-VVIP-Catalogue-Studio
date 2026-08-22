"""Stage 1 - ingest & normalize the master document into a tidy handle table.

Designed for the real VVIP master, which is multi-sheet (Goods / Services /
Luxury / Autos), has a 3-row banner before the data, and is mixed-content (some
cells hold business names instead of handles, others have multiple handles
slash-separated). The loader is forgiving by design: it scans every cell from
the data region and harvests anything that looks like a Carousell handle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from .normalize import normalize_handle, handle_from_profile_url

# A token that looks like a Carousell handle: lowercase letters/digits with
# optional dots/underscores, 3+ chars. Excludes things like "Pte Ltd" or pure
# numbers. Conservative to keep business names out.
_HANDLE_TOKEN_RE = re.compile(r"\b@?([a-z0-9][a-z0-9_.]{2,})\b")

# Things that look like handle tokens but are not (corporate suffixes, banner
# junk, column headers from the VVIP master sheet).
_BLOCKLIST = {
    "pte", "ltd", "llp", "inc", "corp", "co", "sg", "the", "and",
    "as", "of", "may", "june", "july", "to", "in", "is", "for",
    "vvip", "lt1", "lt2", "ac", "notes", "nan",
}
# Whole-cell blocklist: banner cells, column headers, etc. Checked after
# lowering and stripping whitespace.
_ROW_BLOCKLIST_PATS = [
    re.compile(r"sg\s*vvip\s*merchants", re.I),
    re.compile(r"empty\s*space\s*to\s*paste", re.I),
    re.compile(r"merchants?\s*as\s*of", re.I),
    re.compile(r"^as\s+of\s+\d", re.I),
    re.compile(r"lt[12]\s*-\s*(vvip|in)", re.I),
    re.compile(r"^\d{4}(/\d{4})+$"),   # year spans like "2023/2024/2025"
]

# Catalogue stem -> sheet name in the master xlsx, used to pick the right sheet
# automatically from the PDF filename.
CATEGORY_KEYWORDS = {
    "autos": "Autos",
    "auto": "Autos",
    "goods": "Goods",
    "luxury": "Luxury",
    "services": "Services",
    "service": "Services",
}


@dataclass
class MasterTable:
    """Set of expected handles plus best-effort display-name lookup."""

    handles: set[str] = field(default_factory=set)
    name_of_handle: dict[str, str] = field(default_factory=dict)
    source: str = ""
    category: str = ""

    def __len__(self):
        return len(self.handles)


def _looks_like_handle(token: str) -> bool:
    if not token or len(token) < 3:
        return False
    if token in _BLOCKLIST:
        return False
    if token.isdigit():
        return False
    if not any(c.isalpha() for c in token):
        return False
    # Carousell handles only contain [a-z0-9._-]; reject anything with &, spaces, etc.
    if not re.fullmatch(r"[a-z0-9._-]+", token):
        return False
    # Reject if it looks like a banner fragment (too long with no separators)
    if len(token) > 35:
        return False
    return True


_BIZ_SUFFIX_RE = re.compile(
    r"\s*\b(pte\.?\s*ltd\.?|inc\.?|llp|corp|sdn\s*bhd|private\s+limited)\b.*$",
    re.I,
)
_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*")
_DESCRIPTOR_RE = re.compile(
    r"\s*\b(motorcycle\s+shop|auto\s+trading\s*&?\s*services?|"
    r"bikes?|tyres?|financial|mechanic|motors?)\b\s*",
    re.I,
)


def _biz_name_to_handle(text: str) -> str | None:
    """Try to derive a Carousell handle from a business name.

    Strip "Pte Ltd", parenthesised account numbers, and common descriptors,
    collapse whitespace, lowercase. If the remainder looks like a single handle
    token, return it.
    """
    s = _BIZ_SUFFIX_RE.sub("", text).strip()
    s = _PARENS_RE.sub("", s).strip()
    s = _DESCRIPTOR_RE.sub(" ", s).strip()
    # Collapse remaining whitespace - if none left, the name was all descriptor.
    s = re.sub(r"\s+", "", s).lower()
    if not s or len(s) < 3:
        return None
    if _looks_like_handle(s):
        return s
    return None


def _harvest_handles(cell: object) -> list[str]:
    """Pull handle-shaped tokens out of a cell.

    Handles three shapes:
      1. A clean handle or profile URL (no spaces): "acmetints", "acmemotors"
      2. Slash-separated multi-handle: "acmecarshades /Acmecarparts.com"
      3. A business name: "ACME MOTORWORKS PTE LTD" → strip corporate suffixes
         and descriptors, yielding "acmemotorworks"
    """
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    text = str(cell).strip()
    if not text:
        return []
    # Skip banner / header cells
    if any(p.search(text) for p in _ROW_BLOCKLIST_PATS):
        return []
    url_handle = handle_from_profile_url(text)
    if url_handle:
        return [url_handle]

    parts = re.split(r"[\s]*[/,]+[\s]*", text)
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # If no internal whitespace, try as a raw handle token.
        if not any(c.isspace() for c in part):
            m = _HANDLE_TOKEN_RE.fullmatch(part.lower())
            if m and _looks_like_handle(m.group(1)):
                out.append(m.group(1))
                continue
        # Otherwise treat as a business name and try to derive a handle.
        derived = _biz_name_to_handle(part)
        if derived:
            out.append(derived)
    return out


def _pick_sheet(xl: pd.ExcelFile, category: Optional[str]) -> Optional[str]:
    if not category:
        return None
    cat = category.lower()
    for name in xl.sheet_names:
        if cat in name.lower():
            return name
    return None


def category_from_pdf_name(pdf_path: str) -> Optional[str]:
    stem = Path(pdf_path).stem.lower()
    for kw, sheet in CATEGORY_KEYWORDS.items():
        if kw in stem:
            return sheet
    return None


def load_master(path: str, category: Optional[str] = None) -> MasterTable:
    """Load the master document, optionally restricted to one category sheet.

    If `category` matches a sheet name (case-insensitive substring), only that
    sheet's handles are returned. Otherwise every sheet is unioned.
    """
    p = Path(path)
    mt = MasterTable(source=str(p), category=category or "")

    if p.suffix.lower() in (".csv", ".tsv"):
        df = pd.read_csv(p, header=None)
        _harvest_dataframe(df, mt)
        return mt

    xl = pd.ExcelFile(p)
    if category:
        sheet = _pick_sheet(xl, category)
        sheets = [sheet] if sheet else []
    else:
        sheets = xl.sheet_names

    for sheet in sheets:
        df = pd.read_excel(xl, sheet_name=sheet, header=None)
        _harvest_dataframe(df, mt, sheet_name=sheet)
    return mt


def _harvest_dataframe(df: pd.DataFrame, mt: MasterTable, sheet_name: str = ""):
    """Walk every cell from row 3 onward (skipping the 3-row banner) and union
    discovered handles into the master."""
    # Locate where the data actually starts: first row whose any cell yields a
    # handle. Cap the search at row 6 so we don't scan whole sheets.
    start_row = 3
    for ri in range(min(8, len(df))):
        row = df.iloc[ri].tolist()
        if any(_harvest_handles(c) for c in row):
            start_row = ri
            break

    for ri in range(start_row, len(df)):
        row = df.iloc[ri].tolist()
        # Use the first non-empty cell as a candidate display name (business
        # name lives in one cell, handles in the next), but only if it isn't
        # itself a handle.
        display_name = ""
        for c in row:
            if c is None or (isinstance(c, float) and pd.isna(c)):
                continue
            txt = str(c).strip()
            if not txt:
                continue
            if not _harvest_handles(c):
                display_name = txt
            break

        for c in row:
            for h in _harvest_handles(c):
                mt.handles.add(h)
                # First name we encounter wins
                mt.name_of_handle.setdefault(h, display_name or h)
