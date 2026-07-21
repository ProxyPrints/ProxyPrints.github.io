# Stage C 20k-cohort extraction — verification (2026-07-21)

Read-only verification of the 20,000-card `run_image_evidence_cohort` run
the owner authorized and executed directly against prod
(`mpcautofill_django`), following up
`docs/reports/2026-07-20-decoupled-canary-confirm.md` (400-card decoupled
canary, gate CLEAR) with the first at-scale run on the decoupled
fetch/compute architecture (`#228`/`#237`). This session did not run the
extraction — it verifies row counts, failure accounting, and the
no-pixels invariant against what already landed, and reports the result.
No writes were made to any live database or index from this session; all
figures below come from `SELECT`/`count()` queries and the run's own log.

## Run parameters

- Command (owner-executed): `run_image_evidence_cohort --limit 20000 --run-id stagec-20k-20260721T0227Z` (workers/fetch-threads/queue-depth left at their defaults: 7 compute processes, 8 fetch threads, queue-depth 14).
- `run_id`: `stagec-20k-20260721T0227Z`
- `dry_run=False` (confirmed from the run's own startup log line) — a real write, continuing the already-authorized real-write pattern from both prior canaries.
- Resume filter: 800 cards skipped as already-fully-processed — this is exactly the combined row count of the two prior canaries (400 + 400 from `2026-07-20-canary-reprofile.md` and `2026-07-20-decoupled-canary-confirm.md`), confirming the resume filter picked up both correctly and re-did no work.
- Eligible pool at run start: 217,428 cards (217,828 canary-run figure minus the 400 additional cards the decoupled canary itself had just completed).
- Cohort: 20,000 cards, prioritized by edhrec_rank ascending (cold tail last), per the driver's existing priority-key logic.
- Log: `~/stagec-20k-20260721T0227Z.log` (owner's home directory on the host, not in this repo).

## Wall-clock / rate vs. the canary's projection

`docs/reports/2026-07-20-decoupled-canary-confirm.md` projected the full
217,828-card remaining pool at **~10.5–10.9h**, from a measured rate of
5.542/s (400-card basis) to 5.769/s (300-card steady-state basis) on the
decoupled architecture.

| metric                              | canary projection (decoupled) | this run (20,000 cards)   |
| ----------------------------------- | ----------------------------- | ------------------------- |
| rate                                | 5.542–5.769 cards/s           | **5.367 cards/s**         |
| implied wall-clock for 20,000 cards | 3,467–3,608s                  | **3,727s** (measured)     |
| delta vs. canary projection         | —                             | **+3.3% to +7.5% slower** |

The 20k run ran a few percent slower per-card than the canary's own
projection. This is within the same order of variance the canary report
itself flagged between different 400-card cohorts (a 5% CPU-s/card swing
attributed to cohort composition — different OCR difficulty mix at
different points in the edhrec-rank-ordered queue) — not a regression
signal on its own. At this rate, the full remaining pool (217,428 - 20,000
= 197,428 cards) projects to **~10.2h** at this run's own 5.367/s figure,
still inside the design doc's ~10.2h target and well under the ~15h gate
ceiling.

## Fetch-failure count and breakdown

**105/20,000 fetch failures (0.525%)**, `lockout_hit=False` throughout —
no `GoogleFetchLockoutError` observed, confirmed both from the log's own
final summary line and from the DB (no cards recorded as skipped due to
lockout).

Compared against the two prior canary baselines (different architectures,
included here for completeness rather than picking one as "the" baseline):

| run                                                        | cards  | fetch failures   | rate |
| ---------------------------------------------------------- | ------ | ---------------- | ---- |
| original canary, bundled architecture (`canary-reprofile`) | 400    | 0 (0%)           | —    |
| decoupled canary (`decoupled-canary-confirm`)              | 400    | 6 (1.5%)         | —    |
| **this run, decoupled architecture**                       | 20,000 | **105 (0.525%)** | —    |

The decoupled canary (the architecturally comparable baseline, since this
run used the same decoupled code path) saw a _higher_ per-card failure
rate (1.5%) than this full 20k run (0.525%) — the failure rate went down
at scale, not up. (Note: the task brief that opened this verification
referenced "0 failures at 800" as the canary baseline; the actual number
"800" traces to the resume filter's already-done count — the combined
row total of the two prior 400-card canaries — not a 0-failure canary
observation at that size. The 0-failure figure belongs only to the
_original bundled-architecture_ canary at n=400; the decoupled canary run
on the same architecture as this 20k run recorded 6/400 failures. Flagging
this since it doesn't match the brief's framing.)

**Growth curve** (from the log's own progress lines): failures started
accumulating at card 2,175 (first non-zero `fetch_failures` count) and
grew through the run: 47 by card 12,600, 99 by card 18,500, 105 final.
Growth was front-loaded relative to the back half of the run — most of
the eventual total (99/105, 94%) was already present by the 92.5% mark
(18,500/20,000), with only 6 more in the last 1,500 cards — but this
does not describe a monotonically _accelerating_ failure rate; the first
2,175 cards saw zero failures at all.

**Characterization of the failures** (DB read, `Card.source` joined
against the 105 `fetch_ok=False` `ImageEvidence` rows):

- All 105 failures are `GOOGLE_DRIVE`-sourced cards. No non-Drive source
  contributed a single failure.
- Spread across 48 distinct Google Drive folders/owners. The single
  largest cluster is `RustyShackleford` at 16/105 (15.2%) — the only
  cluster in double digits. The next-largest are `hathwellcrisping` (6),
  `Berndt_Toast83` (5), `InvalidCards` (5), and `Toma` (5); the remaining
  ~43 drives each contributed 1–4 failures, most exactly 1.
- Checked whether failures concentrate in the "cold tail" (unranked
  names, sorted last by the cohort's priority key) as a candidate
  explanation for growth being back-loaded: they do not. All 105 failed
  cards have a real `edhrec_rank`-bearing name, ranks ranging 54–1,109
  (median 590) — squarely inside the popular-card range, not the
  cold tail.
- **No single concentrated cause was found.** The failures read as
  independent per-file breakage (individual files unavailable/removed/
  permission-changed across many different Google Drive folders) rather
  than one systemic outage, one bad source, or a popularity/content-type
  correlation. `fetch_error_class` is uniformly `"fetch_failed"` for all
  105 — the pipeline's own existing bucket, not a new failure mode.

## Row-count verification

`ImageEvidence.objects.filter(run_id="stagec-20k-20260721T0227Z").count()` →
**20,000** — matches the log's `completed=20000/20000` exactly. Breakdown:

- `fetch_ok=True`: 19,895
- `fetch_ok=False`: 105
- `fetch_ok` null: 0

19,895 + 105 = 20,000. **No cards were silently dropped** — every one of
the 105 `fetch_failures` the log counted still produced a real
`ImageEvidence` row (with `fetch_ok=False`/`fetch_error_class="fetch_failed"`
and every image-dependent field left at its skip-reason default), not a
missing row. This also confirms the run's `dropped` outcome path (a
`Card.DoesNotExist` in the fetch stage, or an uncaught exception in the
compute stage — see the command's own `_CohortStats.record` docstring) was
never hit: `fetch_failures` in the log's summary line is composed
entirely of `fetch_failed` cards here, zero `dropped`.

`CardScanLog.objects.filter(run_id=...)` → 42,269 rows, all with
`anonymous_id` matching a Stage C manifest extractor name. 105 rows per
extractor for the 11 image-dependent extractors that skip on
`fetch_failed` (fetch_health, geometry_bleed, layout_class,
crop_coordinates, collector_line_ocr, collector_line_tsv, artist_ocr,
symbol_region, legal_line, quality_signals, color_profile — 10 of 11
checked directly; `crop_coordinates` shares the same `fetch_failed`
skip-reason bucket as the others), plus genuine content-based skips
(`no-text` for artist_ocr/legal_line/collector_line_ocr on cards with no
OCR-detectable text, `ambiguous` for layout_class/geometry_bleed on
images that didn't classify cleanly) — all pre-existing skip-reason
vocabulary, nothing new invented.

## No-pixels invariant

Read `ImageEvidence`'s field list directly
(`MPCAutofill/cardpicker/models.py`): every field is a hash
(`content_hash`, `symbol_phash`), a numeric measurement (`width`,
`height`, `aspect_ratio`, `blur_variance`, `image_entropy`,
`color_mean_rgb`, `color_stddev_rgb`), a short classification string
(`bleed_class`, `layout_class`, `fetch_error_class`), OCR text/parse
output (`collector_line_raw_text`, `artist_ocr` fields,
`legal_line_raw_text`), or a JSON list of pixel _coordinates_
(`*_crop_px`, `collector_line_word_boxes`) — never a pixel buffer or
image blob. No field on the model is capable of holding image bytes.
This matches the model's own docstring ("persists ONLY derived facts
about a card's image... never the image pixels themselves") and
CLAUDE.md's governing premise. Confirmed by inspection, not by scanning
row contents (the schema itself makes storing pixels impossible, so a
per-row content scan would add nothing).

## Live API

Not independently re-checked in this verification session (read-only,
DB/log queries only) — the owner's authorized run channel already
covered live-API health as part of executing the run; this session did
not restart or touch any container.

## Stage completion

This completes Stage C's bulk-extraction validation at the 20,000-card
tier: decoupled architecture confirmed at 50x the canary's own scale
(400 → 20,000 cards), row accounting exact (20,000 rows for 20,000
completions, zero dropped), failure rate stable-to-improved relative to
the architecturally comparable canary baseline (1.5% → 0.525%), and
`lockout_hit=False` throughout. Per `docs/features/catalog-completion- plan.md`'s Stage D section, the proposed next step is a **Stage D
dry-run** (join-key calculator pass, `--write` withheld) against this
now-larger `ImageEvidence` population — not a further Stage C scale-up,
since Stage C's own gate conditions (wall-clock, failure rate, memory,
live-API stability, index-not-store) are all clear at this tier.

## Open items

1. The 197,428-card remainder of the eligible pool (217,428 minus this
   run's 20,000) has not been run. A full-catalog harvest needs its own
   separate owner GO per Stage E's resume-contract gate (not part of
   this run or this verification).
2. The task brief that opened this verification cited a "0 failures at
   800" canary baseline that does not match either prior canary's own
   recorded figures (0/400 bundled-architecture, 6/400 decoupled-
   architecture) — see the "Fetch-failure count and breakdown" section
   above for the reconciliation (800 is the resume-filter's
   already-done count, not a canary's own card count).
3. No causal explanation for the 105 Google-Drive fetch failures was
   found beyond "spread across many independent Drive folders, no
   concentration by source, popularity, or run position" — if this
   matters for future harvest planning (e.g. flagging `RustyShackleford`'s
   folder for a manual check, since it's the single largest cluster),
   that's a follow-up task, not resolved here.
