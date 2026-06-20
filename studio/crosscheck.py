"""Feature 1 — VVIP cross-check.

For every merchant, answer two yes/no questions:
  • Are they in the catalogue?  (a card exists for their handle)
  • Are they a VVIP?            (their handle is in the master sheet)

and turn the answer into an action:
  in + vvip   → KEEP    (feature them, no change)
  in + !vvip  → REMOVE  (dropped from VVIP — pull from next edition)
  !in + vvip  → ADD     (missing VVIP — add to next edition)

Removals and additions are emitted as ProposedChange rows for the user to
approve before Feature 3 applies them.

Handle matching is fuzzy on purpose: the master sheet often stores *business
names* that get derived down to a stem ("revology") while the catalogue shows
the real handle ("revologybikes"). A prefix match (min 5 chars) bridges those so
we don't simultaneously propose "remove revologybikes" and "add revology".
"""
from __future__ import annotations

from .sources import extract_pdf, load_master, category_from_pdf_name, QRClass
from .state import (
    StudioSession,
    MerchantRecord,
    ProposedChange,
    CC_KEEP,
    CC_REMOVE,
    CC_ADD,
)

_MIN_FUZZY = 5   # minimum handle length for a prefix match to count


def _match_vvip(handle: str, master_handles: set[str]) -> tuple[bool, str]:
    """Return (is_vvip, matched_master_handle)."""
    if handle in master_handles:
        return True, handle
    # Longest master handles first so the most specific stem wins.
    for mh in sorted(master_handles, key=len, reverse=True):
        if len(mh) < _MIN_FUZZY or len(handle) < _MIN_FUZZY:
            continue
        if handle.startswith(mh) or mh.startswith(handle):
            return True, mh
    return False, ""


def _catalogue_handles(rows, unpaired) -> dict[str, dict]:
    """Collapse extract output into one entry per merchant card handle."""
    found: dict[str, dict] = {}

    for r in rows:
        # Only merchant / shortlink cards carry a handle; CTAs do not.
        if r.qr_class is QRClass.CTA:
            continue
        h = r.printed_handle
        if not h:
            continue
        entry = found.setdefault(h, {"page": r.page, "decoded_url": "",
                                     "decoded_handle": ""})
        if r.decoded_url and not entry["decoded_url"]:
            entry["decoded_url"] = r.decoded_url
            entry["decoded_handle"] = r.decoded_handle or ""

    # Printed handles with no QR at all — still in the catalogue.
    for h in unpaired:
        found.setdefault(h.text, {"page": h.page, "decoded_url": "",
                                  "decoded_handle": ""})

    return found


def run_crosscheck(session: StudioSession) -> StudioSession:
    """Populate session.merchants and emit add/remove proposals."""
    assert session.catalogue_path, "no catalogue loaded"

    # 1. Extract handles present in the catalogue
    rows, unpaired = extract_pdf(session.catalogue_path)
    cat_handles = _catalogue_handles(rows, unpaired)

    # 2. Load the VVIP master set
    if session.master_path:
        category = session.category or category_from_pdf_name(session.catalogue_path)
        master = load_master(session.master_path, category=category)
        session.category = category or session.category
    else:
        from .sources import MasterTable
        master = MasterTable()

    master_handles = set(master.handles)
    session.n_vvip_total = len(master_handles)

    # 3. Build merchant records for everything in the catalogue
    merchants: list[MerchantRecord] = []
    matched_master: set[str] = set()

    for h, info in sorted(cat_handles.items()):
        is_vvip, matched = _match_vvip(h, master_handles)
        if matched:
            matched_master.add(matched)
        rec = MerchantRecord(
            handle=h,
            display_name=master.name_of_handle.get(matched, "") if matched else "",
            page=info["page"],
            in_catalogue=True,
            is_vvip=is_vvip,
            matched_vvip=matched,
            decoded_url=info["decoded_url"],
            decoded_handle=info["decoded_handle"],
            cc_status=CC_KEEP if is_vvip else CC_REMOVE,
        )
        merchants.append(rec)

    # 4. Missing VVIPs — in the sheet, no card in the catalogue
    for mh in sorted(master_handles - matched_master):
        merchants.append(MerchantRecord(
            handle=mh,
            display_name=master.name_of_handle.get(mh, ""),
            in_catalogue=False,
            is_vvip=True,
            matched_vvip=mh,
            cc_status=CC_ADD,
        ))

    session.merchants = merchants

    # 5. Emit proposals (replace any prior cross-check proposals)
    session.clear_changes("crosscheck")
    for rec in merchants:
        if rec.cc_status == CC_REMOVE:
            session.set_change(ProposedChange(
                kind="remove", handle=rec.handle,
                display_name=rec.display_name or rec.handle,
                reason="In catalogue but no longer a VVIP",
                source="crosscheck",
            ))
        elif rec.cc_status == CC_ADD:
            session.set_change(ProposedChange(
                kind="add", handle=rec.handle,
                display_name=rec.display_name or rec.handle,
                reason="VVIP missing from the catalogue",
                source="crosscheck",
            ))

    session.crosscheck_done = True
    return session


# ── Summary helpers for the UI ──────────────────────────────────────────────
def crosscheck_summary(session: StudioSession) -> dict:
    m = session.merchants
    return {
        "in_catalogue": sum(1 for x in m if x.in_catalogue),
        "vvip_total": session.n_vvip_total,
        "keep":   sum(1 for x in m if x.cc_status == CC_KEEP),
        "remove": sum(1 for x in m if x.cc_status == CC_REMOVE),
        "add":    sum(1 for x in m if x.cc_status == CC_ADD),
    }
