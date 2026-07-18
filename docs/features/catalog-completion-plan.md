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

## Part 1 — Run-cohort safety (in progress, finish as planned)

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

## Part 3 — Shared evidence-recovery module (after PR #27 merges; expanded)

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

## Part 4 — LANDS (artist-decomposed identification)

Target pool: unresolved basic lands (Plains/Island/Swamp/Mountain/Forest/
Wastes + Snow-Covered) OR any name whose candidate count exceeded the
phash cap (`PHASH_MAX_CANDIDATES`).

1. Collector-line OCR as normal (confirm the cap never applied to OCR —
   text validation is free at any N; verify against `select_candidates`/
   `run_ocr_for_card`, don't assume).
2. Where OCR fails: artist OCR (already extracted in the fallback pass's
   stored JSON per-card audit data, deliberately unwritten as a vote since
   the pilot's start — confirm this via `local_fallback.py`'s
   `extract_artist_name`/`match_artist`, currently used only to _narrow_
   printing candidates during pass-2, never to vote) → `difflib` ratio
   ≥0.8 against the NAME'S OWN candidates' artists only (not the whole
   artist table).
3. Artist match → filter candidates to that artist's printings → phash
   within the filtered set (reuse the `CanonicalCard.image_hash` cache;
   filtered sets should sit under the cap — report the real distribution,
   don't assume it does). Unique winner with the standard margin →
   printing vote: confidence 0.85 (artist+art agree), 0.8 (art-within-
   artist, weaker signal). Ambiguous → skip, counted.

**HOLD #B — volume check before running the pool**: land-pool size,
artist-extraction rate on a 300-card sample, per-name candidate counts
pre/post artist filtering. Report before building further.

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

## Part 6 — Formal note (starts only after the full-catalog run's final report exists)

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
   automatic enforcement): the identification machinery doubles as the
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
    see the follow-up entry below for the completed numbers. d=0
    sibling propagation: 987 votes would cast (see the corrected number
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
    introduced by Part 3 (identical for every existing artist AI vote,
    not just these) — flagged here for whoever next touches
    question_feed's artist tier, not fixed as part of this work.
  - **HOLD #P3 stands**: no vote has been written to the live database
    by this pass. The write pass (`--write`) runs only after explicit
    go-ahead.
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
