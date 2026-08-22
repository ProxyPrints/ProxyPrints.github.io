# docs/reports/

Relayed work-product reports — point-in-time findings from a session or
agent pass, written up for a later reader instead of staying trapped in
that session's own transcript. Not living reference: check each report's
own "as of" date before trusting anything in it as current.

`schema.json` is a structured mirror of the six-field standing report
format (CLAUDE.md's Reporting convention) — the prose report is still
the record of truth for a human reader; the schema exists for tooling
that needs to route on verdict/deviations/open-items without
re-parsing prose. Tiered: a `summary` object read on every report, and
a `detail` object read only when the summary signals it's needed.

- `2026-07-18-part3-fullrun.md` — Part 3 catalog-completion fullrun
  status + backfilled HOLD #P3 record.
- `2026-07-18-part3-fullrun-data-loss.md` — the fullrun dry-run's
  stdout capture lost to a `--rm` race, and the write-pass decision
  fork that followed.
- `2026-07-18-part3-write-pass-complete.md` — Part 3's write pass
  completion: bounds verified, zero-resolution assertion, queue
  spot-check.
- `2026-07-18-pr62-hard-gate.md` — PR #62's full pytest hard-gate
  results, a real snapshot-drift regression found and fixed, schema
  regen consistency check.
- `2026-07-18-pr62-merge-and-deploy.md` — PR #62 merged, the item-C
  deploy sequence, the live E-2 ground-truth check against production.
- `2026-07-18-merge-sweep-checkpoint-1.md` — merge-sweep checkpoint
  covering PRs #64/#65/#66/#67/#69 (recreated as #72 after a
  base-branch-deletion incident).
- `2026-07-18-ai-to-machine-terminology.md` — "AI" → "machine"
  terminology fix for OCR/phash/deduction vote sources, docs +
  frontend + a backward-compatible settings rename.
- `2026-07-18-wiki-review-findings.md` — publish-script link-rewrite
  fix, Part 3 write-pass status update, and a targeted staleness
  mini-pass across proposal docs and docs/README.md.
- `2026-07-19-backend-tests-ci-tesseract-fix.md` — "Backend tests" CI
  root-caused to three failure classes (live Moxfield network call,
  empty Google Drive secret, 10 tests missing the established
  tesseract-mock convention); the tesseract gap fixed, the other two
  flagged as owner-only, plus worktree/guard tool-access signal.
- `2026-07-19-extractable-primitives-ledger.md` — repo-wide
  extractable-primitives audit (27 rows), the mechanical tether added
  to `docs_lint.py`, and the CLAUDE.md convention line.
- `2026-07-20-pipeline-compute-profile.md` — Stage C/D compute profile:
  Stage D negligible, Stage C (OCR-heavy) projects 71–378h against a
  6.2h reference budget, BLOCKING verdict, x6 thread-pool concurrency
  found to actively hurt CPU-bound work.
- `2026-07-20-canary-reprofile.md` — 400-card process-pool canary on
  rebuilt prod: 63.1% parallel efficiency, ~15.7–16.0h projected,
  STOPPED at the gate's ~15h ceiling.
- `2026-07-20-fetch-compute-timing-diagnostic.md` — 130-card
  `--profile` dry-run confirming fetch-wait (36.5% of wall-clock) as
  the dominant cause of the canary's efficiency gap; verdict to build
  the fetch/compute decoupling design.
- `2026-07-20-decoupled-canary-confirm.md` — 400-card canary on the
  deployed decoupled architecture: 63.1% → 95.2–99.1% parallel
  efficiency, ~10.5–10.9h projected, gate CLEAR.
- `2026-07-21-stagec-20k-extraction.md` — 20,000-card Stage C cohort on
  the decoupled architecture: row accounting exact, 0.525% fetch-failure
  rate (down from the 400-card canary's 1.5%), no-pixels invariant
  confirmed by schema inspection.
- `2026-07-21-staged-write.md` — Stage D join-key + slow-path staged
  write (`run_id=staged-write-20260721T0434Z`): 8,925 votes verified,
  the dry-run's slow-path blind spot traced to its root cause, gate
  independently re-derived at 0/8,925, three review-queue numbers
  disambiguated (#258).
- `2026-07-21-recovery-arc.md` — five-run recovery arc: a parser-bug
  reparse/retraction (100 votes), the AI-art tag detector's first write
  (1,183 votes), a no-text cohort re-extraction (`run_id=ntx-0721`,
  31.3% collector-number recovery), and two further Stage D join-key
  passes (one exposing a real skipped-state-clear sequencing gap);
  `stage-d-join-key-v1` totals reconciled to 11,905, gate re-derived at
  0/12,684 across both the printing- and tag-consensus engines this arc
  touched.
- `2026-07-26-stagec-full-catalog-completion.md` — Stage C full-catalog
  extraction completion: 218,108 / 218,516 cards (99.8%), run_ids
  `pass-full-20260725` + `-r2` superseding all prior Stage C last-writer rows,
  1,614 fetch_ok=False rows + 408 cards with no evidence (all Google Drive),
  full-catalog fetch-failure rate 0.74%.
- `2026-07-22-knowledge-inventory.md` — pipeline-fidelity gate artifact 2
  (knowledge-inventory sweep): a constant-by-constant table of every
  pilot-era value's current home, 3 confirmed MISSING items, 3 open
  items. Cited by [`../pipeline-fidelity-gate.md`](../pipeline-fidelity-gate.md),
  the gate's canonical status page.
- `2026-07-29-external-ip-vs-promo-types-delta.md` — characterisation of
  the Scryfall Tagger `art:external-ip` vs. `promo_types=universesbeyond`
  delta left open by PR #599. Both join paths reconciled (agree to within
  2 rows); the delta is 2,820 printings, not the reported ~2,759, plus a
  reverse delta of 61 the subtraction had hidden. 83.4% is D&D /
  Forgotten Realms and 12.3% Portal Three Kingdoms — neither Universes
  Beyond; 39 of the genuinely-licensed remainder are already marked by
  `godzillaseries`/`draculaseries` in the same column. Recommends dropping
  the Tagger dependency, with the definitional question that would
  invert that recommendation stated explicitly.
- `2026-07-29-printing-vs-illustration-tag-grain.md` — **decision
  document; its central question has since been RULED and EXECUTED.**
  Should `PrintingTagVote` exist? Answer: no — retired in PR #615
  (2026-07-30), so this reads as the record of that reasoning rather than
  a live proposal. Disambiguates `CardPrintingTag` / `CardTagVote` / `PrintingTagVote` and
  traces which of them `PRINTING_TAG_MIN_VOTES` /
  `PRINTING_TAG_IMPLICIT_CAP` / `_split_new_printing_tag_votes` actually
  govern (none of them govern `PrintingTagVote`). Measured: the table is
  empty (0 rows, 0 human) and has no consensus resolver; machine-only
  votes cannot resolve at any volume (executed, n up to 1,000), so the
  original auto-tagging design was unreachable at every grain;
  `promo_types` already carries `universesbeyond` on 10,407 of 113,224
  printings at 100% per-set recall; 0 of 50,828 illustrations straddle
  the UB boundary. Leads with the governing constraint (owner-ratified:
  a machine-only channel never resolving is the design, so any tag
  expected to resolve from machine evidence alone is mis-specified — it
  belongs as a derived attribute, not a vote) and answers what the
  smallest mechanism delivering the UB filter actually is. Folds in three
  owner rulings of 2026-07-29. Eleven numbered open questions.
- `2026-07-29-pipeline-coverage-composition-audit.md` — the composition
  audit: every vote and extractor channel enumerated from code, measured
  against production, and traced to the engine that can reach it. Finds the
  frame-style and bleed-edge attribute chips at zero rows with no substitute
  and no engine wiring (142,633 + 2,786 votes re-derivable from stored
  evidence with no image fetch), `extract_card_evidence` with zero production
  callers, the missing illustration exclusion in the slow-path queryset, and
  six Stage C → Stage D dependencies that no `extractor_versions` gate
  enforces.
- `2026-08-21-name-frequency-elimination-soundness.md` — issue #858:
  `local-name-frequency-v1`'s "79.8% unsound" claim in
  `collector_line_artist.py` had no supporting measurement anywhere in the
  repo. A read-only backtest of the calculator's structural double gate
  against 23,203 confirmed-match ground-truth cards finds it wrong on
  64.9% of its 2,996 checkable simulated firings (35.1% precision) - the
  "unsound" direction holds, the number and its claimed private-normaliser
  cause did not; both corrected in `collector_line_artist.py` to cite this
  report.

- `2026-08-06-card-location-landmark-gate.md` — STEP 1 gate result (NOT
  MET) for locating the card's own rectangle inside a possibly
  canvas-padded image via the rules-text-box's bottom edge: the brief's
  single global `f`-fraction + symmetric-padding formula measured
  against direct pixel-level ground truth on the 4 cards a prior audit
  (crop-geometry-audit, external to this repo) flagged as confirmed
  misclassifications — 0/4 correct (3 abstained, 1 wrong by >10x); 39.3%
  confident rate over a 28-image stratified sample. No code changed; two
  concrete, unattempted follow-up directions identified.

Note: a separate, unrelated session also used the bare `report-relay`
branch name for its own work (upstream-ladder CI, federation-v1 doc
updates) — a genuine cross-session branch-name collision, not a typo.
Only this session's own file above (`2026-07-18-part3-fullrun.md`) was
pulled from that branch; the other session's commits on it were left
untouched, not reviewed or merged here.
