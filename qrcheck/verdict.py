"""Stage 3 decision logic: combine extraction + verification + master into a
single per-QR ReportRow with a reason_code.

The tricky calls and how we make them:

  HANDLE_TYPO vs MISMATCH — both mean "QR username != printed handle". They
    differ in *why*:
      * HANDLE_TYPO: the printed slug is itself dead, and the QR lands on a live
        near-spelling of it. The QR is right; the printed text is the typo.
      * MISMATCH: the printed slug is a live (different) merchant, or the QR
        target is unrelated. The QR points somewhere it shouldn't.
    We can only tell these apart by *also* verifying the printed handle's own
    profile — hence the orchestrator verifies both URLs and passes both here.

  DEAD_LINK vs RENAMED_HANDLE — both 200-ish but not a usable profile:
      * DEAD_LINK: nothing renders / 404 / bounce.
      * RENAMED_HANDLE: a profile *shell* renders but it's an empty placeholder
        (0 listings, not verified) — the classic renamed-and-orphaned slug.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from .models import ExtractedRow, VerifyResult, ReportRow, ReasonCode, QRClass
from .normalize import normalize_handle

# Above this string similarity, a printed-vs-QR difference reads as a typo
# rather than a wholly different merchant.
TYPO_SIMILARITY = 0.72


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def decide(row: ExtractedRow,
           qr_result: Optional[VerifyResult],
           printed_result: Optional[VerifyResult],
           master_handles: set[str]) -> ReportRow:
    """master_handles: set of normalized expected handles from the master."""
    printed = normalize_handle(row.printed_handle) if row.printed_handle else ""
    rr = ReportRow(
        page=row.page,
        printed_handle=("@" + printed) if printed else "",
        decoded_url=row.decoded_url or "",
    )

    # --- DECODE_FAIL: a handle was printed but no QR decoded for it -------- #
    if not row.decoded_url:
        rr.reason_code = ReasonCode.DECODE_FAIL
        rr.qr_status = "no-decode"
        rr.match_status = "—"
        rr.in_master = _in_master(printed, master_handles)
        return rr

    dest = qr_result.resolves_to_handle if qr_result else None
    rr.final_url = getattr(qr_result, "final_url", "") or ""
    rr.resolves_to = ("@" + dest) if dest else (qr_result.final_url if qr_result else "")
    rr.qr_status = qr_result.qr_status if qr_result else ""
    rr.detail = qr_result.detail if qr_result else ""
    rr.screenshot_path = (qr_result.screenshot_path or "") if qr_result else ""

    # --- CTA links: informational, not a merchant profile ----------------- #
    if row.qr_class is QRClass.CTA or (dest is None and not _is_profileish(qr_result)):
        # A shortlink that resolved to a non-profile (category/WhatsApp) is CTA.
        if row.qr_class is QRClass.CTA or (qr_result and not qr_result.is_live_profile
                                           and dest is None and qr_result.qr_status not in ("dead", "blank-shell", "blank", "error")):
            rr.reason_code = ReasonCode.CTA_OK
            rr.match_status = "n/a (CTA)"
            rr.in_master = "—"
            return rr

    # --- QR did not render a live profile --------------------------------- #
    if not qr_result or not qr_result.is_live_profile:
        status = qr_result.qr_status if qr_result else "error"
        if status == "blank-shell":
            rr.reason_code = ReasonCode.RENAMED_HANDLE
        else:  # dead / blank / error / bounced
            rr.reason_code = ReasonCode.DEAD_LINK
        rr.match_status = "no live profile"
        rr.in_master = _in_master(printed, master_handles)
        return rr

    # --- QR rendered a LIVE profile: compare usernames -------------------- #
    rr.in_master = _in_master(dest or printed, master_handles)
    if dest and printed and dest == printed:
        rr.match_status = "match"
        rr.reason_code = (ReasonCode.PASS if _in_master(printed, master_handles) == "Yes"
                          or not master_handles else ReasonCode.NOT_IN_MASTER)
        if rr.reason_code is ReasonCode.NOT_IN_MASTER:
            rr.match_status = "match (not in master)"
        return rr

    # destination != printed handle
    rr.match_status = f"printed @{printed} -> qr @{dest}"
    printed_live = bool(printed_result and printed_result.is_live_profile)
    if not printed_live and _similar(printed, dest or "") >= TYPO_SIMILARITY:
        # printed slug is dead, QR lands on a live near-spelling -> typo
        rr.reason_code = ReasonCode.HANDLE_TYPO
        rr.detail = (rr.detail + " | printed slug not live, near-spelling of QR").strip(" |")
    else:
        rr.reason_code = ReasonCode.MISMATCH
        if printed_live:
            rr.detail = (rr.detail + " | printed handle is a different live store").strip(" |")
    return rr


def _in_master(handle: str, master_handles: set[str]) -> str:
    if not master_handles:
        return "—"
    if not handle:
        return "No"
    return "Yes" if normalize_handle(handle) in master_handles else "No"


def _is_profileish(res: Optional[VerifyResult]) -> bool:
    return bool(res and (res.is_live_profile or res.resolves_to_handle
                         or res.qr_status in ("blank-shell", "dead")))
