# Catalog-completion plan (six-part package)

Tracked-in-git plan for the local printing-ID pilot's post-full-run work,
superseding the plan-mode scratch file at `~/.claude/plans/scalable-baking-cascade.md`
(session-local, not committed — that file's Part 1 detail is migrated into
this doc; treat it as stale from here on). Written after a mid-session rate
limit interrupted execution and the plan had to be reconstructed from the
conversation transcript — the lesson driving this doc's existence: **the
plan lives in git, not in a scratch file**, so a lost session can recover
state from `git log`/`git status` alone.

Owner context: the project is prioritizing ETA and will aggressively
stop → merge → rebuild → restart the live full-catalog run to fold in
improvements as they land. Part 1 exists to make that iteration style safe
and ships first, alone, held for review before anything else proceeds.

**Order**: Part 1 → HOLD #A → Parts 2+3 in parallel → Part 4 → HOLD #B →
Part 5 → HOLD #C → Part 6 (after the main run's final report). Test suite
green at every merge point; this doc updated at each hold.

**No new tags anywhere** — altered-frame and custom-art (already seeded)
are the only classification targets across every part below.

---

## Part 1 — Run-cohort safety (merged, PR #28)

Revocability via a **separate column**, never an `anonymous_id` suffix.
Confirmed via two parallel research passes (git history in this branch's
commits will show the investigation): every production call site treats
`anonymous_id` as an exact-match token — no prefix matching exists
anywhere — and the idempotence/resume mechanism
(`_eligible_base_queryset`'s `.exclude(printing_tags__anonymous_id=anonymous_id)`
in `cardpicker/local_identify_printing_tags.py`) depends on the _same
literal string_ being reused across every invocation of a given engine.
`anonymous_id`'s `max_length=40` is also a hard blocker on its own: a
stamped `"deductive-backfill-v1/..."` is 46 chars, `"local-name-frequency-v1/..."`
is 48 — both exceed it. A separate field sidesteps both problems: exact-
match semantics stay completely untouched, zero blast radius on existing
exclusion/resume/uniqueness logic.

### 1. Schema

Add to `AbstractWeightedVote` (`cardpicker/models.py:550-578` — the shared
abstract base for `CardPrintingTag`/`CardArtistVote`/`CardTagVote`,
currently ending with a `peer` field whose "federation-readiness stub, no
import path sets this yet" docstring convention this field should match):

```python
run_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
```

`max_length=64` (not 40 like `anonymous_id` — nothing here is exact-match-
reused across invocations, no analogous risk). Never set on human-submitted
votes (`views.py`'s `post_submit_*` views construct votes with no `run_id`
kwarg — stays NULL there). One `AddField` migration wave adds the column to
all three models simultaneously, mirroring how migration
`0054_cardartistvote_peer_cardprintingtag_peer_and_more.py` rolled out
`peer`.

New, separate, non-abstract model `PilotRunLedger` (added in the same
migration since both changes landed in the same commit — Django's
autodetector naturally bundles them and there's no data-migration/
dependency reason to force a split, unlike `0059_cardreport.py`'s
historical separation from `peer`'s rollout, which was circumstantial
timing, not a functional requirement):

```python
class PilotRunLedger(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    run_id = models.CharField(max_length=64, unique=True)
    command = models.CharField(max_length=64)
    dry_run = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    git_sha = models.CharField(max_length=40, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    votes_written = models.IntegerField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
```

A DB table over log-scraping: reachable from every context (host venv,
`docker compose run`, Django admin), survives log rotation, whereas the
existing `screen`→`full_run.log` redirect is a host-side artifact with no
reliable path back from inside a container. Keep the human-narrative
`journal/YYYY-MM-DD-*.md` convention completely separate — hand-maintained,
not auto-generated. The ledger is an **audit/context layer only** — the
purge command's actual delete target is always found by querying the vote
tables directly by `run_id`; a missing/inconsistent ledger row must never
block a purge. Register in `admin.py` for a free browsable view.

### 2. Generation and threading

`generate_run_id() -> str` in `local_identify_printing_tags.py` (co-located
with `verify_zero_resolutions`): `f"{timezone.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"`
(~24 chars) — timestamp + short random suffix, not a git SHA (the SHA is
logged separately, see §3; keeping run_id generation independent of
whether the git-SHA file happens to be present avoids coupling two
different failure modes together).

`run_pilot()` gets `run_id: Optional[str] = None` added to its signature;
`run_id = run_id or generate_run_id()` at the top (accepting an explicit
value keeps it deterministic for tests). As a local variable, the
`propagate_cluster_vote` closure picks it up automatically via closure
capture. Five `CardPrintingTag(...)` construction sites need `run_id=run_id`
added (cluster propagation, OCR/phash/fallback votes, name-frequency's own
vote), and three `local_fallback.cast_*_vote(...)` call sites in the write
loop need `run_id=run_id` threaded through as a new parameter on
`cast_border_attribute_vote`/`cast_frame_style_vote`/`cast_bleed_edge_vote`
in `local_fallback.py`.

`run_name_frequency_elimination()` is a separate invocation entrypoint (own
management command, own gate-check loop) — generates its **own** `run_id`,
not one shared with `run_pilot`.

`deductive_backfill.py`'s `run_backfill()` also casts machine votes and
would benefit from the same property — **out of scope for Part 1**, logged
as a known gap, not silently dropped.

Add `run_id: str = ""` to `PilotResult`/`NameFrequencyResult` so both
commands print it prominently (the operator needs it to target a future
purge).

### 3. Git-SHA build-info baking (best-effort visibility, not the hard gate)

`.dockerignore` excludes `.git` from the build context entirely, so the SHA
must be passed in from the host via `docker build --build-arg`, computed
before the build starts — it cannot be computed from inside the Dockerfile.

`docker/django/Dockerfile`: in the `builder` stage (so both
`webserver`/`worker` targets inherit it), after
`COPY MPCAutofill /MPCAutofill/MPCAutofill`:

```dockerfile
ARG GIT_SHA=unknown
RUN echo "$GIT_SHA" > /MPCAutofill/MPCAutofill/GIT_SHA
```

`docker-compose.prod.yml`: add `build.args: { GIT_SHA: ${GIT_SHA:-unknown} }`
to both `django` and `worker` services (currently absent entirely) — reuses
the exact `${VAR}` interpolation pattern already used for
`DJANGO_SECRET_KEY` etc. in the same file.

**Updated rebuild command** (replaces the plain `docker compose build`
everywhere it's referenced — Dockerized-execution section, scaling-
recommendation section of `docs/features/printing-tags.md`):

```bash
GIT_SHA=$(git rev-parse --short HEAD) docker compose -f docker/docker-compose.prod.yml build
```

`get_baked_git_sha() -> Optional[str]` in `cardpicker/utils.py` (reads
`Path(settings.BASE_DIR) / "GIT_SHA"`, `None` if absent). Logged
prominently at each command's startup and stored on the `PilotRunLedger`
row. Explicitly best-effort: capturing it depends on a host-side step that
could be forgotten, so it never blocks a start — that's §4.

### 4. Restart/staleness assertion (the hard gate)

`cardpicker/utils.py` (its first genuinely Django-introspecting function —
reasonable expansion of its role as the shared home for cross-cutting
operational helpers; `purge_machine_votes` has no other reason to import
from the pilot-themed `local_identify_printing_tags.py`):

```python
def find_stale_applied_migrations() -> list[tuple[str, str]]:
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.recorder import MigrationRecorder

    disk = set(MigrationLoader(connection, ignore_no_migrations=True).disk_migrations.keys())
    applied = set(MigrationRecorder(connection).applied_migrations().keys())
    return sorted(applied - disk)
```

Directly detects "the DB has migrations applied that this image's own code
doesn't know about" — the exact signature of the known stale-image bug
class (a `docker compose build` reporting "Successfully built" while a
BuildKit layer-caching bug ships old code underneath — the PR #24/#26
lesson), using pure DB+code introspection, independent of whether §3's
git-SHA capture worked.

Called at the **top of each management command's `handle()`**
(`local_identify_printing_tags`, `local_name_frequency_elimination`,
`purge_machine_votes`) — not inside the library functions, matching the
existing layering where `CommandError` is only ever raised at the command
layer. On a non-empty result: `raise CommandError(...)` with a clear
message, before any other work (before even the `[DRY RUN]`/`[WRITE]`
line) — no ledger row created, no votes written.

### 5. `purge_machine_votes` management command

New file `cardpicker/management/commands/purge_machine_votes.py`, following
`local_name_frequency_elimination.py`/`local_backfill_content_phash.py`'s
established CLI conventions (`[DRY RUN]`/`[WRITE]` prefix, clear counts,
`CommandError` on any violation).

`manage.py purge_machine_votes --run-id <id> [--dry-run]` — `--run-id` is
`required=True` (refuses to run without it, no accidental purge-everything).

1. Staleness check (§4) first.
2. Best-effort `PilotRunLedger` lookup for display context.
3. Query `CardPrintingTag`/`CardArtistVote`/`CardTagVote` by `run_id`,
   collect the union of affected card pks.
4. `--dry-run`: print counts, exit, nothing touched.
5. Real run: delete the three querysets, then **re-resolve every affected
   card** via the _persisting_ resolvers (printing/artist/tag consensus'
   resolve-and-persist functions — not the pure `resolve_*` functions,
   since deleted rows may have contributed to what's _currently stored_,
   which must actually be updated).

**Post-purge invariant, corrected from the original task framing**
("assert statuses return to pre-run state" is wrong and would false-
positive on the first real purge): with the real default weights
(`PRINTING_TAG_MIN_VOTES=2`, `PRINTING_TAG_AI_WEIGHT=0.5`, human vote
weight `1.0`, confirmed live in `settings.py:65-68`), 1 human vote + 2
agreeing machine votes sums to 2.0, clears threshold, resolves. Purging
those 2 machine votes correctly drops the weight below threshold and the
card **legitimately un-resolves** — correct consensus recalculation, not a
violation. The invariant actually worth asserting, mirroring
`verify_zero_resolutions`'s "structurally impossible but verify against
real data" spirit, stated precisely (per docs/features/printing-tags.md's
"Iteration safety" section, the canonical statement - implemented in
`verify_no_machine_only_resolutions`): for every affected card whose
`printing_tag_status` is RESOLVED, at least one surviving `CardPrintingTag`
vote for that resolved printing must be human-backed
(`source not in {VoteSource.DEDUCTION, VoteSource.OCR}`); identically per-tag
for `artist_vote_status`/`tag_vote_statuses`. A card is NOT required to
return to its pre-purge status - un-resolving is the expected, correct
outcome (reported separately, `cards_unresolved_by_purge`), never a
violation. Only a RESOLVED outcome with zero surviving human-backed votes
behind it is a violation — `raise CommandError(...)`, matching the existing
gate-violation
message/truncation style.

6. Print a summary; on success, set `purged_at=now()` on the
   `PilotRunLedger` row if found.

### 6. Documentation

New dated subsection in `docs/features/printing-tags.md` stating the full
safety-property set explicitly: **machine-votes-never-resolve** (existing,
unchanged), **NULL-filter/checkpoint restart-safety** (existing,
unchanged), **revocability** (new — `run_id` vs. `anonymous_id`'s distinct
roles spelled out), **staleness guard** (new). Update the rebuild command
everywhere the old one appears. Update `## Key files`, add a
`## Known gaps` bullet for `deductive_backfill.py`'s votes not yet carrying
`run_id`.

### 7. Tests

Extend `test_local_identify_printing_tags.py`: every vote from one
`run_pilot()`/`run_name_frequency_elimination()` call shares one non-null
`run_id`; two invocations produce distinct `run_id`s. New
`test_purge_machine_votes.py`: dry-run counts; a real purge + the corrected
post-purge assertion (mixed human+machine → un-resolves correctly, no
violation); a case with two different `run_id`s on the same card where
purging only one leaves it correctly still-resolved; a deliberately-
constructed machine-only-survivor case asserting `CommandError`. Extend
`test_utils.py` (already exists) with `find_stale_applied_migrations()`
tests via monkeypatched `MigrationRecorder`, plus confirming each
command's `handle()` raises before any ledger row or vote is written.
Ledger lifecycle test: RUNNING → COMPLETED, and RUNNING → FAILED on a
monkeypatched exception.

Manual end-to-end verification against a **disposable/throwaway DB only,
never the live full-catalog job's production DB**.

**HOLD #A — review before the migration is applied anywhere or any
restart-iteration resumes.** Every restart thereafter runs stamped.

---

## Part 2 — Pipelined `content_phash` backfill

Critical constraint found during investigation: the `lh4.googleusercontent.com`
full-tier image rate limiter (`image-cdn/src/utils.ts`'s
`fetchWithRateLimit`, Cloudflare Worker binding
`IMAGE_FULL_TIER_RATE_LIMITER`, configured in `image-cdn/wrangler.toml:41-43`
as `simple = { limit = 30, period = 10 }` = **3 requests/sec**) is shared
globally across live PDF export, live bulk download, and the pilot/
backfill's own fetches — added specifically because an earlier unattended
backfill script hammered this endpoint. "N fetch threads sized to saturate
the allowance" means N≈3-5, not a large pool — throughput beyond ~3/sec is
rate-limited regardless of thread count. A full backfill at that ceiling is
realistically **~15+ hours if run alone**, not the few-hours figure
informally assumed before this constraint was found.

1. 3-5 fetch-producer threads → bounded queue (depth ~2 batches: warm the
   hasher, bound memory) → single hash consumer (phash is ms-cheap, no
   benefit to parallelizing it against a rate-limited upstream).
2. Checkpoint-flush per batch as built; out-of-order completion is safe
   under NULL-filter idempotence — needs a real test proving it, since
   multi-producer fetch completion order isn't guaranteed the way
   `run_pilot`'s `ThreadPoolExecutor.map()` currently gets for free
   (that's a genuine architectural difference from Part 1's concurrency
   model, not a copy-paste of it).
3. One long-lived invocation (screen/tmux), internal batching — never
   per-batch `docker compose run` spinup.
4. **Sequencing recommendation: auto-start after the live full-catalog run
   completes, not a concurrent `--throttle` trickle.** Both are ultimately
   bottlenecked by the same shared limiter — running alongside the live
   job buys no meaningful extra throughput while risking contention with
   real user-facing traffic during a window the live job is already
   consuming Worker capacity. Sequencing after avoids that entirely at the
   cost of otherwise-idle wall-clock, the better trade for a background
   job with no deadline pressure.
5. Report the corrected wall-clock projection (pipelined vs. sequential,
   at the real 3/sec ceiling) when this part is built.

**WAIT vs. `--throttle` trickle, grounded in the pilot's real observed rate (2026-07-16)**:
the live pilot fetches exactly one image per candidate through the shared CDN Worker (confirmed
by reading `_compute_card` - one `fetch_card_image` call serves OCR, phash, and border/frame/
bleed classification together; phash's own candidate-hash comparisons hit Scryfall directly,
not this Worker, so they don't count against the shared ceiling). Measured over 1.5h of the
current post-restart run: **13,800 candidates in 5,400s = 2.556 req/s** - the pilot is CPU-bound
(OCR/phash/classification compute per candidate), not currently saturating the 3 req/s ceiling
itself, which is what leaves a **headroom of ~0.444 req/s (14.8% of the ceiling)** in principle.

Two scenarios, both starting from the pilot's remaining 152,170 candidates (16.5h at 2.556/s)
and the backfill's full 218,152-card backlog (0 hashed as of this writing):

- **WAIT** (pilot finishes undisturbed, backfill then runs alone at the full 3/s):
  16.5h + (218,152 / 3 ≈ 20.2h) = **~36.7h total**.
- **TRICKLE, optimistic case** (headroom is real and the limiter shares cleanly between
  unrelated callers - unverified assumption, not measured): trickle backfills
  `16.5h × 0.444/s ≈ 26,464 cards` (**12.1% of the backlog**) during the pilot's remaining run,
  then the remaining 191,688 cards finish at full 3/s once the pilot's done (~17.7h):
  16.5h + 17.7h = **~34.3h total** - a **2.5h (6.7%) faster** finish than WAIT, in the best case.

That 6.7% is the _entire_ case for trickling, and it rests on an unverified sharing-fairness
assumption about the Cloudflare Worker's token bucket under two unrelated concurrent callers -
exactly the kind of assumption that motivated building this rate limiter in the first place
(an earlier unattended backfill script hammered this same endpoint) and that caused a real
incident earlier in this same work session (an unverified concurrent-container assumption broke
the live pilot job outright). If the assumption is wrong even partially - the limiter doesn't
share as cleanly as modeled, or the pilot's own rate isn't as stably CPU-bound as one 1.5h
sample suggests - trickling directly steals throughput from a days-long production job for a
worst-case downside that's asymmetric with the 6.7%-best-case upside. And even in the optimistic
case, only 12.1% backlog coverage exists by the time the pilot finishes - nowhere near
"substantial" for Part 3's own needs (its own volume check already found near-zero coverage
uninformative at 0%; 12% isn't a meaningfully different starting point). **The arithmetic does
not overturn WAIT** - it's confirmed as the right call, not merely the safer-feeling one.

**Built** (2026-07-16): `run_content_phash_backfill` (`cardpicker/local_phash.py`) rewritten
around a sliding submission window (`concurrent.futures.wait(..., return_when=FIRST_COMPLETED)`)
instead of a `ThreadPoolExecutor` recreated per batch - one long-lived pool for the whole run,
window size `batch_size * queue_depth_batches` kept full at all times, checkpoint-flush as
completions arrive rather than in lockstep with a batch boundary. New
`TestPipelinedBackfillOutOfOrder` proves persistence is correct when completion order differs
from submission order (a later-submitted card finishing before an earlier one), and that
checkpoint-flushes happen progressively, not as one write at the end. All 5 pre-existing
backfill tests pass unchanged (`compute_content_phash_for_card` stays the per-card unit of
work, only the outer orchestration changed).

**Honest wall-clock correction, not an oversell**: at the real backlog size (218,152 cards, 0
hashed as of 2026-07-16) and the 3 req/sec shared ceiling, the floor is **~20.2 hours**
regardless of pipelining - `218,152 / 3 ≈ 72,717s`. Pipelining does **not** meaningfully reduce
this: the old per-batch design's actual wasted time was the gap between "fetch phase ends" and
"next batch's fetch phase starts" while a `bulk_update` runs, which is fast (~437 batches at
`batch_size=500` × well under 1s each ≈ a few minutes total, under 0.5% of the full run) - not
the dominant cost the naive "eliminate the gaps" framing might suggest. The real value of this
rewrite is **not** a wall-clock win; it's the checkpoint/idempotence guarantees now being
explicit and tested (a kill loses at most one window's worth of in-flight fetches, proven
correct under real out-of-order completion) rather than assumed. Confirms the plan's own
"~15+ hours if run alone" estimate was in the right ballpark; ~20.2h is the precise figure now
that the real backlog size is known. Per item 4 above, this still shouldn't run concurrently
with the live pilot - sequencing after remains the right call regardless of this correction.

**Start mechanism: documented manual step, not an unattended trigger.** WAIT means the
execution gate holds regardless of anything else landing (this PR, a future merge, an idle CI
run) - the backfill does not start while the pilot owns the CDN Worker capacity. No cron job,
no post-merge hook, no "starts automatically once X." After the pilot's own completion report
exists (its final summary in `pilot_full_run_logs/full_run.log` /
`journal/`), start it the same way the pilot itself is started - a `screen`/`tmux` session, run
by whoever is watching the pilot finish:

```bash
screen -dmS content_phash_backfill bash -c 'sudo docker compose -f docker/docker-compose.prod.yml run --rm -T worker \
  python manage.py local_backfill_content_phash --skip-checks \
  > /home/ubuntu/content_phash_backfill_logs/backfill.log 2>&1
echo "BACKFILL EXITED WITH CODE $?" >> /home/ubuntu/content_phash_backfill_logs/backfill.log'
```

Deliberately manual: this session had one incident already this week from an automated/
composed step firing at an assumed-safe moment that turned out not to be. A human confirming
the pilot has actually finished (not just "looks idle") before starting the next unattended,
multi-hour job is worth the few seconds of friction.

**Quota, resolved (2026-07-16)**: the backfill's 218k full-tier fetches exceed the Cloudflare
Workers free tier's 100,000 invocations/day cap on their own, independent of the shared 3 req/sec
rate limiter's own pacing (see `docs/features/image-cdn.md`'s "Full-tier requests" note - every
fetch, pilot or backfill, is one Worker invocation). Resolved by upgrading to Workers Paid
($5/month, 10M requests/month) the same day this was found - the 100k/day cap no longer applies.
The rate limiter itself is unchanged and un-removable by this upgrade - it's a Google-politeness
and live-traffic-fairness control, not a cost control, so the WAIT sequencing above and the
~20.2h wall-clock projection both still hold exactly as stated.

---

## Part 3 — Shared evidence-recovery module (write pass complete, merged 2026-07-18)

Insight: artist is a property of the ARTWORK, not the printing — art-
identity evidence supports artist votes even where printing votes are
correctly withheld (frame conversions). `CardArtistVote` + artist
consensus already exist (`cardpicker/artist_consensus.py`'s `resolve_artist`/
`resolve_and_persist_artist`, confirmed to share the exact same human-
backed gate as printing consensus via `vote_consensus.resolve_weighted_consensus` —
`resolve_artist` builds `VoteTuple`s with `is_human_backed=is_human_backed_source(vote.source)`,
identical wiring to `printing_consensus.resolve_printing`); this is a
producer for a built consumer.

The frame-mismatch pile yields **two votes per card** via **one shared code
path** — consumed by this part and Part 5, no duplicated frame-mismatch
logic between them.

1. **Volume check first** (gate on building at all): count cards with (a)
   a d=0 cluster sibling whose artist is known (resolved printing's
   Scryfall artist or resolved artist consensus), or (b) a withheld-
   printing frame-mismatch where art matched a known printing. If the
   combined number is small (<~2k), log-and-defer; report before building.
   **Blocked on Part 2 for (a)**: `Card.content_phash` is 100% NULL until
   the backfill runs (checked live, 2026-07-16: 0/218,152 populated) - a
   d=0 sibling relationship doesn't exist to count until real hashes
   exist. **(b) isn't a stored-data query at all**: frame-mismatch
   withholding drops the vote with zero DB trace (confirmed by reading
   the code path directly - the vote is never appended to the write
   batch), so getting a real count requires an actual fetch+OCR+frame-
   check compute pass, not a query. Re-run this check once Part 2's
   backfill has populated a meaningful fraction of `content_phash` for
   (a); (b) needs its own small sampling pass regardless.
2. **d=0 siblings** → `CardArtistVote`, `anonymous_id='art-hash-artist-v1'`
   (17 chars, fits well under `max_length=40`) + Part 1's `run_id`,
   confidence 0.9 (identical-image entailment).
3. **Frame-mismatch recovery (dual yield)**: art matched printing P, frame
   disagreed, printing vote withheld — the withheld-printing-vote code at
   `local_identify_printing_tags.py`'s frame-mismatch block (~lines
   990-1015) already computes `canonical` (the matched-but-withheld
   `CanonicalCard`) before discarding the printing vote; `canonical.artist`
   (a non-nullable FK on `CanonicalCard`, `models.py:74`) is directly
   accessible there even though the printing vote itself gets skipped.

   - (a) `CardArtistVote` for P's artist, confidence 0.8 (the art match is
     exactly as valid for artist as it was invalid for printing), and
   - (b) altered-frame positive `CardTagVote`, confidence 0.7 (real
     printing's art in a modified frame — the tag's literal definition),

   both under `anonymous_id='residual-classify-v1'` + `run_id`.

4. Verify artist consensus shares the human-backed gate (cite
   `test_artist_votes.py::TestResolveArtist::test_ai_only_insufficient` as
   the existing template); standard zero-resolution assertion post-write;
   spot-check propagated suggestions surface in the queue's artist
   question type (`question_feed.py`'s Tier 2 contested / Tier 4 fresh,
   both driven by current `artist_vote_status` — a new vote needs
   `resolve_and_persist_artist(card)` called for correct surfacing) and
   the "wrong?" pre-fill chain.

### Scan-log: persisted abstention evidence (built 2026-07-16)

Upgraded from propose-to-hold to build — restores the originally-intended
design (the bleed engine's negative-only votes and item 3 below's own
evidence-gathered-and-negative guard both presuppose that a durable
negative record exists somewhere, not just a positive one).

New `CardScanLog` model (`cardpicker/models.py`, migration `0063`,
additive-only): `(card, anonymous_id, run_id, skip_reason, scanned_at)`.
One row per engine abstention — `skip_reason` uses the pipeline's own
existing strings verbatim (`no-text`, `parsed-but-no-match`,
`too-many-candidates`, `no-hashable-candidates`, `no-clear-winner`,
`no-evidence`, `eliminated`, `ambiguous`, `frame-mismatch`,
`disagreement-with-other-engine`, `unfetchable-image`) — not a
separately-invented vocabulary, so a `grep` for a skip reason in the log
output and a `WHERE skip_reason = '...'` query agree. Voted cards get no
row (the vote is the record); batched into the existing checkpoint flush,
no per-card writes.

`RESCANNABLE_SKIP_REASONS = {"unfetchable-image", "frame-mismatch"}` stay
eligible for re-selection - a transient fetch failure isn't a conclusion
about the card, and `frame-mismatch` needs to stay revisitable so this
Part's own dual-yield step (above) can still process it for artist
extraction even though the printing vote stays withheld. Every other
reason is a genuine, repeatable negative conclusion against the same
deterministic image/candidates - re-scanning those would just burn CDN
budget to re-derive the identical answer.

`_eligible_base_queryset` and fallback's own `already_fallback_covered`
set both now exclude a card with a non-re-scannable scan-log row for that
engine, same per-engine exact-match idempotence pattern votes already
use. Implemented as an explicit `.values_list("card_id", ...)` subquery,
not a single `.exclude(Q(...) & ~Q(...))` on the to-many `scan_logs`
relation - the latter looks equivalent but isn't: Django translates a
negated lookup on a multi-valued relation into its own independent
`NOT EXISTS(...)`, not a same-row condition, so a card with both a
rescannable AND a later non-rescannable row would have incorrectly stayed
eligible under that formulation. Caught by
`TestScanLog::test_a_later_non_rescannable_reason_overrides_an_earlier_rescannable_one`
before it shipped, not assumed correct from how the query reads.

Progress line rewritten: `this invocation N/total (unseen-remaining M)`
plus the corpus-wide unresolved count reported separately (the two move
for different reasons - this invocation's own pool doesn't shrink from
other engines' or humans' activity, the corpus-wide count does), plus a
real rate/ETA computed from elapsed wall-clock since this invocation
started, not a guess.

**What this dissolves downstream, now that it exists:**

- Item 1's own volume-check sub-item (b) - "frame-mismatch withholding
  leaves zero DB trace, needs a live compute pass, not a query" is no
  longer true once this ships and a run has been through the code path
  at least once. Both count and dual-yield population become queries
  against `CardScanLog.objects.filter(skip_reason="frame-mismatch")`,
  not a recompute pass.
- Part 5's "evidence-gathered-and-negative guard" (residual
  classification's hard guard against absence-of-evidence, distinct from
  a genuine negative result) becomes a query against this table too -
  "did an engine actually look at this card and reach a real conclusion"
  is now answerable directly, not inferred from the absence of a vote
  (which was always ambiguous between "looked and found nothing" and
  "never looked").

Migration deploy sequencing (per the entrypoint-composition lesson,
`docs/troubleshooting.md`): `0063_cardscanlog.py` is a pure
`CreateModel` - additive-only, no existing table touched, so the running
pilot is safe regardless of when this lands. Applied the same way as
`0061`/`0062`: `docker compose run --rm django python manage.py migrate`
(a one-off container), never `docker compose up -d django worker`
(persistent-container recreation) while the pilot's own container is
still running - the additive-only property makes this specific migration
individually safe either way, but the sequencing discipline is kept
uniform rather than case-by-case judgment calls about which migrations
are "safe enough" to bend the rule for.

### Abstention-aware ordering (built 2026-07-17, during the backfill's grind)

Task #109's finding ("coverage-gap ordering front-loads unmatchable
names") upgraded from a static heuristic to an evidence-based one, now
that the scan-log above gives it something durable to query. A name
qualifies as **proven hard** for a given engine when it has `>= 5`
distinct cards with a non-rescannable scan-log row (`HARD_NAME_MIN_ATTEMPTS`
in `local_identify_printing_tags.py`) and zero distinct cards with a vote,
both all-time across every `run_id`. `_coverage_priority_key` gets one new
leading tuple dimension ahead of item 1's existing ordering: proven-hard
names sort last. This is a **demotion, not an exclusion** — a hard name's
candidates stay reachable if the rest of the queue is exhausted, they just
sort after everything else. A single real vote disqualifies the name
immediately and re-qualifies it for full-priority ordering on the very
next queue build, no restart needed. Per-engine demotion counts are
logged at queue build (`select_candidates`) and as one aggregate line in
`run_pilot`'s own startup block.

Interim — Part 4 (LANDS, artist-decomposed identification) supersedes
this for genuinely over-cap names with a real fix rather than a demotion,
once it ships. Takes effect at the next natural restart; the running
pilot wasn't stopped for this.

---

## Part 4 — LANDS (artist-decomposed identification) (module built 2026-07-18, HOLD #B cleared 2026-07-18; first full write attempt owner-stopped 2026-07-19 — see status below)

Target pool: unresolved basic lands (Plains/Island/Swamp/Mountain/Forest/
Wastes + Snow-Covered) OR any name whose candidate count exceeded the
phash cap (`PHASH_MAX_CANDIDATES`).

1. Collector-line OCR as normal — **confirmed**: `run_ocr_for_card`
   iterates `local_ocr.validate_against_candidates` unconditionally, no
   `len(candidates)` check anywhere. A card still unresolved and in this
   pool has already had a real, uncapped OCR attempt fail.
2. Where OCR fails: artist OCR, reusing `local_fallback.py`'s
   `detect_illus_anchor`/`extract_artist_name`/`match_artist` verbatim
   (already existed, already used to _narrow_ candidates during pass-2 —
   confirmed never previously used to cast a vote; this module is the
   first caller that votes on their output directly) → `difflib` ratio
   ≥0.8 (`ARTIST_FUZZY_MATCH_THRESHOLD`, unchanged) against the NAME'S
   OWN candidates' artists only.
3. Artist match → filter candidates to that artist's printings → phash
   within the filtered set (`local_phash.get_or_compute_canonical_hash` +
   `find_best_match`, same mechanism Part 3's frame-mismatch recovery
   already uses). Unique winner with the standard margin → printing
   vote. **Confidence split, owner-clarified 2026-07-18** (the spec
   text's "artist+art agree" vs "art-within-artist" phrasing was
   genuinely ambiguous on its own): 0.85 when the artist match ALONE
   already narrows to exactly one candidate and phash on that singleton
   clears the standard acceptance distance (two independent channels
   agreeing); 0.8 when the artist match narrows to multiple candidates
   and phash breaks the tie among them (one deciding channel, scoped by
   the artist filter). Any phash failure/ambiguity in either case →
   skip, counted — never trusted as a coin-flip. Full reasoning lives in
   `local_lands_identify.py`'s module docstring, next to the code it
   governs.

**Built**: `cardpicker/local_lands_identify.py` (the module — target-pool
query, the 3-step pipeline, `dry_run`/`run_id`/ledger rails matching
Part 3's exact shape, plus the `=s800` OCR-tier addendum —
`OCR_FETCH_DPI=220`, task #130's tier-routing idea applied here first;
phash needs no fetch tier, it matches against already-ingested hashes)

- `management/commands/local_lands_identify.py`
  (`--write`/`--run-id`/`--sample-size` [default 300, per HOLD #B]/
  `--fetch-budget` [default 0], staleness guard, `PilotRunLedger` lifecycle,
  `verify_zero_resolutions` gate after any real write) +
  `tests/test_local_lands_identify.py` (17 tests, synthetic fixtures, no
  network — passing). Verified end-to-end against the real pytest suite
  (862 passed, 130/130 snapshots, only the pre-existing known-bucket
  failures — moxfield ×2, `test_sources.py` fixture-path ×2, unrelated to
  this module) and the real `pre-commit` hook set (ruff/isort/black/
  mypy/prettier all clean).

**HOLD #B — cleared, real numbers in** (2026-07-18,
`run_id=20260718T215057-8af41b53`): land pool **39,707 cards**
(materially larger than assumed — basic lands plus every other
over-cap name; e.g. every "Forest" variant alone runs ~944 candidates).
Real 300-card sample: 103 (34.3%) resolve via plain OCR alone (step 1,
no artist-decomposition needed — these were simply never reached by the
main pilot's own OCR pass, not genuinely OCR-illegible); of the
remaining 197, 54 (18.0% of the full sample) got a real artist
extraction, of which only 5 (3 singleton + 2 tiebreak) reached a
confident printing match — 48 came up phash-ambiguous even after a
successful artist match, because artist-filtering doesn't always bring
a name under the phash cap (some filtered sets still run 13-20
candidates). Extrapolated to the full pool (linear, not a guarantee):
~13,633 cards resolvable via free OCR, ~662 additional via artist-
decomposition specifically. Full data, per-outcome breakdown, and the
open design question (is ~1.7% artist-decomposition yield an acceptable
ceiling, or does the phash-ambiguous rate need a narrower margin/
secondary signal) in
[`docs/reports/2026-07-18-part4-hold-b.md`](../reports/2026-07-18-part4-hold-b.md).
Nothing written — ran with no `--write` flag, `total_votes=would_cast=0`
confirmed. Whether to authorize a real `--write` run (full pool or
batched) is an open decision, not made here.

**First write attempt — owner-stopped, 2026-07-19** (`run_id= 20260719T004057-e531b323`): authorized full-pool `--write` run launched
2026-07-19T00:41Z, stopped intentionally by the owner ~3.5h in
(2026-07-19T04:08Z), superseded by the harvest-calculate pipeline
(which re-runs the lands pool as its own first workload, using the same
fetch/hash pre-warm this run left behind). Not a crash. Cost, verified
post-stop: zero `CardPrintingTag`/`LandsAmbiguousResidue` rows for this
`run_id` (expected — the module's `bulk_create()` calls fire once,
after the full card loop, not per-batch; see
[[../lessons.md]]'s batch-flush entry, written from this same run).
`PilotRunLedger` row closed as `FAILED` (the model's closest available
status - no dedicated "owner-stopped" state exists) with `votes_written = 0`. The run's ~3.5h of `CanonicalCard.image_hash` computation
persists regardless (73,223/113,224 canonical printings now hashed,
confirmed post-stop) - that cache is permanent and independent of this
run's own vote/residue loss, and is exactly the pre-warm the
harvest-calculate pipeline's lands chunk inherits.

---

## Harvest-calculate pipeline (Stages A–F, supersedes Part 4's remaining write run)

Fetch-fetch-fetch/extract-once/calculate-once replacement for Part 4's
ad-hoc fetch/OCR/phash logic, commissioned after the owner's 2026-07-19
stop of Part 4's first full-pool write run (see above): fetch each
image once, extract everything, compute every conclusion, streaming
(per-batch flush, never end-of-run dump — the exact gap that write
attempt exposed). Standing rules across every stage: branch/PR per
repo convention, per-batch flush MANDATORY (Stage E), `run_id`
stamping (Part 1's mechanism, unchanged), zero-resolution assertion at
every write pass, the human-backed gate untouched, no new tags
(altered-frame/custom-art only, matching every other part in this
doc). HOLD for owner GO before any full-catalog fire, gated on
real numbers, not projections — see each stage below and the
pipeline-fidelity gate (task #151, blocks Stage D's HOLD) for what
"real" means here. **Deploy-freeze protocol** (task #156): while any
run in this pipeline is active (its soak test or a full-catalog fire),
the deploy/CI/push surface is frozen — see
[[../infrastructure.md]]'s "Deploy-freeze protocol" section for what's
frozen, when, and how the freeze is signaled; not restated here.

### Stage A — instrumented wall-clock probe (merged, PR #128)

`cardpicker/harvest_probe.py` + `manage.py probe_harvest_pipeline [--sample-size N]`: fetches real images for a random sample (default
30), runs the real OCR/bleed/phash/canonical-hash engines against
them, times a real `bulk_create()` that's always rolled back inside a
savepoint (no persistence). Reports the wall-clock split
(fetch/OCR/phash/DB) as totals, percentages, and per-card means.
Baseline (pre-Stage-B, unpaced fetch): see the Stage B measurement
below for the actual numbers — Stage A produced the harness, Stage B
is the first real before/after comparison run through it.

### Stage B — fetch economics (measured, then implemented)

**Item 1 finding — R2 hit-rate is structurally moot, not a
measurement problem**: the harvest's only fetch path
(`image_cdn_fetch.fetch_card_image`/`get_worker_image_url`, the
Worker's "full" tier) never touches R2. Confirmed three independent
ways: `image-cdn/src/handler/image.ts`'s switch statement routes only
`small`/`large` through `R2Service.getThumbnail` — the `full` case
calls `fetchWithRateLimit` directly, and the code's own comment states
it plainly ("full-tier bypasses R2 entirely... EVERY request here hits
lh4.googleusercontent.com directly"); `R2Service.ts`'s
`getThumbnail`/`putImage` are called from nowhere else;
`frontend/src/common/image.ts`'s own `getBucketImageURL()` explicitly
`throw`s for `size === "full"` ("Cannot get full-res image through
bucket, fetch through worker instead") — the frontend's own
acknowledgment that "full" was never designed to have a bucket-domain
path. **This also answers the kill-order's open "did R2 population
survive" check: it's moot.** The stopped Part 4 write run used this
same full-tier-only path, so it never populated R2 in the first
place — there was nothing to survive or not survive. That run's ~4h of
real work is entirely in the `CanonicalCard.image_hash` cache
(73,223/113,224, reported at the time of the stop), not in any R2
cache state. Connects to a pre-existing, already-flagged gap: task
#130 ("tier-route image-cdn fetches by requested size, not hardcoded
full") is the same issue, independently rediscovered here.

**Owner decision, 2026-07-19 (Stage B reframe)**: Google-direct
economics as the real, current picture — no R2 tier in the split
limiter (nothing would ever hit it), keep the config structure
multi-destination so an R2 tier is a later addition, not a rewrite.

**Item 2 — split limiter, implemented, corrected 2026-07-19 by an
owner-commissioned red-team review**: `cardpicker/harvest_fetch_limiter.py`,
a per-destination registry (`DestinationLimiterConfig` + a
`_DestinationLimiter` pacer: strict minimum-interval, a concurrency
semaphore, and two distinct reactive severities — a lockout status
raises `GoogleFetchLockoutError` immediately, a hard stop; a backoff
status doubles the pacing interval, sticky for the process). Both are
one-way for the life of the process deliberately: a reactive signal at
harvest scale means "stay cautious for the rest of this one-shot run,"
not a blip to retry past. Three destinations configured today:

- `GOOGLE_IMAGE` — **3.0 req/s** (corrected from an initial 5.0 —
  the red-team review found this exceeded the only
  empirically-proven-safe sustained rate), concurrency 3, hard-stops
  on 403, exponential backoff on 429. The real, only-governed
  destination (see the R2 finding above) — and, per the review's own
  correction, reached via OUR OWN Worker, never "direct to Google":
  every fetch is one Worker invocation to its full tier, which then
  calls Google's lh4 endpoint server-side. The Worker's own
  `IMAGE_FULL_TIER_RATE_LIMITER` binding (3 req/s configured,
  `image-cdn/wrangler.toml`) is empirically confirmed leaky at
  smaller volume (`local_phash.py`'s 2026-07-17 addendum measured
  ~10.5/s sustained, zero 429s, during Part 2's backfill) — meaning
  THIS client-side limiter is the sole real enforcement, and 3.0/s is
  the one rate that's actually been proven safe at real volume, not a
  number derived from the Worker binding's leakiness. A 403 here is a
  hard stop, not a soft degrade: a lockout risks the live site's own
  image serving (PDF export/bulk download share this same Google
  endpoint), not just this pipeline's throughput.
- `SCRYFALL_CDN` — 10.0 req/s, concurrency 5, no reactive handling
  (no observed throttling history). "Local caching" (the owner's
  amendment) is now satisfied by a real fix, not just a structural
  claim: `CanonicalPrintingMetadata.art_crop_url`, parsed from the
  same weekly Scryfall bulk-data dump already used for printing
  metadata, serves the common case with zero network — see the
  dedicated fix below.
- `SCRYFALL_REST` — 2.0 req/s, concurrency 2, no reactive handling.
  Was the dominant real cost before the fix below (a live REST call
  per not-yet-hashed candidate); now a genuine-gap-only fallback.

No R2 entry exists in the registry (see the owner decision above) —
adding one is a config addition once #130 lands, not a rewrite.
Wired into all three of the codebase's real Google/Scryfall fetch call
sites (`image_cdn_fetch.fetch_card_image`,
`local_phash._fetch_scryfall_art_crop_url`,
`local_phash._fetch_and_hash`) — every existing caller (this pilot,
Part 2's backfill, the ingest hook, the harvest pipeline) shares the
same process-wide ceiling automatically; Part 2's own
`--rate-limit-per-sec` flag composes with `GOOGLE_IMAGE` rather than
conflicting with it (two gates in series, effective rate is whichever
is stricter — unchanged in practice at Part 2's 3.0/s default, now
identical to `GOOGLE_IMAGE`'s own corrected rate).

**Scryfall REST fix, 2026-07-19 (owner-flagged: "should not be a need
to query their REST")**: `get_or_compute_canonical_hash` previously
always hit Scryfall's live REST API per candidate for the art-crop
URL — confirmed as the real bottleneck by item 3's measurement below.
The same URL was already present, unused, in the weekly bulk-data
dump `import_scryfall_printing_metadata` reads (`image_uris.art_crop`,
or `card_faces[0].image_uris.art_crop` for double-faced cards) —
`PrintingMetadataRow` now parses it and
`CanonicalPrintingMetadata.art_crop_url` stores it, zero incremental
network cost (same file, same weekly import). `get_or_compute_canonical_hash`
now checks this local field first, falling back to the live REST call
only when the sidecar row is missing or the field is genuinely empty —
matching `SCRYFALL_REST`'s own "guard for true gaps only" design
intent for the first time.

**Item 3 — measured, real numbers, both before and after the fix
(2026-07-19)**: `probe_harvest_pipeline --sample-size=30`, real network
cost against production, no votes written, run twice on the same
methodology.

- **Before** the Scryfall REST fix (and before the red-team's Google
  rate correction, still at 5.0/s): total 521.76s across 30 fetched
  cards — fetch 25.10s (4.8%, mean 0.837s/card), OCR 8.35s (1.6%, mean
  0.278s/card), **phash 488.17s (93.6%, mean 16.272s/card)**, DB
  0.14s (~0%). Root cause: `SCRYFALL_REST` (2.0 req/s, deliberately
  low as "a guard against volume this call site shouldn't have") was
  absorbing a live REST call for every not-yet-hashed candidate, and
  **65.5% of `CanonicalCard` rows had a populated `image_hash` at
  measurement time (74,144/113,224)** — 34.5% of candidates hit
  anywhere in the catalog paid a real, first-time Scryfall REST+CDN
  round-trip, now correctly paced instead of running unthrottled as
  it did pre-Stage-B.
- **After** both fixes (local-first art-crop URL + corrected 3.0/s
  Google rate), immediately post-merge (PR #131, `65df7d8d`): total
  **85.79s** across the same 30-card methodology — fetch 22.05s
  (25.7%, mean 0.735s/card), OCR 8.59s (10.0%, mean 0.286s/card),
  phash **55.02s (64.1%, mean 1.834s/card)**, DB 0.13s (~0.1%). **A
  6.1x total speedup**; phash specifically dropped **8.9x** (16.272s
  → 1.834s mean/card), confirming the Scryfall fix eliminated the
  REST bottleneck as designed. Stage A's original pre-Stage-B baseline
  (before either fix) was never written to a durable location — a
  real process gap, not repeated here; both numbers above are now the
  permanent record.

**Item 4 — reprojected wall-clock, now grounded in the real post-fix
number**: phash at 1.834s/card mean (post-fix) is fast enough that the
per-card sequential probe no longer reflects the real governing
constraint — `GOOGLE_IMAGE`'s corrected 3.0/s rate ceiling is
unambiguously the dominant cost again, exactly as Stage A's original
projection assumed before the Scryfall finding complicated it. The
**~20.2h fetch-bound floor** (218,164 ÷ 3.0) for the full 218k-image
harvest stands as the real headline number, not the ~12h an
uncorrected 5.0/s would project — matching Part 2's own documented
backfill wall-clock at the same rate. Worker-topology consequence
holds cleanly now: fewer OCR workers likely suffice, since cores will
spend most of their time idle waiting on the Google rate ceiling
rather than CPU-bound on OCR/phash compute, which the post-fix numbers
confirm is now a minor fraction of per-card cost (10.0% + 64.1% of a
much smaller total, only ~2.1s/card combined — comfortably parallel
against a 3/s fetch ceiling with room to spare).

**Fetch Acceleration Study (owner directive, 2026-07-19, amends but
does not yet change the ≤3/s figure above — findings owed before the
full harvest, tracked as task #152)**: three investigations, run
before any full-catalog fire, that could legitimately raise the
Google ceiling above 3/s with real evidence rather than the informed
guess the number above still is: (1) a circuit-breakered ramp probe
through the Worker path (3→5→8→10 req/s steps, ~20-30min each,
logging req/s + status codes; first 429 → drop to 3/s and record that
as the ceiling; any 403 → stop everything, no further steps) — this
confirms rather than blindly explores, since Part 2's backfill already
observed 10.5/s sustained for 50+ minutes with zero 429s through this
exact path; (2) dedupe the fetch queue by unique content cluster (d=0)
rather than per-`Card`-row, reporting how much of 218k collapses away
for free; (3) a 1-2h feasibility spike (investigation only, no build)
on whether the Google Drive `files.get?alt=media` API, using
`update_database`'s existing credentials, could serve these same
images at a materially higher, Google-documented quota — potentially
beating every scraper-path number and removing the guesswork
entirely. Explicitly rejected: any "deliberate exceed-and-cool"
cycling pattern — the circuit breaker exists specifically so this
pipeline never has to learn a 403 lockout's real duration firsthand.
Re-projects wall-clock at HOLD under whichever lever(s) survive.

**Write-through hedge — CANCELLED (owner FINAL POSTURE directive,
2026-07-19; task #150 closed SUPERSEDED-BY-POSTURE)**: the R2
write-through/hopper idea sketched below is superseded in full by the
governing premise adopted the same day — see "Governing posture: we
index, we do not store images" after the Fetch Acceleration Study
below. No R2 write-through, no derivative storage, no retention tiers
of any kind; storage cost $0. Left here, struck through in spirit only
(not literally deleted) as a record of what was considered and why it
was rejected, so a future session doesn't re-derive and re-propose the
same idea: persist a copy of each fetched image to R2 (or make the
Worker's full tier genuinely write-through) so a future extractor
needing different pixels never re-triggers a ~20h Google pull.
Estimated ~218k × ~200KB ≈ 44GB ≈ $0.66/mo storage, Class A writes
inside Cloudflare's free tier — rejected on principle (legal/federation
posture), not cost.

**Resolution/tier investigation (owner directive, 2026-07-19, superseding
the initial "full-only, reject dual-tier" framing; scope narrowed again
by the same day's later FINAL POSTURE directive)**: two cheap
measurements (T1: OCR accuracy vs. fetch resolution; T2: phash Hamming-
distance stability vs. fetch resolution, since `docs/theory.md`'s d=0/
0<d≤2 thresholds were calibrated against full-resolution inputs) still
stand on their own merits — resolution choice affects extraction
_accuracy_ regardless of what happens to the pixels afterward. What
changed: the reason to run them is no longer "which resolution to
cache," since nothing is cached — it's now purely "which resolution to
_fetch at_ for the single in-memory extraction pass," a strictly
cheaper question. The R2-cached-harvest-tier design floated here is
CANCELLED along with task #150 (see "Governing posture" below) — not
a tier-storage decision, only a per-fetch dpi parameter.

**Baseline facts confirmed before any measurement** (both were open
questions, now resolved against primary sources, not assumed): "full
resolution" in every existing phash calibration doc in this project
(the n=2 test, the 300+300 harvested-pair validation underlying the
d=0/d≤2 thresholds) means **250dpi/~925px**
(`docs/features/printing-tags.md:1987`, "hashed at full res
(250dpi/~925px)"), NOT literal native — native is a distinct, higher
baseline (`dpi=None` sends no `h=` resize param to Google's lh4
endpoint at all, confirmed against `image-cdn/src/url.ts` +
`GoogleDriveService.ts`). T2 therefore needs to report distance
against BOTH baselines separately, not one number, since they answer
different questions (native = "how much does resolution matter at
all," 925px = "does the calibration transfer to a new tier").

**Harness built** (`cardpicker/resolution_tier_probe.py` +
`manage.py probe_resolution_tiers [--sample-size N]`, 13 tests,
pre-commit clean): fetches each sampled card at four tiers — `native`
(dpi=None), `1200px` (dpi=320 → 1184px), `925px` (dpi=250,
`DEFAULT_FETCH_DPI`), `800px` (dpi=220, `OCR_FETCH_DPI`, already
shipped in Part 4/LANDS) — and for each tier runs the real OCR
validation path (T1: match rate) and computes the real art-crop phash
(T2: reports Hamming distance vs. both `native` and `925px`
separately). Not yet run against real data — the live run is the next
step, real network cost, no votes ever persisted.

**Fetch Acceleration Study — items 2 and 3 results (measured
2026-07-19, item 1's ramp probe re-sequenced behind item 3, see
below)**:

- **Item 2, content-cluster dedupe**: `_compute_exact_match_clusters`
  run directly against production `Card.content_phash` — 36,709 of
  218,192 fetch targets (16.82%) collapse into an existing d=0 cluster,
  leaving 181,483 unique fetch targets. At the 3.0/s `GOOGLE_IMAGE`
  ceiling this removes ~3.4h from the ~20.2h floor if wired into the
  harvest queue (not yet wired — a queue-construction change, not a
  rate change, so it composes with whatever the fetch path ends up
  being).
- **Item 3, Drive API feasibility spike (1-2h investigation, no build,
  per directive)**: `find_or_create_google_drive_service()` +
  `service.files().get_media(fileId=...)` technically works — 6/6 real
  downloads succeeded, run through the production Docker container's
  own working credentials (the bare-metal pilot venv can't sign the
  service-account JWT — known pyOpenSSL version mismatch, same root
  cause as the pre-existing `test_sources.py` CI flaky bucket). Real
  trade-off found: raw Drive originals are ~5-30x larger than the
  lh4-resized Worker output the harvest pipeline actually needs,
  projecting to roughly 890GB-1TB+ total egress at full-catalog scale
  if adopted naively (vs. the Worker path's much smaller resized
  bytes) — and whether Google enforces a separate sustained-bulk-media-
  download quota beyond the general 200 QPS figure documented for
  metadata-scan concurrency was **unverified** at spike scale (6
  files). This is exactly what the larger verification test below
  answers.

**Drive API verification test (owner "FETCH PATH DECISION" directive,
2026-07-19 — proceeds to verification, not adoption yet)**: pacing
pinned via `AskUserQuestion` after the original "500-1000 files /
1-2h / 2-5 files/s" framing was flagged as internally inconsistent (the
owner's own arithmetic correction): **rate binds** at 2-5 files/s (the
real prospective harvest rate), **duration binds** at 30-45min sustained
(crosses Google's ~100s quota windows repeatedly — the actual thing
being tested), **file count falls out** (~4-10k, not a target). Sample
is a stratified round-robin across every `GOOGLE_DRIVE`-type `Source`
(capped 300/source) so mixed-drive coverage — explicitly including
community drives not owned by the project — is guaranteed by
construction, not luck of a random draw. Abort conditions: first 429 →
note the threshold + sticky exponential backoff (doubling, capped 16x,
mirrors `harvest_fetch_limiter.py`'s existing design); any 403 → full
stop. Bytes discarded per the no-image-storage posture below — sizes
and timings only.

**Results, single-stream (measured 2026-07-19)**: 2,347 files
attempted over 2400.3s (40min budget), 2,345 ok, 1 error (a single
network read-timeout at file 1087 — not a 429/403, no quota signal).
**Zero 429/403 across the entire run.** 16,418,161,171 bytes (~15.29
GiB) transferred, **6.523 MiB/s** sustained, **0.977 files/s**
effective rate. Sample spanned 247/248 available community sources
plus the project's own. Average file size **~6.68 MiB** — confirms
the feasibility spike's flagged trade-off with a much larger, more
reliable sample: Drive originals are far bigger than the lh4-resized
Worker output the existing scraper path fetches.

**Results, two-stream tail run (owner-authorized follow-up, same day,
conditional on the main run finishing with clean quota — it did)**:
10-minute, 2-concurrent-thread run, same per-stream pacing/
stratification/abort rules. 791/791 ok, **zero errors, zero
429/403**. 5,561,646,519 bytes (~5.18 GiB) in 602.2s, **8.808 MiB/s**,
**1.314 files/s** effective — average file size ~6.70 MiB, consistent
with the main run (cross-check that the stratified sample is
representative). **Combined: 3,136 successful real downloads across
~50 minutes of combined test time with zero quota events** — a far
more definitive quota-safety data point than the original 6-file
spike.

**Headline finding — throughput does NOT scale linearly with
concurrency**: 2 streams delivered only **1.35x** the single-stream
throughput (8.808 / 6.523), not 2x — roughly a third of the expected
gain from doubling parallelism was lost to some shared bottleneck.
Plausible cause (untested): the tail run used Python **threads**
within one process/container, which share the GIL — response
deserialization inside `googleapiclient` has real CPU cost that can
serialize across threads; separate OS processes would be the natural
next experiment if pushing this further is worthwhile, since GIL
contention wouldn't apply there.

**Full-harvest projection** (218,192 fetch targets, using the
main run's ~7.00 MB/file average): **~1.53 TB / ~1.42 TiB total raw
transfer** — well above the feasibility spike's rough "890GB-1TB+"
guess (that estimate was based on only 6 files; this is now measured
across 2,345+791). Wall-clock: **~62.0h at N=1**, **~45.9h at N=2**
(both measured, not extrapolated) — both **worse than the existing
scraper+dedupe path's ~16.8h floor** (181,483 unique targets ÷ 3.0/s).
Against the pre-set decision standard's ~2.5 files/s threshold: N=1
achieves 0.977/s (39%), N=2 achieves 1.314/s (53%) — **neither
measured concurrency level clears the bar**, and the sub-linear
scaling means extrapolating how many additional streams would close
the gap is unreliable: a naive-linear model says ~4 streams could
match the scraper's 16.8h, but continuing the observed (much weaker)
marginal per-stream gain instead says ~9 streams — a 2x spread on the
answer to "how many streams," which is itself the honest finding, not
a number to average away.

**FINAL VERDICT (owner decision, 2026-07-19) — option (b), dual
conclusion, task #152 closed**: scraper+dedupe stays the bulk fetch
path. Drive's ~30x bandwidth tax (raw originals, ~6.68 MiB/file
measured, vs. the scraper path's server-resized ~925px output) makes
it structurally wrong for bulk regardless of concurrency — no
process-based follow-up measurement is warranted, since no realistic
concurrency level closes a 30x-per-file gap. **Drive API's PROVEN
role going forward**: delta/gap-fill fetches, dead-link recovery, and
targeted re-extraction — plus lazy-mode one-offs (task #161) — where a
single accurate fetch matters more than bulk throughput. The clean
quota behavior measured across 3,136 downloads (zero 429/403,
spanning 247/248 available community sources) is the evidence backing
this role: Drive is safe and reliable for the low-volume, high-value
cases the bulk path doesn't need to reach for. The previously-
cancelled ramp probe (task #152's former item 1) was **REVIVED** as
task #163 and run 2026-07-19 (owner cleared it to fire without a
scheduled window — "the breaker is the safety mechanism, not a human
watching live" — since the design's own automated stop conditions
cover both real failure modes).

**Ramp probe results (task #163, completed 2026-07-19)**: full
circuit-breakered ramp through the real production path
(`image_cdn_fetch`'s Worker "full" tier, the exact `GOOGLE_IMAGE`
limiter singleton every real caller shares), steps 3→5→8→10 req/s
target, ~25min/step, 22,752 total requests. **Zero 429/403 across the
entire run** — the breaker never tripped, `last_confirmed_safe_rate`
reached the full 10.0/s target with no quota signal at any step.

**But the real per-step throughput plateaued well below the target
rates** — computed from each step's own (ok ÷ elapsed), not the
script's cumulative-average `current_rate()` reading (which dilutes
later steps with earlier, slower ones): 3.0/s target → 2.94/s
achieved; 5.0/s target → 3.83/s achieved; 8.0/s target → 4.16/s
achieved; 10.0/s target → **4.22/s achieved (the asymptote)**. Step 1
was still genuinely pacing-limited (target 3.0/s sits below the real
ceiling); steps 2-4 show throughput converging toward ~4.2/s
regardless of how much higher the pacing target goes — the signature
of a DIFFERENT bottleneck than pacing taking over.

**Little's Law identifies that bottleneck as `GOOGLE_IMAGE.max_concurrency=3`
interacting with real per-request latency, not Google's own rate
limit**: L = λW → with L (concurrency) = 3 and the step 4 asymptotic
λ (throughput) = 4.215/s, **W (mean round-trip latency) ≈ 0.712s** —
strikingly close to Stage B's own independently-measured fetch mean
(0.735s/card, item 3's post-fix measurement above), a real
convergent cross-check, not a coincidence. At `max_concurrency=3`,
no pacing target above ~4.2/s can ever be reached, because only 3
requests can be in flight at once and each one occupies its slot for
~0.71s regardless of how eagerly new requests are paced in.

**Two separate ceilings, only one of them Google's** (owner's own
framing, confirmed): the throughput ceiling measured here (~4.2/s) is
**our own client-side concurrency configuration**, not a Google/Worker
quota — Google's real ceiling remains genuinely unmeasured, since
concurrency=3 capped real throughput below whatever that number is at
every step. This is what task #165 (concurrency-raise probe,
owner-authorized, holds rate fixed at 10/s and steps
`max_concurrency` 3→6→10 instead) is designed to find.

**Immediate, already-measured, lower-risk finding**: independent of
task #165, this run is itself real evidence that `GOOGLE_IMAGE.rate_per_sec`
could safely move from 3.0 to ~4.0-4.2/s at the CURRENT `max_concurrency=3`
— a full 25-minute step targeted 10/s (far above this range) with zero
quota events. Not applied here (config values land only from a
deliberate follow-up per the standing "measure, don't assume" rule) —
flagged as a cheap, separate option the owner may want to take before
or independent of the larger concurrency-raise probe.

**Concurrency-raise probe results (task #165, completed 2026-07-19)**:
rate held fixed at 10.0/s (above the reachable concurrency=3 ceiling,
so concurrency - not pacing - was the dimension under test),
`max_concurrency` stepped 3→6→10, ~25min/step, same breaker as the
rate probe plus a live-site canary (a separate, unthrottled thread
sampling real Worker-path image latency every 15s throughout each
step, independent of the probe's own traffic).

**Zero 429/403 across all three steps and 32,889 total requests —
Google's own quota was never triggered, even at concurrency=10.** But
the canary caught something the quota signal alone would have missed
entirely:

| `max_concurrency`  | achieved rate | canary p95                   | error count | verdict                              |
| ------------------ | ------------- | ---------------------------- | ----------- | ------------------------------------ |
| 3 (today's config) | 4.32/s        | 0.81s (**baseline**)         | 2           | clean                                |
| 6                  | 8.12/s        | 0.39s (better than baseline) | 14          | **clean**                            |
| 10                 | 9.59/s        | 1.97s (**2.43x baseline**)   | 186         | **live-site regression — NOT clean** |

Concurrency=10 hit the fixed 10.0/s pacing target almost exactly
(9.59/s, matching the near-linear throughput-vs-concurrency curve
from 3→6 flattening out as it approaches the pacing ceiling) with
literally zero quota events — by the quota signal alone it would look
like a clean pass. The canary's own real-request latency sampling is
what actually caught the problem: **p95 image-serving latency through
the shared Worker path regressed 2.43x over the concurrency=3
baseline**, alongside a large jump in the probe's own error count (186
vs. 2-14 at lower concurrency) - both signs of real contention on
shared infrastructure that no 429/403 ever surfaced. This is exactly
why the canary was added rather than trusting the quota signal alone.

**Two ceilings, confirmed distinct, as the owner's framing
anticipated**: the throughput-vs-concurrency curve is near-linear from
3→6 (4.32/s → 8.12/s, ~1.88x for 2x concurrency) then flattens 6→10 as
it approaches the fixed pacing target - a pacing artifact, not a real
finding about concurrency=10 itself. The FIRST real degradation signal
of any kind (429/403 or otherwise) across both probes combined
(55,641 total requests) was the concurrency=10 canary regression -
Google's own rate ceiling remains entirely unmeasured; this was a
live-site-latency ceiling, found before ever reaching Google's.

**Deliverable — recommended config value: `max_concurrency=6`,
`rate_per_sec≈8.0`** (a touch under the measured 8.116/s ceiling for
margin), NOT concurrency=10 despite it numerically matching the
owner's own "~10/s achieved" framing - it does not "hold clean" per
the owner's own pre-set standard, since the live-site regression is
itself a stop condition. Final wall-clock table for the 181,483
deduped fetch targets:

| Config                                           | Achieved rate | Wall-clock |
| ------------------------------------------------ | ------------- | ---------- |
| Current (3.0/s, concurrency=3)                   | 2.94/s        | ~17.15h    |
| Rate-only bump (~4.2/s, concurrency=3)           | 4.2/s         | ~12.00h    |
| **Recommended (~8.0/s, concurrency=6)**          | **8.116/s**   | **~6.21h** |
| Concurrency=10 (rejected - live-site regression) | 9.586/s       | ~5.26h     |

The "single evening" framing doesn't quite land - concurrency=6 gets
the bulk harvest to ~6.2h (a 2.76x improvement over today, and the
largest concurrency step that stayed clean on every dimension
measured: quota, error rate, and live-site latency), not the ~5h a
clean concurrency=10 would have given. Owner decides whether to apply
`max_concurrency=6`/`rate_per_sec≈8.0` to `harvest_fetch_limiter.py`'s
`GOOGLE_IMAGE` config - not applied here, per the standing "config
values land only from measurement, not automatically" rule.

### Governing posture: we index, we do not store images (owner FINAL POSTURE + PRIORITIZATION directive, 2026-07-19)

**Constitutional premise**: the catalog persists knowledge about card
images, never the images themselves — the project's legal protection
and the federation pitch's core claim ("card artwork never crosses the
wire"), applied to our own disk as strictly as to the network. Codified
as a one-line standing test in the top-level `CLAUDE.md` so no future
session re-invents a storage tier.

1. **Hopper cancelled entirely** (task #150, and task #154's
   whole-image-persistence idea, both closed SUPERSEDED-BY-POSTURE): no
   R2 write-through, no derivative storage, no retention tiers, no
   EDHREC-gated keeps, no best-DPI exemplars, no dead-drive archives.
   Storage cost: $0.
2. **Evidence store = pure metadata (Stage C amendment)**:
   `ImageEvidence` persists ONLY derived facts — hashes (whole-card /
   art-region / symbol-region), full OCR text + TSV word boxes, parsed
   fields, geometry/layout/border/bleed classes, color statistics,
   quality/integrity signals, dims/DPI, fetch health, extractor-version
   map. No persisted image crops of any kind: crop COORDINATES persist
   (geometry + TSV terms), crop PIXELS exist only in memory during the
   pass and are discarded. The symbol-strip diagnosis re-plans as
   in-pass hash/feature-vector math (store the math, not the strip).
   Folded into task #145's own description as the binding spec for
   Stage C's build.
3. **Consequence accepted, documented**: any re-extraction = re-fetch
   (Drive API path, pending the verification test above) + re-derive in
   memory. Images live at their sources; the catalog retains only what
   it measured.
4. **EDHREC rank + source health survive as prioritization, not
   retention** (task #160): `edhrec_rank` added to
   `CanonicalPrintingMetadata` from the Scryfall bulk dump already
   parsed by `printing_metadata_import.py`; harvest order becomes lands
   chunk #1 → dying-source cards (drive-health rollup, measure before a
   community source vanishes) → queue-backing cards → descending
   `edhrec_rank` → cold tail; same ranking available to the
   confirmation queue's display order later.
5. **Lawyer-hour flag, list-don't-act** (task #162): the existing
   image-cdn R2 small/large thumbnail cache is transient display
   caching inherited from upstream's serving design — queued for
   counsel's read on where caching ends and hosting begins. Region
   hashes/statistics (Stage C's actual extractor outputs) are pure-math
   safe by contrast, not in scope for this flag.
6. **Standing test**: any future design that stores image pixels beyond
   transient display-serving cache fails regardless of other merits —
   see `CLAUDE.md`'s new "Governing premise" section.
7. **Queue-display cache warming** (optional, low priority, UX only —
   the posture-legitimate remainder of the hopper idea): when a card
   enters the human confirmation queue, the EXISTING small/large
   serving tiers MAY be warmed for it — same cache, same eviction,
   triggered by queue-entry instead of first viewer. Strictly bounded
   to queue-backing cards, never catalog-wide; no new tier, no
   resolution change, zero harvest-path involvement. Build only if
   nearly free; skip entirely otherwise. Not started, not tracked as a
   numbered task given its own "skip if not free" clause.
8. **Lazy identification mode** (task #161 for the design-note/docs
   half; the structural half is binding now, folded into task #145):
   (a) **binding on Stage C/E now** — the per-card work unit (fetch →
   extract → evidence → calculate → discard) must be a callable unit
   independent of the bulk runner; the bulk harvest is one driver of
   it, a future demand-driven async task is another; per-card logic
   must never fuse into batch orchestration. (b) **lazy mode**
   (documented now, built later): card viewed/requested + no evidence
   for its content hash → enqueue a single-flight async identification
   job (extraction is ~1-2s, too slow inline; single-flight lock
   prevents duplicate work on concurrent views) → evidence + machine
   suggestion appear seconds later. The evidence store IS the cache;
   computed-once-forever; traffic is the scheduler. (c) **federation
   payoff** (one paragraph for `docs/federation-v1.md` §8, task #161): a
   reference consumer on minimal hardware runs no bulk jobs — knowledge
   accretes with use, fetch load is traffic-paced, peer queries about
   never-seen hashes can trigger on-demand computation.
   "Identification capacity scales with usage, not hardware." (d)
   **equivalence**: bulk harvest = eager pre-computation of what lazy
   mode would eventually compute; same pipeline, two drive modes
   (push/pull) — our instance runs eager because we can, federation
   peers run pull because the design permits it.

### Stages C–F (extractors, calculators, streaming assembly, consumers)

**Stage C: GO NOW (owner directive, 2026-07-19)** — the measurement
hold is cleared (Fetch Acceleration Study closed, task #152). First
PR is the substrate, not an extractor (advisor-confirmed sequencing:
the "one PR per extractor, golden-set-tested before merge" gate isn't
executable until this exists):

- **`ImageEvidence` model** (`cardpicker/models.py`) — metadata-only
  per task #145's amended spec (hashes, geometry, quality signals;
  crop coordinates yes, crop pixels never), keyed `(card, content_hash)` with a `unique_together` constraint so a content
  change creates a new row rather than overwriting the old one.
  `extractor_versions` JSONField is the per-field completion map.
  **Reconciliation ledger fields folded in now** (owner directive,
  same day — task #155's fields, not retrofitted per-extractor):
  `run_id` (last-writer, for report scoping) plus reuse of the
  existing `CardScanLog` model for named skips (`anonymous_id` set to
  the extractor name) — no new ledger table. Migration `0068`.
- **`cardpicker/image_evidence.py`** — the per-card callable
  extraction unit (`extract_card_evidence`, pure, no DB writes) and
  its separate persistence step (`persist_evidence`), satisfying
  FINAL POSTURE item 8a's binding requirement that this be
  independent of the bulk runner. `build_reconciliation_report`
  computes attempted/voted/skipped-by-reason/dropped by querying
  `ImageEvidence` + `CardScanLog` directly (never a separately
  maintained counter, so it can't drift from what was actually
  persisted). Only extractor riding along: `fetch_health` (trivial,
  end-to-end proof only — not the manifest).
- **`cardpicker/golden_set.py`** (new infrastructure — no prior
  precedent existed in this codebase) — 30 real card ids, stratified
  by source (28 distinct sources, drawn 2026-07-19, seeded), pinned
  rather than re-randomized per test run. `GOLDEN_EXPECTATIONS` is
  populated incrementally, one extractor at a time, by whichever PR
  builds that extractor.
- 21 new tests (`test_image_evidence.py`, `test_golden_set.py`), all
  passing; full suite 979 passed / 4 failed (the known pre-existing
  baseline: moxfield x2, sources OpenSSL x2 — nothing new broke);
  `makemigrations --check` clean. Tests run from the host venv
  (`~/.venvs/mpcautofill-pilot`), not inside the django container —
  the container has no Docker socket access, and pytest-django's `db`
  fixture setup needs one; this was hit and diagnosed this session,
  not previously documented.

Every subsequent extractor (geometry/bleed, OCR/collector-line,
artist OCR, phash, border color, symbol-strip, legal-line, etc.)
lands as its own PR against this substrate, golden-set-tested before
merge, per task #145's manifest and its freeze rule.

**geometry/bleed — first manifest extractor, built** (public issue
#147, 2026-07-19): adds `width`/`height`/`aspect_ratio`/`bleed_class`
to `ImageEvidence` (migration `0069`, additive-only `AddField`s, no
freeze conflict — none of `docs/troubleshooting.md`/this doc's own
"Status" section records an active migration freeze). The extractor
itself calls `local_fallback.classify_bleed_edge` directly rather than
re-deriving the aspect-ratio math, so its stored `bleed_class` is
guaranteed to agree with the exact classifier the live pilot/harvest
vote path (`cast_bleed_edge_vote`) already uses — reused, not
duplicated, and no changes to `local_fallback.py` itself (PROTECTED
CORE; calling its existing exported function from new code is not
"changing" it, per `docs/upstreaming/license-provenance.md`).
Deliberately first per the manifest's own stated order: every later
crop-coordinate extractor (#148+) needs `width`/`height` (to turn a
fixed-fraction crop box into pixel coordinates) and `bleed_class` (to
remap that box via `normalize_crop_box` first) — this extractor is
what makes both available from stored evidence. Scope held strictly to
extraction: no vote is cast here (`cast_bleed_edge_vote` is not
called) — that's Stage D calculator territory per the pipeline-fidelity
gate (task #151) once it's built, not folded into this PR.
`GOLDEN_EXPECTATIONS["geometry_bleed"]` populated against a real,
no-persistence `extract_card_evidence()` run over all 30 golden cards
(host venv, real network fetch through the shared `GOOGLE_IMAGE`-paced
Worker path, zero DB writes): 27/30 bleed, 3/30 trimmed. 8 new tests
(6 in `test_image_evidence.py`'s new `TestExtractCardEvidenceGeometryBleed`
class plus 5 pre-existing `TestExtractCardEvidence` tests updated for
the new extractor's presence, 2 in `test_golden_set.py`); full suite
987 passed / 4 skipped (the CI-documented named skips — Moxfield +
Google-Drive-credential — nothing newly broken); `makemigrations --check` clean.

**geometry-group — second manifest extractor PR, built** (public issue
#148, 2026-07-19): adds `layout_class`, `collector_line_crop_px`,
`artist_crop_px`, `art_crop_px` to `ImageEvidence` (migration `0070`,
additive-only `AddField`s, no freeze conflict — checked
`gh issue list --label deploy-freeze-active` fresh immediately before
both the migration and the golden-set gathering run, empty both times).
`layout_class` calls `local_fallback.classify_border_color` — the ONLY
remaining `classify_*` helper in that file that doesn't require an OCR
pass as an input (`classify_frame_style` needs
`parsed_a_collector_number`/`illus_anchor_fired`, both OCR outputs —
issue #149's PR, not this one). Stored under the `layout_class` field
name to match issue #148's own title wording even though the
underlying classifier is named for border color — documented in
`image_evidence.py`'s module docstring so a future reader isn't
confused by the name/semantics gap. The three `*_crop_px` fields turn
the existing fixed-fraction crop-box constants
(`local_ocr.DEFAULT_CROP_BOX`/`local_fallback.ARTIST_CROP_BOX`/
`local_phash.ART_CROP_BOX`) into pixel coordinates for this specific
fetched image, remapped via `normalize_crop_box(box, bleed_class)`
first — crop COORDINATES only, never crop pixels, matching the FINAL
POSTURE directive. No changes to `local_fallback.py`/`local_phash.py`
themselves (both PROTECTED CORE; calling their existing exported
functions/constants from new code is not "changing" them, per
`docs/upstreaming/license-provenance.md`).

**`back_face_flag` (also named in issue #148's title) was NOT built in
this PR** — no signal for it was found anywhere in this repo: `Card`/
`CanonicalCard` carry no DFC-face field (the only `face` field in the
whole schema is `ProjectMember.face`, an unrelated per-slot
print-request concept, not a property of the uploaded image itself),
and no `local_fallback.py` exported helper addresses it either. Four
candidate heuristics were considered and rejected as ungrounded
guesses rather than shipped as an invented definition with fabricated
golden-set expectations (flagging `CardTypes.CARDBACK` rows — already
excluded from the identification pipeline pool at three call sites, so
moot; reusing `ProjectMember.face` — wrong model entirely;
`classify_frame_style`/border-color based guesses — neither actually
addresses "back face"; an aspect-ratio "composite scan" heuristic
built from a prose aside in `local_fallback.py`'s bleed-classification
comment — the comment names it as one of three peer examples of an
ambiguous read, not a discriminating signal). Open question for the
owner, not decided here.

`GOLDEN_EXPECTATIONS["layout_class"]`/`["crop_coordinates"]` populated
against a real, no-persistence `extract_card_evidence()` run over all
30 golden cards (host venv, real network fetch through the shared
`GOOGLE_IMAGE`-paced Worker path, zero DB writes): 14 `black`, 13
`borderless`, 1 `white`, 1 `silver`/gold-taxonomy-miss card (207913)
recorded as `""` with a genuine `ambiguous` skip_reason — kept as-is
rather than discarded, since a golden set that only ever pins
clean-positive outcomes would never catch a regression in the
ambiguous path. The three `trimmed`-classified cards
(145532/150472/189166) show visibly different crop-coordinate numbers
than the `bleed` majority, real evidence `normalize_crop_box`'s remap
is actually engaged for those rows. 21 new tests (11 in
`test_image_evidence.py`'s new `TestExtractCardEvidenceLayoutClass`/
`TestExtractCardEvidenceCropCoordinates` classes, 6 pre-existing
`TestExtractCardEvidence*` tests updated for the two new extractors'
presence, 4 in `test_golden_set.py`); full suite 1024 passed / 4
skipped (the same CI-documented named skips — nothing newly broken);
`makemigrations --check` clean.

**OCR-group — third manifest extractor group, built** (public issue
#149, 2026-07-20): adds `collector_line_raw_text`,
`collector_line_set_code`, `collector_line_collector_number`,
`artist_ocr_raw_text`, `artist_ocr_name`, `illus_anchor_fired`, and
`collector_line_word_boxes`
to `ImageEvidence` (migration `0071`, additive-only `AddField`s, no
freeze conflict — checked `gh issue list --label deploy-freeze-active`
fresh immediately before both the migration and the golden-set
gathering run, empty both times). All three extractors consume
`collector_line_crop_px`/`artist_crop_px` — the pixel boxes issue #148's
crop_coordinates already computed earlier in the same pass — directly
(`image.crop(...)`), rather than recomputing them from the fixed-fraction
constants a second time. None of the three perform candidate matching:
`local_ocr.validate_against_candidates`/`local_fallback.match_artist`
both require a card's real `CandidatePrinting` list, which the per-card
`extract_card_evidence(card)` function never receives — that comparison
is Stage D calculator territory (task #151's pipeline-fidelity gate),
not Stage C extraction. What's stored is raw OCR text plus
`local_ocr.parse_collector_line`/`local_fallback.extract_artist_name`'s
existing tolerant parses (both called, not reimplemented) plus word-level
bounding boxes from a new `local_ocr.run_tesseract_tsv` wrapper around
`pytesseract.image_to_data` — metadata per FINAL POSTURE item 2 ("full
OCR text + TSV word boxes, parsed fields"), never a verdict about which
printing this is. `artist_ocr` reuses `collector_line_ocr`'s own raw
texts first (an old-border card's "Illus. <artist>" credit frequently
lands inside the same crop region a modern card's collector line
occupies), the same reuse-before-recompute convention
`local_fallback.detect_illus_anchor` already uses — only cropping+OCR-
ing `artist_crop_px` if that reuse finds nothing. No changes to
`local_fallback.py` itself (PROTECTED CORE; calling its existing
exported `extract_artist_name` from new code is not "changing" it, per
`docs/upstreaming/license-provenance.md`); `local_ocr.py` is not
PROTECTED CORE, so `run_tesseract_tsv` was added there directly.

`GOLDEN_EXPECTATIONS["collector_line_ocr"]`/`["artist_ocr"]`/
`["collector_line_tsv"]` populated against a real, no-persistence
`extract_card_evidence()` run over all 30 golden cards (host venv, real
network fetch through the shared `GOOGLE_IMAGE`-paced Worker path, zero
DB writes): only 10/30 produced a parseable collector number (several a
4-digit "year" number on `mtg`/`proxy`-coded promos rather than a
classic 3-digit one); `illus_anchor_fired` came back `False` for all 30
— genuine, not a placeholder, since "Illus. <artist>" is an
old-border-only convention (pre-2003) and this source-stratified sample
happened to draw zero old-border cards, consistent with issue #148's
own layout_class results (14 black/13 borderless/1 white/1 ambiguous,
no old-border signal either); 25/30 found at least one non-blank
tesseract word in the collector-line crop, including several cards
where the word(s) found didn't fit the collector-number regex — a
genuinely different (weaker) outcome than a fully blank crop, and worth
keeping distinct in the golden set for exactly that reason. Raw OCR
text itself is NOT pinned (too verbose/brittle across a tesseract
version bump), nor is the exact word-box list (same reasoning) — only
the discrete parsed fields and a `word_boxes_present` bool are, matching
`geometry_bleed`'s own precedent of excluding continuous/brittle values
from the hard gate. 19 new tests (13 in `test_image_evidence.py`'s new
`TestExtractCardEvidenceCollectorLineOcr`/`ArtistOcr`/`CollectorLineTsv`
classes — all three run against real PIL images + the real tesseract
binary, no monkeypatching of tesseract itself, per CLAUDE.md's "no new
skips" rule — plus 6 in `test_golden_set.py`), and 13 pre-existing
`TestExtractCardEvidence*` tests updated for the three new extractors'
presence; full suite 1037 passed / 4 skipped (the same CI-documented
named skips —
nothing newly broken); `makemigrations --check` clean.

`back_face_flag` remained an open question for the owner as of this PR
(see the geometry-group paragraph above) — settled afterward, see the
"back-face flag" paragraph following the legal-line extractor below.

**symbol_region — fourth manifest extractor, built** (public issue #160,
"Part 4b: symbol harness", 2026-07-20): adds `symbol_crop_px` and
`symbol_phash` to `ImageEvidence` (migration `0073`, additive-only
`AddField`s, no freeze conflict — checked
`gh issue list --label deploy-freeze-active --state all` fresh
immediately before both the migration and the golden-set gathering run,
empty both times, despite a concurrent live dataset-population run
writing `ImageEvidence` rows in the background — this PR's own
migration/tests/golden-set run all targeted the throwaway pytest
testcontainers DB or read-only production `Card` reads, never a write to
that live data). `symbol_crop_px` turns `local_fallback.SYMBOL_STRIP_BOX`
— the same right-side vertical strip that module's own
`find_symbol_matches` sub-check scans — into pixel coordinates exactly
the way issue #148's `crop_coordinates` derives its own three boxes
(`normalize_crop_box` remap, then scaled by width/height); `symbol_phash`
is a perceptual hash (`imagehash.phash`) of that region ONLY — the
cropped pixels are hashed in memory and discarded, never persisted (the
Governing posture section's own "the symbol-strip diagnosis re-plans as
in-pass hash/feature-vector math — store the math, not the strip"
directive this task closes out). Deliberately NOT
`find_symbol_matches` itself: that sub-check compares the strip against
a rendered keyrune glyph for each of a card's real `CandidatePrinting`s,
which this per-card function never receives — candidate matching (and
the actual set identification/lookup) is Stage D calculator territory,
same reasoning issue #149's own OCR-group paragraph gives for why no
candidate matching happens in Stage C. `symbol_phash` is stored as a
signed 64-bit int via `twos_complement` (`cardpicker.utils`, not
protected core) — the same representation `local_phash.py`'s own private
`_hash_to_int` uses for `Card.content_phash`/`CanonicalCard.image_hash`,
reproduced rather than imported since that helper isn't exported from
that PROTECTED CORE module. No changes to `local_fallback.py` itself
(PROTECTED CORE; importing its existing `SYMBOL_STRIP_BOX` constant from
new code is not "changing" it, per
`docs/upstreaming/license-provenance.md` — note `SYMBOL_STRIP_BOX` isn't
in that module's own `__all__`, which restricts `from ... import *` only,
not a direct named import).

The only named skip is a degenerate crop box (zero/negative width or
height) — the same "sub-floor" input category `geometry_bleed`'s own
`test_zero_height_image_guards_aspect_ratio_division` guards against for
its aspect-ratio division, applied here before `PIL.Image.crop`/
`imagehash.phash` would raise on an empty region. An earlier design
considered gating on `imagehash.phash` returning the literal all-zero
sentinel `local_phash.py`'s own docstring names for
`CanonicalCard.image_hash` ("vanishingly unlikely for real card art") —
rejected on advisor review as an ungrounded heuristic near-guaranteed
never to fire (the same failure mode issue #148's own `back_face_flag`
rejection names), in favor of the degenerate-box guard actually built:
mechanically necessary regardless (a real crash risk on a sub-floor-
resolution fetch), constructible in a real test (fed a zero-height stub
image), and not a tuned classification threshold.
`GOLDEN_EXPECTATIONS["symbol_region"]` populated against a real,
no-persistence `extract_card_evidence()` run over all 30 golden cards
(host venv, real network fetch through the shared `GOOGLE_IMAGE`-paced
Worker path, zero DB writes): 30/30 produced a real (non-degenerate)
hash, zero "ambiguous" skips — a genuine outcome for this
source-stratified real-image sample, not a placeholder; the degenerate-
box guard is not expected to fire against the golden set, stated plainly
in both the golden-set comment and this extractor's own module docstring
rather than left implicit. 8 new tests (`TestExtractCardEvidenceSymbolRegion`
in `test_image_evidence.py`, plus 2 in `test_golden_set.py`), and existing
`_StubImage`-based `TestExtractCardEvidence*` tests updated (a new
`_stub_symbol_region` helper, mirroring `_stub_border_color`/`_stub_ocr`'s
identical rationale) for the new extractor's presence; full suite 1069
passed / 4 skipped (the same CI-documented named skips — nothing newly
broken); `makemigrations --check` clean.

**Migration 0068 (only) live on production at this point; first real
dataset population launched (2026-07-20)** — **corrected 2026-07-20**:
this paragraph originally claimed migrations `0068`–`0072` were live,
taking production from `0067` to `0072`. That was wrong; see
`docs/infrastructure.md`'s "Stage C migration state" note (also
corrected) for the verified history. Only `0068` — the `ImageEvidence`
substrate itself — was actually applied to the persistent production
Postgres at this point, ad hoc during this run rather than through the
documented deploy sequencing. `0069`–`0072` (the geometry/bleed (#147),
geometry-group (#148), and OCR-group (#149) extractor fields documented
above, plus the `CardScanLog` instrumentation fields
(`evidence_types_used`/`survivor_pks`, `0072`) from issue #209's
negative-vote work) were merged to the codebase but did not stick to
the persistent DB despite the original claim. Every golden-set run
described in this section (the 27/30, 30/30, 10/30, and this extractor's
own 30/30 samples) was, as originally stated, explicitly "zero DB
writes" validation against the pinned 30-card golden set, not
population — the evidence store itself held 0 rows in production until
this run. It wrote its full cohort against a DB with only `0068`
applied: `run_id=stagec-cohort-20260720-full`, 18,072 rows total — all
predating the `0069`–`0075` columns, which are NULL on these rows until
re-extracted.

Migration `0073` (this section's own symbol_region extractor, #160) was
also merged to the codebase as of this writing; its production-deploy
status was flagged here as a separate, unconfirmed open item — **now
resolved**: `0073`, along with `0074`/`0075` (built in later sections
below), was applied only by the 2026-07-20 rebuild-from-master, not
before it. See `docs/infrastructure.md` for the full corrected
timeline.

**legal-line extractor + moderator flag — next manifest extractor, built**
(public issue #151, "Legal-line extractor + moderator flag + volume report
(task #159)", 2026-07-20 — this PR builds the extractor + moderator-flag
signal only; task #159's volume-report half is out of scope, tracked
separately, not folded into this PR): adds `legal_line_crop_px`,
`legal_line_raw_text`, `legal_line_copyright_year`,
`legal_line_proxy_marker_detected` to `ImageEvidence` (migration `0074`,
additive-only `AddField`s, no freeze conflict — checked
`gh issue list --label deploy-freeze-active` fresh immediately before both
the migration and the golden-set gathering run, empty both times; depends
on `0073`, per the note above also not yet confirmed live on
production — this PR's own dev/test work targeted the throwaway pytest
testcontainers DB or read-only production `Card` reads only, never a
write, so this dependency doesn't block merging ahead of that deploy).
A NEW,
dedicated crop region (`local_ocr.LEGAL_LINE_CROP_BOX` — same y-band
`DEFAULT_CROP_BOX` was tuned against, widened to the full card width since
a real copyright legend commonly runs further right than the collector
line's own narrow window), verified against real fetched production images
before being locked in — a quick probe against 18 real golden cards
confirmed the box genuinely captures legal/proxy-marker text (including
several real "NOT FOR SALE"/"PROXY" hits) rather than being invented from
memory, per the same discipline every other `*_crop_px` field followed.
`local_ocr.parse_legal_line` (new, `local_ocr.py` is not PROTECTED CORE)
extracts a copyright year (anchored to a `©`/`(c)`/"copyright" glyph in
preference to a bare 4-digit run elsewhere in the line, avoiding a
collector-number-shaped false read) and detects a proxy/not-for-sale
marker via a deliberately plain, literal (not fuzzy) regex — no candidate
matching happens here (Stage D's job, same as every other OCR-adjacent
extractor). `legal_line_proxy_marker_detected` is the moderator-flag
signal (task #151's real motivating case: a "MTG★EN … NOT FOR SALE
©2022" watermark reads as plausible collector-line-shaped text to a
tolerant parser — this signal is what lets Stage D's calculator reject
that false-accept instead of trusting it); this extractor only emits the
raw True/False fact, it never acts on it directly, matching every other
extractor's "emit signals, don't act on them" discipline. No changes to
`local_fallback.py`/`local_phash.py` (both PROTECTED CORE; not touched by
this extractor at all).
`GOLDEN_EXPECTATIONS["legal_line"]` populated against a real,
no-persistence `extract_card_evidence()` run over all 30 golden cards
(host venv, real network fetch through the shared `GOOGLE_IMAGE`-paced
Worker path, zero DB writes): 10/30 produced a plausible copyright year,
10/30 detected a proxy/not-for-sale marker — genuinely common on this
real sample, not a rare edge case, since this catalog is specifically an
MTG-proxy print catalog rather than a scan archive (real hits include
"NOT FOR SALE", `Custom Proxy *NOTFORSALE*`, "MTG PROXY", and a
community-credit "Proxy - `<username>`" watermark baked into the source
image) — kept as-is per the same "don't discard a real outcome" rationale
every prior extractor's own golden-set comment gives. 21 new tests (7 in
`test_image_evidence.py`'s new `TestExtractCardEvidenceLegalLine` class —
real PIL images + the real tesseract binary, no monkeypatching of
tesseract itself; 12 in `test_local_identify_printing_tags.py`'s new
`TestLegalLineParsing` class — pure string-parsing unit tests of the
marker-detection regex against synthetic strings, including the exact
motivating watermark text, separate from the golden set which only
reflects whatever real production images happen to contain; 2 in
`test_golden_set.py`), plus 4 pre-existing `TestExtractCardEvidence*`
tests updated for the new extractor's presence (including one call-count
assertion in `TestExtractCardEvidenceArtistOcr` that legitimately changes
from 1 to 2, since legal_line — unlike `artist_ocr` — always crops+OCRs
its own dedicated region rather than reusing another extractor's already-
computed raw text); full suite 1088 passed / 4 skipped (the same
CI-documented named skips — nothing newly broken); `makemigrations --check` clean.

**back-face flag — settled by owner decision, built as a name lookup, NOT an
`ImageEvidence` extractor** (public issue #199, 2026-07-20): the owner settled
the open question the geometry-group PR left hanging — back-face is
determined from a card's NAME via Scryfall, not from image analysis, which
makes it name/identity metadata rather than a Stage C image extractor.
`printing_metadata_import.py` gains `get_back_face_names()`/`is_back_face()`:
a deterministic name → back-face lookup built entirely from the Scryfall
bulk data already on disk (`scryfall_cache/default_cards.json`, the same
file that function's own `import_scryfall_printing_metadata` already
parses) — no network fetch, no downloader, per the owner's own wording
("reads the EXISTING on-disk bulk data... a small addition to the existing
metadata-import path, not new plumbing"). For every row whose Scryfall
`layout` is a genuine double-faced layout (`DOUBLE_FACED_LAYOUTS`:
`transform`/`modal_dfc`/`double_faced_token`/`battle`/`reversible_card`),
the second face's name (`card_faces[1]["name"]`) is a back face.
Deliberately narrower than "any row with 2+ `card_faces`": split/flip/
adventure/aftermath/mutate/prototype layouts also nest multiple named
modes under `card_faces`, but those modes are printed on the SAME single
face of the card, not front/back — an unfiltered check would misflag e.g.
Adventure's spell side ("Stomp") as a back face of "Bonecrusher Giant".
`art_series` is excluded for the same reason `MTGIntegration. DFC_SCRYFALL_QUERY` already excludes it for its own (live-API-sourced)
`DFCPair` table. **Scope gap, by the owner's own card_faces-based
definition, not an oversight**: meld back faces are NOT covered — meld
pieces carry no `card_faces` on their own bulk-data row at all (Scryfall
represents the merged result via `all_parts` on the _meld_result_ card
instead, which is why `MTGIntegration.get_meld_pairs` reads a completely
different shape) — this on-disk, name/card_faces-based definition
structurally cannot see them. No `ImageEvidence`/`CanonicalCard`/
`CanonicalPrintingMetadata` field was added: `CanonicalCard.name` for a
double-faced print is Scryfall's own combined `"A // B"` name (one row per
print, both faces embedded), so a per-print boolean doesn't correspond to
"is this a back face" the way it does for a physical uploaded `Card.name`
(which is single-face, e.g. "Insectile Aberration") — no real caller needs
a persisted flag yet, so none was speculatively added; "additive migration
if a field is added" resolved to no migration this round. 11 new tests in
`test_printing_metadata_import.py`'s new `TestGetBackFaceNames` class
(known DFC back face → True, its own front face → False, a normal card →
False, an Adventure/split second mode → False, an art_series row → False,
a missing bulk file → empty set without raising, caching); no real
golden-set expectations gathered for this one — the real
`default_cards.json` isn't present on any dev machine this PR was built on
(no network fetch in scope to obtain it), so the three required cases
(known back face/normal card/front face) are covered by synthetic
bulk-data fixtures instead, per the task's own "if golden-set expectations
fit" conditional wording; full suite 1099 passed / 4 skipped (the same
CI-documented named skips — nothing newly broken); `makemigrations --check`
clean (no model change).

**color_profile / quality_signals / fetch-health completion — LAST Stage C manifest
extractor group, built** (public issue #150's re-spec, 2026-07-20 — the phash half of the
original issue is DROPPED per the owner's same-day re-spec comment on #150, superseded by
user-submitted phash on the art-similarity flag, task #203; set-symbol phash already shipped
separately as `symbol_region`, issue #160): adds `fetch_latency_ms`, `fetch_image_format`,
`image_is_truncated`, `blur_variance`, `image_entropy`, `color_mean_rgb`, `color_stddev_rgb` to
`ImageEvidence` (migration `0075`, additive-only `AddField`s, no freeze conflict — checked
`gh issue list --label deploy-freeze-active --state all` fresh immediately before writing the
migration, empty). New, NOT-protected-core module `cardpicker/local_image_quality.py`
(`docs/upstreaming/license-provenance.md` §2's file list doesn't include it — new helpers land
there directly, same convention `local_ocr.py` already established for OCR-adjacent additions):
`is_image_truncated` (forces a full pixel decode via `Image.load()`, catching the `OSError`
Pillow raises for a genuinely truncated download — verified empirically against a real
half-written JPEG before being wired in), `compute_blur_variance` (variance of a Laplacian-kernel
edge response over the grayscale image, cropping out `PIL.ImageFilter.Kernel`'s own documented
1-pixel unprocessed border first — verified empirically that a flat solid-color image reports an
exact-zero interior response only after that crop, not before), `compute_entropy` (Pillow's own
built-in `Image.entropy()`, not reimplemented), and `compute_color_profile` (per-channel R/G/B
mean + population stddev via `PIL.ImageStat.Stat`, not a hand-rolled pixel loop) — all first-party
Pillow APIs, no external code ported (matching this repo's own provenance-sweep precedent for
`local_phash.py`/`local_fallback.py`, `docs/upstreaming/license-provenance.md` §1.7). No changes
to `local_fallback.py`/`local_phash.py` themselves (both PROTECTED CORE; not touched by this PR).

`quality_signals` runs `is_image_truncated` first and shares that finding with `color_profile`
just below it (an explicit cross-extractor dependency, documented in `image_evidence.py`'s module
docstring the same way `artist_ocr` reusing `collector_line_ocr`'s raw text already is) rather than
re-attempting the same decode twice; `blur_variance`/`image_entropy` are only computed once the
image has loaded cleanly, since a truncated image's partial pixel data would produce meaningless
numbers, not a real reading. Both extractors share a degenerate-size (zero/negative width or
height) guard with `skip_reason="ambiguous"`, the same "sub-floor input" category
`geometry_bleed`'s own zero-height guard and `symbol_region`'s degenerate-crop-box guard handle for
their own divisions/crops — real fetched images essentially never hit this. A truncated image is
reported through the SAME `"fetch_failed"` skip reason `fetch_health` already uses, deliberately —
see the vocabulary note below.

**Vocabulary discipline, advisor-reviewed before building**: the initial design considered
widening `fetch_error_class`'s value space (distinguishing an unsupported source type from a
generic fetch failure) and inventing a new skip-reason string for a truncated download
(`"unfetchable-image"`, an existing but different subsystem's term). Both were dropped after
review: the task asked to complete fetch-health's _fields_ (plural — i.e. add columns), not widen
what values an existing field can take, and `docs/features/catalog-completion-plan.md`'s own
`CardScanLog` design explicitly warns against a separately-invented skip-reason vocabulary ("the
pipeline's own existing strings verbatim... not a separately-invented vocabulary"). The simpler,
fully-precedented path shipped instead: `fetch_error_class` stays `""`/`"fetch_failed"` only, new
fields (`fetch_latency_ms`, measured around the SAME `fetch_card_image` call this extractor
already made — no second fetch; `fetch_image_format`, the fetched image's own `PIL.Image.format`)
complete the trivial substrate-PR version of this extractor, and a truncated image is bucketed
under the same `"fetch_failed"` skip reason `quality_signals`/`color_profile` share above.
`FETCH_HEALTH_EXTRACTOR_VERSION` is bumped `v1` → `v2` to signal that a row bearing the old tag
predates these two fields, per `ImageEvidence`'s own "per-field completion/versioning map" design
intent.

**Golden-set gathering — closed by public issue #216 (2026-07-20)**: this PR's own worktree had
neither production DB credentials nor a route to the real network fetch path (no `docker/.env`,
and reaching into the live containers to work around that was declined), so it shipped without
`GOLDEN_EXPECTATIONS` entries for `quality_signals`/`color_profile`/`fetch_health`'s completed
fields — the owner relaxed the golden gate for this one PR on condition it was confirmed sooner
than later, tracked as issue #216. A follow-up session with prod docker access ran the same
read-only, no-persistence `extract_card_evidence()` sweep every prior extractor used (30/30 golden
cards fetched cleanly, PNG/JPEG, 0/30 truncated) and populated `GOLDEN_EXPECTATIONS["quality_signals"]`/`["color_profile"]`/`fetch_health`'s new `fetch_image_format` field — bringing this PR
to the same golden bar as #147–#151/#160. `blur_variance`/`image_entropy`/`fetch_latency_ms` are
real continuous/timing values this run also produced but are deliberately NOT hard-pinned (same
"exclude the continuous/brittle" rationale every prior extractor's own golden-set comment gives for
width/height/aspect_ratio/the raw phash int); `color_profile` in particular has no discrete signal
at all, so its real recorded per-card mean/stddev values are kept in `golden_set.py` as a
documentation artifact only — `test_golden_set.py` checks shape/type/range, not exact equality,
against them. 18 new tests (10 in a new
`test_local_image_quality.py` - the pure math functions, tested in isolation with real PIL images;
`is_image_truncated` specifically tested there rather than through the full pipeline, since a
genuinely truncated real file would also trip up earlier real-pixel-reading extractors that run
before `quality_signals` in `extract_card_evidence`'s own order, a pre-existing, out-of-scope gap
in those extractors, not something to route around by picking a "safe" truncation point - 8 in
`test_image_evidence.py`'s new `TestExtractCardEvidenceQualitySignals`/`ColorProfile` classes),
plus 13 pre-existing `TestExtractCardEvidence`/`GeometryBleed`/`CropCoordinates` `_StubImage`-based
tests updated for the two new extractors' presence (`_stub_quality_signals`/`_stub_color_profile`
helpers, mirroring `_stub_symbol_region`'s own identical rationale); full suite (host venv) 1106
passed / 4 skipped (the same CI-documented named skips - nothing newly broken); `makemigrations --check` clean.

**Stage C bulk driver: compute profile + concurrency/OCR-cost fix (2026-07-20)** —
`docs/reports/2026-07-20-pipeline-compute-profile.md` measured the bulk cohort driver
(`run_image_evidence_cohort.py`, previously landed on an unmerged worktree branch only, ported to
master in this same pass) at 71–378h projected wall-clock for the full ~218k-card harvest against
a 6.2h reference budget (11.5x–61x over), concentrated in the two Tesseract-backed extractors
(`ocr_group` 41.7%, `legal_line` 16.2%, together 58%), with the driver's `ThreadPoolExecutor (concurrency=6)` measured 3.25x SLOWER than sequential (CPU-bound OCR oversubscribing a fixed core
count, not the I/O-bound case that concurrency level was validated for on the fetch stage). Fixed
two ways: (1) the driver now uses a `ProcessPoolExecutor` sized to the host's USABLE compute cores
(owner-confirmed hardware: 8 OCPU total, 1 pinned to network traffic, 7 usable — `--workers`/
`STAGE_C_WORKERS` env-tunable, default 7), each worker forcing `OMP_THREAD_LIMIT=1` so N processes
don't ALSO nest-oversubscribe tesseract's own internal OpenMP threading; a local synthetic
micro-benchmark (not the authoritative re-profile — that happens after deploy) reproduced the
qualitative finding directly: `ThreadPoolExecutor` at 0.24–0.29x vs sequential, `ProcessPoolExecutor`
at 4.0–4.9x. Converting to a process pool required re-deriving three pieces of state threads were
sharing for free (DB connections, the stop-on-lockout flag, and `harvest_fetch_limiter`'s
process-local rate limiter singleton) — see `docs/lessons.md`'s new entry on this for the general
pattern, and `run_image_evidence_cohort.py`'s own module docstring for the specific fix to each.
(2) `local_ocr.run_tesseract_text_and_words` (new) derives BOTH a variant's raw text and its
TSV word boxes from a single `pytesseract.image_to_data` call, replacing collector_line_ocr's old
separate `run_tesseract` + `run_tesseract_tsv` calls on the same winning variant (measured 2.01x
speedup for that call site alone, local micro-benchmark); both collector_line_ocr's and
legal_line's own multi-variant loops now short-circuit at the first variant that parses something
usable, instead of always OCR-ing every variant. No `ImageEvidence` field or its semantics
changed — same signal set, cheaper to compute; full backend suite green (1184 passed / 4 skipped,
same CI-documented named skips) including the real-tesseract
`TestExtractCardEvidenceArtistOcr::test_finds_artist_within_collector_line_crop_without_a_second_ocr_pass`
reuse test, run explicitly to confirm the short-circuit doesn't starve `artist_ocr`'s own
reuse-before-recompute path.

**Stage D no-text bucket: OCR preprocessing/crop recovery + supersede/re-vote tooling (issue
#259)** — a diagnostic over run `staged-write-20260721T0434Z`'s 9,675 join-key `no-text` skips
found 88.8% carry recoverable signal, not a genuine coverage ceiling: 76.8% show non-empty
garbled collector text (a region was found and read, unparseably) and the population skews
bottom-quartile `blur_variance` (blurry uploads). Fixed at the `collector_line_ocr` extractor
level (`image_evidence.py`), NOT by changing `parse_collector_line`'s own regexes: a new,
lazily-evaluated attempt tier (`_collector_line_ocr_attempts`) tries `local_ocr. preprocess_variants`' original two PSM-6 polarity variants first (unchanged happy path), then —
only once BOTH have failed to parse a collector number — a fallback tier (`local_ocr. preprocess_fallback_variants`: heavier 5x upscale + `ImageFilter.UnsharpMask` for blur, plus a
median-anchored percentile threshold for uneven-brightness "garbled" crops, percentile tried
first since `UnsharpMask` can amplify noise into a spurious digit-shaped fragment that would
otherwise win the "first successful parse" race), then a re-try of the original variants under
`ALTERNATE_TESSERACT_CONFIG` (`--psm 11`, sparse-text mode — targets a segmentation failure, not
a pixel-quality one). Worst case 8 tesseract calls (up from 2) — only paid by cards the happy
path already failed on. Real, reproducible recovery demonstrated at the `local_ocr` function
level (`test_local_ocr.py::TestFallbackTierRecoversBlurryUpload` — a `GaussianBlur(1.1)` crop
where tesseract 4.1.1 misreads "158" as "168" under the base tier and the fallback tier reads it
correctly) — an end-to-end `extract_card_evidence`-level demonstration was attempted but not
achieved: the same blur parameters produce a hard pass/fail cliff through the real
`crop_coordinates`-derived box geometry, with no stable band where the base tier cleanly fails
and the fallback tier cleanly recovers in reasonable search effort; aggregate recovery rate was
an open question for the real gated re-extraction at the time this section was first written, not
something this PR's fixtures could quantify on their own.

**Aggregate recovery rate, now measured (2026-07-21, run `ntx-0721`, see
`docs/reports/2026-07-21-recovery-arc.md` for the full verification)**: 9,675 `no-text`-skipped
cards re-extracted under the fallback tier above, **3,032/9,675 (31.3%) gained a parsed collector
number**, and 7,897/9,675 (81.6%) gained at least some non-empty raw text. The follow-on Stage D
pass over exactly the 3,032-card recovered cohort (`run_id=staged3-0721`) resolved only 20 of them
to an actual printing match, with 2,990 resolving to a confirmed no-match vote instead — consistent
with this section's own characterization of the bucket (garbled-not-blank text, bottom-quartile
`blur_variance`) plus `#151`'s "NOT FOR SALE"/proxy-watermark motivating case: recovering readable
text from a blurry/garbled crop overwhelmingly means recovering a real proxy/custom-card marker,
not a previously-illegible official collector line. Read as a real OCR-preprocessing win
(readable text recovered from cards that previously contributed none) with a classification, not
identification, character. Companion tooling: `reparse_collector_evidence` (new management command, dry-run
by default) re-parses `ImageEvidence.collector_line_raw_text` with the CURRENT parser and
retracts the stale `stage-d-join-key-v1` vote/scan-log for exactly the cards whose join-key
CONCLUSION changed (compared against the RECORDED `CardPrintingTag`/`CardScanLog` state, not
against `ImageEvidence`'s own stored parse — see that command's own module docstring for why the
naive stored-field comparison is a silent no-op for the no-text cohort), gated by a card-level
`resolve_printing(card) is not None` safety check (covers both a resolved printing and a
resolved `NO_MATCH`) that lists a currently-resolved card for human review instead of retracting.
`--selector parser-bug` targets the #260 bug's own misparse shape and is immediately actionable
(zero re-extraction needed); `--selector no-text --stage-d-run-id RUN_ID` needs a PRIOR
`run_image_evidence_cohort --card-ids-file <cohort>` re-extraction pass (new flag, bypasses both
priority ordering and the resume filter for explicit ids) before it finds anything to retract.
28 new tests (13 `test_local_ocr.py`, 6 new in `test_image_evidence.py`, 17
`test_reparse_collector_evidence.py`, 2 `test_run_image_evidence_cohort.py`); full backend suite
green (1268 passed / 4 skipped, same CI-documented named skips).

### Recovery-arc lessons — precondition artifact for the 197,428-card Stage C remainder GO (2026-07-21)

Five owner-authorized runs executed directly against prod on 2026-07-21 (parser-bug reparse/
retraction, an AI-art tag-detector write, the no-text-cohort re-extraction, and two further Stage
D join-key passes — `docs/reports/2026-07-21-recovery-arc.md`, verifying
`docs/reports/2026-07-21-staged-write.md`'s original write) surfaced five operational lessons,
folded in here as the precondition artifact for authorizing a full-catalog Stage C harvest of the
remaining 197,428 cards (confirmed still current: `Card.objects.filter(content_phash__isnull=False).count()`
= 218,228 minus 20,800 distinct cards with a current `ImageEvidence` row today, unchanged since
`docs/reports/2026-07-21-stagec-20k-extraction.md`/`docs/reports/2026-07-21-staged-write.md` both
recorded the same figure — no further Stage C extraction has happened since).

**1. Remainder-run ordering — cheap pre-classification short-circuit.** The `collector_line_ocr`
extractor's issue #259 multi-tier attempt loop (`image_evidence._collector_line_ocr_attempts`)
currently escalates from tier 1 (the original 2 PSM-6 attempts) through tiers 2–3 (4
heavier-preprocessed variants + a PSM-11 re-try, 6 more tesseract calls) for EVERY card whose tier
1 fails to parse a collector number — regardless of whether tier 1 found no text at all, or found
real (but non-collector-line) text. Verified against today's own recovery data
(`ImageEvidence.collector_line_raw_text` for a card that never parses anything across all 8
attempts is, by construction, exactly tier 1's own first-attempt text — see
`compute_card_evidence`'s own fallback-to-`collector_texts_and_words[0][0]` behavior): of the
6,643 cards still carrying a `no-text` join-key skip after today's full re-extraction (the
`ntx-0721` cohort, post-escalation), **6,625 (99.7%) have literally zero digit characters
anywhere in their tier-1 OCR text** (1,778 blank, 4,847 non-blank-but-digit-free) — meaning
tiers 2–3's heavier preprocessing was paying full cost to re-read the SAME non-digit text more
clearly, never to manufacture a collector number that wasn't there in any form. Only 18/6,643
(0.27%) had a digit-bearing tier-1 read that still never validated, even after every escalation
tier — and escalating didn't help those either.

Proposed short-circuit (spec only, not built in this PR — see implementation-scope judgment
below): after tier 1's own two attempts both fail to parse a collector number, check whether
EITHER attempt's raw text contains any digit character (a cheap in-memory string scan against
already-computed OCR text — no new image work, no new tesseract call) before reaching for tiers
2–3. If neither attempt found a single digit, skip straight to the `no-text` outcome; escalate
only when tier 1 found digit-bearing (if unparseable) text.

**CRITICAL correction, owner-stated, encoded verbatim**: proxy/NOT-FOR-SALE marker PRESENCE is
NOT a custom-card signal — the catalog REQUIRES every card, real printings included, to carry
proxy marking; only the collector line's own STRUCTURE (does it contain a plausible collector
number, regardless of what else is on the line) discriminates a genuine Wizards printing from a
custom/proxy upload. The short-circuit above is deliberately keyed on digit-bearing STRUCTURE in
the collector-line crop's own OCR text, never on whether a proxy/NOT-FOR-SALE marker was detected
anywhere (that's a different crop — `legal_line`, issue #151/#159 — and a different, existing
signal entirely, already wired as the moderator-flag veto in `_apply_agreement_checks`, item 4
below). Marker-text deductions are bonus signals only, never a stand-in for the collector-line
structure check.

**Open verification gap, not fully closeable from stored data**: whether ANY of the 3,032 cards
`ntx-0721` genuinely recovered a collector number via tiers 2–3 would have had literally ZERO
digits at tier 1 alone (which the short-circuit above would then incorrectly skip, silently
losing that one recovery) cannot be checked from what's persisted today — `ImageEvidence` only
stores the WINNING variant's raw text, not every tier's own intermediate output, so a card that
needed escalation to succeed has no surviving record of what tier 1 alone produced. A small,
targeted validation pass (re-running tier 1 alone, in isolation, against a sample of these 3,032
cards' already-cached fetched images, comparing against their known-successful escalated outcome)
is recommended before trusting the short-circuit at full-remainder scale — not run here (out of
scope for this docs-first PR, and the 99.7%/0.27% split above is strong enough evidence to spec
the short-circuit, not strong enough to certify zero regression on its own). **Partially closed
by the implementation (2026-07-21)**: `run_image_evidence_cohort`'s own `short_circuited` counter
(`ExtractionResult.short_circuited` → `_CohortStats.short_circuited`, printed in both the
progress line and the final `DONE` summary) means the 197k-card remainder run itself now produces
a real short-circuit-rate measurement as a side effect of running — this still doesn't answer
"how many would have recovered at tiers 2-3" directly, but a large gap between the remainder's
own rate and the 99.7% figure above would be an early warning worth investigating before trusting
the projection in item 5 below at full scale.

**2. Atomic cast-and-route — corrected finding, not the premise as originally stated.** Read
`local_calculate_verdicts.py`'s `Command.handle()` directly: `run_join_key_calculator` and
`run_slow_path_calculator` already run in ONE invocation/`run_id`, unconditionally, every time
`--write` is passed — this is not a gap in the command itself. The very first write run
(`staged-write-20260721T0434Z`) proves this end-to-end: 8,925 join-key votes AND 16,928 slow-path
routing rows landed atomically in that one invocation
(`docs/reports/2026-07-21-staged-write.md`).

What actually happened today, verified live against the DB (not inferred from logs): pass 2
(`staged2-0721`, the 100-card parser-bug retraction cohort) and pass 3 (`staged3-0721`, the
3,032-card no-text re-extraction cohort) both ran this SAME atomic command, but
`CardScanLog.objects.filter(anonymous_id="stage-d-slow-path-v1")` shows rows from
`staged-write-20260721T0434Z` ONLY — zero rows for either `staged2-0721` or `staged3-0721`.
Root cause, confirmed by reading `reparse_collector_evidence.reparse_and_retract` directly: it
retracts a card's stale `stage-d-join-key-v1` `CardPrintingTag`/`CardScanLog` rows before
re-voting, but never touches that card's own `stage-d-slow-path-v1` `CardScanLog` row from the
ORIGINAL routing pass. `_slow_path_eligible_cards_queryset` excludes any card already carrying a
`stage-d-slow-path-v1` row, permanently — so a card retracted-and-revoted at the join-key layer
is silently excluded from ever being re-routed at the slow-path layer, even though
`local_calculate_verdicts --write` correctly re-ran both stages in the same invocation
immediately afterward. Exact count, queried live: **3,042 cards** (30 from pass 2 — 14
`border-mismatch` + 16 `proxy-marker-veto` — plus 3,012 from pass 3 — 2,990 `is_no_match` votes +
15 `border-mismatch` + 4 `ambiguous` + 3 `proxy-marker-veto`) carry a join-key conclusion that
postdates their only `stage-d-slow-path-v1` row.

**This is NOT the same as "invisible to the shipped clustering backend," and that framing is
withdrawn here after direct verification** — the task brief and
`docs/reports/2026-07-21-recovery-arc.md`'s own next-step item 2 both assumed these cards need a
FUTURE slow-path routing pass to become visible; reading `cardpicker/review_clusters.py` directly
shows this is wrong. `_review_queue_card_ids()` only checks for the EXISTENCE of a
`stage-d-slow-path-v1`/`to-review` row (any `run_id`, any point in time) — these 3,042 cards
already have one, from the original run. `_eligible_review_cards()` additionally requires
`printing_tag_status=UNRESOLVED`, which all 3,042 still are (a single 0.5-weight machine vote
can't cross the resolution threshold alone — confirmed by this same arc's own gate re-derivation,
0/12,684). And `_current_evidence_by_card_id` re-reads each card's CURRENT `ImageEvidence` row
fresh, keyed on live `content_phash` — not from anything stored on the stale `CardScanLog` row
itself (which, additionally, has never stored a per-card reason at all: `skip_reason` is
hardcoded to the literal string `"to-review"` for every row this calculator ever writes — there
is no stale "reason" field to be wrong). **All 3,042 cards are therefore already visible and
correctly clusterable in the shipped review-cluster backend (#262/#265) today, with fresh
signals** — confirmed by code reading, not assumed.

What IS real, and worth fixing as hygiene (not as a remainder-GO blocker): the retraction
tooling's incompleteness is a latent gap, currently harmless only because today's one consumer of
the slow-path marker (#262/#265) never reads anything from that row beyond its bare existence. A
future consumer that reads something more specific from it (e.g., a per-card "why was this
routed" reason, which doesn't exist today but could be added later) would silently inherit stale
state through this same path. Fix spec (owner-gated, not built in this PR): extend
`reparse_collector_evidence.reparse_and_retract` to also delete the retracted card's own
`stage-d-slow-path-v1` `CardScanLog` row in the same pass it deletes the `stage-d-join-key-v1`
rows — mirroring the existing delete, same safety gate (`resolve_printing(card) is not None`
refusal), same `--write`-gated convention. Once that ships, no separate "one-off routing pass"
command is needed for today's 3,042: they are already correctly visible, and the fix only matters
for the NEXT retraction pass, not this one.

**For the remainder run specifically: no fix is needed.** The 197,428 remaining cards have never
been touched by any engine — no stale `stage-d-slow-path-v1` row exists for any of them, so
`local_calculate_verdicts --write` will atomically cast-and-route them exactly as it did for the
original 20,800-card cohort (proven: 8,925 votes + 16,928 routed, same invocation, fully
reconciled). The atomicity property the remainder GO depends on already holds; today's gap is
specific to retraction/state-clear passes over PREVIOUSLY-touched cards, a distinct concern from
the remainder harvest.

**3. State-clear safety — mandatory dry-run before any `--selector` state-clear write.** Today's
runbook ran `reparse_collector_evidence --selector parser-bug` as a dry-run/write pair (dry-run
first, confirmed identical counts, then `--write`), but ran
`--selector no-text --stage-d-run-id staged-write-20260721T0434Z` (the state-clear step ahead of
Stage D pass 3) straight to `--write`, with no preceding dry-run — the one place in the whole
arc's runbook this happened
(`docs/reports/2026-07-21-recovery-arc.md`'s own "Run parameters" table: every other pair has a
matching dry-run row, row 19 does not). This was also the one step whose omission — skipped
ahead of pass 2 as "redundant" — caused a real, silent scope gap: pass 2 never touched the
3,032-card no-text-recovered cohort at all, because those cards still carried a stale `no-text`
join-key skip row until the state-clear step retracted it, only caught before pass 3 by
re-checking the runbook, not by any automated gate.

**Binding runbook rule, effective immediately for every future invocation of this command**: a
dry-run of the EXACT same `--selector`/`--stage-d-run-id`/`--card-ids-file` invocation is
mandatory before its corresponding `--write` — no exceptions for a selector that "should be
mechanical" (the no-text selector's own narrower, more mechanical retraction logic was exactly
the reasoning offered for skipping it today, and it was still the one place the process gap
surfaced). This is a documented process discipline, not a code-enforced gate in this PR — a code
guard (e.g., requiring evidence of a matching prior dry-run before accepting `--write` for the
same selector/cohort) is a plausible future hardening, tracked here as a candidate, not built
(implementation-scope judgment below).

**4. Marker-absence compliance scan — owner requirement, verified against the current build:
nothing scans for it today.** Owner, verbatim: "all cards in the catalog should show proxy/not
for sale somewhere even if they are an actual printing. that is a catalog requirement, we scan it
to pass on to moderation when not there." Checked directly, not assumed:
`legal_line_proxy_marker_detected` (issue #151/#159) is read in exactly one place in the
codebase, `local_calculate_verdicts._apply_agreement_checks`, and only for the case where it's
`True` (the moderator-flag VETO — a detected marker makes an otherwise-good join-key match
untrustworthy, per item 1's own CRITICAL correction above). The OPPOSITE case —
`legal_line_proxy_marker_detected == False`, marker genuinely absent — is never read, checked, or
routed anywhere. `CardReport`/`CardReportReason` (`docs/features/moderation.md`'s report-button
system) has no reason choice for this at all (`NSFW`/`LOW_QUALITY`/`WRONG_CARD`/`BROKEN_IMAGE`/
`OTHER` only), and no management command or extractor writes a `CardReport` row automatically.
**Verdict: not built anywhere — this is a real gap against a stated catalog requirement, not
already covered by existing machinery.**

Current population (read-only, live DB, 2026-07-21): of the 20,800 cards with a current
`legal_line` evidence row, **14,412 (69.3%) show `legal_line_proxy_marker_detected=False`**
(marker absent), 6,337 (30.5%) show `True` (marker present), 51 (0.2%) are `NULL` (the extractor
never reached a conclusion, e.g. a truncated/failed fetch). This 14,412 count is a snapshot of
today's 20,800-card Stage C cohort only — it will grow roughly proportionally as the 197,428-card
remainder is extracted, not a fixed ceiling.

Spec (not built in this PR — owner-gated): a new, dedicated scan (its own management command or a
mode of an existing reconciliation pass, run per Stage C extraction batch — "cadence: per
extraction run," matching every other reconciliation report in this pipeline) that queries
current `ImageEvidence` rows for `legal_line_proxy_marker_detected=False`, excludes cards already
flagged (idempotent, same exact-match-`anonymous_id`/append-only convention every other engine in
this codebase uses — e.g. a dedicated `anonymous_id` value on a new `CardReport` row, or a new
`CardReportReason` choice if that model is judged the right sink), and routes the result to the
EXISTING moderation queue (`docs/features/moderation.md`'s already-shipped report/review
machinery — the owner's own wording, "pass it on to moderation," names the existing sink rather
than a new one). Population: cards with current evidence only (the 14,412 above, growing with the
remainder). Not built here: this needs the same dry-run/write convention, safety gate, and test
coverage every other tool in this pipeline carries, and a decision on which existing moderation
surface (a new `CardReportReason`, or a distinct machine-only flag) is the right sink — an owner
call, not made here.

**5. Multi-pass OCR tiers are now the deployed Stage C default (banked); projected remainder
runtime, with vs. without the short-circuit.** Issue #259's multi-tier `collector_line_ocr`
escalation (item 1 above) is live in the current `master` build — every future Stage C extraction
run, including the remainder, uses it automatically; there is no separate opt-in. Using today's
two real measured rates: **5.4 cards/s "plain"** (the 20,000-card cohort's own 5.367 cards/s,
`docs/reports/2026-07-21-stagec-20k-extraction.md` — measured 2026-07-21T02:27Z, which predates
issue #259's merge (2026-07-21T10:48Z UTC) by ~8h, so this is genuinely the pre-multi-pass,
tier-1-only baseline rate) and **3.5 cards/s "multi-pass-heavy"** (the `ntx-0721` no-text
re-extraction run's own measured 3.492 cards/s, `~/writes-20260721-recovery.log` — a
100%-escalation-guaranteed cohort by construction, every one of its 9,675 cards had already
failed tier 1 once before, so this is the real worst-case per-card cost once every tier runs).

Projection (estimate, not a direct measurement — stated assumptions below), for the 197,428-card
remainder:

- **Without the short-circuit** (today's actual deployed default): extrapolating the original
  join-key cohort's own `no-text` fraction (9,675/20,677 ≈ 46.8% of cards failed tier 1 entirely
  under the pre-#259 baseline) onto the remainder, and blending the two measured rates by that
  split (weighted-average per-card cost, `0.468 × 1/3.492 + 0.532 × 1/5.367 ≈ 0.233s/card` ⇒
  ≈4.29 cards/s blended): **197,428 ÷ ~4.29 ≈ 46,000s ≈ ~12.8h** — a ~25% erosion of the
  design doc's own ~10.2h target (`docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md`'s
  decoupling design, restated as the 20k-cohort's own gate in
  `docs/reports/2026-07-21-stagec-20k-extraction.md`), driven entirely by cards paying full
  6-tesseract-call escalation cost for zero benefit.
- **With the short-circuit** (item 1's proposal): since 99.7% of the genuinely-unrecoverable
  tier-1-failure population is non-digit-bearing at tier 1 (this arc's own measured figure) and
  would exit at tier-1-equivalent cost rather than paying for tiers 2–3, only ≈0.14% of the total
  remainder (46.8% × 0.27%) would still pay the heavy multi-pass cost: **≈
  (197,428 − 276) ÷ 5.367 + 276 ÷ 3.492 ≈ 36,800s ≈ ~10.2h** — back in line with the original
  design-doc target.

Assumptions stated plainly: (a) the 46.8% tier-1-failure fraction is extrapolated from the
original 20,677-card cohort, not independently measured for the untouched remainder; (b) blending
by blended per-card cost assumes throughput scales roughly linearly with per-card compute cost,
consistent with the compute-profile report's own finding that OCR/legal-line extraction dominates
per-card cost (`ocr_group` 41.7% + `legal_line` 16.2% ≈ 58%,
`docs/reports/2026-07-20-pipeline-compute-profile.md`); (c) the short-circuit's own regex-check
cost is treated as negligible (a cheap in-memory string scan, no new I/O or image work).

**Implementation-scope judgment for this PR**: docs-only. None of items 1–4's code changes are
bundled here. Reasoning, stated per item rather than as one blanket call: item 1's short-circuit
and item 2's retraction-tooling fix both touch already-shipped, in-production extraction/retraction
tooling that carries its own dry-run/safety-gate/test conventions (`_collector_line_ocr_attempts`,
`reparse_and_retract`'s safety gate) — correctly extending either needs its own test coverage
(a real, not-yet-collected fixture demonstrating the short-circuit doesn't regress a genuine
digit-bearing recovery; a retraction test proving the new slow-path delete never fires when the
gate refuses) and its own review cycle, not a same-PR add-on to a docs update. Item 3 is a
runbook/process rule with no code change proposed (a future code-enforced guard is named as a
candidate, not decided). Item 4 needs an owner call on which moderation sink to use before any
code is written at all — nothing to build yet. A separate implementation PR per item, once each
is owner-approved, is the right shape — not attempted here.

**Follow-up status (2026-07-21, owner-approved)**: item 1's short-circuit is now BUILT
(`image_evidence._collector_line_ocr_attempts`/`compute_card_evidence`'s `short_circuit` param,
default ON, `--no-shortcircuit`/`STAGE_C_NO_SHORTCIRCUIT` escape hatch) — see this section's own
"moderator-flag signal" write-up above for the companion correction (the marker withhold this
item's own CRITICAL correction flagged is retired too, in the same PR) and
`reparse_collector_evidence --selector proxy-marker-veto` for the matching re-scan tooling.
Item 2 (the retraction-tooling slow-path-delete gap), item 3 (a code-enforced dry-run guard), and
item 4 (the marker-absence compliance scan) remain unbuilt, owner-gated as this section originally
scoped them.

Queued behind Stage B per the paced task sequence (#145–149, #151, #160). Stage D
carries a hard precondition: the pipeline-fidelity gate (task #151,
owner directive 2026-07-19) — calculators must call the existing
shipped identification code paths with `ImageEvidence`-supplied
inputs, not re-derive their logic; a stratified-sample parity replay
against run `20260716T193408-6613a1a6`'s recorded outputs must show
zero unexplained divergence; a full knowledge-inventory sweep (every
empirically-derived constant/threshold/override/skip-reason mapped to
its home in the new pipeline, or flagged missing) must be clean. Both
gate task #148 (the owner HOLD deliverable) and any full-catalog fire.

**Gate artifact 2 (knowledge-inventory sweep) status, 2026-07-22**: run —
`docs/reports/2026-07-22-knowledge-inventory.md`. NOT clean as originally
worded above: 3 confirmed MISSING items (`RESOLUTION_FLOOR_DPI=200` has no
Stage C/D analogue at all; `EXCLUDED_RESOLVED_TAGS` custom-art/non-english
exclusion and the deductive-backfill-covered exclusion are both absent from
Stage D's `_eligible_cards_queryset`) plus 3 open items (the pilot's
per-batch checkpoint-flush cadence vs. Stage D's single end-of-run flush;
`NAME_FREQUENCY_ANONYMOUS_ID`'s structural-elimination engine has no Stage D
port; printing-vote d≤2 cluster propagation has no confirmed Stage D
equivalent). None of the three MISSING items are soundness violations (the
human-backed consensus gate still applies to every vote Stage D casts), but
the gate's own "must be clean" bar is not met as stated — owner review
needed on whether these three are must-fix-before-fire or accepted gaps.
Artifact 1 (the stratified-sample parity replay) is separately queued
behind the extraction and not addressed by this pass.

**Stage C: fetch/compute decoupling design (2026-07-20, addresses the canary's
63.1% parallel-efficiency gap)** — the process-pool fix above (PR #224) was a
real, large improvement (377.8h projected at x6 thread-pool concurrency down
to a process pool matching the 7 usable cores), but a 400-card canary against
rebuilt prod (`docs/reports/2026-07-20-canary-reprofile.md`, run
`stagec-canary-20260720T1659Z`, `--workers 7`) measured only **63.1% parallel
efficiency** (458.79 CPU-s / 400 cards = 1.147 CPU-s/card, against a
theoretical 7-way budget of 1.817 CPU-s/card) — equivalently, **4.41 of 7
workers busy on average** (458.79 CPU-s ÷ 104s wall-clock), meaning ~37% of
usable cores sit idle rather than pegged. Idle-not-pegged is the signature of
workers stalling on I/O, not CPU contention, and the almost-certain cause is
structural: `run_image_evidence_cohort.py`'s per-card work unit
(`_process_one_card`, lines 194–220) calls `extract_card_evidence(card)` at
line 213, and that function's own first step (`image_evidence.py` line 295,
`image = fetch_card_image(card, dpi=dpi)`, inside `extract_card_evidence`
defined at line 280) does a real network fetch — bundled into the same
worker process that then goes on to run the OCR-heavy extractors. Every one
of the 7 compute workers spends part of each card's wall-clock blocked on its
own Google-image fetch before it can start the CPU-bound work it exists to
do. This is a design gap, not a re-litigation of the canary's own STOPPED gate
decision — that decision (condition (a), ~15.7–16h projected vs. a ~15h
ceiling) stands; this section is the design to close the gap the canary
surfaced, plus what would need to be measured to confirm it before spending
more compute on a re-profile.

The **~6.2h reference budget**'s provenance (fetch-only, predates Stage
C/OCR) is fully derived in the Fetch Acceleration Study above (see "Two
ceilings, confirmed distinct" and its deliverable table) and confirmed
not to include compute cost by
`docs/reports/2026-07-20-pipeline-compute-profile.md`'s own "Fetch vs.
compute" section; not re-derived here. The decoupling design below leans
on it directly: once fetch and compute run as two independent concurrent
stages instead of one bundled per-card unit, the two stages' wall-clocks
compose as `max(fetch, compute)` rather than `fetch + compute`.

**1. Decoupling architecture.** Two concurrent stages instead of one bundled
per-card unit:

- **Fetch stage**: a pool of fetch threads (I/O-bound — a Python thread
  releases the GIL for the duration of the blocking `requests.get` inside
  `rate_limited_get`, so threads are the right primitive here, unlike the
  compute stage where threading measured 0.31x/3.25x-slower for CPU-bound
  OCR) built directly around `harvest_fetch_limiter.GOOGLE_IMAGE` — the
  reusable, already-integrated, already-owner-validated pacing (PR #179:
  `max_concurrency=6`, `rate_per_sec=8.0`), used exactly as
  `image_cdn_fetch.fetch_card_image` already calls it today, unmodified.
  Fetch-thread count should be sized a little above `GOOGLE_IMAGE`'s own
  `max_concurrency=6` (e.g. 8) — the limiter's own semaphore is the real
  concurrency ceiling regardless of thread count, so extra threads beyond 6
  only exist to keep a request queued and ready the instant a semaphore slot
  frees, at negligible cost (idle thread stacks, no compute). This also
  removes a piece of accepted complexity the process-pool conversion had to
  add specifically because fetch was bundled into N compute processes: today,
  `_init_worker` (lines 161–191) pre-seeds each of the 7 worker processes
  with its own workers-scaled-down copy of `GOOGLE_IMAGE` (rate and
  concurrency divided by 7, module docstring's numbered point 3) because each
  process would otherwise construct its own independent limiter instance and
  the aggregate ceiling across all 7 would silently become 7x too high. Once
  fetching lives in one place (the fetch stage, not 7 separate compute
  processes), `harvest_fetch_limiter.get_limiter`'s existing process-wide
  singleton semantics apply directly — the descaling hack has nothing left
  to compensate for.
- **Compute stage**: unchanged in spirit — a `ProcessPoolExecutor` sized to
  the 7 usable compute cores (1 of the host's 8 OCPU stays pinned to network
  traffic, per the owner-confirmed hardware profile already recorded above),
  each worker still forcing `OMP_THREAD_LIMIT=1` so N processes don't
  nest-oversubscribe Tesseract's own OpenMP threading. The difference is
  what a compute worker receives: not a bare `card_id` that it re-fetches
  itself, but a card plus an already-fetched image buffer, so a compute
  worker's own wall-clock is 100% CPU-bound extraction, never fetch-wait.
- **The queue between them**: a bounded, RAM-only handoff — the fetch stage
  produces (card, image buffer) pairs no faster than the compute stage can
  accept them, via backpressure (a bounded number of outstanding
  fetched-but-not-yet-computed buffers, enforced however the eventual
  implementation chooses to gate submission — e.g. a counting semaphore
  around handoff to the compute pool). A reasonable starting depth is on the
  order of 2x the compute pool size (~14–16) — enough that a compute worker
  finishing early never stalls waiting on the next buffer (this also directly
  addresses one of the canary's own cited efficiency-loss factors, "uneven
  per-card OCR cost" — a shallow queue would let that variance become worker
  idle time even after decoupling), without letting fetch run so far ahead
  that memory grows unbounded. The exact depth is a tuning knob for the
  confirming re-profile below, not a value to fix in this spec.

  _Memory-budget arithmetic_ (derived estimate, not a measured figure — used
  here only to show the design has wide margin, not to pin an exact number):
  at the fetch stage's `DEFAULT_FETCH_DPI=250`, the Worker's own
  `height = dpi * 1110 / 300` conversion (`image-cdn/src/url.ts`) gives a
  fetched image height of 925px; at a standard MTG card's 2.5:3.5in aspect
  ratio, width ≈ 661px. A fully-decoded RGB buffer at that size is
  `661 × 925 × 3 ≈ 1.8 MiB`. Worst-case buffers alive at once ≈ fetch
  threads in flight (≈8) + queue depth (≈16) + one per compute worker (7) ≈
  31, so ≈ 31 × 1.8 MiB ≈ **56 MiB** — even at a generous 10x that estimate
  (in case the size derivation above is off, or a future DPI bump changes
  it), total buffer memory is still under 1 GiB, a rounding error against
  the host's 24GB ceiling. This is not RAM-bound at any plausible queue
  depth; the ceiling that matters here is backpressure/throughput tuning,
  not memory.

**2. Change points.** What the decoupled structure replaces (description,
not a diff):

- `run_image_evidence_cohort.py`'s `_process_one_card` (lines 194–220) —
  today's single per-card unit, run once per card inside a compute worker,
  that both fetches (via `extract_card_evidence`'s own internal call to
  `fetch_card_image`, `image_evidence.py` line 295) and computes. This
  collapses into two cooperating units: a fetch-only step (calling
  `fetch_card_image` from a fetch thread, not a compute worker) and a
  compute-only step (running everything `extract_card_evidence` does
  _after_ its current fetch step, against an already-fetched buffer).
- `_init_worker`'s rate-limiter descaling (lines 179–191, module docstring's
  numbered point 3) — goes away once only the fetch stage ever calls
  `rate_limited_get(GOOGLE_IMAGE, ...)`; the unscaled `GOOGLE_IMAGE` config
  applies directly, with no per-process division needed.
- The cross-process stop-on-lockout `Event` (module docstring's numbered
  point 2, `multiprocessing.Manager().Event()`, checked at the top of every
  `_process_one_card` call) — a `GoogleFetchLockoutError` can now only ever
  originate in the fetch stage (compute workers no longer fetch anything),
  which simplifies where this needs to be checked, though the exact
  mechanism for telling already-idle compute workers "no more work is
  coming" (a sentinel, a different signal, or something else) is an
  implementation choice left open here, not settled by this design.

**3. Instrumentation spec for the confirming re-profile.** The canary above
diagnosed the idle-core signature by inference (aggregate CPU-seconds ÷
wall-clock), not direct measurement — it never captured where the idle time
actually went. Before spending more compute on a full re-profile, add:

- **cgroup `io.stat` / block I/O**, sampled before/after the run (same
  cgroup-read approach the canary already used for `memory.current`/
  `memory.peak`) — this pipeline's own image fetch is a network read, not
  disk I/O, so `io.stat` here mainly serves as a negative control: it should
  show ~zero incremental block-device writes throughout, confirming the
  index-not-store posture holds (no image buffer or intermediate spilled to
  disk) and ruling out unexpected disk contention (e.g. logging, Tesseract
  temp files) as an alternative explanation for idle cores.
- **Network bytes** (container network cgroup/interface counters, rx/tx
  delta over the run) — cross-checked against the memory-budget section's
  derived per-image size estimate; a large discrepancy would mean that
  estimate needs correcting before the queue-depth tuning above is trusted.
- **A per-card fetch-wait-vs-compute-time split.** `extract_card_evidence`
  already records `fields["fetch_latency_ms"]` (`image_evidence.py`, right
  after its `fetch_card_image` call) — the confirming re-profile should
  capture the matching compute-side duration (time from end of fetch to end
  of extraction) alongside it, aggregated into the run's own summary
  logging rather than a new persisted `ImageEvidence` field (this is
  re-profile instrumentation, not new catalog signal). With both numbers,
  the 63.1%-efficiency gap can be attributed directly — how much is
  fetch-wait (the hypothesis this design is built around) versus pool
  dispatch, `_init_worker`'s per-task DB reconnect cost, or genuine
  straggler variance — instead of inferred from one aggregate ratio.

**4. Expected outcome + risks.** Once compute workers never block on
download, the compute stage's own wall-clock should approach the
compute-profile report's compute-only figure divided across the 7 usable
cores: 71.2h single-threaded ÷ 7 ≈ **~10.2h**, run near-linear because the
workers are now doing CPU-bound-only work matched 1:1 to available cores
(no fetch-wait, same `OMP_THREAD_LIMIT=1` anti-nesting fix as today). Fetch
overlaps in its own already-validated ~6.2h-scale budget (`GOOGLE_IMAGE`'s
concurrency=6/rate=8.0 config) running concurrently rather than bundled in
sequence, so total wall-clock composes as `max(fetch, compute)` plus
fill/drain slack at the start and tail of a cohort, not `fetch + compute` —
landing around **~10–11h** for the full 218,212-card remaining-work pool,
materially better than the canary's measured ~15.7–16h. Risks:

- **Memory ceiling** — shown above to have wide margin (tens of MiB to
  under 1 GiB even at 10x the derived per-buffer estimate, against a 24GB
  host); the real risk is a queue-depth misconfiguration that removes the
  bound entirely (e.g. an accidentally-unbounded queue), not the depth
  values under discussion here.
- **Backpressure tuning** — too shallow a queue reintroduces compute-worker
  idle time (just moved from "waiting on its own fetch" to "waiting on the
  queue"); too deep lets fetch run far ahead of compute, which is still
  memory-bounded per the arithmetic above but wastes the fetch stage's own
  paced-rate budget on cards compute won't reach for a while. Needs
  empirical tuning against the instrumentation above, not a value fixed in
  this design.
- **Straggler cards** — the canary's own cited "uneven per-card OCR cost"
  factor means the last few cards in a cohort can leave some compute workers
  idle waiting on a fetch stage that has nothing left to hand them (a
  tail/drain concern, distinct from steady-state backpressure).
- **The network-pinned core** — the hardware profile already reserves 1 of
  8 OCPU for network traffic, separate from the 7 usable compute cores; the
  fetch stage's own threads are I/O-bound and don't need a dedicated core of
  their own, but this only holds if the fetch stage stays I/O-only (e.g. if
  `fetch_card_image`'s `Image.open()` call were ever changed to force a full
  JPEG decode eagerly, that would add real CPU work to the fetch side that
  this hardware profile didn't budget compute for — worth keeping in mind
  for whoever implements this, not a problem today since decoding is lazy).

**Confirming re-profile (2026-07-20,
`docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md`)**: fetch-wait
confirmed as the dominant cause of the canary's efficiency gap (measured
fetch fraction matches the gap within noise). Verdict: build the decoupling
design above as specified — no different fix is indicated.

**Stage C: fetch/compute decoupling — implemented (2026-07-20)**, on top of
the confirming re-profile just above (`docs/reports/2026-07-20-fetch-compute-timing-diagnostic.md`,
#235: fetch measured at 36.5% of mean per-card wall-clock, cross-validated
against cgroup CPU-seconds — the same number as the canary's "missing" ~37%
efficiency within noise, not two separate findings). `run_image_evidence_cohort.py`
now runs a `ThreadPoolExecutor` fetch stage (`--fetch-threads`/
`STAGE_C_FETCH_THREADS`, default 8) concurrently with the `ProcessPoolExecutor`
compute stage (`--workers`/`STAGE_C_WORKERS`, unchanged, default 7), joined by
a windowed handoff (`--queue-depth`/`STAGE_C_QUEUE_DEPTH`, default
`workers * 2`) that bounds how many fetched-but-not-yet-computed buffers can
be outstanding at once — the design doc's own "counting semaphore around
handoff to the compute pool" example, implemented as a `wait(..., FIRST_COMPLETED)` sliding window over the compute futures instead (easier to
drive deterministically in tests, same bounding effect). One deviation from
the literal architecture description above, reasoned through rather than
incidental: the buffer crossing the fetch/compute process boundary is the
RAW, still-encoded fetch response (`image_cdn_fetch.fetch_card_image_bytes`,
new — a bytes-returning sibling of the existing `fetch_card_image`), not a
decoded `PIL.Image`, because pickling an already-loaded `Image` for
`ProcessPoolExecutor.submit()` forces a full pixel decode at submit time
(`Image.__getstate__` calls `tobytes()`) — on whichever thread calls
`submit()`, which would silently move real CPU work onto the fetch side,
exactly what the design doc's own "network-pinned core" risk item warned
against. Decoding (`Image.open`) now happens inside the compute worker itself,
right before `image_evidence.compute_card_evidence` (new — the compute-only
continuation of `extract_card_evidence`, split so a `ProcessPoolExecutor`
worker can call it directly against an already-fetched buffer without
`extract_card_evidence`'s own single-call behavior changing for its existing
callers/tests). Two pieces of process-local state the bundled design needed
are gone rather than kept as dead code: the rate-limiter descaling in
`_init_worker` (fetching now lives in one thread pool in one process, so
`harvest_fetch_limiter`'s own process-wide singleton applies unscaled), and
the `multiprocessing.Manager().Event()` used to signal a lockout across N
compute processes (replaced by a plain `threading.Event`, since a
`GoogleFetchLockoutError` can now only ever originate in the fetch stage) —
this structurally eliminates the PR #225 bug class (calling a manager proxy's
`is_set()` after `manager.shutdown()`) rather than continuing to carefully
order around it, verified by keeping (and updating) that regression test
against the new architecture. Full backend suite green (1199 passed / 4
skipped, same CI-documented named skips); `makemigrations --check` clean (no
model change). Not yet re-profiled against live prod — that's the owner's
next authorized run, not part of this change.

**Stage D — join-key calculator (framework + first slice, built 2026-07-20,
public issue #152, "Stage D: calculators D1-D6")**: the owner directive
dispatching this work named "calculators D1-D6", but no numbered D1-D6 spec
exists anywhere — checked before building, not assumed (issue #152's own
body/comments, this doc, the private orchestration orientation doc). What
IS binding: the design frame (funnel-to-review, fast/slow path split,
collector-line-OCR-plus-set-symbol as ONE near-unique join key, the
pipeline-fidelity gate's "call the existing shipped code, don't re-derive"),
`docs/theory.md`'s candidate-constrained-decoding model, and the Governing
posture section above. Per that directive's own scope-management clause,
this PR builds the calculator FRAMEWORK plus one coherent first slice — the
join-key calculator — rather than inventing a six-item spec to fill.

New module `cardpicker/local_calculate_verdicts.py` (+ management command
`local_calculate_verdicts`, `--write`/`--run-id`/`--chunk-size`, dry-run
default, mirroring `local_residual_classify`'s own CLI shape and its
1:1 module/command filename convention). `calculate_join_key_verdict`
reconstructs an `OcrParseResult` from Stage C's already-persisted
`collector_line_set_code`/`collector_line_collector_number` fields (no
re-OCR, no re-fetch) and calls the existing, unmodified
`local_ocr.validate_against_candidates` — satisfying the pipeline-fidelity
gate by direct reuse, not a parallel implementation. `local_ocr.py` (not
PROTECTED CORE) gained a small behavior-preserving refactor,
`find_matching_candidates`, extracting the candidate-narrowing filter
`validate_against_candidates` already computed internally so a caller with
independent tie-break evidence can inspect the ambiguous match set
directly instead of only learning that ambiguity occurred.

**Collector-line OCR + set-symbol phash are ONE join key, not two
calculators**: a pre-M15 card's collector line never printed a set code, so
matching on collector number alone can hit more than one of the card's own
candidates (different expansions — `(expansion, collector_number)` is
unique per `CanonicalCard`) even though a genuine printing identity exists.
Stage C's `symbol_phash` (issue #160) resolves this inside the SAME
calculator call: the card's own rendered set symbol is compared against
each ambiguous candidate's expansion glyph
(`local_fallback.render_set_symbol`, PROTECTED CORE, called not modified)
via plain Hamming-distance arithmetic on the stored hash ints — the same
"reimplement the arithmetic, don't touch the protected decision logic"
pattern `local_identify_printing_tags._classify_no_clear_winner` already
established for phash distance re-derivation. An initial draft split this
across two calculators (D1 OCR, D2 symbol) before an advisor review flagged
that as contradicting the design frame's own "one join key" framing —
folded into one calculator before this PR was built out further.

**The moderator-flag signal** (the design frame's original explicit ask,
corrected 2026-07-21 — see this section's own "Recovery-arc lessons" item
1's "CRITICAL correction" note above for the full owner-ruling writeup):
`legal_line_proxy_marker_detected`
(issue #151/#212's real motivating case — a "NOT FOR SALE"/proxy watermark
misparsing as a plausible collector line) was originally checked only at
the moment a join-key match would otherwise be trusted, withholding it as a
named skip (`"proxy-marker-veto"`) rather than casting an `is_no_match`
vote. **Retired as a veto 2026-07-21**: the catalog requires proxy/NOT-FOR-
SALE marking on every genuine upload, real printings' proxies included, so
the field's presence carries no discriminating power over whether any
specific match is right or wrong — a live trace found it discarding 1,552
already-validated matches, 99.4% with a real, DB-matching set/number parse.
The match now proceeds unaffected (no withhold, no confidence change) —
`legal_line_proxy_marker_detected` is read but has zero effect on the
outcome.

Casts `CardPrintingTag` votes via the unmodified `VoteSource.OCR`/
`resolve_and_persist_printing` machinery (own
`anonymous_id='stage-d-join-key-v1'`, independently purgeable via the
existing `purge_machine_votes --run-id`) — a single calculator vote at machine
weight (0.5) can never resolve a card alone, reusing
`local_identify_printing_tags.verify_zero_resolutions` directly as the
command's own post-write gate (no new gate function needed — the printing-
side equivalent of `verify_no_single_machine_vote_resolutions` already
existed).

**Known, accepted overlap with the live pilot (not a bug)**: this
calculator's own eligibility query excludes only cards already carrying a
`stage-d-join-key-v1` vote/skip — it does NOT exclude cards
`local-ocr-v1`/`local-phash-v1`/`local-fallback-v1` (the live pilot's own
engines) already voted or skipped on. Since Stage C's `ImageEvidence`
cohort and the live pilot's own target pool substantially overlap during
this transitional period, running this calculator for real will frequently
re-vote on cards the old pilot already touched. Structurally safe
regardless (the human-backed gate makes it impossible for any accumulation
of machine-only votes across engines to resolve a card by itself — verified
via `vote_consensus.resolve_weighted_consensus`'s own hard AND-gate), but a
real characteristic of two mechanisms running concurrently mid-migration,
named here rather than left to surface later as a surprise.

**Agreement/corroboration layer (built 2026-07-20, issue #152 continuation,
"Stage D calculators D2-D5")**: five cross-checks folded directly into
`calculate_join_key_verdict`/`run_join_key_calculator`'s existing control
flow — no new eligible-card population, no new `anonymous_id`, no new vote
type — per the dispatching directive's own "raw cross-check feeding the
verdict, not a second classifier" framing:

- **Back-face-aware candidate selection** (issue #199/#213): new
  `_resolve_candidates_for_card` tries the card's own name first (unchanged
  fast path), and only when that finds nothing AND
  `printing_metadata_import.is_back_face` confirms the name is a known DFC
  back face, reconstructs Scryfall's own combined `"{front} // {back}"`
  `CanonicalCard.name` form (via the already-shipped `DFCPair` table's
  `back=name` lookup) and retries — fixes candidate _selection_ for a
  cohort (back-face-named split-image DFC uploads) that would otherwise
  never match at all, since `CanonicalCard.name` for these rows is never
  the bare back-face name alone.
- **Border/frame agreement**: `layout_class` vs. the matched printing's own
  `CanonicalPrintingMetadata.border_color` (direct string comparison — both
  use the same value space) and an OCR-re-derived frame class
  (`local_fallback.classify_frame_style`/`frame_style_is_consistent`,
  PROTECTED CORE, called not modified) vs. `.frame` — either disagreement
  WITHHOLDS the match (`border-mismatch`/`frame-mismatch` named skips),
  mirroring the live pilot's own frame-mismatch-withholding exactly.
  `bleed_class` is deliberately NOT cross-checked (no Scryfall field it
  could ever agree/disagree with — a proxy-sheet-formatting property, not a
  printing property), despite this PR's own earlier deferred-item wording
  naming it.
- **Copyright-year era check** (issue #152/#220 follow-up, built alongside
  the slow-path routing calculator below): the legal line's parsed
  copyright year (`ImageEvidence.legal_line_copyright_year`, issue
  #151/#159) cross-checked against the matched printing's own
  `CanonicalPrintingMetadata.released_at` — reusing the SAME
  `CanonicalCard`/`CanonicalPrintingMetadata` query the border/frame checks
  just above already perform, no second lookup. Only a gap of more than
  `COPYRIGHT_YEAR_MISMATCH_THRESHOLD_YEARS` (2) years — copyright
  _predating_ release, the one direction the design frame actually names —
  withholds the match as a new named, non-rescannable skip
  (`"copyright-year-mismatch"`); a small/plausible gap (a print run landing
  near a calendar-year boundary, an older copyright legend surviving into a
  reprint) is deliberately not vetoed. Withheld, not confidence-adjusted —
  confirmed by reading `vote_consensus.py` directly: it weights strictly by
  `source`, never `confidence`, so a confidence-field tweak here would have
  zero effect on resolution, the same point this module's own
  `JOIN_KEY_CONFIDENCE_BOTH` comment already makes elsewhere.
- **Artist-OCR corroboration**: `artist_ocr_name` vs. the matched
  printing's `CanonicalCard.artist` via `local_fallback.match_artist`
  (PROTECTED CORE, called not modified) — a disagreement WEAKENS confidence
  (`JOIN_KEY_CONFIDENCE_ARTIST_DISAGREEMENT`, 0.65) rather than vetoing,
  per the directive's own framing and `match_artist`'s own softer,
  tie-tolerant design.
- **Quality/integrity gating**: `image_is_truncated` is a hard veto
  (`truncated-image` named skip). `blur_variance`/`image_entropy` are
  deliberately NOT thresholded — both fields' own `local_image_quality.py`
  docstrings defer "what counts as too blurry/too flat" to a calibrated
  Stage D number, and #218's real golden-set gather run explicitly did NOT
  hard-pin either value; inventing an arbitrary cutoff here would violate
  this project's own "config values land only from measurement, not
  automatically" rule, so only the binary integrity signal is acted on.

All five checks above live in ONE function, `_apply_agreement_checks`,
called from both of `calculate_join_key_verdict`'s match-producing branches
(direct match, symbol-phash tie-break) rather than duplicated across them.

**Deliberate deviation from the live pilot's own precedent**:
`border-mismatch`/`frame-mismatch`/`truncated-image`/
`copyright-year-mismatch` are NOT added to `JOIN_KEY_RESCANNABLE_SKIP_REASONS` (unlike `local_identify_printing_tags`'s own rescannable
`"frame-mismatch"`) — that module's rescannability exists because a future
run re-fetches the image and may read it differently; Stage D's join-key
calculator instead reads an already-persisted, content-hash-keyed
`ImageEvidence` row, so re-selecting the same card against the same stored
evidence would deterministically recompute the identical mismatch forever.

**Two further cheap additions (built 2026-07-20, owner decision on issue
#220)**:

1. **Slow-path routing** (`calculate_slow_path_verdict`/
   `run_slow_path_calculator`, own `anonymous_id="stage-d-slow-path-v1"`):
   issue #220's settled answer for the ~83% of cards the join-key
   calculator alone can't confidently resolve — explicitly option (b) from
   that issue (send no-hit cards to the human review queue carrying their
   partial extracted signals), not (a) bulk server-side phash (the
   165k-run analysis found that costs ~84h to resolve only 2.6% — exactly
   why #203 already moved phash to user-submitted instead) and not (c)
   user-submitted phash itself (issue #203, a distinct, separately-designed,
   not-yet-built mechanism, deliberately not built here). A pure routing
   step, not a matching engine — casts no `CardPrintingTag` at all (nothing
   to vote for), only a `CardScanLog(skip_reason="to-review")` durable
   marker once a card gets a real `is_no_match` vote or a non-rescannable
   join-key/agreement-layer skip (`ambiguous`, `no-text`,
   `border-mismatch`, `frame-mismatch`, `truncated-image`,
   `copyright-year-mismatch` — `proxy-marker-veto` is no longer PRODUCED as
   of the 2026-07-21 moderator-flag-signal correction above, but stays in
   `JOIN_KEY_NO_HIT_SKIP_REASONS` deliberately so a pre-correction stale row
   still routes correctly until `reparse_collector_evidence --selector proxy-marker-veto` retracts it). No new storage: the
   signals themselves already live in `ImageEvidence` (Stage C's job) —
   `SlowPathVerdict.raw_signals` is an in-memory packaging of that same
   data for whatever consumes it next, not a second copy.
2. **Collector-number-only ambiguity guard** — a hardening/regression item,
   not new logic: the ~472 pre-M15 cards where OCR parsed a collector
   number but no set code (globally ambiguous alone — ~15.7% of
   collector-number values appear in ≥2 sets, per the run analysis
   motivating issue #220's slow-path decision) were already structurally
   safe, since `calculate_join_key_verdict` only ever receives a
   `candidates` list already narrowed to the card's own name (via
   `_resolve_candidates_for_card`, which always starts from
   `CandidateNameIndex.candidates_for(card.name)` and only ever widens to
   the DFC-combined name for a confirmed back face, never a global query),
   and `CandidatePrinting` carries no `name` field for a global re-match to
   even be expressible. Made explicit via a docstring invariant plus a
   dedicated regression test (`TestCollectorNumberOnlyStaysNameScoped`,
   including a defense-in-depth case proving a misscoped candidate list
   degrades to `"ambiguous"`, never a silent wrong-printing match) rather
   than new matching logic.

**Still deferred (not built or stubbed here)**: visual/phash slow-path
_matching_ (distinct from the slow-path _routing_ calculator built above)
— explicitly NOT bulk server-side phash (issue #150's own 2026-07-20
re-spec dropped that in favor of user-submitted phash, task #203, a
distinct, not-yet-designed mechanism); a calibrated
`blur_variance`/`image_entropy` trust-modifier threshold (needs real
measurement against production data first, per the same "measurement, not
automatically" rule above — the slow-path routing calculator already
carries both as raw signals for human review, which is not the same as a
machine trust modifier).

Golden-gated against synthetic `ImageEvidence`/`Card`/`CanonicalCard`/
`CanonicalPrintingMetadata`/`DFCPair` DB fixtures, not a live fetch — Stage
D consumes stored evidence + Scryfall-backed models, it never touches a
live image, so Stage C's "real network fetch over 30 pinned cards"
golden-set convention doesn't apply here (host venv, no network —
`render_set_symbol` IS exercised for real, a pure local font-render, so the
symbol-phash tie-break is tested against real keyrune glyph hashes;
`is_back_face` IS exercised against a real, temporary on-disk bulk-data
JSON file, never mocked). 20 new tests added on top of the agreement/
corroboration layer's own 37 in `test_local_calculate_verdicts.py` (57
total in that file now) — 10 for the copyright-year era check
(`TestCopyrightYearEraCheck`), 2 for the collector-number-only name-scoping
regression (`TestCollectorNumberOnlyStaysNameScoped`), 1 for
`calculate_slow_path_verdict`'s raw-signal packaging
(`TestCalculateSlowPathVerdict`), and 7 for `run_slow_path_calculator`
(`TestRunSlowPathCalculator`); full suite 1184 passed / 4 skipped (the same
CI-documented named skips — nothing newly broken); `makemigrations --check`
clean (no model change — every field these checks read already existed on
`ImageEvidence`/`CanonicalPrintingMetadata`); `pre-commit`
(ruff/isort/black/mypy/prettier) clean.

**Command flags, rollback, and testing posture (2026-07-20, issue
#152)**:

- **Command flags** (`manage.py local_calculate_verdicts`, both
  `run_join_key_calculator` and `run_slow_path_calculator` share the one
  invocation/run_id): `--write` (`action="store_true", default=False`) —
  the command defaults to dry-run and requires this explicit flag to
  persist any `CardPrintingTag`/`CardScanLog` row; dry-run computes every
  verdict and reports `would_cast` counts (`total_votes=would_cast=N` in
  the final summary line) while writing nothing. `--run-id` (`default=None`)
  reuses/pins a specific `run_id`; the default is a freshly generated one
  (`generate_run_id()`). `--chunk-size` (`type=int, default=500`) is the
  `.iterator()` chunk size for both calculators' eligibility querysets.
- **Rollback / poisoning containment**: writes are `run_id`-scoped (Part
  1's mechanism, unchanged), so a bad batch is revertible by deleting that
  `run_id`'s rows — `manage.py purge_machine_votes --run-id <id>` — with
  no separate DB snapshot required. This `run_id`-batching is the same
  poisoning-containment mechanism carried over from the first backfill
  round (Part 1 §5 above), not a Stage-D-specific addition.
- **Caveat, honest**: `purge_machine_votes --run-id` cleanly reverts the
  vote ROWS (and, in the same invocation, re-resolves affected cards'
  consensus status — `purge_run` calls `resolve_and_persist_printing`/
  `resolve_and_persist_artist`/`resolve_and_persist_tag_votes` right after
  the `.delete()`), but this is two sequential calls, not one atomic
  transaction — a consensus resolution computed from a bad vote can
  already have been live (served, reindexed to ES via
  `reindex_card_safely`) for the entire interval between the bad write and
  someone noticing and running the purge; deleting the row afterward does
  not erase that it was live. Separately, `purge_run`'s own query touches
  only `CardPrintingTag`/`CardArtistVote`/`CardTagVote` — it never touches
  `CardScanLog`, so Stage D's own skip markers for that `run_id`
  (`no-evidence`, `ambiguous`, `to-review`, etc.) survive a purge intact.
  Since `_eligible_cards_queryset`/`_slow_path_eligible_cards_queryset`
  both exclude any card already carrying a non-rescannable `CardScanLog`
  row for the relevant `anonymous_id`, a purged card does not
  automatically become re-eligible for a redo under the same
  `anonymous_id` — fully unwinding a written run so it can be re-run
  cleanly needs more than the batch-delete alone. Not transaction-perfect
  downstream; named here rather than assumed.
- **Testing posture**: the 20k-card test run uses dry-run only — no
  writes, no interaction with the pre-existing 165k-run's own machine
  votes, no backup needed, since nothing is persisted. Production cutover
  is the only phase that uses `--write --run-id <fresh>`.

**Stage E resume contract (owner directive, 2026-07-19 — full spec on
task #147, acceptance test folded into task #156's soak gate)**:
resumability is a TESTED requirement, not an assumed property — this
is what Part 4's original kill lacked (its "zero polluted rows"
conclusion came from architecture reading, not a ledger, exactly the
gap this closes). Four binding pieces: (1) kill-and-restart at ANY
point with zero manual cleanup, proven via a blocking `kill -9`
mid-batch acceptance test during the soak; (2) resume filter = "cards
lacking an `ImageEvidence` row for this extractor-version set" (+
`run_id` scoping) — idempotent by construction; (3) evidence + votes +
residue for a batch commit in ONE transaction, or (if impractical)
evidence-first with idempotent calculator re-derivation on resume,
whichever is chosen stated explicitly when built; (4) a durable run
ledger (run_id, started_at, last_batch_at, batches_flushed,
cards_processed, per-destination fetch counts, state, heartbeat) —
likely extends Part 1's existing `PilotRunLedger` rather than a new
model. Applies to the shared runner, so Stage C golden runs and the
fidelity replay inherit it for free.

---

## Part 5 — Residual classification (existing tags only)

Only for cards where ALL identification tiers **genuinely ran** and
returned negative. **Hard guard**: exclude 404s, sub-floor resolution,
OCR-illegible, every skip category — absence of evidence is not evidence
of absence; only evidence-gathered-and-negative qualifies.

1. Frame-mismatch cases: handled by Part 3's shared module — **do not
   re-implement** here.
2. Artist matched a candidate artist but art matched nothing → altered-
   frame positive vote, confidence 0.6 (know the hand, not the artwork).
3. Collector + artist + art all ran, all negative → custom-art positive
   vote, confidence 0.6.
4. These are queue priors, not conclusions: verify they surface in the
   attribute chips' confidence fill correctly; zero-resolution assertion.

**HOLD #C — report expected volumes per class** before writing votes (cite
Part 3's frame-mismatch census number for its share of this pool).

---

## Part 6 — Formal note (merged — docs/theory.md)

`docs/theory.md`: the pipeline as candidate-constrained unique decoding
over a closed codebook.

1. Model: name n → finite candidate set C(n); OCR as a noisy string
   channel, phash as a noisy 64-bit channel, artist as a categorical
   channel; the validation rail as the decoding rule (accept iff exactly
   one codeword within the evidence ball).
2. False-accept bound, **calibrated from real data**: the autopsy buckets,
   the 300+300 confusion numbers (see `docs/features/printing-tags.md`'s
   "Validation against real production data" section), the full run's
   final rates.
3. Comparison: Fellegi-Sunter record linkage (the classical frame),
   tmikonen's population z-score rule (see "Prior-art read" in
   `docs/features/printing-tags.md`), our best-plus-margin rule — all as
   likelihood-ratio-test approximations; state where ours is tighter/
   looser and why the closed-world constraint is the load-bearing
   difference.
4. The two-threshold split (d=0 entailment / d<=2 prior) and the human-
   backed gate as explicit soundness mechanisms.
5. Honest novelty statement: standard components, novel composition; name
   the transferable pattern (user-submitted media vs. canonical registry,
   multi-channel weak evidence, human-gated resolution) and 2-3 domains
   beyond MTG. Written for an external reader — doubles as the federation
   pitch's technical annex.
6. **Sybil/bad-actor unification** (added 2026-07-16, future-work
   addendum — nothing built until there's an observed attack or real
   resolution volume; detectors ship as admin reports first, never
   automatic enforcement. **Readiness re-checked 2026-07-18: still not
   ready** — 155k+ vote rows now exist but almost all are this
   pipeline's own machine throughput, not human-population volume;
   real human voters number 4 distinct IDs. See
   `docs/reports/2026-07-18-dawid-skene-readiness-recheck.md`. The
   cluster-consistency detector below is the one exception not gated
   by this): the identification machinery doubles as the
   integrity layer, because it already treats every vote as noisy
   evidence rather than ground truth.
   - Machine evidence as an independent witness: a planned, report-only
     detector computing per-`anonymous_id` disagreement rate against
     validated machine evidence, plus a human-consensus-vs-machine
     contradiction list — surfaces a misbehaving or miscalibrated
     source without touching the resolution path itself.
   - Cluster consistency as a free contradiction detector: `d=0` cluster
     members that resolve differently are, by the clustering
     definition itself (same uploaded image), already a contradiction —
     no new machinery needed, just a report over
     `local_clustering`'s existing output.
   - Cohort revocation generalizes beyond `run_id`: the same purge
     pattern (`purge_machine_votes`, the post-purge invariant) applies
     to a suspect _human_ cohort scoped by `created_at` window instead
     of `run_id` — same mechanism, same invariant, different scoping
     dimension.
   - Trust tiers, if ever needed, enter as one more vote-tuple
     dimension (`is_established`) alongside source/confidence — not a
     parallel system.
   - This section gains a subsection relating the voter-as-noisy-channel
     model to Dawid-Skene reliability estimation: one framework
     covering OCR noise, honest human error, and deliberate
     manipulation together, and the basis for federation's own
     per-peer reliability measurement against shared `content_hash`es
     (see `docs/federation-v1.md`).

---

## Future work: contributor nodes (design note, 2026-07-19 — not built)

The per-card callable extraction unit (`image_evidence.py`, task
#145), manifest-mode segmentation (task #99), and content-hash-keyed
evidence (`ImageEvidence`) compose into a self-hosted contributor
node: users fetch and extract their own decks locally (their own IP,
no shared quota) and contribute evidence-only back — never image
bytes, in either direction. Full design note lives in
`docs/federation-v1.md`'s "Future work: contributor nodes" section
(depends on task #161 landing first, plus a real subscriber-side
federation implementation and its own node-trust design pass — none
of that exists yet). One-line pitch: "the architecture already
permits your users to be the compute."

---

## Status

- Part 1: **merged** (PR #28) - `run_id`, `PilotRunLedger`, staleness
  guard, `purge_machine_votes`, migration 0061 applied to production.
  HOLD #A cleared.
- PR #27 (hash-at-ingest + two-threshold clustering) also merged, after
  fixing a migration-number collision (both PRs independently picked
  `0061`; PR #27's was renumbered to `0062` and its dependency
  retargeted at PR #28's `0061`).
- Deploying PR #27's merge crashed the live pilot job (2026-07-16
  15:39 UTC) - see [[../troubleshooting.md]]'s "Entrypoint + migrate
  composition traps" entry for what happened, and
  [[printing-tags.md]]'s "Iteration safety" section for the resulting
  cohort convention (`run_id IS NULL` = pre-crash, not "pre-natural-
  completion"). Verified no data loss before restarting: 0 violations
  from `verify_no_machine_only_resolutions` run against the whole
  resolved-card pool.
- Parts 2 and 3 proceed now that #27 is merged. Part 4 after HOLD #B.
  Part 5 after HOLD #C.
- Part 6: **merged** — `docs/theory.md`, reviewed and approved by the
  owner 2026-07-17 (3 edits: §2b's false-accept/abstention-verification
  reframe + arithmetic fix, §3's XOR-framing correction). Calibrated
  against the full-catalog run's real numbers (43,426 votes, 26.2%
  invocation hit rate, 0/43,426 gate). Sequencing after backfill
  completes: Part 3's volume check against real `content_phash` + the
  6,379 scan-logged frame-mismatches, then Part 4 HOLD #B, then Part 5
  HOLD #C.
- Part 2's backfill **completed** 2026-07-18 (~19.5h real wall-clock,
  paced at ~3/s after the domain-mismatch fix - see
  [[../troubleshooting.md]]): 218,164/218,179 cards hashed (15
  fetch/hash failures, unset, will retry on next invocation).
- **Part 3's volume check, run against real data for the first time**
  (item 1's own gate, checked live 2026-07-18): (a) d=0 sibling with a
  known artist — **CORRECTED, 2026-07-18**: originally reported as 0
  here, but that number only queried the vote-derived fields
  (`inferred_canonical_card`/`inferred_canonical_artist`, still 3/0
  catalog-wide). The spec's own wording ("resolved printing's Scryfall
  artist OR resolved artist consensus") also includes confirmed
  indexing matches (`canonical_card`/`canonical_artist` — 10,926/7,333
  cards catalog-wide, entirely independent of the vote system). Once
  `run_d0_sibling_artist_propagation` (built this session, see below)
  was run for real against the full precedence chain
  `Card.serialise()` uses, the correct number is **987** cards that
  would receive a propagated artist vote today, not 0. (b) frame-
  mismatch scan-log census — **6,379 distinct cards** (6,753 rows),
  broken down by engine: phash 980 (free to recover — see below),
  OCR 5,178 (costs a refetch each), fallback 595 (also costs a
  refetch each — see the correction below). Combined volume clears
  the ~2k threshold via (b) alone, ~3x over. **Part 3 is
  volume-justified to build.**
- **Part 3 build — done, HOLD #P3** (2026-07-18): shared evidence-
  recovery module `cardpicker/local_residual_classify.py` +
  management command `local_residual_classify` (`--write` required to
  actually cast votes; defaults to dry-run — a deliberate deviation
  from `purge_machine_votes`'s opt-out convention, since HOLD #P3
  gates the write pass specifically). One code path, built for reuse
  by Part 5 later (`recover_frame_mismatch_printing_via_phash`/
  `_via_ocr_refetch`/`_via_fallback_refetch` are the reusable
  single-card primitives).
  - **P-recovery mechanism** (the design question): the matched-but-
    withheld printing P is computed in-memory during the original
    pilot run but never persisted — the durable `CardScanLog` row
    only records which _engine_ flagged a frame-mismatch skip, not
    which printing it matched. Recovery is recomputed, priced very
    differently by engine: **phash is free** (`Card.content_phash`,
    backfilled catalog-wide by Part 2, is confirmed to be the exact
    same hash the live phash engine would compute (see
    `local_phash.compute_content_phash_for_card`'s own docstring) — so
    recovery is a pure DB+arithmetic comparison against cached
    `CanonicalCard.image_hash`, zero fetch); **OCR and fallback both
    cost one real CDN fetch + a fresh engine pass per card** (neither
    engine's matched evidence — collector text, or the fallback
    engine's border/artist/symbol combination — is persisted anywhere
    else). **Correction** (caught on a second read of
    `local_fallback.py` before this module first shipped):
    `run_fallback_for_card` is in fact a standalone, single-card-
    callable function (exported in that module's own `__all__`) — an
    initial claim that fallback recovery had "no reusable function,
    out of scope" was wrong and has been fixed in the same PR that
    introduced it, before merge.
  - **Expected vote counts** (dry-run against live data, 2026-07-18):
    frame-mismatch dual yield — phash path (free, ran against the full
    980-card population): 750 recovered → 750 artist votes + 750
    altered-frame tag votes would cast. OCR/fallback paths: validated
    on a 30-fetch OCR sample (30/30 recovered — expected near-100%,
    this is _recovering_ an already-successful match, not matching
    cold), then run against the full OCR+fallback population
    (~5,773 cards after phash-priority dedup) in the background —
    **completed 2026-07-18, see the write-pass entry below for the real
    numbers** (4,804/4,804 OCR recovered, 590/595 fallback recovered).
    d=0 sibling propagation: 987 votes would cast (see the corrected number
    above), safely re-runnable, idempotent (excludes cards with an
    existing vote from its own `anonymous_id`).
  - **Rails**: `verify_no_single_machine_vote_resolutions` (zero-
    resolution-style gate, mirrors `purge_machine_votes`'s identical
    check — a single machine vote, weight 0.5, can never alone resolve
    an artist per `resolve_weighted_consensus`'s human-backed gate; see
    `test_artist_votes.py::TestResolveArtist::test_ai_only_insufficient`
    for the existing template this shares). `PilotRunLedger` row per
    invocation (RUNNING → COMPLETED/FAILED).
    Purgeable via the existing `purge_machine_votes --run-id` (both
    `CardArtistVote`/`CardTagVote` already carry `run_id` from Part
    1 — no new purge code needed). 17 tests in
    `test_local_residual_classify.py`, all passing (host venv only —
    the same testcontainers-vs-nested-Docker limitation documented in
    [[../troubleshooting.md]] applies).
  - **Queue-surfacing spot-check** (real finding, not inferred): a
    newly-cast machine artist vote correctly stays `UNRESOLVED` (0.5
    weight can't cross the 2.0 threshold alone) and correctly surfaces
    via `question_feed.py`'s Tier 4 (fresh). But `_artist_item()`
    (question_feed.py:79) has **no artist equivalent of printing's
    Tier-1 "confirm suggestion" UI** — it only exposes
    `confidentlyKnownArtistName` (populated only for a non-vote-
    derived, confirmed artist). A voter answering a fresh Tier-4
    artist question sees zero hint of the machine's guess, even
    though the vote is correctly weighted and participates in
    consensus. This is a **pre-existing question_feed gap**, not
    introduced by Part 3 (identical for every existing artist machine vote,
    not just these) — flagged here for whoever next touches
    question_feed's artist tier, not fixed as part of this work.
  - **HOLD #P3 cleared, write pass complete** (2026-07-18,
    `run_id=20260718T145157-a12b1387`): 13,275 real votes now live
    (7,131 `CardArtistVote` + 6,144 `CardTagVote`) — phash 750 recovered
    → 1,500 combined votes, d=0 siblings 987 artist votes, OCR
    4,804/4,804 recovered, fallback 590/595 recovered, OCR+fallback
    combined → 10,788 votes. All hard bounds passed (phash exactly 750,
    siblings exactly 987, OCR+fallback within the ≤11,546-vote ceiling).
    Zero-resolution assertion re-run at full population (not just the
    command's own 14-card sample gate): 0/7,124 violations — no card
    resolved on machine-only votes anywhere in the run. Full detail:
    [`docs/reports/2026-07-18-part3-write-pass-complete.md`](../reports/2026-07-18-part3-write-pass-complete.md).
  - Item 1's 15 permanent `content_phash` backfill failures: scattered
    across 6 distinct community Drive sources (CompC ×1,
    Hathwellcrisping ×4, LePoulpe_Dec_2023 ×2, RustyShackleford ×6,
    Trix_Are_For_Scoot ×1, Trix_Are_For_Scoot_2 ×1) — **not**
    concentrated in the owner's own WilfordGrimley source, genuine
    scattered dead/flaky Drive links rather than an intentional
    exclusion. No distinct per-card failure-reason field exists to
    report beyond `content_phash IS NULL` itself (the backfill command
    only tracks an aggregate `failed` count). Noted here as the
    ready-made live test set for PR #35's dead-link blocking-confirm
    feature and the "degradation badge" work: card ids 35226, 6074,
    1631, 6342, 4614, 36867, 36927, 57997, 62298, 74102, 58652, 64896,
    57583, 114225, 117403.
