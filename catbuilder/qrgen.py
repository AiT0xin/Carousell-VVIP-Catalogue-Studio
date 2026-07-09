"""QR code generator.

Generates a QR code PNG for a Carousell profile URL.
Cached to <cache_dir>/qrcodes/<handle>.png.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import qrcode
import qrcode.constants
from PIL import Image

from .models import MerchantData


def generate_qr(
    merchant: MerchantData,
    cache_dir: Path,
    size_px: int = 300,
) -> Optional[Path]:
    """Generate and cache QR code PNG for the merchant's profile URL.

    Returns local path or None on failure.
    """
    cache_dir = Path(cache_dir)
    qr_dir = cache_dir / "qrcodes"
    qr_dir.mkdir(parents=True, exist_ok=True)
    out_path = qr_dir / f"{merchant.handle}.png"

    if out_path.exists():
        return out_path

    url = merchant.profile_url or f"https://www.carousell.sg/u/{merchant.handle}/"

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img: Image.Image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size_px, size_px), Image.LANCZOS)
    img.save(out_path, "PNG")
    return out_path
