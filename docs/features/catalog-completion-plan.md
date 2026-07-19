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

Queued behind Stage B per the paced task sequence (#145–148). Stage D
carries a hard precondition: the pipeline-fidelity gate (task #151,
owner directive 2026-07-19) — calculators must call the existing
shipped identification code paths with `ImageEvidence`-supplied
inputs, not re-derive their logic; a stratified-sample parity replay
against run `20260716T193408-6613a1a6`'s recorded outputs must show
zero unexplained divergence; a full knowledge-inventory sweep (every
empirically-derived constant/threshold/override/skip-reason mapped to
its home in the new pipeline, or flagged missing) must be clean. Both
gate task #148 (the owner HOLD deliverable) and any full-catalog fire.

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
