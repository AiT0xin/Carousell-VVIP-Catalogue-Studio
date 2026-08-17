"""Visual preview: render PDF pages with QR bounding boxes, pairing lines,
and handle labels overlaid. Used by the Streamlit UI."""
from __future__ import annotations

from io import BytesIO

import numpy as np
import cv2
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

from .models import ExtractedRow, QRClass, BBox

# Colours (RGB)
_GREEN = (76, 175, 80)
_RED = (229, 57, 53)
_AMBER = (255, 160, 0)
_BLUE = (66, 165, 245)
_GREY = (158, 158, 158)

_SCALE = 2.0  # render scale for preview (balance quality vs speed)


def _color_for_row(row: ExtractedRow, verified: dict | None = None) -> tuple:
    if row.qr_class is QRClass.CTA:
        return _GREY
    if verified and row.decoded_url in verified:
        v = verified[row.decoded_url]
        if hasattr(v, "is_live_profile"):
            if not v.is_live_profile:
                return _RED
    if row.printed_handle and row.decoded_handle:
        if row.printed_handle != row.decoded_handle:
            return _AMBER
    if row.qr_class is QRClass.SHORTLINK:
        return _BLUE
    return _GREEN


def render_page_preview(
    pdf_path: str,
    page_no: int,
    rows: list[ExtractedRow],
    unpaired_handles=None,
    verified: dict | None = None,
    scale: float = _SCALE,
) -> Image.Image:
    """Render one page with overlaid annotations."""
    doc = pdfium.PdfDocument(pdf_path)
    page = doc[page_no - 1]
    bmp = page.render(scale=scale)
    img = bmp.to_pil().convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(14 * scale))
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(11 * scale))
    except Exception:
        font = ImageFont.load_default()
        font_sm = font

    page_rows = [r for r in rows if r.page == page_no]

    for r in page_rows:
        color = _color_for_row(r, verified)
        if r.qr_box:
            box = r.qr_box
            x0, y0 = int(box.x0 * scale), int(box.y0 * scale)
            x1, y1 = int(box.x1 * scale), int(box.y1 * scale)
            # Draw QR bounding box
            for i in range(3):
                draw.rectangle([x0 - i, y0 - i, x1 + i, y1 + i], outline=color)

            # Label
            if r.qr_class is QRClass.CTA:
                label = "CTA"
            elif r.decoded_handle:
                label = f"@{r.decoded_handle}"
            elif r.qr_class is QRClass.SHORTLINK:
                # Show resolved handle if available
                if verified and r.decoded_url in verified:
                    v = verified[r.decoded_url]
                    if hasattr(v, "resolves_to_handle") and v.resolves_to_handle:
                        label = f"→@{v.resolves_to_handle}"
                    else:
                        label = "shortlink"
                else:
                    label = "shortlink"
            else:
                label = "?"

            # Status badge
            status = ""
            if verified and r.decoded_url in verified:
                v = verified[r.decoded_url]
                if hasattr(v, "qr_status"):
                    status = f" [{v.qr_status}]"

            full_label = label + status
            # Background for label
            bbox_text = draw.textbbox((0, 0), full_label, font=font_sm)
            tw = bbox_text[2] - bbox_text[0]
            th = bbox_text[3] - bbox_text[1]
            lx, ly = x0, y0 - th - 6
            if ly < 0:
                ly = y1 + 4
            draw.rectangle([lx, ly, lx + tw + 8, ly + th + 4], fill=color)
            draw.text((lx + 4, ly + 1), full_label, fill="white", font=font_sm)

            # Mismatch indicator
            if r.printed_handle and r.decoded_handle and r.printed_handle != r.decoded_handle:
                warn = f"printed @{r.printed_handle} != QR @{r.decoded_handle}"
                bbox_w = draw.textbbox((0, 0), warn, font=font)
                ww = bbox_w[2] - bbox_w[0]
                wh = bbox_w[3] - bbox_w[1]
                wx = x0
                wy = y1 + 4
                draw.rectangle([wx, wy, wx + ww + 10, wy + wh + 6], fill=_AMBER)
                draw.text((wx + 5, wy + 2), warn, fill="white", font=font)

    # Unpaired handles
    if unpaired_handles:
        page_unpaired = [h for h in unpaired_handles if h.page == page_no]
        for h in page_unpaired:
            bx = h.box
            x0, y0 = int(bx.x0 * scale), int(bx.y0 * scale)
            x1, y1 = int(bx.x1 * scale), int(bx.y1 * scale)
            for i in range(2):
                draw.rectangle([x0 - i, y0 - i, x1 + i, y1 + i], outline=_RED)
            label = f"@{h.text} (no QR)"
            draw.text((x0, y1 + 2), label, fill=_RED, font=font_sm)

    return img


def render_all_pages(pdf_path: str, rows, unpaired_handles=None,
                     verified=None) -> list[Image.Image]:
    doc = pdfium.PdfDocument(pdf_path)
    pages = []
    for i in range(len(doc)):
        pages.append(render_page_preview(
            pdf_path, i + 1, rows, unpaired_handles, verified))
    return pages
