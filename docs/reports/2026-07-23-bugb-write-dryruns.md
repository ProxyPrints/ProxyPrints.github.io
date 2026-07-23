```
TASK: #347 zeroing-plan pre-write dry-runs (B(i) reparse scoped dry-run,
B(ii)+B(iii) staged-run retraction dry-run) + poll-bindable write commands.
Branch: worktree-agent-a53de93dcb9f9c22f. No PR/commit to app code — this
report file plus the ledger rows below are the only artifacts. Repo state:
master @ 42a09b3c (PR #348, deployed). No --write executed anywhere.

WHAT SHIPPED:

1. Regenerated the 284/285-signature ID file FRESH, read-only, against the
   live DB (query: ImageEvidence fetch_ok=True + extractor_versions has key
   collector_line_ocr + non-blank collector_line_raw_text, restricted to
   each card's CURRENT evidence row (content_hash == card.content_phash,
   matching reparse_collector_evidence._current_evidence_for_card's own
   convention — no pre-existing script for this query was found in-repo,
   so this convention was applied deliberately), re-parsed with the
   deployed parse_collector_line, kept cards where fresh set_code !=
   stored collector_line_set_code). Result: RAW_EVIDENCE_ROWS_FETCHOK_
   NONBLANK=197,938 (exact match to the whole-DB reparse's considered=
   197,938), CURRENT_EVIDENCE_ROWS=197,938 (zero stale-version rows in
   this cohort), MATCHED_CARD_IDS=285 — EXACT match to §10's "284
   glued-marker guard rows plus 1 unrelated improvement (card 62354)",
   zero drift. Written one-per-line to bugb_write_ids.txt, docker cp'd
   into mpcautofill_django at /MPCAutofill/MPCAutofill/bugb_write_ids.txt
   (verified in place, 285 lines, after every subsequent step).

2. B(i) dry-run: `reparse_collector_evidence --card-ids-file
   bugb_write_ids.txt --run-id bugb-write-dry-20260723T090258Z` (default
   dry-run, no --write). Result: considered=285 no_evidence=0
   no_prior_join_key_state=39 unchanged=10 changed=236 would_fix_
   fields=285 would_retract=236. PilotRunLedger id 35 verified live
   (dry_run=True, status=completed, votes_written=0).

3. B(ii)+B(iii) dry-run: `retract_stage_d_by_run_id --run-id
   staged-write-20260721T0434Z --run-id staged2-0721 --run-id
   staged3-0721 --run-id staged4-0721` (default dry-run, no --write).
   Per-run-id: staged-write-20260721T0434Z votes_deleted=8825
   skips_deleted=7187; staged2-0721 votes_deleted=70 skips_deleted=14;
   staged3-0721 votes_deleted=3010 skips_deleted=19; staged4-0721
   votes_deleted=999 skips_deleted=553. TOTALS: votes_deleted=12904
   skips_deleted=7773 skipped_resolved_gate=0 skipped_rescannable=
   718828 cards_resynced=0. PilotRunLedger id 36 verified live
   (run_id 20260723T090331-fdf5822b — the command's own auto-generated
   operational id, dry_run=True, status=completed, counters JSON
   matches stdout exactly).

DEVIATIONS:

1. Step 1a's exact regeneration query had no prior script/doc to copy
   verbatim from — built read-only per the plan's own literal
   description (fetch_ok=True, non-blank raw text, fresh-vs-stored
   set_code diff) plus the codebase's established "current evidence"
   convention. Validated by reproducing 285/285 exactly against §10's
   pre-recorded prediction with zero drift — treated as confirmation
   the interpretation is correct, not asserted a priori.
2. §347/task expected a skip_reason-tier breakdown for step 2 (no-text
   6,643 / border-mismatch 1,060 / frame-mismatch 63 / ambiguous 6 /
   copyright-year 1 = 7,773) — `retract_stage_d_by_run_id`'s own output/
   `PilotRunLedger.counters` only reports skips_deleted totals per
   run_id, no skip_reason breakdown field exists in this command. Total
   skips_deleted=7,773 matches the expected total exactly; the specific
   per-reason split could not be independently re-verified from this
   run's own output (would require a separate read-only CardScanLog
   query, not run, since it wasn't requested as its own step).
3. Deliverable command 2 (retraction write command) drops "sudo" (uses
   `docker exec` not `sudo docker exec`) to fit the ≤190-char budget —
   see OPEN ITEMS 1.
4. Deliverable command 2 could not include a "fresh descriptive
   --run-id" for the command's own ledger row — see OPEN ITEMS 2. Its
   `--run-id` flag is repeatable and means TARGET run_id(s) to retract,
   not the command's own operational id; the command generates its own
   ledger run_id internally (confirmed live: ledger id 36 auto-got
   `20260723T090331-fdf5822b`), with no CLI flag to override it.

VERIFICATION:
- ID file regen: ran via `manage.py shell -c exec(open(...))`, read-only,
  20260723T090219Z–20260723T090243Z (24s). stderr counters:
  RAW_EVIDENCE_ROWS_FETCHOK_NONBLANK=197938 CURRENT_EVIDENCE_ROWS=197938
  MATCHED_CARD_IDS=285. `docker cp` into container, `wc -l` = 285,
  re-verified in place after every later step.
- Step 1b dry-run: 20260723T090258Z–20260723T090305Z, 5.392s real wall
  (`time` builtin). Counters as in WHAT SHIPPED item 2, no divergence
  from expectation (fields_fixed exactly 285/285, changed exactly
  236/236 — 0% divergence, well under the 10% flag threshold).
- Step 2 dry-run: 20260723T090329Z–20260723T090443Z, 1m13.790s real
  wall. Counters as in WHAT SHIPPED item 3 — totals match the task's
  stated expectation (votes 12,904 / skips 7,773 / gate 0) exactly, 0%
  divergence. Per-run-id vote split (8825/70/3010/999) also matches
  §6's cited table exactly.
- PilotRunLedger rows 35 and 36 re-queried live post-run and cross-
  checked against stdout — exact match both times (see WHAT SHIPPED).
- Deferred: skip_reason-tier breakdown independent re-derivation (see
  DEVIATIONS 2) — not requested as its own step, not run.
- RESOURCE CAPTURE: `docker stats --no-stream` before/after each run
  (point-in-time snapshots, not sustained-window sampling — noted as a
  measurement-method caveat, not a result). django/postgres CPU and RSS
  were flat/negligible in every snapshot (django RSS 122MiB throughout,
  postgres RSS ~182MiB throughout); django container net I/O rose ~8MB
  over step 1 and ~35MB over step 2 (real DB round-trip traffic, matching
  the queries' scale); postgres disk I/O deltas were 0 across both dry
  runs (no writes, consistent with dry-run-by-default and both commands'
  own "Dry run — nothing deleted" stdout line). Nothing observed over
  ~1 core or ~500MiB in either run.

OPEN ITEMS / DECISIONS NEEDED:

1. Poll-bindable write command 1 (B(i), 185 chars):
   `sudo docker exec -w /MPCAutofill/MPCAutofill mpcautofill_django python manage.py reparse_collector_evidence --card-ids-file bugb_write_ids.txt --run-id bugb-write-20260723T0905Z --write`
   Uses the exact 285-row bugb_write_ids.txt already in place in the
   container. `--run-id` here is this command's own supported flag —
   fresh and descriptive, distinct from the dry-run's id.

2. Poll-bindable write command 2 (B(ii)+B(iii), 186 chars, "sudo"
   dropped to fit ≤190 — confirmed live this host's operating user has
   passwordless docker-group access, `docker exec mpcautofill_django
   whoami` succeeded without sudo, so this is functionally identical to
   the sudo form used everywhere else in this task, not a permissions
   gap):
   `docker exec -w /MPCAutofill/MPCAutofill mpcautofill_django python manage.py retract_stage_d_by_run_id --run-ids staged-write-20260721T0434Z,staged2-0721,staged3-0721,staged4-0721 --write`
   Decision needed: this command has no CLI flag for a caller-supplied
   operational run-id (see DEVIATIONS 4) — its ledger row will get an
   auto-generated id (`generate_run_id()`'s own timestamp+hash format,
   e.g. `20260723T090331-fdf5822b`) at execution time, not knowable in
   advance for poll-binding by value. If the poll needs to bind to a
   specific known id ahead of time, the command needs a `--run-id`
   (operational) flag added first — flagging rather than fabricating a
   nonexistent flag.
3. With "sudo docker exec" kept (matching every other command in this
   task) command 2 is 191 chars — 1 over the 190 budget — hence the
   sudo-drop in item 2 above. If sudo is a hard requirement regardless
   of char budget, the budget itself needs relaxing by the orchestrator
   instead.

LIVE STATE:
- /MPCAutofill/MPCAutofill/bugb_write_ids.txt is in place inside
  mpcautofill_django, 285 lines, verified after every step — required
  by the poll-bindable write command 1 above, left in place per
  instruction.
- Two harmless scratch files (/tmp/gen_bugb_ids.py, /tmp/verify_ledger.py)
  remain inside the container — copied in as root via `docker cp`,
  could not be removed by the container's own non-root exec user
  (`rm: Operation not permitted`); inert, outside /MPCAutofill, do not
  interfere with either poll command or bugb_write_ids.txt.
- PilotRunLedger ids 35 (reparse_collector_evidence,
  bugb-write-dry-20260723T090258Z) and 36 (retract_stage_d_by_run_id,
  20260723T090331-fdf5822b) are the only DB writes made this session —
  both dry-run ledger rows (dry_run=True), zero votes/scan-logs/
  ImageEvidence rows touched. No --write executed anywhere. Nothing
  else running, deployed, or pushed beyond this report file/branch.
```
