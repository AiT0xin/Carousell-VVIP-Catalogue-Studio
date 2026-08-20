# Requirements register

The product requirements for VVIP Catalogue Studio, each with acceptance
criteria and the verification that covers it (ISO 9001 clause 8.2 — determining
and reviewing requirements; clause 8.3 — design traceability). "Verified by"
names an automated test where one exists, or "manual / integration" where the
step needs a real PDF, browser, or network and is checked by hand.

Update this register when behavior changes, and add or adjust the covering test
in the same change.

## Functional requirements

### FR-1 Cross-check (catalogue vs VVIP master)

| ID | Requirement | Acceptance criteria | Verified by |
|----|-------------|---------------------|-------------|
| FR-1.1 | Identify every merchant present in the catalogue PDF | Each card's printed handle is extracted; CTA-only cards carry no handle | manual / integration (`extract_pdf`) |
| FR-1.2 | Classify each merchant KEEP / REMOVE / ADD | in+vvip → KEEP; in+¬vvip → REMOVE; ¬in+vvip → ADD | `tests/test_crosscheck.py::test_summary_counts` |
| FR-1.3 | Bridge business-name stems to full handles | Prefix match ≥ 5 chars unifies e.g. `acmebrand` ↔ `acmebrandsg` | `tests/test_crosscheck.py::test_prefix_fuzzy_match` |

### FR-2 QR check

| ID | Requirement | Acceptance criteria | Verified by |
|----|-------------|---------------------|-------------|
| FR-2.1 | Decode every QR and pair it to a printed handle | QRs decoded and paired; unpaired handles reported | manual / integration (`extract_pdf`) |
| FR-2.2 | Assign each QR a correct outcome | PASS / DEAD_LINK / RENAMED_HANDLE / HANDLE_TYPO / MISMATCH / CTA_OK / NOT_IN_MASTER / DECODE_FAIL per the documented rules | `tests/test_verdict.py` (11 cases) |
| FR-2.3 | **Never fetch a non-Carousell URL during live verify** | Every fetch, including each redirect hop, passes `is_verifiable_url`; lookalikes, internal IPs, cloud metadata, and non-http schemes are rejected | `tests/test_ssrf.py` (6 cases) |
| FR-2.4 | Classification and URL handling are correct | Handle/URL normalization, CTA/shortlink/profile classification | `tests/test_normalize.py` (8 cases) |

### FR-3 Generate corrected catalogue

| ID | Requirement | Acceptance criteria | Verified by |
|----|-------------|---------------------|-------------|
| FR-3.1 | Rebuild each card fresh (profile, description, new QR from canonical URL) | Every broken QR is corrected by construction | manual / integration (`render_pdf`) |
| FR-3.2 | AI descriptions are optional and off unless a provider is configured | Toggle disabled with no `AI_API_KEY` / explicit local base; cards use a generic description | `tests/test_describer.py::test_ai_*` |
| FR-3.3 | AI generation fails over from primary to fallback model | On error / empty output, retry `AI_FALLBACK_MODEL`; only raise if all fail | manual / integration (failover run) |
| FR-3.4 | Master ingest tolerates messy, multi-sheet, mixed-content input | Handles harvested from names, slash-separated cells, corporate suffixes; banner rows skipped | `tests/test_ingest.py` (6 cases) |
| FR-3.5 | Category → colour mapping is stable | Known categories map to fixed hex; unknown → default | `tests/test_models.py::test_colour_for_category_known_and_default` |

## Non-functional requirements

| ID | Requirement | Acceptance criteria | Verified by |
|----|-------------|---------------------|-------------|
| NFR-1 | Runs locally; uploaded PDFs / sheets never leave the machine | No upload of user files to third parties | design review (README) |
| NFR-2 | Configuration via env vars / `.env`; secrets never committed | `.env` gitignored; real env vars override the file | `tests/test_env.py` + security audit |
| NFR-3 | Reproducible environment | `requirements.lock` pins the verified set | `requirements.lock` present |
| NFR-4 | Every change is verified before release | CI runs `pytest` on push / PR to `main` | `.github/workflows/ci.yml` |
