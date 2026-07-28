"""
Tests for cardpicker.management.commands.stage_e_shakedown (issue #465, the Stage E Phase 3
shakedown driver). Split into cohort-derivation coverage (`bug_a_tail_card_ids`, no real dispatch)
and driver-loop coverage (`handle()`, `dispatch_micro_batch` either stubbed to isolate chunking/
run_id-prefix behaviour or exercised for real via the SAME halt/throttle mechanisms
`test_stage_e_dispatch.py::TestBackstopSweep` already proves against `stream_backstop_sweep`).
"""

import datetime as dt
import re
from typing import Any

import psycopg2
import pytest

from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from cardpicker import stage_e_dispatch
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
)
from cardpicker.management.commands.stage_e_shakedown import (
    FORCE_ESCALATED_RUN_ID,
    WAVE_1_SOURCE_NAMES,
    _parse_reextracted_after,
    bug_a_tail_card_ids,
)
from cardpicker.models import EnvelopeTrip, ImageEvidence, PilotRunLedger
from cardpicker.stage_e_concurrency import _LOCK_NAMESPACE
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory, SourceFactory

STREAMING_ON = override_settings(STAGE_E_STREAMING_ENABLED=True)


def _blank_tail_evidence(card: Any, **overrides: Any) -> ImageEvidence:
    """A CURRENT, full-manifest ImageEvidence row carrying the Bug-A tail's own signature - the
    same "every field blank" shape `test_stage_e_dispatch.py::_full_evidence` builds, kept as its
    own local helper (rather than imported) since this module's own default `fetch_ok`/blank-text
    combination IS the thing under test, not incidental setup."""
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
        fetch_ok=True,
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
        legal_line_proxy_marker_detected=False,
        symbol_phash=None,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestParseReextractedAfter:
    def test_accepts_a_z_suffixed_iso_timestamp(self) -> None:
        parsed = _parse_reextracted_after("2026-07-25T00:00:00Z")
        assert parsed == dt.datetime(2026, 7, 25, 0, 0, 0, tzinfo=dt.timezone.utc)

    def test_naive_timestamp_is_treated_as_utc(self) -> None:
        parsed = _parse_reextracted_after("2026-07-25T00:00:00")
        assert parsed.tzinfo == dt.timezone.utc

    def test_garbage_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            _parse_reextracted_after("not-a-timestamp")

    def test_required_arg_missing_is_a_command_error(self, db: Any) -> None:
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("stage_e_shakedown")

    def test_garbage_value_surfaces_as_a_command_error(self, db: Any) -> None:
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("stage_e_shakedown", "--reextracted-after", "not-a-timestamp")


class TestBugATailCohortQuery:
    """`bug_a_tail_card_ids` - issue #418's own blank-tier-1 signature query, re-derived fresh,
    scoped to CURRENT evidence and to the still-open tail. Every test below builds exactly the
    minimal card+evidence combination needed to isolate ONE exclusion at a time."""

    def test_a_genuine_blank_tier_1_card_is_included(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card)

        assert list(bug_a_tail_card_ids()) == [card.pk]

    def test_fetch_ok_false_is_excluded(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card, fetch_ok=False)

        assert list(bug_a_tail_card_ids()) == []

    def test_non_blank_raw_text_is_excluded(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card, collector_line_raw_text="MOM-158")

        assert list(bug_a_tail_card_ids()) == []

    def test_whitespace_only_raw_text_still_counts_as_blank(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card, collector_line_raw_text="   \n  ")

        assert list(bug_a_tail_card_ids()) == [card.pk]

    def test_a_non_empty_collector_number_is_excluded(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card, collector_line_collector_number="158")

        assert list(bug_a_tail_card_ids()) == []

    def test_stale_evidence_from_a_prior_image_version_is_excluded(self, db: Any) -> None:
        card = CardFactory(content_phash=99)
        _blank_tail_evidence(card, content_hash=1)  # doesn't match the card's LIVE content_phash

        assert list(bug_a_tail_card_ids()) == []

    def test_ntx_0721_force_escalated_run_id_is_excluded(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card, run_id=FORCE_ESCALATED_RUN_ID)

        assert list(bug_a_tail_card_ids()) == []

    @pytest.mark.parametrize("source_name", sorted(WAVE_1_SOURCE_NAMES))
    def test_wave_1_sources_are_excluded(self, db: Any, source_name: str) -> None:
        source = SourceFactory(name=source_name)
        card = CardFactory(content_phash=1, source=source)
        _blank_tail_evidence(card)

        assert list(bug_a_tail_card_ids()) == []

    def test_a_non_wave_1_source_is_unaffected(self, db: Any) -> None:
        source = SourceFactory(name="SomeOtherSource")
        card = CardFactory(content_phash=1, source=source)
        _blank_tail_evidence(card)

        assert list(bug_a_tail_card_ids()) == [card.pk]

    def test_reextracted_after_excludes_a_card_already_re_scanned_this_epoch(self, db: Any) -> None:
        already_rescanned = CardFactory(content_phash=1)
        evidence = _blank_tail_evidence(already_rescanned)
        cutoff = timezone.now()
        # bypass auto_now (Model.save()'s own mechanism) to simulate a re-extraction that happened
        # AFTER the epoch cutoff, without needing a real Stage C pass in this test.
        ImageEvidence.objects.filter(pk=evidence.pk).update(updated_at=cutoff + dt.timedelta(seconds=1))

        still_pending = CardFactory(content_phash=2)
        pending_evidence = _blank_tail_evidence(still_pending)
        ImageEvidence.objects.filter(pk=pending_evidence.pk).update(updated_at=cutoff - dt.timedelta(seconds=1))

        assert list(bug_a_tail_card_ids(reextracted_after=cutoff)) == [still_pending.pk]
        # without the cutoff, both are still in the pool (proves the exclusion is additive, not a
        # replacement for the rest of the signature query).
        assert set(bug_a_tail_card_ids()) == {already_rescanned.pk, still_pending.pk}


def _now_cutoff() -> str:
    """A `--reextracted-after` value that's AFTER any evidence a test has already set up (auto_now
    stamps `updated_at` at creation time, which is always earlier than "now" evaluated here) - so
    the cohort query's own resume-filter exclusion never wrongly excludes fixture evidence a test
    wants to be genuinely pending, without needing every test to hand-roll a timestamp."""
    return timezone.now().isoformat()


def _install_ok_stage_c_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every dispatch this module's driver-loop tests trigger must actually complete Stage C/D
    without a real network fetch - reuses the exact same source-module-patch discipline
    `test_stage_e_dispatch.py`'s own `_install_stage_c_stub` establishes (a local copy here keeps
    this test module import-independent of that one's private helpers)."""
    import io

    from PIL import Image

    from cardpicker.image_evidence import ExtractionResult

    def _png_bytes() -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buffer, format="PNG")
        return buffer.getvalue()

    def _stub_compute(
        card_id: int,
        content_hash,
        image,
        fetch_latency_ms=0.0,
        profile=None,
        short_circuit=None,
        known_set_codes=None,
        md5_checksum=None,
        sha256_checksum=None,
    ):
        fields = {
            "fetch_ok": True,
            "collector_line_raw_text": "",
            "collector_line_set_code": "",
            "collector_line_collector_number": "",
            "legal_line_proxy_marker_detected": False,
            "symbol_phash": None,
        }
        return ExtractionResult(
            card_id=card_id,
            content_hash=content_hash,
            fields=fields,
            extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
        )

    import cardpicker.image_cdn_fetch as image_cdn_fetch_module
    import cardpicker.image_evidence as image_evidence_module

    monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: _png_bytes())
    monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _stub_compute)


class TestDriverChunkingAndRunIdPrefix:
    @STREAMING_ON
    def test_chunks_honor_batch_size_and_run_id_prefix_shape(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 6)]  # 5 cards
        for card in cards:
            _blank_tail_evidence(card)
        _install_ok_stage_c_stub(monkeypatch)

        call_command(
            "stage_e_shakedown",
            "--reextracted-after",
            _now_cutoff(),
            "--batch-size",
            "2",
        )
        output = capsys.readouterr().out

        # 5 cards / batch-size 2 -> 3 chunks (2, 2, 1) -> 3 dispatched batches.
        assert "DONE batches_dispatched=3/3" in output
        assert "cohort_size=5" in output

        run_ids = sorted(PilotRunLedger.objects.values_list("run_id", flat=True))
        assert len(run_ids) == 3
        # microsecond-precision invocation timestamp (drill-found fix, §7(b) - a date-only prefix
        # collided with PilotRunLedger.run_id's own UNIQUE constraint on a second same-day
        # invocation), all three batches from this ONE invocation sharing the same prefix.
        for i, run_id in enumerate(run_ids):
            assert re.fullmatch(rf"stage-e-shakedown-b2-\d{{8}}T\d{{12}}-{i}", run_id), run_id
        prefixes = {run_id.rsplit("-", 1)[0] for run_id in run_ids}
        assert len(prefixes) == 1  # same invocation -> same prefix, only the trailing chunk index varies

    @STREAMING_ON
    def test_two_same_day_invocations_produce_distinct_run_ids(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """The drill-found defect itself (§7(b)): a date-only run_id prefix made a SECOND
        same-day invocation collide with the first on PilotRunLedger.run_id's UNIQUE constraint,
        so a kill-and-resume (or any multi-invocation wave) died with IntegrityError at the very
        first batch's ledger create. Two back-to-back invocations here must produce entirely
        disjoint run_id sets."""
        card_one = CardFactory(content_phash=1)
        _blank_tail_evidence(card_one)
        _install_ok_stage_c_stub(monkeypatch)
        call_command("stage_e_shakedown", "--reextracted-after", _now_cutoff())
        first_run_ids = set(PilotRunLedger.objects.values_list("run_id", flat=True))
        assert len(first_run_ids) == 1

        card_two = CardFactory(content_phash=2)
        _blank_tail_evidence(card_two)
        # no IntegrityError - proves the fix; a pre-fix date-only prefix would collide here on any
        # day where both invocations happen to run within the same calendar day (i.e. always, in
        # practice, for a same-day kill-and-resume).
        call_command("stage_e_shakedown", "--reextracted-after", _now_cutoff())
        second_run_ids = set(PilotRunLedger.objects.values_list("run_id", flat=True)) - first_run_ids
        assert len(second_run_ids) == 1
        assert first_run_ids.isdisjoint(second_run_ids)

    @STREAMING_ON
    def test_max_batches_bounds_a_single_invocation(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 6)]  # 5 cards
        for card in cards:
            _blank_tail_evidence(card)
        _install_ok_stage_c_stub(monkeypatch)

        call_command(
            "stage_e_shakedown",
            "--reextracted-after",
            _now_cutoff(),
            "--batch-size",
            "1",
            "--max-batches",
            "2",
        )
        output = capsys.readouterr().out

        assert "DONE batches_dispatched=2/2" in output
        assert PilotRunLedger.objects.count() == 2

    @STREAMING_ON
    def test_limit_bounds_the_cohort_before_chunking(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 6)]  # 5 cards
        for card in cards:
            _blank_tail_evidence(card)
        _install_ok_stage_c_stub(monkeypatch)

        call_command(
            "stage_e_shakedown",
            "--reextracted-after",
            _now_cutoff(),
            "--batch-size",
            "10",
            "--limit",
            "3",
        )
        output = capsys.readouterr().out

        assert "cohort_size=3" in output

    @STREAMING_ON
    def test_empty_cohort_is_a_no_op(self, db: Any, capsys: pytest.CaptureFixture) -> None:
        call_command("stage_e_shakedown", "--reextracted-after", "2020-01-01T00:00:00Z")
        output = capsys.readouterr().out

        assert "Nothing to do." in output
        assert PilotRunLedger.objects.count() == 0

    @STREAMING_ON
    def test_force_reextract_actually_re_extracts_a_blank_tail_card(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end proof (not just the isolated dispatch_micro_batch-level proof in
        test_stage_e_dispatch.py::TestForceStageCReextract) that the driver actually passes
        force_stage_c_reextract=True through call_command - a card with CURRENT, full-manifest,
        but blank evidence gets a fresh Stage C pass rather than being silently skipped."""
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card)
        _install_ok_stage_c_stub(monkeypatch)

        call_command("stage_e_shakedown", "--reextracted-after", _now_cutoff())

        ledger = PilotRunLedger.objects.get()
        assert ledger.counters["stage_c_completed"] == 1
        assert ledger.counters["trigger_reason"] == "shakedown"


class TestDriverStopsOnHaltOrThrottle:
    @STREAMING_ON
    def test_stops_on_an_envelope_halt_without_touching_the_remaining_cohort(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 4)]
        for card in cards:
            _blank_tail_evidence(card)
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=9.0),
        )

        call_command("stage_e_shakedown", "--reextracted-after", _now_cutoff(), "--batch-size", "1")
        output = capsys.readouterr().out

        assert EnvelopeTrip.objects.filter(bar=EnvelopeTrip.Bar.HOST_LOAD).count() == 1
        assert "Envelope halt" in output
        assert "stopping (do not retry)" in output
        assert "halted=halted-new-trip" in output
        # stopped before any batch's own work happened - no ledger row at all (matches
        # dispatch_micro_batch's own halted-new-trip convention).
        assert PilotRunLedger.objects.count() == 0

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_stops_on_a_throttled_concurrency_cap_without_looping(self, db: Any, capsys: pytest.CaptureFixture) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 4)]
        for card in cards:
            _blank_tail_evidence(card)

        connection.ensure_connection()
        raw = psycopg2.connect(**connection.get_connection_params())
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, 0])
            (acquired,) = cursor.fetchone()
            assert acquired is True, "test setup failed to claim the only slot"
        try:
            call_command(
                "stage_e_shakedown",
                "--reextracted-after",
                _now_cutoff(),
                "--batch-size",
                "1",
                "--max-batches",
                "5",
            )
        finally:
            raw.close()

        output = capsys.readouterr().out
        assert "Driver stopped: dispatch slots saturated (throttled-concurrency-cap)" in output
        assert output.count("Driver stopped: dispatch slots saturated") == 1
        assert "batches_dispatched=0" in output
        assert "stopped_reason=throttled-concurrency-cap" in output
        assert PilotRunLedger.objects.count() == 0

    def test_disabled_by_default_is_a_no_op_before_the_cohort_is_ever_derived(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        """STAGE_E_STREAMING_ENABLED is False by default (settings.py) - this driver guards on it
        explicitly (same convention as stream_backstop_sweep.py's own handle()) rather than relying
        on dispatch_micro_batch's own per-chunk "disabled" status, so a disabled run never even
        derives the cohort, let alone loops over chunks reporting a false "completed" count."""
        card = CardFactory(content_phash=1)
        _blank_tail_evidence(card)

        call_command("stage_e_shakedown", "--reextracted-after", "2020-01-01T00:00:00Z")
        output = capsys.readouterr().out

        assert "no-op" in output
        assert "Cohort:" not in output
        assert PilotRunLedger.objects.count() == 0
