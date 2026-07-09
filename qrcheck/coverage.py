"""Stage 3a — coverage: set-diff the handles present in the catalogue/sheet
against the master document.

Produces extra ReportRows for handles that are out of coverage:
  * NOT_IN_MASTER      — in the catalogue/sheet but absent from the master
  * MISSING_FROM_SHEET — in the master but never seen in the catalogue/sheet
These are independent of QR integrity (a QR can pass while its merchant is still
missing from the master).
"""
from __future__ import annotations

from typing import Iterable

from .models import ReportRow, ReasonCode
from .ingest import MasterTable


def coverage_rows(sheet_handles: Iterable[str],
                  master: MasterTable) -> list[ReportRow]:
    sheet = {h for h in sheet_handles if h}
    rows: list[ReportRow] = []

    if not master.handles:
        return rows  # no master supplied -> coverage check skipped

    for h in sorted(sheet - master.handles):
        rows.append(ReportRow(
            page=0, printed_handle="@" + h,
            match_status="in sheet, not in master", in_master="No",
            reason_code=ReasonCode.NOT_IN_MASTER,
            detail="coverage: present in catalogue/sheet, absent from master",
        ))

    for h in sorted(master.handles - sheet):
        rows.append(ReportRow(
            page=0, printed_handle="@" + h,
            match_status="in master, not in sheet", in_master="Yes",
            reason_code=ReasonCode.MISSING_FROM_SHEET,
            detail=f"coverage: master lists '{master.name_of_handle.get(h, h)}', "
                   "not found in catalogue/sheet",
        ))
    return rows
