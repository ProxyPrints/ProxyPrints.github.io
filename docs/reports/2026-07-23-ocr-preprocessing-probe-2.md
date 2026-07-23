```
TASK: SECOND OCR-preprocessing recovery probe (owner-authorized, 2026-07-23) - worktree
worktree-agent-ac77a14e73df66b0b, base commit 00f0190e (confirmed an ancestor of origin/master's
current HEAD, cea8a258 - see DEVIATIONS item 1). Reused the first probe's harness/variant sets
verbatim (branch report-ocr-preprocessing-probe-2b17e9, MPCAutofill/scripts/experiments/
ocr_preprocessing_probe.py). No branch pushed for code (worktree-only experimental scripts,
deliberately not merged - verdict: no variant won). This report file ships on branch
report-ocr-preprocessing-probe-2-f4c91e. GitHub comments posted to issue #370
(https://github.com/ProxyPrints/ProxyPrints.github.io/issues/370#issuecomment-5061330755) and
issue #360 (https://github.com/ProxyPrints/ProxyPrints.github.io/issues/360#issuecomment-5061333416).

WHAT SHIPPED:
1. Built a stratified sampler (MPCAutofill/scripts/experiments/ocr_preprocessing_probe2_sample.py,
   worktree-only, NOT committed) that derives, read-only:
   - STRATUM A pool: 52,349 cards - `CardPrintingTag(anonymous_id="stage-d-join-key-v1",
     is_no_match=True)` whose CURRENT `ImageEvidence` row (content_hash == card.content_phash,
     same lookup `run_join_key_calculator` itself uses) has a non-blank
     `collector_line_set_code` NOT in the real lexicon (`CanonicalExpansion.code`,
     case-insensitive, 1,047 codes) - EXACT match to issue #370's own sizing (52,349/61,247,
     blank=4,586, lexicon-valid-no-match=4,312 - all four numbers reproduced live, DB-verified,
     before drawing any sample).
   - STRATUM B pool: 39,253 cards - the same anonymous_id's genuine matches (is_no_match=False),
     ground truth = the vote's own `printing_id`.
   - Sampled 300 from A (seed=20260723) and 150 from B (seed=20260724, a documented sub-seed of
     the same base), both uniform-random via `random.Random(seed).sample(...)` over a sorted id
     list (deterministic regardless of DB row order).
2. Built a second harness (ocr_preprocessing_probe2_run.py, worktree-only) that IMPORTS the first
   probe's own `VARIANT_SETS`/`_run_variant_set` (a_baseline / b_adaptive (+Sauvola) /
   c_cc_localize (+CC text-localization) / d_cc_adaptive (combined)) rather than reimplementing
   them - zero drift between the two probes' variant logic. Adds only: (a) two-stratum dispatch,
   (b) for stratum B, a `matches_known_pk` field per variant (parsed candidate_pk ==
   ground-truth printing_id) - the actual disqualifying signal the task's verdict rule needs.
3. Ran all 450 cards (300 A + 150 B) x 4 variants sequentially, single-process, single-thread,
   inside the django container: `docker compose -f docker-compose.prod.yml exec -T django python
   .../ocr_preprocessing_probe2_run.py --stratum-a-ids ... --stratum-b-ids ...
   --stratum-b-truth ... --out /tmp/ocr_probe2_full.jsonl --progress-every 20`. Completed
   2026-07-23, 686.9s (11m27s) wall, 0 fetch failures, RSS flat 214-219MB throughout (psutil,
   sampled every 20 cards - no leak).
4. Filed the clean-negative result (see RESULTS) as comments on issues #370 and #360 per the
   task's own instructed venues, stating the noise-vs-degraded-real split the data implies.

RESULTS - STRATUM A (borderline, lexicon-invalid no-match), n=300:

| variant       | genuine_match | lexicon_plausible_no_match | noise_parse  | avg wall_ms | avg attempts |
|---------------|--------------:|----------------------------:|-------------:|------------:|-------------:|
| a_baseline    | 0 (0.0%)      | 0 (0.0%)                    | 300 (100.0%) | 216         | 1.15         |
| b_adaptive    | 0 (0.0%)      | 0 (0.0%)                    | 300 (100.0%) | 207 (-4.3%) | 1.18         |
| c_cc_localize | 0 (0.0%)      | 0 (0.0%)                    | 300 (100.0%) | 221 (+2.6%) | 1.23         |
| d_cc_adaptive | 0 (0.0%)      | 1 (0.3%)                    | 299 (99.7%)  | 227 (+5.2%) | 1.22         |

Lexicon-valid parses gained vs baseline: b=+0, c=+0, d=+1 (net) - and that one gain (card_id
185888, "Mystic Remora") is a coincidental collision, not a rescue: d_cc_adaptive read
set="eve" (Eventide, a real code) num="7" - "eve" is not among this card's own 8 candidate
printings, so it stays `lexicon_plausible_no_match`, never `genuine_match`.
Candidate-VALIDATED genuine matches gained (THE PRIZE NUMBER): b=+0, c=+0, d=+0. ZERO across all
three non-baseline variants - an even cleaner negative than the first probe's (which found a
2-card baseline floor with zero variant deltas; here baseline itself is a 0-card floor).

Only 7/300 (2.3%) stratum-A cards produced ANY different raw parse (set_code and/or
collector_number) under ANY of the three non-baseline variants vs baseline - and every one of
those 7 alternate reads was still non-lexicon garbage ("ooye", "bee", "say", "yoy", "ors", "wel",
"ote" - none real set codes, none real words). The other 293/300 (97.7%) produced the IDENTICAL
parse under every variant.

STRUCTURAL FINDING (not anticipated by the task spec, discovered live): 282/300 (94.0%) of
stratum A short-circuits at the very FIRST preprocessing attempt under every variant, including
the three non-baseline ones - because production's own escalation loop
(`image_evidence.py` lines 619-627, verified byte-identical to this worktree's copy) breaks the
instant `parse_collector_line` returns ANY non-None `collector_number`, with no validation
against the set-code lexicon before accepting. Since these are exactly the cards that already
carry a `parsed-but-no-match` no-match vote (i.e., SOME collector-number-shaped garbage was
already read), the new preprocessing tiers this probe tests (inserted after tier 1) are
STRUCTURALLY UNREACHABLE for 94% of the sample, regardless of whether they would have helped -
the loop never gets there. Only the 18/300 cards whose tier-1 read failed to produce a
collector_number at all reach the new tier, and among those, zero produced a genuine match and
only one (the coincidental "eve" collision above) produced a lexicon-valid parse. This means the
null result has two contributing causes this probe cannot fully separate: (1) genuinely illegible
signal in most of the crop region (supported by the 18-card subset that DID get a fair shot and
still found nothing), and (2) a pipeline-level short-circuit that never gives most of the
population a shot in the first place.

RESULTS - STRATUM B (positive control, genuine matches), n=150:

Baseline (a_baseline) reproduces the known match (`matches_known_pk`) for 150/150 (100.0%) - a
clean baseline-fidelity floor (this probe's `_run_variant_set` calls `_collector_line_ocr_attempts`
verbatim for baseline, same guarantee as the first probe).

| variant       | match-preservation (of baseline's 150) | avg wall_ms  | avg attempts |
|---------------|----------------------------------------:|-------------:|-------------:|
| a_baseline    | 150/150 (100.0%)                        | 164           | 1.00         |
| b_adaptive    | 150/150 (100.0%)                        | 167 (+1.8%)   | 1.00         |
| c_cc_localize | 150/150 (100.0%)                        | 162 (-1.2%)   | 1.00         |
| d_cc_adaptive | 150/150 (100.0%)                        | 161 (-1.8%)   | 1.00         |

Zero cards lost by any variant. Parse-quality drift: 150/150 (100%) `genuine_match` under EVERY
variant, zero `lexicon_plausible_no_match`/`noise_parse`/`no_text` anywhere - completely flat,
no drift at all. `avg_attempts=1.00` for all four variants confirms every stratum-B card's known
match is found on the very first tier-1 preprocessing attempt (unsurprising - these are the
"easy", already-legible cards by construction), so the new tiers never even get exercised here
either, consistent with (and reinforcing) the structural finding above.

VERDICT (per task's own rule: "a variant wins only if it gains genuine matches in A while
preserving >=99.5% of B's matches"): NO VARIANT WINS. All three (b/c/d) gain 0 genuine matches in
A - fails the FIRST clause outright, so B's clean 100% preservation (which would have passed) is
moot. Negative, same overall shape as the first probe, but a cleaner, more informative negative:
baseline itself is a 0/300 floor here (vs. the first probe's 2/300), and the new structural
short-circuit finding gives a concrete, actionable reason beyond "no signal found."

SPLIT THE DATA IMPLIES (for issue #370's noise-vs-degraded-real question, THIS is the answer this
task asked me to state): 0/300 genuine rescues under 4 preprocessing strategies -> rule-of-three
95% upper CI on the true rescue rate is ~3/300 (~1.0%). Point estimate: the 52,349-card
lexicon-invalid no-match population is AT LEAST ~99% genuinely hopeless art-noise, not
degraded-but-real collector lines - rescuable by NEITHER simple global-threshold preprocessing
(the first probe's finding, different population) NOR local-adaptive-threshold/CC-localization
preprocessing (this probe). The one caveat that keeps this from being fully conclusive: the
structural short-circuit above means 94% of the sample was never actually given a fair shot at
the new tiers - so this bounds "how much of the untested majority MIGHT be degraded-but-real" at
"unknown, not measured by this probe," while still concluding "of the ~6% that WAS given a fair
shot, zero were rescuable."

DEVIATIONS:
1. Between this task's dispatch and this probe's run, PR #380 (cea8a258, merged 2026-07-23
   13:13:25-04:00, same day) already fixed issue #370 AT THE VOTE-CASTING LAYER:
   `calculate_join_key_verdict` (local_calculate_verdicts.py) now abstains instead of casting a
   confident `is_no_match` vote when the parsed set code isn't lexicon-valid, plus a
   `--selector set-code-lexicon-gate` retraction tool (reparse_collector_evidence.py) to
   retroactively fix past runs. CONFIRMED LIVE this fix has NOT yet been run against the existing
   population: the 61,247/39,253 vote counts were identical immediately before and immediately
   after this probe's run. This probe's sampled population (the 52,349-card pool) is therefore
   still fully present and valid to test against - REASONING for not re-deriving against a
   "post-fix" population: no such population exists yet (the fix changes future computation, not
   past votes, until someone runs the retraction tool). Separately CONFIRMED: PR #380 does NOT
   touch `image_evidence.py` (the extraction/escalation loop this probe's own structural finding
   is about) - the two fixes are complementary, not overlapping; flagged in both GitHub comments
   as a live, actionable connection between #370's already-landed fix and this probe's own
   unaddressed structural finding.
2. Runtime came in far under the ~40-50 min estimate: 11m27s for 450 cards (1.53s/card avg) vs.
   the first probe's 4.94s/card. REASONING: this probe's two populations are structurally
   "easy-to-attempt-once" by construction - stratum A cards already have SOME collector-number-
   shaped parse (required to have earned an `is_no_match` vote in the first place) and stratum B
   cards have a KNOWN genuine match (found on the very first attempt, avg_attempts=1.00 exactly) -
   unlike the first probe's blank-tier-1 population, which needed heavy escalation through every
   fallback tier before giving up (avg_attempts 7-9). Not a bug; a real property of these two
   different populations, and part of what produced the structural short-circuit finding above.
3. Same simplified-classifier limitation as the first probe's own DEVIATIONS item 1:
   `_classify`/`validate_against_candidates` only, not the full Stage D `calculate_join_key_
   verdict` agreement-check layer (frame-style veto, copyright-year era check, artist-OCR
   corroboration). Lower-impact here than in the first probe: stratum A's own "genuine match"
   count is a flat 0 across all variants (nothing to over-count), and stratum B's ground truth
   comes from the ALREADY-CAST real vote's `printing_id`, not this probe's own simplified
   classifier, so `matches_known_pk` (the actual verdict-relevant metric) is unaffected by this
   limitation entirely.

VERIFICATION:
- Population sizing reproduced EXACTLY live before sampling: lexicon size 1,047; total no-match
  votes 61,247; stratum-A pool 52,349 (blank=4,586, lexicon-valid-no-match=4,312 - both sum
  correctly: 52,349+4,586+4,312=61,247); stratum-B pool 39,253 - all four numbers match issue
  #370's own DB-verified sizing exactly, independently re-derived (not copy-pasted).
- Confirmed this worktree's base commit (00f0190e) is an ancestor of origin/master's current HEAD
  (cea8a258, PR #380) via `git merge-base --is-ancestor` - establishes this probe genuinely ran
  against the PRE-#380 calculator/extraction code, consistent with the container.
- Confirmed the running django container's own copies of local_ocr.py, image_evidence.py,
  local_calculate_verdicts.py, local_identify_printing_tags.py, image_cdn_fetch.py, and
  local_fallback.py are byte-identical (`diff`, zero output on all six) to this worktree's copies
  before trusting the probe's reuse of production internals to mean anything.
- Full run: 450/450 cards processed, 0 fetch failures, 686.9s wall (11m27.9s), RSS flat 214-219MB
  across the whole run (psutil, sampled every 20 cards) - no leak.
- Smoke test (--limit-a 3 --limit-b 3) run before the full run: completed cleanly, sane per-
  variant outcomes, stratum-B `matches_known_pk=True` on all 3 smoke-test B cards under all 4
  variants - confirmed the ground-truth wiring works before committing to the full run.
- POST-RUN: confirmed zero DB writes - `CardPrintingTag` no-match/match counts unchanged
  (61,247/39,253, identical to pre-run), zero `ImageEvidence`/`CardScanLog`/`PilotRunLedger` rows
  with `run_id` containing "probe2" (this probe's harness casts no `run_id` at all - read-only
  throughout, verified by inspection: no `.save()`/`.create()`/`bulk_create` call exists anywhere
  in either script).
- DEFERRED: did not re-verify the one `lexicon_plausible_no_match` gain (card_id 185888) against
  the live Stage D agreement-check layer - moot, since it never reaches `genuine_match` under the
  simplified classifier either way (see DEVIATIONS item 3).

OPEN ITEMS / DECISIONS NEEDED:
1. None blocking - clean negative, filed to issues #370 and #360 per the task's own instructed
   venues. No PR prepared (task's own "PR only if a variant wins" instruction - none did).
2. Whether to pursue a follow-up experiment that makes the ESCALATION LOOP's own break condition
   lexicon-aware (only stop early on a lexicon-valid parse, keep escalating through preprocessing
   tiers on a lexicon-invalid one) - flagged as a recommendation in both GitHub comments, not
   decided here. This is a DIFFERENT, not-yet-run experiment from either OCR-preprocessing probe
   to date (both probes so far tested "does better preprocessing help," not "does the pipeline
   even give preprocessing a chance to run").
3. Whether/when to run PR #380's own `--selector set-code-lexicon-gate` retraction tool against
   the existing 52,349-card population is a separate owner call, orthogonal to this probe's own
   verdict (this probe measured whether that population is preprocessing-rescuable, not whether
   its stale votes should be retracted - #380 already answered the latter question).

LIVE STATE:
- Probe scripts exist only inside this worktree, UNCOMMITTED (git status: untracked
  `MPCAutofill/scripts/` only - `ocr_preprocessing_probe2_sample.py`,
  `ocr_preprocessing_probe2_run.py`, `ocr_preprocessing_probe2_analyze.py`, plus a copy of the
  first probe's own `ocr_preprocessing_probe.py`/`ocr_preprocessing_probe_analyze.py` reused as a
  library import) - not pushed anywhere, per "no PR since nothing won"; left in place for a
  future task to re-run or extend. Container-side copies (`/MPCAutofill/MPCAutofill/scripts/
  experiments/`) REMOVED after the run (`rm -rf`, confirmed via follow-up `ls`).
  - Governing-premise compliance: every fetched image decoded in memory, cropped in memory,
    OCR'd, and discarded at end of each card (`del image`, normal scope exit for the crop) - ZERO
    image bytes or pixel data written to disk by either script at any point. Only per-card
    metadata JSON (outcomes/timings/parsed text strings, not pixels) was ever written to disk.
- Result artifacts on the HOST (outside any container): `/tmp/ocr_probe2_stratum_a_ids.txt`,
  `/tmp/ocr_probe2_stratum_b_ids.txt`, `/tmp/ocr_probe2_stratum_b_truth.jsonl` (card ids +
  known printing pks only), `/tmp/ocr_probe2_full.jsonl` (450 lines, per-card metadata only),
  `/tmp/ocr_probe2_full.log` (run log), `/tmp/ocr_probe2_smoke.jsonl` (6-line smoke test) - none
  contain image data, safe to delete at will, not copied into the repo. Container-side copies of
  the same files (`/tmp/ocr_probe2_*` inside `mpcautofill_django`) REMOVED (`rm -f`, confirmed via
  follow-up `ls` showing none of this probe's own files remain - unrelated pre-existing /tmp
  files from other sessions were left untouched, not mine to clean).
- No votes, no `ImageEvidence` rows, no `CardScanLog` rows, no `PilotRunLedger` rows, no other DB
  writes of any kind - both scripts are read-only against Card/CanonicalCard/CanonicalExpansion/
  CardPrintingTag/ImageEvidence throughout (verified pre- and post-run vote counts identical, and
  by inspection - no `.save()`/`.create()`/`bulk_create` call exists anywhere in either script).
- WORKERS.md: no row added (read-only session throughout, matches the file's own "read-only
  sessions add no row" rule). Checked for an active `deploy-freeze-active` GitHub label before
  starting - none found.
- GitHub: comments posted to issue #370
  (https://github.com/ProxyPrints/ProxyPrints.github.io/issues/370#issuecomment-5061330755) and
  issue #360 (https://github.com/ProxyPrints/ProxyPrints.github.io/issues/360#issuecomment-5061333416).
  No PR opened. This
  report file is committed on branch `report-ocr-preprocessing-probe-2-f4c91e` and pushed to
  origin - not merged, awaiting the owner (per this repo's own "PRs+owner sequencing" push-policy
  note, applied conservatively to a report artifact as prior probe reports have been).
```
