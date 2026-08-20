"""Shared data structures passed between pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ReasonCode(str, Enum):
    """Per-row outcome. PASS / CTA_OK are non-flags; the rest are flags."""

    PASS = "PASS"
    CTA_OK = "CTA_OK"
    DECODE_FAIL = "DECODE_FAIL"
    DEAD_LINK = "DEAD_LINK"
    RENAMED_HANDLE = "RENAMED_HANDLE"
    HANDLE_TYPO = "HANDLE_TYPO"
    MISMATCH = "MISMATCH"
    NOT_IN_MASTER = "NOT_IN_MASTER"
    MISSING_FROM_SHEET = "MISSING_FROM_SHEET"
    UNPAIRED_QR = "UNPAIRED_QR"          # QR decoded but no nearby printed handle
    UNPAIRED_HANDLE = "UNPAIRED_HANDLE"  # printed handle with no QR

    @property
    def is_flag(self) -> bool:
        return self not in (ReasonCode.PASS, ReasonCode.CTA_OK)


class QRClass(str, Enum):
    MERCHANT = "merchant"     # carousell.sg/u/<handle> profile link (direct)
    SHORTLINK = "shortlink"   # caro.sl/... — destination unknown until resolved
    CTA = "cta"               # category / WhatsApp / info redirect, not a profile


@dataclass
class BBox:
    """Bounding box in PDF points, top-left origin (matches pdfplumber)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class DecodedQR:
    """A QR code found on a page, with where it points and where it sits."""

    page: int                       # 1-based
    data: str                       # raw decoded payload (a URL, for these PDFs)
    box: BBox
    decoders: set = field(default_factory=set)  # e.g. {"zbar@3.0", "cv@4.0"}
    qr_class: QRClass = QRClass.MERCHANT
    decoded_handle: Optional[str] = None  # handle parsed from the URL path


@dataclass
class PrintedHandle:
    """An @handle string extracted from the page text, with position."""

    page: int
    text: str           # normalized handle, no leading '@'
    raw: str            # exactly as printed, e.g. "@acmemotors"
    box: BBox


@dataclass
class ExtractedRow:
    """One QR paired (or not) with one printed handle, before verification."""

    page: int
    printed_handle: Optional[str]   # normalized, no '@'
    decoded_url: Optional[str]
    decoded_handle: Optional[str]   # from the QR URL
    qr_class: QRClass
    decoders: set = field(default_factory=set)
    qr_box: Optional[BBox] = None


@dataclass
class VerifyResult:
    """Outcome of resolving + rendering a decoded URL."""

    final_url: Optional[str] = None
    resolves_to_handle: Optional[str] = None  # username at the live destination
    is_live_profile: bool = False
    verified_badge: Optional[bool] = None
    qr_status: str = ""             # human label: "live", "dead", "blank-shell"...
    detail: str = ""
    screenshot_path: Optional[str] = None


@dataclass
class ReportRow:
    """Final, flattened row written to the XLSX report."""

    page: int
    printed_handle: str = ""
    decoded_url: str = ""
    resolves_to: str = ""
    qr_status: str = ""
    match_status: str = ""
    in_master: str = ""
    reason_code: ReasonCode = ReasonCode.PASS
    detail: str = ""
    screenshot_path: str = ""

    @property
    def is_flag(self) -> bool:
        return self.reason_code.is_flag
