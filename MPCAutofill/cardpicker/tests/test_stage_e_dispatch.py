"""
Tests for cardpicker.stage_e_dispatch - Stage E Phase 2's streaming dispatch loop
(docs/proposals/stage-e-streaming.md, docs/features/stage-e-operations.md's "Phase 2" section).

No network calls, no live image fetch - `fetch_card_image_bytes`/`compute_card_evidence` are
monkeypatched at their SOURCE module (`cardpicker.image_cdn_fetch`/`cardpicker.image_evidence`),
never at `cardpicker.stage_e_dispatch` itself, because `_run_stage_c` imports both lazily (inside
the function body, module docstring's own "avoid a hard import-time dependency" convention) - a
patch applied to the source module before the call is what a fresh `from ... import ...` inside the
function body actually observes. `persist_evidence` itself is left REAL (unmocked) in every test
below - it's a small, already-tested, non-network function, and exercising it for real is what
proves ImageEvidence rows actually land, matching `_evidence()`'s own convention in
`test_local_calculate_verdicts.py`.
"""

import io
from typing import Any

import psycopg2
import pytest
from PIL import Image

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from cardpicker import stage_e_dispatch
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_evidence import ExtractionResult
from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_KEYS,
)
from cardpicker.management.commands.stream_backstop_sweep import (
    _next_stage_d_backlog_ids,
)
from cardpicker.models import (
    CardPrintingTag,
    EnvelopeTrip,
    ImageEvidence,
    PilotRunLedger,
    PrintingTagStatus,
    StageESweepCursor,
    StageEThrottleCounter,
    VoteSource,
)
from cardpicker.operating_envelope import (
    FETCH_FAILURE_WINDOW,
    acknowledge_trip,
    check_envelope,
    current_trip,
)
from cardpicker.stage_e_concurrency import _LOCK_NAMESPACE
from cardpicker.stage_e_dispatch import (
    _FetchOutcomeWindow,
    _select_micro_batch,
    dispatch_for_card,
    dispatch_micro_batch,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    ImageEvidenceFactory,
)

STREAMING_ON = override_settings(STAGE_E_STREAMING_ENABLED=True)


@pytest.fixture(autouse=True)
def _reset_fetch_failure_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rolling fetch-outcome window (`stage_e_dispatch._window`) is a process-local module
    singleton spanning a worker process's whole uptime by design (module docstring) - reset it
    before every test in this file so no test observes another's fetch outcomes."""
    monkeypatch.setattr(stage_e_dispatch, "_window", _FetchOutcomeWindow())


def _png_bytes() -> bytes:
    """A tiny, genuinely-decodable PNG - `_run_stage_c` calls the real `PIL.Image.open` on
    whatever `fetch_card_image_bytes` returns before handing it to `compute_card_evidence` (which
    is separately stubbed below), so this needs to be real image bytes, not an arbitrary literal."""
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


def _stub_compute_card_evidence_ok(**field_overrides: Any):
    """Builds a stand-in for `cardpicker.image_evidence.compute_card_evidence` that returns an
    `ExtractionResult` carrying every Stage C manifest key (so the resume filter treats the card as
    fully processed after one pass) plus whatever join-key-relevant fields the caller wants to
    steer Stage D's own verdict."""

    def _stub(
        card_id: int, content_hash, image, fetch_latency_ms=0.0, profile=None, short_circuit=None, known_set_codes=None
    ):
        fields = {
            "fetch_ok": True,
            "collector_line_raw_text": "",
            "collector_line_set_code": "",
            "collector_line_collector_number": "",
            "legal_line_proxy_marker_detected": False,
            "symbol_phash": None,
        }
        fields.update(field_overrides)
        return ExtractionResult(
            card_id=card_id,
            content_hash=content_hash,
            fields=fields,
            extractor_versions={key: f"{key}-v1" for key in MANIFEST_EXTRACTOR_KEYS},
        )

    return _stub


def _install_stage_c_stub(monkeypatch: pytest.MonkeyPatch, fetch_result: Any = b"", **field_overrides: Any) -> None:
    import cardpicker.image_cdn_fetch as image_cdn_fetch_module
    import cardpicker.image_evidence as image_evidence_module

    if callable(fetch_result):
        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", fetch_result)
    else:
        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: fetch_result)
    monkeypatch.setattr(
        image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence_ok(**field_overrides)
    )


class TestDefaultOff:
    def test_disabled_by_default_returns_disabled_status(self, db: Any) -> None:
        outcome = dispatch_micro_batch(card_ids=[1])
        assert outcome.status == "disabled"
        assert PilotRunLedger.objects.count() == 0
        assert EnvelopeTrip.objects.count() == 0

    def test_dispatch_for_card_is_a_silent_no_op_when_disabled(self, db: Any) -> None:
        card = CardFactory(content_phash=42)
        dispatch_for_card(card.pk, "card-create")
        assert PilotRunLedger.objects.count() == 0

    def test_backstop_sweep_is_a_no_op_when_disabled(self, db: Any, capsys: pytest.CaptureFixture) -> None:
        call_command("stream_backstop_sweep")
        assert PilotRunLedger.objects.count() == 0
        assert "no-op" in capsys.readouterr().out


class TestEnvelopeTripHaltsAndNoSelfResume:
    @STREAMING_ON
    def test_a_breached_envelope_halts_before_any_work_and_records_a_trip(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=42)
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=8.0),
        )

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "halted-new-trip"
        assert outcome.trip_id is not None
        trip = EnvelopeTrip.objects.get(trip_id=outcome.trip_id)
        assert trip.bar == EnvelopeTrip.Bar.HOST_LOAD
        # halted BEFORE any ledger row/Stage C/D work - a halted dispatch never partially starts.
        assert PilotRunLedger.objects.count() == 0
        assert ImageEvidence.objects.count() == 0

    @STREAMING_ON
    def test_an_open_trip_refuses_dispatch_even_with_healthy_signals_no_self_resume(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=42)
        open_trip = check_envelope(stage_e_dispatch.EnvelopeSignals(load_avg=9.0))
        assert open_trip is not None
        # Every signal is now healthy - the trip alone must still gate dispatch (no self-resume).
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=0.1),
        )

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "halted-open-trip"
        assert outcome.trip_id == open_trip.trip_id
        assert PilotRunLedger.objects.count() == 0
        open_trip.refresh_from_db()
        assert open_trip.acknowledged_at is None  # this module never clears a trip itself

    @STREAMING_ON
    def test_dispatch_resumes_only_after_an_explicit_acknowledge(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=42)
        _full_evidence(card)  # already Stage-C-complete, isolates this to "did dispatch proceed"
        trip = check_envelope(stage_e_dispatch.EnvelopeSignals(load_avg=9.0))
        assert trip is not None
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=0.1),
        )

        still_halted = dispatch_micro_batch(card_ids=[card.pk])
        assert still_halted.status == "halted-open-trip"

        acknowledge_trip(trip.trip_id, "load confirmed back to normal")
        resumed = dispatch_micro_batch(card_ids=[card.pk])
        assert resumed.status in ("completed", "empty")
        assert current_trip() is None


class TestFetchFailureWindowSizing:
    def test_window_maxlen_matches_the_ratified_500_constant(self) -> None:
        window = _FetchOutcomeWindow()
        assert window._window.maxlen == FETCH_FAILURE_WINDOW == 500

    def test_window_caps_at_500_and_evicts_oldest(self) -> None:
        window = _FetchOutcomeWindow()
        for _ in range(500):
            window.record(success=False)
        failures, total = window.failures_and_total()
        assert (failures, total) == (500, 500)

        window.record(success=True)  # the 501st push evicts the oldest (a failure)
        failures, total = window.failures_and_total()
        assert total == 500  # capped, never grows past the ratified window size
        assert failures == 499  # one failure evicted, replaced by a success

    def test_window_feeds_check_envelope_at_exactly_the_ratified_rate(self, db: Any) -> None:
        """Ties the window's own sizing directly to operating_envelope's ratified >1%-over-500
        math (docs/proposals/stage-e-streaming.md §10(a)) - not just that this module's deque is
        sized 500, but that a real 500-card window built via this module trips (or doesn't) exactly
        where the primitive says it should."""
        window = _FetchOutcomeWindow()
        for _ in range(494):
            window.record(success=True)
        for _ in range(6):
            window.record(success=False)  # 6/500 = 1.2% > 1% ceiling
        failures, total = window.failures_and_total()
        signals = stage_e_dispatch.EnvelopeSignals(fetch_failures_in_window=failures, fetch_total_in_window=total)
        trip = check_envelope(signals)
        assert trip is not None
        assert trip.bar == EnvelopeTrip.Bar.FETCH_FAILURE_RATE

    def test_exactly_5_of_500_does_not_trip(self, db: Any) -> None:
        window = _FetchOutcomeWindow()
        for _ in range(495):
            window.record(success=True)
        for _ in range(5):
            window.record(success=False)  # exactly 1.0% - the ceiling itself, not a breach
        failures, total = window.failures_and_total()
        signals = stage_e_dispatch.EnvelopeSignals(fetch_failures_in_window=failures, fetch_total_in_window=total)
        assert check_envelope(signals) is None


def _full_evidence(card, **overrides: Any) -> ImageEvidence:
    """A CURRENT ImageEvidence row carrying every Stage C manifest key - makes Stage C's own resume
    filter treat this card as already-done, isolating a test to the Stage D leg (or to pure
    dispatch-gating behaviour) without needing to mock the fetch/compute chain at all."""
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions={key: f"{key}-v1" for key in MANIFEST_EXTRACTOR_KEYS},
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
        legal_line_proxy_marker_detected=False,
        symbol_phash=None,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestSelectMicroBatch:
    """Issue #458 - `_select_micro_batch`'s backlog fill now walks `StageESweepCursor.position`
    through the pk space in bounded chunks instead of anti-joining the whole catalog every call
    (see that function's own docstring for the full design). Seed handling itself (dedupe,
    seed-first, early return once the seed alone fills the batch) is untouched by #458 and is
    covered by the first two tests below exactly as before."""

    def test_seed_cards_come_first_and_are_deduplicated(self, db: Any) -> None:
        card = CardFactory(content_phash=42)
        _full_evidence(card)
        batch = _select_micro_batch([card.pk, card.pk], batch_size=5)
        assert batch == [card.pk]

    def test_seed_alone_already_at_batch_size_skips_the_backlog_query_and_the_cursor_entirely(self, db: Any) -> None:
        seed = CardFactory(content_phash=1)
        CardFactory(content_phash=2)  # would be backlog-eligible, but batch_size=1 leaves no room
        batch = _select_micro_batch([seed.pk], batch_size=1)
        assert batch == [seed.pk]
        # the cursor is never touched (not even created) when the seed alone fills the batch.
        assert StageESweepCursor.objects.count() == 0

    def test_backlog_fill_skips_fully_processed_cards_and_advances_the_cursor_to_the_last_examined_pk(
        self, db: Any
    ) -> None:
        done = CardFactory(content_phash=1)
        _full_evidence(done)
        pending_a = CardFactory(content_phash=2)
        pending_b = CardFactory(content_phash=3)
        no_hash = CardFactory(content_phash=None)

        # batch_size=2 is filled exactly by the two pending cards, so this dispatch stops there
        # rather than continuing on to hit (and wrap on) the end of the pk space - wrap-around is
        # its own separate scenario, covered below.
        batch = _select_micro_batch([], batch_size=2)

        assert done.pk not in batch
        assert no_hash.pk not in batch
        assert set(batch) == {pending_a.pk, pending_b.pk}
        # the cursor advances to the last pk this dispatch actually examined - `pending_b` is the
        # highest-pk candidate (content_phash is not None) in the single chunk this call verified.
        cursor = StageESweepCursor.objects.get()
        assert cursor.position == pending_b.pk
        assert cursor.wrap_count == 0

    def test_backlog_fill_is_bounded_by_batch_size(self, db: Any) -> None:
        for _ in range(5):
            CardFactory(content_phash=100)
        batch = _select_micro_batch([], batch_size=2)
        assert len(batch) == 2

    def test_wrap_around_resets_position_and_increments_wrap_count_returning_an_empty_batch(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _full_evidence(card)  # already processed - nothing left to sweep past it
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_C, position=card.pk)  # cursor at the end

        batch = _select_micro_batch([], batch_size=5)

        assert batch == []  # empty is a valid outcome (mirrors dispatch_micro_batch's own "empty")
        cursor = StageESweepCursor.objects.get()
        assert cursor.position == 0
        assert cursor.wrap_count == 1

    def test_wrap_around_stops_this_dispatch_rather_than_resuming_from_zero_leaving_a_partial_batch(
        self, db: Any
    ) -> None:
        seed = CardFactory(content_phash=1)
        _full_evidence(seed)
        pending = CardFactory(content_phash=2)  # would be found immediately if this wrapped AND
        # kept scanning from 0 in the same call - the binding rule is that it must NOT, so this
        # dispatch's own batch must come back with the seed only, not [seed, pending].
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_C, position=pending.pk)

        batch = _select_micro_batch([seed.pk], batch_size=5)

        assert batch == [seed.pk]  # the seed only - partial, never resumed from 0 in this call
        cursor = StageESweepCursor.objects.get()
        assert cursor.position == 0
        assert cursor.wrap_count == 1

    def test_cas_race_discards_the_lost_chunk_and_retries_until_it_wins(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = [CardFactory(content_phash=i) for i in range(1, 4)]
        real_try_advance = StageESweepCursor.try_advance
        calls = {"n": 0}

        def _flaky_try_advance(name: str, from_position: int, to_position: int) -> bool:
            calls["n"] += 1
            if calls["n"] <= 2:
                return False  # simulate two concurrent dispatches winning the CAS race first
            return real_try_advance(name, from_position, to_position)

        monkeypatch.setattr(StageESweepCursor, "try_advance", staticmethod(_flaky_try_advance))

        batch = _select_micro_batch([], batch_size=10)

        assert calls["n"] == 3  # 2 losses + 1 winning attempt - well within the retry budget
        assert set(batch) == {c.pk for c in pending}

    def test_cas_race_gives_up_after_three_retries_and_returns_whatever_it_already_has(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for i in range(1, 4):
            CardFactory(content_phash=i)
        calls = {"n": 0}

        def _always_loses(name: str, from_position: int, to_position: int) -> bool:
            calls["n"] += 1
            return False

        monkeypatch.setattr(StageESweepCursor, "try_advance", staticmethod(_always_loses))

        batch = _select_micro_batch([], batch_size=10)

        assert batch == []  # never won a claim, so never verified a single candidate
        assert calls["n"] == 4  # 1 initial attempt + 3 retries, then this dispatch stops

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=2, STAGE_E_SELECTION_SCAN_CAP=6)
    def test_scan_cap_limits_examined_candidates_and_returns_a_partial_batch(self, db: Any) -> None:
        for i in range(1, 5):
            card = CardFactory(content_phash=i)
            _full_evidence(card)  # 4 already-processed cards - the first 2 chunks of 2
        eligible = CardFactory(content_phash=100)  # 5th candidate - inside the cap, genuinely eligible
        trailing_processed = CardFactory(content_phash=200)
        _full_evidence(trailing_processed)  # 6th and last candidate this dispatch examines
        beyond_cap = CardFactory(content_phash=300)  # 7th candidate - past SCAN_CAP=6, never reached

        batch = _select_micro_batch([], batch_size=5)

        assert batch == [eligible.pk]  # only the one eligible card inside the examined window
        assert beyond_cap.pk not in batch
        cursor = StageESweepCursor.objects.get()
        # exactly SCAN_CAP=6 candidates examined (3 chunks of CHUNK_SIZE=2), never more.
        assert cursor.position == trailing_processed.pk

    def test_selection_query_count_is_flat_regardless_of_catalog_size(self, db: Any) -> None:
        """Bounded queries (issue #458's own acceptance bar): the query COUNT `_select_micro_batch`
        issues must depend only on batch_size/CHUNK_SIZE/SCAN_CAP, never on how many rows already
        exist in `cardpicker_card` - asserted directly via query counts, not timing."""
        for i in range(1, 21):
            CardFactory(content_phash=i)  # a 20-card catalog

        with CaptureQueriesContext(connection) as small_catalog_queries:
            small_batch = _select_micro_batch([], batch_size=5)
        assert len(small_batch) == 5

        StageESweepCursor.objects.all().delete()  # reset the cursor for a fair second measurement
        for i in range(21, 421):
            CardFactory(content_phash=i)  # grow the catalog by 20x

        with CaptureQueriesContext(connection) as large_catalog_queries:
            large_batch = _select_micro_batch([], batch_size=5)
        assert len(large_batch) == 5

        assert len(large_catalog_queries.captured_queries) == len(small_catalog_queries.captured_queries)


class TestEndToEndMicroBatch:
    """event -> batch -> Stage C extraction + Stage D calculators invoked -> counters written."""

    @STREAMING_ON
    def test_dispatch_for_card_runs_the_full_conveyor(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _install_stage_c_stub(
            monkeypatch,
            fetch_result=_png_bytes(),
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        dispatch_for_card(card.pk, "card-create")

        evidence = ImageEvidence.objects.get(card=card)
        assert MANIFEST_EXTRACTOR_KEYS.issubset(evidence.extractor_versions.keys())

        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        assert vote.is_no_match is False
        # a single VoteSource.OCR vote can never resolve a card alone (the human-backed gate).
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

        ledger = PilotRunLedger.objects.get(command="stage_e_streaming_dispatch")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["trigger_reason"] == "card-create"
        assert ledger.counters["stage_c_completed"] == 1
        assert ledger.counters["stage_d_join_key_votes"] == 1
        assert "peak_rss_mb" in ledger.counters
        assert "elapsed_s" in ledger.counters

    @STREAMING_ON
    def test_a_card_with_current_evidence_skips_stage_c_but_still_runs_stage_d(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        def _fail_if_called(card, dpi=None):
            raise AssertionError("Stage C should have been skipped - evidence is already current")

        _install_stage_c_stub(monkeypatch, fetch_result=_fail_if_called)

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "completed"
        assert outcome.stage_c_completed == 0
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk


class TestConcurrencyCapIntegration:
    """The concurrency-cap companion change (`cardpicker.stage_e_concurrency`), exercised through
    the REAL, post-#448 `dispatch_micro_batch` body - not just the module-level unit coverage in
    `test_stage_e_concurrency.py`. A raw, independent `psycopg2` connection holds every available
    slot (standing in for another concurrent dispatch on a separate django-q worker process, the
    same "genuinely separate session" discipline `test_stage_e_concurrency.py`'s own module
    docstring establishes - Postgres session-level advisory locks are re-entrant within one
    session, so simulating a second dispatcher via Django's own connection would be a false test)."""

    def _raw_connection_holding_every_slot(self, cap: int) -> "psycopg2.extensions.connection":
        connection.ensure_connection()
        raw = psycopg2.connect(**connection.get_connection_params())
        raw.autocommit = True
        with raw.cursor() as cursor:
            for slot in range(cap):
                cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, slot])
                (acquired,) = cursor.fetchone()
                assert acquired is True, f"test setup failed to claim slot {slot}"
        return raw

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_dispatch_is_throttled_when_the_only_slot_is_already_held(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")

        def _fail_if_called(card, dpi=None):
            raise AssertionError("Stage C must never run once the concurrency cap has throttled")

        _install_stage_c_stub(monkeypatch, fetch_result=_fail_if_called)

        raw = self._raw_connection_holding_every_slot(cap=1)
        try:
            outcome = dispatch_micro_batch(card_ids=[card.pk])
        finally:
            raw.close()  # auto-releases the advisory lock, same crash-safety property tested above

        assert outcome.status == "throttled-concurrency-cap"
        # a throttled dispatch never partially starts, matching halted-open-trip/halted-new-trip's
        # own convention - no ledger row, no evidence, no vote.
        assert PilotRunLedger.objects.count() == 0
        assert ImageEvidence.objects.count() == 0
        assert CardPrintingTag.objects.count() == 0
        # observability signal (Tron gate anomaly 4, 2026-07-25) - the ONE durable, queryable
        # record that this throttle happened, since no ledger row was written above.
        counter = StageEThrottleCounter.objects.get()
        assert counter.count == 1
        assert counter.last_throttled_at is not None

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_dispatch_proceeds_normally_once_the_slot_is_released(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        raw = self._raw_connection_holding_every_slot(cap=1)
        raw.close()  # released before dispatching - the cap must not still be considered "held"

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "completed"
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk


class TestGoogleLockoutMidBatch:
    @STREAMING_ON
    def test_lockout_stops_stage_c_trips_the_envelope_and_refuses_the_next_dispatch(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card_a = CardFactory(name="Card A", content_phash=1)
        card_b = CardFactory(name="Card B", content_phash=2)

        def _lockout_fetch(card, dpi=None):
            raise GoogleFetchLockoutError("locked out")

        _install_stage_c_stub(monkeypatch, fetch_result=_lockout_fetch)

        outcome = dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk])

        assert outcome.status == "completed-with-trip"
        assert outcome.trip_id is not None
        trip = EnvelopeTrip.objects.get(trip_id=outcome.trip_id)
        assert trip.bar == EnvelopeTrip.Bar.GOOGLE_LOCKOUT
        assert ImageEvidence.objects.count() == 0  # lockout hit before any card's fetch succeeded

        ledger = PilotRunLedger.objects.get(run_id=outcome.run_id)
        assert ledger.counters["lockout_trip_id"] == trip.trip_id

        # no self-resume: the next dispatch call refuses outright.
        refused = dispatch_micro_batch(card_ids=[card_a.pk])
        assert refused.status == "halted-open-trip"


class TestKillSafetyResumeContract:
    """Extends the batch kill-test's own assertions (scripts/ops/crash_drill.sh, docs/proposals/
    stage-e-streaming.md §7) to a streamed micro-batch: a mid-batch crash leaves a truthful FAILED
    ledger row and every already-committed card durably written, and a re-invocation over the same
    (or an overlapping) card set completes idempotently with zero manual cleanup."""

    @STREAMING_ON
    def test_mid_batch_crash_leaves_truthful_ledger_and_durable_partial_work(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card_a = CardFactory(name="Card A", content_phash=1)
        card_b = CardFactory(name="Card B", content_phash=2)
        card_c = CardFactory(name="Card C", content_phash=3)
        calls = {"n": 0}

        def _fetch_crashes_on_second_card(card, dpi=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated kill mid-batch")
            return _png_bytes()

        _install_stage_c_stub(monkeypatch, fetch_result=_fetch_crashes_on_second_card)

        with pytest.raises(RuntimeError, match="simulated kill mid-batch"):
            dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk, card_c.pk], run_id="kill-drill-1")

        ledger = PilotRunLedger.objects.get(run_id="kill-drill-1")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert "RuntimeError" in ledger.counters["failure_reason"]

        # durable partial work: the first card's evidence committed before the crash.
        assert ImageEvidence.objects.filter(card=card_a).count() == 1
        # nothing committed for the card that crashed or anything after it in this pass.
        assert ImageEvidence.objects.filter(card=card_b).count() == 0
        assert ImageEvidence.objects.filter(card=card_c).count() == 0

        # RESUME: fix the fault and re-invoke over the SAME card set - zero manual cleanup.
        _install_stage_c_stub(monkeypatch, fetch_result=_png_bytes())
        resumed = dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk, card_c.pk], run_id="kill-drill-2")

        assert resumed.status == "completed"
        # idempotent re-entry: card_a's evidence is not duplicated, despite being re-included.
        assert ImageEvidence.objects.filter(card=card_a).count() == 1
        assert ImageEvidence.objects.filter(card=card_b).count() == 1
        assert ImageEvidence.objects.filter(card=card_c).count() == 1
        resumed_ledger = PilotRunLedger.objects.get(run_id="kill-drill-2")
        assert resumed_ledger.status == PilotRunLedger.Status.COMPLETED
        # only the two cards the crashed run never reached needed real Stage C work this time.
        assert resumed_ledger.counters["stage_c_completed"] == 2


class TestConcurrentDispatchVoteCollision:
    """Regression for the VOTE-COLLISION half of the Stage E Phase 2 shakedown's first live
    incident (failed run_ids stage-e-stream-20260724T2144*, seven losers + the one winner = eight
    total concurrent dispatches, exactly Q_CLUSTER["workers"]=8) - see
    `local_calculate_verdicts._split_new_printing_tag_votes`' own docstring for the full
    root-cause writeup, INCLUDING why this is a separate failure from the same run's
    `envtrip-20260724T214616-be6e5db9` host-load envelope trip (a resource-contention problem this
    change does not address - see that docstring's own "SEPARATE FAILURE" section). Two CONCURRENT
    `dispatch_micro_batch` calls scoped to an overlapping card set (django-q2 runs 8 workers; the
    backstop sweep can also overlap an event trigger) used to abort a WHOLE micro-batch with an
    `IntegrityError` the instant the losing dispatch's own Stage D `bulk_create` raced a winner's.
    Reproduced here at the full conveyor level (not just the calculator level
    `test_local_calculate_verdicts.py` covers) by seeding the winner's vote directly and
    confirming the loser's own `dispatch_micro_batch` call completes rather than raising."""

    @STREAMING_ON
    def test_a_losing_race_completes_instead_of_raising_integrity_error(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cardpicker.local_calculate_verdicts as local_calculate_verdicts_module

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_collector_number="999")  # doesn't match "158" -> is_no_match=True
        monkeypatch.setattr(
            local_calculate_verdicts_module,
            "_eligible_cards_queryset",
            lambda *args, **kwargs: local_calculate_verdicts_module.Card.objects.filter(pk=card.pk),
        )

        # the WINNER of the race: another (concurrent, not modeled here) dispatch's own vote
        # already landed for this exact (card, anonymous_id) pair.
        CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        outcome = dispatch_micro_batch(card_ids=[card.pk])  # must not raise IntegrityError

        assert outcome.status == "completed"
        assert outcome.stage_d_join_key_already_voted == 1
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).count() == 1

        ledger = PilotRunLedger.objects.get(run_id=outcome.run_id)
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["stage_d_join_key_already_voted"] == 1


class TestBackstopSweep:
    @STREAMING_ON
    def test_sweep_processes_the_stage_d_backlog_and_is_idempotent_on_rerun(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        call_command("stream_backstop_sweep")
        first_output = capsys.readouterr().out
        assert "batches_dispatched=1" in first_output or "stage_d_votes_or_routes=1" in first_output

        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        votes_after_first_run = CardPrintingTag.objects.count()

        call_command("stream_backstop_sweep")
        second_output = capsys.readouterr().out
        assert "batches_dispatched=0" in second_output

        assert CardPrintingTag.objects.count() == votes_after_first_run  # idempotent - no dup votes

    @STREAMING_ON
    def test_sweep_stops_on_an_envelope_halt(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        CardFactory(name="Some Card", content_phash=42)
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=9.0),
        )

        call_command("stream_backstop_sweep")

        assert EnvelopeTrip.objects.filter(bar=EnvelopeTrip.Bar.HOST_LOAD).count() == 1
        assert PilotRunLedger.objects.count() == 0  # halted before any batch ledger row was written

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_sweep_stops_on_a_throttled_concurrency_cap_without_looping(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        """Tron gate defect fix: pre-fix, "throttled-concurrency-cap" matched neither
        `_HALT_STATUSES` nor "empty" and fell through to `batches_dispatched += 1` with an immediate
        re-entry into `dispatch_micro_batch` - a hot, backoff-free loop up to `--max-batches`,
        precisely when the host is already saturated, reporting a success-shaped
        `batches_dispatched=N` for a sweep that did nothing. Mirrors
        `TestConcurrencyCapIntegration`'s own "genuinely separate session" discipline (that class's
        own docstring) - a raw, independent `psycopg2` connection holds the only slot, standing in
        for another concurrent dispatch (a django-q worker, or the event trigger racing this same
        sweep) - reusing the SAME session for both would be a false test (re-entrant advisory
        locks, this file's own `stage_e_concurrency` test module docstring)."""
        CardFactory(name="Some Card", content_phash=42)

        connection.ensure_connection()
        raw = psycopg2.connect(**connection.get_connection_params())
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, 0])
            (acquired,) = cursor.fetchone()
            assert acquired is True, "test setup failed to claim the only slot"
        try:
            call_command("stream_backstop_sweep", "--max-batches", "5")
        finally:
            raw.close()  # auto-releases the advisory lock, same crash-safety property tested above

        output = capsys.readouterr().out
        assert "sweep stopped: dispatch slots saturated (throttled-concurrency-cap)" in output
        # exactly one occurrence - proves the loop actually STOPPED on the first throttled outcome
        # rather than re-entering dispatch_micro_batch up to --max-batches=5 with no backoff.
        assert output.count("sweep stopped: dispatch slots saturated") == 1
        assert "batches_dispatched=0" in output
        assert "stopped_reason=throttled-concurrency-cap" in output
        # no ledger row - the throttled attempt never started real work, matching a halt's own
        # convention (TestConcurrencyCapIntegration's own assertion for dispatch_micro_batch
        # directly).
        assert PilotRunLedger.objects.count() == 0


def _voted_card(content_phash: int = 1) -> Any:
    """A Stage-C-complete card carrying a JOIN_KEY_ANONYMOUS_ID vote already - INELIGIBLE for the
    Stage D backlog (`_eligible_cards_queryset`'s own `.exclude(printing_tags__anonymous_id=...)`),
    used across `TestStageDBacklog`/`TestBackstopSweepBacklogBExhaustedVsCapHit` below to build a
    "not what we're looking for" candidate that a cursor walk must still examine (and skip)
    without mistaking it for backlog exhaustion."""
    card = CardFactory(content_phash=content_phash)
    _full_evidence(card)
    CardPrintingTag.objects.create(
        card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
    )
    return card


class TestSweepCursorMigration:
    """Issue #460 - migration `0083_stageesweepcursor_keyed` renames the pre-#460 singleton row
    (`singleton_key=1`, issue #458) to the keyed `stage_c` row, `position`/`wrap_count` preserved.
    Exercised via `MigrationExecutor` directly (migrate back to 0082, create the pre-#460 row
    shape, migrate forward to 0083, assert the row survived under its new key) - the one-time
    transition every existing deployment's own database goes through."""

    def test_existing_singleton_row_becomes_the_stage_c_row_with_position_preserved(self, db: Any) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate([("cardpicker", "0082_stageesweepcursor")])
        old_apps = executor.loader.project_state(("cardpicker", "0082_stageesweepcursor")).apps
        old_cursor_model = old_apps.get_model("cardpicker", "StageESweepCursor")
        old_cursor_model.objects.create(singleton_key=1, position=777, wrap_count=3)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([("cardpicker", "0083_stageesweepcursor_keyed")])

        new_apps = executor.loader.project_state(("cardpicker", "0083_stageesweepcursor_keyed")).apps
        new_cursor_model = new_apps.get_model("cardpicker", "StageESweepCursor")
        row = new_cursor_model.objects.get()
        assert row.name == "stage_c"
        assert row.position == 777
        assert row.wrap_count == 3

        # Restore the schema to the latest migration state - this test is the only one in the
        # suite that ever moves the schema backward, so every later test must see it forward again.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


class TestKeyedCursorIsolation:
    """Issue #460 - `StageESweepCursor.STAGE_C`/`STAGE_D` are independent rows; advancing/wrapping
    one must never move the other."""

    def test_advancing_stage_d_never_moves_stage_c(self, db: Any) -> None:
        stage_c = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_C)
        stage_d = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_D)

        assert StageESweepCursor.try_advance(StageESweepCursor.STAGE_D, stage_d.position, 500) is True

        stage_c.refresh_from_db()
        assert stage_c.position == 0
        stage_d.refresh_from_db()
        assert stage_d.position == 500

    def test_advancing_stage_c_never_moves_stage_d(self, db: Any) -> None:
        stage_c = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_C)
        stage_d = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_D)

        assert StageESweepCursor.try_advance(StageESweepCursor.STAGE_C, stage_c.position, 300) is True

        stage_d.refresh_from_db()
        assert stage_d.position == 0
        stage_c.refresh_from_db()
        assert stage_c.position == 300

    def test_wrapping_stage_d_never_touches_stage_cs_wrap_count(self, db: Any) -> None:
        StageESweepCursor.get_cursor(StageESweepCursor.STAGE_C)
        stage_d = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_D)
        StageESweepCursor.try_advance(StageESweepCursor.STAGE_D, stage_d.position, 100)

        assert StageESweepCursor.try_wrap(StageESweepCursor.STAGE_D, 100) is True

        stage_c = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C)
        assert stage_c.wrap_count == 0
        stage_d.refresh_from_db()
        assert stage_d.position == 0
        assert stage_d.wrap_count == 1


class TestStageDBacklog:
    """Issue #460 - `_next_stage_d_backlog_ids` (`stream_backstop_sweep.py`), walking
    `StageESweepCursor.STAGE_D` via the shared `_cursor_chunk_walk` helper
    (`stage_e_dispatch.py`). Mirrors `TestSelectMicroBatch`'s own structure for the Stage C
    cursor, one test per behavior this function's own docstring documents."""

    def test_finds_an_evidence_complete_vote_missing_card_and_advances_the_cursor(self, db: Any) -> None:
        eligible = CardFactory(content_phash=1)
        _full_evidence(eligible)

        # batch_size=1 matches exactly the one candidate available, so this call stops the instant
        # it's found rather than continuing on to hit (and wrap on) the end of the pk space - wrap
        # while carrying an already-found id is its own separate scenario (the CAS-race test below).
        ids, exhausted = _next_stage_d_backlog_ids(1)

        assert ids == [eligible.pk]
        assert exhausted is False
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_D)
        assert cursor.position == eligible.pk

    def test_skips_a_card_that_already_has_a_join_key_vote(self, db: Any) -> None:
        voted = _voted_card(content_phash=1)
        pending = CardFactory(content_phash=2)
        _full_evidence(pending)

        ids, exhausted = _next_stage_d_backlog_ids(5)

        assert ids == [pending.pk]
        assert voted.pk not in ids

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=2, STAGE_E_SELECTION_SCAN_CAP=2)
    def test_scan_cap_hit_with_backlog_still_unscanned_returns_exhausted_false(self, db: Any) -> None:
        # Two already-voted (ineligible) cards fill the SCAN_CAP=2 examined window this call
        # spends - a genuinely eligible card sits just past it, unscanned.
        _voted_card(content_phash=1)
        _voted_card(content_phash=2)
        beyond_cap = CardFactory(content_phash=100)
        _full_evidence(beyond_cap)

        ids, exhausted = _next_stage_d_backlog_ids(5)

        assert ids == []
        assert exhausted is False  # cap-hit-empty, NOT exhaustion - beyond_cap is still unscanned
        assert beyond_cap.pk not in ids

    def test_wrap_around_with_nothing_eligible_returns_exhausted_true(self, db: Any) -> None:
        _voted_card(content_phash=1)

        ids, exhausted = _next_stage_d_backlog_ids(5)

        assert ids == []
        assert exhausted is True
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_D)
        assert cursor.position == 0
        assert cursor.wrap_count == 1

    def test_cas_race_on_the_stage_d_cursor_discards_the_lost_chunk_and_retries_until_it_wins(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mirrors `TestSelectMicroBatch.test_cas_race_discards_the_lost_chunk_and_retries_until_
        it_wins` for the Stage C cursor - same shared `_cursor_chunk_walk`, exercised here against
        the Stage D cursor instead, proving the CAS retry logic isn't accidentally Stage-C-specific."""
        pending = []
        for i in range(1, 4):
            card = CardFactory(content_phash=i)
            _full_evidence(card)
            pending.append(card)
        real_try_advance = StageESweepCursor.try_advance
        calls = {"n": 0}

        def _flaky_try_advance(name: str, from_position: int, to_position: int) -> bool:
            calls["n"] += 1
            if calls["n"] <= 2:
                return False  # simulate two concurrent dispatches winning the CAS race first
            return real_try_advance(name, from_position, to_position)

        monkeypatch.setattr(StageESweepCursor, "try_advance", staticmethod(_flaky_try_advance))

        ids, exhausted = _next_stage_d_backlog_ids(10)

        assert calls["n"] == 3  # 2 losses + 1 winning attempt - well within the retry budget
        assert set(ids) == {c.pk for c in pending}
        assert exhausted is True  # the walk reached (and wrapped past) the end of the pk space


class TestBackstopSweepBacklogBExhaustedVsCapHit:
    """Issue #460 §4 - the sweep loop's own distinction between backlog (b)'s `exhausted=True`
    (break) and a cap-hit-empty result (`exhausted=False`, continue to the next batch)."""

    @STREAMING_ON
    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=1, STAGE_E_SELECTION_SCAN_CAP=1)
    def test_sweep_continues_past_a_cap_hit_empty_backlog_b_result_and_still_finds_the_later_card(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        _voted_card(content_phash=1)  # examined and skipped on the sweep's first pass - cap-hit
        card = CardFactory(name="Some Card", content_phash=2)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        call_command("stream_backstop_sweep", "--max-batches", "5")

        output = capsys.readouterr().out
        assert "batches_dispatched=1" in output
        assert "Backlog exhausted - nothing left to dispatch." in output
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk

    @STREAMING_ON
    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=1, STAGE_E_SELECTION_SCAN_CAP=1)
    def test_sweep_stays_bounded_by_max_batches_when_cap_hit_empty_never_resolves(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        # Five already-voted, Stage-C-complete cards - with SCAN_CAP=1 each sweep iteration's own
        # backlog (b) walk examines exactly one of them and comes back cap-hit-empty every time,
        # never reaching the end of the pk space (so never `exhausted`) within the two-batch
        # budget this test allows - proving `range(max_batches)` alone is what stops this loop,
        # not the exhausted/halt/throttle paths.
        for i in range(1, 6):
            _voted_card(content_phash=i)

        call_command("stream_backstop_sweep", "--max-batches", "2")

        output = capsys.readouterr().out
        assert "batches_dispatched=0" in output
        assert "Backlog exhausted" not in output
        assert "Envelope halt" not in output
        assert "sweep stopped" not in output
