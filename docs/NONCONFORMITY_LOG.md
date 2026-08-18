# Nonconformity & corrective-action log

Record of defects and audit findings, their root cause, and the corrective
action taken (ISO 9001 clause 10.2). The aim is to fix causes, not just
symptoms, and to see patterns over time. Add a row whenever a nonconformity is
found — from the ISO self-audit, a bug report, or a failed CI run.

Status: **Open** · **Fixed** · **Monitoring**

## From the ISO 9001 internal audit (18 Aug 2026)

| ID | Clause | Finding | Root cause | Corrective action | Status |
|----|--------|---------|------------|-------------------|--------|
| NC-01 | 8.6 | No verification that the product meets requirements before release | No test suite or CI ever set up | Added `tests/` (50 tests) over the critical paths + GitHub Actions CI gate on push/PR | Fixed |
| NC-02 | 8.2 | Product requirements not recorded or reviewed | Requirements lived only in chat / commits | Added [REQUIREMENTS.md](REQUIREMENTS.md) with acceptance criteria traced to tests | Fixed |
| NC-03 | 7.5.3 | No controlled release identifier | Version hard-coded as a footer string | Single-sourced `studio.__version__`; footer derives its label from it | Fixed |
| NC-04 | 8.4 | Dependencies not pinned to a reproducible baseline | Only floor pins (`>=`) in requirements.txt | Added `requirements.lock` (fully pinned snapshot) | Fixed |
| NC-05 | 8.7 / 9.1 | Broad exception handling with no logging could mask nonconforming outputs | No logging; silent `except … : pass` | Added module logging; recorded the silent-swallow points in `describer.py`; documented the pattern in QUALITY.md | Fixed |
| NC-06 | 6.1 / 8.5.1 | SSRF allowlist duplicated and hand-synced across two files | Copy kept "in sync" by a comment, not by code | Extracted to `studio/ssrf.py`; single definition imported by callers; dead `qr_worker.py` retired | Fixed |
| OBS-01 | 5.2 / 6.2 | No quality policy or measurable objectives | Not documented | Added policy + 4 measurable objectives in [QUALITY.md](QUALITY.md) | Fixed |
| OBS-02 | 7.5.3 | No repository licence | Not added | Added proprietary `LICENSE` (all rights reserved) | Fixed |
| OBS-03 | 10.2 | Defects corrected but not logged | No log existed | This document | Fixed |

## Ongoing defect log

New defects go here. Example row kept as a template — replace with real entries.

| ID | Date | Clause | Defect | Root cause | Corrective action | Status |
|----|------|--------|--------|------------|-------------------|--------|
| D-001 | 2026-08-18 | 7.1.3 | AI toggle stayed disabled although `~/.zshrc` had the key | The `sh -c` launcher never sources `~/.zshrc`, so shell exports didn't reach the process | Load a gitignored `.env` at startup (`studio/env.py`); pinned with `tests/test_env.py` so it can't regress | Fixed |
