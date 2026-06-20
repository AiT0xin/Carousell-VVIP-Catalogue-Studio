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

# ── Carousell design language ────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Brand colours ── */
:root {
  --red:    #EE3422;
  --red-dk: #C4200F;
  --blue:   #1A56DB;
  --grey:   #F4F5F7;
  --border: #E5E7EB;
  --text:   #111827;
  --muted:  #6B7280;
}

/* ── Global font & background — kill dark-theme root ── */
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > section,
[data-testid="stAppViewContainer"] > section > div {
  font-family: "Inter", "Helvetica Neue", Arial, sans-serif !important;
  background-color: #F8F9FA !important;
  color: var(--text) !important;
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
  color: var(--text) !important;
}

/* Re-whiten the hero banner (more specific → wins) */
.carousell-hero h1,
.carousell-hero p,
.carousell-hero span:not(.carousell-logo) {
  color: #fff !important;
}
.carousell-logo {
  color: var(--red) !important;
  background: #fff !important;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, [data-testid="stDecoration"] { display: none !important; }

/* ── Page header banner (red hero strip) ── */
[data-testid="stAppViewContainer"] > section > div:first-child {
  padding-top: 0 !important;
}

/* ── Title & caption (inside the red banner) ── */
[data-testid="stAppViewContainer"] h1 {
  font-size: 2rem !important;
  font-weight: 800 !important;
  letter-spacing: -0.02em !important;
  color: var(--text) !important;
}

/* ── Subheaders ── */
h2, h3, [data-testid="stMarkdownContainer"] h3 {
  font-weight: 700 !important;
  color: var(--text) !important;
}

/* ── Tabs: Carousell pill style ── */
[data-testid="stTabs"] [role="tablist"] {
  gap: 4px;
  border-bottom: 2px solid var(--border) !important;
  padding-bottom: 0;
}
[data-testid="stTabs"] [role="tab"] {
  font-weight: 600 !important;
  font-size: 0.9rem !important;
  padding: 10px 20px !important;
  border-radius: 8px 8px 0 0 !important;
  color: var(--muted) !important;
  background: transparent !important;
  border: none !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--red) !important;
  border-bottom: 3px solid var(--red) !important;
  background: transparent !important;
}

/* ── Primary buttons → Carousell red ── */
[data-testid="stButton"] button[kind="primary"],
button[data-testid="baseButton-primary"] {
  background: var(--red) !important;
  color: #fff !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 700 !important;
  font-size: 0.9rem !important;
  padding: 10px 24px !important;
  transition: background 0.15s ease, transform 0.1s ease !important;
  box-shadow: 0 2px 6px rgba(238,52,34,0.25) !important;
}
[data-testid="stButton"] button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover {
  background: var(--red-dk) !important;
  transform: translateY(-1px) !important;
}

/* ── Secondary/default buttons ── */
[data-testid="stButton"] button[kind="secondary"],
button[data-testid="baseButton-secondary"] {
  border: 2px solid var(--red) !important;
  color: var(--red) !important;
  background: #fff !important;
  border-radius: 8px !important;
  font-weight: 600 !important;
}

/* ── Download button ── */
[data-testid="stDownloadButton"] button {
  background: var(--red) !important;
  color: #fff !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 700 !important;
  box-shadow: 0 2px 6px rgba(238,52,34,0.25) !important;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
  background: #fff !important;
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
  padding: 16px 20px !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
}
[data-testid="stMetricLabel"] {
  font-size: 0.75rem !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.05em !important;
  color: var(--muted) !important;
}
[data-testid="stMetricValue"] {
  font-size: 1.75rem !important;
  font-weight: 800 !important;
  color: var(--text) !important;
}

/* ── Container / card borders ── */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] > div {
  border-radius: 16px !important;
  border: 1px solid var(--border) !important;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
  background: #fff !important;
  padding: 20px !important;
}

/* ── Info / success / warning banners ── */
[data-testid="stAlert"][data-baseweb="notification"][aria-label="Info"] {
  border-left: 4px solid var(--blue) !important;
  border-radius: 10px !important;
  background: #EFF6FF !important;
}
[data-testid="stAlert"][data-baseweb="notification"][aria-label="Success"] {
  border-left: 4px solid #16A34A !important;
  border-radius: 10px !important;
  background: #F0FDF4 !important;
}

/* ── Cream palette for all form controls ── */

/* Text inputs */
[data-testid="stTextInput"] input {
  background: #FFFBF8 !important;
  color: var(--text) !important;
  border-radius: 8px !important;
  border: 1.5px solid #F0E8E4 !important;
  font-size: 0.9rem !important;
}
[data-testid="stTextInput"] input:focus {
  border-color: var(--red) !important;
  box-shadow: 0 0 0 3px rgba(238,52,34,0.10) !important;
}

/* Selectbox — all layers need explicit light colours */
[data-testid="stSelectbox"] > div > div,
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stSelectbox"] [data-baseweb="select"] div {
  background: #FFFBF8 !important;
  border-color: #F0E8E4 !important;
  color: var(--text) !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
  border: 1.5px solid #F0E8E4 !important;
  border-radius: 8px !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within {
  border-color: var(--red) !important;
  box-shadow: 0 0 0 3px rgba(238,52,34,0.10) !important;
}
/* The actual selected value text and placeholder */
[data-testid="stSelectbox"] [data-baseweb="select"] span,
[data-testid="stSelectbox"] [data-baseweb="select"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="placeholder"],
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="singleValue"],
[data-testid="stSelectbox"] [data-baseweb="select"] [class*="value"] {
  color: var(--text) !important;
}
/* Dropdown arrow icon */
[data-testid="stSelectbox"] [data-baseweb="select"] svg {
  fill: var(--muted) !important;
}
/* Dropdown popover — hardcoded colours, no CSS vars (portal is outside :root scope) */
[data-baseweb="popover"],
[data-baseweb="popover"] > div,
[data-baseweb="menu"],
[data-baseweb="menu"] ul {
  background: #FFFBF8 !important;
  border: 1px solid #F0E8E4 !important;
  border-radius: 10px !important;
}
[data-baseweb="menu"] li,
[data-baseweb="option"],
[role="option"],
[role="listbox"] > * {
  background: #FFFBF8 !important;
  color: #111827 !important;
}
[data-baseweb="option"] *,
[role="option"] * {
  color: #111827 !important;
}
[data-baseweb="option"]:hover,
[role="option"]:hover,
[data-baseweb="option"]:hover * {
  background: #FFF0ED !important;
  color: #111827 !important;
}
[data-baseweb="option"][aria-selected="true"],
[role="option"][aria-selected="true"] {
  background: #FFE8E5 !important;
  color: #EE3422 !important;
}
[data-baseweb="option"][aria-selected="true"] *,
[role="option"][aria-selected="true"] * {
  color: #EE3422 !important;
}

/* File uploader — kill the dark outer shell first */
[data-testid="stFileUploader"] > section,
[data-testid="stFileUploader"] > div,
[data-testid="stFileUploaderDropzone"] {
  background: #FFF8F5 !important;
  border-radius: 12px !important;
}

/* Drop zone itself */
[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed #F4C5BD !important;
  color: var(--text) !important;
}
[data-testid="stFileUploaderDropzone"]:hover {
  background: #FFF0ED !important;
  border-color: var(--red) !important;
}

/* Instructions text inside uploader */
[data-testid="stFileUploaderDropzoneInstructions"] {
  background: transparent !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small {
  color: var(--muted) !important;
}

/* Browse files button inside uploader */
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzoneInstructions"] button {
  background: #FFF0ED !important;
  color: var(--red) !important;
  border: 1.5px solid #F4C5BD !important;
  border-radius: 6px !important;
  font-weight: 600 !important;
}

/* Checkbox */
[data-testid="stCheckbox"] label > div {
  background: #FFFBF8 !important;
  border-color: #F0E8E4 !important;
}

/* Number/text area inputs */
textarea {
  background: #FFFBF8 !important;
  color: var(--text) !important;
  border: 1.5px solid #F0E8E4 !important;
  border-radius: 8px !important;
}

/* ── Toggle ── */
[data-testid="stToggle"] > label > div[data-checked="true"] {
  background: var(--red) !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
  border-radius: 12px !important;
  overflow: hidden !important;
  border: 1px solid var(--border) !important;
}

/* ── Progress bar ── */
[data-testid="stProgressBar"] > div > div {
  background: var(--red) !important;
}

/* ── Sidebar (if any) ── */
[data-testid="stSidebar"] {
  background: #fff !important;
  border-right: 1px solid var(--border) !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
  background: #FFFBF8 !important;
  border: 1px solid #F0E8E4 !important;
  border-radius: 10px !important;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary * {
  color: #111827 !important;
  background: #FFFBF8 !important;
}
[data-testid="stExpander"] > div {
  background: #FFFBF8 !important;
}

/* ── Code blocks ── */
[data-testid="stCode"],
[data-testid="stCode"] > div,
[data-testid="stCode"] pre,
.stCode, pre {
  background: #FFF5F3 !important;
  border: 1px solid #F0E8E4 !important;
  border-radius: 8px !important;
  color: #111827 !important;
}
[data-testid="stCode"] code,
[data-testid="stCode"] span,
pre code, pre span {
  color: #C4200F !important;
  background: transparent !important;
}

/* ── Custom hero banner ── */
.carousell-hero {
  background: linear-gradient(135deg, var(--red) 0%, #C4200F 100%);
  border-radius: 16px;
  padding: 32px 36px;
  margin-bottom: 24px;
  color: white;
}
.carousell-hero h1 {
  color: white !important;
  font-size: 2.3rem !important;
  font-weight: 800 !important;
  margin: 0 0 8px 0 !important;
}
.carousell-hero p {
  color: rgba(255,255,255,0.85) !important;
  font-size: 1.1rem !important;
  margin: 0 !important;
}
.carousell-hero-inner {
  display: flex;
  align-items: center;
  gap: 22px;
}
.carousell-logo-icon {
  flex-shrink: 0;
  width: 64px;
  height: 64px;
}
.carousell-hero-text { flex: 1; }
.carousell-experiment {
  margin-top: 8px !important;
  font-size: 0.82em !important;
  font-style: italic !important;
  color: #ff9999 !important;
  font-weight: 600 !important;
  opacity: 0.9 !important;
}
@keyframes rainbow { 0%{background-position:0%} 100%{background-position:300%} }

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

/* ── Data editor: fix white text on selected cells ── */
[data-testid="stDataEditor"] .dvn-scroller .rdg-cell[aria-selected="true"],
[data-testid="stDataEditor"] .rdg-cell:focus,
[data-testid="stDataEditor"] .rdg-row:hover .rdg-cell {
  color: #111827 !important;
}
[data-testid="stDataEditor"] .rdg-cell[aria-selected="true"] {
  background: rgba(211, 28, 12, 0.08) !important;
  color: #111827 !important;
  outline: 2px solid #D91C0C !important;
}
[data-testid="stDataEditor"] input,
[data-testid="stDataEditor"] textarea {
  color: #111827 !important;
  background: white !important;
}

/* ── Progress bars ── */
[data-baseweb="progress-bar"] > div > div {
  background: rgba(0,0,0,0.08) !important;
  border-radius: 6px !important;
  height: 10px !important;
}
[data-baseweb="progress-bar"] > div > div > div {
  background: linear-gradient(90deg, #D91C0C, #ff6b6b) !important;
  border-radius: 6px !important;
  transition: width 0.4s ease !important;
}

/* ── File upload success indicator ── */
[data-testid="stFileUploaderFileName"]::after {
  content: " ✓";
  color: #22c55e;
  font-weight: 700;
  font-size: 1em;
}

/* ── Greyed tabs when not ready ── */
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


# ── Header + setup ──────────────────────────────────────────────────────────
st.markdown("""
<div class="carousell-hero">
  <div class="carousell-hero-inner">
    <svg class="carousell-logo-icon" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
      <!-- Rounded square body (black) -->
      <rect x="4" y="10" width="88" height="86" rx="18" ry="18" fill="black"/>
      <!-- Small bump top-right -->
      <rect x="64" y="4" width="24" height="20" rx="7" ry="7" fill="black"/>
      <!-- C shape in white -->
      <path d="M54 26 A24 24 0 1 0 54 74 L47 65 A13 13 0 1 1 47 35 Z" fill="white"/>
      <!-- Two dots in white -->
      <circle cx="65" cy="38" r="8.5" fill="white"/>
      <circle cx="65" cy="61" r="7" fill="white"/>
    </svg>
    <div class="carousell-hero-text">
      <h1>VVIP Catalogue Studio <span style="font-size:0.42em;font-weight:600;background:rgba(255,255,255,0.18);border:1px solid rgba(255,255,255,0.4);border-radius:6px;padding:3px 10px;vertical-align:middle;letter-spacing:0.05em;">BETA</span></h1>
      <p>Cross-check VVIPs &nbsp;·&nbsp; verify QR codes &nbsp;·&nbsp; generate the corrected catalogue <span style="font-size:0.6em;font-weight:500;opacity:0.8;">(beta)</span></p>
      <p class="carousell-experiment">An Owin &times; Claude Code experiment</p>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

with st.container(border=True):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 📄 Catalogue PDF")
        uploaded = st.file_uploader("Upload catalogue", type=["pdf"],
                                    label_visibility="collapsed")
        new_pdf = None
        if uploaded:
            tmp = Path("/tmp/studio_upload.pdf")
            tmp.write_bytes(uploaded.read())
            new_pdf = str(tmp)
        if new_pdf and new_pdf != sess.catalogue_path:
            sess.catalogue_path = new_pdf
            _reset_results()
        if sess.catalogue_path:
            st.caption(f"📄 {Path(sess.catalogue_path).name}")

    with c2:
        st.markdown("##### 📊 VVIP Master")
        master_up = st.file_uploader("Upload master xlsx or csv", type=["xlsx", "csv"],
                                     label_visibility="collapsed")
        new_master = None
        if master_up:
            ext = Path(master_up.name).suffix.lower()
            tmp = Path(f"/tmp/studio_master{ext}")
            tmp.write_bytes(master_up.read())
            new_master = str(tmp)
        if new_master != sess.master_path:
            sess.master_path = new_master
            if sess.crosscheck_done:
                _reset_results()
        if sess.master_path:
            st.caption(f"📊 {Path(sess.master_path).name}")
        _CATEGORIES = ["Autos", "Services", "Luxury", "Goods"]
        _CAT_OPTIONS = ["Select Category"] + _CATEGORIES
        # Default to index 0 (Select Category); if sess.category is set, find it in _CATEGORIES and add 1 for the placeholder
        current_idx = 0
        if sess.category in _CATEGORIES:
            current_idx = _CATEGORIES.index(sess.category) + 1
        cat = st.selectbox(
            "Category (sheet)",
            _CAT_OPTIONS,
            index=current_idx,
        )
        if cat != "Select Category" and cat != sess.category:
            sess.category = cat
        elif cat == "Select Category":
            sess.category = ""

# --- TEMP DEMO AUTOLOAD (revert after screenshots) ---
if Path("/tmp/studio_demo_autoload").exists():
    if not sess.catalogue_path and Path("/tmp/studio_upload.pdf").exists():
        sess.catalogue_path = "/tmp/studio_upload.pdf"
    if not sess.master_path and Path("/tmp/studio_master.xlsx").exists():
        sess.master_path = "/tmp/studio_master.xlsx"
# --- END TEMP DEMO AUTOLOAD ---

ready = bool(sess.catalogue_path and sess.master_path)
if not ready:
    st.info("Load a catalogue PDF and the VVIP master sheet above to get started.")
    st.markdown("""
    <style>
    [data-testid="stTabs"] { opacity: 0.45; pointer-events: none; user-select: none; }
    </style>
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
                st.text(err)
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
                    st.text(err or "(no traceback captured)")
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

        default_out = f"/tmp/{Path(sess.catalogue_path).stem}_corrected.pdf"
        out_path = st.text_input("Output path", value=sess.output_path or default_out)

        if st.button("▶ Generate catalogue", type="primary", key="run_gen"):
            sess.output_path = out_path
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
                st.error("Generation failed.")
                with st.expander("Trace"):
                    st.code(err)
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
