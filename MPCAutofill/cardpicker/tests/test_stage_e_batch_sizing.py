"""
Tests for `cardpicker.stage_e_batch_sizing` (2026-07-29, micro-batch size as a measured runtime
property rather than a constant) and for the four call sites that consume it.

EVERY HARDWARE-DEPENDENT ASSERTION INJECTS A `HostProfile`. Nothing here reads the machine running
the suite, and that is the point rather than a convenience: a rule whose whole job is to behave
differently on different hardware cannot be tested on one host by hoping that host happens to
exhibit each case. `autoscale_batch_size(host=...)` exists for exactly this. The two tests that DO
touch real discovery (`TestHostDiscovery`) assert only invariants that hold on any host - bounds
and orderings, never a number.
"""

from typing import Any, Optional

import pytest

from django.test import override_settings

from cardpicker.harvest_fetch_limiter import GOOGLE_IMAGE
from cardpicker.operating_envelope import HOST_LOAD_CEILING, RSS_MB_PER_WORKER_CEILING
from cardpicker.stage_e_batch_sizing import (
    BATCH_WORKING_SET_RSS_MB,
    FETCH_BOUND_CARD_SECONDS,
    FETCH_THREADS_PER_DISPATCH,
    INCREMENTAL_BATCH_SIZE,
    MARGINAL_RSS_MB_PER_CARD,
    MIN_BATCH_SIZE,
    MODE_BULK,
    MODE_INCREMENTAL,
    SATURATION_BATCH_SIZE,
    TARGET_BATCH_SECONDS,
    BatchSizeDecision,
    HostProfile,
    autoscale_batch_size,
    discover_host,
    resolve_micro_batch_size,
)


def host(
    cpu_count: int = 8,
    concurrent_dispatches: int = 3,
    available_rss_mb: Optional[float] = 18000.0,
    usable_cores: Optional[int] = None,
) -> HostProfile:
    """A stated hardware profile. `usable_cores` defaults to the rule's own
    `cpu_count - CORES_RESERVED_FOR_NETWORK`, so a test that only cares about memory does not have
    to restate the core arithmetic."""
    return HostProfile(
        cpu_count=cpu_count,
        usable_cores=usable_cores if usable_cores is not None else max(1, cpu_count - 1),
        concurrent_dispatches=concurrent_dispatches,
        available_rss_mb=available_rss_mb,
    )


class TestSaturationCap:
    """The measured fetch-saturation limit is the operative value on any healthy host, and it does
    NOT grow with the hardware - the constraint that separates this rule from "use as much of the
    box as you can find"."""

    def test_a_well_resourced_host_lands_exactly_on_the_saturation_cap(self) -> None:
        decision = autoscale_batch_size(mode=MODE_BULK, host=host())
        assert decision.batch_size == SATURATION_BATCH_SIZE
        assert decision.bound_by == "saturation"

    @pytest.mark.parametrize("cpus,memory_mb", [(8, 18_000.0), (64, 512_000.0), (256, 4_000_000.0)])
    def test_more_hardware_never_buys_a_bigger_batch_than_the_fetch_limiter_allows(
        self, cpus: int, memory_mb: float
    ) -> None:
        # The owner directive is "scale with available hardware UP TO the fetch saturation limit".
        # A 256-core host with 4 TB of RAM must still choose the saturation cap: the cap is set by
        # ONE dispatch's own serial fetch floor (a single fetch-ahead thread, so `1 / c` cards per
        # second whatever the batch size), which is a property of the network round trip and not of
        # this machine - so past the cap a larger batch buys no throughput and only costs memory.
        decision = autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=cpus, available_rss_mb=memory_mb))
        assert decision.batch_size == SATURATION_BATCH_SIZE

    def test_the_cap_is_the_size_the_measurement_selected(self) -> None:
        # Pins the number the measurement table in the module docstring was read off. If a future
        # re-measurement moves it, this test is the place that says so out loud rather than the
        # value drifting silently.
        assert SATURATION_BATCH_SIZE == 250


class TestMemoryGuard:
    """The memory term against the ratified 768 MB per-worker RSS bar. It is a GUARD - on any host
    that can hold the working set it is worth hundreds of thousands of cards and cannot bind - so
    what is worth testing is that it engages at all when the host really is small, and that it
    divides the host's memory between every concurrent dispatch PROCESS rather than handing the
    whole machine to each one."""

    def test_a_host_that_cannot_hold_the_working_set_collapses_to_the_floor(self) -> None:
        # 900 MB available across 3 dispatches is 300 MB each - under the ~320 MB a warm
        # dispatch process needs to exist at all. The batch cannot be made to fit by shrinking it,
        # so the rule floors rather than returning something absurd like 0 or a negative.
        decision = autoscale_batch_size(mode=MODE_BULK, host=host(available_rss_mb=900.0))
        assert decision.batch_size == MIN_BATCH_SIZE
        assert decision.bound_by == "floor"
        assert decision.memory_limit == 0

    def test_the_budget_is_divided_between_concurrent_dispatch_processes(self) -> None:
        # Same machine, same memory; only the number of dispatch processes sharing it changes. One
        # can use the whole 1000 MB and clears the working set easily; four get 250 MB each and
        # cannot. A rule that handed every process the whole machine would return the same answer to
        # both, which is the failure this pins.
        roomy = autoscale_batch_size(mode=MODE_BULK, host=host(available_rss_mb=1000.0, concurrent_dispatches=1))
        crowded = autoscale_batch_size(mode=MODE_BULK, host=host(available_rss_mb=1000.0, concurrent_dispatches=4))
        assert roomy.memory_limit is not None and crowded.memory_limit is not None
        assert roomy.memory_limit > crowded.memory_limit
        assert crowded.memory_limit == 0

    def test_the_budget_never_exceeds_the_ratified_per_worker_rss_bar(self) -> None:
        # A host with effectively unlimited memory must still be bounded by the 768 MB bar, because
        # that bar is what the operating envelope actually trips on - sizing against the machine's
        # free memory instead would produce batches the envelope halts.
        limit = autoscale_batch_size(
            mode=MODE_BULK, host=host(available_rss_mb=10_000_000.0, concurrent_dispatches=1)
        ).memory_limit
        implied = int((RSS_MB_PER_WORKER_CEILING - BATCH_WORKING_SET_RSS_MB) / MARGINAL_RSS_MB_PER_CARD)
        assert limit == implied

    def test_the_divisor_counts_processes_the_fetch_semaphore_would_have_hidden(self) -> None:
        # The sizing consequence of the discovery fix, on a host small enough for the memory term to
        # be the binding one. 12 concurrent dispatches on a 8 GB box get 683 MB each; the old
        # expression clamped the count to `GOOGLE_IMAGE.max_concurrency` = 6 and handed each one
        # 1366 MB - over the 768 MB per-worker bar, and twice the memory the batch may really take.
        # The semaphore that clamp appealed to is per-PROCESS and cannot see the other eleven.
        honest = autoscale_batch_size(mode=MODE_BULK, host=host(available_rss_mb=8192.0, concurrent_dispatches=12))
        as_the_semaphore_would_have_had_it = autoscale_batch_size(
            mode=MODE_BULK, host=host(available_rss_mb=8192.0, concurrent_dispatches=GOOGLE_IMAGE.max_concurrency)
        )
        assert honest.memory_limit is not None and as_the_semaphore_would_have_had_it.memory_limit is not None
        assert honest.memory_limit < as_the_semaphore_would_have_had_it.memory_limit

    def test_unreadable_memory_skips_the_guard_rather_than_failing(self) -> None:
        # `process_metrics.get_process_rss_mb`'s established convention: a best-effort signal that
        # could not be read is "skip this bar", never an error and never a zero that would be
        # mistaken for "no memory available".
        decision = autoscale_batch_size(mode=MODE_BULK, host=host(available_rss_mb=None))
        assert decision.memory_limit is None
        assert decision.batch_size == SATURATION_BATCH_SIZE


class TestDurationGuard:
    """The duration term: a batch is simultaneously the envelope's sampling interval and the
    resume/kill-loss bound, so it must not outlive one progress interval. The per-card cost is
    inflated by the WORST contention the envelope will still dispatch under
    (`HOST_LOAD_CEILING / usable_cores`), never by a live load reading."""

    def test_a_host_with_few_cores_gets_a_smaller_batch(self) -> None:
        # 4 cores -> 3 usable -> a run queue of 7.0 (the highest the envelope permits a dispatch to
        # start at, on every host, because HOST_LOAD_CEILING is flat) gives each task 3/7 of a core,
        # so every card stretches 2.33x and the same batch would run 2.33x longer. This is the
        # "behaves sensibly on a maintainer's laptop" case.
        laptop = autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=4, concurrent_dispatches=3))
        assert laptop.batch_size < SATURATION_BATCH_SIZE
        assert laptop.bound_by == "duration"
        assert laptop.batch_size == int(TARGET_BATCH_SECONDS / (FETCH_BOUND_CARD_SECONDS * (HOST_LOAD_CEILING / 3)))

    def test_smaller_hosts_get_monotonically_smaller_batches(self) -> None:
        sizes = [autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=cpus)).batch_size for cpus in (2, 3, 4, 6, 8)]
        assert sizes == sorted(sizes), sizes
        assert sizes[0] < sizes[-1], "the rule must actually vary with the hardware, not just claim to"

    def test_the_production_host_is_not_trimmed_by_this_guard(self) -> None:
        # 8 OCPU -> 7 usable -> ratio exactly 1.0. The guard is for hardware the rule has not been
        # measured on; it must not quietly clip the size on the host it WAS measured on.
        production = autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=8))
        assert production.batch_size == SATURATION_BATCH_SIZE
        assert production.duration_limit == int(TARGET_BATCH_SECONDS / FETCH_BOUND_CARD_SECONDS)

    def test_spare_cores_do_not_inflate_the_batch_past_saturation(self) -> None:
        # Contention below 1.0 is clamped to 1.0: extra cores cannot make a card arrive faster than
        # the fetch limiter allows, so a wide host must not talk itself into a longer batch.
        wide = autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=64, concurrent_dispatches=2))
        assert wide.duration_limit == int(TARGET_BATCH_SECONDS / FETCH_BOUND_CARD_SECONDS)
        assert wide.batch_size == SATURATION_BATCH_SIZE

    def test_a_severely_contended_host_is_still_floored_not_driven_to_one(self) -> None:
        starved = autoscale_batch_size(
            mode=MODE_BULK, host=host(cpu_count=2, usable_cores=1, concurrent_dispatches=1, available_rss_mb=8000.0)
        )
        assert starved.batch_size >= MIN_BATCH_SIZE

    def test_the_guard_reads_no_live_load_average(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The binding caution: this box routinely carries 5+ concurrent agent sessions at load
        # 7.9-11.5, so a size fitted to whichever instant it was computed in would be a different
        # number every dispatch. A rule that consulted getloadavg would move when this does.
        import os as _os

        monkeypatch.setattr(_os, "getloadavg", lambda: (0.01, 0.01, 0.01))
        quiet = autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=4))
        monkeypatch.setattr(_os, "getloadavg", lambda: (40.0, 40.0, 40.0))
        busy = autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=4))
        assert quiet.batch_size == busy.batch_size

    def test_the_target_is_the_commands_own_progress_interval(self) -> None:
        from cardpicker.management.commands.stream_full_catalog import (
            DEFAULT_PROGRESS_EVERY_SECONDS,
        )

        # Not an arbitrary 300: a batch that outlives one progress interval makes
        # --progress-every-seconds' own "bounds how stale the log's own resume pk can be" untrue.
        assert TARGET_BATCH_SECONDS == DEFAULT_PROGRESS_EVERY_SECONDS


class TestIncrementalMode:
    """Event echoes and the cron backstop sweep want a small bounded unit of work, not throughput."""

    def test_incremental_ignores_the_hardware_entirely(self) -> None:
        big = autoscale_batch_size(mode=MODE_INCREMENTAL, host=host(cpu_count=256, available_rss_mb=4_000_000.0))
        small = autoscale_batch_size(mode=MODE_INCREMENTAL, host=host(cpu_count=2, available_rss_mb=600.0))
        assert big.batch_size == small.batch_size == INCREMENTAL_BATCH_SIZE
        assert big.bound_by == "incremental"

    def test_incremental_is_the_pre_autoscale_production_size(self) -> None:
        # The event path is behaviourally UNCHANGED by this module's introduction. If this ever
        # stops holding it should be a deliberate decision with its own reasoning, not a side
        # effect of retuning the bulk pass.
        assert INCREMENTAL_BATCH_SIZE == 25

    def test_bulk_and_incremental_genuinely_differ_on_a_healthy_host(self) -> None:
        healthy = host()
        assert (
            autoscale_batch_size(mode=MODE_BULK, host=healthy).batch_size
            > autoscale_batch_size(mode=MODE_INCREMENTAL, host=healthy).batch_size
        )


class TestPrecedence:
    """An explicit setting always wins - the property `stream_full_catalog`'s "every tunable is a
    flag" design constraint depends on."""

    def test_an_explicit_argument_beats_everything(self) -> None:
        with override_settings(STAGE_E_MICRO_BATCH_SIZE=77):
            decision = resolve_micro_batch_size(explicit=13, mode=MODE_BULK, host=host())
        assert decision.batch_size == 13
        assert decision.source == "flag"

    def test_a_pinned_setting_beats_the_rule(self) -> None:
        with override_settings(STAGE_E_MICRO_BATCH_SIZE=77):
            decision = resolve_micro_batch_size(mode=MODE_BULK, host=host())
        assert decision.batch_size == 77
        assert decision.source == "setting"

    def test_an_unpinned_setting_hands_over_to_the_rule(self) -> None:
        with override_settings(STAGE_E_MICRO_BATCH_SIZE=None):
            decision = resolve_micro_batch_size(mode=MODE_BULK, host=host())
        assert decision.batch_size == SATURATION_BATCH_SIZE
        assert decision.source == "autoscale"

    @pytest.mark.parametrize("pinned", [0, -5, "nonsense", ""])
    def test_a_nonsensical_pin_is_ignored_rather_than_honoured_or_raised_on(self, pinned: Any) -> None:
        # This runs on the dispatch path of an unattended multi-hour run: a typo'd env var must not
        # be able to take the run down, and 0 is not a batch size.
        with override_settings(STAGE_E_MICRO_BATCH_SIZE=pinned):
            decision = resolve_micro_batch_size(mode=MODE_BULK, host=host())
        assert decision.source == "autoscale"
        assert decision.batch_size == SATURATION_BATCH_SIZE

    def test_a_pinned_setting_applies_to_incremental_too(self) -> None:
        with override_settings(STAGE_E_MICRO_BATCH_SIZE=9):
            assert resolve_micro_batch_size(mode=MODE_INCREMENTAL).batch_size == 9


class TestHostDiscovery:
    """Real discovery, asserted only on invariants that hold on ANY host."""

    def test_concurrent_dispatches_is_the_advisory_lock_cap_and_nothing_else(self) -> None:
        # THE REGRESSION THIS PINS (2026-07-30). `discover_host` used to compute
        #     dispatch_streams = min(STAGE_E_MAX_CONCURRENT_DISPATCHES,
        #                            GOOGLE_IMAGE.max_concurrency,   # <- 6
        #                            usable_cores)
        # and then divide the host's memory by it. Both of the extra terms are wrong for this
        # number. `GOOGLE_IMAGE.max_concurrency` is enforced by a `threading.Semaphore` built once
        # PER PROCESS (`harvest_fetch_limiter._DestinationLimiter.__init__`), and concurrent
        # dispatches are separate OS PROCESSES, so it constrains nothing across them; `usable_cores`
        # bounds who is SCHEDULED, not who is RESIDENT, and a descheduled dispatch process still
        # holds its whole RSS. The only thing that caps how many dispatch processes exist at once is
        # `stage_e_concurrency`'s Postgres advisory-lock slot count, i.e. the setting itself.
        #
        # Under the old expression this assertion reads 6 (min(12, 6, usable_cores) on any host with
        # >= 7 usable cores), i.e. the rule believed half as many processes were sharing the box as
        # really are, and handed each one twice the memory budget it may actually take.
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=12):
            profile = discover_host()
        assert profile.concurrent_dispatches == 12
        assert profile.concurrent_dispatches > GOOGLE_IMAGE.max_concurrency
        assert profile.usable_cores <= profile.cpu_count

    def test_the_real_aggregate_fetch_concurrency_is_per_process_multiplied(self) -> None:
        # The other half of the same falsehood, stated as a number. N concurrent dispatches each
        # construct their OWN `threading.Semaphore(GOOGLE_IMAGE.max_concurrency)`, so the aggregate
        # the destination actually sees is N x (this dispatch's fetch threads) - it is NOT clamped
        # to 6 by anything. The old code asserted the opposite by construction (its
        # `min(..., GOOGLE_IMAGE.max_concurrency, ...)` could never exceed 6).
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=12):
            profile = discover_host()
        assert profile.aggregate_fetch_threads == 12 * FETCH_THREADS_PER_DISPATCH
        assert profile.fetch_overcommitted is True

    def test_a_conveyor_sized_cap_is_within_the_destination_budget(self) -> None:
        # The production setting (2) and the largest cap that still fits the destination budget are
        # NOT flagged - the flag has to mean something, so it must be quiet in the normal case.
        for cap in (1, 2, GOOGLE_IMAGE.max_concurrency // FETCH_THREADS_PER_DISPATCH):
            with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=cap):
                profile = discover_host()
            assert profile.aggregate_fetch_threads <= GOOGLE_IMAGE.max_concurrency
            assert profile.fetch_overcommitted is False

    def test_the_configured_concurrency_cap_is_honoured_when_it_is_the_smallest(self) -> None:
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1):
            assert discover_host().concurrent_dispatches == 1

    def test_a_garbage_concurrency_cap_does_not_raise(self) -> None:
        with override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES="not-a-number"):
            assert discover_host().concurrent_dispatches >= 1

    def test_discovery_reports_a_plausible_machine(self) -> None:
        profile = discover_host()
        assert profile.cpu_count >= 1
        assert profile.usable_cores >= 1
        assert profile.available_rss_mb is None or profile.available_rss_mb > 0

    def test_the_real_host_produces_a_usable_bulk_size(self) -> None:
        with override_settings(STAGE_E_MICRO_BATCH_SIZE=None):
            decision = resolve_micro_batch_size(mode=MODE_BULK)
        assert MIN_BATCH_SIZE <= decision.batch_size <= SATURATION_BATCH_SIZE


class TestDecisionReporting:
    """The operator has to be able to read WHY off the log - an autoscaled tunable that reported
    only its answer would defeat the kill-change-relaunch working method."""

    def test_describe_names_the_binding_term_and_the_discovered_inputs(self) -> None:
        text = autoscale_batch_size(mode=MODE_BULK, host=host(cpu_count=12, available_rss_mb=4321.0)).describe()
        assert "source=autoscale" in text
        assert "bound_by=saturation" in text
        assert "cpus=12" in text
        assert "available_mb=4321" in text
        assert f"saturation={SATURATION_BATCH_SIZE}" in text
        # The two numbers the 2026-07-30 correction added. `dispatches` is the memory divisor and
        # `fetch_threads` is what the destination really sees; an operator reading a run's log has
        # to be able to tell the second one is not 6-by-construction.
        assert "dispatches=3" in text
        assert f"fetch_threads={3 * FETCH_THREADS_PER_DISPATCH}" in text

    def test_describe_shouts_when_the_configured_cap_overcommits_the_destination(self) -> None:
        # An over-committed fetch aggregate is an operational fact the run's own first line must
        # state, not something an operator has to derive from the setting and the limiter config.
        text = autoscale_batch_size(
            mode=MODE_BULK, host=host(concurrent_dispatches=GOOGLE_IMAGE.max_concurrency + 1)
        ).describe()
        assert "FETCH-OVERCOMMIT" in text

    def test_describe_names_the_flag_when_the_flag_decided(self) -> None:
        text = resolve_micro_batch_size(explicit=42, mode=MODE_BULK).describe()
        assert "batch_size=42" in text and "source=flag" in text

    def test_a_decision_is_immutable(self) -> None:
        decision = autoscale_batch_size(mode=MODE_BULK, host=host())
        with pytest.raises(Exception):
            decision.batch_size = 1  # type: ignore[misc]
        assert isinstance(decision, BatchSizeDecision)


class TestConsumerWiring:
    """Which mode each call site asks for. Worth its own tests because the modes are
    indistinguishable from the outside once the number has been chosen - a driver wired to the
    wrong one produces a batch size that is not wrong, only silently slow (or silently ten times
    the scheduled footprint), and nothing else in the suite would notice."""

    def _spy(self, monkeypatch: pytest.MonkeyPatch, module: Any) -> list:
        seen: list = []
        real = module.resolve_micro_batch_size

        def _recorder(**kwargs: Any) -> Any:
            seen.append(kwargs)
            return real(**kwargs)

        monkeypatch.setattr(module, "resolve_micro_batch_size", _recorder)
        return seen

    def test_the_event_echo_fallback_asks_for_incremental(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        from cardpicker import stage_e_dispatch

        seen = self._spy(monkeypatch, stage_e_dispatch)
        with override_settings(STAGE_E_STREAMING_ENABLED=True, STAGE_E_MICRO_BATCH_SIZE=None):
            stage_e_dispatch.dispatch_micro_batch(card_ids=None, trigger_reason="event")

        assert seen and seen[0]["mode"] == MODE_INCREMENTAL

    def test_an_explicit_batch_size_still_reaches_the_conveyor_unchanged(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cardpicker import stage_e_dispatch

        seen = self._spy(monkeypatch, stage_e_dispatch)
        with override_settings(STAGE_E_STREAMING_ENABLED=True, STAGE_E_MICRO_BATCH_SIZE=None):
            stage_e_dispatch.dispatch_micro_batch(card_ids=[], batch_size=7)

        assert seen[0]["explicit"] == 7

    def test_the_cron_backstop_sweep_asks_for_incremental(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        # Its per-invocation footprint is --max-batches (default 1000) x batch size. Taking the
        # bulk size here would turn one scheduled sweep into a 250,000-card job.
        from django.core.management import call_command

        from cardpicker.management.commands import stream_backstop_sweep

        seen = self._spy(monkeypatch, stream_backstop_sweep)
        with override_settings(STAGE_E_STREAMING_ENABLED=True, STAGE_E_MICRO_BATCH_SIZE=None):
            call_command("stream_backstop_sweep", "--max-batches", "1")

        assert seen and seen[0]["mode"] == MODE_INCREMENTAL

    def test_the_bulk_driver_asks_for_bulk(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        from cardpicker.management.commands import stream_full_catalog

        seen = self._spy(monkeypatch, stream_full_catalog)
        monkeypatch.setattr(stream_full_catalog, "_get_default_cards_entry", lambda: None)
        monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: True)
        from django.core.management import call_command

        with override_settings(STAGE_E_STREAMING_ENABLED=True, STAGE_E_MICRO_BATCH_SIZE=None):
            call_command("stream_full_catalog", "--dry-run")

        assert seen and seen[0]["mode"] == MODE_BULK
