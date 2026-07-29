"""
Tests for cardpicker.operating_envelope - the Stage E Phase 1 envelope enforcement primitive
(docs/proposals/stage-e-streaming.md §3 decision (5)/§10(a)'s ratified PASSIVE-mode bars). Pure
primitive, no streaming loop consumes it yet (see the module's own docstring) - these tests cover
the four bars individually, trip persistence, the current_trip() gating query, and the
acknowledge_trip() resume action in isolation from any dispatcher.
"""

import pytest

from cardpicker.models import EnvelopeTrip
from cardpicker.operating_envelope import (
    FETCH_FAILURE_RATE_CEILING,
    FETCH_FAILURE_WINDOW,
    HOST_LOAD_CEILING,
    RSS_MB_PER_WORKER_CEILING,
    EnvelopeSignals,
    acknowledge_trip,
    check_envelope,
    current_trip,
)


def _failures_exactly_at_the_rate_ceiling() -> int:
    """
    The failure count that puts a FULL `FETCH_FAILURE_WINDOW` EXACTLY on
    `FETCH_FAILURE_RATE_CEILING` - 5 failures in 500 at today's ratified 1%/500 numbers.

    Derived rather than hardcoded for the same reason ea72abf7 derived the RSS tests from
    `RSS_MB_PER_WORKER_CEILING`: a signal literal chosen relative to a threshold rots silently when
    the threshold moves. The rate bar's boundary case is the worst instance of that shape, because
    it asserts `is None` - if the ceiling rose, a hardcoded 5/500 would keep passing while no longer
    sitting on the boundary it exists to pin. The callers' own `failures / FETCH_FAILURE_WINDOW ==
    FETCH_FAILURE_RATE_CEILING` assertion is the tether: if a future ceiling/window pair makes this
    count non-exact, the boundary test fails LOUDLY and asks to be rethought rather than quietly
    testing something else.
    """
    return round(FETCH_FAILURE_RATE_CEILING * FETCH_FAILURE_WINDOW)


class TestCheckEnvelopeClearSignals:
    def test_returns_none_when_nothing_breached(self, db):
        signals = EnvelopeSignals(
            load_avg=1.0,
            rss_mb_per_worker=100.0,
            fetch_failures_in_window=1,
            fetch_total_in_window=500,
            google_lockout=False,
        )
        assert check_envelope(signals) is None
        assert EnvelopeTrip.objects.count() == 0

    def test_returns_none_for_all_default_signals(self, db):
        # every field defaults to None/0/False - the "no data yet" state, never trips.
        assert check_envelope(EnvelopeSignals()) is None
        assert EnvelopeTrip.objects.count() == 0

    def test_exactly_at_the_ceiling_does_not_trip(self, db):
        """Bars are '>' the ceiling, not '>=' - the ratified numbers (§10(a)) are themselves safe
        values (e.g. the 7.0 load-average escalation threshold is the existing safe boundary, not
        the first unsafe value)."""
        signals = EnvelopeSignals(load_avg=HOST_LOAD_CEILING, rss_mb_per_worker=RSS_MB_PER_WORKER_CEILING)
        assert check_envelope(signals) is None


class TestHostLoadBar:
    def test_trips_just_above_the_host_load_ceiling(self, db):
        load_avg = HOST_LOAD_CEILING + 0.1
        trip = check_envelope(EnvelopeSignals(load_avg=load_avg))
        assert trip is not None
        assert trip.bar == EnvelopeTrip.Bar.HOST_LOAD
        assert trip.detail == {"load_avg": load_avg, "ceiling": HOST_LOAD_CEILING}

    def test_persists_a_row(self, db):
        check_envelope(EnvelopeSignals(load_avg=9.0))
        assert EnvelopeTrip.objects.filter(bar=EnvelopeTrip.Bar.HOST_LOAD).count() == 1


class TestRssBar:
    def test_trips_above_rss_ceiling_per_worker(self, db):
        rss_mb_per_worker = RSS_MB_PER_WORKER_CEILING + 0.1
        trip = check_envelope(EnvelopeSignals(rss_mb_per_worker=rss_mb_per_worker))
        assert trip is not None
        assert trip.bar == EnvelopeTrip.Bar.RSS
        assert trip.detail == {"rss_mb_per_worker": rss_mb_per_worker, "ceiling": RSS_MB_PER_WORKER_CEILING}

    def test_well_under_the_ceiling_does_not_trip(self, db):
        assert check_envelope(EnvelopeSignals(rss_mb_per_worker=190.0)) is None


class TestFetchFailureRateBar:
    def test_trips_just_above_the_rate_ceiling_over_the_window(self, db):
        # one failure more than the ceiling allows over a full window (6/500 = 1.2% > 1% today) -
        # derived, not hardcoded, so a future ceiling/window change can't leave this feeding a
        # value that no longer breaches.
        failures = _failures_exactly_at_the_rate_ceiling() + 1
        trip = check_envelope(
            EnvelopeSignals(fetch_failures_in_window=failures, fetch_total_in_window=FETCH_FAILURE_WINDOW)
        )
        assert trip is not None
        assert trip.bar == EnvelopeTrip.Bar.FETCH_FAILURE_RATE
        assert trip.detail["fetch_failure_rate"] == pytest.approx(failures / FETCH_FAILURE_WINDOW)
        assert trip.detail["ceiling"] == FETCH_FAILURE_RATE_CEILING
        assert trip.detail["failures"] == failures
        assert trip.detail["total"] == FETCH_FAILURE_WINDOW

    def test_exactly_at_the_rate_ceiling_does_not_trip(self, db):
        """The `>` (not `>=`) boundary for the rate bar, the fetch-side twin of
        TestCheckEnvelopeClearSignals::test_exactly_at_the_ceiling_does_not_trip. Derived from the
        ceiling rather than written as 5/500: a hardcoded pair stays GREEN if the ceiling moves, it
        just silently stops sitting on the boundary it claims to test."""
        failures = _failures_exactly_at_the_rate_ceiling()
        assert failures / FETCH_FAILURE_WINDOW == FETCH_FAILURE_RATE_CEILING
        assert (
            check_envelope(
                EnvelopeSignals(fetch_failures_in_window=failures, fetch_total_in_window=FETCH_FAILURE_WINDOW)
            )
            is None
        )

    def test_never_trips_on_an_empty_window(self, db):
        """total=0 means 'not enough data yet', not a 0/0 division or a spurious trip."""
        assert check_envelope(EnvelopeSignals(fetch_failures_in_window=0, fetch_total_in_window=0)) is None

    def test_a_small_window_can_still_breach_the_rate(self, db):
        # not gated on FETCH_FAILURE_WINDOW itself being reached - the caller owns windowing; this
        # module only compares whatever rate it's given.
        trip = check_envelope(EnvelopeSignals(fetch_failures_in_window=1, fetch_total_in_window=10))
        assert trip is not None
        assert trip.bar == EnvelopeTrip.Bar.FETCH_FAILURE_RATE


class TestGoogleLockoutBar:
    def test_trips_instantly_regardless_of_other_signals(self, db):
        """No ceiling to cross - any occurrence trips immediately, even with every other signal
        well inside its own bar (§10(a)'s 'instant pause')."""
        trip = check_envelope(
            EnvelopeSignals(load_avg=0.1, rss_mb_per_worker=1.0, fetch_total_in_window=0, google_lockout=True)
        )
        assert trip is not None
        assert trip.bar == EnvelopeTrip.Bar.GOOGLE_LOCKOUT
        assert trip.detail == {}

    def test_lockout_takes_priority_when_multiple_bars_breach_at_once(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=99.0, rss_mb_per_worker=99999.0, google_lockout=True))
        assert trip.bar == EnvelopeTrip.Bar.GOOGLE_LOCKOUT


class TestBreachPriorityOrder:
    def test_load_takes_priority_over_rss_and_fetch_rate(self, db):
        trip = check_envelope(
            EnvelopeSignals(
                load_avg=99.0,
                rss_mb_per_worker=99999.0,
                fetch_failures_in_window=500,
                fetch_total_in_window=500,
            )
        )
        assert trip.bar == EnvelopeTrip.Bar.HOST_LOAD

    def test_rss_takes_priority_over_fetch_rate(self, db):
        trip = check_envelope(
            EnvelopeSignals(rss_mb_per_worker=99999.0, fetch_failures_in_window=500, fetch_total_in_window=500)
        )
        assert trip.bar == EnvelopeTrip.Bar.RSS


class TestCheckEnvelopeRunIdTagging:
    def test_run_id_is_stored_on_the_trip(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0), run_id="stream-1")
        assert trip.run_id == "stream-1"

    def test_run_id_defaults_to_none(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        assert trip.run_id is None

    def test_trip_id_is_auto_generated_and_unique(self, db):
        trip_a = check_envelope(EnvelopeSignals(load_avg=8.0))
        # acknowledge so the next check_envelope call can trip a fresh row (current_trip's own
        # gating isn't exercised by check_envelope itself - see TestCurrentTrip below - but two
        # independent trip_ids should never collide regardless).
        trip_b = check_envelope(EnvelopeSignals(load_avg=9.0))
        assert trip_a.trip_id != trip_b.trip_id
        assert trip_a.trip_id.startswith("envtrip-")


class TestCurrentTrip:
    def test_none_when_nothing_has_ever_tripped(self, db):
        assert current_trip() is None

    def test_returns_the_open_trip(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        assert current_trip() == trip

    def test_none_after_acknowledgement(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        acknowledge_trip(trip.trip_id, "confirmed load back to normal")
        assert current_trip() is None

    def test_returns_the_most_recent_open_trip_when_several_exist(self, db):
        """
        `current_trip` is `order_by("-tripped_at").first()` - of SEVERAL simultaneously-open trips
        it must return the NEWEST. Two things this test used to get wrong, both fixed here:

          1. It fed `rss_mb_per_worker=600.0`, a literal chosen to clear the RSS ceiling back when
             that ceiling was 512. 70225df8 raised it to 768, so `check_envelope` returned None and
             `second` was None - and because the trip it failed to create was also the trip being
             asserted on, the test went VACUOUS rather than red (`current_trip()` was None too, so
             `None == None` passed). The signal is now derived from the ceiling, as ea72abf7 already
             did for this file's other RSS tests.
          2. It acknowledged `first` before creating `second`, so only ONE trip was ever open and
             the ordering the test is named for was never exercised - it would still have passed
             against a `current_trip` that returned the OLDEST open trip. Both trips now stay open.

        (The acknowledged-then-newly-tripped case that the old body actually covered is kept, under
        its own name, as `test_an_acknowledged_trip_does_not_shadow_a_later_one` below.)
        """
        first = check_envelope(EnvelopeSignals(load_avg=8.0))
        second = check_envelope(EnvelopeSignals(rss_mb_per_worker=RSS_MB_PER_WORKER_CEILING + 0.1))
        assert first is not None and second is not None
        assert EnvelopeTrip.objects.filter(acknowledged_at__isnull=True).count() == 2
        assert second.tripped_at > first.tripped_at
        assert current_trip() == second

    def test_an_acknowledged_trip_does_not_shadow_a_later_one(self, db):
        first = check_envelope(EnvelopeSignals(load_avg=8.0))
        acknowledge_trip(first.trip_id, "resolved")
        second = check_envelope(EnvelopeSignals(rss_mb_per_worker=RSS_MB_PER_WORKER_CEILING + 0.1))
        assert second is not None
        assert current_trip() == second

    def test_scoped_to_run_id_but_still_gated_by_an_unscoped_trip(self, db):
        """An unscoped (run_id=None) open trip still gates a scoped lookup - matches
        enforce_dry_run_precondition's own 'scope=None on the caller side matches any scoped or
        unscoped row' convention, applied here in the opposite direction (an unscoped ROW still
        matches a scoped caller query)."""
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))  # run_id=None
        assert current_trip(run_id="stream-1") == trip

    def test_scoped_lookup_ignores_a_different_run_ids_trip(self, db):
        check_envelope(EnvelopeSignals(load_avg=8.0), run_id="stream-other")
        assert current_trip(run_id="stream-1") is None

    def test_scoped_lookup_finds_its_own_run_ids_trip(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0), run_id="stream-1")
        assert current_trip(run_id="stream-1") == trip


class TestAcknowledgeTrip:
    def test_sets_acknowledged_at_and_note(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        acknowledged = acknowledge_trip(trip.trip_id, "host load confirmed back under 3.0")
        assert acknowledged.acknowledged_at is not None
        assert acknowledged.acknowledged_note == "host load confirmed back under 3.0"

    def test_raises_does_not_exist_for_an_unknown_trip_id(self, db):
        with pytest.raises(EnvelopeTrip.DoesNotExist):
            acknowledge_trip("envtrip-does-not-exist", "note")

    def test_raises_value_error_when_already_acknowledged(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        acknowledge_trip(trip.trip_id, "first ack")
        with pytest.raises(ValueError, match="already acknowledged"):
            acknowledge_trip(trip.trip_id, "second ack")

    def test_a_double_acknowledge_does_not_overwrite_the_first_notes(self, db):
        trip = check_envelope(EnvelopeSignals(load_avg=8.0))
        acknowledge_trip(trip.trip_id, "first ack")
        try:
            acknowledge_trip(trip.trip_id, "second ack")
        except ValueError:
            pass
        trip.refresh_from_db()
        assert trip.acknowledged_note == "first ack"
