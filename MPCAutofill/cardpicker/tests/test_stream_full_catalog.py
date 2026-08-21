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

from cardpicker import stage_e_batch_sizing as batch_sizing
from cardpicker import stage_e_dispatch
from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.management.commands import stream_full_catalog
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
)
from cardpicker.management.commands.stream_full_catalog import (
    FULL_CATALOG_SCOPE,
    deterministic_sample_pks,
    full_catalog_pk_queryset,
    parse_source_keys,
    resume_scope_for,
)
from cardpicker.models import (
    CardPrintingTag,
    EnvelopeTrip,
    PilotRunLedger,
    Source,
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
    SourceFactory,
)
from cardpicker.tests.test_stage_e_dispatch import _SyncStagePoolStub

STREAMING_ON = override_settings(STAGE_E_STREAMING_ENABLED=True)


@pytest.fixture(autouse=True)
def _sync_stage_c_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    """This driver dispatches through the real `dispatch_micro_batch` -> `_run_stage_c` for every
    test in this module that isn't stubbed at the `dispatch_micro_batch` boundary itself (via
    `_install_recording_dispatch`) - see `_SyncStagePoolStub`'s own docstring in
    `test_stage_e_dispatch.py` for why the real `ThreadPoolExecutor`/`ProcessPoolExecutor` module
    names must be replaced rather than left real in a test process."""
    monkeypatch.setattr(stage_e_dispatch, "ThreadPoolExecutor", _SyncStagePoolStub)
    monkeypatch.setattr(stage_e_dispatch, "ProcessPoolExecutor", _SyncStagePoolStub)


def _exit_code(*argv: Any, **kwargs: Any) -> int:
    """Run the command and return THE EXIT CODE a supervisor would actually observe.

    `call_command` raises `CommandError` rather than exiting, so this reproduces what Django's own
    `BaseCommand.run_from_argv` does with one (`sys.exit(exc.returncode)`) - which is the only
    thing the systemd unit / wrapper script reading this command's status ever sees. Exit 0 is the
    absence of a `CommandError`, exactly as in the real process.
    """
    try:
        call_command("stream_full_catalog", *argv, **kwargs)
    except CommandError as exc:
        assert exc.returncode != 0, "a CommandError that exits 0 would report a failure as a success"
        return int(exc.returncode)
    return 0


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
        artist_lexicon: Any = None,
        printing_artist_lookup: Any = None,
        card_artist_names: Any = (),
        modern_artist_lexicon: Any = None,
        md5_checksum: Any = None,
        sha256_checksum: Any = None,
        stale_extractor_keys: Any = None,
        stored_evidence_fields: Any = None,
        stored_extractor_versions: Any = None,
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

        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == cards[-1].pk
        assert StageEFullCatalogCursor.objects.get().cards_dispatched == 4

    @STREAMING_ON
    def test_a_killed_run_resumes_where_it_stopped(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(6)

        first = _install_recording_dispatch(monkeypatch)
        # --max-batches with cards still left is an INCOMPLETE pass, so it exits 5 - the resume
        # behaviour this test is about is unchanged by that.
        assert _exit_code("--batch-size", "2", "--max-batches", "2") == 5
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
        assert _exit_code("--batch-size", "2") == 3  # an envelope halt leaves work: non-zero
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == cards[1].pk

        resumed = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "2")
        assert resumed.dispatched_ids == [cards[2].pk, cards[3].pk]

    @STREAMING_ON
    def test_start_pk_overrides_and_resets_the_stored_mark(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(6)
        StageEFullCatalogCursor.reset_to(FULL_CATALOG_SCOPE, cards[3].pk)

        first = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10", "--start-pk", str(cards[0].pk))
        assert first.dispatched_ids == [c.pk for c in cards[1:]]

        # ...and the reset STUCK: a bare relaunch must not snap back to the old, higher mark. The
        # mark is monotonic, so without the explicit reset in handle() it would still read
        # cards[3].pk here rather than the pk this --start-pk run actually finished at.
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == cards[-1].pk

    @STREAMING_ON
    def test_start_pk_zero_restarts_the_whole_pass(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(4)
        StageEFullCatalogCursor.reset_to(FULL_CATALOG_SCOPE, cards[-1].pk)

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
        assert _exit_code("--batch-size", "2") == 3
        output = capsys.readouterr().out

        assert f"RESUME scope=full-catalog resume_pk={cards[1].pk}" in output
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
        StageEFullCatalogCursor.reset_to(FULL_CATALOG_SCOPE, cards[0].pk)

        recorder = _install_recording_dispatch(monkeypatch)
        # a sample that finishes its own draw is a COMPLETE pass over that cohort: exit 0.
        assert _exit_code("--sample", "8", "--batch-size", "8") == 0

        # the stored mark is unchanged...
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == cards[0].pk
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


class TestRunIdIsStableAcrossBatchesLedgerIdIsNot:
    """GitHub issue #666 follow-up: `run_id` used to carry a `-{batch_num}` suffix, making
    `_partition_by_md5_verdict`'s already-voted read (scoped to `run_id`) structurally always-empty
    across batches - no batch could ever see an md5 sibling's vote cast by an earlier batch of the
    same pass. `run_id` must now be the pass's stable prefix on every batch, while `ledger_run_id`
    (not `PilotRunLedger.run_id` directly) is what stays unique per batch."""

    @STREAMING_ON
    def test_run_id_is_identical_across_batches_while_ledger_run_id_is_unique(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _cards(3)
        recorder = _install_recording_dispatch(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "1")

        assert len(recorder.calls) == 3
        run_ids = [call["run_id"] for call in recorder.calls]
        assert len(set(run_ids)) == 1  # stable across every batch of the pass

        ledger_run_ids = [call["ledger_run_id"] for call in recorder.calls]
        assert len(set(ledger_run_ids)) == 3  # unique per batch
        assert all(ledger_run_id != run_ids[0] for ledger_run_id in ledger_run_ids)

    @STREAMING_ON
    def test_real_dispatch_writes_one_ledger_row_per_batch_with_no_unique_constraint_collision(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same shape, through the REAL `dispatch_micro_batch` (no recorder stub) - proves
        `ledger_run_id` actually avoids the `PilotRunLedger.run_id` unique-constraint collision a
        stable, unsuffixed `run_id` would otherwise hit on the second batch."""
        cards = _cards(3)
        _install_ok_stage_c_stub(monkeypatch)

        call_command("stream_full_catalog", "--batch-size", "1")

        assert PilotRunLedger.objects.count() == 3
        assert PilotRunLedger.objects.values_list("run_id", flat=True).distinct().count() == 3
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == cards[-1].pk


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

        assert _exit_code("--batch-size", "1") == 3
        output = capsys.readouterr().out

        assert EnvelopeTrip.objects.filter(bar=EnvelopeTrip.Bar.HOST_LOAD).count() == 1
        assert "Envelope halt" in output
        assert "stopping (do not retry, never self-resume)" in output
        assert "halted=halted-new-trip" in output
        assert output.count("Envelope halt") == 1  # one attempt, not six
        assert PilotRunLedger.objects.count() == 0
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == 0

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

        assert _exit_code("--batch-size", "1") == 3
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

        assert _exit_code("--batch-size", "1", "--max-throttle-retries", "20") == 3
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
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == cards[-1].pk

    @STREAMING_ON
    def test_backoff_is_capped(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _cards(1)
        waits = _install_sleep_recorder(monkeypatch)
        _install_recording_dispatch(monkeypatch, outcomes=[DispatchOutcome(status="throttled-concurrency-cap")] * 5)

        assert (
            _exit_code(
                "--max-throttle-retries",
                "4",
                "--throttle-backoff-initial",
                "1",
                "--throttle-backoff-max",
                "3",
            )
            == 4
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

        with pytest.raises(CommandError, match="concurrency cap did not clear") as exc_info:
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
        # code 4 specifically, not just "non-zero": a supervisor may safely relaunch THIS one
        # unattended once the cap frees up, which it must never do for an envelope halt (3).
        assert exc_info.value.returncode == 4
        output = capsys.readouterr().out

        # the first attempt plus exactly 3 retries - bounded, never unbounded.
        assert len(recorder.calls) == 4
        assert "giving up" in output
        assert "stopped_reason=throttle-retries-exhausted" in output
        # the resume pk is still printed before the non-zero exit.
        assert "RESUME scope=full-catalog resume_pk=0" in output
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
    # STAGE_E_GOVERNOR_CONCURRENCY_CAP=1 - same reasoning as the identical fix in
    # test_stage_e_dispatch.py::TestConcurrencyCapIntegration and test_stage_e_shakedown.py: pins
    # the governor's ceiling to this test's single held slot.
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1, STAGE_E_GOVERNOR_CONCURRENCY_CAP=1)
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
            code = _exit_code(
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
        assert code == 4

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

        # 10 cards, 3 batches of 2 -> 4 cards left over, so the bound truncated the pass: exit 5.
        assert _exit_code("--batch-size", "2", "--max-batches", "3") == 5
        output = capsys.readouterr().out

        assert len(recorder.calls) == 3
        assert "batches_dispatched=3 cards_done=6" in output

    def test_disabled_by_default_is_a_no_op(self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
        CardFactory(content_phash=1)
        recorder = _install_recording_dispatch(monkeypatch)

        # NON-ZERO (code 6): the whole cohort is left unprocessed, so a supervisor must not read
        # this as a completed pass. It is still a no-op in every other sense.
        assert _exit_code() == 6
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

        # EXIT ZERO: a dry run did exactly what was asked of it - it is not an interrupted pass.
        assert _exit_code("--batch-size", "3", "--dry-run") == 0
        output = capsys.readouterr().out

        assert "PASS COMPLETE exit_code=0 reason=dry-run-plan-only" in output
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
        with pytest.raises(CommandError) as exc_info:
            call_command("stream_full_catalog", *argv)
        # code 1 - Django's own CommandError default: the INVOCATION was rejected, nothing ran.
        assert exc_info.value.returncode == 1


class TestFullCatalogCursorModel:
    def test_advance_is_monotonic(self, db: Any) -> None:
        StageEFullCatalogCursor.advance(FULL_CATALOG_SCOPE, 100, cards_dispatched=5)
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == 100

        StageEFullCatalogCursor.advance(FULL_CATALOG_SCOPE, 50, cards_dispatched=5)
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == 100  # never rewinds

        StageEFullCatalogCursor.advance(FULL_CATALOG_SCOPE, 150, cards_dispatched=5)
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == 150

    def test_reset_to_is_the_only_backwards_move(self, db: Any) -> None:
        StageEFullCatalogCursor.advance(FULL_CATALOG_SCOPE, 100)
        StageEFullCatalogCursor.reset_to(FULL_CATALOG_SCOPE, 10)
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == 10

    def test_position_is_zero_before_the_command_has_ever_run(self, db: Any) -> None:
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == 0
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

        with pytest.raises(CommandError, match="STAGE 0 FAILED") as exc_info:
            call_command("stream_full_catalog", "--require-fresh")
        assert exc_info.value.returncode == 2  # "did not start", distinct from every mid-pass stop

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

        with pytest.raises(CommandError, match="could not read Scryfall's /bulk-data entry") as exc_info:
            call_command("stream_full_catalog")

        assert exc_info.value.returncode == 2
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

        with pytest.raises(CommandError, match="half-imported") as exc_info:
            call_command("stream_full_catalog")

        assert exc_info.value.returncode == 2
        assert recorder.calls == []
        assert PilotRunLedger.objects.count() == 0

    @STREAMING_ON
    def test_a_refresh_on_a_resumed_run_is_called_out_loudly(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A resume that refreshes has the same early/late inconsistency as a mid-run refresh,
        only spread across two invocations."""
        cards = _cards(6)
        StageEFullCatalogCursor.reset_to(FULL_CATALOG_SCOPE, cards[1].pk)
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

        assert _exit_code() == 6  # the gate is still checked BEFORE stage 0, it just reports honestly now


class TestSourceScoping:
    """`--source <key>` (2026-07-28) - push one newly-added drive through the extractor without a
    full-catalog traversal. A SCOPE, not an eligibility filter: within the chosen source nothing is
    still skipped for being already done."""

    @STREAMING_ON
    def test_a_scoped_cohort_contains_only_that_sources_cards(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        wanted = SourceFactory(key="new_drive", name="New Drive")
        other = SourceFactory(key="old_drive", name="Old Drive")
        mine = [CardFactory(content_phash=i, source=wanted) for i in (1, 2)]
        theirs = [CardFactory(content_phash=i, source=other) for i in (3, 4)]

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "new_drive", "--batch-size", "10")

        assert recorder.dispatched_ids == [c.pk for c in mine]
        assert not set(recorder.dispatched_ids) & {c.pk for c in theirs}

    @STREAMING_ON
    def test_an_unscoped_run_still_covers_the_whole_catalog(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        wanted = SourceFactory(key="new_drive", name="New Drive")
        other = SourceFactory(key="old_drive", name="Old Drive")
        cards = [CardFactory(content_phash=1, source=wanted), CardFactory(content_phash=2, source=other)]

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10")

        assert recorder.dispatched_ids == [c.pk for c in cards]

    @STREAMING_ON
    @pytest.mark.parametrize("argv", [["--source", "a", "--source", "b"], ["--source", "a,b"]])
    def test_repeated_and_comma_separated_forms_are_equivalent(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, argv: List[str]
    ) -> None:
        source_a = SourceFactory(key="a", name="A")
        source_b = SourceFactory(key="b", name="B")
        SourceFactory(key="c", name="C")
        wanted = [CardFactory(content_phash=1, source=source_a), CardFactory(content_phash=2, source=source_b)]
        CardFactory(content_phash=3, source=Source.objects.get(key="c"))

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", *argv, "--batch-size", "10")

        assert recorder.dispatched_ids == [c.pk for c in wanted]

    @STREAMING_ON
    def test_an_unknown_source_key_is_an_error_not_an_empty_cohort(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo'd drive key that quietly "completed" a zero-card pass is exactly the false
        success an unattended run must never report."""
        SourceFactory(key="real_drive", name="Real Drive")
        CardFactory(content_phash=1, source=Source.objects.get(key="real_drive"))
        recorder = _install_recording_dispatch(monkeypatch)

        with pytest.raises(CommandError, match="unknown source key") as exc_info:
            call_command("stream_full_catalog", "--source", "typo_drive")
        assert exc_info.value.returncode == 1

        assert recorder.calls == []
        assert StageEFullCatalogCursor.objects.count() == 0

    @STREAMING_ON
    def test_an_unknown_key_alongside_a_known_one_still_errors(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        SourceFactory(key="real_drive", name="Real Drive")
        recorder = _install_recording_dispatch(monkeypatch)

        with pytest.raises(CommandError, match=r"unknown source key\(s\) \['typo_drive'\]"):
            call_command("stream_full_catalog", "--source", "real_drive,typo_drive")

        assert recorder.calls == []

    @STREAMING_ON
    def test_dry_run_reports_the_scoped_cohort_size(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        wanted = SourceFactory(key="new_drive", name="New Drive")
        other = SourceFactory(key="old_drive", name="Old Drive")
        for i in (1, 2, 3):
            CardFactory(content_phash=i, source=wanted)
        for i in (4, 5, 6, 7):
            CardFactory(content_phash=i, source=other)

        call_command("stream_full_catalog", "--source", "new_drive", "--dry-run", "--batch-size", "2")
        output = capsys.readouterr().out

        assert "Cohort: 3 cards remaining" in output  # the scoped 3, not the catalog's 7
        assert "sources ['new_drive']" in output
        assert "planned_batches=2" in output

    @STREAMING_ON
    def test_start_pk_applies_within_the_narrowed_set(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        wanted = SourceFactory(key="new_drive", name="New Drive")
        other = SourceFactory(key="old_drive", name="Old Drive")
        mine = [CardFactory(content_phash=i, source=wanted) for i in (1, 2, 3)]
        CardFactory(content_phash=4, source=other)

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "new_drive", "--start-pk", str(mine[0].pk))

        assert recorder.dispatched_ids == [c.pk for c in mine[1:]]

    @STREAMING_ON
    def test_sample_draws_from_the_narrowed_pool(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        wanted = SourceFactory(key="new_drive", name="New Drive")
        other = SourceFactory(key="old_drive", name="Old Drive")
        mine = {CardFactory(content_phash=i, source=wanted).pk for i in range(1, 21)}
        for i in range(21, 41):
            CardFactory(content_phash=i, source=other)

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "new_drive", "--sample", "5", "--batch-size", "5")

        assert len(recorder.dispatched_ids) == 5
        assert set(recorder.dispatched_ids) <= mine
        # still deterministic, given the same N AND the same scope.
        assert deterministic_sample_pks(5, ["new_drive"]) == sorted(recorder.dispatched_ids)


class TestResumeMarkIsKeyedByScope:
    """The part most likely to go subtly wrong: a mark recorded during a `--source X` run must
    never make a later full-catalog run skip pk space it has not examined."""

    @STREAMING_ON
    def test_a_scoped_run_does_not_advance_the_full_catalog_mark(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wanted = SourceFactory(key="high_pk_drive", name="High Pk Drive")
        other = SourceFactory(key="other_drive", name="Other Drive")
        # the OTHER source's cards sort FIRST, the scoped source's LAST - so a shared mark would
        # park at the very top of the pk space after the scoped run.
        low = [CardFactory(content_phash=i, source=other) for i in (1, 2, 3)]
        high = [CardFactory(content_phash=i, source=wanted) for i in (4, 5)]

        _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "high_pk_drive", "--batch-size", "10")

        assert StageEFullCatalogCursor.get_position("source:high_pk_drive") == high[-1].pk
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == 0

        # ...and the full-catalog run that follows still covers EVERY card, including the low ones
        # a shared mark would have skipped entirely.
        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10")

        assert recorder.dispatched_ids == [c.pk for c in low + high]

    @STREAMING_ON
    def test_a_full_catalog_run_does_not_complete_a_scoped_one(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        wanted = SourceFactory(key="new_drive", name="New Drive")
        mine = [CardFactory(content_phash=i, source=wanted) for i in (1, 2)]

        _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--batch-size", "10")
        assert StageEFullCatalogCursor.get_position(FULL_CATALOG_SCOPE) == mine[-1].pk

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "new_drive", "--batch-size", "10")

        # the scoped scope has its own, untouched mark - the cards are re-dispatched, which is the
        # correct behaviour for a cohort that is deliberately unfiltered by eligibility.
        assert recorder.dispatched_ids == [c.pk for c in mine]

    @STREAMING_ON
    def test_two_different_scopes_resume_independently(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        source_a = SourceFactory(key="a", name="A")
        source_b = SourceFactory(key="b", name="B")
        a_cards = [CardFactory(content_phash=i, source=source_a) for i in (1, 2, 3, 4)]
        b_cards = [CardFactory(content_phash=i, source=source_b) for i in (5, 6, 7, 8)]

        first = _install_recording_dispatch(monkeypatch)
        # both bounded runs stop with cards left in their own scope, hence exit 5 apiece
        assert _exit_code("--source", "a", "--batch-size", "2", "--max-batches", "1") == 5
        assert first.dispatched_ids == [c.pk for c in a_cards[:2]]

        second = _install_recording_dispatch(monkeypatch)
        assert _exit_code("--source", "b", "--batch-size", "2", "--max-batches", "1") == 5
        assert second.dispatched_ids == [c.pk for c in b_cards[:2]]

        # each scope picks up its OWN remainder, neither confused by the other.
        third = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "a", "--batch-size", "10")
        assert third.dispatched_ids == [c.pk for c in a_cards[2:]]

        fourth = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "b", "--batch-size", "10")
        assert fourth.dispatched_ids == [c.pk for c in b_cards[2:]]

    @STREAMING_ON
    def test_multi_source_scope_keys_are_order_insensitive(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """`--source a,b` and `--source b,a` select exactly the same cohort, so they must share a
        resume mark rather than each starting over."""
        source_a = SourceFactory(key="a", name="A")
        source_b = SourceFactory(key="b", name="B")
        cards = [CardFactory(content_phash=1, source=source_a), CardFactory(content_phash=2, source=source_b)]

        _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "a,b", "--batch-size", "10")

        recorder = _install_recording_dispatch(monkeypatch)
        call_command("stream_full_catalog", "--source", "b,a", "--batch-size", "10")

        assert recorder.calls == []  # already complete under the shared scope key
        assert StageEFullCatalogCursor.get_position("source:a,b") == cards[-1].pk

    def test_resume_scope_for_derives_a_stable_key(self) -> None:
        assert resume_scope_for(None) == FULL_CATALOG_SCOPE
        assert resume_scope_for([]) == FULL_CATALOG_SCOPE
        assert resume_scope_for(["b", "a"]) == resume_scope_for(["a", "b"]) == "source:a,b"
        assert resume_scope_for(["a", "a"]) == "source:a"

    def test_parse_source_keys_accepts_both_forms(self) -> None:
        assert parse_source_keys(None) is None
        assert parse_source_keys([]) is None
        assert parse_source_keys(["a", "b"]) == ["a", "b"]
        assert parse_source_keys(["a,b"]) == ["a", "b"]
        assert parse_source_keys(["a, b", "c"]) == ["a", "b", "c"]
        assert parse_source_keys([" , "]) is None


def _verdict_line(output: str) -> str:
    """The command's own final verdict line (`PASS COMPLETE ...` / `PASS STOPPED EARLY ...`),
    which is required to be the LAST thing every terminating path writes to stdout."""
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines, "no stdout at all"
    return lines[-1]


class TestExitCodeContract:
    """OWNER RULING (2026-07-29): ANY termination that leaves work in the cohort exits NON-ZERO;
    exit zero is reserved for genuine cohort exhaustion.

    This command runs UNATTENDED across ~230k cards and a supervisor decides whether the pass
    finished by reading its exit status - so an envelope halt exiting 0 (which is what it used to
    do) told that supervisor the opposite of the truth. These tests pin the whole table down,
    including the two directions that are easy to get subtly wrong: the SAME stop condition can be
    complete or incomplete depending only on whether work is left (`--max-batches`), and the
    human-readable verdict line must never contradict the number.

    The stop CONDITIONS themselves are untouched by any of this - `TestStopConditions` and
    `TestThrottleBackoffAndRetry` above still own those, and still prove the halt hard-stops with
    no backoff and the throttle retries within its budget.
    """

    @STREAMING_ON
    def test_a_genuinely_exhausted_cohort_is_the_completed_case(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(4)
        _install_recording_dispatch(monkeypatch)

        assert _exit_code("--batch-size", "2") == 0
        output = capsys.readouterr().out

        assert "stopped_reason=cohort-exhausted" in output
        assert _verdict_line(output).startswith("PASS COMPLETE exit_code=0 reason=cohort-exhausted")

    @STREAMING_ON
    def test_a_pass_that_already_finished_still_exits_zero(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The bare relaunch after a completed pass - nothing remains, so nothing was left
        undone."""
        _cards(2)
        _install_recording_dispatch(monkeypatch)
        assert _exit_code("--batch-size", "10") == 0
        capsys.readouterr()

        recorder = _install_recording_dispatch(monkeypatch)
        assert _exit_code("--batch-size", "10") == 0
        output = capsys.readouterr().out

        assert recorder.calls == []
        assert "Nothing to do." in output
        assert _verdict_line(output).startswith("PASS COMPLETE exit_code=0 reason=cohort-exhausted")
        assert "is EMPTY" not in output  # it FINISHED; it was never empty

    @STREAMING_ON
    def test_an_empty_scope_exits_zero_but_says_so_loudly(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A `--source` key that EXISTS but whose drive has no indexed cards yet:
        complete-but-vacuous. Zero work remains, which is the ruling's own definition of complete,
        so it exits 0 - but the operator situation is real (the catalog import for that drive has
        not run), so it gets a loud warning rather than a fake failure. The other reading of this
        case, a MISSPELLED key, is caught far earlier and far more precisely as a code-1
        unknown-key error, so nothing is lost by exiting 0 here."""
        SourceFactory(key="empty_drive", name="Empty Drive")
        other = SourceFactory(key="stocked_drive", name="Stocked Drive")
        CardFactory(content_phash=1, source=other)
        recorder = _install_recording_dispatch(monkeypatch)

        assert _exit_code("--source", "empty_drive") == 0
        output = capsys.readouterr().out

        assert recorder.calls == []
        assert "is EMPTY" in output
        assert "no indexed cards with a content_phash yet" in output
        assert _verdict_line(output).startswith("PASS COMPLETE exit_code=0 reason=cohort-empty")

    @STREAMING_ON
    def test_max_batches_landing_exactly_on_exhaustion_is_complete(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The check is "is any work left", never "was the bound hit" - 4 cards in 2 batches of 2
        under --max-batches 2 is a finished pass, and exiting 5 there would send a supervisor
        chasing a run that had actually completed."""
        _cards(4)
        _install_recording_dispatch(monkeypatch)

        assert _exit_code("--batch-size", "2", "--max-batches", "2") == 0
        output = capsys.readouterr().out

        assert "reached exactly as the cohort ran out" in output
        assert _verdict_line(output).startswith("PASS COMPLETE exit_code=0 reason=cohort-exhausted")

    @STREAMING_ON
    def test_max_batches_with_cards_left_is_incomplete(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A deliberate operator bound, NOT a fault - but still an incomplete pass, and a
        supervisor cannot otherwise tell "you asked me to stop" from "I finished". Its own code
        (5) is what keeps that distinction available to one."""
        cards = _cards(6)
        _install_recording_dispatch(monkeypatch)

        assert _exit_code("--batch-size", "2", "--max-batches", "2") == 5
        output = capsys.readouterr().out

        assert "stopped_reason=max-batches-reached" in output
        assert "This is the bound you asked for, not a fault" in output
        verdict = _verdict_line(output)
        assert verdict.startswith("PASS STOPPED EARLY exit_code=5 reason=max-batches-reached")
        assert f"resume_pk={cards[3].pk}" in verdict

    @STREAMING_ON
    def test_max_batches_truncating_a_sample_is_incomplete_too(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """A --sample run has no pk-walk left to probe, so "is any work left" is answered from the
        sample offset instead - the same question, the same answer."""
        _cards(40)
        _install_recording_dispatch(monkeypatch)

        assert _exit_code("--sample", "8", "--batch-size", "2", "--max-batches", "2") == 5
        assert _verdict_line(capsys.readouterr().out).startswith("PASS STOPPED EARLY exit_code=5")

    @STREAMING_ON
    def test_a_sample_that_runs_out_exactly_on_the_bound_is_complete(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(40)
        _install_recording_dispatch(monkeypatch)

        assert _exit_code("--sample", "4", "--batch-size", "2", "--max-batches", "2") == 0
        assert _verdict_line(capsys.readouterr().out).startswith("PASS COMPLETE exit_code=0")

    @STREAMING_ON
    @pytest.mark.parametrize("halt_status", ["halted-open-trip", "halted-new-trip"])
    def test_both_envelope_halt_statuses_exit_three(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, halt_status: str
    ) -> None:
        """THE bug this change exists to fix: both halt statuses used to exit ZERO, so a supervisor
        reading exit 0 on a trip recorded a full-catalog pass as complete with ~229k cards
        untouched. The hard stop itself is unchanged - still immediate, still no retry, no backoff,
        no self-resume (proved by TestStopConditions above); only the report changed."""
        cards = _cards(6)
        waits = _install_sleep_recorder(monkeypatch)
        recorder = _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="completed", card_ids=[cards[0].pk, cards[1].pk]),
                DispatchOutcome(status=halt_status, trip_id="envtrip-test"),
            ],
        )

        assert _exit_code("--batch-size", "2") == 3
        output = capsys.readouterr().out

        assert len(recorder.calls) == 2  # stopped AT the halt, no retry past it
        assert waits == []  # and no backoff on the halt path, ever
        verdict = _verdict_line(output)
        assert verdict.startswith("PASS STOPPED EARLY exit_code=3 reason=envelope-halt")
        assert f"resume_pk={cards[1].pk}" in verdict  # the halted batch's own pks are NOT claimed
        assert "resolve_envelope_trip" in output

    @STREAMING_ON
    def test_the_throttle_budget_and_the_envelope_halt_have_different_codes(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The operationally expensive distinction: 4 is safe for a supervisor to relaunch
        unattended once the cap frees up, 3 must NEVER be auto-relaunched because the trip needs a
        human acknowledgement first and a relaunch would only re-trip."""
        _cards(4)
        _install_sleep_recorder(monkeypatch)
        _install_recording_dispatch(monkeypatch, outcomes=[DispatchOutcome(status="throttled-concurrency-cap")] * 10)

        assert (
            _exit_code(
                "--batch-size",
                "2",
                "--max-throttle-retries",
                "1",
                "--throttle-backoff-initial",
                "0.01",
                "--throttle-backoff-max",
                "0.01",
            )
            == 4
        )
        assert _verdict_line(capsys.readouterr().out).startswith(
            "PASS STOPPED EARLY exit_code=4 reason=throttle-retries-exhausted"
        )

    @STREAMING_ON
    def test_a_stage_zero_failure_exits_two_and_says_the_pass_never_started(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _cards(4)
        recorder = _install_recording_dispatch(monkeypatch)
        monkeypatch.setattr(stream_full_catalog, "_is_fresh", lambda path, entry: False)

        assert _exit_code("--require-fresh") == 2
        output = capsys.readouterr().out

        assert recorder.calls == []
        assert _verdict_line(output).startswith("PASS STOPPED EARLY exit_code=2 reason=stage-0-freshness-failed")

    def test_the_streaming_gate_exits_six_with_the_whole_cohort_left(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """`stream_backstop_sweep`/`stage_e_shakedown` may exit 0 here - they are cron-invoked and
        have a next scheduled run. THIS COMMAND HAS NO NEXT INVOCATION, so a silent zero would
        record a full-catalog pass as complete having dispatched nothing at all."""
        _cards(3)
        recorder = _install_recording_dispatch(monkeypatch)

        assert _exit_code() == 6
        output = capsys.readouterr().out

        assert recorder.calls == []
        assert _verdict_line(output).startswith("PASS STOPPED EARLY exit_code=6 reason=streaming-disabled")

    @STREAMING_ON
    def test_a_stopped_early_verdict_always_carries_a_resume_pk_and_a_relaunch_argument(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Requirement 4 of the ruling, as its own test: the verdict line is what an operator
        reading a truncated multi-hour log looks for, so a stopped-early one has to be actionable
        on its own."""
        source = SourceFactory(key="d", name="D")
        cards = [CardFactory(content_phash=i, source=source) for i in (1, 2, 3, 4)]
        _install_recording_dispatch(monkeypatch)

        assert _exit_code("--source", "d", "--batch-size", "2", "--max-batches", "1") == 5
        verdict = _verdict_line(capsys.readouterr().out)

        assert "scope=source:d" in verdict
        assert f"resume_pk={cards[1].pk}" in verdict
        assert f"--start-pk {cards[1].pk}" in verdict

    @STREAMING_ON
    def test_the_verdict_line_never_disagrees_with_the_exit_code(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The invariant behind the whole table, checked across a completed pass, a halt and an
        operator bound in one go: whatever the code is, the words agree with it, and the number in
        the words IS the number the process exits with. Each scenario gets its OWN --source scope
        so neither the cohort nor the resume mark leaks between them."""
        scenarios = [
            (["--batch-size", "10"], None, 0),
            (["--batch-size", "1"], [DispatchOutcome(status="halted-new-trip", trip_id="t")], 3),
            (["--batch-size", "1", "--max-batches", "1"], None, 5),
        ]
        for index, (argv, outcomes, expected) in enumerate(scenarios):
            key = f"verdict{index}"
            source = SourceFactory(key=key, name=key)
            for phash in range(1, 5):
                CardFactory(content_phash=phash, source=source)
            _install_recording_dispatch(monkeypatch, outcomes=outcomes)
            capsys.readouterr()

            code = _exit_code("--source", key, *argv)
            verdict = _verdict_line(capsys.readouterr().out)

            assert code == expected, argv
            assert f"exit_code={code}" in verdict, verdict
            assert verdict.startswith("PASS COMPLETE" if code == 0 else "PASS STOPPED EARLY"), verdict


class TestBatchSizeAutoscaling:
    """2026-07-29 - `--batch-size` defaults to `auto`, which hands the decision to
    `cardpicker.stage_e_batch_sizing`. The rule itself is tested in
    `test_stage_e_batch_sizing.py`; what is tested HERE is the plumbing: that this driver asks in
    BULK mode, that the flag and a pinned setting still win, and that the decision is visible in
    the log."""

    @STREAMING_ON
    def test_the_default_invocation_asks_for_a_bulk_size(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        # The whole-catalogue pass is the case the owner directive is about. If this driver ever
        # started asking for the INCREMENTAL size the pass would silently run at 25 again, which is
        # exactly the regression this change exists to prevent - and it would be invisible, because
        # a 25-card batch is not wrong, just slow.
        asked: List[dict] = []
        # The REAL callable captured before the patch - re-reading the module attribute inside the
        # spy would call the spy, which is an infinite recursion rather than a passthrough.
        real = stream_full_catalog.resolve_micro_batch_size

        def _spy(**kwargs: Any) -> Any:
            asked.append(kwargs)
            return real(**kwargs)

        monkeypatch.setattr(stream_full_catalog, "resolve_micro_batch_size", _spy)
        _cards(1)
        _install_recording_dispatch(monkeypatch)

        with override_settings(STAGE_E_MICRO_BATCH_SIZE=None):
            call_command("stream_full_catalog")

        assert asked and asked[0]["mode"] == batch_sizing.MODE_BULK
        assert asked[0]["explicit"] is None

    @STREAMING_ON
    def test_an_explicit_flag_still_wins_over_the_rule(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        # The binding design property of this command: changing a setting must cost a kill and a
        # relaunch, never a rebuild. Autoscaling must not take the flag away.
        cards = _cards(4)
        recorder = _install_recording_dispatch(monkeypatch)

        with override_settings(STAGE_E_MICRO_BATCH_SIZE=None):
            call_command("stream_full_catalog", "--batch-size", "2")

        assert [call["card_ids"] for call in recorder.calls] == [
            [cards[0].pk, cards[1].pk],
            [cards[2].pk, cards[3].pk],
        ]

    @STREAMING_ON
    def test_a_pinned_setting_wins_over_the_rule(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = _cards(3)
        recorder = _install_recording_dispatch(monkeypatch)

        with override_settings(STAGE_E_MICRO_BATCH_SIZE=3):
            call_command("stream_full_catalog")

        assert [call["card_ids"] for call in recorder.calls] == [[c.pk for c in cards]]

    @STREAMING_ON
    def test_the_chosen_size_and_its_derivation_are_printed_before_batch_zero(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        _cards(1)
        _install_recording_dispatch(monkeypatch)

        with override_settings(STAGE_E_MICRO_BATCH_SIZE=None):
            call_command("stream_full_catalog")

        out = capsys.readouterr().out
        assert "Batch sizing:" in out
        assert "source=autoscale" in out
        assert "bound_by=" in out

    @STREAMING_ON
    def test_dry_run_reports_the_sizing_it_would_have_used(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        _cards(1)
        _install_recording_dispatch(monkeypatch)

        with override_settings(STAGE_E_MICRO_BATCH_SIZE=None):
            call_command("stream_full_catalog", "--dry-run")

        assert "Batch sizing:" in capsys.readouterr().out

    @pytest.mark.parametrize("spelling", ["auto", "AUTO", " auto "])
    def test_auto_is_accepted_in_any_case(self, spelling: str) -> None:
        assert stream_full_catalog.parse_batch_size_option(spelling) is None

    @pytest.mark.parametrize("spelling", ["0", "-1", "1.5", "big", "", "twenty-five"])
    def test_every_other_non_integer_spelling_is_rejected(self, spelling: str) -> None:
        # `auto` must be the ONLY word that means anything - a typo'd size has to be a loud error,
        # not a silent fallback to the rule, or an operator who meant `--batch-size 250` and typed
        # `--batch-size 25O` would never find out.
        with pytest.raises(CommandError):
            stream_full_catalog.parse_batch_size_option(spelling)

    def test_an_omitted_flag_parses_as_auto(self) -> None:
        assert stream_full_catalog.parse_batch_size_option(None) is None

    @pytest.mark.parametrize("spelling", ["1", "250", 250])
    def test_a_positive_size_parses_to_itself(self, spelling: Any) -> None:
        assert stream_full_catalog.parse_batch_size_option(spelling) == int(spelling)


class TestDestinationRateThrottleDegradesRatherThanHalting:
    """2026-07-30 OWNER RATE RULING: "the limit needs to be on the amount we are fetching from
    google api 7/s or hardware whichever comes first. and the limit needs to throttle not shut it
    down."

    The whole point of this class is the pair of tests below, which must move TOGETHER or the
    change is wrong in one of two opposite ways:

      * sustained RATE PRESSURE (Google answering 429/503) must SLOW the pass and let it finish,
        exiting ZERO with every card accounted for - never exit 3, never demand a human
        `resolve_envelope_trip` acknowledgement;
      * a GENUINE ENVELOPE BREACH (host load here; RSS, a 403 lockout and a non-throttle
        fetch-failure rate behave identically) must still HARD-STOP at exit 3, untouched.

    Before this change both produced the second behaviour, because a 429 reached
    `stage_e_dispatch`'s fetch-outcome window as an ordinary per-card failure and >1% of a rolling
    500-card window trips `EnvelopeTrip.Bar.FETCH_FAILURE_RATE`.
    """

    @STREAMING_ON
    def test_sustained_rate_pressure_degrades_and_completes_at_exit_zero(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """EVERY fetch in this pass is throttled - 100% rate pressure, far past the envelope's own
        >1% fetch-failure bar. The pass must still run to genuine cohort exhaustion and exit 0."""
        import cardpicker.image_cdn_fetch as image_cdn_fetch_module
        from cardpicker.harvest_fetch_limiter import DestinationThrottledError

        cards = _cards(6)
        stage_e_dispatch._window = stage_e_dispatch._FetchOutcomeWindow()

        def _throttled_fetch(card: Any, dpi: Any = None) -> bytes:
            raise DestinationThrottledError("429 - pacing interval widened")

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", _throttled_fetch)

        call_command("stream_full_catalog", "--batch-size", "2")  # exit 0: does not raise
        output = capsys.readouterr().out

        # No trip of ANY kind, and specifically not the fetch-failure-rate bar this used to hit.
        assert EnvelopeTrip.objects.count() == 0
        assert "Envelope halt" not in output
        # The run kept going through every batch rather than stopping at the first throttle.
        assert PilotRunLedger.objects.count() == 3
        # Throttles are reported as throttles, and are NEVER counted as fetch failures.
        assert f"stage_c_fetch_throttled={len(cards)}" in output
        assert "stage_c_fetch_failures=0" in output
        # The envelope's own window never saw them at all - the load-bearing assertion, since that
        # window is what the >1% bar is computed from.
        failures, total = stage_e_dispatch._window.failures_and_total()
        assert (failures, total) == (0, 0)

    @STREAMING_ON
    def test_a_genuine_envelope_breach_still_hard_stops_at_exit_three(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The other half of the pair. Rate pressure degrading must not have made the envelope
        itself soft: a real bar (host load 9.0 > the ratified 7.0 ceiling) still stops the pass
        dead, records a trip, and exits 3."""
        _cards(6)
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=9.0),
        )

        assert _exit_code("--batch-size", "1") == 3
        output = capsys.readouterr().out

        assert EnvelopeTrip.objects.filter(bar=EnvelopeTrip.Bar.HOST_LOAD).count() == 1
        assert "halted=halted-new-trip" in output
        assert output.count("Envelope halt") == 1  # one attempt, no retry, no self-resume

    @STREAMING_ON
    def test_non_throttle_fetch_failures_still_reach_the_envelope_window(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The narrowing is a narrowing, not a removal. A fetch that fails for a reason slowing
        down would NOT fix (a 404, a corrupt download - anything that arrives as `-> None`) still
        feeds `fetch_failures_in_window`, so the >1% bar keeps every bit of the reach it had for
        the failures it was actually written to catch."""
        import cardpicker.image_cdn_fetch as image_cdn_fetch_module

        _cards(4)
        stage_e_dispatch._window = stage_e_dispatch._FetchOutcomeWindow()
        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: None)

        call_command("stream_full_catalog", "--batch-size", "4")

        failures, total = stage_e_dispatch._window.failures_and_total()
        assert (failures, total) == (4, 4)
