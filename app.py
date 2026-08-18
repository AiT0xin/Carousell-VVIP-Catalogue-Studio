"""VVIP Catalogue Studio - one app, three features.

  1. Cross-check  - who's in the catalogue vs who's a VVIP → add / remove
  2. QR check     - every QR decodes, is live, and lands on the right merchant
  3. Generate     - apply the approved changes → corrected catalogue PDF

Run:  cd ~/vvip-catalogue-studio && .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from studio.crosscheck import run_crosscheck, crosscheck_summary
from studio.qr import run_qrcheck
from studio.generate import generate_plan, generate
from studio.runner import threaded_stage
from studio.state import (
    StudioSession,
    MerchantRecord,
    ProposedChange,
    CC_KEEP, CC_REMOVE, CC_ADD,
    QR_OK, QR_MISMATCH, QR_RENAMED, QR_DEAD, QR_SOFT404, QR_NONE, QR_UNKNOWN,
)

PROJECT_ROOT = Path(__file__).parent


def _load_dotenv() -> None:
    """Load AI_* (and any other) settings from a project-root .env into the
    environment, so the app works no matter how it was launched.

    The Streamlit process is started via `sh -c` (see .claude/launch.json and
    the deploy runner), which does NOT source ~/.zshrc — so shell exports never
    reach it and the AI toggle would stay disabled. Reading .env here fixes that
    without leaking secrets (.env is gitignored). Existing real env vars win, so
    a shell export or a hosting provider's secrets panel still takes precedence.
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

st.set_page_config(page_title="VVIP Catalogue Studio", layout="wide")

# ── Design system: load catalogue imagery + fonts ─────────────────────────────
import base64 as _b64
from pathlib import Path as _P

def _img_b64(name: str) -> str:
    p = _P(__file__).parent / "studio" / "static" / f"{name}.b64"
    return f"data:image/jpeg;base64,{p.read_text().strip()}" if p.exists() else ""

_img_goods    = _img_b64("goods_card")
_img_autos    = _img_b64("autos_card")
_img_luxury   = _img_b64("luxury_card")
_img_services = _img_b64("services_card")

st.markdown(
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet">',
    unsafe_allow_html=True,
)

_fabriga_path = Path.home() / "Library" / "Fonts" / "Fabriga Bold.ttf"
_fabriga_b64 = (
    base64.b64encode(_fabriga_path.read_bytes()).decode()
    if _fabriga_path.exists()
    else ""
)
_fabriga_face = (
    f"""@font-face {{
  font-family: 'Fabriga';
  src: url('data:font/truetype;base64,{_fabriga_b64}') format('truetype');
  font-weight: 700;
  font-style: normal;
}}"""
    if _fabriga_b64
    else ""
)
st.markdown(f"""
<style>
{_fabriga_face}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
/* ── Colour tokens ── */
:root {
  --primary:        #8b0a1a;
  --primary-active: #d6003a;
  --ink:            #1a1a1a;
  --body:           #3f3f3f;
  --muted:          #6a6a6a;
  --muted-soft:     #929292;
  --canvas:         #ffffff;
  --surface-soft:   #f8f8f8;
  --surface-card:   #ffffff;
  --border:         #e0e0e0;
  --border-soft:    #ededed;
  --error:          #c13515;
  --blue:           #3b82f6;
  --sidebar-bg:     #fafafa;
}
section[data-testid="stSidebar"] {
  --secondary-background-color: transparent !important;
  --background-color: transparent !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] > div,
section[data-testid="stSidebar"] [data-baseweb="select"] > div > div,
section[data-testid="stSidebar"] [data-baseweb="select"] [class*="control"],
section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div {
  background: #ffffff !important;
  background-color: #ffffff !important;
  border: 1.5px solid rgba(255,255,255,0.6) !important;
}
/* Dropdown popover menu */
[data-baseweb="popover"],
[data-baseweb="popover"] > div,
[data-baseweb="menu"],
[data-baseweb="menu"] ul,
[data-baseweb="menu"] li,
[role="listbox"],
[role="listbox"] li,
[role="option"] {
  background: #8b0a1a !important;
  background-color: #8b0a1a !important;
  border: 1px solid rgba(255,255,255,0.2) !important;
  color: #ffffff !important;
}
[role="option"]:hover,
[data-baseweb="menu"] li:hover,
[aria-selected="true"] {
  background: rgba(255,255,255,0.15) !important;
  color: #ffffff !important;
}

/* ── Global typography & appearance ── */
html, body, .stApp, * {
  font-family: "Poppins", "-apple-system", "system-ui", "Helvetica Neue", sans-serif !important;
  background-color: var(--canvas) !important;
  color: var(--ink) !important;
  line-height: 1.6 !important;
  font-size: 15px !important;
}

/* ── Dataframe: fully opt out of global overrides ── */
[data-testid="stDataFrame"] *,
[data-testid="stDataEditor"] * {
  background-color: unset !important;
  background: unset !important;
  color: unset !important;
  font-size: unset !important;
  line-height: unset !important;
}

/* Better text selection styling */
::selection {
  background-color: rgba(139, 10, 26, 0.25) !important;
  color: #ffffff !important;
}
::-moz-selection {
  background-color: rgba(139, 10, 26, 0.25) !important;
  color: #ffffff !important;
}

/* Main page area is white; only the sidebar is red */
[data-testid="stAppViewContainer"] {
  background: #ffffff !important;
  min-height: 100vh !important;
}
[data-testid="stMain"] > div {
  background: transparent !important;
}

/* All widget labels, captions, paragraphs → dark */
.stApp label,
.stApp p,
.stApp span:not(.carousell-logo),
[data-testid="stWidgetLabel"] *,
[data-testid="stText"] *,
[class*="stFileUploaderFileName"],
[class*="stFileUploaderFileData"] * {
  color: var(--ink) !important;
  font-size: 15px !important;
  line-height: 1.6 !important;
}

/* Small text (captions, helper text) */
.stApp small,
[data-testid="stCaption"],
.stApp caption {
  font-size: 13px !important;
  color: var(--muted) !important;
  line-height: 1.5 !important;
  font-weight: 400 !important;
}

/* Re-whiten the hero banner (more specific → wins) */
.carousell-hero h1,
.carousell-hero p,
.carousell-hero span:not(.carousell-logo) {
  color: #fff !important;
}

/* Marquee banner — must beat .stApp span:not(.carousell-logo) at 0-2-1 */
.stApp .marquee-track span,
.stApp .marquee-track span em,
.stApp .marquee-wrap .marquee-track span {
  color: #ffffff !important;
  background-color: transparent !important;
}

/* Beta pill */
.stApp .beta-pill {
  background-color: #fef08a !important;
  color: #7a6000 !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  border-radius: 999px !important;
  padding: 1px 7px !important;
  vertical-align: middle !important;
  letter-spacing: 0.03em !important;
  border: none !important;
}
.carousell-logo {
  color: var(--primary) !important;
  background: #fff !important;
}

/* ── Marquee banner text ── */
.marquee-track span, .marquee-track span em, .marquee-track * {
  color: #ffffff !important;
  background: transparent !important;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, [data-testid="stDecoration"] { display: none !important; }
/* Remove the sidebar collapse control entirely (no button, no reserved space) */
[data-testid="stSidebarHeader"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
/* Remove the Streamlit top header bar (deploy button + toolbar notch) */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stAppDeployButton"] { display: none !important; }

/* ── Page header banner (red hero strip) ── */
[data-testid="stAppViewContainer"] > section > div:first-child {
  padding-top: 0 !important;
}

/* ── Heading hierarchy (clear, readable) ── */
[data-testid="stAppViewContainer"] h1 {
  font-size: 32px !important;
  font-weight: 800 !important;
  letter-spacing: -0.015em !important;
  line-height: 1.35 !important;
  color: var(--ink) !important;
  margin: 24px 0 16px 0 !important;
}

h2, [data-testid="stMarkdownContainer"] h2 {
  font-size: 26px !important;
  font-weight: 700 !important;
  line-height: 1.3 !important;
  color: var(--ink) !important;
  margin: 24px 0 12px 0 !important;
}

h3, [data-testid="stMarkdownContainer"] h3 {
  font-size: 20px !important;
  font-weight: 600 !important;
  line-height: 1.35 !important;
  color: var(--ink) !important;
  margin: 18px 0 10px 0 !important;
}

h4, h5, h6 {
  font-size: 16px !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  color: var(--ink) !important;
  margin: 12px 0 8px 0 !important;
}

/* ── Tabs (clean underline style) ── */
[data-testid="stTabs"] [role="tablist"] {
  gap: 24px;
  border-bottom: 1px solid var(--border-soft) !important;
  padding-bottom: 0;
}
[data-testid="stTabs"] [role="tab"] {
  font-weight: 600 !important;
  font-size: 15px !important;
  padding: 14px 0 !important;
  color: var(--muted) !important;
  background: transparent !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  transition: all 0.2s ease !important;
  cursor: pointer !important;
}
[data-testid="stTabs"] [role="tab"]:hover {
  color: var(--body) !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--ink) !important;
  border-bottom: 3px solid var(--primary) !important;
  background: transparent !important;
  font-weight: 700 !important;
}

/* ── Primary + Download buttons (solid Rausch) ──
   Keyed off the stable kind="primary" attribute (and the download wrapper) so
   styling can't fall through to a white default if Streamlit renames its
   data-testids between versions. */
button[kind="primary"],
[data-testid="stButton"] button[kind="primary"],
[data-testid="stBaseButton-primary"],
[data-testid="stDownloadButton"] button[kind],
[data-testid="stDownloadButton"] button {
  background: var(--primary) !important;
  background-color: var(--primary) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
  font-size: 15px !important;
  padding: 14px 24px !important;
  height: 48px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
  cursor: pointer !important;
  position: relative !important;
  overflow: hidden !important;
}
button[kind="primary"] *,
button[kind="primary"] p,
button[kind="primary"] span,
[data-testid="stDownloadButton"] button[kind] *,
[data-testid="stDownloadButton"] button[kind] p,
[data-testid="stDownloadButton"] button[kind] span,
[data-testid="stDownloadButton"] button *,
[data-testid="stDownloadButton"] button p,
[data-testid="stDownloadButton"] button span {
  background: transparent !important;
  background-color: transparent !important;
  color: #ffffff !important;
}
button[kind="primary"]:hover,
[data-testid="stDownloadButton"] button[kind]:hover,
[data-testid="stDownloadButton"] button:hover {
  background: var(--primary-active) !important;
  box-shadow: 0 8px 16px rgba(139, 10, 26, 0.3) !important;
  transform: translateY(-2px) !important;
}
button[kind="primary"]:active,
[data-testid="stDownloadButton"] button[kind]:active,
[data-testid="stDownloadButton"] button:active {
  transform: translateY(0px) !important;
  box-shadow: 0 2px 4px rgba(139, 10, 26, 0.2) !important;
}
button[kind="primary"]:disabled {
  opacity: 0.6 !important;
  cursor: not-allowed !important;
}
button[kind="primary"]:focus-visible {
  outline: 2px solid var(--primary) !important;
  outline-offset: 2px !important;
  box-shadow: 0 0 0 4px rgba(139, 10, 26, 0.15) !important;
}

/* ── Secondary buttons (outline) ── */
button[kind="secondary"],
[data-testid="stButton"] button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {
  border: 1.5px solid var(--primary) !important;
  color: var(--primary) !important;
  background: var(--canvas) !important;
  background-color: var(--canvas) !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
  font-size: 15px !important;
  padding: 13px 23px !important;
  height: 48px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
  cursor: pointer !important;
}
button[kind="secondary"] *,
button[kind="secondary"] p,
button[kind="secondary"] span {
  background: transparent !important;
  background-color: transparent !important;
  color: var(--primary) !important;
}
button[kind="secondary"]:hover {
  background: rgba(139, 10, 26, 0.05) !important;
  border-color: var(--primary-active) !important;
  color: var(--primary-active) !important;
}
button[kind="secondary"]:active {
  background: rgba(139, 10, 26, 0.1) !important;
}
button[kind="secondary"]:disabled {
  opacity: 0.5 !important;
  cursor: not-allowed !important;
}

/* ── Metric cards (simple, clean) ── */
[data-testid="stMetric"] {
  background: var(--canvas) !important;
  border: 1px solid var(--border-soft) !important;
  border-radius: 14px !important;
  padding: 24px !important;
  box-shadow: none !important;
}
[data-testid="stMetricLabel"] {
  font-size: 15px !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.28px !important;
  color: var(--muted) !important;
  margin-bottom: 12px !important;
  line-height: 1.4 !important;
}
[data-testid="stMetricValue"] {
  font-size: 46px !important;
  font-weight: 800 !important;
  line-height: 1.15 !important;
  color: var(--ink) !important;
}
[data-testid="stMetricValue"] * {
  color: var(--ink) !important;
}
[data-testid="stMetricDelta"] {
  font-size: 14px !important;
  color: var(--muted) !important;
}

/* ── Cards (soft shadows, generous padding) ── */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] > div {
  border-radius: 14px !important;
  border: none !important;
  background: transparent !important;
  padding: 0 !important;
  box-shadow: none !important;
}

/* ── Info / success / warning alerts ── */
[data-testid="stAlert"][data-baseweb="notification"][aria-label="Info"] {
  border-left: 4px solid var(--blue) !important;
  border-radius: 10px !important;
  background: #eff6ff !important;
  color: var(--ink) !important;
}
[data-testid="stAlert"][data-baseweb="notification"][aria-label="Success"] {
  border-left: 4px solid #16a34a !important;
  border-radius: 10px !important;
  background: #f0fdf4 !important;
  color: var(--ink) !important;
}
[data-testid="stAlert"][data-baseweb="notification"][aria-label="Warning"] {
  border-left: 4px solid #ca8a04 !important;
  border-radius: 10px !important;
  background: #fefce8 !important;
  color: var(--ink) !important;
}
[data-testid="stAlert"][data-baseweb="notification"][aria-label="Error"] {
  border-left: 4px solid var(--error) !important;
  border-radius: 10px !important;
  background: #fee2e2 !important;
  color: var(--error) !important;
}

/* ── Form controls (clean, minimal) ── */

/* Text inputs */
[data-testid="stTextInput"] input {
  background: #ffffff !important;
  background-color: #ffffff !important;
  color: #1a1a1a !important;
  border-radius: 8px !important;
  border: 1.5px solid #d0d0d0 !important;
  font-size: 15px !important;
  font-weight: 400 !important;
  padding: 12px 14px !important;
  height: 48px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
  line-height: 1.6 !important;
}
[data-testid="stTextInput"] input::placeholder {
  color: #9a9a9a !important;
}
[data-testid="stTextInput"] input:hover {
  border-color: var(--muted) !important;
  box-shadow: 0 0 0 2px rgba(139, 10, 26, 0.05) !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextInput"] input:focus-visible {
  border-color: var(--primary) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(139, 10, 26, 0.15) !important;
}
[data-testid="stTextInput"] input::placeholder {
  color: var(--muted-soft) !important;
  font-weight: 400 !important;
}

/* Selectbox (clean styling) */
[data-testid="stSelectbox"] > div > div,
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stSelectbox"] [data-baseweb="select"] div {
  background: var(--canvas) !important;
  border-color: var(--border) !important;
  color: var(--ink) !important;
}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] div,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] * {
  background: #ffffff !important;
  background-color: #ffffff !important;
  border-color: rgba(255,255,255,0.6) !important;
  color: #8b0a1a !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
  border: 1.5px solid rgba(255, 255, 255, 0.25) !important;
  border-radius: 8px !important;
  min-height: 56px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div:hover {
  border-color: var(--muted) !important;
  box-shadow: 0 0 0 2px rgba(139, 10, 26, 0.05) !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within {
  border-color: var(--primary) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(139, 10, 26, 0.15) !important;
}

/* Select text + placeholder */
[data-testid="stSelectbox"] [data-baseweb="select"] span,
[data-testid="stSelectbox"] [data-baseweb="select"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"],
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="singleValue"],
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="value"] {
  color: #ffffff !important;
  font-size: 15px !important;
  font-weight: 400 !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"] {
  color: rgba(255, 255, 255, 0.5) !important;
  font-weight: 400 !important;
}

/* Dropdown arrow */
[data-testid="stSelectbox"] [data-baseweb="select"] svg {
  fill: var(--muted) !important;
}

/* Dropdown menu (portal) */
[data-baseweb="popover"],
[data-baseweb="popover"] > div,
[data-baseweb="menu"],
[data-baseweb="menu"] ul {
  background: var(--canvas) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12) !important;
}
[data-baseweb="menu"] li,
[data-baseweb="option"],
[role="option"],
[role="listbox"] > * {
  background: var(--canvas) !important;
  color: var(--ink) !important;
  padding: 12px 16px !important;
  transition: all 0.15s ease !important;
  cursor: pointer !important;
  font-size: 15px !important;
  font-weight: 400 !important;
}
[data-baseweb="option"] *,
[role="option"] * {
  color: var(--ink) !important;
  font-size: 15px !important;
}
[data-baseweb="option"]:hover,
[role="option"]:hover,
[data-baseweb="option"]:hover * {
  background: var(--surface-soft) !important;
  color: var(--ink) !important;
  padding-left: 20px !important;
}
[data-baseweb="option"][aria-selected="true"],
[role="option"][aria-selected="true"] {
  background: rgba(139, 10, 26, 0.08) !important;
  color: var(--primary) !important;
  font-weight: 600 !important;
  border-left: 3px solid var(--primary) !important;
  padding-left: 13px !important;
}
[data-baseweb="option"][aria-selected="true"] *,
[role="option"][aria-selected="true"] * {
  color: var(--primary) !important;
}

/* File uploader (simple, clean) */
[data-testid="stFileUploader"] > section,
[data-testid="stFileUploader"] > div {
  background: transparent !important;
  border-radius: 12px !important;
}

[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed rgba(255, 255, 255, 0.3) !important;
  color: #ffffff !important;
  padding: 32px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
  background: rgba(255, 255, 255, 0.05) !important;
  border-radius: 12px !important;
}
[data-testid="stFileUploaderDropzone"]:hover {
  background: #ffffff !important;
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 2px rgba(139, 10, 26, 0.1) !important;
}

/* Instructions text inside uploader */
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzoneInstructions"] > div,
[data-testid="stFileUploaderDropzoneInstructions"] > section,
[data-testid="stFileUploaderDropzoneInstructions"] *,
div[class*="uploadInstructions"],
div[class*="UploadInstructions"],
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"],
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] * {
  background: transparent !important;
  background-color: transparent !important;
  border: none !important;
  box-shadow: none !important;
  --secondary-background-color: transparent !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small {
  color: #ffffff !important;
  font-weight: 500 !important;
  font-size: 15px !important;
  line-height: 1.5 !important;
  text-shadow: none !important;
}

/* Browse files button */
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzoneInstructions"] button {
  background: var(--canvas) !important;
  color: var(--primary) !important;
  border: 1.5px solid var(--primary) !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
  padding: 10px 16px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
  cursor: pointer !important;
}
[data-testid="stFileUploaderDropzone"] button:hover,
[data-testid="stFileUploaderDropzoneInstructions"] button:hover {
  background: rgba(139, 10, 26, 0.05) !important;
  border-color: var(--primary-active) !important;
  color: var(--primary-active) !important;
}

/* Checkbox */
[data-testid="stCheckbox"] label {
  cursor: pointer !important;
  transition: all 0.2s ease !important;
}
[data-testid="stCheckbox"] label > div {
  background: var(--canvas) !important;
  border: 1.5px solid var(--border) !important;
  border-radius: 6px !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}
[data-testid="stCheckbox"] label > div[data-checked="true"] {
  background: var(--primary) !important;
  border-color: var(--primary) !important;
  box-shadow: 0 2px 6px rgba(139, 10, 26, 0.15) !important;
}
[data-testid="stCheckbox"] label:hover > div {
  border-color: var(--primary) !important;
}

/* Text areas */
textarea {
  background: rgba(255, 255, 255, 0.1) !important;
  color: #ffffff !important;
  border: 1.5px solid rgba(255, 255, 255, 0.25) !important;
  border-radius: 8px !important;
  font-family: inherit !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}
textarea::placeholder {
  color: rgba(255, 255, 255, 0.5) !important;
}
textarea:hover {
  border-color: var(--muted) !important;
  box-shadow: 0 0 0 2px rgba(139, 10, 26, 0.05) !important;
}
textarea:focus {
  border-color: var(--primary) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(139, 10, 26, 0.15) !important;
}

/* ── Toggle switch ── */
[data-testid="stToggle"] > label > div[data-checked="true"] {
  background: var(--primary) !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {
  border-radius: 12px !important;
  border: 1px solid var(--border-soft) !important;
}

/* ── Progress bar (live updates) ── */
[data-baseweb="progress-bar"] > div > div {
  background: rgba(0,0,0,0.08) !important;
  border-radius: 6px !important;
  height: 10px !important;
}
[data-baseweb="progress-bar"] > div > div > div {
  background: linear-gradient(90deg, var(--primary), #ff6b6b) !important;
  border-radius: 6px !important;
  transition: width 0.4s ease !important;
}

/* ── Sidebar (static/fixed, red) ── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] * {
  background: #8b0a1a !important;
}

[data-testid="stSidebar"] {
  border-right: 1px solid rgba(0,0,0,0.08) !important;
  box-shadow: 2px 0 20px rgba(0,0,0,0.12) !important;
  position: relative !important;
  left: auto !important;
  top: auto !important;
  height: auto !important;
  min-height: 100vh !important;
  overflow: visible !important;
  z-index: 100 !important;
  width: 280px !important;
  transform: none !important;
}

/* Force transparent backgrounds on sidebar divs to show red */
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div > div {
  background: transparent !important;
}

/* Sidebar now flows in-page; no main offset needed */
[data-testid="stAppViewContainer"] {
  margin-left: 0 !important;
}

/* ── Unified page scroll: scroll sidebar + main together ── */
/* The whole app is the single scroll container */
[data-testid="stApp"] {
  height: 100vh !important;
  overflow-y: auto !important;
  overflow-x: hidden !important;
}
/* The flex row grows to its tallest child so the red panel fills full height */
[data-testid="stAppViewContainer"] {
  position: static !important;
  height: auto !important;
  min-height: 100vh !important;
  overflow: visible !important;
  align-items: stretch !important;
}
/* Stop the main column from scrolling on its own */
[data-testid="stMain"] {
  overflow: visible !important;
  height: auto !important;
  background: transparent !important;
  background-color: transparent !important;
}
/* Header band must not paint white over the red — let red show at the top */
[data-testid="stHeader"],
[data-testid="stToolbar"] {
  background: transparent !important;
  background-color: transparent !important;
}
/* The wrapper div between the view container and main must grow, not clip */
[data-testid="stAppViewContainer"] > div:not([data-testid="stSidebar"]) {
  height: auto !important;
  overflow: visible !important;
  background: transparent !important;
  background-color: transparent !important;
}
[data-testid="stSidebar"] > div:first-child {
  padding-top: 0 !important;
}

/* Sidebar text on red background */
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] .stText,
[data-testid="stSidebar"] [data-testid="stText"] * {
  color: #ffffff !important;
}

/* Sidebar file uploader on red */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
  background: rgba(255,255,255,0.15) !important;
  border: 2px dashed rgba(255,255,255,0.4) !important;
  padding: 12px !important;
}

[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] small {
  color: rgba(255,255,255,0.8) !important;
}

[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
  background: #ffffff !important;
  color: #8b0a1a !important;
  border: 1.5px solid #ffffff !important;
}

[data-testid="stSidebar"] label {
  font-size: 12px !important;
  font-weight: 700 !important;
  color: rgba(255,255,255,0.9) !important;
  letter-spacing: 0.02em !important;
}

/* Sidebar selectbox on red */
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div {
  background: #ffffff !important;
  border: 1.5px solid rgba(255,255,255,0.6) !important;
  color: #8b0a1a !important;
}

section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] span,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] input,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"],
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] [class*="singleValue"],
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] [class*="value"] {
  color: #8b0a1a !important;
  font-weight: 700 !important;
}

[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] svg,
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] svg path,
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] svg * {
  fill: #8b0a1a !important;
  display: inline-block !important;
  opacity: 1 !important;
}

/* Sidebar divider */
[data-testid="stSidebar"] hr {
  border-color: rgba(255,255,255,0.2) !important;
}

/* Sidebar checkbox */
[data-testid="stSidebar"] [data-testid="stCheckbox"] label {
  color: #ffffff !important;
}

[data-testid="stSidebar"] [data-testid="stCheckbox"] label > div {
  background: rgba(255,255,255,0.2) !important;
  border: 1.5px solid rgba(255,255,255,0.3) !important;
}

[data-testid="stSidebar"] [data-testid="stCheckbox"] label > div[data-checked="true"] {
  background: #ffffff !important;
  border-color: #ffffff !important;
}

/* ── Toggle switch: the global white-bg rule hides the track; recolour it ── */
/* The only st.checkbox-rendered widgets in the main area are toggles. */
/* OFF: grey track */
[data-testid="stMain"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > div:first-of-type {
  background: #c4c4c4 !important;
  background-color: #c4c4c4 !important;
  border: none !important;
  width: 44px !important;
  height: 24px !important;
  border-radius: 999px !important;
  flex-shrink: 0 !important;
}
/* ON: teal track */
[data-testid="stMain"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"]:has(input:checked) > div:first-of-type {
  background: #1a7a6a !important;
  background-color: #1a7a6a !important;
}
/* White thumb with shadow so it's always visible; slide it on check */
[data-testid="stMain"] [data-testid="stCheckbox"] label[data-baseweb="checkbox"] > div:first-of-type > div {
  background: #ffffff !important;
  background-color: #ffffff !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.4) !important;
  width: 18px !important;
  height: 18px !important;
  border-radius: 50% !important;
}

/* ── Expander (accordion) ── */
[data-testid="stExpander"] {
  background: var(--canvas) !important;
  border: 1px solid var(--border-soft) !important;
  border-radius: 10px !important;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary * {
  color: var(--ink) !important;
  background: transparent !important;
}
[data-testid="stExpander"] > div {
  background: var(--surface-soft) !important;
}

/* ── Code blocks ── */
[data-testid="stCode"],
[data-testid="stCode"] > div,
[data-testid="stCode"] pre,
.stCode, pre {
  background: #f5f5f5 !important;
  border: 1px solid var(--border-soft) !important;
  border-radius: 8px !important;
  color: var(--ink) !important;
}
[data-testid="stCode"] code,
[data-testid="stCode"] span,
pre code, pre span {
  color: var(--primary) !important;
  background: transparent !important;
}

/* ── Main content card wrapper (floats over red background) ── */
[data-testid="stMainBlockContainer"] {
  background: #ffffff !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  margin: 0 !important;
  padding: 32px 40px 64px !important;
  min-height: 100vh !important;
}

/* ── Hero banner ── */
.carousell-hero {
  background: linear-gradient(135deg, #8b0a1a 0%, #c9113a 100%);
  border-radius: 20px;
  padding: 40px 48px;
  margin-bottom: 32px;
  color: white;
  position: relative;
  overflow: hidden;
}
/* subtle radial glow top-right */
.carousell-hero::after {
  content: "";
  position: absolute;
  top: -40px; right: -40px;
  width: 260px; height: 260px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.07);
  pointer-events: none;
}
.carousell-hero-inner {
  display: flex;
  align-items: center;
  gap: 28px;
  position: relative;
  z-index: 1;
}
.carousell-logo-icon {
  flex-shrink: 0;
  width: 64px;
  height: 64px;
}
.carousell-hero-text { flex: 1; }
.hero-eyebrow {
  font-size: 11px !important;
  font-weight: 700 !important;
  letter-spacing: 0.32px !important;
  text-transform: uppercase !important;
  color: rgba(255, 255, 255, 0.65) !important;
  margin-bottom: 8px !important;
}
.carousell-hero h1 {
  color: #ffffff !important;
  font-size: 28px !important;
  font-weight: 700 !important;
  line-height: 1.3 !important;
  margin: 0 0 10px 0 !important;
  letter-spacing: -0.02em !important;
}
.hero-badge {
  font-size: 11px !important;
  font-weight: 700 !important;
  letter-spacing: 0.32px !important;
  text-transform: uppercase !important;
  background: rgba(255, 255, 255, 0.18) !important;
  border: 1px solid rgba(255, 255, 255, 0.35) !important;
  border-radius: 20px !important;
  padding: 3px 10px !important;
  vertical-align: middle !important;
  margin-left: 10px !important;
}
.carousell-hero p {
  color: rgba(255, 255, 255, 0.85) !important;
  font-size: 15px !important;
  line-height: 1.5 !important;
  margin: 0 0 4px 0 !important;
}
.carousell-experiment {
  font-size: 12px !important;
  font-weight: 600 !important;
  font-style: italic !important;
  color: rgba(255, 200, 200, 0.8) !important;
  margin-top: 10px !important;
}
/* ── Tables: fixed height, no resize handle ── */
[data-testid="stDataFrame"] > div,
[data-testid="stDataEditor"] > div {
  resize: none !important;
}
[data-testid="stDataFrame"] > div > div,
[data-testid="stDataEditor"] > div > div {
  resize: none !important;
}
/* Hide the drag-to-resize gripper */
[data-testid="stDataFrame"] .glideDataEditor,
[data-testid="stDataEditor"] .glideDataEditor {
  resize: none !important;
}

/* ── Data editor: cell selection ── */
[data-testid="stDataEditor"] .dvn-scroller .rdg-cell[aria-selected="true"],
[data-testid="stDataEditor"] .rdg-cell:focus,
[data-testid="stDataEditor"] .rdg-row:hover .rdg-cell {
  color: var(--ink) !important;
}
[data-testid="stDataEditor"] .rdg-cell[aria-selected="true"] {
  background: rgba(255, 56, 92, 0.08) !important;
  color: var(--ink) !important;
  outline: 2px solid var(--primary) !important;
}
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea {
  color: var(--ink) !important;
  background: var(--canvas) !important;
  border-color: var(--border) !important;
}
[data-testid="stDataEditor"] input:focus,
[data-testid="stDataEditor"] textarea:focus {
  border-color: var(--primary) !important;
  outline: none !important;
}


/* ── Hero empty state text ── */
.hero-heading {
  font-size: clamp(28px, 4vw, 44px) !important;
  font-weight: 800 !important;
  color: #8b0a1a !important;
  margin-bottom: 12px !important;
  letter-spacing: -0.03em !important;
  line-height: 1.25 !important;
}
.hero-subtext {
  font-size: 17px !important;
  color: #5a5a5a !important;
  max-width: 520px !important;
  margin: 0 auto 12px auto !important;
  line-height: 1.65 !important;
  font-weight: 400 !important;
}
/* Image category label chips */
.cat-label {
  text-align: center;
  font-weight: 700;
  font-size: 10px;
  color: #6a6a6a !important;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-top: 6px;
}
/* Image cards: round corners + subtle shadow */
[data-testid="stImage"] img {
  border-radius: 10px !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08) !important;
}

/* ── UX: cursor + transitions on interactive elements ── */
button,
[role="button"],
[data-testid="stButton"] button,
[data-testid="baseButton-secondary"],
[data-testid="baseButton-primary"],
[data-testid="stFileUploaderDropzone"],
[data-testid="stSelectbox"],
[data-testid="stCheckbox"] label,
[data-testid="stTabs"] [role="tab"],
[role="option"],
[role="tab"] {
  cursor: pointer !important;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
}
/* Primary action buttons */
[data-testid="stButton"] > button[kind="primary"],
[data-testid="baseButton-primary"] {
  background: var(--primary) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 10px !important;
  font-weight: 700 !important;
  font-size: 14px !important;
  padding: 12px 24px !important;
  letter-spacing: 0.02em !important;
  box-shadow: 0 2px 8px rgba(139,10,26,0.25) !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover,
[data-testid="baseButton-primary"]:hover {
  background: #a00d20 !important;
  box-shadow: 0 4px 16px rgba(139,10,26,0.35) !important;
  transform: translateY(-1px) !important;
}
[data-testid="stButton"] > button[kind="primary"]:active,
[data-testid="baseButton-primary"]:active {
  transform: translateY(0px) scale(0.98) !important;
  box-shadow: 0 1px 4px rgba(139,10,26,0.2) !important;
}
/* Secondary buttons */
[data-testid="stButton"] > button[kind="secondary"],
[data-testid="baseButton-secondary"] {
  background: transparent !important;
  color: var(--primary) !important;
  border: 1.5px solid var(--primary) !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
  padding: 10px 20px !important;
}
[data-testid="stButton"] > button[kind="secondary"]:hover,
[data-testid="baseButton-secondary"]:hover {
  background: rgba(139,10,26,0.06) !important;
  border-color: var(--primary-active) !important;
  color: var(--primary-active) !important;
}
/* Prefers-reduced-motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
  }
}

/* ── Greyed tabs when loading ── */
.tabs-disabled [data-testid="stTabs"] {
  opacity: 0.4;
  pointer-events: none;
  user-select: none;
}

/* ── Sidebar: force all text white ── */
section[data-testid="stSidebar"] *,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div,
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] li,
section[data-testid="stSidebar"] a {
  color: #ffffff !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] span,
section[data-testid="stSidebar"] [data-baseweb="select"] div,
section[data-testid="stSidebar"] [data-baseweb="select"] [class*="placeholder"],
section[data-testid="stSidebar"] [data-baseweb="select"] [class*="singleValue"] {
  color: #ffffff !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] svg path {
  fill: #ffffff !important;
}
section[data-testid="stSidebar"] hr {
  border-color: rgba(255,255,255,0.2) !important;
}

/* ── Restore Material Symbols for Streamlit chrome ── */
/* Our * { font-family: Inter } breaks icon ligatures; put them back */
[data-testid="stToolbar"] *,
[data-testid="stHeader"] *,
header[data-testid="stHeader"] span,
[data-testid="stSidebarCollapseButton"] *,
[data-testid="stSidebarCollapsedControl"] * {
  font-family: "Material Symbols Rounded", "Material Icons", -apple-system, sans-serif !important;
  font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24 !important;
}

/* ── Empty state enhancements ── */
/* Better spacing for empty state message */
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
  margin-bottom: 12px !important;
}

/* Badge/pill styling for empty state features */
[data-testid="stColumn"] p {
  font-size: 14px !important;
  color: var(--body) !important;
}

/* Better divider styling */
[data-testid="stDivider"] {
  margin: 20px 0 !important;
  background: linear-gradient(90deg, transparent, var(--border), transparent) !important;
}

/* Metric cards on hover */
[data-testid="stMetric"]:hover {
  box-shadow: rgba(0,0,0,0.04) 0 0 0 1px, rgba(0,0,0,0.06) 0 4px 12px, rgba(0,0,0,0.1) 0 8px 20px !important;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

/* Improve heading spacing */
h1, h2, h3, h4, h5, h6 {
  margin-top: 24px !important;
}
h1:first-child, h2:first-child, h3:first-child {
  margin-top: 0 !important;
}
</style>
""", unsafe_allow_html=True)


# ── Session bootstrap ───────────────────────────────────────────────────────
if "sess" not in st.session_state:
    st.session_state.sess = StudioSession()
sess: StudioSession = st.session_state.sess


@st.dialog("Terms of Use")
def _show_tos():
    st.markdown("""
**VVIP E-Catalogue Studio — Terms of Use**
*Last updated: 17 August 2026*

By accessing, installing, running, or otherwise using this Software, you acknowledge that you have read, understood, and agree to be bound by these Terms of Use ("Terms") in their entirety. If you do not agree, do not use the Software.

---

**1. Nature of This Software**

VVIP E-Catalogue Studio ("the Software") is an independent, personal productivity tool developed by Owin Tan ("the Developer") to assist with the VVIP Flyer and E-Catalogue workflow. It is provided as a personal, non-commercial software project and is not affiliated with, endorsed by, sponsored by, authorised by, or in any way officially connected to Carousell Pte. Ltd., Carousell Group, or any of their subsidiaries, affiliates, officers, employees, contractors, or agents ("Carousell Group"), nor to any other company, platform, or third party referenced within it.

**2. No Affiliation; No Infringement Intended**

The Software does not claim ownership over, reproduce, redistribute, or commercialise any proprietary content, trademarks, branding, data, or intellectual property belonging to Carousell Group or any third party. All product names, logos, brands, and trademarks are the property of their respective owners and are referenced for identification and interoperability purposes only. Any interaction with third-party platforms, merchant profiles, or catalogue formats is incidental to the Software's workflow-automation purpose. The Developer respects all applicable intellectual-property rights and intends no infringement.

**3. User Responsibility for Data and Inputs**

You are solely responsible for any files, spreadsheets, images, PDFs, URLs, credentials, or other data ("Inputs") that you upload to or process with the Software. You represent and warrant that you own or have all necessary rights, licences, consents, and permissions to use, upload, and process such Inputs, and that doing so does not violate any law, contract, privacy right, intellectual-property right, or third-party terms of service. The Software processes Inputs locally on the machine on which it runs; the Developer does not collect, receive, store, monitor, or have access to your Inputs or outputs.

**4. Third-Party Services and Platforms**

The Software may, at your direction, interact with third-party services and platforms (including but not limited to Carousell websites and the Anthropic API). Your use of any such third-party service is governed solely by that service's own terms of service, acceptable-use policies, and applicable laws. You are solely responsible for ensuring that your use of the Software — including any automated access, retrieval, verification, or processing of publicly available information — complies with those terms and with all applicable laws and regulations. The Developer does not endorse, control, or assume any responsibility for any third-party service, its availability, or the consequences of your use of it.

**5. Acceptable Use and Assumption of Risk**

You agree to use the Software only for lawful purposes and in accordance with these Terms. You assume all risk arising from your use of the Software. You are responsible for independently reviewing, verifying, and validating all outputs (including generated catalogues, QR codes, and merchant data) before relying on, publishing, distributing, or acting upon them. The Software's outputs may be incomplete, inaccurate, or out of date, and must not be treated as authoritative without independent verification.

**6. Restriction on Copying**

The Software, including its source code, logic, structure, design, and presentation, is the intellectual property of Owin Tan. Carousell Group, and any other person or entity, is expressly prohibited from copying, reproducing, adapting, translating, reverse-engineering, decompiling, redistributing, sublicensing, or incorporating any part of the Software — in whole or in part — into any commercial, internal, or derivative product without the prior written consent of Owin Tan. No rights are granted except as expressly set out in these Terms.

**7. Permitted Use**

The Software is made available for use by authorised individuals within the intended workflow context. You may not redistribute, resell, sublicense, rent, lease, or make the Software available to any third party without the Developer's explicit prior written permission.

**8. No Warranty**

THE SOFTWARE IS PROVIDED "AS IS" AND "AS AVAILABLE", WITHOUT WARRANTY OF ANY KIND, WHETHER EXPRESS, IMPLIED, STATUTORY, OR OTHERWISE, INCLUDING WITHOUT LIMITATION ANY IMPLIED WARRANTIES OR CONDITIONS OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, ACCURACY, OR NON-INFRINGEMENT. THE DEVELOPER DOES NOT WARRANT THAT THE SOFTWARE WILL BE UNINTERRUPTED, ERROR-FREE, SECURE, OR THAT ANY OUTPUT WILL BE ACCURATE OR COMPLETE. YOU USE THE SOFTWARE ENTIRELY AT YOUR OWN RISK.

**9. Limitation of Liability**

TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL THE DEVELOPER BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, OR FOR ANY LOSS OF PROFITS, REVENUE, DATA, GOODWILL, OR BUSINESS OPPORTUNITY, ARISING OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THESE TERMS, WHETHER IN CONTRACT, TORT (INCLUDING NEGLIGENCE), STRICT LIABILITY, OR OTHERWISE, EVEN IF THE DEVELOPER HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. THE DEVELOPER'S TOTAL AGGREGATE LIABILITY FOR ALL CLAIMS RELATING TO THE SOFTWARE SHALL NOT EXCEED SGD 0 (ZERO SINGAPORE DOLLARS).

**10. Indemnification**

You agree to indemnify, defend, and hold harmless the Developer from and against any and all claims, liabilities, damages, losses, costs, and expenses (including reasonable legal fees) arising out of or related to (a) your use or misuse of the Software; (b) your Inputs; (c) your violation of these Terms; (d) your violation of any law or any third-party right, including any third-party terms of service, intellectual-property right, or privacy right.

**11. No Support Obligation**

The Software is provided without any obligation on the part of the Developer to provide maintenance, updates, support, or corrections of any kind.

**12. Compliance with Laws**

You are solely responsible for ensuring that your use of the Software complies with all laws, regulations, and third-party agreements applicable to you, including data-protection and privacy laws.

**13. Severability**

If any provision of these Terms is held to be invalid, illegal, or unenforceable, that provision shall be severed and the remaining provisions shall continue in full force and effect.

**14. Changes to These Terms**

The Developer may modify these Terms at any time. Continued use of the Software after any change constitutes acceptance of the revised Terms. The "Last updated" date above indicates when these Terms were most recently revised.

**15. Entire Agreement**

These Terms constitute the entire agreement between you and the Developer regarding the Software and supersede any prior understandings or agreements.

**16. Governing Law and Jurisdiction**

These Terms shall be governed by and construed in accordance with the laws of the Republic of Singapore, without regard to its conflict-of-laws principles. You agree to submit to the exclusive jurisdiction of the courts of Singapore in respect of any dispute arising out of or in connection with these Terms or the Software.

---

*© 2026 Owin Tan. All rights reserved.*
""")


def _reset_results():
    sess.merchants = []
    sess.changes = []
    sess.crosscheck_done = False
    sess.qrcheck_done = False
    sess.generate_done = False
    sess.generate_result = None
    sess.output_path = None


# ── Sidebar ──────────────────────────────────────────────────────────────────

def _pill(ok: bool, label: str) -> str:
    if ok:
        return (
            f'<div style="display:inline-flex;align-items:center;gap:5px;'
            f'background:rgba(255,255,255,0.18);border:1px solid rgba(255,255,255,0.35);'
            f'border-radius:999px;padding:4px 10px 4px 6px;margin:3px 4px 3px 0;">'
            f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
            f'<span style="font-size:11px;color:#ffffff;font-weight:600;letter-spacing:0.01em;white-space:nowrap;">{label}</span>'
            f'</div>'
        )
    return (
        f'<div style="display:inline-flex;align-items:center;gap:5px;'
        f'background:rgba(0,0,0,0.15);border:1px solid rgba(255,255,255,0.12);'
        f'border-radius:999px;padding:4px 10px 4px 6px;margin:3px 4px 3px 0;">'
        f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/></svg>'
        f'<span style="font-size:11px;color:rgba(255,255,255,0.5);font-weight:500;letter-spacing:0.01em;white-space:nowrap;">{label}</span>'
        f'</div>'
    )

with st.sidebar:
    st.markdown("""
<style>
section[data-testid="stSidebar"] *,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div,
section[data-testid="stSidebar"] small {
  color: #ffffff !important;
}
.carousell-brand {
  font-family: 'Fabriga', Poppins, sans-serif !important;
  font-size: clamp(24px, 4vw, 40px) !important;
  font-weight: 700 !important;
  color: #ffffff !important;
  text-align: center !important;
  letter-spacing: -0.02em !important;
  line-height: 1 !important;
  margin: 0 0 16px 0 !important;
  display: block !important;
  white-space: nowrap !important;
}
/* ── High-specificity overrides for sidebar text ── */
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] div,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] small {
  color: #ffffff !important;
}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] *,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] span,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] label {
  color: #ffffff !important;
}
section[data-testid="stSidebar"] hr {
  border-color: rgba(255,255,255,0.15) !important;
  margin: 16px 0 !important;
}
section[data-testid="stSidebar"] .ecatalogue-label {
  font-size: 26px !important;
}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [class*="placeholder"],
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [class*="singleValue"],
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [class*="value"],
section[data-testid="stSidebar"] [data-testid="stSelectbox"] span {
  color: #8b0a1a !important;
  font-weight: 700 !important;
}
</style>
""", unsafe_allow_html=True)

    st.markdown("""
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;margin-bottom:24px;">
  <div class="carousell-brand">Carousel</div>
  <svg width="120" height="120" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" style="margin-bottom:12px;">
    <rect x="8" y="8" width="104" height="104" rx="20" fill="#ffffff"/>
    <circle cx="60" cy="28" r="8" fill="#8b0a1a"/>
    <circle cx="80" cy="36" r="8" fill="#8b0a1a"/>
    <circle cx="92" cy="52" r="8" fill="#8b0a1a"/>
    <circle cx="92" cy="72" r="8" fill="#8b0a1a"/>
    <circle cx="80" cy="88" r="8" fill="#8b0a1a"/>
    <circle cx="60" cy="96" r="8" fill="#8b0a1a"/>
    <circle cx="40" cy="88" r="8" fill="#8b0a1a"/>
    <circle cx="28" cy="72" r="8" fill="#8b0a1a"/>
    <circle cx="28" cy="52" r="8" fill="#8b0a1a"/>
    <circle cx="40" cy="36" r="8" fill="#8b0a1a"/>
  </svg>
  <div style="font-weight:800;color:#ffffff;letter-spacing:0.05em;text-transform:uppercase;text-align:center;margin-bottom:8px;" class="ecatalogue-label">E-Catalogue Studio</div>
</div>
""", unsafe_allow_html=True)

    st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.15);margin:0 0 16px 0;">', unsafe_allow_html=True)
    st.markdown('<p style="font-size:11px;font-weight:700;letter-spacing:0.32px;text-transform:uppercase;color:#ffffff !important;margin-bottom:12px;">STEP 1  CATALOGUE PDF</p>', unsafe_allow_html=True)

    uploaded = st.file_uploader("Catalogue PDF", type=["pdf"], label_visibility="collapsed")
    # Only (re)process when a genuinely new file is uploaded — file_id is stable
    # across reruns, so this won't re-create tempfiles or wipe results each run.
    if uploaded is not None:
        if st.session_state.get("_cat_file_id") != uploaded.file_id:
            import tempfile, os
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="studio_upload_")
            os.chmod(tmp_path, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(uploaded.getvalue())
            sess.catalogue_path = tmp_path
            st.session_state["_cat_file_id"] = uploaded.file_id
            _reset_results()
    elif sess.catalogue_path is not None:
        sess.catalogue_path = None
        st.session_state["_cat_file_id"] = None
        _reset_results()

    st.markdown('<p style="font-size:11px;font-weight:700;letter-spacing:0.32px;text-transform:uppercase;color:#ffffff !important;margin:20px 0 12px 0;">STEP 2  VVIP MASTER SHEET</p>', unsafe_allow_html=True)

    master_up = st.file_uploader("VVIP Master Sheet", type=["xlsx", "csv"], label_visibility="collapsed")
    if master_up is not None:
        if st.session_state.get("_master_file_id") != master_up.file_id:
            import tempfile, os
            ext = Path(master_up.name).suffix.lower()
            fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="studio_master_")
            os.chmod(tmp_path, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(master_up.getvalue())
            sess.master_path = tmp_path
            st.session_state["_master_file_id"] = master_up.file_id
            _reset_results()
    elif sess.master_path is not None:
        sess.master_path = None
        st.session_state["_master_file_id"] = None
        _reset_results()

    st.markdown('<div style="font-size:11px;font-weight:700;letter-spacing:0.32px;text-transform:uppercase;color:#ffffff;margin:20px 0 12px 0;">STEP 3  SELECT CATEGORY</div>', unsafe_allow_html=True)

    _CATEGORIES = ["Autos", "Services", "Luxury", "Goods"]
    _CAT_OPTIONS = ["Select Category"] + _CATEGORIES
    current_idx = 0
    if sess.category in _CATEGORIES:
        current_idx = _CATEGORIES.index(sess.category) + 1
    cat = st.selectbox("Category (sheet)", _CAT_OPTIONS, index=current_idx, label_visibility="collapsed")
    if cat != "Select Category" and cat != sess.category:
        sess.category = cat
    elif cat == "Select Category":
        sess.category = ""

    st.divider()

    def _step(ok: bool, label: str, last: bool = False) -> str:
        dot_bg   = "#39ff14" if ok else "transparent"
        dot_border = "#39ff14" if ok else "#ff0033"
        dot_shadow = "0 0 6px #39ff14, 0 0 12px #39ff14, 0 0 20px rgba(57,255,20,0.6)" if ok else "0 0 6px #ff0033, 0 0 12px #ff0033, 0 0 20px rgba(255,0,51,0.6)"
        tick = ('<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#111111" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
                if ok else "")
        label_color = "#ffffff" if ok else "rgba(255,255,255,0.45)"
        label_weight = "600" if ok else "400"
        rail = "" if last else (
            '<div style="width:2px;background:rgba(255,255,255,0.25) !important;'
            'background-color:rgba(255,255,255,0.25) !important;'
            'height:20px;margin:2px 0 2px 6px;flex-shrink:0;border-radius:1px;"></div>'
        )
        return (
            f'<div style="display:flex;align-items:center;gap:10px;">'
            f'  <div style="width:15px;height:15px;border-radius:50%;'
            f'    background:{dot_bg};border:1.5px solid {dot_border};'
            f'    box-shadow:{dot_shadow};'
            f'    flex-shrink:0;display:flex;align-items:center;justify-content:center;">{tick}</div>'
            f'  <span style="font-size:12px;font-weight:{label_weight};color:{label_color};'
            f'    letter-spacing:0.01em;">{label}</span>'
            f'</div>'
            f'{rail}'
        )

    steps = [
        (bool(sess.catalogue_path), "Catalogue PDF"),
        (bool(sess.master_path),    "Master Sheet"),
        (bool(sess.category),       "Category"),
        (sess.crosscheck_done,      "Cross check"),
        (sess.qrcheck_done,         "QR check"),
        (sess.generate_done,        "Generate Catalogue"),
    ]
    stepper_html = (
        '<style>'
        'section[data-testid="stSidebar"] .session-box {'
        '  background-color: #111111 !important;'
        '  border: 1px solid rgba(255,255,255,0.15) !important;'
        '  border-radius: 12px !important;'
        '  padding: 16px 16px 14px !important;'
        '  margin-top: 4px !important;'
        '}'
        'section[data-testid="stSidebar"] .session-box * {'
        '  background-color: transparent !important;'
        '  background: transparent !important;'
        '}'
        '</style>'
        '<div class="session-box">'
        '<div style="font-size:10px;font-weight:700;letter-spacing:0.3em;'
        'text-transform:uppercase;color:rgba(255,255,255,0.45);margin-bottom:14px;">'
        'Session Status</div>'
        '<div style="display:flex;flex-direction:column;">'
        + "".join(_step(ok, lbl, last=(i == len(steps)-1)) for i, (ok, lbl) in enumerate(steps))
        + '</div></div>'
    )
    st.markdown(stepper_html, unsafe_allow_html=True)

    st.markdown("""
<style>
section[data-testid="stSidebar"] [data-testid="stButton"] button {
  background: #1a7a6a !important;
  background-color: #1a7a6a !important;
  border: 2px solid #1a7a6a !important;
  color: #ffffff !important;
  font-size: 12px !important;
  font-weight: 700 !important;
  white-space: nowrap !important;
  border-radius: 8px !important;
  cursor: pointer !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}
section[data-testid="stSidebar"] [data-testid="stButton"] button > * {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  width: 100% !important;
  text-align: center !important;
}
section[data-testid="stSidebar"] [data-testid="stButton"] button,
section[data-testid="stSidebar"] [data-testid="stButton"] button p,
section[data-testid="stSidebar"] [data-testid="stButton"] button span,
section[data-testid="stSidebar"] [data-testid="stButton"] button * {
  background: #1a7a6a !important;
  background-color: #1a7a6a !important;
  color: #ffffff !important;
}
section[data-testid="stSidebar"] [data-testid="stButton"] button:hover {
  background: #22957f !important;
  background-color: #22957f !important;
  border-color: #22957f !important;
}
</style>
<div style="margin-top:20px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.12);"></div>
""", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])
    with col:
        if st.button("↺  Start over", key="reset_session", use_container_width=False):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

# ── Rolling banner ──────────────────────────────────────────────────────────
st.markdown("""
<style>
.marquee-wrap {
  overflow: hidden;
  background: #111111 !important;
  border-radius: 10px;
  padding: 10px 0;
  margin-bottom: 12px;
  white-space: nowrap;
}
.marquee-wrap * { background: transparent !important; }
.marquee-track {
  display: inline-flex;
  animation: marquee-scroll 18s linear infinite;
}
.marquee-track span,
.marquee-track span * {
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: 0.18em !important;
  text-transform: uppercase !important;
  color: #ffffff !important;
  padding: 0 40px;
}
.marquee-track span em {
  color: rgba(255,255,255,0.5) !important;
  font-style: normal;
  margin: 0 12px;
}
@keyframes marquee-scroll {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
</style>
<div class="marquee-wrap">
  <div class="marquee-track">
    <span>Owin × Claude Code <em>✦</em> Owin × Claude Code <em>✦</em> Owin × Claude Code <em>✦</em> Owin × Claude Code <em>✦</em></span>
    <span>Owin × Claude Code <em>✦</em> Owin × Claude Code <em>✦</em> Owin × Claude Code <em>✦</em> Owin × Claude Code <em>✦</em></span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Main workspace ──────────────────────────────────────────────────────────
ready = bool(sess.catalogue_path and sess.master_path)

if not ready:
    from PIL import Image
    import io

    def _load_img(name: str):
        p = _P(__file__).parent / "studio" / "static" / f"{name}.b64"
        if p.exists():
            b64 = p.read_text().strip()
            img_data = _b64.b64decode(b64)
            return Image.open(io.BytesIO(img_data))
        return None

    st.markdown("""
    <div id="hero-text" style="padding:16px 0 12px;text-align:center;">
    <div class="hero-heading">Ready to audit your catalogue?</div>
    <div class="hero-subtext">Upload a catalogue PDF and VVIP master sheet in the sidebar to run cross check, verify QR codes, or generate a corrected catalogue.</div>
    </div>
<style>
.cat-grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px; margin: 24px 0 32px 0; }
.cat-card { position: relative; border-radius: 12px; overflow: hidden; }
.cat-card img { width: 100%; height: 140px; object-fit: cover; display: block; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.10); }
.cat-card .cat-label {
  position: absolute; bottom: 0; left: 0; right: 0;
  background: #8b0a1a !important;
  color: #ffffff !important;
  font-size: 10px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; text-align: center;
  padding: 1px 8px 1px; border-radius: 0 0 12px 12px;
}
</style>
    """, unsafe_allow_html=True)

    # Category tiles use the locally-embedded images (studio/static/*.b64) so the
    # page is fully self-contained — no external hotlinks that can break, go
    # stale, or leak each visitor's IP to third-party image hosts.
    st.markdown(f"""
<div class="cat-grid">
  <div class="cat-card">
    <img src="{_img_goods}" alt="Goods">
    <div class="cat-label">Goods</div>
  </div>
  <div class="cat-card">
    <img src="{_img_services}" alt="Services">
    <div class="cat-label">Services</div>
  </div>
  <div class="cat-card">
    <img src="{_img_autos}" alt="Autos">
    <div class="cat-label">Autos</div>
  </div>
  <div class="cat-card">
    <img src="{_img_luxury}" alt="Luxury">
    <div class="cat-label">Luxury</div>
  </div>
</div>
    """, unsafe_allow_html=True)

    st.image(str(Path(__file__).resolve().parent / "studio" / "static" / "features_grid.png"), use_container_width=True)

    st.markdown("""
    <div style="padding:8px 0;"></div>
    """, unsafe_allow_html=True)

    st.markdown("""
<style>
.workflow-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 24px 0 28px;
}
.workflow-card {
  position: relative;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 28px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.workflow-card:nth-child(3) {
  grid-column: 1 / -1;
}
.workflow-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: #8b0a1a;
  opacity: 0;
  transition: opacity 0.2s ease;
}
.wf-step {
  font-size: 64px;
  font-weight: 800;
  color: #8b0a1a;
  opacity: 0.07;
  position: absolute;
  top: -8px; right: 12px;
  line-height: 1;
  letter-spacing: -0.04em;
  font-family: 'Poppins', sans-serif;
  pointer-events: none;
  user-select: none;
}
.wf-icon {
  width: 40px;
  height: 40px;
  background: rgba(139,10,26,0.08);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}
.wf-label {
  font-size: 14px;
  font-weight: 700;
  color: #1a1a1a;
  margin-bottom: 5px;
  line-height: 1.35;
  letter-spacing: -0.01em;
}
.wf-desc {
  font-size: 12px;
  color: #888;
  line-height: 1.55;
  font-weight: 400;
}
</style>
<div class="workflow-grid">
  <div class="workflow-card">
    <span class="wf-step">01</span>
    <div class="wf-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8b0a1a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>
        <polyline points="3 6 4 7 6 5"/><polyline points="3 12 4 13 6 11"/><circle cx="4.5" cy="18" r="1.5"/>
      </svg>
    </div>
    <div class="wf-label">Cross-check VVIPs</div>
    <div class="wf-desc">Compare catalogue listings against the master sheet. Find who to add or remove.</div>
  </div>
  <div class="workflow-card">
    <span class="wf-step">02</span>
    <div class="wf-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8b0a1a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
        <rect x="14" y="14" width="3" height="3"/><rect x="18" y="18" width="3" height="3"/>
      </svg>
    </div>
    <div class="wf-label">Verify QR codes</div>
    <div class="wf-desc">Scan every QR in the PDF, confirm each decodes and lands on the right merchant profile.</div>
  </div>
  <div class="workflow-card">
    <span class="wf-step">03</span>
    <div class="wf-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#8b0a1a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/>
        <polyline points="12 12 12 17"/>
      </svg>
    </div>
    <div class="wf-label">Generate catalogue <span class="beta-pill">beta</span></div>
    <div class="wf-desc">Apply approved changes and export a corrected, print-ready catalogue PDF.</div>
  </div>
</div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <style>[data-testid="stTabs"] { display: none !important; }</style>
    """, unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["Cross check", "QR Check", "Generate"])


# ── Helper: approval editor ─────────────────────────────────────────────────
def approval_editor(changes: list[ProposedChange], key: str) -> None:
    """Render a checkbox table that writes approval back onto the changes."""
    if not changes:
        st.success("Nothing to change here.")
        return
    df = pd.DataFrame([{
        "Approve": c.approved,
        "Action": c.kind.replace("_", " "),
        "Handle": c.handle,
        "Merchant": c.display_name,
        "Why": c.reason,
    } for c in changes])
    edited = st.data_editor(
        df, key=key, hide_index=True, use_container_width=True,
        height=561,
        disabled=["Action", "Handle", "Merchant", "Why"],
        column_config={"Approve": st.column_config.CheckboxColumn(width="small")},
    )
    for c, ok in zip(changes, edited["Approve"]):
        c.approved = bool(ok)


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 - CROSS-CHECK
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### VVIP Cross check")
    st.caption("Is each merchant in the catalogue, and are they still a VVIP?")

    if not ready:
        st.info("Upload a catalogue PDF and VVIP master sheet in the sidebar to begin.")
    elif st.button("Run cross check", type="primary", key="run_cc"):
        prog = st.progress(0.0, text="Starting cross check…")
        err = None

        def _cc_stage(emit):
            import time as _t
            emit({"pct": 0.05, "msg": "Rendering PDF pages…"})
            # Pulse the bar while extract_pdf runs (it's the slow part)
            from studio.sources import extract_pdf as _extract, load_master as _lm, category_from_pdf_name as _cfp
            rows, unpaired = _extract(sess.catalogue_path)
            emit({"pct": 0.6, "msg": "Comparing to VVIP master sheet…"})
            run_crosscheck(sess)
            emit({"pct": 0.95, "msg": "Finalising…"})
            return True

        for kind, payload in threaded_stage(_cc_stage):
            if kind == "progress":
                prog.progress(payload["pct"], text=payload["msg"])
            elif kind == "error":
                err = payload
        if err:
            st.error("Cross check failed.")
            with st.expander("Trace", expanded=True):
                import re as _re; st.text(_re.sub(r'File "/.+?/([^/"]+\.py)"', r'File "\1"', err or ""))
        else:
            prog.progress(1.0, text="Cross check complete")
            import time as _t; _t.sleep(0.5); prog.empty()
            st.rerun()

    if sess.crosscheck_done:
        s = crosscheck_summary(sess)
        st.markdown("""
<style>
/* Cross-check metric cards — uniform height + tinted fill, no white inner box */
[data-testid="stHorizontalBlock"] > div [data-testid="stMetric"] {
  min-height: 150px !important;
  display: flex !important;
  flex-direction: column !important;
  justify-content: center !important;
  border-radius: 12px !important;
  padding: 16px 18px !important;
}
/* Make every inner box (value/label/delta wrappers) transparent so the card colour fills */
[data-testid="stHorizontalBlock"] > div [data-testid="stMetric"] [data-testid="stMetricValue"],
[data-testid="stHorizontalBlock"] > div [data-testid="stMetric"] [data-testid="stMetricLabel"],
[data-testid="stHorizontalBlock"] > div [data-testid="stMetric"] [data-testid="stMetricDeltaIcon-Up"],
[data-testid="stHorizontalBlock"] > div [data-testid="stMetric"] [data-testid="stMetricDeltaIcon-Down"],
[data-testid="stHorizontalBlock"] > div [data-testid="stMetric"] [data-testid="stMetricDelta"],
[data-testid="stHorizontalBlock"] > div [data-testid="stMetric"] * {
  background: transparent !important;
  background-color: transparent !important;
}
/* Cards 1 & 2 — neutral */
[data-testid="stHorizontalBlock"] > div:nth-child(1) [data-testid="stMetric"],
[data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stMetric"] {
  background-color: #f7f7f8 !important;
  border: 1px solid #e5e7eb !important;
}
/* Card 3 — Keep (green) */
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetric"] {
  background-color: #dcfce7 !important;
  border: 1px solid #86efac !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetricLabel"] * {
  color: #059669 !important;
}
/* Card 4 — Remove (red) */
[data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetric"] {
  background-color: #ffe4e6 !important;
  border: 1px solid #fecdd3 !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetricLabel"] * {
  color: #8b0a1a !important;
}
/* Card 5 — Add (blue) */
[data-testid="stHorizontalBlock"] > div:nth-child(5) [data-testid="stMetric"] {
  background-color: #dbeafe !important;
  border: 1px solid #bfdbfe !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(5) [data-testid="stMetricLabel"] * {
  color: #2563eb !important;
}
</style>
""", unsafe_allow_html=True)
        m = st.columns(5)
        m[0].metric("In catalogue", s["in_catalogue"])
        m[1].metric("VVIPs in sheet", s["vvip_total"])
        m[2].metric("✓ Keep", s["keep"])
        m[3].metric("— Remove", s["remove"], delta=f"-{s['remove']}",
                    delta_color="normal")
        m[4].metric("+ Add", s["add"], delta=f"+{s['add']}",
                    delta_color="normal")

        _BADGE = {CC_KEEP: "✓ keep", CC_REMOVE: "— remove", CC_ADD: "+ add"}
        rows = [{
            "Handle": x.handle,
            "Merchant": x.display_name or "-",
            "In catalogue": "✓" if x.in_catalogue else "",
            "VVIP": "✓" if x.is_vvip else "",
            "Action": _BADGE.get(x.cc_status, x.cc_status),
            "Pg": str(x.page) if x.page else "",
        } for x in sorted(sess.merchants, key=lambda r: (r.cc_status, r.handle))]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     height=561)

        st.markdown("##### Proposed changes - approve to apply")
        cc_changes = [c for c in sess.changes if c.source == "crosscheck"]
        approval_editor(cc_changes, key="cc_appr")
    else:
        pass


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 - QR CHECK
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### QR Code Check")
    st.caption("Decode every QR, confirm it's live, and that it lands on the printed merchant - not a renamed or blank shell.")

    if not ready:
        pass
    elif not sess.crosscheck_done:
        pass
    else:
        do_live = st.toggle("Check each link is live",
                            value=True)
        if st.button("Run QR check", type="primary", key="run_qr"):
            prog = st.progress(0.0, text="Starting…")
            err = None

            def _stage(emit):
                def cb(i, n, rec):
                    emit({"i": i, "n": n, "handle": rec.handle,
                          "status": rec.qr_status})
                run_qrcheck(sess, do_live=do_live, progress_cb=cb)
                return True

            for kind, payload in threaded_stage(_stage):
                if kind == "progress":
                    prog.progress(payload["i"] / max(payload["n"], 1),
                                  text=f"Verified {payload['i']}/{payload['n']} - "
                                       f"@{payload['handle']} → {payload['status']}")
                elif kind == "error":
                    err = payload
                elif kind == "result":
                    pass
            if err:
                st.error("QR check failed.")
                with st.expander("Trace", expanded=True):
                    import re as _re; st.text(_re.sub(r'File "/.+?/([^/"]+\.py)"', r'File "\1"', err or "(no traceback captured)"))
            else:
                sess.qrcheck_done = True
                prog.progress(1.0, text="QR check complete")
                import time as _t2; _t2.sleep(0.5); prog.empty()
                st.rerun()

        if sess.qrcheck_done:
            from collections import Counter
            cards = sess.in_catalogue()
            counts = Counter(c.qr_status for c in cards)
            st.markdown("""
<style>
[data-testid="stHorizontalBlock"] > div:nth-child(1) [data-testid="stMetric"] {
  background-color: rgba(16,185,129,0.07) !important;
  border: 1px solid rgba(16,185,129,0.22) !important;
  border-radius: 12px !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(1) [data-testid="stMetricLabel"] * { color: #059669 !important; }
[data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stMetric"] {
  background-color: rgba(234,179,8,0.07) !important;
  border: 1px solid rgba(234,179,8,0.25) !important;
  border-radius: 12px !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stMetricLabel"] * { color: #a16207 !important; }
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetric"] {
  background-color: rgba(249,115,22,0.07) !important;
  border: 1px solid rgba(249,115,22,0.22) !important;
  border-radius: 12px !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetricLabel"] * { color: #c2410c !important; }
[data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetric"] {
  background-color: rgba(139,10,26,0.07) !important;
  border: 1px solid rgba(139,10,26,0.22) !important;
  border-radius: 12px !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetricLabel"] * { color: #8b0a1a !important; }
[data-testid="stHorizontalBlock"] > div:nth-child(5) [data-testid="stMetric"] {
  background-color: rgba(139,10,26,0.04) !important;
  border: 1px solid rgba(139,10,26,0.12) !important;
  border-radius: 12px !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(5) [data-testid="stMetricLabel"] * { color: #8b0a1a !important; }
[data-testid="stHorizontalBlock"] > div:nth-child(6) [data-testid="stMetric"] {
  background-color: rgba(100,116,139,0.06) !important;
  border: 1px solid rgba(100,116,139,0.18) !important;
  border-radius: 12px !important;
}
[data-testid="stHorizontalBlock"] > div:nth-child(6) [data-testid="stMetricLabel"] * { color: #475569 !important; }
</style>
""", unsafe_allow_html=True)
            m = st.columns(6)
            m[0].metric("✓ OK", counts.get(QR_OK, 0))
            m[1].metric("~ Mismatch", counts.get(QR_MISMATCH, 0))
            m[2].metric("» Renamed", counts.get(QR_RENAMED, 0))
            m[3].metric("× Dead", counts.get(QR_DEAD, 0))
            m[4].metric("? Soft 404", counts.get(QR_SOFT404, 0))
            m[5].metric("— No QR", counts.get(QR_NONE, 0))

            _QB = {QR_OK: "✓ ok", QR_MISMATCH: "~ mismatch", QR_RENAMED: "» renamed",
                   QR_DEAD: "× dead", QR_SOFT404: "? soft 404", QR_NONE: "— no qr",
                   QR_UNKNOWN: "·"}
            rows = [{
                "Handle": x.handle,
                "Printed": x.at,
                "QR lands on": f"@{x.resolves_to}" if x.resolves_to else "-",
                "Status": _QB.get(x.qr_status, x.qr_status),
                "Detail": (x.qr_detail or "")[:60],
                "Pg": str(x.page) if x.page else "",
            } for x in sorted(cards, key=lambda r: (r.qr_ok, r.handle))]
            st.dataframe(pd.DataFrame(rows), hide_index=True,
                         use_container_width=True, height=561)

            st.markdown("##### Broken QRs - approve to regenerate")
            qr_changes = [c for c in sess.changes if c.source == "qrcheck"]
            approval_editor(qr_changes, key="qr_appr")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 - GENERATE
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown("### Generate Corrected Catalogue")
    if not ready:
        pass
    elif not sess.crosscheck_done:
        pass
    else:
        plan = generate_plan(sess)
        m = st.columns(4)
        m[0].metric("Final merchants", plan["final_count"])
        m[1].metric("Adding", plan["added"])
        m[2].metric("Removing", plan["removed"])
        m[3].metric("QR fixes", plan["qr_fixes"])

        st.caption("Generation rebuilds every card fresh (profile, description, "
                   "and a brand-new QR from the canonical URL) - so every broken "
                   "QR is corrected by construction.")

        from studio.sources import ai_configured
        have_key = ai_configured()
        do_describe = st.toggle(
            "Write AI descriptions (needs an AI provider)",
            value=have_key, disabled=not have_key,
            help=None if have_key else "Set AI_BASE_URL / AI_API_KEY / AI_MODEL for a free provider (Ollama Cloud, local Ollama, or Gemini). See README.")
        if not have_key:
            st.caption("No API key found - cards will use a generic description.")

        st.markdown("**Cover pages** — optional. Upload a front and/or back "
                    "cover (PDF or image) to wrap the catalogue. Leave empty for "
                    "no cover.")
        _cov_c1, _cov_c2 = st.columns(2)
        with _cov_c1:
            cover_up = st.file_uploader("Front cover", type=["pdf", "png", "jpg", "jpeg"],
                                        key="cover_up")
        with _cov_c2:
            back_up = st.file_uploader("Back cover", type=["pdf", "png", "jpg", "jpeg"],
                                       key="back_up")

        def _prep_cover(upload, name: str):
            """Save an uploaded cover (PDF/image) as a full-page PNG; return its path."""
            if upload is None:
                return None
            covers_dir = Path(sess.cache_dir) / "covers"
            covers_dir.mkdir(parents=True, exist_ok=True)
            out_png = covers_dir / f"{name}.png"
            data = upload.getvalue()
            if Path(upload.name).suffix.lower() == ".pdf":
                import pypdfium2 as _pdfium, io as _io
                doc = _pdfium.PdfDocument(data)
                doc[0].render(scale=3.0).to_pil().convert("RGB").save(out_png)
            else:
                from PIL import Image as _Image
                import io as _io
                _Image.open(_io.BytesIO(data)).convert("RGB").save(out_png)
            return out_png

        import re as _re
        _stem = _re.sub(r"[^a-zA-Z0-9._-]", "_", Path(sess.catalogue_path).stem)[:80]
        default_out = f"/tmp/{_stem}_corrected.pdf"
        out_path = st.text_input("Output path", value=sess.output_path or default_out)

        if st.button("Generate catalogue", type="primary", key="run_gen"):
            try:
                _cover_path = _prep_cover(cover_up, "cover")
                _back_path = _prep_cover(back_up, "back_cover")
            except Exception as _ce:
                st.error(f"Couldn't read a cover file: {_ce}")
                st.stop()
            # Blank field → fall back to the default file path.
            out_path = (out_path or "").strip() or default_out
            # If a directory (or path with no .pdf suffix) was given, drop a
            # named file inside it instead of trying to write onto the folder.
            _out = Path(out_path).expanduser().resolve()
            if _out.is_dir() or _out.suffix.lower() != ".pdf":
                _out = (_out / f"{_stem}_corrected.pdf") if _out.is_dir() \
                    else _out.with_suffix(".pdf")
            # Validate: must live within /tmp or the home dir. Resolve the allowed
            # roots too — on macOS /tmp is a symlink to /private/tmp, so a resolved
            # output path won't match the literal "/tmp". Use real path containment
            # (== root or root in parents), not a string prefix — a prefix check
            # would wrongly accept siblings like /tmp-evil or /Users/owinX.
            _allowed = (Path("/tmp").resolve(), Path.home().resolve())
            if not any(_out == p or p in _out.parents for p in _allowed):
                st.error("Output path must be within /tmp or your home directory.")
                st.stop()
            # Make sure the parent folder exists so the render can write the file.
            try:
                _out.parent.mkdir(parents=True, exist_ok=True)
            except Exception as _e:
                st.error(f"Can't create output folder {_out.parent}: {_e}")
                st.stop()
            sess.output_path = str(_out)
            prog = st.progress(0.0, text="Building…")
            result = None
            err = None

            def _stage(emit):
                def cb(i, n, handle, name):
                    emit({"i": i, "n": n, "handle": handle, "status": name})
                return generate(sess, do_describe=do_describe,
                                cover_path=_cover_path, back_cover_path=_back_path,
                                progress_cb=cb)

            for kind, payload in threaded_stage(_stage):
                if kind == "progress":
                    prog.progress(payload["i"] / max(payload["n"], 1),
                                  text=f"[{payload['i']}/{payload['n']}] "
                                       f"@{payload['handle']} - {payload['status']}")
                elif kind == "error":
                    err = payload
                elif kind == "result":
                    result = payload
            if err:
                import logging
                logging.error("Generation failed:\n%s", err)
                st.error("Generation failed.")
                with st.expander("Trace", expanded=True):
                    # Strip full file paths from traceback before displaying
                    import re as _re
                    safe_err = _re.sub(r'File "/.+?/([^/"]+\.py)"', r'File "\1"', err)
                    st.text(safe_err)
            elif result:
                prog.progress(1.0, text="Done")
                # Persist the result and rerun so the sidebar Session Status can
                # light up "Generate Catalogue"; the panel below re-renders the
                # success + download from session state after the rerun.
                sess.generate_result = {
                    "built": result["built"],
                    "output": result["output"],
                    "skipped": list(result.get("skipped", [])),
                }
                sess.generate_done = True
                st.rerun()

        # Persistent result panel — survives the rerun above so the download
        # button and preview stay visible after generation completes.
        if sess.generate_done and sess.generate_result:
            _gr = sess.generate_result
            st.success(f"Built {_gr['built']} cards - {_gr['output']}")
            if _gr.get("skipped"):
                st.warning("Skipped (profile not found): " +
                           ", ".join("@" + h for h in _gr["skipped"]))
            out = Path(_gr["output"])
            if out.exists():
                with open(out, "rb") as f:
                    st.download_button("Download corrected PDF", f.read(),
                                       file_name=out.name,
                                       mime="application/pdf",
                                       use_container_width=True)
                # preview first pages
                try:
                    import pypdfium2 as pdfium
                    doc = pdfium.PdfDocument(str(out))
                    pages = list(doc)
                    st.caption(f"Preview ({len(pages)} page(s))")
                    for i, pg in enumerate(pages[:4]):
                        st.image(pg.render(scale=1.4).to_pil(),
                                 use_container_width=True)
                except Exception:
                    pass

st.markdown("""
<style>
div.tos-footer { text-align:center; margin-top:40px; margin-bottom:4px; }
div.tos-footer span { font-size:8px; color:rgba(0,0,0,0.3); letter-spacing:0.05em; }
.stApp [data-testid="stBaseButton-secondary"][aria-label="Terms of Use"] {
  background:transparent !important; border:none !important;
  color:rgba(0,0,0,0.3) !important; font-size:8px !important;
  text-decoration:underline !important; padding:0 !important;
  height:auto !important; min-height:0 !important; box-shadow:none !important;
}
</style>
<div class="tos-footer"><span>© 2026 Owin Tan · Vibe Coded with Claude Code · v5</span></div>
""", unsafe_allow_html=True)

_, mid, _ = st.columns([3, 1, 3])
with mid:
    if st.button("Terms of Use", key="tos_btn_footer", use_container_width=True):
        _show_tos()

st.markdown('<div style="height:32px;"></div>', unsafe_allow_html=True)

st.markdown('<div style="height:32px;"></div>', unsafe_allow_html=True)
