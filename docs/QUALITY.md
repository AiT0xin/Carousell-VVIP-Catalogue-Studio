# Quality Management — VVIP Catalogue Studio

This document is the project's lightweight Quality Management System (QMS),
mapping the relevant ISO 9001:2015 clauses onto how this codebase is actually
built and released. It is deliberately proportionate to a single-maintainer
tool — the goal is real assurance, not paperwork.

Related records:
- [REQUIREMENTS.md](REQUIREMENTS.md) — what the product must do + how each item is verified (clause 8.2 / 8.3)
- [NONCONFORMITY_LOG.md](NONCONFORMITY_LOG.md) — defects, audit findings, and their disposition (clause 10.2)

## Quality policy (clause 5.2)

VVIP Catalogue Studio exists to make Carousell VVIP e-catalogues **correct and
trustworthy** — every merchant that should be in is in, every QR resolves to the
right live profile, and nothing is shipped that hasn't been verified. Quality is
maintained by keeping the verification automatic (not dependent on the
maintainer remembering), keeping the code documented, and recording defects so
causes — not just symptoms — get fixed.

## Quality objectives (clause 6.2)

Measurable, reviewed whenever the audit is re-run:

| ID   | Objective | Target | How it's measured |
|------|-----------|--------|-------------------|
| QO-1 | Every change on `main` passes the automated test suite before it's considered released | 100% of pushes green | GitHub Actions CI (`.github/workflows/ci.yml`) |
| QO-2 | A generated catalogue contains no broken QR codes | 0 broken | QRs are rebuilt from the canonical profile URL by construction; QR check flags any survivor |
| QO-3 | No secrets committed to the repository | 0 | `.gitignore` covers `.env`; verified in the security audit |
| QO-4 | Every pure-logic module has at least one characterization test | 100% of listed modules | `tests/` coverage of ssrf, normalize, verdict, ingest, models, crosscheck, describer, env |

## Process approach (clause 4.4)

The product is a three-stage pipeline, mirrored by the package layout:

1. **Cross-check** (`studio/crosscheck.py`) — catalogue vs master → add / remove
2. **QR check** (`studio/qr.py`, `qrcheck/`) — every QR decodes, is live, lands right
3. **Generate** (`studio/generate.py`, `catbuilder/`) — apply approved changes → corrected PDF

`studio/sources.py` is the single wiring point to the two engine packages.

## Operation & release control (clause 8.5 / 8.6)

- **Verification before release:** `pytest` runs on every push and pull request
  via CI. A red suite blocks the change. The passing run is the retained
  evidence that acceptance criteria were met.
- **Reproducible baseline:** `requirements.lock` pins the verified dependency
  set; `requirements.txt` is the loose human-edited source of truth.
- **Change control:** all changes go through Git with descriptive messages and a
  remote backup. Version is single-sourced in `studio/__init__.py`.

## Monitoring & nonconforming outputs (clause 8.7 / 9.1)

Failures that would otherwise degrade output silently (an unparseable cached
profile, a web-search miss, a model that errors or returns nothing) are recorded
through Python's `logging` module rather than swallowed, so a bad description or
a skipped merchant can be traced. The SSRF allowlist (`studio/ssrf.py`) is the
one control that actively prevents a nonconforming (and unsafe) output.

## Improvement (clause 10)

Defects and audit findings are recorded in
[NONCONFORMITY_LOG.md](NONCONFORMITY_LOG.md) with their root cause and
corrective action, so recurring issues are addressed at the cause. The ISO 9001
self-audit is the periodic internal review; re-run it after significant change.

## Scope note

ISO 9001 certifies an organization's QMS, not software, and full certification
requires an accredited registrar. This document and the accompanying tests /
records bring the **development lifecycle** into substantial conformance with
the standard's intent; they are a self-assessment aid, not a certificate.
