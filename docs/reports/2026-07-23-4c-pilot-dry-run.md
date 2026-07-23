# 4c pilot dry-run — full-pool `local_calculate_verdicts` measurement of record

**GitHub issue #154**, `docs/pipeline-fidelity-gate.md` §9(d). This is
the owner-ratified measurement of record for the new-data basis (§8):
the first full-eligible-pool run of the join-key + fallback calculators
against the corrected evidence/parser. **Dry-run only — nothing was
written to `CardPrintingTag`/`CardScanLog` by this run.**

## Pre-flight (live-verified before launch)

- `local_calculate_verdicts --help` and source confirm: `--write` opts
  in to persistence (default is dry-run), and **one invocation covers
  both channels** — the join-key calculator runs first, then (in the
  same process, same `run_id`) the fallback calculator runs over
  whatever the join-key pass found no confident hit for, then slow-path
  routing.
- Fire-sequence prerequisites B(i) (Bug-B write pass), B(ii)+B(iii)
  (retraction), and (c) (Bug-A forced-escalation sample) were found
  live-complete (`PilotRunLedger` rows `bugb-write-20260723T0905Z`,
  `20260723T091446-35a1bde5`, `buga-sample-20260723T0927Z`, all
  `status=completed`) even though `docs/pipeline-fidelity-gate.md` §9
  text still read "NOT YET RUN" for all three at task start — the page
  was stale, not the prerequisite work. Confirmed directly: 0
  `CardPrintingTag` rows carried `anonymous_id=stage-d-join-key-v1`
  pre-run (retraction fully cleared the 12,904 staged votes), and the
  live eligible pool was exactly 200,366 — matching the task's own
  "post-zeroing" expectation exactly. `docs/pipeline-fidelity-gate.md`
  §9/§12 updated in this same change to record this.
- Deploy freeze raised on tracking issue #154
  (`deploy-freeze-active` label, newly created — the one-time repo
  setup step `docs/infrastructure.md` flagged as not-yet-done) at
  2026-07-23T09:45Z, the same moment the run's `PilotRunLedger` row
  was created; removed at run completion (see LIVE STATE below).

## The command and its actual output

```
docker exec -w /MPCAutofill/MPCAutofill mpcautofill_django \
  python manage.py local_calculate_verdicts --run-id pilot-dry-20260723T094518Z
```

`PilotRunLedger` id **41**, `run_id=pilot-dry-20260723T094518Z`,
`command=local_calculate_verdicts`, `dry_run=True`, `status=completed`,
`git_sha=42a09b3c794f7cf8aca5eb1ca2d4f6cdaa2895a6` (matches the
worktree HEAD this run launched from), `votes_written=0` (dry-run
field convention — no write occurred), started `09:45:35.327378Z`,
finished `09:53:12.969723Z` (7m37s / 457s).

Verbatim counters:

```
[join-key] considered=200345 votes=would_cast=39253 no_match_votes=would_cast=61247
  skip_counts={'no-text': 83723, 'ambiguous': 85, 'border-mismatch': 14746,
               'frame-mismatch': 1250, 'copyright-year-mismatch': 41, 'no-evidence': 10}
[fallback] considered=0 votes=would_cast=0 skip_counts={}
[slow-path] considered=0 routed=would_cast=0 reason_counts={}
total_votes=would_cast=100500   (join-key match 39,253 + join-key no_match 61,247)
```

Eligible pool at launch: 200,366 (`_eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID).count()`,
live-verified immediately pre-run). `considered=200,345` is 21 fewer —
those 21 have `content_phash is None` and are skipped before the
evidence lookup (mirrors the command's own `continue` for that case,
not a counted skip reason). Arithmetic check: `39,253 + 61,247 + 83,723 + 85 + 14,746 + 1,250 + 41 + 10 = 200,355`; the 10-card gap
against `considered` is the `no-evidence` cards, which the command
counts in `skip_counts` but not in `cards_considered` (an ImageEvidence
row never existed for them, so they were never actually evaluated) —
confirmed by source read, not inferred.

**Blank-evidence abstentions (the tracked Bug-A gap)**: `no-text`
(OCR ran, produced no usable text) = **83,723**; `no-evidence` (no
`ImageEvidence` row at all yet) = **10**. Combined blank-evidence
abstention total = **83,733** of the 200,366-card pool (41.8%). This is
the single largest skip category by a wide margin and is the number the
owner's defer-tracking is keyed to.

**Data-quality caveat, discovered live, not previously documented**:
the Scryfall bulk-data cache (`scryfall_cache/default_cards.json`,
consumed by `_resolve_candidates_for_card`'s `is_back_face` check) does
not exist anywhere in the `mpcautofill_django` container (confirmed via
a full-filesystem `find`, not just a path miss) — `get_back_face_names`
degrades gracefully (logs a warning, returns an empty set, does not
crash) per its own docstring, but this means **every card in this run
was evaluated with `is_back_face` unconditionally false**. This does
not invalidate the run (a documented, non-crashing degrade path, not
silent data corruption), but it means any back-face-specific behavior
in candidate resolution was inert for the whole pool. Flagged as an
open item — see below.

## The fallback-channel structural finding

The actual command reported `[fallback] considered=0 votes=would_cast=0`.
This is **not** a data gap or a bug in this run — it is a structural
property of `_fallback_eligible_cards_queryset`, confirmed by source
read: it selects cards via
`CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True)`
and `CardScanLog.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason__in=JOIN_KEY_NO_HIT_SKIP_REASONS)`
— i.e. it reads the join-key pass's **persisted** rows. A dry-run
(`dry_run=True`) never writes those rows (by design — "compute and
count everything without writing"), so in the SAME invocation, the
fallback calculator has structurally nothing to consider. This is true
of `local_calculate_verdicts` regardless of flags/invocation shape —
there is no way to get a nonzero fallback dry-run count from the
shipped command as written. (`[slow-path] considered=0` is the same
root cause: it too reads join-key/fallback's persisted no-hit rows.)

### Read-only recovery of the true fallback numbers

Since the task's own CAPTURE requirement explicitly wants "fallback's
FIRST-EVER prod numbers," and the shipped command structurally cannot
produce them in one dry-run pass, a bounded, **zero-write** diagnostic
was built and run **twice** (independently, for determinism
confirmation) that:

1. Re-runs the join-key pass's own per-card loop in-memory, calling the
   exact same production functions (`_resolve_candidates_for_card`,
   `calculate_join_key_verdict`) — reproduced **exactly** the real run's
   own counters (`considered=200345 match=39253 no_match=61247`,
   identical `skip_counts`), confirming full-population determinism.
2. Builds the same "no confident hit" card_id population
   `_fallback_eligible_cards_queryset` would have selected had those
   rows actually been persisted (is_no_match=True OR skip_reason in
   `JOIN_KEY_NO_HIT_SKIP_REASONS`) — **161,092 cards**, applying that
   queryset's own remaining (non-persistence-dependent) filters.
3. Calls the actual production `calculate_fallback_verdict` function
   per eligible card — the exact function `run_fallback_calculator`
   itself calls, read-only, no DB writes anywhere in the script (no
   `.save()`/`.bulk_create()`/`.delete()`/`resolve_and_persist_printing`
   calls).

Both independent runs produced **identical** results:

```
fallback considered=161092
fallback votes_would_cast=29710
fallback skip_counts={'ambiguous': 86674, 'no-sub-check-evidence': 44558, 'eliminated': 150}
```

(`29,710 + 86,674 + 44,558 + 150 = 161,092`, exact.) This is the
fallback channel's **real first-ever numbers** against production
data — recovered faithfully via the same production code paths, never
written anywhere. Because in a real `--write` invocation the join-key
pass's votes/scan-logs ARE persisted before the fallback pass begins
(same process, sequential), this in-memory reconstruction is exactly
what a `--write` run's fallback pass would see and decide — not an
approximation.

### Combined per-channel breakdown (the pilot's own statistics)

| channel  | considered | positive match (would cast) | no_match / abstain votes                                 | skipped (no verdict)                                                       |
| -------- | ---------- | --------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------- |
| join-key | 200,345    | 39,253                      | 61,247 (is_no_match votes)                               | 99,845 (skip_counts, excl. no-evidence) + 10 no-evidence                   |
| fallback | 161,092    | 29,710                      | 0 (fallback never casts a no-match vote — module design) | 131,382 (86,674 ambiguous + 44,558 no-sub-check-evidence + 150 eliminated) |

Total positive-match votes a real `--write` pass would cast:
**39,253 + 29,710 = 68,963**. Total `CardPrintingTag` rows a real
`--write` pass would create (match + no_match, both channels):
**39,253 + 61,247 + 29,710 = 130,210**.

## Resource profile

- **Main dry-run** (ledger id 41): wall-clock 457s (7m37s, ledger-timed)
  / ~498s (8m18s, shell-timed including container-exec overhead) for
  200,345 considered cards → **~438 cards/s**. Peak `mpcautofill_django`
  RSS: **300.7 MiB**. Peak CPU: ~82% of one core. Postgres peak CPU:
  ~34%, RSS stable ~189–223 MiB. Host load average peaked at **1.09**
  (well under the 7.0 escalation threshold); no RSS threshold breach
  (well under the 4 GiB note-prominently bar, nowhere near the 16 GiB
  kill bar). `vmstat` samples throughout: iowait (`wa`) 0–1%, idle
  80–89%, `si`/`so` negligible (no swap pressure despite 1.5 GiB swap
  already in use host-wide from prior sessions) — no I/O contention.
- **Read-only fallback diagnostic** (two independent runs, each
  end-to-end): wall-clock **2,192–2,194s** (~36.5 min) each — phase 1
  (join-key re-derivation) 456–458s, phase 2 (population intersection)
  ~2s, phase 3 (fallback verdict computation over 161,092 cards)
  1,733–1,734s → **~93 cards/s** for the fallback phase specifically
  (materially slower per-card than join-key's ~438/s — expected, since
  every fallback-eligible card attempts a symbol-phash render/hash
  regardless of outcome, unlike join-key's early-exit no-text path).
  Peak `mpcautofill_django` RSS during this phase: **334.1 MiB**.
  Postgres CPU 23–34%. No resource threshold concerns at any point.
- Full docker-stats/vmstat snapshot log:
  `/home/ubuntu/.claude/jobs/e893dbef/tmp/pilot-dry-run-resources.log`
  and `pilot-dry-run-vmstat.log` (machine-local, not committed).

## Owner sample-audit package

150 card_ids, seed `20260723150`, drawn via
`random.Random(20260723150).sample(...)` **separately per channel**
(stratified, largest-remainder proportional allocation: join-key
85/39,253 population, fallback 65/29,710 population — 85+65=150) from
the two **positive-match** populations only (a no_match/abstain vote
has no "matched printing" to audit, so the sample is scoped to cards
the pilot would actually resolve to a printing). Per-card verdict detail
(matched printing, evidence fields) recomputed for just these 150 cards
via the same production functions, read-only.

Sheet: `/home/ubuntu/.claude/jobs/e893dbef/tmp/pilot-audit-sample.md`
(machine-local scratch, per the task's own instruction — not committed
to the repo). One line per card: card_id, card name, channel, matched
printing (set/collector#/canonical name), and the parsed evidence
fields it matched on (join-key: OCR set/collector-number + raw OCR
detail string; fallback: which evidence types survived the
border/artist/symbol intersection, plus the raw `layout_class`/
`artist_ocr_name`/`symbol_phash` fields). No images, no external
fetches — entirely from already-persisted `ImageEvidence` rows.

## Deviations from spec

1. **Fallback channel could not be measured by the sanctioned command
   invocation alone** — see "structural finding" above. Resolved via a
   bounded, zero-write, same-production-function diagnostic rather than
   a second `--write` invocation (which the task explicitly forbade) or
   a code change to the calculator itself (out of scope, and would
   touch `local_fallback.py`-adjacent logic without owner review).
2. **Two extra background scripts were written and run**
   (`fallback_readonly_diagnostic.py`, `build_audit_sample.py`,
   both under `/home/ubuntu/.claude/jobs/e893dbef/tmp/`, not committed)
   to recover the fallback numbers and build the audit sample. Neither
   performs any DB write — verified by code review (no `.save()`/
   `.bulk_create()`/`.delete()`/`resolve_and_persist_printing` calls
   anywhere in either script) and by the fact both ran twice with
   identical results and the live `CardPrintingTag`/`CardScanLog`
   counts for `stage-d-fallback-v1` remained 0 throughout (spot-checked
   after both diagnostic runs).
3. **`docs/pipeline-fidelity-gate.md` §9/§12 updated in this same
   change** to record B(i)/B(ii)+B(iii)/(c) as live-verified DONE (they
   were already complete when this task started; the page text hadn't
   caught up) and to record this run's own §9(d) outcome — per this
   repo's own "update the docs your own work touches in the same PR"
   convention. A gap was also flagged there: none of B(i)/B(ii)+B(iii)/(c)
   has its own `docs/data/` report (the page's own stated convention for
   every run in the sequence) — not written retroactively here, as it's
   outside this task's own mandate (§9(d) only).

## Open items / decisions needed

1. **Owner sample audit** (the next fire-sequence step) — sheet ready
   at the path above; needs the owner's own eyes before `--write` can
   run.
2. **Scryfall bulk-data cache is missing from the production container**
   — `is_back_face` was unconditionally `False` for this entire run
   (and for every prior Stage D dry-run/reparse run on this container,
   by the same mechanism). Needs an owner decision: is this an
   acceptable, already-known gap (if so, worth a `docs/troubleshooting.md`
   entry so it stops being rediscovered), or does it need fixing (the
   cache file re-fetched/re-mounted) before the real `--write` pass,
   since back-face resolution could plausibly change some candidates
   set for double-faced cards specifically.
3. **B(i)/B(ii)+B(iii)/(c) have no `docs/data/` report** — whoever ran
   them (not this task) should backfill one, or the owner should
   confirm it's not needed.
4. Given the fallback channel's true numbers are now known
   (29,710 would-be votes, ~18.4% of its own 161,092-card eligible
   pool), does this change any sizing assumption elsewhere in
   `docs/pipeline-fidelity-gate.md` (e.g. §6's consensus-impact
   projections) that was written before this number existed? Not
   checked in this task (out of the §9(d) mandate) — flagged for
   whoever picks up the sample-audit step next.
