# VVIP Catalogue Studio

One app, three features, for maintaining Carousell VVIP merchant e-catalogues.

## Setup

Requires Python 3.10+.

```bash
git clone https://github.com/<your-username>/vvip-catalogue-studio.git
cd vvip-catalogue-studio
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # one-time, for QR live-verify + profile fetch
streamlit run app.py
```

This opens the app in your browser at `http://localhost:8501`, running
entirely on your own machine — uploaded PDFs and sheets never leave your
computer.

Optional — AI-written merchant descriptions. Without any config, cards use a
generic description. To enable AI descriptions, point the app at any
OpenAI-compatible provider via env vars (pick a free one):

```bash
# Ollama Cloud (free tier) — key from ollama.com
export AI_BASE_URL=https://ollama.com/v1
export AI_API_KEY=<your-ollama-key>
export AI_MODEL=gpt-oss:120b

# …or local Ollama (free, offline — run `ollama serve` and `ollama pull llama3.2`)
export AI_BASE_URL=http://localhost:11434/v1
export AI_MODEL=llama3.2            # no key needed

# …or Google Gemini (free tier) — key from aistudio.google.com/app/apikey
export AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
export AI_API_KEY=<your-gemini-key>
export AI_MODEL=gemini-1.5-flash
```

Load a **catalogue PDF** + the **VVIP master sheet**, then work through three tabs.

## The three features

1. **Cross-check** — for every merchant, is it *in the catalogue* and is it *still a
   VVIP* (in the sheet)?
   - in + VVIP → **keep**
   - in + not VVIP → **remove** (dropped from VVIP)
   - VVIP + not in → **add** (missing VVIP)
   - Handle matching is fuzzy (the sheet stores business names that get derived to
     stems like `revology`; the catalogue shows `revologybikes` — a prefix match
     bridges them).

2. **QR check** — decode every QR and prove it is trustworthy:
   - decodes to the **printed handle** (else *mismatch*)
   - resolves to a **live profile** (else *dead*)
   - lands on the **right merchant**, not a renamed account (*renamed*) or a blank
     shell that loads but isn't the profile (*soft-404*)
   - missing QR → *no-qr*

3. **Generate** — apply the **approved** changes and render the corrected next
   edition: `final = in-catalogue VVIPs − approved removals + approved additions`.
   Every card is rebuilt fresh (profile, description, and a brand-new QR from the
   canonical URL), so every broken QR is fixed by construction. Dead profiles are
   skipped and reported.

Changes from Features 1 & 2 are **proposed**, you **approve** them (checkboxes), and
only then does Generate **apply** them.

## Architecture

```
app.py                 Streamlit UI — 3 tabs, session-state driven
studio/
  sources.py           single wiring point to the two engine packages (lazy
                       imports for the heavy native/browser entry points)
  state.py             StudioSession, MerchantRecord, ProposedChange
  crosscheck.py        Feature 1  (extract + master diff)            — in-process
  qr.py                Feature 2  (decode-match + live + soft-404)   — threaded
  generate.py          Feature 3  (apply approved changes + render)  — threaded
  runner.py            run a Playwright stage on a background thread
```

Engines reused as-is (vendored at the repo root, not external packages):
- **qrcheck/** — PDF extraction, master ingest, live verify
- **catbuilder/** — profile fetch, describe, QR gen, PDF render

The Playwright-backed stages (live QR check, profile fetch) run on a **background
thread** inside the Streamlit process — sync Playwright can't `start()` on a thread
that already has a running asyncio loop, so a fresh thread sidesteps it. No
subprocess required.

## Notes / environment

- **AI descriptions** need an OpenAI-compatible provider configured via
  `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` (see the free options above); without
  it, cards get a generic description (toggle is disabled).
- **macOS sandbox**: if launched in a restricted sandbox, files under `~/Downloads`
  and `~/Library/CloudStorage` may be unreadable. The app prefers
  `/tmp/qrcheck_master.xlsx` and `/tmp/qrcheck_archive/*.pdf`; stage copies there if
  needed.
- The master sheet stores business *names*, so the **add** list can contain noisy
  derived handles — review and uncheck junk before generating (dead ones are skipped
  anyway).
- Profile/avatar/QR assets are cached under `/tmp/catbuilder_cache` (shared with
  catbuilder).
