"""PDF renderer for the Carousell VVIP e-catalogue.

Faithfully matches the Autos sample catalogue:
  - Header: full-width photo/banner image (with embedded red diagonal + icon + text)
            OR fallback: drawn red diagonal polygon + white icon circle + white text
  - Cards: pure white, subtle drop shadow, no border
  - Page background: white
  - QR: white rounded-corner container with thin grey border

Layout (measured from real Autos PDFs):
  Spread: 1191 × 842 pt (double-A4 landscape)
  Half-page: 595.5 × 842 pt
  Header: 195 pt tall (full half-page width)
  Cards: 3 × 195 pt = 585 pt  (below header)
  Bottom margin: ~62 pt

  Header diagonal polygon (left-to-right, top-down coordinates):
    (0, 0) → (330, 0) → (240, 195) → (0, 195)
  Header icon (if no banner): white circle x=22, cy=78 from hdr_top, r=22
  Header text: x=70, y=72 from hdr_top, bold 17pt white

  Card internal (relative to card top, y increases downward):
    Avatar circle: x=14, cy=58, r=30  (60pt diameter, circle-cropped)
    Handle text:   x=90, y=44  (bold 11pt dark)
    Category pill: x=90, y=60  (rounded rect, 17pt tall, white 8pt text)
    Description:   x=14, y=96  w=425 (7.5pt grey, up to 6 lines)
    QR container:  x=448, y=20  106×106pt (white box, grey border, 6pt radius)
    QR image:      x=453, y=25  96×96pt (inside container)
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from .models import CatalogueJob, CatalogueSection, MerchantData, colour_for_category

# ── Page geometry ─────────────────────────────────────────────────────────────

PAGE_W   = 1191.0
PAGE_H   = 842.0
HALF_W   = PAGE_W / 2      # 595.5
HEADER_H = 195.0
CARD_H   = 195.0

# ── Fonts ─────────────────────────────────────────────────────────────────────

REG  = "Helvetica"
BOLD = "Helvetica-Bold"

# ── Colours ───────────────────────────────────────────────────────────────────

# Exact red sampled from original Autos catalogue header
HEADER_RED  = colors.HexColor("#911D21")
PILL_RED    = colors.HexColor("#911D21")   # same red for Autos; per-category in colour_for_category

_WHITE  = colors.white
_DARK   = colors.HexColor("#1A1A1A")       # near-black for handle text
_GREY   = colors.HexColor("#555555")       # description text
_SHADOW = colors.HexColor("#CCCCCC")       # card drop shadow
_QR_BG  = colors.white
_QR_BDR = colors.HexColor("#DDDDDD")       # QR container border

# ── Banner image lookup ───────────────────────────────────────────────────────

# Canonical category name → filename in <cache>/banners/
_BANNER_KEYS: dict[str, str] = {
    # Autos sub-categories
    "used cars":               "used_cars",
    "car rental":              "used_cars",
    "car parts & accessories": "car_parts_accessories",
    "car parts and accessories": "car_parts_accessories",
    "motorcycles":             "motorcycles",
    "others":                  "others",
    # Top-level sheet names → first banner for that catalogue
    "autos":                   "used_cars",
    "goods":                   "used_cars",    # placeholder until goods banners extracted
    "services":                "used_cars",
    "luxury":                  "used_cars",
}


def _banner_path(category: str, cache_dir: Path) -> Optional[Path]:
    key = category.lower().strip()
    fname = _BANNER_KEYS.get(key)
    if fname:
        p = cache_dir / "banners" / f"{fname}.png"
        if p.exists():
            return p
    # Also try direct filename match
    safe = re.sub(r"[^a-z0-9]+", "_", key).strip("_")
    p = cache_dir / "banners" / f"{safe}.png"
    return p if p.exists() else None


# ── Image helpers ──────────────────────────────────────────────────────────────

def _circle_crop_buf(img_path: Path, size: int = 200) -> io.BytesIO:
    """Circle-crop an image; return PNG bytes buffer."""
    try:
        img = Image.open(img_path).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        result = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        result.paste(img, mask=mask)
        final = Image.new("RGB", (size, size), (255, 255, 255))
        final.paste(result, mask=result.split()[3])
    except Exception:
        final = _placeholder_avatar_img(size)
    buf = io.BytesIO()
    final.save(buf, "PNG")
    buf.seek(0)
    return buf


def _placeholder_avatar_img(size: int = 200) -> Image.Image:
    img = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(200, 200, 200))
    return img


def _extract_brand_rgb(avatar_path: Optional[Path]) -> tuple[int, int, int]:
    """Return the dominant non-white, non-black RGB from the avatar."""
    if not avatar_path or not avatar_path.exists():
        return (180, 180, 180)
    try:
        img = Image.open(avatar_path).convert("RGB").resize((40, 40), Image.LANCZOS)
        pixels = list(img.getdata())
        filtered = [
            (r, g, b) for r, g, b in pixels
            if not (r > 210 and g > 210 and b > 210)   # skip near-white
            and not (r < 40 and g < 40 and b < 40)     # skip near-black
        ]
        if not filtered:
            return (180, 180, 180)
        r = sum(p[0] for p in filtered) // len(filtered)
        g = sum(p[1] for p in filtered) // len(filtered)
        b = sum(p[2] for p in filtered) // len(filtered)
        return (r, g, b)
    except Exception:
        return (180, 180, 180)


def _brand_bg_colour(avatar_path: Optional[Path]) -> colors.Color:
    """Very light tint (92% white, 8% brand colour) for card background."""
    r, g, b = _extract_brand_rgb(avatar_path)
    tint = 0.10
    br = int(r * tint + 255 * (1 - tint))
    bg = int(g * tint + 255 * (1 - tint))
    bb = int(b * tint + 255 * (1 - tint))
    return colors.Color(br / 255, bg / 255, bb / 255)


def _fit_crop_buf(img_path: Path, w: int, h: int) -> Optional[io.BytesIO]:
    """Crop-fill an image to exactly w×h; return PNG buffer or None on failure."""
    try:
        img = Image.open(img_path).convert("RGB")
        src_w, src_h = img.size
        scale = max(w / src_w, h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        img = img.crop((left, top, left + w, top + h))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return buf
    except Exception:
        return None


# ── Drawing helpers ────────────────────────────────────────────────────────────

def _draw_wrapped_text(
    c: rl_canvas.Canvas,
    text: str,
    x: float,
    y_top: float,   # top of block; text draws downward
    max_width: float,
    font_size: float,
    font_name: str = REG,
    line_height: float | None = None,
    max_lines: int = 6,
) -> None:
    if not text:
        return
    lh = line_height or font_size * 1.45
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if stringWidth(test, font_name, font_size) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    for i, line in enumerate(lines[:max_lines]):
        c.drawString(x, y_top - (i + 1) * lh, line)


# ── Header drawing ────────────────────────────────────────────────────────────

def _draw_header(
    c: rl_canvas.Canvas,
    ox: float,          # x-offset (0 = left half, HALF_W = right half)
    banner: Optional[Path],
    section: CatalogueSection,
) -> None:
    """Draw the category section header (195pt tall, full half-page wide)."""

    hdr_top    = PAGE_H - HEADER_H        # y of top of header (reportlab y-up)
    hdr_bottom = PAGE_H                   # y of very top of page = bottom of header area
    # In reportlab: y increases upward.  Header occupies y = [PAGE_H-HEADER_H, PAGE_H]

    if banner and banner.exists():
        # ── Use extracted banner image (already has diagonal + icon + text) ─────
        c.drawImage(
            str(banner),
            ox, PAGE_H - HEADER_H,
            width=HALF_W, height=HEADER_H,
            preserveAspectRatio=False,
        )
    else:
        # ── Fallback: draw red diagonal polygon + icon + text ───────────────────
        cat_colour = colors.HexColor(section.colour or "#911D21")

        # White background behind header first (in case of rounded page)
        c.setFillColor(_WHITE)
        c.rect(ox, PAGE_H - HEADER_H, HALF_W, HEADER_H, fill=1, stroke=0)

        # Dark red full background
        c.setFillColor(cat_colour)
        c.rect(ox, PAGE_H - HEADER_H, HALF_W, HEADER_H, fill=1, stroke=0)

        # Diagonal polygon: covers left ~55-65% of header with a slanted right edge
        # Top-down coordinates: (0,0)→(330,0)→(240,195)→(0,195)
        # In reportlab y-up: shift by (PAGE_H - HEADER_H) for y
        diag_pts = [
            (ox + 0,   PAGE_H - 0),
            (ox + 330, PAGE_H - 0),
            (ox + 240, PAGE_H - HEADER_H),
            (ox + 0,   PAGE_H - HEADER_H),
        ]
        path = c.beginPath()
        path.moveTo(*diag_pts[0])
        for pt in diag_pts[1:]:
            path.lineTo(*pt)
        path.close()
        c.setFillColor(colors.HexColor("#7A1518"))   # slightly darker diagonal
        c.drawPath(path, fill=1, stroke=0)

        # White circle icon placeholder
        icon_cx = ox + 28
        icon_cy = PAGE_H - HEADER_H + (HEADER_H - 78)   # 78pt from header top
        c.setFillColor(_WHITE)
        c.circle(icon_cx, icon_cy, 22, fill=1, stroke=0)

        # Initial letter inside circle
        initial = section.category[0].upper()
        c.setFont(BOLD, 16)
        c.setFillColor(cat_colour)
        iw = stringWidth(initial, BOLD, 16)
        c.drawString(icon_cx - iw / 2, icon_cy - 6, initial)

        # Category name
        c.setFont(BOLD, 17)
        c.setFillColor(_WHITE)
        c.drawString(ox + 62, PAGE_H - HEADER_H + (HEADER_H - 84), section.category)


# ── Card layout constants ──────────────────────────────────────────────────────
#
# Card: HALF_W × CARD_H  =  ~595 × 195 pt
# Columns:
#   Left content  : x = 0   … 440 pt  (identity + description + product images)
#   Right QR zone : x = 440 … 595 pt  (155 pt wide)
#
# Rows (from card top, downward):
#   Identity row  : 0  –  78 pt  (avatar + name + handle + pill)
#   Divider       : 78 –  82 pt
#   Product strip : 82 – 147 pt  (65 pt tall, 3 images side by side)
#   Description   : 150 – 183 pt (2-3 lines, 7.5 pt)

_CARD_MARGIN     = 5.0     # horizontal inset of card within half-page
_CARD_INNER_W    = HALF_W - _CARD_MARGIN * 2   # ≈585 pt

_QR_ZONE_W       = 130.0
_CONTENT_W       = _CARD_INNER_W - _QR_ZONE_W  # ≈455 pt

_AVATAR_CY_REL   = 42.0   # avatar centre, pt from card top
_AVATAR_R        = 28.0   # radius (56 pt diameter)
_AVATAR_X        = 12.0

_ID_X            = 76.0   # name/handle/pill left edge
_DISPNAME_Y_REL  = 22.0
_HANDLE_Y_REL    = 36.0
_PILL_Y_REL      = 50.0

_DIVIDER_Y_REL   = 78.0   # thin horizontal rule below identity row

_STRIP_Y_REL     = 82.0   # product strip top, pt from card top
_STRIP_H         = 65.0   # height of product thumbnails
_STRIP_GAP       = 3.0    # gap between thumbnail tiles

_DESC_Y_REL      = 152.0  # description top, pt from card top

_QR_BOX_W        = 112.0
_QR_BOX_H        = 112.0
_QR_PAD          = 5.0


def _draw_card(
    c: rl_canvas.Canvas,
    ox: float,
    card_top_y: float,
    merchant: MerchantData,
    pill_colour: str,
) -> None:
    """Draw one merchant card: brand-tinted background + product images + QR."""

    y_bottom = card_top_y - CARD_H
    card_x   = ox + _CARD_MARGIN

    # ── Brand-tinted card background ───────────────────────────────────────
    bg_colour = _brand_bg_colour(merchant.avatar_path)
    shadow_offset = 2.5
    c.setFillColor(_SHADOW)
    c.roundRect(
        card_x + shadow_offset, y_bottom - shadow_offset,
        _CARD_INNER_W, CARD_H - 4, 7, fill=1, stroke=0,
    )
    c.setFillColor(bg_colour)
    c.roundRect(card_x, y_bottom, _CARD_INNER_W, CARD_H - 4, 7, fill=1, stroke=0)

    # ── Avatar (circle-cropped) ────────────────────────────────────────────
    if merchant.avatar_path and merchant.avatar_path.exists():
        av_buf = _circle_crop_buf(merchant.avatar_path, 200)
    else:
        ph = _placeholder_avatar_img(200)
        av_buf = io.BytesIO()
        ph.save(av_buf, "PNG")
        av_buf.seek(0)

    av_diam = _AVATAR_R * 2
    av_y_bot = card_top_y - _AVATAR_CY_REL - _AVATAR_R
    c.drawImage(
        ImageReader(av_buf), card_x + _AVATAR_X, av_y_bot,
        width=av_diam, height=av_diam,
        preserveAspectRatio=True, mask="auto",
    )

    # ── Display name ───────────────────────────────────────────────────────
    disp = (merchant.display_name or merchant.handle.title())[:40]
    c.setFont(BOLD, 11)
    c.setFillColor(_DARK)
    c.drawString(card_x + _ID_X, card_top_y - _DISPNAME_Y_REL - 11, disp)

    # ── Handle ─────────────────────────────────────────────────────────────
    c.setFont(REG, 8.5)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawString(card_x + _ID_X, card_top_y - _HANDLE_Y_REL - 8.5, merchant.at_handle)

    # ── Category pill ──────────────────────────────────────────────────────
    pill_text = merchant.category[:32]
    pill_tw   = stringWidth(pill_text, REG, 7.5)
    pill_w    = pill_tw + 12
    pill_h    = 14
    pill_bx   = card_x + _ID_X
    pill_by   = card_top_y - _PILL_Y_REL - pill_h
    c.setFillColor(colors.HexColor(pill_colour))
    c.roundRect(pill_bx, pill_by, pill_w, pill_h, 4, fill=1, stroke=0)
    c.setFillColor(_WHITE)
    c.setFont(BOLD, 7.5)
    c.drawString(pill_bx + 6, pill_by + 3, pill_text)

    # ── Thin divider below identity row ────────────────────────────────────
    div_y = card_top_y - _DIVIDER_Y_REL
    r, g, b = _extract_brand_rgb(merchant.avatar_path)
    div_colour = colors.Color(r / 255 * 0.6 + 0.4, g / 255 * 0.6 + 0.4, b / 255 * 0.6 + 0.4)
    c.setStrokeColor(div_colour)
    c.setLineWidth(0.4)
    c.line(card_x + 10, div_y, card_x + _CONTENT_W - 10, div_y)

    # ── Product image strip ────────────────────────────────────────────────
    listing_paths = getattr(merchant, "listing_image_paths", None) or []
    valid_imgs = [p for p in listing_paths if Path(p).exists()][:3]

    strip_top_y = card_top_y - _STRIP_Y_REL
    strip_bot_y = strip_top_y - _STRIP_H
    n_imgs      = len(valid_imgs)

    if n_imgs > 0:
        tile_w = (_CONTENT_W - 12 - _STRIP_GAP * (n_imgs - 1)) / n_imgs
        tile_h = int(_STRIP_H)
        for idx, img_path in enumerate(valid_imgs):
            tx = card_x + 6 + idx * (tile_w + _STRIP_GAP)
            buf = _fit_crop_buf(img_path, int(tile_w), tile_h)
            if buf:
                c.saveState()
                p = c.beginPath()
                p.roundRect(tx, strip_bot_y, tile_w, _STRIP_H, 4)
                c.clipPath(p, stroke=0)
                c.drawImage(ImageReader(buf), tx, strip_bot_y,
                            width=tile_w, height=_STRIP_H)
                c.restoreState()
    else:
        # No product images — draw a subtle placeholder tint block
        c.setFillColor(colors.Color(r / 255 * 0.05 + 0.92,
                                    g / 255 * 0.05 + 0.92,
                                    b / 255 * 0.05 + 0.92))
        c.roundRect(card_x + 6, strip_bot_y, _CONTENT_W - 12, _STRIP_H, 4, fill=1, stroke=0)
        c.setFont(REG, 7)
        c.setFillColor(colors.HexColor("#AAAAAA"))
        c.drawString(card_x + _CONTENT_W / 2 - 30, strip_bot_y + _STRIP_H / 2 - 4, "no preview images")

    # ── Description text (2-3 compact lines) ──────────────────────────────
    c.setFont(REG, 7.5)
    c.setFillColor(_GREY)
    _draw_wrapped_text(
        c, merchant.description,
        card_x + 10, card_top_y - _DESC_Y_REL,
        _CONTENT_W - 14, 7.5,
        max_lines=3, line_height=11.0,
    )

    # ── QR zone (white pill on right side) ────────────────────────────────
    qr_zone_x = card_x + _CONTENT_W
    qr_bg_pad = 8
    qr_bg_x   = qr_zone_x + (_QR_ZONE_W - _QR_BOX_W) / 2 - qr_bg_pad / 2
    qr_bg_y   = y_bottom + (CARD_H - 4 - _QR_BOX_H - 22) / 2

    # White pill background behind QR
    c.setFillColor(_WHITE)
    c.setStrokeColor(_QR_BDR)
    c.setLineWidth(0.5)
    c.roundRect(qr_bg_x, qr_bg_y - 2, _QR_BOX_W + qr_bg_pad, _QR_BOX_H + 20, 6, fill=1, stroke=1)

    # QR image
    if merchant.qr_path and merchant.qr_path.exists():
        qr_inner = _QR_BOX_W - 2 * _QR_PAD
        c.drawImage(
            str(merchant.qr_path),
            qr_bg_x + _QR_PAD + qr_bg_pad / 2,
            qr_bg_y + 16,
            width=qr_inner, height=qr_inner,
        )

    # "Scan" label
    c.setFont(BOLD, 6.5)
    c.setFillColor(colors.HexColor("#999999"))
    lbl = "SCAN TO VISIT"
    lbl_w = stringWidth(lbl, BOLD, 6.5)
    c.drawString(qr_bg_x + (_QR_BOX_W + qr_bg_pad) / 2 - lbl_w / 2, qr_bg_y + 4, lbl)


# ── Page layout planner ────────────────────────────────────────────────────────

_CARDS_PER_HALF = 3   # hard cap: always exactly 3 merchant cards per column


def _plan_half_pages(job: CatalogueJob) -> list[dict]:
    """Return a list of half-page descriptors.

    Each descriptor:
        {
            "section":  CatalogueSection | None,   # present = draw header at top
            "cards":    [MerchantData | None] × 3, # always exactly 3 slots
            "cat_colour": str,
        }

    Rules:
    - Each section always starts on a fresh half-page (header at the top).
    - Continuation half-pages for the same section have no header; cards
      start from the very top of the column.
    - Every half-page has exactly _CARDS_PER_HALF card slots (some may be None).
    """
    half_pages: list[dict] = []

    for section in job.sections:
        cat_colour = section.colour or colour_for_category(section.category)
        merchants  = list(section.merchants)
        first      = True

        while merchants or first:
            batch     = merchants[:_CARDS_PER_HALF]
            merchants = merchants[_CARDS_PER_HALF:]
            # Pad to exactly 3 slots
            cards = batch + [None] * (_CARDS_PER_HALF - len(batch))
            half_pages.append({
                "section":    section if first else None,
                "cards":      cards,
                "cat_colour": cat_colour,
            })
            first = False
            if not merchants:
                break

    return half_pages


# ── Top-level render ──────────────────────────────────────────────────────────

def _draw_cover_page(c: rl_canvas.Canvas, image_path: Optional[Path], title: str, category: str) -> None:
    """Draw a full-spread cover (or back cover) page.

    If *image_path* exists, it is stretched to fill the page.
    Otherwise a branded Carousell-red page is drawn with the catalogue title.
    """
    _COVER_RED  = colors.HexColor("#EE3422")
    _COVER_DARK = colors.HexColor("#C4200F")

    if image_path and image_path.exists():
        buf = _fit_crop_buf(image_path, int(PAGE_W), int(PAGE_H))
        if buf:
            c.drawImage(ImageReader(buf), 0, 0, width=PAGE_W, height=PAGE_H,
                        preserveAspectRatio=False)
            return

    # ── Fallback: branded red page ────────────────────────────────────────────
    # Background gradient approximated with two rects
    c.setFillColor(_COVER_RED)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # Subtle dark diagonal accent (bottom-left corner)
    c.setFillColor(_COVER_DARK)
    p = c.beginPath()
    p.moveTo(0, 0); p.lineTo(480, 0); p.lineTo(0, 360); p.close()
    c.drawPath(p, fill=1, stroke=0)

    # "CAROUSELL" wordmark
    c.setFillColor(_WHITE)
    c.setFont(BOLD, 22)
    c.drawString(80, PAGE_H - 90, "CAROUSELL")

    # Thin underline below wordmark
    c.setStrokeColor(_WHITE)
    c.setLineWidth(1.5)
    c.line(80, PAGE_H - 100, 220, PAGE_H - 100)

    # Main title
    c.setFont(BOLD, 64)
    c.setFillColor(_WHITE)
    c.setFillColor(_WHITE)
    c.setFont(BOLD, 64)
    y = PAGE_H - 230
    for line in title.split("\n")[:3]:
        c.drawString(80, y, line)
        y -= 78

    # Category pill
    if category:
        pill_text = category.upper()
        pill_w = stringWidth(pill_text, BOLD, 14) + 28
        pill_x, pill_y = 80, PAGE_H - 310
        c.setFillColor(colors.HexColor("#FFFFFF33"))
        c.roundRect(pill_x, pill_y, pill_w, 26, 5, fill=1, stroke=0)
        c.setFillColor(_WHITE)
        c.setFont(BOLD, 14)
        c.drawString(pill_x + 14, pill_y + 7, pill_text)

    # Bottom tagline
    c.setFont(REG, 13)
    c.setFillColor(colors.HexColor("#FFFFFFAA"))
    c.drawString(80, 54, "carousell.sg  ·  VVIP Catalogue Studio")


def render_pdf(job: CatalogueJob) -> None:
    """Render the full catalogue PDF to job.output_path.

    A fixed cover page is prepended and a back cover appended.
    Place cover art at  <cache>/covers/cover.png  and
                        <cache>/covers/back_cover.png  to use custom images;
    otherwise a branded Carousell-red page is generated automatically.
    """
    cache_dir = Path(job.cache_dir)
    # Covers are user-supplied only. When a path is given the image is drawn as a
    # full-page cover; when None, that page is omitted entirely (no auto cover).
    cover_img = Path(job.cover_path) if job.cover_path else None
    back_cover_img = Path(job.back_cover_path) if job.back_cover_path else None

    half_pages = _plan_half_pages(job)

    # Pair into spreads (left + right)
    spreads = []
    for i in range(0, len(half_pages), 2):
        left  = half_pages[i]
        right = half_pages[i + 1] if i + 1 < len(half_pages) else None
        spreads.append((left, right))

    job.output_path.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(job.output_path), pagesize=(PAGE_W, PAGE_H))

    # ── Cover page (only if the user supplied one) ─────────────────────────────
    if cover_img and cover_img.exists():
        _draw_cover_page(c, cover_img, f"VVIP\n{job.title}\nCatalogue", job.title)
        c.showPage()

    # ── Content spreads ───────────────────────────────────────────────────────
    for left_hp, right_hp in spreads:
        # White page background
        c.setFillColor(_WHITE)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

        for half_idx, hp in enumerate((left_hp, right_hp)):
            if hp is None:
                continue
            ox = HALF_W * half_idx

            has_header = hp["section"] is not None

            # Draw header if this is the first half-page of a section
            if has_header:
                banner = _banner_path(hp["section"].category, Path(cache_dir))
                _draw_header(c, ox, banner, hp["section"])
                card_start_y = PAGE_H - HEADER_H
            else:
                card_start_y = PAGE_H   # cards start from the very top

            # Draw the 3 card slots
            for i, merchant in enumerate(hp["cards"]):
                if merchant is None:
                    continue
                card_top = card_start_y - i * CARD_H
                _draw_card(c, ox, card_top, merchant, hp["cat_colour"])

        c.showPage()

    # ── Back cover page (only if the user supplied one) ────────────────────────
    if back_cover_img and back_cover_img.exists():
        _draw_cover_page(c, back_cover_img, "Thank you", job.title)
        c.showPage()

    c.save()
    print(f"✅ Saved: {job.output_path}")
