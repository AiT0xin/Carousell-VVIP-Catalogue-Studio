"""VVIP Catalogue Studio — one app, three features.

  1. Cross-check  — who's in the catalogue vs who's a VVIP → add / remove
  2. QR check     — every QR decodes, is live, and lands on the right merchant
  3. Generate     — apply the approved changes → corrected catalogue PDF

Run:  cd ~/vvip-catalogue-studio && .venv/bin/streamlit run app.py
"""
from __future__ import annotations

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

st.set_page_config(page_title="VVIP Catalogue Studio", layout="wide", page_icon="🗂️")

# ── Airbnb-inspired design system ────────────────────────────────────────────
st.markdown("""
<style>
/* ── Colour tokens (Airbnb system) ── */
:root {
  --primary:        #ff385c;
  --primary-active: #e00b41;
  --ink:            #222222;
  --body:           #3f3f3f;
  --muted:          #6a6a6a;
  --muted-soft:     #929292;
  --canvas:         #ffffff;
  --surface-soft:   #f7f7f7;
  --surface-card:   #ffffff;
  --border:         #dddddd;
  --border-soft:    #ebebeb;
  --error:          #c13515;
  --blue:           #428bff;
}

/* ── Global typography & appearance ── */
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > section,
[data-testid="stAppViewContainer"] > section > div {
  font-family: "Inter", "-apple-system", "system-ui", "Roboto", "Helvetica Neue", sans-serif !important;
  background-color: var(--canvas) !important;
  color: var(--ink) !important;
  line-height: 1.5 !important;
}

/* All widget labels, captions, paragraphs → dark */
.stApp label,
.stApp p,
.stApp small,
.stApp span:not(.carousell-logo),
[data-testid="stWidgetLabel"] *,
[data-testid="stText"] *,
[class*="stFileUploaderFileName"],
[class*="stFileUploaderFileData"] * {
  color: var(--ink) !important;
}

/* Re-whiten the hero banner (more specific → wins) */
.carousell-hero h1,
.carousell-hero p,
.carousell-hero span:not(.carousell-logo) {
  color: #fff !important;
}
.carousell-logo {
  color: var(--primary) !important;
  background: #fff !important;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, [data-testid="stDecoration"] { display: none !important; }

/* ── Page header banner (red hero strip) ── */
[data-testid="stAppViewContainer"] > section > div:first-child {
  padding-top: 0 !important;
}

/* ── Heading hierarchy (modest weights) ── */
[data-testid="stAppViewContainer"] h1 {
  font-size: 28px !important;
  font-weight: 700 !important;
  letter-spacing: -0.02em !important;
  line-height: 1.43 !important;
  color: var(--ink) !important;
}

h2, [data-testid="stMarkdownContainer"] h2 {
  font-size: 22px !important;
  font-weight: 600 !important;
  line-height: 1.18 !important;
  color: var(--ink) !important;
}

h3, [data-testid="stMarkdownContainer"] h3 {
  font-size: 18px !important;
  font-weight: 600 !important;
  line-height: 1.25 !important;
  color: var(--ink) !important;
}

/* ── Tabs (clean underline style) ── */
[data-testid="stTabs"] [role="tablist"] {
  gap: 24px;
  border-bottom: 1px solid var(--border-soft) !important;
  padding-bottom: 0;
}
[data-testid="stTabs"] [role="tab"] {
  font-weight: 600 !important;
  font-size: 16px !important;
  padding: 12px 0 !important;
  color: var(--muted) !important;
  background: transparent !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--ink) !important;
  border-bottom: 2px solid var(--primary) !important;
  background: transparent !important;
}

/* ── Primary buttons (Rausch) ── */
[data-testid="stButton"] button[kind="primary"],
button[data-testid="baseButton-primary"] {
  background: var(--primary) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  font-size: 16px !important;
  padding: 14px 24px !important;
  height: 48px !important;
  transition: background 0.2s ease !important;
}
[data-testid="stButton"] button[kind="primary"]:hover {
  background: var(--primary-active) !important;
}

[data-testid="stButton"] button[kind="primary"]:focus-visible {
  outline: 2px solid var(--primary) !important;
  outline-offset: 2px !important;
}

/* ── Secondary buttons (outline) ── */
[data-testid="stButton"] button[kind="secondary"],
button[data-testid="baseButton-secondary"] {
  border: 1.5px solid var(--primary) !important;
  color: var(--primary) !important;
  background: var(--canvas) !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  font-size: 16px !important;
  padding: 13px 23px !important;
  height: 48px !important;
}

/* ── Download button ── */
[data-testid="stDownloadButton"] button {
  background: var(--primary) !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  transition: background 0.2s ease !important;
}
[data-testid="stDownloadButton"] button:hover {
  background: var(--primary-active) !important;
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
  font-size: 12px !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.32px !important;
  color: var(--muted) !important;
  margin-bottom: 8px !important;
}
[data-testid="stMetricValue"] {
  font-size: 28px !important;
  font-weight: 700 !important;
  line-height: 1.1 !important;
  color: var(--ink) !important;
}

/* ── Cards (soft shadows, generous padding) ── */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] > div {
  border-radius: 14px !important;
  border: 1px solid var(--border-soft) !important;
  background: var(--canvas) !important;
  padding: 24px !important;
  box-shadow: rgba(0,0,0,0.02) 0 0 0 1px, rgba(0,0,0,0.04) 0 2px 6px, rgba(0,0,0,0.1) 0 4px 8px !important;
  transition: box-shadow 0.2s ease !important;
}
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] > div:hover {
  box-shadow: rgba(0,0,0,0.04) 0 0 0 1px, rgba(0,0,0,0.08) 0 4px 12px, rgba(0,0,0,0.15) 0 6px 16px !important;
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
  background: var(--canvas) !important;
  color: var(--ink) !important;
  border-radius: 8px !important;
  border: 1px solid var(--border) !important;
  font-size: 16px !important;
  padding: 14px 12px !important;
  height: 56px !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextInput"] input:focus-visible {
  border-color: var(--primary) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(255, 56, 92, 0.1) !important;
}
[data-testid="stTextInput"] input::placeholder {
  color: var(--muted-soft) !important;
}

/* Selectbox (clean styling) */
[data-testid="stSelectbox"] > div > div,
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stSelectbox"] [data-baseweb="select"] div {
  background: var(--canvas) !important;
  border-color: var(--border) !important;
  color: var(--ink) !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
  min-height: 56px !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within {
  border-color: var(--primary) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(255, 56, 92, 0.1) !important;
}

/* Select text + placeholder */
[data-testid="stSelectbox"] [data-baseweb="select"] span,
[data-testid="stSelectbox"] [data-baseweb="select"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"],
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="singleValue"],
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="value"] {
  color: var(--ink) !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"] {
  color: var(--muted-soft) !important;
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
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
}
[data-baseweb="menu"] li,
[data-baseweb="option"],
[role="option"],
[role="listbox"] > * {
  background: var(--canvas) !important;
  color: var(--ink) !important;
  padding: 12px 16px !important;
}
[data-baseweb="option"] *,
[role="option"] * {
  color: var(--ink) !important;
}
[data-baseweb="option"]:hover,
[role="option"]:hover,
[data-baseweb="option"]:hover * {
  background: var(--surface-soft) !important;
  color: var(--ink) !important;
}
[data-baseweb="option"][aria-selected="true"],
[role="option"][aria-selected="true"] {
  background: #f7f7f7 !important;
  color: var(--primary) !important;
  font-weight: 600 !important;
}
[data-baseweb="option"][aria-selected="true"] *,
[role="option"][aria-selected="true"] * {
  color: var(--primary) !important;
}

/* File uploader (simple, clean) */
[data-testid="stFileUploader"] > section,
[data-testid="stFileUploader"] > div,
[data-testid="stFileUploaderDropzone"] {
  background: var(--surface-soft) !important;
  border-radius: 12px !important;
}

[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed var(--border) !important;
  color: var(--ink) !important;
  padding: 32px !important;
  transition: all 0.2s ease !important;
}
[data-testid="stFileUploaderDropzone"]:hover {
  background: #ffffff !important;
  border-color: var(--primary) !important;
}

/* Instructions text inside uploader */
[data-testid="stFileUploaderDropzoneInstructions"] {
  background: transparent !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small {
  color: var(--muted) !important;
}

/* Browse files button */
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzoneInstructions"] button {
  background: var(--canvas) !important;
  color: var(--primary) !important;
  border: 1px solid var(--primary) !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  padding: 10px 16px !important;
}
[data-testid="stFileUploaderDropzone"] button:hover {
  background: rgba(255, 56, 92, 0.05) !important;
}

/* Checkbox */
[data-testid="stCheckbox"] label > div {
  background: var(--canvas) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
}
[data-testid="stCheckbox"] label > div[data-checked="true"] {
  background: var(--primary) !important;
  border-color: var(--primary) !important;
}

/* Text areas */
textarea {
  background: var(--canvas) !important;
  color: var(--ink) !important;
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
  font-family: inherit !important;
}
textarea:focus {
  border-color: var(--primary) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(255, 56, 92, 0.1) !important;
}

/* ── Toggle switch ── */
[data-testid="stToggle"] > label > div[data-checked="true"] {
  background: var(--primary) !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
  border-radius: 12px !important;
  overflow: hidden !important;
  border: 1px solid var(--border-soft) !important;
  background: var(--canvas) !important;
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

/* ── Sidebar ── */
[data-testid="stSidebar"] {
  background: var(--surface-soft) !important;
  border-right: 1px solid var(--border-soft) !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
  background: var(--canvas) !important;
  border: 1.5px dashed var(--border) !important;
  padding: 16px !important;
}
[data-testid="stSidebar"] label {
  font-size: 13px !important;
  font-weight: 600 !important;
  color: var(--ink) !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] > div {
  background: var(--canvas) !important;
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

/* ── Hero banner ── */
.carousell-hero {
  background: linear-gradient(135deg, #ff385c 0%, #c9113a 100%);
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
  overflow: hidden !important;
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

/* File upload success indicator (✓ tick) */
[data-testid="stFileUploaderFileName"]::after {
  content: " ✓";
  color: #22c55e;
  font-weight: 700;
  font-size: 1em;
}

/* ── Greyed tabs when loading ── */
.tabs-disabled [data-testid="stTabs"] {
  opacity: 0.4;
  pointer-events: none;
  user-select: none;
}
</style>
""", unsafe_allow_html=True)


# ── Session bootstrap ───────────────────────────────────────────────────────
if "sess" not in st.session_state:
    st.session_state.sess = StudioSession()
sess: StudioSession = st.session_state.sess


def _reset_results():
    sess.merchants = []
    sess.changes = []
    sess.crosscheck_done = False
    sess.qrcheck_done = False
    sess.output_path = None


# ── Sidebar: setup panel ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
<div style="padding:8px 0 24px 0;">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
    <svg width="36" height="36" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="10" width="88" height="86" rx="18" ry="18" fill="#ff385c"/>
      <rect x="64" y="4" width="24" height="20" rx="7" ry="7" fill="#ff385c"/>
      <path d="M54 26 A24 24 0 1 0 54 74 L47 65 A13 13 0 1 1 47 35 Z" fill="white"/>
      <circle cx="65" cy="38" r="8.5" fill="white"/>
      <circle cx="65" cy="61" r="7" fill="white"/>
    </svg>
    <div>
      <div style="font-size:11px;font-weight:700;letter-spacing:0.32px;text-transform:uppercase;color:#929292;line-height:1;">VVIP Tools</div>
      <div style="font-size:18px;font-weight:700;color:#222222;line-height:1.3;margin-top:2px;">Catalogue Studio</div>
    </div>
  </div>
  <div style="font-size:11px;color:#929292;font-style:italic;margin-top:8px;">An Owin × Claude Code experiment</div>
</div>
""", unsafe_allow_html=True)

    st.markdown('<div style="font-size:11px;font-weight:700;letter-spacing:0.32px;text-transform:uppercase;color:#929292;margin-bottom:8px;">1 — Upload Files</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader("Catalogue PDF", type=["pdf"])
    new_pdf = None
    if uploaded:
        import tempfile, os
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="studio_upload_")
        os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(uploaded.read())
        new_pdf = tmp_path
    if new_pdf and new_pdf != sess.catalogue_path:
        sess.catalogue_path = new_pdf
        _reset_results()

    master_up = st.file_uploader("VVIP Master Sheet", type=["xlsx", "csv"])
    new_master = None
    if master_up:
        import tempfile, os
        ext = Path(master_up.name).suffix.lower()
        fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="studio_master_")
        os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(master_up.read())
        new_master = tmp_path
    if new_master != sess.master_path:
        sess.master_path = new_master
        if sess.crosscheck_done:
            _reset_results()

    st.markdown('<div style="font-size:11px;font-weight:700;letter-spacing:0.32px;text-transform:uppercase;color:#929292;margin:20px 0 8px 0;">2 — Select Category</div>', unsafe_allow_html=True)

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

    # Status summary
    def _status_dot(ok: bool) -> str:
        return "🟢" if ok else "⚪"

    st.markdown(f"""
<div style="font-size:12px;color:#6a6a6a;line-height:2;">
  {_status_dot(bool(sess.catalogue_path))} Catalogue PDF<br>
  {_status_dot(bool(sess.master_path))} Master Sheet<br>
  {_status_dot(bool(sess.category))} Category selected<br>
  {_status_dot(sess.crosscheck_done)} Cross-check done<br>
  {_status_dot(sess.qrcheck_done)} QR check done
</div>
""", unsafe_allow_html=True)

# ── Main workspace ──────────────────────────────────────────────────────────
ready = bool(sess.catalogue_path and sess.master_path)

if not ready:
    st.markdown("""
<div style="text-align:center;padding:80px 40px;">
  <div style="font-size:48px;margin-bottom:16px;">🗂️</div>
  <div style="font-size:22px;font-weight:600;color:#222222;margin-bottom:8px;">Ready to get started</div>
  <div style="font-size:15px;color:#6a6a6a;max-width:400px;margin:0 auto;">
    Upload your catalogue PDF and VVIP master sheet in the sidebar to unlock the tools below.
  </div>
</div>
""", unsafe_allow_html=True)
    st.markdown("""
    <style>[data-testid="stTabs"] { opacity: 0.45; pointer-events: none; user-select: none; }</style>
    """, unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["① Cross-check", "② QR Check", "③ Generate"])


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
# TAB 1 — CROSS-CHECK
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown("### VVIP Cross-check")
    st.caption("Is each merchant in the catalogue, and are they still a VVIP?")

    if not ready:
        pass
    elif st.button("▶ Run cross-check", type="primary", key="run_cc"):
        prog = st.progress(0.0, text="Starting cross-check…")
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
            st.error("Cross-check failed.")
            with st.expander("Trace", expanded=True):
                import re as _re; st.text(_re.sub(r'File "/.+?/([^/"]+\.py)"', r'File "\1"', err or ""))
        else:
            prog.progress(1.0, text="Cross-check complete ✓")
            import time as _t; _t.sleep(0.5); prog.empty()

    if sess.crosscheck_done:
        s = crosscheck_summary(sess)
        m = st.columns(5)
        m[0].metric("In catalogue", s["in_catalogue"])
        m[1].metric("VVIPs in sheet", s["vvip_total"])
        m[2].metric("✅ Keep", s["keep"])
        m[3].metric("➖ Remove", s["remove"], delta=f"-{s['remove']}",
                    delta_color="inverse")
        m[4].metric("➕ Add", s["add"], delta=f"+{s['add']}")

        _BADGE = {CC_KEEP: "✅ keep", CC_REMOVE: "➖ remove", CC_ADD: "➕ add"}
        rows = [{
            "Handle": x.handle,
            "Merchant": x.display_name or "—",
            "In catalogue": "✓" if x.in_catalogue else "",
            "VVIP": "✓" if x.is_vvip else "",
            "Action": _BADGE.get(x.cc_status, x.cc_status),
            "Pg": str(x.page) if x.page else "",
        } for x in sorted(sess.merchants, key=lambda r: (r.cc_status, r.handle))]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     height=561)

        st.markdown("##### Proposed changes — approve to apply")
        cc_changes = [c for c in sess.changes if c.source == "crosscheck"]
        approval_editor(cc_changes, key="cc_appr")
    else:
        pass


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — QR CHECK
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown("### QR Code Check")
    st.caption("Decode every QR, confirm it's live, and that it lands on the printed merchant — not a renamed or blank shell.")

    if not ready:
        pass
    elif not sess.crosscheck_done:
        pass
    else:
        do_live = st.toggle("Live verification (open each link in a browser)",
                            value=True)
        if st.button("▶ Run QR check", type="primary", key="run_qr"):
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
                                  text=f"Verified {payload['i']}/{payload['n']} — "
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
                prog.progress(1.0, text="QR check complete ✅")

        if sess.qrcheck_done:
            from collections import Counter
            cards = sess.in_catalogue()
            counts = Counter(c.qr_status for c in cards)
            m = st.columns(6)
            m[0].metric("✅ OK", counts.get(QR_OK, 0))
            m[1].metric("🔀 Mismatch", counts.get(QR_MISMATCH, 0))
            m[2].metric("📛 Renamed", counts.get(QR_RENAMED, 0))
            m[3].metric("💀 Dead", counts.get(QR_DEAD, 0))
            m[4].metric("👻 Soft-404", counts.get(QR_SOFT404, 0))
            m[5].metric("⬜ No QR", counts.get(QR_NONE, 0))

            _QB = {QR_OK: "✅ ok", QR_MISMATCH: "🔀 mismatch", QR_RENAMED: "📛 renamed",
                   QR_DEAD: "💀 dead", QR_SOFT404: "👻 soft-404", QR_NONE: "⬜ no-qr",
                   QR_UNKNOWN: "·"}
            rows = [{
                "Handle": x.handle,
                "Printed": x.at,
                "QR lands on": f"@{x.resolves_to}" if x.resolves_to else "—",
                "Status": _QB.get(x.qr_status, x.qr_status),
                "Detail": (x.qr_detail or "")[:60],
                "Pg": str(x.page) if x.page else "",
            } for x in sorted(cards, key=lambda r: (r.qr_ok, r.handle))]
            st.dataframe(pd.DataFrame(rows), hide_index=True,
                         use_container_width=True, height=561)

            st.markdown("##### Broken QRs — approve to regenerate")
            qr_changes = [c for c in sess.changes if c.source == "qrcheck"]
            approval_editor(qr_changes, key="qr_appr")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — GENERATE
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
        m[1].metric("➕ Adding", plan["added"])
        m[2].metric("➖ Removing", plan["removed"])
        m[3].metric("🔧 QR fixes", plan["qr_fixes"])

        st.caption("Generation rebuilds every card fresh (profile, description, "
                   "and a brand-new QR from the canonical URL) — so every broken "
                   "QR is corrected by construction.")

        have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        do_describe = st.toggle(
            "Write AI descriptions (needs ANTHROPIC_API_KEY)",
            value=have_key, disabled=not have_key,
            help=None if have_key else "Set ANTHROPIC_API_KEY in your shell to enable.")
        if not have_key:
            st.caption("⚠ No API key found — cards will use a generic description.")

        import re as _re
        _stem = _re.sub(r"[^a-zA-Z0-9._-]", "_", Path(sess.catalogue_path).stem)[:80]
        default_out = f"/tmp/{_stem}_corrected.pdf"
        out_path = st.text_input("Output path", value=sess.output_path or default_out)

        if st.button("▶ Generate catalogue", type="primary", key="run_gen"):
            # Validate output path: must be absolute and within /tmp or home dir
            _out = Path(out_path).resolve()
            _allowed = (Path("/tmp"), Path.home())
            if not any(str(_out).startswith(str(p)) for p in _allowed):
                st.error("Output path must be within /tmp or your home directory.")
                st.stop()
            sess.output_path = str(_out)
            prog = st.progress(0.0, text="Building…")
            result = None
            err = None

            def _stage(emit):
                def cb(i, n, handle, name):
                    emit({"i": i, "n": n, "handle": handle, "status": name})
                return generate(sess, do_describe=do_describe, progress_cb=cb)

            for kind, payload in threaded_stage(_stage):
                if kind == "progress":
                    prog.progress(payload["i"] / max(payload["n"], 1),
                                  text=f"[{payload['i']}/{payload['n']}] "
                                       f"@{payload['handle']} — {payload['status']}")
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
                prog.progress(1.0, text="Done ✅")
                st.success(f"Built {result['built']} cards → {result['output']}")
                if result["skipped"]:
                    st.warning("Skipped (profile not found): " +
                               ", ".join("@" + h for h in result["skipped"]))
                out = Path(result["output"])
                if out.exists():
                    with open(out, "rb") as f:
                        st.download_button("📥 Download corrected PDF", f.read(),
                                           file_name=out.name,
                                           mime="application/pdf",
                                           use_container_width=True)
                    # preview first page
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
