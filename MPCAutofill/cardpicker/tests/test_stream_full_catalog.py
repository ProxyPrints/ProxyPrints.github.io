"""
Tests for `cardpicker.management.commands.stream_full_catalog` (2026-07-28, the full-catalog
streaming driver).

Two styles, mirroring `test_stage_e_shakedown.py`'s own split: driver-loop coverage with
`dispatch_micro_batch` stubbed (to isolate cohort/chunking/flag-plumbing/resume behaviour from any
real Stage C/D work), and real-conveyor coverage exercising the SAME halt/throttle mechanisms
`test_stage_e_dispatch.py`/`test_stage_e_shakedown.py` already prove, plus the load-bearing
"never touches either sweep cursor" property that can only be observed against the real
`_select_micro_batch`.
"""

from typing import Any, List

import psycopg2
import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings

from cardpicker import stage_e_dispatch
from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.management.commands import stream_full_catalog
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
)
from cardpicker.management.commands.stream_full_catalog import (
    deterministic_sample_pks,
    full_catalog_pk_queryset,
)
from cardpicker.models import (
    CardPrintingTag,
    EnvelopeTrip,
    PilotRunLedger,
    StageEFullCatalogCursor,
    StageESweepCursor,
    VoteSource,
)
from cardpicker.operating_envelope import check_envelope
from cardpicker.stage_e_concurrency import _LOCK_NAMESPACE
from cardpicker.stage_e_dispatch import DispatchOutcome
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    ImageEvidenceFactory,
)

STREAMING_ON = override_settings(STAGE_E_STREAMING_ENABLED=True)


class _FakeBulkEntry:
    """Stands in for `printing_metadata_import.BulkDataEntry` - stage 0 only ever reads
    `updated_at` off it."""

    updated_at = "2026-07-28T00:00:00.000Z"


@pytest.fixture(autouse=True)
def _stage_zero_never_touches_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage 0 (issue #513 item 2) runs by DEFAULT on every invocation, so every test in this
    module would otherwise reach Scryfall's /bulk-data API. Patched on the COMMAND module's own
    namespace (it imports these names at import time) to report FRESH, which is stage 0's own
    skip-and-continue path. Tests that care about stage 0 override these; a test that forgets
    still cannot make a network call."""
    monkeypatch.setattr(stream_full_catalog, "_get_default_cards_entry", lambda: _FakeBulkEntry())
    monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: True)
    monkeypatch.setattr(
        stream_full_catalog,
        "import_scryfall_printing_metadata",
        lambda: pytest.fail("stage 0 refreshed when the fixture reported FRESH"),
    )


def _current_full_evidence(card: Any, **overrides: Any) -> Any:
    """A CURRENT, full-manifest ImageEvidence row - i.e. a card BOTH existing drivers would skip
    (`stream_backstop_sweep`'s backlog (a) selector and the conveyor's own already-done check both
    key off exactly this shape). The whole point of this command is that it dispatches such a card
    anyway."""
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
        fetch_ok=True,
        collector_line_raw_text="MOM 158",
        collector_line_set_code="mom",
        collector_line_collector_number="158",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class _RecordingDispatch:
    """Stands in for `dispatch_micro_batch`, recording every call's own kwargs and returning a
    `completed` outcome. Patched onto the COMMAND module's own name (the command does
    `from cardpicker.stage_e_dispatch import dispatch_micro_batch` at import time, so that is the
    binding the driver loop actually calls)."""

    def __init__(self, outcomes: Any = None) -> None:
        self.calls: List[dict] = []
        self._outcomes = list(outcomes) if outcomes is not None else None

    def __call__(self, **kwargs: Any) -> DispatchOutcome:
        self.calls.append(kwargs)
        if self._outcomes:
            return self._outcomes.pop(0)
        return DispatchOutcome(status="completed", run_id=kwargs.get("run_id"), card_ids=list(kwargs["card_ids"]))

    @property
    def dispatched_ids(self) -> List[int]:
        return [pk for call in self.calls for pk in call["card_ids"]]


def _install_recording_dispatch(monkeypatch: pytest.MonkeyPatch, outcomes: Any = None) -> _RecordingDispatch:
    recorder = _RecordingDispatch(outcomes=outcomes)
    monkeypatch.setattr(stream_full_catalog, "dispatch_micro_batch", recorder)
    return recorder


def _install_ok_stage_c_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same source-module-patch discipline `test_stage_e_dispatch.py`/`test_stage_e_shakedown.py`
    establish - `_run_stage_c` imports both lazily inside the function body, so the patch must land
    on the SOURCE module."""
    import io

    from PIL import Image

    from cardpicker.image_evidence import ExtractionResult

    def _png_bytes() -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buffer, format="PNG")
        return buffer.getvalue()

    def _stub_compute(
        card_id: int,
        content_hash: Any,
        image: Any,
        fetch_latency_ms: float = 0.0,
        profile: Any = None,
        short_circuit: Any = None,
        known_set_codes: Any = None,
        md5_checksum: Any = None,
        sha256_checksum: Any = None,
    ) -> Any:
        return ExtractionResult(
            card_id=card_id,
            content_hash=content_hash,
            fields={
                "fetch_ok": True,
                "collector_line_raw_text": "MOM 158",
                "collector_line_set_code": "mom",
                "collector_line_collector_number": "158",
                "legal_line_proxy_marker_detected": False,
                "symbol_phash": None,
            },
            extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
        )

    import cardpicker.image_cdn_fetch as image_cdn_fetch_module
    import cardpicker.image_evidence as image_evidence_module

    monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: _png_bytes())
    monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute)


def _install_sleep_recorder(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    """Observe the throttle backoff SCHEDULE without actually spending it. Patches the command
    module's own `_sleep` indirection rather than `time.sleep`, so no other thread running in this
    test session is affected."""
    waits: List[float] = []
    monkeypatch.setattr(stream_full_catalog, "_sleep", waits.append)
    return waits


def _cards(count: int, start: int = 1) -> List[Any]:
    return [CardFactory(content_phash=i) for i in range(start, start + count)]


class TestCohortIsUnfilteredByEligibility:
    """The defining difference from `stream_backstop_sweep`, whose BOTH selectors are "cards that
    still need work"."""

    @STREAMING_ON
    def test_already_done_cards_are_still_dispatched(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        never_touched = CardFactory(content_phash=1)

        stage_c_done = CardFactory(content_phash=2)
        _current_full_evidence(stage_c_done)

        fully_done = CardFactory(content_phash=3)
        _current_full_evidence(fully_done)
        CardPrintingTag.objects.create(
            card=fully_done,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10")

        # Every card, regardless of how complete its existing Stage C evidence or Stage D votes are.
        assert recorder.dispatched_ids == [never_touched.pk, stage_c_done.pk, fully_done.pk]

    @STREAMING_ON
    def test_a_card_without_a_content_phash_is_the_only_exclusion(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not an eligibility filter - a card with no stable content hash has no identity for
        `ImageEvidence.content_hash` to key against and is skipped by `_run_stage_c` itself, so
        dispatching it could only ever produce a guaranteed no-op batch slot."""
        with_hash = CardFactory(content_phash=1)
        CardFactory(content_phash=None)

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10")

        assert recorder.dispatched_ids == [with_hash.pk]

    @STREAMING_ON
    def test_cards_are_dispatched_in_pk_order_across_batches(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(5)
        recorder = _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "2")

        assert [call["card_ids"] for call in recorder.calls] == [
            [cards[0].pk, cards[1].pk],
            [cards[2].pk, cards[3].pk],
            [cards[4].pk],
        ]
        # batch_size == len(chunk) on EVERY call - the load-bearing property that keeps
        # _select_micro_batch off the sweep-cursor path (see TestSweepCursorsAreNeverTouched).
        for call in recorder.calls:
            assert call["batch_size"] == len(call["card_ids"])
            assert call["trigger_reason"] == "full-catalog"


class TestSweepCursorsAreNeverTouched:
    """The reason this command exists rather than a fix to the sweep - stated in its own module
    docstring as a structural property, proved here against the REAL `_select_micro_batch`."""

    @STREAMING_ON
    def test_no_sweep_cursor_row_is_created_by_a_full_catalog_pass(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _cards(4)
        _install_ok_stage_c_stub(monkeypatch)

        assert StageESweepCursor.objects.count() == 0
        call_command("stream_full_catalog", "--batch-size", "2")

        # `_cursor_chunk_walk` calls `StageESweepCursor.get_cursor`, which is get_or_create - if
        # this command ever reached the backlog-fill branch, a row would exist here.
        assert StageESweepCursor.objects.count() == 0
        assert PilotRunLedger.objects.count() == 2  # the batches really did dispatch

    @STREAMING_ON
    def test_pre_existing_sweep_cursors_are_left_exactly_where_they_were(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = _cards(4)
        _install_ok_stage_c_stub(monkeypatch)
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_C, position=cards[0].pk, wrap_count=3)
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_D, position=cards[1].pk, wrap_count=7)

        call_command("stream_full_catalog", "--batch-size", "2")

        stage_c = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C)
        stage_d = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_D)
        assert (stage_c.position, stage_c.wrap_count) == (cards[0].pk, 3)
        assert (stage_d.position, stage_d.wrap_count) == (cards[1].pk, 7)

    @STREAMING_ON
    def test_a_wrapped_stage_c_cursor_does_not_end_the_pass(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """`stream_backstop_sweep` breaks out with "Backlog exhausted" on `exhausted=True`, which
        only ever means "the cursor wrapped". A cursor parked at the very end of the pk space (the
        state that produces that wrap on the next walk) must have no effect on this command at
        all."""
        cards = _cards(4)
        _install_ok_stage_c_stub(monkeypatch)
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_C, position=cards[-1].pk + 10_000)

        call_command("stream_full_catalog", "--batch-size", "2")
        output = capsys.readouterr().out

        assert "Cohort exhausted" in output  # ended on the COHORT, not on a cursor lap
        assert PilotRunLedger.objects.count() == 2
        assert StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C).wrap_count == 0


class TestResume:
    @STREAMING_ON
    def test_high_water_mark_advances_after_every_completed_batch(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = _cards(4)
        _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "2")

        assert StageEFullCatalogCursor.get_position() == cards[-1].pk
        assert StageEFullCatalogCursor.objects.get().cards_dispatched == 4

    @STREAMING_ON
    def test_a_killed_run_resumes_where_it_stopped(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(6)

        first = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "2", "--max-batches", "2")
        assert first.dispatched_ids == [c.pk for c in cards[:4]]

        second = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "2")
        # picks up at exactly the next pk - no card re-dispatched, none skipped.
        assert second.dispatched_ids == [c.pk for c in cards[4:]]

    @STREAMING_ON
    def test_a_halted_batch_is_not_recorded_as_done(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A halt/throttle means the batch did NO work, so its pks must not advance the mark - the
        relaunch has to re-dispatch exactly that chunk."""
        cards = _cards(4)
        _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="completed", card_ids=[cards[0].pk, cards[1].pk]),
                DispatchOutcome(status="halted-new-trip", trip_id="envtrip-test"),
            ],
        )
        call_command("stream_full_catalog", "--batch-size", "2")
        assert StageEFullCatalogCursor.get_position() == cards[1].pk

        resumed = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "2")
        assert resumed.dispatched_ids == [cards[2].pk, cards[3].pk]

    @STREAMING_ON
    def test_start_pk_overrides_and_resets_the_stored_mark(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(6)
        StageEFullCatalogCursor.reset_to(cards[3].pk)

        first = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10", "--start-pk", str(cards[0].pk))
        assert first.dispatched_ids == [c.pk for c in cards[1:]]

        # ...and the reset STUCK: a bare relaunch must not snap back to the old, higher mark. The
        # mark is monotonic, so without the explicit reset in handle() it would still read
        # cards[3].pk here rather than the pk this --start-pk run actually finished at.
        assert StageEFullCatalogCursor.get_position() == cards[-1].pk

    @STREAMING_ON
    def test_start_pk_zero_restarts_the_whole_pass(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(4)
        StageEFullCatalogCursor.reset_to(cards[-1].pk)

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10", "--start-pk", "0")

        assert recorder.dispatched_ids == [c.pk for c in cards]

    @STREAMING_ON
    def test_resume_pk_is_printed_on_every_exit_path(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = _cards(4)
        _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="completed", card_ids=[cards[0].pk, cards[1].pk]),
                DispatchOutcome(status="halted-new-trip", trip_id="envtrip-test"),
            ],
        )
        call_command("stream_full_catalog", "--batch-size", "2")
        output = capsys.readouterr().out

        assert f"RESUME resume_pk={cards[1].pk}" in output
        # ...and the rolled-up summary carries it too, so a log truncated before the DONE line
        # still contains a valid resume point.
        assert f"resume_pk={cards[1].pk}" in [line for line in output.splitlines() if line.startswith("PROGRESS")][-1]

    @STREAMING_ON
    def test_an_exhausted_catalog_stops_cleanly(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(2)
        _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10")
        capsys.readouterr()

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10")
        output = capsys.readouterr().out

        assert recorder.calls == []
        assert "Nothing to do." in output


class TestSample:
    @STREAMING_ON
    def test_the_same_n_always_selects_the_same_cards(self, db: Any) -> None:
        _cards(60)

        first = deterministic_sample_pks(12)
        second = deterministic_sample_pks(12)

        assert first == second
        assert len(first) == 12
        assert first == sorted(first)  # returned in pk order, like every other cohort walk

    @STREAMING_ON
    def test_the_sample_is_spread_across_the_pk_space_not_a_prefix(self, db: Any) -> None:
        _cards(60)
        all_pks = list(full_catalog_pk_queryset().values_list("pk", flat=True))

        sampled = deterministic_sample_pks(12)

        assert sampled != all_pks[:12]
        midpoint = all_pks[len(all_pks) // 2]
        assert any(pk <= midpoint for pk in sampled), "no card drawn from the low half of the pk space"
        assert any(pk > midpoint for pk in sampled), "no card drawn from the high half of the pk space"

    @STREAMING_ON
    def test_a_sample_larger_than_the_catalog_is_the_whole_catalog(self, db: Any) -> None:
        cards = _cards(5)
        assert deterministic_sample_pks(500) == [c.pk for c in cards]

    @STREAMING_ON
    def test_two_sample_runs_dispatch_identical_card_sets(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _cards(40)

        first = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--sample", "8", "--batch-size", "3")

        second = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--sample", "8", "--batch-size", "3")

        assert first.dispatched_ids == second.dispatched_ids
        assert len(first.dispatched_ids) == 8

    @STREAMING_ON
    def test_a_sample_run_never_reads_or_writes_the_stored_mark(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """A sample is spread across the WHOLE pk space, so letting one advance the mark would jump
        a real catalog pass's resume point to near the end of the catalog after a single batch."""
        cards = _cards(40)
        StageEFullCatalogCursor.reset_to(cards[0].pk)

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--sample", "8", "--batch-size", "8")

        # the stored mark is unchanged...
        assert StageEFullCatalogCursor.get_position() == cards[0].pk
        # ...and was not applied as a filter either: the sample is drawn from the whole pk space,
        # so it can legitimately include cards at or below the stored mark.
        assert len(recorder.dispatched_ids) == 8

    @STREAMING_ON
    def test_start_pk_bounds_a_sample_without_redrawing_it(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Relaunching a killed sample run with the same N and a --start-pk must cover the
        REMAINDER of the same draw, never a fresh one."""
        _cards(40)
        full_sample = deterministic_sample_pks(8)
        cutoff = full_sample[3]

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--sample", "8", "--batch-size", "8", "--start-pk", str(cutoff))

        assert recorder.dispatched_ids == full_sample[4:]


class TestReextractAndShortCircuitAreIndependent:
    """Command-level half of the decoupling (the conveyor-level half is
    `test_stage_e_dispatch.py::TestForceStageCReextract::
    test_short_circuit_is_independent_of_force_stage_c_reextract`)."""

    @STREAMING_ON
    @pytest.mark.parametrize(
        "argv, expected_reextract, expected_short_circuit",
        [
            ([], False, None),
            (["--reextract"], True, None),
            (["--no-short-circuit"], False, False),
            (["--short-circuit"], False, True),
            (["--reextract", "--no-short-circuit"], True, False),
            (["--reextract", "--short-circuit"], True, True),
        ],
    )
    def test_every_combination_reaches_the_conveyor_verbatim(
        self,
        db: Any,
        monkeypatch: pytest.MonkeyPatch,
        argv: List[str],
        expected_reextract: bool,
        expected_short_circuit: Any,
    ) -> None:
        CardFactory(content_phash=1)
        recorder = _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", *argv)

        assert recorder.calls[0]["force_stage_c_reextract"] is expected_reextract
        assert recorder.calls[0]["short_circuit"] is expected_short_circuit

    @STREAMING_ON
    def test_omitting_both_short_circuit_flags_inherits_the_env_default(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """`short_circuit=None` is what makes `compute_card_evidence` resolve the value from
        `STAGE_C_NO_SHORTCIRCUIT` at call time - the flag being absent must not silently become a
        hardcoded True or False anywhere along the way."""
        card = CardFactory(content_phash=1)
        CanonicalCardFactory(name=card.name, expansion__code="mom", collector_number="158")

        observed: List[Any] = []

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module
        import cardpicker.image_evidence as image_evidence_module

        _install_ok_stage_c_stub(monkeypatch)
        real_stub = image_evidence_module.compute_card_evidence

        def _recording(*args: Any, **kwargs: Any) -> Any:
            observed.append(kwargs.get("short_circuit"))
            return real_stub(*args, **kwargs)

        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _recording)
        assert image_cdn_fetch_module.fetch_card_image_bytes is not None

        call_command("stream_full_catalog", "--reextract")
        capsys.readouterr()

        assert observed == [None]

    @STREAMING_ON
    def test_reextract_actually_re_extracts_an_already_current_card(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=1)
        _current_full_evidence(card)
        _install_ok_stage_c_stub(monkeypatch)

        call_command("stream_full_catalog", "--reextract")

        assert PilotRunLedger.objects.get().counters["stage_c_completed"] == 1

    @STREAMING_ON
    def test_without_reextract_an_already_current_card_skips_stage_c(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Still DISPATCHED (the cohort has no eligibility filter), just not re-extracted - the
        conveyor's own already-done check is what skips the Stage C work."""
        card = CardFactory(content_phash=1)
        _current_full_evidence(card)

        def _fail_if_called(card: Any, dpi: Any = None) -> bytes:
            raise AssertionError("Stage C should have been skipped - evidence is already current")

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", _fail_if_called)

        call_command("stream_full_catalog")

        ledger = PilotRunLedger.objects.get()
        assert ledger.counters["stage_c_completed"] == 0
        assert ledger.counters["batch_size"] == 1  # dispatched all the same


class TestStopConditions:
    """The two conditions are DELIBERATELY ASYMMETRIC: an envelope trip hard-stops with no retry
    ever (NO SELF-RESUME is a binding design gate), while a concurrency-cap throttle is transient
    and self-clearing, so it gets a bounded exponential backoff-and-retry instead of ending an
    unattended multi-hour pass."""

    @STREAMING_ON
    def test_stops_on_an_envelope_halt_without_retrying(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(6)
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=9.0),
        )

        call_command("stream_full_catalog", "--batch-size", "1")
        output = capsys.readouterr().out

        assert EnvelopeTrip.objects.filter(bar=EnvelopeTrip.Bar.HOST_LOAD).count() == 1
        assert "Envelope halt" in output
        assert "stopping (do not retry, never self-resume)" in output
        assert "halted=halted-new-trip" in output
        assert output.count("Envelope halt") == 1  # one attempt, not six
        assert PilotRunLedger.objects.count() == 0
        assert StageEFullCatalogCursor.get_position() == 0

    @STREAMING_ON
    def test_stops_on_an_already_open_trip(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """NO SELF-RESUME: an open trip stops the pass outright, and nothing in this command ever
        acknowledges or clears it."""
        _cards(4)
        open_trip = check_envelope(stage_e_dispatch.EnvelopeSignals(load_avg=9.0))
        assert open_trip is not None
        # Every signal is healthy again - the OPEN TRIP alone must still stop the pass.
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=0.1),
        )
        _install_ok_stage_c_stub(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "1")
        output = capsys.readouterr().out

        assert "halted=halted-open-trip" in output
        assert output.count("Envelope halt") == 1
        assert PilotRunLedger.objects.count() == 0
        # the trip is still open and un-acknowledged - resolve_envelope_trip's job, never this
        # command's.
        assert EnvelopeTrip.objects.filter(acknowledged_at__isnull=True).count() == 1

    @STREAMING_ON
    def test_an_envelope_halt_never_backs_off_or_retries(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The asymmetry, stated as its own test: the halt path must never reach the backoff
        machinery. A trip clears only via an explicit human `resolve_envelope_trip`, so sleeping
        and re-sampling could only ever burn wall-clock."""
        _cards(6)
        waits = _install_sleep_recorder(monkeypatch)
        recorder = _install_recording_dispatch(
            monkeypatch, outcomes=[DispatchOutcome(status="halted-open-trip", trip_id="envtrip-test")]
        )

        call_command("stream_full_catalog", "--batch-size", "1", "--max-throttle-retries", "20")
        output = capsys.readouterr().out

        assert waits == []  # no backoff, ever, on the halt path
        assert len(recorder.calls) == 1  # one attempt, not six
        assert "halted=halted-open-trip" in output
        assert "throttle_retries=0" in output


class TestThrottleBackoffAndRetry:
    """A throttle means every `STAGE_E_MAX_CONCURRENT_DISPATCHES` slot is currently held. It is
    TRANSIENT and self-clearing as in-flight dispatches finish, so ending an unattended
    full-catalog pass on it would strand a multi-hour run on a condition that resolves in seconds.
    The bounded exponential backoff below is the mitigation `stage_e_dispatch.py`'s own "hot,
    backoff-free loop" warning asks for - the objection there is to the ABSENCE of backoff, not to
    retrying."""

    @STREAMING_ON
    def test_backs_off_and_retries_the_same_chunk(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = _cards(2)
        waits = _install_sleep_recorder(monkeypatch)
        recorder = _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="completed", card_ids=[c.pk for c in cards]),
            ],
        )

        call_command(
            "stream_full_catalog",
            "--batch-size",
            "2",
            "--throttle-backoff-initial",
            "4",
            "--throttle-backoff-max",
            "60",
        )
        output = capsys.readouterr().out

        # exponential: 4s, then 8s - and the SAME chunk every time, never skipped.
        assert waits == [4.0, 8.0]
        assert [call["card_ids"] for call in recorder.calls[:3]] == [[c.pk for c in cards]] * 3
        # ...under the SAME run_id too: a throttled dispatch writes no ledger row, so reusing it
        # cannot collide, and the successful attempt lands under its own batch index.
        assert len({call["run_id"] for call in recorder.calls[:3]}) == 1
        assert "backing off 4.0s" in output
        assert "SATURATED, not stalled" in output
        assert "throttle_retries=2" in output
        # the pass completed - a transient throttle must not end it.
        assert "cards_done=2" in output
        assert StageEFullCatalogCursor.get_position() == cards[-1].pk

    @STREAMING_ON
    def test_backoff_is_capped(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _cards(1)
        waits = _install_sleep_recorder(monkeypatch)
        _install_recording_dispatch(monkeypatch, outcomes=[DispatchOutcome(status="throttled-concurrency-cap")] * 5)

        with pytest.raises(CommandError):
            call_command(
                "stream_full_catalog",
                "--max-throttle-retries",
                "4",
                "--throttle-backoff-initial",
                "1",
                "--throttle-backoff-max",
                "3",
            )

        assert waits == [1.0, 2.0, 3.0, 3.0]  # doubling, then pinned at the ceiling

    @STREAMING_ON
    def test_the_retry_budget_is_bounded_and_exits_non_zero(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Exhausting the budget is the genuine "the cap is not clearing, a human needs to look"
        signal - and an unattended run that gave up must be detectable by a supervisor, hence the
        non-zero exit (`CommandError`)."""
        _cards(4)
        _install_sleep_recorder(monkeypatch)
        recorder = _install_recording_dispatch(
            monkeypatch, outcomes=[DispatchOutcome(status="throttled-concurrency-cap")] * 20
        )

        with pytest.raises(CommandError, match="concurrency cap did not clear"):
            call_command(
                "stream_full_catalog",
                "--batch-size",
                "2",
                "--max-throttle-retries",
                "3",
                "--throttle-backoff-initial",
                "0.01",
                "--throttle-backoff-max",
                "0.01",
            )
        output = capsys.readouterr().out

        # the first attempt plus exactly 3 retries - bounded, never unbounded.
        assert len(recorder.calls) == 4
        assert "giving up" in output
        assert "stopped_reason=throttle-retries-exhausted" in output
        # the resume pk is still printed before the non-zero exit.
        assert "RESUME resume_pk=0" in output
        assert PilotRunLedger.objects.count() == 0

    @STREAMING_ON
    def test_the_consecutive_counter_resets_on_a_successful_dispatch(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The budget bounds a CONTINUOUS saturation episode, not the run's lifetime total - two
        throttles, a success, then two more throttles must not exhaust a budget of 2."""
        cards = _cards(4)
        _install_sleep_recorder(monkeypatch)
        _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="completed", card_ids=[cards[0].pk, cards[1].pk]),
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="completed", card_ids=[cards[2].pk, cards[3].pk]),
            ],
        )

        call_command(
            "stream_full_catalog",
            "--batch-size",
            "2",
            "--max-throttle-retries",
            "2",
            "--throttle-backoff-initial",
            "0.01",
            "--throttle-backoff-max",
            "0.01",
        )
        output = capsys.readouterr().out

        assert "cards_done=4" in output
        assert "throttle_retries=4" in output  # 4 total, but never 3 consecutive
        assert "stopped_reason=cohort-exhausted" in output

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_a_real_saturated_cap_backs_off_then_gives_up(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Against the REAL conveyor and a genuinely held advisory-lock slot, not a stubbed
        outcome (the same "genuinely separate session" discipline `test_stage_e_concurrency.py`
        establishes - Postgres session-level advisory locks are re-entrant within one session)."""
        _cards(6)
        waits = _install_sleep_recorder(monkeypatch)

        connection.ensure_connection()
        raw = psycopg2.connect(**connection.get_connection_params())
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, 0])
            (acquired,) = cursor.fetchone()
            assert acquired is True, "test setup failed to claim the only slot"
        try:
            with pytest.raises(CommandError):
                call_command(
                    "stream_full_catalog",
                    "--batch-size",
                    "1",
                    "--max-throttle-retries",
                    "2",
                    "--throttle-backoff-initial",
                    "0.01",
                    "--throttle-backoff-max",
                    "0.01",
                )
        finally:
            raw.close()

        output = capsys.readouterr().out
        assert len(waits) == 2
        assert "batches_dispatched=0" in output
        assert "stopped_reason=throttle-retries-exhausted" in output
        assert PilotRunLedger.objects.count() == 0


class TestProgressOutput:
    """Built for an UNATTENDED run - assume nobody is watching most of the time."""

    @STREAMING_ON
    def test_the_per_batch_line_is_hidden_at_default_verbosity(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(6)
        _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "2")
        output = capsys.readouterr().out

        assert "[batch 0] pk" not in output

    @STREAMING_ON
    def test_the_per_batch_line_appears_at_verbosity_2(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(6)
        _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "2", "--verbosity", "2")
        output = capsys.readouterr().out

        assert "[batch 0] pk" in output
        assert "cards/s" in output

    @STREAMING_ON
    def test_a_rolled_up_summary_is_emitted_on_the_batch_cadence(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(12)
        _install_recording_dispatch(monkeypatch)

        call_command(
            "stream_full_catalog",
            "--batch-size",
            "2",
            "--progress-every-batches",
            "2",
            "--progress-every-seconds",
            "3600",
        )
        output = capsys.readouterr().out
        summaries = [line for line in output.splitlines() if line.startswith("PROGRESS")]

        # 6 batches at a cadence of 2 -> 3 periodic summaries, plus the unconditional final one.
        assert len(summaries) == 4
        for field in ("done=", "remaining=", "elapsed=", "rate_now=", "rate_avg=", "resume_pk="):
            assert field in summaries[0]
        assert "projected_completion=" in summaries[0]
        assert "throttle_retries=" in summaries[0]

    @STREAMING_ON
    def test_a_final_summary_is_always_emitted_even_with_no_periodic_ones(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = _cards(2)
        _install_recording_dispatch(monkeypatch)

        call_command(
            "stream_full_catalog",
            "--batch-size",
            "2",
            "--progress-every-batches",
            "1000",
            "--progress-every-seconds",
            "3600",
        )
        output = capsys.readouterr().out
        summaries = [line for line in output.splitlines() if line.startswith("PROGRESS")]

        assert len(summaries) == 1
        assert "done=2/2 remaining=0" in summaries[0]
        assert f"resume_pk={cards[-1].pk}" in summaries[0]

    @STREAMING_ON
    def test_max_batches_bounds_one_invocation(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(10)
        recorder = _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "2", "--max-batches", "3")
        output = capsys.readouterr().out

        assert len(recorder.calls) == 3
        assert "batches_dispatched=3 cards_done=6" in output

    def test_disabled_by_default_is_a_no_op(self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
        CardFactory(content_phash=1)
        recorder = _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog")
        output = capsys.readouterr().out

        assert "no-op" in output
        assert "Cohort:" not in output
        assert recorder.calls == []


class TestDryRun:
    @STREAMING_ON
    def test_dry_run_reports_the_plan_and_dispatches_nothing(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(7)
        recorder = _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "3", "--dry-run")
        output = capsys.readouterr().out

        assert "Cohort: 7 cards remaining" in output
        assert "planned_batches=3" in output
        assert "DRY RUN" in output
        assert recorder.calls == []
        assert PilotRunLedger.objects.count() == 0
        assert StageEFullCatalogCursor.objects.count() == 0

    @STREAMING_ON
    def test_dry_run_never_writes_the_high_water_mark_even_with_start_pk(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(4)
        call_command("stream_full_catalog", "--dry-run", "--start-pk", "2")

        assert StageEFullCatalogCursor.objects.count() == 0


class TestArgumentValidation:
    @pytest.mark.parametrize(
        "argv",
        [
            ["--batch-size", "0"],
            ["--sample", "0"],
            ["--max-batches", "0"],
            ["--start-pk", "-1"],
        ],
    )
    def test_non_positive_values_are_command_errors(self, db: Any, argv: List[str]) -> None:
        """Validated BEFORE the streaming-enabled gate (stage_e_shakedown's own convention) - a bad
        invocation must never look like a silent, successful no-op."""
        with pytest.raises(CommandError):
            call_command("stream_full_catalog", *argv)


class TestFullCatalogCursorModel:
    def test_advance_is_monotonic(self, db: Any) -> None:
        StageEFullCatalogCursor.advance(100, cards_dispatched=5)
        assert StageEFullCatalogCursor.get_position() == 100

        StageEFullCatalogCursor.advance(50, cards_dispatched=5)
        assert StageEFullCatalogCursor.get_position() == 100  # never rewinds

        StageEFullCatalogCursor.advance(150, cards_dispatched=5)
        assert StageEFullCatalogCursor.get_position() == 150

    def test_reset_to_is_the_only_backwards_move(self, db: Any) -> None:
        StageEFullCatalogCursor.advance(100)
        StageEFullCatalogCursor.reset_to(10)
        assert StageEFullCatalogCursor.get_position() == 10

    def test_position_is_zero_before_the_command_has_ever_run(self, db: Any) -> None:
        assert StageEFullCatalogCursor.get_position() == 0
        assert StageEFullCatalogCursor.objects.count() == 0


class TestStageZeroFreshness:
    """Issue #513 item 2 - "Freshness belongs inside the streaming process, not as a pre-step".
    Stage 0 verifies (and refreshes) Scryfall printing-metadata freshness ONCE, before batch 0,
    and never again for the lifetime of the invocation."""

    @STREAMING_ON
    def test_fresh_data_is_reported_and_no_refresh_happens(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(2)
        _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog")
        output = capsys.readouterr().out

        assert "STAGE 0: Scryfall printing metadata is FRESH" in output
        assert "remote updated_at=2026-07-28T00:00:00.000Z" in output
        # the autouse fixture fails the test if import_scryfall_printing_metadata is called at all.

    @STREAMING_ON
    def test_stale_data_is_refreshed_once_before_any_dispatch(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The once-only property, observed directly: the refresh happens BEFORE the first
        dispatch and exactly once, however many batches follow. Stage D's illustration deduction
        indexes CanonicalPrintingMetadata, so a mid-run refresh would change the deduction index
        underneath a running pass."""
        _cards(6)
        events: List[str] = []
        monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: False)

        def _refresh() -> Any:
            events.append("refresh")
            return {"created": 1, "updated": 2, "deleted": 0, "skipped": 3}

        monkeypatch.setattr(stream_full_catalog, "import_scryfall_printing_metadata", _refresh)

        recorder = _RecordingDispatch()

        def _recording_dispatch(**kwargs: Any) -> DispatchOutcome:
            events.append("dispatch")
            return recorder(**kwargs)

        monkeypatch.setattr(stream_full_catalog, "dispatch_micro_batch", _recording_dispatch)

        call_command("stream_full_catalog", "--batch-size", "2")
        output = capsys.readouterr().out

        assert "STAGE 0: Scryfall printing metadata is STALE - refreshing now" in output
        assert "STAGE 0: refresh complete - created=1 updated=2" in output
        assert "will NOT run again for the lifetime of this invocation" in output
        # exactly one refresh, and it strictly precedes every dispatch.
        assert events.count("refresh") == 1
        assert events[0] == "refresh"
        assert set(events[1:]) == {"dispatch"}

    @STREAMING_ON
    def test_require_fresh_fails_instead_of_refreshing(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _cards(2)
        recorder = _install_recording_dispatch(monkeypatch)
        monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: False)

        with pytest.raises(CommandError, match="STAGE 0 FAILED"):
            call_command("stream_full_catalog", "--require-fresh")

        # verify-only: nothing refreshed (the autouse fixture would fail the test), nothing
        # dispatched.
        assert recorder.calls == []

    @STREAMING_ON
    def test_a_bulk_data_lookup_failure_aborts_before_any_dispatch(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Did not start" and "ran to completion" are the only acceptable outcomes - never
        "started against reference data of unknown age"."""
        _cards(4)
        recorder = _install_recording_dispatch(monkeypatch)

        def _boom() -> Any:
            raise RuntimeError("scryfall unreachable")

        monkeypatch.setattr(stream_full_catalog, "_get_default_cards_entry", _boom)

        with pytest.raises(CommandError, match="could not read Scryfall's /bulk-data entry"):
            call_command("stream_full_catalog")

        assert recorder.calls == []
        assert PilotRunLedger.objects.count() == 0
        assert StageEFullCatalogCursor.objects.count() == 0

    @STREAMING_ON
    def test_a_refresh_failure_aborts_before_any_dispatch(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _cards(4)
        recorder = _install_recording_dispatch(monkeypatch)
        monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: False)

        def _boom() -> Any:
            raise RuntimeError("half-imported")

        monkeypatch.setattr(stream_full_catalog, "import_scryfall_printing_metadata", _boom)

        with pytest.raises(CommandError, match="half-imported"):
            call_command("stream_full_catalog")

        assert recorder.calls == []
        assert PilotRunLedger.objects.count() == 0

    @STREAMING_ON
    def test_a_refresh_on_a_resumed_run_is_called_out_loudly(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A resume that refreshes has the same early/late inconsistency as a mid-run refresh,
        only spread across two invocations."""
        cards = _cards(6)
        StageEFullCatalogCursor.reset_to(cards[1].pk)
        _install_recording_dispatch(monkeypatch)
        monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: False)
        monkeypatch.setattr(stream_full_catalog, "import_scryfall_printing_metadata", dict)

        call_command("stream_full_catalog", "--batch-size", "2")
        output = capsys.readouterr().out

        assert "STAGE 0 WARNING" in output
        assert "RESUMED run and the reference data CHANGED" in output

    @STREAMING_ON
    def test_a_refresh_on_a_first_run_is_not_flagged_as_a_resume(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(2)
        _install_recording_dispatch(monkeypatch)
        monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: False)
        monkeypatch.setattr(stream_full_catalog, "import_scryfall_printing_metadata", dict)

        call_command("stream_full_catalog")
        output = capsys.readouterr().out

        assert "STAGE 0 WARNING" not in output

    @STREAMING_ON
    def test_skip_freshness_bypasses_stage_zero_entirely(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(2)
        _install_recording_dispatch(monkeypatch)

        def _boom() -> Any:
            raise AssertionError("stage 0 must not run under --skip-freshness")

        monkeypatch.setattr(stream_full_catalog, "_get_default_cards_entry", _boom)

        call_command("stream_full_catalog", "--skip-freshness")
        output = capsys.readouterr().out

        assert "STAGE 0 skipped (--skip-freshness)" in output
        assert "cards_done=2" in output

    @STREAMING_ON
    def test_dry_run_skips_stage_zero(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A refresh is a real ~558MB download and a real DB write; --dry-run writes nothing."""
        _cards(2)

        def _boom() -> Any:
            raise AssertionError("stage 0 must not run under --dry-run")

        monkeypatch.setattr(stream_full_catalog, "_get_default_cards_entry", _boom)

        call_command("stream_full_catalog", "--dry-run")
        output = capsys.readouterr().out

        assert "STAGE 0 skipped (--dry-run" in output
        assert "DRY RUN" in output

    def test_stage_zero_never_runs_when_streaming_is_disabled(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        CardFactory(content_phash=1)

        def _boom() -> Any:
            raise AssertionError("stage 0 must not run when STAGE_E_STREAMING_ENABLED is False")

        monkeypatch.setattr(stream_full_catalog, "_get_default_cards_entry", _boom)

        call_command("stream_full_catalog")
