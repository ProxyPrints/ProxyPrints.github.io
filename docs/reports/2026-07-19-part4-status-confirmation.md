As of: 2026-07-19
Task: Part 4 (LANDS) priority directive — status confirmation against the
re-stated standing spec
Branch/worktree: catalog-completion-part2 (report-only; no code touched)

## Summary

Part 4's build and its HOLD #B volume check are **already complete**,
from earlier in this same session (2026-07-18). This task's re-statement
of the standing spec was checked line-by-line against what was actually
shipped and run; no rebuild or re-run was needed or performed.

## Spec-vs-shipped checklist

| Spec item (as re-stated)                                                 | Shipped                                                                                                                                                                         |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Collector-line OCR uncapped                                              | Step 1 of the pipeline — the existing OCR engine, never capped (unlike phash's `PHASH_MAX_CANDIDATES`)                                                                          |
| Artist-OCR difflib ≥0.8 against each name's own candidates               | `ARTIST_FUZZY_MATCH_THRESHOLD = 0.8`, difflib-based (`local_fallback.match_artist`)                                                                                             |
| phash within the artist-filtered set                                     | Step 3 — matches against already-computed `content_phash`/`image_hash`, no re-fetch                                                                                             |
| Confidence 0.85 = artist narrows to ONE + phash clears standard distance | `LANDS_SINGLETON_CONFIDENCE = 0.85`                                                                                                                                             |
| Confidence 0.8 = phash breaks a multi-candidate tie                      | `LANDS_TIEBREAK_CONFIDENCE = 0.8`                                                                                                                                               |
| Any ambiguity → skip, counted                                            | `ambiguous_phash=48` in the real run — explicitly counted, not silently dropped                                                                                                 |
| =s800 tier for OCR fetches                                               | `OCR_FETCH_DPI = 220` (see note below on the "2.6x" figure)                                                                                                                     |
| phash keeps its canonical tier                                           | Confirmed — phash step never re-fetches at all, so no tier question applies to it                                                                                               |
| Standard rails: run_id, ledger, dry-run default                          | `PilotRunLedger`, `generate_run_id()`, `dry_run=True` default, all reused verbatim from Part 1                                                                                  |
| Volume check: land-pool census                                           | **39,707 cards** (free query, `--fetch-budget 0`)                                                                                                                               |
| Volume check: artist-extraction rate on 300-card sample                  | **18.0%** (54/300, against `fetch_attempted`)                                                                                                                                   |
| Volume check: per-name candidate counts pre/post artist filter           | Both captured in the raw log — pre-filter (e.g. every "Forest" variant: 944 candidates each); post-filter (e.g. `Etali, Primal Storm`: 20, `Winter Orb`: 16, `Ancient Tomb`: 1) |
| Rate ceiling respected                                                   | Yes — same shared image-cdn Worker limiter (~3 req/sec) every other fetch-based pilot pass respects                                                                             |
| STOP at HOLD #B, zero votes written                                      | `total_votes=would_cast=0` — dry-run only, confirmed in the run log                                                                                                             |

## The "2.6x" OCR-tier figure — resolved

The re-stated spec cited "=s800 tier for OCR fetches (2.6x)". Flagged
this in the first pass of this report as unverifiable against the shipped
addendum's own derivation (`OCR_FETCH_DPI = 220` vs `DEFAULT_FETCH_DPI = 250` works out to ~1.14x linear / ~1.29x by fetch area, not 2.6x, and no
"2.6x" figure exists anywhere in the repo). Owner confirmed directly:
this priority push was a courier re-send, and "2.6x" refers to the
already-shipped `=s800` addendum itself — nothing to re-derive or
reconcile. No further action needed on this point.

## Where the real numbers already live

- `docs/reports/2026-07-18-part4-hold-b.md` — the full HOLD #B report,
  real production run (`run_id=20260718T215057-8af41b53`,
  `git_sha=cceb7eb8`), including the complete outcome table, the
  arithmetic cross-checks, extrapolated yields (~662 votes from
  artist-decomposition, ~13,633 cards from free OCR alone), and the two
  open design questions (real `--write` run authorization; the 88.9%
  ambiguous-phash rate among artist-matched cards).
- `docs/features/catalog-completion-plan.md`'s Part 4 section — updated
  in place to reflect HOLD #B cleared, per this repo's edit-in-place doc
  convention.

## Verification

- Every checklist row above was checked against the actual shipped code
  (`MPCAutofill/cardpicker/local_lands_identify.py`) and the actual
  real-run log, not re-derived from memory of the spec.
- No Docker rebuild, no fetch, no DB write performed for this
  confirmation pass — purely a re-read of already-shipped, already-run
  artifacts.

## Open items / decisions needed

1. Both open items already on record in the HOLD #B report itself remain
   open and undecided by this confirmation pass (real `--write` run
   scope/authorization; whether to narrow the phash margin or accept the
   current ~1.7% artist-decomposition yield ceiling).

## Live state

Nothing built, run, or written by this confirmation task. Master is
unaffected. Queue items (#101/#105/#106 merges, the verification pass,
the auth-fix merge) that were yielding to this can resume.
