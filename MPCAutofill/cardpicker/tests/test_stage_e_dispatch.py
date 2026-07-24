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

import pytest
from PIL import Image

from django.core.management import call_command
from django.test import override_settings

from cardpicker import stage_e_dispatch
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_evidence import ExtractionResult
from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_KEYS,
)
from cardpicker.models import (
    CardPrintingTag,
    EnvelopeTrip,
    ImageEvidence,
    PilotRunLedger,
    PrintingTagStatus,
)
from cardpicker.operating_envelope import (
    FETCH_FAILURE_WINDOW,
    acknowledge_trip,
    check_envelope,
    current_trip,
)
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
    def test_seed_cards_come_first_and_are_deduplicated(self, db: Any) -> None:
        card = CardFactory(content_phash=42)
        _full_evidence(card)
        batch = _select_micro_batch([card.pk, card.pk], batch_size=5)
        assert batch == [card.pk]

    def test_backlog_fills_up_to_batch_size_excluding_already_processed_cards(self, db: Any) -> None:
        done = CardFactory(content_phash=1)
        _full_evidence(done)
        pending_a = CardFactory(content_phash=2)
        pending_b = CardFactory(content_phash=3)
        no_hash = CardFactory(content_phash=None)

        batch = _select_micro_batch([], batch_size=10)

        assert done.pk not in batch
        assert no_hash.pk not in batch
        assert set(batch) == {pending_a.pk, pending_b.pk}

    def test_backlog_fill_is_bounded_by_batch_size(self, db: Any) -> None:
        for _ in range(5):
            CardFactory(content_phash=100)
        batch = _select_micro_batch([], batch_size=2)
        assert len(batch) == 2

    def test_seed_alone_already_at_batch_size_skips_the_backlog_query_entirely(self, db: Any) -> None:
        seed = CardFactory(content_phash=1)
        CardFactory(content_phash=2)  # would be backlog-eligible, but batch_size=1 leaves no room
        batch = _select_micro_batch([seed.pk], batch_size=1)
        assert batch == [seed.pk]


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
