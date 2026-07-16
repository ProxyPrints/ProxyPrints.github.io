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
  Part 5 after HOLD #C. Part 6 last, gated on the full run's own
  completion.
