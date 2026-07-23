```
TASK: OCR preprocessing recovery probe (owner task, 2026-07-23) — worktree
worktree-agent-aa43375e9c1c5399c, base commit 8097fcc0 (master HEAD at start). No branch pushed
for code (worktree-only experimental script, deliberately not merged - see WHAT SHIPPED). This
report file itself ships on branch report-ocr-preprocessing-probe-2b17e9. No PR opened (verdict:
no variant won - see below). GitHub comment posted:
https://github.com/ProxyPrints/ProxyPrints.github.io/issues/360#issuecomment-5060946847

WHAT SHIPPED:
1. Built a worktree-only probe script
   (MPCAutofill/scripts/experiments/ocr_preprocessing_probe.py, NOT committed to master/any
   shared branch - see LIVE STATE) that, per card: fetches the image transiently via the
   production `image_cdn_fetch.fetch_card_image` call, crops the collector strip via production's
   own `image_evidence._crop_box_to_pixels` + `local_ocr.DEFAULT_CROP_BOX`, then runs OCR under 4
   variant sets and validates the parse against the card's real name-scoped candidates via
   production's own `local_ocr.validate_against_candidates`
   (`local_identify_printing_tags.CandidateNameIndex`). Calls the existing extraction internals
   throughout (`local_ocr.preprocess_variants`/`preprocess_fallback_variants`/
   `run_tesseract_text_and_words`/`parse_collector_line`, `image_evidence._collector_line_ocr_attempts`
   for the (a) baseline reproduction verbatim) — no reimplementation of any PROTECTED CORE logic;
   local_ocr.py/local_fallback.py/local_identify_printing_tags.py were read, never edited.
2. Ran the harness against the exact 300-card `buga-sample-20260723T0927Z` sample (ids pulled live
   from `/MPCAutofill/MPCAutofill/buga_sample_ids.txt` inside the running container, confirmed
   identical to `docs/data/2026-07-23-zeroing-and-buga-sample.md`'s own documented sample) under 4
   variant sets:
   - (a) baseline — production's own attempt chain unchanged (reproduction control).
   - (b) + Sauvola local-adaptive threshold (new, worktree-only function, numpy/scipy only).
   - (c) + connected-component text-localization pre-pass (`scipy.ndimage.label`, crop to the
     text-shaped bounding box before the existing fixed threshold).
   - (d) (b) + (c) combined.
   Each of (b)/(c)/(d) is a STRICT SUPERSET of baseline's own recovery paths (the new tier is
   inserted, nothing removed), so any measured regression can only be an ordering/
   first-parse-wins effect, never a lost capability.
3. Metrics captured per card per variant: outcome bucket (genuine_match /
   lexicon_plausible_no_match / noise_parse / no_text), attempts tried, wall-clock ms — plus a
   cheap join to the buga-sample run's own already-computed `ImageEvidence.layout_class`/
   `bleed_class` per card (no recompute) for the visual-signal split.
4. Filed the clean-negative result as a comment on issue #360 (the task's own instructed venue for
   a non-winning result), not a PR.

RESULTS TABLE (300 cards, fetch_ok=299/300, one transient CDN read-timeout on card_id=94278
"Stingscourger" — unrelated to preprocessing, same card failed identically for all 4 variants
since fetch happens once per card):

| variant       | genuine_match | lexicon_plausible_no_match | noise_parse  | no_text      | avg wall_ms | avg attempts |
|---------------|--------------:|----------------------------:|-------------:|-------------:|------------:|-------------:|
| a_baseline    | 2 (0.7%)      | 2 (0.7%)                    | 74 (24.7%)   | 221 (73.9%)  | 909         | 7.06         |
| b_adaptive    | 2 (0.7%)      | 3 (1.0%)                    | 95 (31.8%)   | 199 (66.6%)  | 1087 (+20%) | 8.37         |
| c_cc_localize | 2 (0.7%)      | 2 (0.7%)                    | 80 (26.8%)   | 215 (71.9%)  | 1114 (+23%) | 8.92         |
| d_cc_adaptive | 2 (0.7%)      | 2 (0.7%)                    | 96 (32.1%)   | 199 (66.6%)  | 1117 (+23%) | 8.42         |

Genuine matches: IDENTICAL 2-card set across all 4 variants (card_id=122326 "Ephemerate (Sketch
Yumiko-68)" → candidate pk 147042; card_id=126947 "entreat the angels 4" → candidate pk 102130).
Zero cards where any non-baseline variant found a genuine match baseline missed.

By `layout_class` (cheap join, buga-sample run's own precomputed value, not recomputed):
- black (n=198): 0 genuine matches under ANY variant. noise_parse: a=52, b=65, c=55, d=61.
- white (n=47): 0 genuine matches under ANY variant. noise_parse: a=9, b=12, c=12, d=19.
- borderless (n=49): 2 genuine matches under ALL variants (same 2 cards, no incremental gain).
  noise_parse: a=11, b=14, c=11, d=13.
- (ambiguous/none, n=4) / silver (n=1): too small to read anything into; no genuine matches.
Both genuine matches concentrate in the borderless bucket (the only bucket where either baseline
or any variant ever found one) — consistent with issue #360's own composition finding that the
blank-OCR cohort tracks source/template more than card style, since even borderless's own 49-card
subset only yields 2/49 (4.1%) regardless of preprocessing.

DEVIATIONS:
1. "Genuine match" in this probe is a SIMPLIFIED classifier (raw `local_ocr.validate_against_
   candidates` only) — it does NOT run the full Stage D `calculate_join_key_verdict` agreement-
   check layer (frame-style veto, copyright-year era check, artist-OCR corroboration,
   `local_calculate_verdicts.py`). Discovered live: this probe's baseline reproduction found 2
   "genuine matches" against this exact sample, one more than the production funnel's own
   documented "1 genuine match" (docs/data/2026-07-23-zeroing-and-buga-sample.md). Traced the
   extra hit (card_id=126947) to a 3-token, 5-character garbled OCR read ("a\n4\nrd") that
   happened to collide, via the collector-number-only fallback path, with the one candidate among
   7 carrying collector_number="4" — exactly the kind of weak match Stage D's own agreement-check
   layer exists to catch and would very plausibly reject (not independently re-verified against
   the live calculator this pass, since doing so would have required also fetching CanonicalCard
   frame/release-date metadata this probe didn't otherwise need). REASONING for not fixing this:
   irrelevant to the actual experiment question — every one of the 4 variants used the IDENTICAL
   simplified classifier, so the relative comparison (does any variant beat baseline) is
   unaffected by this absolute-count discrepancy; both "genuine matches" this probe counted are
   IDENTICAL across all 4 variants regardless. Flagged here rather than silently reconciled to the
   production number.
2. Task asked for "sequential or small pool" — ran fully sequential, single-process, single-
   thread (no pool at all). REASONING: 300 cards at ~4.9s/card sequential (~25 min total) already
   fit comfortably inside the "tens of minutes" budget: a pool would have added coordination
   complexity (Django DB connections across forks, RSS tracking per worker) for no measurement
   benefit at this scale.
3. scipy (variant (c)/(d)'s `scipy.ndimage.label`/`uniform_filter`) is NOT a direct
   `requirements.txt` pin — flagged per the task's own "no new prod deps without flagging"
   instruction. It IS already present in the running prod container as a transitive dependency of
   `ImageHash~=4.3.2` (confirmed live: `pip show scipy` → `Required-by: ImageHash`, version
   1.18.0) — no `pip install` was needed to run this probe. If a future PR ever depended on scipy
   DIRECTLY (moot here since no variant won), it should be pinned explicitly in requirements.txt
   rather than relying on ImageHash's transitive pull, which could drop or change it on a future
   ImageHash bump with no warning.

VERIFICATION:
- Probe script test run (--limit 3) before the full run: completed cleanly, 4.8s/card, sane
  per-variant attempt counts and outcomes (spot-checked manually against expected tier structure).
- Full run: `docker compose -f docker-compose.prod.yml exec -T django python
  /MPCAutofill/MPCAutofill/scripts/experiments/ocr_preprocessing_probe.py --ids-file
  /tmp/buga_sample_ids.txt --out /tmp/ocr_probe_full.jsonl --progress-every 20`, started
  2026-07-23T16:09:28Z (container log timestamp), completed after 1481.5s (24m41.5s) — 300/300
  cards processed, 4.94s/card average, 1 fetch_failure (transient CDN read-timeout on card_id
  94278, 15.06s before giving up — the container's own `rate_limited_get(timeout=15)`).
- RSS held flat at 219-224MB across the whole run (`psutil`, sampled every 20 cards) — no leak.
- Verified the container's own `local_ocr.py` is byte-identical to this worktree's copy (`diff`,
  zero output) before trusting the probe's reuse of production internals to mean anything; also
  confirmed the container's baked commit (42a09b3c) is an ancestor of this worktree's HEAD
  (8097fcc0), i.e. no drift between what was measured and current master.
- Confirmed the sample ids file (300 non-comment lines) matches the count and header comment
  documented in docs/data/2026-07-23-zeroing-and-buga-sample.md's own §9(c) section (seed=20260723,
  17,531-card blank-tier-1 pool at generation time) — no independent resampling was done.
- DEFERRED: did not independently re-verify card_id=126947's match against the live
  `calculate_join_key_verdict` (see DEVIATIONS item 1) — out of scope for the comparative
  question this probe was built to answer.

OPEN ITEMS / DECISIONS NEEDED:
1. None blocking — clean negative, filed to issue #360 per the task's own instructed venue. No PR
   prepared (task's own "PR only if a variant wins" instruction — none did).
2. Whether to pursue a source/template-legibility investigation for the blank-OCR cohort instead
   of further preprocessing experiments is an owner call, not answerable from this probe alone —
   flagged as a recommendation in the issue #360 comment, not decided here.

LIVE STATE:
- Probe script + analysis script existed only inside this worktree
  (MPCAutofill/scripts/experiments/ocr_preprocessing_probe.py,
  MPCAutofill/scripts/experiments/ocr_preprocessing_probe_analyze.py) and a copy inside the
  running `django` container (`/MPCAutofill/MPCAutofill/scripts/experiments/`) for execution.
  Container copy REMOVED after the run (`rm -rf .../scripts/experiments`, confirmed via a
  follow-up `ls`). The worktree copies remain on disk in this worktree, UNCOMMITTED (git status:
  untracked `MPCAutofill/scripts/` only) — not pushed anywhere, per "no PR since nothing won";
  left in place in case a future task wants to re-run or extend this probe, but not part of this
  report's own committed branch.
- Fetched images: every fetch was decoded in memory (`PIL.Image.open` via
  `fetch_card_image`), cropped in memory, OCR'd, and discarded at end of each loop iteration
  (explicit `del image` plus normal scope exit for the crop) — ZERO image bytes or pixel data
  written to disk at any point, by this script or the container filesystem. Only metadata
  (outcome/timing JSON) was ever written to disk, and even that was a /tmp scratch file, not
  committed anywhere.
- Result artifacts: `/tmp/ocr_probe_full.jsonl` (300 lines, per-card metadata only) and
  `/tmp/ocr_probe_full.log` (run log) exist on the HOST (outside any container) at those paths —
  not copied into the repo, not containing any image data, safe to delete at will; removed the
  container-side copy already (see above). The container's OWN `/tmp/buga_sample_ids.txt` (a
  redundant copy of card ids I pushed in for convenience, duplicate of the file that already
  lives at `/MPCAutofill/MPCAutofill/buga_sample_ids.txt`) could NOT be removed (uid mismatch,
  `Operation not permitted` under the container's own `mpcautofill` user) — left behind, but it
  contains only already-public integer card ids (no image data, no secrets), and duplicates a
  file the container already had before this task started.
- No votes, no ImageEvidence rows, no CardScanLog rows, no PilotRunLedger rows, no other DB writes
  of any kind — the probe script is read-only against Card/CanonicalCard/CanonicalExpansion/
  ImageEvidence throughout (verified by inspection of every DB call in the script; no `.save()`/
  `.create()`/`bulk_create` call exists anywhere in it).
- GitHub: comment posted to issue #360
  (https://github.com/ProxyPrints/ProxyPrints.github.io/issues/360#issuecomment-5060946847). No PR
  opened. This report file is committed on branch `report-ocr-preprocessing-probe-2b17e9` and
  pushed to origin — not merged, awaiting the owner (per this repo's own "PRs+owner sequencing"
  push-policy note for anything beyond a solo direct-master push, applied conservatively here
  since this is a report artifact, not code).
```
