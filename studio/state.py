"""Shared data model for a Studio working session.

One `StudioSession` holds everything the three features read and write:

  - the loaded catalogue PDF + master VVIP sheet
  - one `MerchantRecord` per merchant (union of catalogue cards and sheet VVIPs)
  - a list of `ProposedChange` (add / remove / replace-QR) awaiting approval

Feature 1 (cross-check) fills in `in_catalogue` / `is_vvip` and proposes
add/remove. Feature 2 (QR check) fills in the QR fields and proposes replace-QR.
Feature 3 (generate) consumes the approved changes to build the corrected PDF.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Cross-check status ──────────────────────────────────────────────────────
CC_KEEP   = "keep"      # in catalogue AND vvip            → leave as-is
CC_REMOVE = "remove"    # in catalogue but NOT vvip        → drop from next edition
CC_ADD    = "add"       # vvip but NOT in catalogue        → add to next edition
CC_NA     = "n/a"       # neither (shouldn't be shown)

# ── QR status ───────────────────────────────────────────────────────────────
QR_OK       = "ok"          # decodes to printed handle, lands on live profile
QR_MISMATCH = "mismatch"    # QR's handle != printed handle on the card
QR_RENAMED  = "renamed"     # lands live but on a different handle than printed
QR_DEAD     = "dead"        # link does not resolve to a live page
QR_SOFT404  = "soft-404"    # page loads but is not the merchant's profile
QR_NONE     = "no-qr"       # printed handle with no QR found
QR_UNKNOWN  = "unknown"     # not yet checked

QR_BROKEN = {QR_MISMATCH, QR_RENAMED, QR_DEAD, QR_SOFT404, QR_NONE}


@dataclass
class MerchantRecord:
    """One merchant in the working set."""

    handle: str                       # normalized, no '@'
    display_name: str = ""
    page: Optional[int] = None        # page in the loaded catalogue (if present)

    # ── Feature 1: cross-check ──────────────────────────────────────────────
    in_catalogue: bool = False
    is_vvip: bool = False
    matched_vvip: str = ""            # which master handle it matched (fuzzy)
    cc_status: str = CC_NA

    # ── Feature 2: QR check ─────────────────────────────────────────────────
    decoded_url: str = ""
    decoded_handle: str = ""
    resolves_to: str = ""            # handle the QR actually lands on
    qr_live: Optional[bool] = None
    qr_status: str = QR_UNKNOWN
    qr_detail: str = ""

    @property
    def at(self) -> str:
        return f"@{self.handle}"

    @property
    def qr_ok(self) -> bool:
        return self.qr_status == QR_OK

    @property
    def qr_broken(self) -> bool:
        return self.qr_status in QR_BROKEN


@dataclass
class ProposedChange:
    """A single suggested edit to the catalogue, pending user approval."""

    kind: str            # "add" | "remove" | "replace_qr"
    handle: str
    display_name: str = ""
    reason: str = ""
    source: str = ""     # "crosscheck" | "qrcheck"
    approved: bool = True

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.handle}"


@dataclass
class StudioSession:
    """The full working state for one catalogue."""

    catalogue_path: Optional[str] = None
    master_path: Optional[str] = None
    category: str = ""

    merchants: list[MerchantRecord] = field(default_factory=list)
    changes: list[ProposedChange] = field(default_factory=list)

    # how many master VVIP handles were loaded (for the cross-check summary)
    n_vvip_total: int = 0

    # progress flags so the UI can gate features
    crosscheck_done: bool = False
    qrcheck_done: bool = False
    generate_done: bool = False
    # persisted result of the last generation so the success panel + download
    # survive the rerun that refreshes the sidebar status
    generate_result: Optional[dict] = None

    # Shared with catbuilder so fetched profiles/avatars/QRs are reused.
    # Use ~/.cache (user-private) instead of world-readable /tmp
    cache_dir: Path = Path.home() / ".cache" / "catbuilder"
    output_path: Optional[str] = None

    # ── lookups ─────────────────────────────────────────────────────────────
    def by_handle(self, handle: str) -> Optional[MerchantRecord]:
        for m in self.merchants:
            if m.handle == handle:
                return m
        return None

    def in_catalogue(self) -> list[MerchantRecord]:
        return [m for m in self.merchants if m.in_catalogue]

    def changes_of(self, kind: str) -> list[ProposedChange]:
        return [c for c in self.changes if c.kind == kind]

    def approved_changes(self, kind: str) -> list[ProposedChange]:
        return [c for c in self.changes if c.kind == kind and c.approved]

    def set_change(self, change: ProposedChange) -> None:
        """Add or replace a change by its key (idempotent)."""
        for i, c in enumerate(self.changes):
            if c.key == change.key:
                # preserve the user's approval choice on refresh
                change.approved = c.approved
                self.changes[i] = change
                return
        self.changes.append(change)

    def clear_changes(self, source: str) -> None:
        self.changes = [c for c in self.changes if c.source != source]
