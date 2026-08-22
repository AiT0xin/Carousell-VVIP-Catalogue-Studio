"""Stage 2 - extract QR codes and printed handles from a catalogue PDF and pair
each QR with its handle.

Design notes (validated against the real Carousell VVIP catalogues):
  * pypdfium2 renders pages; 1 PDF point == `scale` pixels, top-left origin.
  * pdfplumber word boxes share that coordinate space, so QR boxes (converted
    from pixels by dividing by scale) and handle boxes are directly comparable.
  * Decoding is a *union* across several render scales and two decoders
    (pyzbar primary, OpenCV fallback). Single-pass decoding misses codes - this
    union is the single biggest reliability lever.
  * Pairing: for each QR, restrict candidate handles to the same page column
    (same side of the page midline - required for 2-up landscape spreads), then
    pick the handle whose vertical center is nearest the QR's. Measured against
    the samples, this pairs every QR correctly.
"""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import cv2
import pypdfium2 as pdfium

# Silence OpenCV's per-QR "ECI is not supported" stderr spam during decode.
try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    pass
import pdfplumber
from pyzbar.pyzbar import decode as zbar_decode
from pyzbar.pyzbar import ZBarSymbol

from .models import BBox, DecodedQR, PrintedHandle, ExtractedRow, QRClass
from .normalize import normalize_handle, classify_url

# Render scales fed to the decoders. Low scales catch large codes cheaply; high
# scales recover small/dense ones. The union of all passes is what we keep.
DEFAULT_SCALES = (2.0, 3.0, 4.0, 6.0)

# A printed handle token: '@' followed by Carousell-legal username chars.
HANDLE_RE = re.compile(r"@[A-Za-z0-9_.]{2,}")

# Max vertical gap (points) between a QR center and a handle top for them to be
# considered the same card. Row pitch in the samples is ~195pt; a card is well
# under that. 140 leaves margin without bleeding into the neighbouring row.
MAX_PAIR_DY = 140.0


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #
def _zbar_decode(img_rgb: np.ndarray, scale: float) -> list[tuple[str, BBox]]:
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    out = []
    for sym in zbar_decode(gray, symbols=[ZBarSymbol.QRCODE]):
        data = sym.data.decode("utf-8", "replace")
        r = sym.rect
        box = BBox(r.left / scale, r.top / scale,
                   (r.left + r.width) / scale, (r.top + r.height) / scale)
        out.append((data, box, f"zbar@{scale}"))
    return out


def _opencv_decode(img_rgb: np.ndarray, scale: float) -> list[tuple[str, BBox]]:
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    det = cv2.QRCodeDetector()
    out = []
    ok, infos, points, _ = det.detectAndDecodeMulti(bgr)
    if ok and infos is not None and points is not None:
        for data, pts in zip(infos, points):
            if not data:
                continue
            xs, ys = pts[:, 0], pts[:, 1]
            box = BBox(float(xs.min()) / scale, float(ys.min()) / scale,
                       float(xs.max()) / scale, float(ys.max()) / scale)
            out.append((data, box, f"cv@{scale}"))
    return out


def _render(page, scale: float) -> np.ndarray:
    bmp = page.render(scale=scale)
    return np.array(bmp.to_pil().convert("RGB"))


def decode_page_qrs(page, scales: Iterable[float] = DEFAULT_SCALES,
                    page_no: int = 0) -> list[DecodedQR]:
    """Union-decode one pypdfium page across scales + decoders.

    Codes are deduped by payload; the first box seen wins (positions agree
    across scales to sub-point precision) and decoder provenance is accumulated.
    """
    by_data: dict[str, DecodedQR] = {}
    for scale in scales:
        img = _render(page, scale)
        for data, box, src in (*_zbar_decode(img, scale), *_opencv_decode(img, scale)):
            qr = by_data.get(data)
            if qr is None:
                qr_class, handle = classify_url(data)
                qr = DecodedQR(page=page_no, data=data, box=box,
                               qr_class=qr_class, decoded_handle=handle)
                by_data[data] = qr
            qr.decoders.add(src)
    return list(by_data.values())


# --------------------------------------------------------------------------- #
# Handle text extraction
# --------------------------------------------------------------------------- #
def extract_page_handles(pl_page, page_no: int = 0) -> list[PrintedHandle]:
    """Find @handle tokens with their bounding boxes via pdfplumber words."""
    handles: list[PrintedHandle] = []
    words = pl_page.extract_words(use_text_flow=False, keep_blank_chars=False)
    for w in words:
        for m in HANDLE_RE.finditer(w["text"]):
            raw = m.group(0)
            handles.append(PrintedHandle(
                page=page_no,
                text=normalize_handle(raw),
                raw=raw,
                box=BBox(w["x0"], w["top"], w["x1"], w["bottom"]),
            ))
    return handles


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #
def _same_column(qr: DecodedQR, h: PrintedHandle, midline: float) -> bool:
    qr_left = qr.box.cx < midline
    h_left = h.box.x0 < midline
    return qr_left == h_left


def pair_qrs_to_handles(qrs: list[DecodedQR], handles: list[PrintedHandle],
                        page_width: float):
    """Return (rows, unpaired_handles).

    Pairing is purely *geometric* and covers every QR - merchant, shortlink, and
    CTA alike - because at extract time a caro.sl shortlink looks like a CTA but
    is usually a merchant card's QR. We pair first, classify after resolution.
    Candidate QR/handle pairs are sorted by vertical distance within the same
    column and consumed best-first, so each handle backs at most one QR.
    Dedicated CTA-page links sit on handle-free pages, so they stay unpaired and
    surface as printed_handle=None rows.
    """
    midline = page_width / 2

    candidates = []
    for qi, qr in enumerate(qrs):
        for hi, h in enumerate(handles):
            if not _same_column(qr, h, midline):
                continue
            dy = abs(qr.box.cy - h.box.cy)
            if dy <= MAX_PAIR_DY:
                candidates.append((dy, qi, hi))
    candidates.sort(key=lambda c: c[0])

    used_q: set[int] = set()
    used_h: set[int] = set()
    pair_of_q: dict[int, int] = {}
    for dy, qi, hi in candidates:
        if qi in used_q or hi in used_h:
            continue
        used_q.add(qi)
        used_h.add(hi)
        pair_of_q[qi] = hi

    rows: list[ExtractedRow] = []
    for qi, qr in enumerate(qrs):
        hi = pair_of_q.get(qi)
        printed = handles[hi].text if hi is not None else None
        rows.append(ExtractedRow(
            page=qr.page, printed_handle=printed, decoded_url=qr.data,
            decoded_handle=qr.decoded_handle, qr_class=qr.qr_class,
            decoders=qr.decoders, qr_box=qr.box,
        ))

    # A handle is only genuinely "missing a QR" if it appears nowhere among the
    # paired rows on its page. Handles printed twice (header + card) leave a
    # leftover occurrence that must not be reported as a missing QR.
    paired_on_page = {(r.page, r.printed_handle) for r in rows if r.printed_handle}
    seen: set[tuple[int, str]] = set()
    unpaired_handles = []
    for hi, h in enumerate(handles):
        if hi in used_h:
            continue
        key = (h.page, h.text)
        if key in paired_on_page or key in seen:
            continue
        seen.add(key)
        unpaired_handles.append(h)
    return rows, unpaired_handles


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #
def extract_pdf(pdf_path: str, scales: Iterable[float] = DEFAULT_SCALES):
    """Extract and pair across a whole catalogue.

    Returns (rows, unpaired_handles) where rows is one ExtractedRow per QR
    (merchant or CTA) and unpaired_handles lists printed handles with no QR.
    """
    doc = pdfium.PdfDocument(pdf_path)
    all_rows: list[ExtractedRow] = []
    all_unpaired: list[PrintedHandle] = []
    with pdfplumber.open(pdf_path) as pl:
        for i in range(len(doc)):
            page = doc[i]
            page_no = i + 1
            width = page.get_size()[0]
            qrs = decode_page_qrs(page, scales=scales, page_no=page_no)
            handles = extract_page_handles(pl.pages[i], page_no=page_no)
            rows, unpaired = pair_qrs_to_handles(qrs, handles, width)
            all_rows.extend(rows)
            all_unpaired.extend(unpaired)
    return all_rows, all_unpaired
