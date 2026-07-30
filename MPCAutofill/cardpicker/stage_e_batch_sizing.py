"""
2026-07-29 - MICRO-BATCH SIZE AS A MEASURED RUNTIME PROPERTY, not a constant (owner directive:
"regarding batch size we have to follow the data. i want it to scale with available hardware up to
the fetch saturation limit while keeping the mem overhead low and fastest bulk timing").

This module answers exactly one question - "how many cards should the next micro-batch hold?" -
and it answers it from three measured terms, the smallest of which wins. It performs no I/O beyond
reading `/proc/meminfo` and `os`-level CPU counts, holds no state, and is safe to call on every
dispatch.

WHAT BATCH SIZE ACTUALLY BUYS, AND WHERE IT STOPS BUYING IT
-----------------------------------------------------------
One dispatch costs `F + (m + c) * N` seconds, where `N` is the batch size:

  * `F` - the batch-FIXED cost: Stage D's four eligibility queries plus Stage C's own per-batch
    lexicon/lookup builds and already-done manifest query. Paid once per dispatch however large
    the batch is, so its per-card share is `F / N` and shrinks as the batch grows. This is the
    ONLY term batch size improves.
  * `m` - Stage D's per-card marginal compute. Unaffected by batch size.
  * `c` - Stage C's per-card floor: one fetch overlapped with one extraction
    (`_stage_c_fetch_ahead_worker` is a SINGLE fetch thread feeding a SINGLE sequential compute
    loop), so `c ~= max(fetch, compute)`. Unaffected by batch size, and it is by far the largest
    term. A dispatch's throughput is therefore `1 / c` cards per second NO MATTER HOW BIG ITS BATCH
    IS - one in-flight fetch at a time is one in-flight fetch at a time - which is why a bigger
    batch cannot buy throughput past the point where `F / N` has already vanished into `c`. THAT is
    the fetch-saturation limit, expressed as a batch size.

    CORRECTED 2026-07-30. This paragraph used to say aggregate throughput across dispatches was
    "capped by `harvest_fetch_limiter.GOOGLE_IMAGE.max_concurrency = 6`". It is not: that ceiling
    is a per-PROCESS `threading.Semaphore` and concurrent dispatches are separate OS processes (see
    `HostProfile.aggregate_fetch_threads`). The saturation cap does not depend on that claim and is
    unchanged by its removal - it rests on the measured per-card `c` floor within ONE dispatch,
    which is a serial property of the single fetch-ahead thread and needs no cross-process
    guarantee. The claim was load-bearing for nothing but was still false, and a false statement
    next to a correct number is how the same number gets re-derived wrongly later.

Measured on the live catalog, 2026-07-29, against a tree with PR #579 applied (see VERIFICATION
below for why that qualifier is load-bearing) - median of 3 reps per point, fresh process per
point, cohort redrawn per rep across the whole pk space:

    N       batch-fixed+marginal    residual overhead     share of the
            cost per card           above the asymptote   `c` floor
    ------------------------------------------------------------------
     25       8.70 ms                 6.96 ms              1.24%
     50       5.26 ms                 3.52 ms              0.63%
    100       3.66 ms                 1.92 ms              0.34%
    250       2.39 ms                 0.65 ms              0.12%
    500       2.15 ms                 0.41 ms              0.07%
   1000       1.90 ms                 0.16 ms              0.03%
   2000       1.84 ms                 0.09 ms              0.02%

Least-squares over that table gives `F ~= 175 ms` and `m ~= 1.74 ms/card`. The `c` floor was
measured separately over 24 real cards fetched through the same `image_cdn_fetch.
fetch_card_image_bytes` the conveyor uses: fetch 561 ms median / 653 ms mean, extraction 538 ms
median / 666 ms mean, so `c ~= 561 ms/card` overlapped - three orders of magnitude larger than the
amortisation gain being chased above N=250.

SATURATION_BATCH_SIZE = 250 is read straight off that table by a stated criterion: the smallest
tested size whose residual per-card fixed-cost overhead is under 1 ms, which is an order of
magnitude below the run-to-run spread of the `c` floor itself (561 median vs 653 mean). N=100
misses it at 1.92 ms. Going on to N=500 buys a further 0.24 ms/card - 0.04% of `c` - while
doubling how long the batch runs unobserved. It is deliberately NOT a hardware-scaled number: it is
set by ONE dispatch's own serial fetch floor, and a bigger host does not make a remote image arrive
faster. A bigger host buys more concurrent DISPATCHES, not a bigger batch, which is precisely the
owner's "up to the fetch saturation limit" - and how many dispatches may run at once is
`STAGE_E_MAX_CONCURRENT_DISPATCHES`, an operator setting enforced by `stage_e_concurrency`'s
cross-process advisory locks, not something this module gets to raise.

WHY THE OTHER TWO TERMS SCALE DOWN AND NEVER UP
------------------------------------------------
Both remaining terms are GUARDS. On any host healthy enough to run the conveyor, the saturation
cap is the operative value and neither guard binds; they exist so the same rule behaves on a
maintainer's laptop, or on a box under real memory pressure, without being tuned to this one.

  * MEMORY. Measured marginal cost of a batch's own live set (the `to_fetch` list of `Card`
    instances plus the id list) is ~1.0-1.9 KB/card: fresh processes holding 5,000 and 10,000
    cards grew 4.94 MB and 18.66 MB respectively once arena reuse was exhausted. The image bytes
    themselves are NOT batch-size-proportional at all - `_STAGE_C_FETCH_AHEAD_DEPTH = 2` bounds
    the number of decoded images in flight regardless of N, which is the property that makes a
    large batch affordable in the first place. Against `operating_envelope.
    RSS_MB_PER_WORKER_CEILING = 768` and a measured warm working set of ~300 MB, the memory term
    is worth hundreds of thousands of cards and cannot bind at any size this rule would choose.
    It is kept anyway, and stated as a guard rather than dressed up as a tuning knob: on a host
    where the working set does not fit the per-process budget at all it collapses the batch to
    MIN_BATCH_SIZE, which is the correct behaviour and the only behaviour it will ever exhibit.
  * DURATION. This is the term with real teeth on slow hardware, and it is the one the envelope
    cares about. `dispatch_micro_batch` samples the operating envelope EXACTLY ONCE per dispatch,
    before the batch starts, and `stream_full_catalog` advances its resume high-water mark exactly
    once per COMPLETED batch. So the batch is simultaneously the envelope's sampling interval and
    the kill-loss bound, and both degrade linearly in `N * c`. TARGET_BATCH_SECONDS = 300 is not
    invented: it is `stream_full_catalog.DEFAULT_PROGRESS_EVERY_SECONDS`, that command's own
    ratified answer to "how stale may the operator's view of this run be" - a batch that outlives
    one progress interval makes that flag a lie. The floor on the other side is
    `os.getloadavg()[0]`, a 1-minute average: sampling the load bar faster than once a minute
    tells you nothing new, so there is no benefit in driving the batch below ~60 s either.
    The per-card cost this term divides by is the measured floor inflated by
    `HOST_LOAD_CEILING / usable_cores` - the worst contention a dispatch can LEGALLY be running
    under, since the envelope's flat 7.0 ceiling permits a dispatch to start at a run queue of 7
    whether the host has 16 cores or 2. On the 8-OCPU production host that ratio is 1.0 and this
    term is inert; on a 4-core laptop it is 2.33 and the term binds at 229. See `_duration_limit`
    for why the inflation is derived from the CEILING and never from a live `getloadavg` sample.

SIZING MUST NOT FIGHT THE HOST-LOAD BAR (`operating_envelope.HOST_LOAD_CEILING = 7.0`), and the
direction of that constraint is the counter-intuitive part, so it is written down rather than left
to be re-derived: the load bar is checked at DISPATCH TIME, once, so a SMALLER batch means MORE
dispatch attempts across the same catalog and therefore MORE opportunities to trip, not fewer.
Nothing here shrinks the batch in the hope of placating the envelope. What the duration term does
instead is refuse to let a single batch run so long that the bar stops being sampled at a useful
cadence. This rule is also deliberately not a function of the CURRENT load average: this box
routinely carries 5+ concurrent agent sessions at load 7.9-11.5, and a batch size fitted to
whichever instant it was computed in would be a different number every dispatch and would be
wrong on a quiet box and on a busy one alike.

TWO MODES, BECAUSE TWO CALLERS WANT OPPOSITE THINGS
----------------------------------------------------
  * `MODE_BULK` - the unattended, run-to-completion whole-catalogue pass
    (`stream_full_catalog`). Nothing waits on any individual batch, the run is measured in hours,
    and the only figure of merit is total wall clock. Gets the full autoscaled size.
  * `MODE_INCREMENTAL` - the event echo (`stage_e_dispatch.dispatch_for_card`, one triggering
    card, the rest of the batch filled from the backlog) and the cron backstop sweep
    (`stream_backstop_sweep`, whose per-invocation footprint is `--max-batches` x batch size, with
    `--max-batches` defaulting to 1000). Both want a SMALL, BOUNDED unit of work: an event echo
    that turned one card's `post_save` into a 250-card, 140-second django-q task would be a
    latency and worker-occupancy regression for no throughput gain, and a cron sweep whose
    footprint silently grew tenfold is a different job than the one that was scheduled.
    INCREMENTAL_BATCH_SIZE = 25 keeps both on exactly the size they run today - at 25 the fixed
    cost is already only 1.2% of a single card's own `c`, so there is nothing to reclaim - and the
    value is now a stated latency choice rather than the placeholder it used to be.

PRECEDENCE - AN EXPLICIT SETTING ALWAYS WINS, AND MUST NEVER COST A REDEPLOY
-----------------------------------------------------------------------------
`resolve_micro_batch_size` applies, in order: an explicit caller argument (a `--batch-size` flag)
-> an explicit `settings.STAGE_E_MICRO_BATCH_SIZE` -> this rule. `stream_full_catalog`'s docstring
makes "every tunable is a command-line flag" a binding design property because the operator's
method is launch, watch, kill, change a setting, relaunch; autoscaling must never take that away.
It does not: `--batch-size N` still wins outright, `--batch-size auto` names this rule explicitly,
and every decision this module makes is returned as a `BatchSizeDecision` carrying the term that
bound it and every input it was computed from, so the operator can read WHY off the run's own log
instead of inferring it. No new tunable is introduced that would need a flag of its own - an
operator who disagrees with the rule's answer passes the number they want, which is the mechanism
that already existed.
"""

import os
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from cardpicker.harvest_fetch_limiter import GOOGLE_IMAGE
from cardpicker.operating_envelope import HOST_LOAD_CEILING, RSS_MB_PER_WORKER_CEILING

MODE_BULK = "bulk"
MODE_INCREMENTAL = "incremental"

# THE FETCH-SATURATION CAP, in cards (module docstring's own measurement table and the stated
# "smallest tested size whose residual per-card overhead is under 1 ms" criterion). Not
# hardware-scaled, deliberately: the limiter that sets it does not get bigger when the host does.
SATURATION_BATCH_SIZE = 250

# The latency/footprint size for event echoes and the cron backstop sweep (module docstring's
# "TWO MODES" section). Identical to the pre-autoscale production value, so both of those callers
# are behaviourally unchanged by this module's introduction.
INCREMENTAL_BATCH_SIZE = 25

# The smallest batch the guards below may ever collapse to. Also the pre-autoscale production
# value: a host too constrained for the rule's own answer still gets the size that has actually
# been running in production, never something smaller and untested.
MIN_BATCH_SIZE = 25

# Measured 2026-07-29: fresh processes holding 5,000 / 10,000 `Card` instances plus their id list
# grew 4.94 MB / 18.66 MB once arena reuse was exhausted -> 1.01 / 1.91 KB per card. The high end,
# rounded up, so the guard errs toward a smaller batch. Excludes decoded image bytes ON PURPOSE:
# `_STAGE_C_FETCH_AHEAD_DEPTH` bounds those independently of N (module docstring).
MARGINAL_RSS_MB_PER_CARD = 0.002

# Measured 2026-07-29: a warm dispatch process (process-level candidate-name index, artist
# lexicon, printing-artist lookup, ORM machinery, all built) sat at 298 MB current RSS with a
# 313 MB lifetime high-water mark, flat from N=10 to N=2000. 320 rounds the high-water mark up.
# Subtracted from the per-process budget before the marginal term is divided in, so the guard
# reasons about the memory a batch may ADD, not the memory the process needs to exist.
BATCH_WORKING_SET_RSS_MB = 320.0

# Measured 2026-07-29 over 24 real cards: fetch 561 ms median / 653 ms mean, extraction 538 ms
# median / 666 ms mean, overlapped by the single fetch-ahead thread into `max(fetch, compute)`.
# The median is used rather than the mean because the mean is pulled by a small number of very
# large images, and the duration guard wants the typical batch, not the worst one.
FETCH_BOUND_CARD_SECONDS = 0.561

# `stream_full_catalog.DEFAULT_PROGRESS_EVERY_SECONDS` (module docstring's DURATION paragraph) -
# a batch that outlives one progress interval makes that flag's own "bounds how stale the log's
# own resume pk can be" promise untrue. Not duplicated by import: that constant lives in a
# management-command module, and this module is imported from `cardpicker.stage_e_dispatch` which
# `apps.py`'s `ready()` reaches at app-startup time (see `stage_e_dispatch.
# _stage_c_manifest_extractor_keys`' own lazy-import note for the same posture).
TARGET_BATCH_SECONDS = 300.0

# One core is pinned to network work, never to compute - `run_image_evidence_cohort`'s own
# `--workers` default is 7 on this 8-OCPU host for exactly this reason, and that allocation is the
# established one, not a new judgement made here.
CORES_RESERVED_FOR_NETWORK = 1

# Fetch threads ONE `dispatch_micro_batch` call runs: exactly one. `stage_e_dispatch` starts a
# single `threading.Thread` running `_stage_c_fetch_ahead_worker`, which fetches serially into a
# `queue.Queue(maxsize=_STAGE_C_FETCH_AHEAD_DEPTH)` while THIS dispatch's own loop does the
# sequential OCR/phash compute. Declared as a named constant rather than left as an implicit 1
# because it is the multiplicand in the aggregate-fetch arithmetic below, and an aggregate that
# silently assumed 1 would be wrong the day the fetch stage grows a pool.
FETCH_THREADS_PER_DISPATCH = 1


@dataclass(frozen=True)
class HostProfile:
    """
    What the rule discovered about the host it is running on, right now. `available_rss_mb` is
    best-effort and `None` on a platform without a readable `/proc/meminfo` - callers must treat
    `None` as "skip the memory guard", never as an error, matching
    `process_metrics.get_process_rss_mb`'s own documented convention for exactly the same reason.

    `concurrent_dispatches` IS A PROCESS COUNT, NOT A THREAD COUNT, and everything below depends on
    that distinction - see `discover_host`.
    """

    cpu_count: int
    usable_cores: int
    concurrent_dispatches: int
    available_rss_mb: Optional[float]

    @property
    def aggregate_fetch_threads(self) -> int:
        """
        Concurrent fetches this pipeline can really have in flight against
        `harvest_fetch_limiter.GOOGLE_IMAGE`, across every dispatch at once.

        READ THE MULTIPLICATION LITERALLY. It is NOT clamped to `GOOGLE_IMAGE.max_concurrency`, and
        the reason is one line of `harvest_fetch_limiter._DestinationLimiter.__init__`:

            self._semaphore = threading.Semaphore(config.max_concurrency)

        A `threading.Semaphore` coordinates THREADS INSIDE ONE PROCESS. Concurrent dispatches are
        separate OS PROCESSES (`stage_e_concurrency`'s module docstring: django-q2's workers are
        "separate OS PROCESSES (`multiprocessing`, not threads)"), so each one constructs its own
        full-strength `Semaphore(6)` that cannot see - and is not blocked by - the other N-1. The
        aggregate the destination experiences is therefore N x this dispatch's fetch threads, and
        `min(..., GOOGLE_IMAGE.max_concurrency, ...)` anywhere in this module would be asserting a
        cross-process guarantee that no cross-process mechanism provides. This is the same defect
        `run_image_evidence_cohort`'s docstring records having had to compensate for with a
        per-worker "descaling hack" back when fetching lived inside N compute processes; that hack
        was retired when fetching moved into ONE process, where the semaphore is honest. The
        conveyor is the multi-process case, so the honest number here is the product.
        """
        return self.concurrent_dispatches * FETCH_THREADS_PER_DISPATCH

    @property
    def fetch_overcommitted(self) -> bool:
        """
        True when this host's configured dispatch concurrency puts more concurrent fetches on
        `GOOGLE_IMAGE` than the destination budget task #165's probe ratified (`max_concurrency=6`,
        the concurrency=10 step having been REJECTED on a 2.43x p95 canary regression).

        This module CANNOT fix that by shrinking a batch - the overcommit is a function of process
        count, and the batch size is what each process does once it is running. What it can do, and
        does, is refuse to hide it: the flag is surfaced in `BatchSizeDecision.describe()`, so an
        unattended run states the condition on its own first line instead of leaving it to be
        rediscovered from an envelope trip. The lever is `STAGE_E_MAX_CONCURRENT_DISPATCHES`
        (production default 2, i.e. 2 concurrent fetches against a budget of 6 - comfortably
        inside it, which is why this is a guard rather than a live problem).
        """
        return self.aggregate_fetch_threads > GOOGLE_IMAGE.max_concurrency


@dataclass(frozen=True)
class BatchSizeDecision:
    """
    The answer plus its whole derivation, so a run's log can state WHY it chose a size rather than
    just asserting one. `source` is which precedence tier decided ("flag", "setting" or
    "autoscale"); `bound_by` is which term of the rule was the binding one when `source` is
    "autoscale" ("saturation", "memory", "duration", or "floor" when a guard pushed below
    MIN_BATCH_SIZE and was clamped back up).
    """

    batch_size: int
    mode: str
    source: str
    bound_by: str
    host: Optional[HostProfile] = None
    saturation_limit: Optional[int] = None
    memory_limit: Optional[int] = None
    duration_limit: Optional[int] = None

    def describe(self) -> str:
        if self.source != "autoscale":
            return f"batch_size={self.batch_size} (source={self.source}, mode={self.mode})"
        host = self.host
        # An over-committed fetch aggregate is prepended, not appended, and shouted: it is the one
        # thing in this line that is a WARNING about the run rather than a description of it, and
        # an unattended multi-hour run's operator must see it without parsing the rest. It cannot
        # be fixed by any number this rule chooses - see `HostProfile.fetch_overcommitted`.
        overcommit = ""
        if host is not None and host.fetch_overcommitted:
            overcommit = (
                f"FETCH-OVERCOMMIT: {host.aggregate_fetch_threads} concurrent fetches against "
                f"{GOOGLE_IMAGE.name} budget {GOOGLE_IMAGE.max_concurrency} - "
                f"per-process semaphores do not clamp this; lower "
                f"STAGE_E_MAX_CONCURRENT_DISPATCHES. "
            )
        return (
            f"{overcommit}"
            f"batch_size={self.batch_size} (source=autoscale, mode={self.mode}, "
            f"bound_by={self.bound_by}; saturation={self.saturation_limit}, "
            f"memory={self.memory_limit}, duration={self.duration_limit}; "
            f"cpus={host.cpu_count if host else '?'}, "
            f"usable_cores={host.usable_cores if host else '?'}, "
            f"dispatches={host.concurrent_dispatches if host else '?'}, "
            f"fetch_threads={host.aggregate_fetch_threads if host else '?'}, "
            f"available_mb={round(host.available_rss_mb) if host and host.available_rss_mb else '?'})"
        )


def _discover_cpu_count() -> int:
    """
    CPU count as this PROCESS may actually use it - `sched_getaffinity` first, so a cgroup- or
    taskset-restricted container reports what it was given rather than what the metal has, and
    `os.cpu_count()` only as the fallback for platforms without affinity support. Never returns
    less than 1.
    """
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _discover_available_rss_mb() -> Optional[float]:
    """
    Best-effort currently-available system memory (MB), read from `/proc/meminfo`'s `MemAvailable`
    - the kernel's own estimate of what is obtainable without swapping, which is the right
    question here (`MemFree` is not: it excludes reclaimable page cache and would make any busy
    host look starved). Never raises; returns `None` where `/proc` is unreadable, and every caller
    treats `None` as "skip the memory guard" (see `HostProfile`).
    """
    try:
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def discover_host() -> HostProfile:
    """
    The runtime hardware discovery the owner directive asks for ("scale with available hardware
    ... discovered at runtime, not hardcoded to this box").

    `concurrent_dispatches` is how many `dispatch_micro_batch` calls can be RESIDENT AT ONCE, and
    it is `settings.STAGE_E_MAX_CONCURRENT_DISPATCHES` alone. Not a minimum of anything.

    CORRECTED 2026-07-30 - IT USED TO BE A `min()` OF THREE TERMS AND TWO OF THEM WERE WRONG FOR
    THIS QUESTION. The old expression was:

        min(STAGE_E_MAX_CONCURRENT_DISPATCHES, GOOGLE_IMAGE.max_concurrency, usable_cores)

    - `GOOGLE_IMAGE.max_concurrency` was justified as "a stream past the limiter's sixth just
      blocks on its semaphore". IT DOES NOT. That limiter's ceiling is a `threading.Semaphore`
      built per process (`harvest_fetch_limiter._DestinationLimiter.__init__`), and concurrent
      dispatches are separate OS PROCESSES, so each holds its own independent `Semaphore(6)`.
      Nothing blocks on anyone else's. See `HostProfile.aggregate_fetch_threads`, which now states
      the real cross-process aggregate instead of a number that could never exceed 6 by
      construction, and `HostProfile.fetch_overcommitted`, which reports when it exceeds the
      destination budget rather than pretending arithmetic prevented it.
    - `usable_cores` bounds who is SCHEDULED, not who EXISTS. A dispatch process waiting for a core
      still holds its entire RSS, so it must still be counted by the memory guard below.

    The only thing that actually caps the number of concurrent dispatch processes is
    `stage_e_concurrency`'s Postgres advisory-lock slot count, which IS this setting (its
    `_slot_count()` reads exactly the same value, floored at 1) - a cross-process mechanism, which
    is what the question needs and the semaphore is not. So the setting is the whole answer, and
    under-counting it was the unsafe direction: `_memory_limit` divides by this, and dividing by 6
    when 12 processes are resident hands each one twice the memory budget it may really take.

    Compute-core pressure has NOT been dropped on the floor - it is still priced, in
    `_duration_limit`, via the envelope's own `HOST_LOAD_CEILING / usable_cores` contention term,
    which is where an oversubscribed host belongs. It just is not a process count.
    """
    cpu_count = _discover_cpu_count()
    usable_cores = max(1, cpu_count - CORES_RESERVED_FOR_NETWORK)
    configured_cap = getattr(settings, "STAGE_E_MAX_CONCURRENT_DISPATCHES", 2)
    try:
        configured_cap = max(1, int(configured_cap))
    except (TypeError, ValueError):
        configured_cap = 2
    return HostProfile(
        cpu_count=cpu_count,
        usable_cores=usable_cores,
        concurrent_dispatches=configured_cap,
        available_rss_mb=_discover_available_rss_mb(),
    )


def _memory_limit(host: HostProfile) -> Optional[int]:
    """
    How many cards a batch may hold before its own live set threatens the ratified per-worker RSS
    bar. The budget is the SMALLER of that bar and this host's actually-available memory divided
    between the concurrent dispatch PROCESSES - the bar alone would be the wrong question on a host
    that does not have 768 MB per process to give. `None` when available memory could not be read.

    The divisor is `concurrent_dispatches` (the advisory-lock cap), deliberately, and NOT a number
    trimmed by core count or by the fetch limiter: memory is held by every resident process,
    including one that is descheduled or blocked on a fetch. See `discover_host` for the 2026-07-30
    correction that removed those two trims, and why under-counting here was the unsafe direction.
    """
    if host.available_rss_mb is None:
        return None
    per_process_mb = min(RSS_MB_PER_WORKER_CEILING, host.available_rss_mb / host.concurrent_dispatches)
    headroom_mb = per_process_mb - BATCH_WORKING_SET_RSS_MB
    if headroom_mb <= 0:
        return 0
    return int(headroom_mb / MARGINAL_RSS_MB_PER_CARD)


def _duration_limit(host: HostProfile) -> int:
    """
    How many cards a batch may hold before it runs longer than one progress/envelope-sampling
    interval (module docstring's DURATION paragraph). Per-card cost is the measured fetch-bound
    floor, inflated by the WORST CPU contention a dispatch can legally be running under.

    THAT WORST CASE COMES FROM THE ENVELOPE, NOT FROM A LOAD READING, and the distinction is the
    whole point. `operating_envelope.HOST_LOAD_CEILING` is a flat 7.0 on every host - it is not
    scaled to core count - so a dispatch is permitted to start whenever the 1-minute load average
    is at most 7.0, which on a 16-core host is a quiet machine and on a 2-core laptop is 7x
    oversubscription. A run queue of 7.0 shared across `usable_cores` cores gives each runnable
    task `usable_cores / 7.0` of a core, so the extraction half of every card stretches by the
    reciprocal. Clamped at 1.0 on the roomy side: extra cores cannot make a card arrive faster
    than the fetch limiter allows.

    Deriving the inflation from the CEILING rather than from `os.getloadavg()` is deliberate and
    is the reason this function takes no live sample. This box routinely carries 5+ concurrent
    agent sessions at load 7.9-11.5; a batch size computed from whichever instant it happened to
    be evaluated in would be a different number on every dispatch, would be too large whenever the
    box was briefly quiet, and would make the rule untestable and unreproducible. The ceiling is a
    ratified constant, so this term is a property of the HOST, which is what was asked for.

    Note this is why the term is inert on the 8-OCPU production host (7 usable cores, ratio 1.0)
    and binds on smaller ones - it is a guard for hardware this rule has not been measured on, not
    a knob that trims the production size.
    """
    contention = max(1.0, HOST_LOAD_CEILING / host.usable_cores)
    per_card_seconds = FETCH_BOUND_CARD_SECONDS * contention
    return max(1, int(TARGET_BATCH_SECONDS / per_card_seconds))


def autoscale_batch_size(mode: str = MODE_BULK, host: Optional[HostProfile] = None) -> BatchSizeDecision:
    """
    The rule itself, with no precedence handling - `resolve_micro_batch_size` is the entry point
    callers should use. `host` is injectable so tests can state a hardware profile directly rather
    than trying to make the machine running them look like a laptop.

    MODE_INCREMENTAL short-circuits to a fixed size before any hardware is consulted, deliberately:
    that mode's whole point is a small bounded unit of work, and a term that could only ever raise
    it toward the saturation cap would defeat that (module docstring's "TWO MODES").
    """
    if mode == MODE_INCREMENTAL:
        return BatchSizeDecision(
            batch_size=INCREMENTAL_BATCH_SIZE,
            mode=mode,
            source="autoscale",
            bound_by="incremental",
        )

    profile = host if host is not None else discover_host()
    saturation = SATURATION_BATCH_SIZE
    memory = _memory_limit(profile)
    duration = _duration_limit(profile)

    candidates = [("saturation", saturation), ("duration", duration)]
    if memory is not None:
        candidates.append(("memory", memory))
    bound_by, chosen = min(candidates, key=lambda pair: pair[1])
    if chosen < MIN_BATCH_SIZE:
        chosen, bound_by = MIN_BATCH_SIZE, "floor"

    return BatchSizeDecision(
        batch_size=chosen,
        mode=mode,
        source="autoscale",
        bound_by=bound_by,
        host=profile,
        saturation_limit=saturation,
        memory_limit=memory,
        duration_limit=duration,
    )


def resolve_micro_batch_size(
    explicit: Optional[int] = None,
    mode: str = MODE_BULK,
    host: Optional[HostProfile] = None,
) -> BatchSizeDecision:
    """
    THE entry point every caller uses. Applies the precedence the module docstring states: an
    explicit caller argument (a `--batch-size` flag) beats an explicit
    `settings.STAGE_E_MICRO_BATCH_SIZE` beats the rule.

    `settings.STAGE_E_MICRO_BATCH_SIZE` now defaults to `None` ("auto"), and a non-`None` value
    means an operator or an environment deliberately pinned it - which is why it outranks the rule
    rather than merely seeding it. A non-positive or unparseable pin is IGNORED rather than
    honoured or raised on: this function is called on the dispatch path of an unattended
    multi-hour run, where a typo'd env var must not be able to take the run down, and a batch size
    of 0 is not a size at all.
    """
    if explicit is not None:
        return BatchSizeDecision(batch_size=explicit, mode=mode, source="flag", bound_by="flag")

    pinned = getattr(settings, "STAGE_E_MICRO_BATCH_SIZE", None)
    if pinned is not None:
        try:
            pinned_int = int(pinned)
        except (TypeError, ValueError):
            pinned_int = 0
        if pinned_int > 0:
            return BatchSizeDecision(batch_size=pinned_int, mode=mode, source="setting", bound_by="setting")

    return autoscale_batch_size(mode=mode, host=host)
