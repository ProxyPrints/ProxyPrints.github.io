# Stage D join-key + slow-path staged write — verification (2026-07-21)

Read-only verification of the Stage D `local_calculate_verdicts --write` run
the owner authorized and executed directly against prod
(`mpcautofill_django`, claim `run-e6ab18dc4bcc-1376136`), following the
preceding dry-run of the same command. This session did not run the write —
it verifies the resulting row counts, the gate check, and the review-queue
implications against what already landed, and reports the result. No writes
were made to any live database or index from this session; every figure
below comes from a `SELECT`/`count()`/pure-function re-derivation run
against the live DB, or from the two runs' own logs.

## Run parameters

- Command (owner-executed): `local_calculate_verdicts --write --run-id staged-write-20260721T0434Z` (join-key calculator, then the slow-path routing calculator, same invocation/run_id — see `MPCAutofill/cardpicker/management/commands/local_calculate_verdicts.py`).
- `run_id`: `staged-write-20260721T0434Z`
- Preceding dry-run: `staged-dryrun-20260721T0423Z` (`--write` withheld), same command.
- `PilotRunLedger` confirms both invocations: `staged-dryrun-20260721T0423Z` (`dry_run=True`, `status=completed`, `votes_written=0`), `staged-write-20260721T0434Z` (`dry_run=False`, `status=completed`, `votes_written=8925`).
- Logs: `~/staged-dryrun-20260721T0423Z.log`, `~/staged-write-20260721T0434Z.log` (owner's home directory on the host, not in this repo).
- Code path calls PROTECTED CORE only via its public functions — `local_calculate_verdicts.py` imports `render_set_symbol`/`classify_frame_style`/`frame_style_is_consistent`/`match_artist` from `local_fallback.py` and calls `resolve_and_persist_printing`/`resolve_printing` from `printing_consensus.py` (both on `docs/upstreaming/license-provenance.md`'s protected-file list), duplicating only the Hamming-distance arithmetic (the same "reimplement the arithmetic, not the protected decision logic" pattern `local_identify_printing_tags._classify_no_clear_winner` already established) — no protected-core file was modified to build this run's calculator.

## Dry-run vs. write reconciliation

**Join-key calculator stage: exact match.**

| metric         | dry-run (`staged-dryrun-...`) | write (`staged-write-...`) |
| -------------- | ----------------------------- | -------------------------- |
| considered     | 20,677                        | 20,677                     |
| votes (match)  | 3,749 (would_cast)            | 3,749 (written)            |
| no-match votes | 5,176 (would_cast)            | 5,176 (written)            |
| skip_counts    | identical dict (below)        | identical dict (below)     |
| total_votes    | 8,925 (would_cast)            | 8,925 (written)            |

skip_counts (both runs, identical): `no-evidence` 179,707, `no-text` 9,675, `proxy-marker-veto` 1,533, `border-mismatch` 507, `frame-mismatch` 35, `ambiguous` 2.

**Slow-path calculator stage: NOT identical — the dry-run tested nothing here. Flagging this prominently, not softening it.**

| metric        | dry-run | write                                                                                                                              |
| ------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| considered    | **0**   | 16,928                                                                                                                             |
| routed        | **0**   | 16,928                                                                                                                             |
| reason_counts | **{}**  | `parsed-but-no-match` 5,176, `no-text` 9,675, `proxy-marker-veto` 1,533, `border-mismatch` 507, `frame-mismatch` 35, `ambiguous` 2 |

Root cause, confirmed by reading `local_calculate_verdicts.py` directly (not
inferred): the slow-path calculator's own eligibility query
(`_slow_path_eligible_cards_queryset`) looks for cards with an _already-
persisted_ `CardPrintingTag(is_no_match=True)` or `CardScanLog` skip row
under the join-key calculator's `anonymous_id`. In a dry run, the join-key
stage computes its counts entirely in memory and writes nothing — so when
the slow-path stage runs immediately afterward in the _same_ dry-run
invocation, its DB query against `stage-d-join-key-v1` finds zero rows,
because none exist yet. `considered=0`/`routed=0`/`reason_counts={}` is
therefore not evidence the slow-path logic is broken or that anything
changed between runs — it is a structural consequence of dry-run mode
never persisting the upstream stage's output for the downstream stage to
read. The write run's slow-path figures are internally self-consistent
(16,928 = 5,176 no-match + 9,675 + 1,533 + 507 + 35 + 2, exactly the
join-key stage's own no-match-plus-non-rescannable-skip total), and every
field it needed already existed in `CardPrintingTag`/`CardScanLog` before
it ran. But the **practical conclusion is that the slow-path stage was
never actually dry-run-tested before the real write** — the dry run's
"identical counts" claim holds for the join-key/vote-count portion only,
not for slow-path routing. This is worth carrying forward as a caveat on
any future dry-run of this same two-stage command.

## Vote-count verification (`CardPrintingTag`, `anonymous_id="stage-d-join-key-v1"`)

```
CardPrintingTag.objects.filter(anonymous_id="stage-d-join-key-v1")
  total:                8,925
  is_no_match=True:     5,176
  is_no_match=False:    3,749
```

Matches the write log exactly (3,749/5,176/8,925). Checked for other-run
attribution under this `anonymous_id`: `.values_list("run_id", flat=True) .distinct()` returns exactly one value, `staged-write-20260721T0434Z` — no
pre-existing v1 votes from an earlier run exist to reconcile against; this
is this `anonymous_id`'s first-ever write. `PilotRunLedger` carries a row
for both the dry-run and the write run (dry-run `votes_written=0`, which is
expected and not a discrepancy — the ledger's `votes_written` field is only
ever populated from the actual-written count, never the would-cast count,
so a dry run always shows 0 there regardless of what it projected).

## Slow-path routing verification (`CardScanLog`, `anonymous_id="stage-d-slow-path-v1"`)

```
CardScanLog.objects.filter(anonymous_id="stage-d-slow-path-v1")
  total:                 16,928
  distinct run_id:       ["staged-write-20260721T0434Z"]  (single run, no other attribution)
  skip_reason:           100% "to-review" (the routing marker, not a genuine abstention reason)
  distinct card_id:      16,928  (exactly 1 row per card — no duplicate routing)
```

Matches the write log's `[slow-path] routed=written=16928` exactly, and its
`reason_counts` breakdown (via the join-key stage's own scan-log/no-match
records that fed it) also matches exactly:
`parsed-but-no-match` 5,176, `no-text` 9,675, `proxy-marker-veto` 1,533,
`border-mismatch` 507, `frame-mismatch` 35, `ambiguous` 2 → sum 16,928.

Also verified the join-key stage's own `CardScanLog` rows (its skip-reason
side, `anonymous_id="stage-d-join-key-v1"`): 191,459 rows, breaking down as
`no-evidence` 179,707 / `no-text` 9,675 / `proxy-marker-veto` 1,533 /
`border-mismatch` 507 / `frame-mismatch` 35 / `ambiguous` 2 — exactly the
log's skip_counts dict, confirmed as real rows, not just a log-line claim.

## Gate check — independently re-derived, not just re-read from the log

The log's own claim: `Gate check passed: 0/8925 touched cards resolved machine-only.` This session re-ran the check independently, via the same
pure function the command itself calls (`printing_consensus.resolve_printing`,
never `resolve_and_persist_printing`, which would write) against the full
touched-card set freshly queried from the DB — not by trusting the log line:

```
touched_ids = CardPrintingTag.objects.filter(
    run_id="staged-write-20260721T0434Z", anonymous_id="stage-d-join-key-v1"
).values_list("card_id", flat=True)   # 8,925 cards

for card in Card.objects.filter(pk__in=touched_ids):
    if resolve_printing(card) is not None:
        violations.append(card.pk)

violations: 0 / 8925
```

Cross-checked a second, independent way against the persisted denormalized
cache (`Card.printing_tag_status`, kept in lockstep by
`resolve_and_persist_printing` at write time): `Card.objects.filter(pk__in= touched_ids).exclude(printing_tag_status="unresolved").count()` → **0**.
Both independent checks agree with the log's own claim: **0/8,925 touched
cards resolved from this single, low-weight machine pass alone** — the
human-backed consensus gate held throughout this run.

## Review-queue implications

Three related but distinct numbers came out of this verification — stating
which one **is** "the queue" and how the other two relate, per the task's
own instruction not to just list them:

1. **16,928 — this run's own new addition to the queue** (the slow-path
   `to-review` `CardScanLog` rows created by this write). This is the
   number the run facts highlighted as "the human bottleneck number," and
   it is real, but it is a _delta_, not the queue's size.
2. **211,065 — the printing-only backlog** (`Card.objects.filter( printing_tag_status="unresolved", card_type=CARD).count()`), i.e. every
   card still needing a human printing-identification decision, regardless
   of source or how it got there (this run's slow-path routing, an earlier
   engine's skip, or a card no engine has touched at all yet). Confirmed
   that all 16,928 of this run's newly-routed cards are a subset of this
   211,065 (`still_unresolved == 16928` when filtered against this set) —
   the slow-path marker doesn't add a second queue, it flags a subset of
   this existing one with attached raw signals for a reviewer.
3. **218,243 — the combined "What's That Card?" question-feed total**
   (`question_feed.get_remaining_estimate().total`), which is the actual
   live queue-size figure the frontend's review surface itself uses. It is
   larger than (2) because it's a `.distinct()` union across printing,
   artist, _and_ tag review needs, not printing alone — a card can be
   printing-resolved but still need an artist or tag decision, and vice
   versa. (Also returned: `confirmable=89,655`, `contested=1,202`,
   `fresh=218,243` — `fresh` happening to equal `total` here is a real
   query result, not a bug: nearly the entire backlog is currently
   "fresh," i.e. not already flagged contested, so the union collapses to
   the fresh tier almost exactly at today's snapshot.)

**Read: (3) is the queue as the product actually presents it; (2) is the
printing-specific slice of it that this run's calculators operate on; (1)
is what this one write run added to (2), fully contained within it.** None
of these three numbers moved as a _result_ of this run in a way that
resolved anything — this was a funnel-to-review pass by design (module
docstring: "a single calculator's vote... can never alone resolve a card"),
so the queue only grew (via the 16,928 newly-flagged cards getting a
durable `to-review` marker with attached signals), never shrank.

## Reversibility

Both runs are independently purgeable via the existing
`purge_machine_votes --run-id <id>` management command (confirmed present
at `MPCAutofill/cardpicker/management/commands/purge_machine_votes.py`),
scoped by the exact-match `run_id`/`anonymous_id` pair used throughout this
run:

- `CardPrintingTag.objects.filter(run_id="staged-write-20260721T0434Z", anonymous_id="stage-d-join-key-v1")` — 8,925 rows (3,749 match votes, 5,176 no-match votes).
- `CardScanLog.objects.filter(run_id="staged-write-20260721T0434Z")` — covers both the join-key stage's own skip rows (191,459, `anonymous_id="stage-d-join-key-v1"`) and the slow-path routing rows (16,928, `anonymous_id="stage-d-slow-path-v1"`).

A purge of this `run_id` reverts every vote and every scan-log row this run
wrote, and (per `resolve_and_persist_printing`'s own re-resolution on
purge) would restore the touched cards' `printing_tag_status` cache to
whatever it was before this run — no separate manual cache-fix needed.

## Next-step options

1. **The 197,428-card Stage C remainder.** Confirmed current, not stale:
   `Card.objects.filter(content_phash__isnull=False).count()` = 218,228
   (Stage C's own eligibility filter, per `run_image_evidence_cohort.py`),
   minus 20,800 distinct cards with an `ImageEvidence` row today (400 +
   400 + 20,000 across the three runs to date) = 197,428, matching the
   `2026-07-21-stagec-20k-extraction.md` report's own arithmetic exactly —
   no further Stage C extraction has happened since that report, so this
   number hasn't moved. A full-catalog Stage C harvest of this remainder
   needs its own separate owner GO per Stage E's resume-contract gate, same
   as noted in that report; Stage D's join-key/slow-path calculators can
   only ever operate on cards Stage C has already extracted evidence for,
   so growing that 20,800-card base is the actual lever on both the
   join-key/no-match/skip counts above and the review-queue's growth rate.
2. **Review-queue tooling/prioritization.** With 211,065 cards needing a
   printing decision (16,928 of them now carrying durable, structured raw
   signals via this run's slow-path routing) and a combined question-feed
   total of 218,243, the review side is now the larger of the two open
   bottlenecks — not resolved by this verification, a genuine follow-up
   task: e.g. does the question feed's existing tier ordering
   (`_tier_1_confirm_suggestion`/`_tier_2_contested`/`_tier_4_fresh`) need
   a new tier that prioritizes slow-path-routed cards (which carry richer
   signals than a bare "fresh" card) ahead of the undifferentiated fresh
   pool? That's a product/UX decision, not something this verification
   session should decide.

## Live API

Not independently re-checked in this verification session (read-only, DB/log
queries only) — the owner's authorized run channel already covered live-API
health as part of executing the run; this session did not restart or touch
any container beyond issuing read-only Django-shell queries against the
already-running `mpcautofill_django` container.
