```
TASK: Catalog-completion Part 3, fullrun dry-run aftermath (HOLD #P3
conditional-go). Worktree: catalog-completion-part2. run_id
part3-fullpass-dryrun-01.

WHAT SHIPPED:
- PR #60 merged (14:25:57Z) citing the explicit authorization message
  as the human review the classifier hold was waiting for.
- PR #63 (Level 2 stale-filter fix) merged - frontend-only, CI green,
  no flake.
- Fullrun container exited (exit code 0) at 14:34:58Z.

MISTAKE, STATED PLAINLY: the container's stdout - the ONLY place the
per-engine recovery breakdown (phash/OCR/fallback recovered counts,
unrecovered, cards_considered) was ever going to exist - is LOST. I
flagged the --rm-vs-log-capture race as a risk before it happened and
built a background `docker wait` + `docker logs` capture specifically
to beat it; the mitigation didn't close the window. By the time the
capture's `docker logs` call ran, `--rm` had already deleted the
container. This is the same class of self-caused error as the earlier
fallback "out of scope" mistake - not softening it.

What IS recoverable, confirmed via direct query against
`PilotRunLedger` (mpcautofill_django, live DB):
  run_id=part3-fullpass-dryrun-01 status=completed dry_run=True
  git_sha=3b59bc74 started_at=13:14:11Z finished_at=14:34:58Z
  votes_written=0 elapsed=80.8min

This confirms: the run completed without crashing (status=completed,
not failed), and zero real votes were written (dry_run=True,
votes_written=0) - HOLD #P3 was NOT breached by this run regardless
of what happens next. It does NOT confirm the per-engine numbers
condition (a) of the conditional go requires.

Checked whether the breakdown survives anywhere else before treating
it as lost: grepped local_residual_classify.py and its management
command on master - `PilotRunLedger.save()` only ever writes
status/finished_at/votes_written (an aggregate, correctly 0 for a dry
run by the command's own gating). `FrameMismatchRecoveryResult`'s
per-engine fields (phash_recovered, ocr_refetch_recovered,
fallback_refetch_recovered, cards_considered, unrecovered) reach only
print() - never the DB, never a file. Confirmed dead end, not
assumed.

Weak circumstantial evidence only: 80.8min elapsed against the
~35min fetch-only estimate is consistent with the run processing
close to the full ~5,773-card OCR+fallback population once real
per-card CPU cost (tesseract OCR, fallback border/artist/symbol
detection) is priced in on top of fetch latency - this repo's own
soak-test findings (65f3fa6a) already established the pipeline is
CPU-bound, not I/O-bound, so this ratio is plausible rather than
alarming. This is NOT a substitute for the real per-engine numbers
and I'm not treating it as satisfying condition (a).

DEVIATIONS: none from the queue as given - this is a failure to
deliver on a condition, not a scope change.

OPEN ITEM / DECISION NEEDED (real fork, not mine to resolve alone -
the next step spends ~80min + ~1.3GB against the shared CDN limiter
either way):

1. RE-RUN A PROPERLY-CAPTURED DRY RUN first (no --rm this time, or
   redirect stdout to a bind-mounted file), verify (a)/(b) for real,
   then proceed to --write only if they hold. Costs ~80min + ~1.3GB
   now, then the write pass itself costs the same again after
   (confirmed no write-from-enumeration path exists, per the earlier
   fetch-economy answer - recompute is unavoidable regardless).
   Total: ~160min + ~2.6GB across two passes. This is the only path
   that actually honors the conditional go's sequencing (verify
   BEFORE any real vote is cast) - condition (a) exists specifically
   to catch an anomaly before it reaches a real vote, so folding
   verification into the write pass's own live output would let any
   anomaly write real votes for every card processed before it's
   noticed.
2. Proceed straight to --write now (PR #60 is merged, satisfying
   condition (c)) and treat its own live output as the verification.
   Faster (~80min + ~1.3GB total, one pass) but this quietly weakens
   what "IF AND ONLY IF (a) the dry-run block shows counts consistent
   with expectations" was designed to gate - by the time an anomaly
   showed up in the live output, real votes for prior cards in the
   same pass would already be written.

I'm holding here rather than picking one - recommend option 1 for
fidelity to the condition as written, but flagging that this is a
real cost/production-limiter call, not a default I should make
silently.

LIVE STATE: no container running. No votes written anywhere (verified
via direct CardArtistVote/CardTagVote count-by-run_id query: 0/0).
Ledger row exists and is COMPLETED/dry_run=True/votes_written=0.
Waiting for direction on option 1 vs 2 above before spending the next
~80min fetch window.
```
