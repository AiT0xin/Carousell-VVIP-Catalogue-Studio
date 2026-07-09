"""Command-line entrypoint: PDF in -> decode + pair -> resolve + render -> XLSX.

This replicates the manual editing session end-to-end (milestone M1), and adds
the master coverage diff (M2) when a master is supplied.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extract import extract_pdf, DEFAULT_SCALES
from .models import ExtractedRow, ReportRow, ReasonCode, QRClass
from .normalize import normalize_handle, profile_url_for
from .verdict import decide
from .coverage import coverage_rows
from .report import write_report
from .ingest import load_master, MasterTable, category_from_pdf_name


def _verify_rows(rows, verifier, log):
    """Two-phase verification, minimizing network hits.

    Phase 1: verify every decoded URL (QR destination).
    Phase 2: only for rows whose QR rendered a live profile but whose username
             differs from the printed handle, verify the printed handle's own
             profile (needed to tell HANDLE_TYPO from MISMATCH).
    Returns (qr_results_by_url, printed_results_by_handle).
    """
    qr_results: dict[str, object] = {}
    # Pure-CTA links are marked CTA_OK without a render; only resolve profile
    # and shortlink destinations.
    urls = [r.decoded_url for r in rows
            if r.decoded_url and r.qr_class is not QRClass.CTA]
    uniq = list(dict.fromkeys(urls))
    log(f"  resolving + rendering {len(uniq)} unique QR destinations...")
    for i, url in enumerate(uniq, 1):
        qr_results[url] = verifier.verify(url)
        log(f"    [{i}/{len(uniq)}] {url} -> {qr_results[url].qr_status} "
            f"(@{qr_results[url].resolves_to_handle or '?'})")

    printed_results: dict[str, object] = {}
    to_check = set()
    for r in rows:
        if not r.printed_handle or not r.decoded_url:
            continue
        qres = qr_results.get(r.decoded_url)
        if qres and qres.is_live_profile:
            dest = qres.resolves_to_handle
            if dest and normalize_handle(r.printed_handle) != dest:
                to_check.add(normalize_handle(r.printed_handle))
    if to_check:
        log(f"  verifying {len(to_check)} printed handles (mismatch triage)...")
    for h in sorted(to_check):
        printed_results[h] = verifier.verify(profile_url_for(h))
        log(f"    printed @{h} -> {printed_results[h].qr_status}")
    return qr_results, printed_results


def run(pdf_path: str, out_path: str, master_path: str | None = None,
        verify: bool = True, screenshot_dir: str | None = None,
        platform: str = "carousell", scales=DEFAULT_SCALES, log=print) -> dict:
    log(f"[1/4] Extracting QR codes + handles from {Path(pdf_path).name} ...")
    rows, unpaired = extract_pdf(pdf_path, scales=scales)
    n_merch = sum(1 for r in rows if r.qr_class is not QRClass.CTA)
    log(f"      {len(rows)} QRs ({n_merch} merchant/shortlink, "
        f"{len(rows)-n_merch} CTA), {len(unpaired)} handles with no QR")

    if master_path:
        category = category_from_pdf_name(pdf_path)
        master = load_master(master_path, category=category)
        log(f"[2/4] Loaded master ({category or 'all sheets'}): "
            f"{len(master)} handles from {Path(master_path).name}")
    else:
        master = MasterTable()

    qr_results, printed_results = {}, {}
    if verify:
        from .verify import get_verifier
        from .verify.base import VerifierConfig
        cfg = VerifierConfig(screenshot_dir=screenshot_dir)
        log("[3/4] Verifying live profiles (Playwright headless Chromium)...")
        with get_verifier(platform, config=cfg) as verifier:
            qr_results, printed_results = _verify_rows(rows, verifier, log)
    else:
        log("[3/4] --no-verify: skipping live profile checks")

    # Build report rows
    report_rows: list[ReportRow] = []
    for r in rows:
        qres = qr_results.get(r.decoded_url) if r.decoded_url else None
        pres = (printed_results.get(normalize_handle(r.printed_handle))
                if r.printed_handle else None)
        if not verify:
            report_rows.append(_offline_row(r, master.handles))
        else:
            report_rows.append(decide(r, qres, pres, master.handles))

    # handles printed with no QR at all
    for h in unpaired:
        report_rows.append(ReportRow(
            page=h.page, printed_handle=h.raw, qr_status="no-qr",
            match_status="printed handle, no QR found",
            in_master=("Yes" if h.text in master.handles else ("No" if master.handles else "—")),
            reason_code=ReasonCode.UNPAIRED_HANDLE,
            detail="a handle is printed but no QR was paired to it",
        ))

    # coverage diff (sheet = handles seen in the catalogue)
    if master.handles:
        seen = {normalize_handle(r.printed_handle) for r in rows if r.printed_handle}
        seen |= {r.decoded_handle for r in rows if r.decoded_handle}
        report_rows.extend(coverage_rows(seen, master))

    log(f"[4/4] Writing report -> {out_path}")
    summary = write_report(report_rows, out_path)
    log(f"      {summary['total']} rows, {summary['flagged']} flagged for review")
    for code, n in sorted(summary["counts"].items(), key=lambda kv: kv[0].value):
        marker = "  ⚑" if code.is_flag else "   "
        log(f"      {marker} {code.value:20} {n}")
    return summary


def _offline_row(r: ExtractedRow, master_handles) -> ReportRow:
    """Report row when --no-verify: pairing/decoding only, no liveness."""
    printed = normalize_handle(r.printed_handle) if r.printed_handle else ""
    rr = ReportRow(page=r.page,
                   printed_handle=("@" + printed) if printed else "",
                   decoded_url=r.decoded_url or "")
    if r.qr_class is QRClass.CTA:
        rr.reason_code = ReasonCode.CTA_OK
        rr.match_status = "n/a (CTA)"
        rr.in_master = "—"
        return rr
    dh = r.decoded_handle or ""
    rr.resolves_to = ("@" + dh) if dh else (r.decoded_url or "")
    rr.qr_status = "decoded (not verified)"
    if r.qr_class is QRClass.SHORTLINK:
        rr.match_status = "shortlink — resolve to compare"
        rr.reason_code = ReasonCode.PASS
    elif printed and dh:
        if printed == dh:
            rr.match_status = "printed == QR"
            rr.reason_code = ReasonCode.PASS
        else:
            rr.match_status = f"printed @{printed} != QR @{dh}"
            rr.reason_code = ReasonCode.MISMATCH
    rr.in_master = ("Yes" if (dh or printed) in master_handles
                    else ("No" if master_handles else "—"))
    return rr


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="qrcheck",
        description="Verify catalogue QR codes resolve to the correct live merchant profiles.")
    ap.add_argument("pdf", help="catalogue PDF to check")
    ap.add_argument("-o", "--out", default=None, help="output XLSX path")
    ap.add_argument("-m", "--master", default=None,
                    help="master document (CSV/XLSX) of expected merchants")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip live profile checks (decode + pair only)")
    ap.add_argument("--screenshots", default=None,
                    help="directory to save evidence screenshots for flagged rows")
    ap.add_argument("--platform", default="carousell")
    args = ap.parse_args(argv)

    pdf = args.pdf
    out = args.out or str(Path(pdf).with_suffix("")) + "_qrcheck.xlsx"
    summary = run(pdf, out, master_path=args.master, verify=not args.no_verify,
                  screenshot_dir=args.screenshots, platform=args.platform)
    return 0 if summary is not None else 1


if __name__ == "__main__":
    sys.exit(main())
