"""
Tests for `cardpicker.management.commands.backfill_survivor_pks` (2026-08-11).

Two styles, mirroring `test_stream_full_catalog.py`'s own split: driver-loop coverage with
`dispatch_micro_batch` stubbed (cohort selection, resume, dry-run, envelope-halt/throttle
handling, isolated from any real Stage C/D work), and one real-conveyor test proving the actual
claim this command exists for - that re-dispatching an incomplete row through the real
`dispatch_micro_batch` -> `_run_stage_d` -> `run_fallback_calculator` chain backfills
`survivor_pks`/`evidence_types_used` without touching the skip_reason or casting any vote.
"""

from typing import Any, List

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from cardpicker import stage_e_dispatch
from cardpicker.local_calculate_verdicts import (
    FALLBACK_ELIMINATED_SKIP_REASON,
    JOIN_KEY_ANONYMOUS_ID,
    STAGE_D_FALLBACK_ANONYMOUS_ID,
)
from cardpicker.management.commands import backfill_survivor_pks
from cardpicker.management.commands.backfill_survivor_pks import (
    RESUME_SCOPE,
    backfill_cohort_queryset,
)
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    PilotRunLedger,
    StageEFullCatalogCursor,
    VoteSource,
)
from cardpicker.stage_e_dispatch import DispatchOutcome
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
    ImageEvidenceFactory,
)
from cardpicker.tests.test_stage_e_dispatch import _SyncStagePoolStub

STREAMING_ON = override_settings(STAGE_E_STREAMING_ENABLED=True)


@pytest.fixture(autouse=True)
def _sync_stage_c_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same rationale as `test_stream_full_catalog.py`'s own identical fixture: this driver
    dispatches through the real `dispatch_micro_batch` -> `_run_stage_c` for every test that
    isn't stubbed at the `dispatch_micro_batch` boundary itself."""
    monkeypatch.setattr(stage_e_dispatch, "ThreadPoolExecutor", _SyncStagePoolStub)
    monkeypatch.setattr(stage_e_dispatch, "ProcessPoolExecutor", _SyncStagePoolStub)


def _exit_code(*argv: Any, **kwargs: Any) -> int:
    """Reproduces what `BaseCommand.run_from_argv` does with an unhandled `CommandError`
    (`sys.exit(exc.returncode)`) - the only thing a supervisor reading this command's exit status
    would ever see."""
    try:
        call_command("backfill_survivor_pks", *argv, **kwargs)
    except CommandError as exc:
        assert exc.returncode != 0, "a CommandError that exits 0 would report a failure as a success"
        return int(exc.returncode)
    return 0


class _RecordingDispatch:
    """Stands in for `dispatch_micro_batch` - same shape as
    `test_stream_full_catalog._RecordingDispatch`, patched onto the command module's own binding."""

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
    monkeypatch.setattr(backfill_survivor_pks, "dispatch_micro_batch", recorder)
    return recorder


def _install_sleep_recorder(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    waits: List[float] = []
    monkeypatch.setattr(backfill_survivor_pks, "_sleep", waits.append)
    return waits


def _incomplete_row(card: Any, *, skip_reason: str = FALLBACK_ELIMINATED_SKIP_REASON) -> CardScanLog:
    """A pre-#764 style `stage-d-fallback-v1` scan-log row: the calculator reached a computed
    skip, but the write path never carried `evidence_types_used`/`survivor_pks` onto the row -
    exactly the historical shape this command backfills."""
    return CardScanLog.objects.create(
        card=card,
        anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
        skip_reason=skip_reason,
        evidence_types_used=[],
        survivor_pks=None,
    )


def _complete_row(card: Any, *, skip_reason: str = FALLBACK_ELIMINATED_SKIP_REASON) -> CardScanLog:
    return CardScanLog.objects.create(
        card=card,
        anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
        skip_reason=skip_reason,
        evidence_types_used=["border"],
        survivor_pks=[],
    )


class TestCohortSelection:
    def test_a_row_missing_survivor_pks_is_in_the_cohort(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _incomplete_row(card)
        assert list(backfill_cohort_queryset()) == [card]

    def test_a_row_that_already_has_survivor_pks_is_excluded(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _complete_row(card)
        assert list(backfill_cohort_queryset()) == []

    def test_a_no_evidence_skip_never_enters_the_cohort(self, db: Any) -> None:
        """`FALLBACK_NO_EVIDENCE_SKIP_REASON` never reaches `calculate_fallback_verdict`, so
        `survivor_pks` is correctly `None` forever for it - not a row this command should touch."""
        card = CardFactory(content_phash=1)
        CardScanLog.objects.create(
            card=card,
            anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID,
            skip_reason="no-evidence",
            evidence_types_used=[],
            survivor_pks=None,
        )
        assert list(backfill_cohort_queryset()) == []

    def test_a_join_key_row_is_never_selected(self, db: Any) -> None:
        """Only `stage-d-fallback-v1` rows carry these two fields at all - a join-key skip row is
        out of scope regardless of its own field values."""
        card = CardFactory(content_phash=1)
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="ambiguous")
        assert list(backfill_cohort_queryset()) == []

    def test_a_card_with_both_an_old_and_a_backfilled_row_is_excluded(self, db: Any) -> None:
        """The self-terminating half: once ANY row for this anonymous_id on this card carries
        `survivor_pks`, the card drops out, regardless of an older incomplete row still sitting in
        the table (append-only, never updated in place)."""
        card = CardFactory(content_phash=1)
        _incomplete_row(card)
        _complete_row(card)
        assert list(backfill_cohort_queryset()) == []


class TestDryRun:
    @STREAMING_ON
    def test_dry_run_dispatches_nothing_and_does_not_touch_the_resume_mark(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        card = CardFactory(content_phash=1)
        _incomplete_row(card)
        recorder = _install_recording_dispatch(monkeypatch)

        assert _exit_code("--dry-run") == 0
        output = capsys.readouterr().out

        assert recorder.calls == []
        assert "1 row(s) would gain survivor_pks/evidence_types_used" in output
        assert StageEFullCatalogCursor.objects.filter(scope=RESUME_SCOPE).exists() is False
        # the row itself is untouched
        row = CardScanLog.objects.get(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
        assert row.survivor_pks is None
        assert row.evidence_types_used == []

    @STREAMING_ON
    def test_dry_run_exits_zero_even_with_an_empty_cohort(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_recording_dispatch(monkeypatch)
        assert _exit_code("--dry-run") == 0


class TestResume:
    @STREAMING_ON
    def test_high_water_mark_advances_after_every_completed_batch(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 5)]
        for card in cards:
            _incomplete_row(card)
        _install_recording_dispatch(monkeypatch)

        call_command("backfill_survivor_pks", "--batch-size", "2")

        assert StageEFullCatalogCursor.get_position(RESUME_SCOPE) == cards[-1].pk

    @STREAMING_ON
    def test_a_killed_run_resumes_where_it_stopped(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 7)]
        for card in cards:
            _incomplete_row(card)

        first = _install_recording_dispatch(monkeypatch)
        assert _exit_code("--batch-size", "2", "--max-batches", "2") == 5
        assert first.dispatched_ids == [c.pk for c in cards[:4]]

        second = _install_recording_dispatch(monkeypatch)
        call_command("backfill_survivor_pks", "--batch-size", "2")
        assert second.dispatched_ids == [c.pk for c in cards[4:]]

    @STREAMING_ON
    def test_a_halted_batch_is_not_recorded_as_done(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 5)]
        for card in cards:
            _incomplete_row(card)
        _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="completed", card_ids=[cards[0].pk, cards[1].pk]),
                DispatchOutcome(status="halted-new-trip", trip_id="envtrip-test"),
            ],
        )
        assert _exit_code("--batch-size", "2") == 3
        assert StageEFullCatalogCursor.get_position(RESUME_SCOPE) == cards[1].pk

        resumed = _install_recording_dispatch(monkeypatch)
        call_command("backfill_survivor_pks", "--batch-size", "2")
        assert resumed.dispatched_ids == [cards[2].pk, cards[3].pk]

    @STREAMING_ON
    def test_resume_pk_is_printed_on_every_exit_path(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 5)]
        for card in cards:
            _incomplete_row(card)
        _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="completed", card_ids=[cards[0].pk, cards[1].pk]),
                DispatchOutcome(status="halted-new-trip", trip_id="envtrip-test"),
            ],
        )
        assert _exit_code("--batch-size", "2") == 3
        output = capsys.readouterr().out
        assert f"RESUME scope={RESUME_SCOPE} resume_pk={cards[1].pk}" in output
        assert "PASS STOPPED EARLY exit_code=3" in output


class TestEnvelopeHalt:
    @STREAMING_ON
    def test_stops_on_an_envelope_halt_without_retrying(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 3)]
        for card in cards:
            _incomplete_row(card)
        waits = _install_sleep_recorder(monkeypatch)
        recorder = _install_recording_dispatch(
            monkeypatch, outcomes=[DispatchOutcome(status="halted-open-trip", trip_id="envtrip-test")]
        )

        assert _exit_code("--batch-size", "1", "--max-throttle-retries", "20") == 3
        output = capsys.readouterr().out

        assert waits == []  # no backoff on a halt, ever
        assert len(recorder.calls) == 1  # one attempt, not a retry loop
        assert "halted=halted-open-trip" in output
        assert PilotRunLedger.objects.count() == 0


class TestThrottleBackoffAndRetry:
    @STREAMING_ON
    def test_backs_off_and_retries_the_same_chunk(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 3)]
        for card in cards:
            _incomplete_row(card)
        waits = _install_sleep_recorder(monkeypatch)
        recorder = _install_recording_dispatch(
            monkeypatch,
            outcomes=[
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="throttled-concurrency-cap"),
                DispatchOutcome(status="completed", card_ids=[c.pk for c in cards]),
            ],
        )

        assert _exit_code("--batch-size", "10") == 0
        assert waits == [5.0, 10.0]
        assert len(recorder.calls) == 3
        assert recorder.calls[0]["card_ids"] == recorder.calls[2]["card_ids"]

    @STREAMING_ON
    def test_exhausting_the_retry_budget_exits_four(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        card = CardFactory(content_phash=1)
        _incomplete_row(card)
        _install_sleep_recorder(monkeypatch)
        _install_recording_dispatch(monkeypatch, outcomes=[DispatchOutcome(status="throttled-concurrency-cap")] * 3)

        assert _exit_code("--batch-size", "10", "--max-throttle-retries", "2") == 4


class TestStreamingDisabled:
    def test_exits_six_and_dispatches_nothing_when_streaming_is_off(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=1)
        _incomplete_row(card)
        recorder = _install_recording_dispatch(monkeypatch)

        assert _exit_code("--batch-size", "10") == 6
        assert recorder.calls == []


class TestRealConveyorBackfill:
    """The claim this command exists for, proved against the REAL `dispatch_micro_batch` ->
    `_run_stage_d` -> `run_fallback_calculator` chain rather than a stub: an incomplete row gets a
    NEW, complete sibling row; the old row is untouched; the skip_reason itself is unchanged; and
    no CardPrintingTag vote is ever cast for a card whose Stage D fallback pass only ever skips."""

    @STREAMING_ON
    def test_fields_populate_and_skip_reason_is_unchanged_and_no_vote_is_cast(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two candidate printings for the same card name: border evidence points at one, artist
        # evidence points at the other - their intersection is empty, so a genuine, deterministic
        # "eliminated" skip (never a match) - see TestCalculateFallbackVerdict's own identical
        # setup in test_local_calculate_verdicts.py.
        printing_a = CanonicalCardFactory(
            name="Test Card", expansion__code="mom", collector_number="158", artist__name="Rebecca Guay"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_a, border_color="black")
        printing_b = CanonicalCardFactory(
            name="Test Card", expansion__code="vow", collector_number="200", artist__name="Someone Else"
        )
        CanonicalPrintingMetadataFactory(canonical_card=printing_b, border_color="white")

        card = CardFactory(name="Test Card", content_phash=12345)
        ImageEvidenceFactory(
            card=card,
            content_hash=card.content_phash,
            extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
            collector_line_raw_text="",
            collector_line_set_code="",
            collector_line_collector_number="",
            legal_line_proxy_marker_detected=False,
            symbol_phash=None,
            layout_class="black",
            artist_ocr_name="Someone Else",
        )
        # A prior join-key pass already found no hit for this card - satisfies the fallback
        # calculator's own eligibility precondition regardless of what a fresh join-key pass (run
        # unconditionally as part of the same Stage D sequence) concludes this time.
        CardScanLog.objects.create(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text")
        old_row = _incomplete_row(card, skip_reason=FALLBACK_ELIMINATED_SKIP_REASON)

        call_command("backfill_survivor_pks", "--batch-size", "10")

        old_row.refresh_from_db()
        assert old_row.survivor_pks is None  # append-only: the old row is never rewritten
        assert old_row.evidence_types_used == []

        new_row = (
            CardScanLog.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID)
            .exclude(pk=old_row.pk)
            .get()
        )
        assert new_row.skip_reason == FALLBACK_ELIMINATED_SKIP_REASON  # outcome unchanged
        assert new_row.survivor_pks == []  # eliminated -> zero survivors, but now RECORDED
        assert set(new_row.evidence_types_used) == {"border", "artist"}

        assert list(backfill_cohort_queryset()) == []  # the card has dropped out of the cohort
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=STAGE_D_FALLBACK_ANONYMOUS_ID).count() == 0


class _VoteCastingDispatch:
    """Same recording shape as `_RecordingDispatch`, plus an optional side effect: on a given
    call index, cast real `CardPrintingTag` rows (stamped with THIS call's own `run_id`, exactly
    as the real conveyor stamps every vote it writes) before returning the stubbed outcome. Lets
    a test prove the fidelity gate reacts to genuine rows under this pass's own run identity,
    without needing to drive the real Stage D calculators to get there."""

    def __init__(self, outcomes: Any = None, votes_by_call_index: Any = None) -> None:
        self.calls: List[dict] = []
        self._outcomes = list(outcomes) if outcomes is not None else None
        self._votes_by_call_index = dict(votes_by_call_index) if votes_by_call_index is not None else {}

    def __call__(self, **kwargs: Any) -> DispatchOutcome:
        index = len(self.calls)
        self.calls.append(kwargs)
        for factory_kwargs in self._votes_by_call_index.get(index, []):
            CardPrintingTagFactory(run_id=kwargs["run_id"], **factory_kwargs)
        if self._outcomes:
            return self._outcomes.pop(0)
        return DispatchOutcome(status="completed", run_id=kwargs.get("run_id"), card_ids=list(kwargs["card_ids"]))


class TestFidelityGate:
    """`local_identify_printing_tags.run_fidelity_gate` wired into a real pass - the SAME shared
    gate `run_pipeline.py` calls at the end of its own pass, so both commands agree on what "the
    gate" means (see this command's own module docstring). Votes are cast by a stub dispatch
    rather than the real Stage D calculators - the gate's own reaction to genuine rows under this
    pass's `run_id` is what's under test here, not calculator internals (already covered by
    `TestRealConveyorBackfill` and `local_calculate_verdicts`'s own test suite)."""

    @STREAMING_ON
    def test_a_clean_pass_reports_the_gate_and_exits_ok(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        card = CardFactory(content_phash=1)
        _incomplete_row(card)
        printing = CanonicalCardFactory()
        # A single machine vote (weight 0.5) sits well below PRINTING_TAG_MIN_VOTES (2.0) on its
        # own - the card stays UNRESOLVED, so the gate has real rows to inspect and finds them
        # clean, rather than trivially reporting "nothing to check".
        monkeypatch.setattr(
            backfill_survivor_pks,
            "dispatch_micro_batch",
            _VoteCastingDispatch(votes_by_call_index={0: [dict(card=card, printing=printing, source=VoteSource.OCR)]}),
        )

        assert _exit_code("--batch-size", "10") == 0
        output = capsys.readouterr().out

        assert "FIDELITY GATE: clear over 1 cards." in output
        assert "FIDELITY GATE VIOLATION" not in output
        assert CardPrintingTag.objects.filter(card=card).count() == 1  # the vote stays written

    @STREAMING_ON
    def test_a_card_resolved_on_this_pass_own_machine_votes_makes_the_gate_fire_and_exit_seven(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The hard human-backed gate in `vote_consensus.resolve_weighted_consensus` means a
        card can never resolve from machine votes with literally zero human vote anywhere on it -
        that path is structurally closed. What this pass CAN do is cast the fresh machine vote
        that tips an already-borderline card (one stale human vote, short of quorum alone) over
        `PRINTING_TAG_MIN_VOTES` - a real card reaching RESOLVED on the strength of THIS pass's
        own machine votes, exactly the case this gate exists to report."""
        card = CardFactory(content_phash=1)
        _incomplete_row(card)
        printing = CanonicalCardFactory()
        # Pre-existing, stale human vote (weight 1.0) - short of the 2.0 quorum alone.
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, run_id="stale-earlier-run")
        # THIS pass casts two agreeing machine votes (0.5 each) under its own run_id - combined
        # weight 2.0, clears quorum, and the human-backed gate is satisfied by the stale vote
        # above, so the card genuinely resolves.
        monkeypatch.setattr(
            backfill_survivor_pks,
            "dispatch_micro_batch",
            _VoteCastingDispatch(
                votes_by_call_index={
                    0: [
                        dict(card=card, printing=printing, source=VoteSource.OCR),
                        dict(card=card, printing=printing, source=VoteSource.OCR),
                    ]
                }
            ),
        )

        assert _exit_code("--batch-size", "10") == 7
        output = capsys.readouterr().out

        assert "FIDELITY GATE VIOLATION: 1 card(s)" in output
        assert "PASS STOPPED EARLY exit_code=7 reason=fidelity-gate-violation" in output
        # never rolled back - every vote this pass cast stays written.
        assert CardPrintingTag.objects.filter(card=card, source=VoteSource.OCR).count() == 2

    @STREAMING_ON
    def test_an_envelope_halt_keeps_its_own_exit_code_even_with_a_violation_ready_to_fire(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """PRECEDENCE: an envelope halt keeps EXIT_ENVELOPE_HALT (3) and its own meaning
        unchanged, even when an earlier batch in the SAME pass already cast votes that would
        violate the gate. The gate is skipped entirely once a halt is seen - never merely
        non-overriding - so it can neither change the exit code nor add a second, conflicting
        report to a pass a human is already required to go acknowledge."""
        cards = [CardFactory(content_phash=i) for i in range(1, 5)]
        for card in cards:
            _incomplete_row(card)
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=cards[0], printing=printing, source=VoteSource.USER, run_id="stale-earlier-run")
        monkeypatch.setattr(
            backfill_survivor_pks,
            "dispatch_micro_batch",
            _VoteCastingDispatch(
                outcomes=[
                    DispatchOutcome(status="completed", card_ids=[cards[0].pk, cards[1].pk]),
                    DispatchOutcome(status="halted-new-trip", trip_id="envtrip-test"),
                ],
                votes_by_call_index={
                    0: [
                        dict(card=cards[0], printing=printing, source=VoteSource.OCR),
                        dict(card=cards[0], printing=printing, source=VoteSource.OCR),
                    ]
                },
            ),
        )
        # Sanity: the votes the first batch casts really would resolve the card and really would
        # violate the gate if it ran - otherwise this test could pass for the wrong reason.
        from cardpicker.printing_consensus import resolve_printing

        assert _exit_code("--batch-size", "2") == 3  # EXIT_ENVELOPE_HALT, unchanged
        output = capsys.readouterr().out

        assert resolve_printing(cards[0]) == printing
        assert "FIDELITY GATE: skipped" in output
        assert "FIDELITY GATE VIOLATION" not in output
        assert "halted=halted-new-trip" in output
        # nothing rolled back - the first batch's votes stay written despite the later halt.
        assert CardPrintingTag.objects.filter(card=cards[0], source=VoteSource.OCR).count() == 2
