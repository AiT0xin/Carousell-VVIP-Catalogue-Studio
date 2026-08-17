"""CLI entry point: catbuild

Usage:
  catbuild --master XLSX --category AUTOS --out catalogue.pdf
  catbuild --handles motordez revologybikes --category "Autos" --cat-label "Car Parts & Accessories" --out test.pdf
  catbuild --handles motordez --no-fetch --no-describe --out test.pdf   # offline test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import CatalogueJob, CatalogueSection, MerchantData, colour_for_category
from .fetcher import fetch_and_cache
from .describer import generate_description
from .qrgen import generate_qr
from .pdf_render import render_pdf


CACHE_DIR = Path("/tmp/catbuilder_cache")


def _load_from_master(master_path: Path, category: str | None) -> list[CatalogueSection]:
    """Load merchant handles from the master XLSX using qrcheck's parser.

    The master XLSX has a complex format (mixed business names + handles,
    slash-separated multi-handle cells, corporate suffixes, etc.).
    We reuse the qrcheck ingest module which was built specifically for it.
    """
    # Add qrcheck to path so we can import its parser
    qrcheck_dir = Path.home() / "qr-catalogue-checker"
    if str(qrcheck_dir) not in sys.path:
        sys.path.insert(0, str(qrcheck_dir))

    try:
        from qrcheck.ingest import load_master
    except ImportError:
        print("Warning: Could not import qrcheck parser. Falling back to simple parser.")
        return _load_from_master_simple(master_path, category)

    # qrcheck's load_master reads one sheet at a time by category keyword
    # Sheet names in the XLSX are: Goods, Services, Luxury, Autos
    SHEET_CATEGORIES: dict[str, str] = {
        "Autos":    "Autos",
        "Goods":    "Goods",
        "Services": "Services",
        "Luxury":   "Luxury",
    }

    # Determine which sheets to load
    if category:
        # Find the matching sheet name (case-insensitive)
        sheet_map = {k.lower(): k for k in SHEET_CATEGORIES}
        sheet_name = sheet_map.get(category.lower(), category)
        sheets_to_load = [(sheet_name, sheet_name)]
    else:
        sheets_to_load = [(k, v) for k, v in SHEET_CATEGORIES.items()]

    sections: list[CatalogueSection] = []
    seen_handles: set[str] = set()

    for cat_label, sheet_key in sheets_to_load:
        mt = load_master(str(master_path), category=sheet_key)
        if not mt.handles:
            continue

        merchants: list[MerchantData] = []
        for handle in sorted(mt.handles):
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            display_name = mt.name_of_handle.get(handle, "")
            url = f"https://www.carousell.sg/u/{handle}/"
            m = MerchantData(
                handle=handle,
                display_name=display_name,
                category=cat_label,
                profile_url=url,
            )
            merchants.append(m)

        if merchants:
            sections.append(CatalogueSection(
                category=cat_label,
                merchants=merchants,
                colour=colour_for_category(cat_label),
            ))

    return sections


def _load_from_master_simple(master_path: Path, category: str | None) -> list[CatalogueSection]:
    """Simple fallback parser (less accurate, used if qrcheck is unavailable)."""
    import re, openpyxl
    wb = openpyxl.load_workbook(master_path, data_only=True)
    sections: list[CatalogueSection] = []
    sheets = [wb[category]] if category and category in wb.sheetnames else wb.worksheets
    for ws in sheets:
        cat_name = ws.title
        if category and cat_name.lower() != category.lower():
            continue
        merchants: list[MerchantData] = []
        for row in ws.iter_rows(min_row=4, values_only=True):
            for cell in row:
                if not cell:
                    continue
                val = str(cell).strip().lstrip("@").lower()
                if re.match(r'^[a-z][a-z0-9._\-]{2,34}$', val):
                    merchants.append(MerchantData(
                        handle=val, category=cat_name,
                        profile_url=f"https://www.carousell.sg/u/{val}/",
                    ))
        if merchants:
            sections.append(CatalogueSection(
                category=cat_name, merchants=merchants,
                colour=colour_for_category(cat_name),
            ))
    return sections


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="catbuild",
        description="Build a Carousell VVIP e-catalogue PDF",
    )
    parser.add_argument("--master", help="Path to VVIP E-Catalogue Merchant Filter.xlsx")
    parser.add_argument("--category", help="Category/sheet name filter (e.g. Autos)")
    parser.add_argument("--handles", nargs="+", help="Explicit list of handles (no @)")
    parser.add_argument("--cat-label", default="", help="Category label when using --handles")
    parser.add_argument("--out", default="catalogue.pdf", help="Output PDF path")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR), help="Cache directory")
    parser.add_argument("--no-fetch", action="store_true", help="Skip Playwright profile fetching")
    parser.add_argument("--no-describe", action="store_true", help="Skip Claude API description generation")
    parser.add_argument("--model", default="claude-haiku-4-5", help="Claude model for descriptions")
    args = parser.parse_args(argv)

    cache_dir = Path(args.cache_dir)

    # ── Build sections ──────────────────────────────────────────────────────
    if args.handles:
        cat = args.cat_label or args.category or "General"
        merchants = [
            MerchantData(
                handle=h.lstrip("@"),
                category=cat,
                profile_url=f"https://www.carousell.sg/u/{h.lstrip('@')}/",
            )
            for h in args.handles
        ]
        sections = [CatalogueSection(
            category=cat,
            merchants=merchants,
            colour=colour_for_category(cat),
        )]
    elif args.master:
        sections = _load_from_master(Path(args.master), args.category)
    else:
        parser.error("Provide --master or --handles")
        return

    job = CatalogueJob(
        title=args.category or "VVIP Catalogue",
        sections=sections,
        output_path=Path(args.out),
        cache_dir=cache_dir,
    )

    all_merchants = job.all_merchants
    print(f"[catbuild] {len(all_merchants)} merchants across {len(sections)} categories")

    # ── Stage 1: Fetch profiles ──────────────────────────────────────────────
    if not args.no_fetch:
        print("[1/3] Fetching Carousell profiles...")
        for i, m in enumerate(all_merchants, 1):
            print(f"  [{i}/{len(all_merchants)}] @{m.handle}", end=" ", flush=True)
            fetch_and_cache(m, cache_dir)
            print(f"→ {m.display_name or '(no name)'}")
    else:
        # Load from cache if available
        for m in all_merchants:
            cache_file = cache_dir / "profiles" / f"{m.handle}.json"
            if cache_file.exists():
                data = json.loads(cache_file.read_text())
                m.display_name = data.get("display_name") or m.handle.title()
                m.bio = data.get("bio") or ""
                m.profile_url = data.get("profile_url") or m.profile_url
            else:
                m.display_name = m.display_name or m.handle.replace(".", " ").replace("_", " ").title()

    # Wire avatar paths (downloaded during fetch)
    for m in all_merchants:
        avatar_path = cache_dir / "avatars" / f"{m.handle}.png"
        if avatar_path.exists():
            m.avatar_path = avatar_path

    # ── Stage 2: Generate descriptions ──────────────────────────────────────
    if not args.no_describe:
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "\nWarning: ANTHROPIC_API_KEY is not set.\n"
                "   Add it to your shell profile, then re-run:\n"
                "     echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc\n"
                "     source ~/.zshrc\n"
                "   Or skip description generation for now:\n"
                "     catbuild ... --no-describe\n"
            )
            sys.exit(1)

        print("[2/3] Generating descriptions with Claude...")
        for i, m in enumerate(all_merchants, 1):
            print(f"  [{i}/{len(all_merchants)}] @{m.handle}", end=" ", flush=True)
            m.description = generate_description(m, cache_dir, model=args.model)
            word_count = len(m.description.split())
            print(f"({word_count} words)")
    else:
        for m in all_merchants:
            cache_file = cache_dir / "descriptions" / f"{m.handle}.txt"
            if cache_file.exists():
                m.description = cache_file.read_text().strip()
            else:
                m.description = f"{m.display_name or m.handle} is a trusted merchant on Carousell offering quality products and excellent service. Visit our profile to browse listings and connect with us today."

    # ── Stage 3: Generate QR codes ───────────────────────────────────────────
    print("[3/3] Generating QR codes...")
    for m in all_merchants:
        path = generate_qr(m, cache_dir)
        if path:
            m.qr_path = path

    # ── Stage 4: Render PDF ───────────────────────────────────────────────────
    print(f"[4/4] Rendering PDF → {job.output_path}")
    render_pdf(job)
    print(f"Done. {len(all_merchants)} merchant cards written.")


if __name__ == "__main__":
    run()
