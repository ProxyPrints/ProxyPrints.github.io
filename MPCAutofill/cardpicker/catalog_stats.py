"""
Proposal F catalog stats aggregate - backend, pass 1 (docs/proposals/proposal-f-public-stats-page.md;
docs/features/catalog-stats.md; issue #233's HOLD-lifted ruling, 2026-07-29). Follows
`cardpicker.artist_external_links`'s compute/warm/cache-only-read structure exactly - see that
module's own docstring for the shared architecture this mirrors (including the full "why
`caches['shared']`, never `default`" reasoning, restated below only where something differs).

THIS IS NOT A REVIVAL OF THE OFF-REPO `vote_stats.py` SNAPSHOT issue #233's ruling comment
describes. That snapshot read/wrote Django's `default` cache (issue #538 - a cron-warmed
`default` blob is invisible to the web server process, since a warm run is a separate `manage.py`
process) and used different field names/URL (`machineVotes`/`humanVotes` at `1/voteStats/`) than
this module ships. Nothing here is a port of that snapshot - every aggregation below is written
fresh against this repo's real, measured field shapes (see the five panel docstrings for the
measured numbers each was checked against, 2026-07-29).

FIVE PANELS OF PROPOSAL F'S SEVEN, THIS PASS. Proposal F specs 7 charts; this backend pass ships
the aggregates behind charts 2, 4, 6, 7, plus the call-to-action panel (participation - not
numbered in the original 7-chart table, it is the "N cards resolved, click here to help" strip).
Charts 1 (catalog resolution progress) and 5 (hash coverage) are DELIBERATELY DEFERRED, not
merely unbuilt: both would render as close to a single, uninformative bar at today's measured
values (resolved printings: 3 of ~230,770 cards; content_phash coverage: ~218k of ~230,770, i.e.
near-100%) - shipping either now would be misleading in the OPPOSITE direction from the
participation panel's own "don't understate progress" concern below. See
docs/proposals/proposal-f-public-stats-page.md's "HOLD lifted" section for the record of this
decision - a future pass revisits both once the underlying numbers move.

CACHE: `caches["shared"]` (`DatabaseCache`, PR #543/#538) - NEVER `caches["default"]`. Same
cross-process gap `cardpicker.artist_external_links`'s own module docstring documents in full:
`warm_catalog_stats` runs as a separate `manage.py` process from the running web server, so a
`default`-cached (per-process `LocMemCache`) blob would be written to memory the web server never
reads - the endpoint would return its zeroed skeleton forever while the warm command reported
success. `default` stays `LocMemCache` on purpose (django-ratelimit + `cardpicker.review_clusters`
depend on that - see the linked docstring), so this module reads/writes the named `"shared"`
alias exclusively, exactly like `cardpicker.artist_external_links` does.

SCHEDULE: hourly, via django-q2 (see `management/commands/warm_catalog_stats.py` and migration
`0094_...`'s own docstrings for the cadence justification - these aggregates move slowly, so
hourly is generous headroom, not a tuned-to-the-edge number). Unlike the MTGAC integration this
module's sibling PR adds, there is no third-party rate limit here and no opt-in gate to respect -
`warm_catalog_stats` reads only this project's own database, so it always runs, on every instance,
unconditionally.

CACHE-ONLY READ, NEVER COMPUTES ON REQUEST - Proposal F's own explicit constraint ("zero live
aggregate queries from public traffic"). `get_cached_catalog_stats()` (this module) and
`views.get_catalog_stats` (the `1/catalogStats/` endpoint) never call any `compute_*` function
below - only `warm_catalog_stats_cache()` (invoked from the `warm_catalog_stats` management
command) does. A cache miss - cold cache (never warmed yet), or `"shared"` not configured at all
(pre-#538/#543 environments) - returns `zeroed_catalog_stats()`, a fully-shaped, all-zero blob, so
the page always has something to render and the endpoint never 500s because an optional piece of
infrastructure isn't wired up yet. See `_shared_cache_for_read`/`_shared_cache_for_write` below,
identical split to `cardpicker.artist_external_links`'s own (read path swallows a missing
`"shared"` alias as an ordinary miss; write path raises loudly, since a warm run that silently
writes nowhere while reporting success is exactly the bug issue #538 exists to prevent).

HUMAN_SOURCES - A STATS-PAGE-SPECIFIC SPLIT, DELIBERATELY NOT `vote_consensus._MACHINE_DERIVED_
SOURCES`. Issue #233's owner ruling (2026-07-29): "the snapshot groups USER/ADMIN/FEDERATED as
human and DEDUCTION/OCR/IMPLICIT as machine, deliberately differing from vote_consensus.
_MACHINE_DERIVED_SOURCES (which counts FEDERATED as machine-derived) ... That distinction is
sound and worth preserving: the consensus set answers 'can this vote resolve a card unattended',
while a public stats page answers 'who is doing the tagging work'." Every "human vote"/"human
voter" count in this module (`compute_contributions_over_time`, `compute_participation`) filters
on `HUMAN_SOURCES` below, never on `vote_consensus.is_human_backed_source`. `VoteSource.IMPLICIT`
is deliberately excluded even though it DOES write `vote_surface` (see
`compute_contributions_over_time`'s own docstring for where this matters concretely) - it is a
passive, tiny-weight ("never human-backed", per `VoteSource.IMPLICIT`'s own docstring) by-product
of a card selection, not tagging work a person chose to do.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Optional

from django.core.cache import InvalidCacheBackendError, caches
from django.db.models import Count
from django.db.models.functions import TruncWeek
from django.utils import timezone

from cardpicker.models import (
    Card,
    CardArtistVote,
    CardPrintingTag,
    CardScanLog,
    CardTagVote,
    PilotRunLedger,
    VoteSource,
    summarise_contributions,
)
from cardpicker.question_feed import get_remaining_estimate

# The named cache alias this feature reads/writes - deliberately NOT `default`. See module
# docstring's "CACHE" section.
SHARED_CACHE_ALIAS = "shared"

# Versioned so a future shape change can be rolled out without a stale-shaped blob confusing a
# freshly-deployed reader - same idiom as `views.py`'s "funnel-counts-v1" and
# `cardpicker.artist_external_links.CACHE_KEY`.
CACHE_KEY = "catalog-stats-v1"

# No TTL - refreshed by the hourly warm run, not by request-triggered recomputation (this
# feature is deliberately cache-ONLY on the read path, see module docstring). An expiring TTL
# here would mean a missed warm run silently blanks the whole page back to zeroes instead of
# quietly serving a slightly-stale-but-real blob - worse than staleness. Freshness is the warm
# command's job, not the cache's.
CACHE_TIMEOUT = None

# Stats-page-specific human/machine split - see module docstring's "HUMAN_SOURCES" section for
# the owner ruling this encodes and why it deliberately differs from
# `vote_consensus._MACHINE_DERIVED_SOURCES`. DO NOT replace this with
# `vote_consensus.is_human_backed_source` without re-reading that ruling first.
HUMAN_SOURCES: list[str] = [VoteSource.USER, VoteSource.ADMIN, VoteSource.FEDERATED]

# How far back `compute_contributions_over_time` looks, in weeks. This is a small, cheap window
# (12 weeks = one quarter) - the panel is "recent confirmations by surface", not a full history;
# nothing about the schedule or cache design depends on this number.
CONTRIBUTIONS_OVER_TIME_LOOKBACK_WEEKS = 12

# How many `PilotRunLedger` rows `compute_run_history` returns, most-recent-first. Proposal F's own
# mock shows "last 10" - this is generous headroom above that for a chart that might want to show
# a slightly longer trend, still small and cheap against a table indexed by `started_at`.
RUN_HISTORY_RECENT_LIMIT = 50

# `Any`, not a `type[AbstractWeightedVote]` union - iterating a tuple of concrete Django model
# classes and calling `.objects` on the loop variable is a known mypy/django-stubs limitation
# (mypy widens the loop variable to the common abstract base, which - being `abstract = True` -
# has no manager attached in the stubs). Same workaround convention
# `cardpicker.models.purge_stale_machine_votes` already uses for its own `model_class: Any`
# parameter, for the same reason.
_VOTE_MODELS: tuple[Any, ...] = (CardPrintingTag, CardArtistVote, CardTagVote)


def compute_contributions_over_time(
    weeks: int = CONTRIBUTIONS_OVER_TIME_LOOKBACK_WEEKS, now: Optional[Any] = None
) -> dict[str, Any]:
    """
    Proposal F chart 2 - human confirmations bucketed by week, split by `vote_surface`, across all
    three vote tables (`CardPrintingTag`/`CardArtistVote`/`CardTagVote`).

    HUMAN-ONLY BY TWO INDEPENDENT FILTERS, NOT ONE. `vote_surface` (`AbstractWeightedVote`'s own
    field docstring) is written by the three human vote-submission endpoints
    (`post_submit_printing_tag`/`post_submit_artist_vote`/`post_submit_tag_vote`) and by
    `post_confirm_review_cluster`'s moderator no-match confirmations - all `source=VoteSource.
    USER`. It is NEVER written by a machine calculator (`local_identify_printing_tags.py`/
    `local_fallback.py`'s engines never pass a `vote_surface` kwarg). **It IS also written by
    `post_cast_implicit_vote`** (`views.IMPLICIT_VOTE_SURFACE = "display-editor-filter"`,
    `source=VoteSource.IMPLICIT`) - a passive, tiny-weight by-product of a card selection under
    active filter chips, "never human-backed" per `VoteSource.IMPLICIT`'s own docstring, and
    machine-derived under THIS module's own `HUMAN_SOURCES` split (see module docstring). This
    function therefore filters on BOTH `vote_surface__isnull=False` (excludes the DEDUCTION/OCR
    machine calculators, which never set it at all) AND `source__in=HUMAN_SOURCES` (excludes
    VoteSource.IMPLICIT specifically, which DOES set it) - relying on the first filter alone would
    let implicit votes leak into a chart titled "human confirmations". Blank-string `vote_surface`
    values (distinct from NULL - the field is `null=True, blank=True`) are excluded the same way
    NULL is; there is no "unlabeled" bucket in this pass, since every value observed at this cache
    design's inception was already non-blank when set at all.

    Returns `{"bucketDays": 7, "series": [{"weekStart": "YYYY-MM-DD", "bySurface": {surface:
    count}}, ...]}`, ordered oldest week first, only including weeks with at least one qualifying
    vote in the lookback window (`weeks`, default 12 - see module docstring). `weekStart` is the
    Monday `TruncWeek` buckets each `created_at` into, formatted as an ISO date string.
    """
    now = now or timezone.now()
    since = now - timedelta(weeks=weeks)

    buckets: dict[Any, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for model in _VOTE_MODELS:
        rows = (
            model.objects.filter(source__in=HUMAN_SOURCES, created_at__gte=since)
            .exclude(vote_surface__isnull=True)
            .exclude(vote_surface="")
            .annotate(week_start=TruncWeek("created_at"))
            .values("week_start", "vote_surface")
            .annotate(count=Count("id"))
        )
        for row in rows:
            week_start = row["week_start"]
            week_start_date = week_start.date() if hasattr(week_start, "date") else week_start
            buckets[week_start_date][row["vote_surface"]] += row["count"]

    series = [
        {"weekStart": week_start.isoformat(), "bySurface": dict(sorted(by_surface.items()))}
        for week_start, by_surface in sorted(buckets.items())
    ]
    return {"bucketDays": 7, "series": series}


def compute_skip_breakdown() -> dict[str, Any]:
    """
    Proposal F chart 4 - `CardScanLog.skip_reason` grouped by reason, and (optionally, for a
    per-engine view) by reason + `anonymous_id` (the field this project's calculators use as their
    engine identity, e.g. `local-ocr-v1`/`local-phash-v1`/`local-fallback-v1` - see
    `CardScanLog.anonymous_id`'s own field comment: "same field, same width, same semantics as
    `AbstractWeightedVote.anonymous_id`"). ~11 distinct `skip_reason` values exist in production
    (measured 2026-07-29) - this aggregation makes no assumption about that count, it is purely a
    `GROUP BY`.

    Returns `{"byReason": [{"reason": str, "count": int}, ...], "byReasonAndEngine": [{"reason":
    str, "engine": str, "count": int}, ...]}`, both sorted by count descending (ties broken
    alphabetically by reason) so the largest bars come first without the page needing to re-sort.
    """
    by_reason = [
        {"reason": row["skip_reason"], "count": row["count"]}
        for row in (
            CardScanLog.objects.values("skip_reason").annotate(count=Count("id")).order_by("-count", "skip_reason")
        )
    ]
    by_reason_and_engine = [
        {"reason": row["skip_reason"], "engine": row["anonymous_id"], "count": row["count"]}
        for row in (
            CardScanLog.objects.values("skip_reason", "anonymous_id")
            .annotate(count=Count("id"))
            .order_by("-count", "skip_reason", "anonymous_id")
        )
    ]
    return {"byReason": by_reason, "byReasonAndEngine": by_reason_and_engine}


def compute_run_history(limit: int = RUN_HISTORY_RECENT_LIMIT) -> dict[str, Any]:
    """
    Proposal F chart 6 - the `RUN_HISTORY_RECENT_LIMIT` most recent `PilotRunLedger` rows
    (most-recent-first by `started_at`): `run_id`, `command`, `status`, `startedAt`, `finishedAt`,
    `durationSeconds` (`None` while `finished_at` is unset - a still-`RUNNING` row, or a crashed
    invocation `pilot_run_lifecycle.mark_ledger_failed` never reached), and `votesWritten`.

    **CAUTION, read before trusting any `PilotRunLedger.counters` key on a future panel**: several
    `stage_d_*_already_voted` counters (`stage_d_join_key_already_voted`/`stage_d_fallback_
    already_voted`/`stage_d_illustration_already_voted`, all inside `counters`, NOT top-level
    fields) are structurally 0 on every row written since 2026-07-28 - `cardpicker.vote_write`'s
    purge-then-write primitive purges by calculator family (which includes the caller's own
    current `anonymous_id`) BEFORE the already-voted split ever runs, so the split counts against
    a table it just emptied. See `cardpicker.vote_write`'s own module docstring, point 1, for the
    full mechanism. **This function does NOT surface any `counters` key at all**, specifically to
    avoid shipping one of these - `run_history` only ever reads the four TOP-LEVEL `PilotRunLedger`
    columns named above.

    **`votes_written` (the top-level column this function DOES surface) is NOT affected by that
    same bug, verified by tracing every call site that sets it**
    (`grep -rn "votes_written\\s*=" MPCAutofill/cardpicker/management/commands/*.py
    MPCAutofill/cardpicker/*.py`, 2026-07-29): every command that sets `ledger.votes_written` does
    so from a `result.votes_written`/`len(new_votes)` value computed by the SPLIT step, which
    `cardpicker.vote_write`'s own docstring establishes runs BEFORE the purge (point 1: "a caller
    that runs an already-voted split ... MUST run it BEFORE calling this function") - the count is
    correct at the moment it's taken, only the (separately-named, `counters`-only) already-voted
    counter is corrupted by what happens next. `votes_written` is therefore safe to surface as-is.

    **`votes_written` IS `None` for `command="stage_e_streaming_dispatch"` rows specifically** -
    a SEPARATE, unrelated observability gap (`stage_e_dispatch.py`'s per-micro-batch ledger update
    writes only `counters` keys - `stage_d_join_key_votes`/`stage_d_fallback_votes`/`stage_d_
    illustration_votes` - never the top-level `votes_written` column at all). This function passes
    the raw (possibly-`None`) value through rather than backfilling it from `counters`, since
    reconstructing a top-level field from a JSON blob that was never meant to back-fill it risks
    silently disagreeing with whatever a future fix to `stage_e_dispatch.py` itself writes there.
    """
    rows = PilotRunLedger.objects.order_by("-started_at")[:limit]
    recent = []
    for row in rows:
        duration_seconds: Optional[float] = None
        if row.finished_at is not None:
            duration_seconds = (row.finished_at - row.started_at).total_seconds()
        recent.append(
            {
                "runId": row.run_id,
                "command": row.command,
                "status": row.status,
                "startedAt": row.started_at.isoformat(),
                "finishedAt": row.finished_at.isoformat() if row.finished_at is not None else None,
                "durationSeconds": duration_seconds,
                "votesWritten": row.votes_written,
            }
        )
    return {"recent": recent}


def compute_catalog_composition() -> dict[str, Any]:
    """
    Proposal F chart 7 - the cheapest of the five panels, by design: reuses
    `cardpicker.models.summarise_contributions()` VERBATIM (the same raw-SQL aggregation
    `views.get_contributions`/`GET 2/contributions/` already computes live, on every request).
    This panel's only job is to move that existing live query onto the same cached/scheduled
    footing as the other four - no new aggregation logic of its own.

    Returns `{"sources": [SourceContribution.model_dump(mode="json"), ...], "cardCountByType":
    {card_type: count}, "totalDatabaseSize": int}` - `mode="json"` on the per-source dump so the
    `SourceType` enum field serialises to its plain string value in the cached blob, rather than an
    enum instance whose class identity could drift across a deploy that reorders/renames the enum.
    """
    sources, card_count_by_type, total_database_size = summarise_contributions()
    return {
        "sources": [source.model_dump(mode="json") for source in sources],
        "cardCountByType": dict(card_count_by_type),
        "totalDatabaseSize": total_database_size,
    }


def compute_participation() -> dict[str, Any]:
    """
    The call-to-action panel (not one of Proposal F's numbered 7 charts - the "N cards resolved,
    here's how to help" strip the proposal's mock shows above the fold).

    Emits `confirmable`/`contested`/`fresh`/`total` from `question_feed.get_remaining_estimate()`
    UNCHANGED (see that function's own docstring - `total` is "cards needing review in any
    category", not a synonym for `Card.objects.count()`, though the two happen to coincide today
    since nearly the whole catalog is still unresolved), plus total human votes (by table and
    summed), distinct human voters, and the md5-group figures - all as RAW COUNTS.

    **DELIBERATELY EMITS NO "percent complete" FIELD - do not add one.** Owner ruling (relayed via
    this proposal's directive): measured 2026-07-29, total human votes across all three vote
    tables is 237 (CardPrintingTag 125 + CardArtistVote 6 + CardTagVote 106) against `total`
    230,770 - roughly 0.1%. A single computed ratio at that value reads as "this project failed"
    rather than "this project needs you", the opposite of a call to action. This function emits
    BOTH the numerator-shaped numbers (`humanVotes`) and the denominator-shaped numbers
    (`confirmable`/`total`) so the page can choose its own framing (e.g. "103,687 cards are one
    quick confirmation away" reads very differently from "237 of 230,770 votes cast", even though
    both are honest readings of the same underlying counts) - never pre-computing that choice away
    into one percentage here.

    `humanVotes`/`distinctHumanVoters` filter on `HUMAN_SOURCES` (module docstring's own section -
    USER/ADMIN/FEDERATED, NOT `vote_consensus`'s four-source machine-derived set), matching the
    237-vote/~11-voter figures measured against production on 2026-07-29.
    """
    counts = get_remaining_estimate()

    human_vote_counts = {
        "printingTag": CardPrintingTag.objects.filter(source__in=HUMAN_SOURCES).count(),
        "artist": CardArtistVote.objects.filter(source__in=HUMAN_SOURCES).count(),
        "tag": CardTagVote.objects.filter(source__in=HUMAN_SOURCES).count(),
    }
    total_human_votes = sum(human_vote_counts.values())

    distinct_voters: set[str] = set()
    for model in _VOTE_MODELS:
        distinct_voters.update(model.objects.filter(source__in=HUMAN_SOURCES).values_list("anonymous_id", flat=True))

    md5_group_sizes = list(
        Card.objects.exclude(md5_checksum__isnull=True)
        .exclude(md5_checksum="")
        .values("md5_checksum")
        .annotate(group_size=Count("id"))
        .filter(group_size__gt=1)
        .values_list("group_size", flat=True)
    )

    return {
        "total": counts.total,
        "confirmable": counts.confirmable,
        "contested": counts.contested,
        "fresh": counts.fresh,
        "humanVotes": {**human_vote_counts, "total": total_human_votes},
        "distinctHumanVoters": len(distinct_voters),
        "md5Groups": {
            "groupsWithMultipleCards": len(md5_group_sizes),
            "cardsInMultiCardGroups": sum(md5_group_sizes),
            "largestGroupSize": max(md5_group_sizes, default=0),
        },
    }


def compute_catalog_stats() -> dict[str, Any]:
    """Compute all five panels in one call - the body of `warm_catalog_stats_cache`. Never called
    from the request-serving path (see module docstring's "CACHE-ONLY READ" section)."""
    return {
        "generatedAt": timezone.now().isoformat(),
        "contributionsOverTime": compute_contributions_over_time(),
        "skipBreakdown": compute_skip_breakdown(),
        "runHistory": compute_run_history(),
        "catalogComposition": compute_catalog_composition(),
        "participation": compute_participation(),
    }


def zeroed_catalog_stats() -> dict[str, Any]:
    """The shape returned for a cache miss - cold cache (never warmed), or the `"shared"` cache
    backend isn't configured at all yet. Fully-shaped, all-zero/empty, so a page reading this
    before the first warm run (or before issue #538/#543's infrastructure lands) renders its
    empty state instead of crashing on a missing key."""
    return {
        "generatedAt": None,
        "contributionsOverTime": {"bucketDays": 7, "series": []},
        "skipBreakdown": {"byReason": [], "byReasonAndEngine": []},
        "runHistory": {"recent": []},
        "catalogComposition": {"sources": [], "cardCountByType": {}, "totalDatabaseSize": 0},
        "participation": {
            "total": 0,
            "confirmable": 0,
            "contested": 0,
            "fresh": 0,
            "humanVotes": {"printingTag": 0, "artist": 0, "tag": 0, "total": 0},
            "distinctHumanVoters": 0,
            "md5Groups": {"groupsWithMultipleCards": 0, "cardsInMultiCardGroups": 0, "largestGroupSize": 0},
        },
    }


def _shared_cache_for_read() -> Optional[Any]:
    """Same split as `cardpicker.artist_external_links._shared_cache_for_read` - returns the
    named `"shared"` cache backend, or `None` if it isn't configured (`InvalidCacheBackendError`),
    treated EXACTLY like a cache miss by the caller, never an exception that could 500 the
    endpoint."""
    try:
        return caches[SHARED_CACHE_ALIAS]
    except InvalidCacheBackendError:
        return None


def _shared_cache_for_write() -> Any:
    """Same split as `cardpicker.artist_external_links._shared_cache_for_write` - returns the
    named `"shared"` cache backend for the WRITE path (the warm command), or raises `RuntimeError`
    with an actionable message if it isn't configured, deliberately NOT swallowed the way the read
    path swallows it (a warm run that appears to succeed while silently writing nowhere is exactly
    the bug issue #538 exists to prevent)."""
    try:
        return caches[SHARED_CACHE_ALIAS]
    except InvalidCacheBackendError as e:
        raise RuntimeError(
            f"The {SHARED_CACHE_ALIAS!r} cache backend is not configured in CACHES "
            "(MPCAutofill/settings.py) - issue #538/#543 tracks the infrastructure PR that adds "
            "it. warm_catalog_stats cannot write anywhere without it, so refusing to run rather "
            "than silently succeeding while writing nowhere."
        ) from e


def warm_catalog_stats_cache() -> dict[str, Any]:
    """
    Compute + write the cache blob in one call - the body of the `warm_catalog_stats` management
    command. Resolves the `"shared"` cache backend BEFORE computing anything (`_shared_cache_for_
    write` raises immediately if it isn't configured), so a misconfigured environment never pays
    for five aggregation passes it couldn't have written down anyway.

    IDEMPOTENT AND FAILURE-SAFE BY CONSTRUCTION, NOT BY EXTRA CODE: `compute_catalog_stats()` is
    a pure read (five `SELECT`-only aggregations, no writes) and only its RETURN VALUE is ever
    written to the cache, in the one `.set()` call at the end of this function. If any aggregation
    raises, this function raises too, and the previous cache entry - today's or an earlier run's
    good blob, or nothing at all on a first run - is left completely untouched, because nothing
    reaches the `.set()` call. Two back-to-back successful calls leave the cache in exactly the
    same state a single call would (each is a full recomputation from the live database, never a
    merge/diff against the previous blob).
    """
    shared_cache = _shared_cache_for_write()
    blob = compute_catalog_stats()
    shared_cache.set(CACHE_KEY, blob, timeout=CACHE_TIMEOUT)
    return blob


def get_cached_catalog_stats() -> dict[str, Any]:
    """
    Cache-only read - NEVER computes, regardless of hit or miss (see module docstring's
    "CACHE-ONLY READ" section - this is Proposal F's core public-traffic guarantee). Returns
    `zeroed_catalog_stats()` when the `"shared"` cache backend isn't configured yet, or the cache
    hasn't been warmed yet even though it IS configured - both look identical to the caller, by
    design, exactly like `cardpicker.artist_external_links.get_cached_artist_external_links`'s own
    three-way-identical-miss shape.
    """
    shared_cache = _shared_cache_for_read()
    if shared_cache is None:
        return zeroed_catalog_stats()
    blob = shared_cache.get(CACHE_KEY)
    if not blob:
        return zeroed_catalog_stats()
    return blob
