"""
Tests for cardpicker.management.commands.reparse_legal_line_proxy_marker (JestaProxy ticket,
2026-07-23 - the retroactive re-derivation half of local_ocr.py's `_PROXY_MARKER_RE` widening).
No network calls, no live image fetch - this command consumes stored `ImageEvidence.
legal_line_raw_text` only, matching test_reparse_collector_evidence.py's own "network-free"
convention for its sibling command.
"""

from unittest.mock import patch

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from cardpicker.management.commands.reparse_legal_line_proxy_marker import (
    reparse_legal_line_proxy_marker,
    select_evidence_ids,
)
from cardpicker.models import PilotRunLedger
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory


def _evidence(card, **overrides):
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions={"legal_line": "legal-line-v1"},
        legal_line_raw_text="",
        legal_line_copyright_year="",
        legal_line_proxy_marker_detected=False,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestSelectEvidenceIds:
    def test_finds_false_rows_with_raw_text(self, db):
        card = CardFactory(name="Card A")
        evidence = _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")
        assert select_evidence_ids() == [evidence.pk]

    def test_excludes_true_rows(self, db):
        card = CardFactory(name="Card B")
        _evidence(card, legal_line_raw_text="NOT FOR SALE 2022", legal_line_proxy_marker_detected=True)
        assert select_evidence_ids() == []

    def test_excludes_null_rows(self, db):
        card = CardFactory(name="Card C")
        _evidence(card, legal_line_raw_text="", legal_line_proxy_marker_detected=None)
        assert select_evidence_ids() == []

    def test_excludes_empty_raw_text(self, db):
        card = CardFactory(name="Card D")
        _evidence(card, legal_line_raw_text="", legal_line_proxy_marker_detected=False)
        assert select_evidence_ids() == []


class TestReparseLegalLineProxyMarker:
    def test_flips_jestaproxy_example(self, db):
        card = CardFactory(name="Jesta Card")
        evidence = _evidence(card, legal_line_raw_text="2025 JestaProxy\nMTG © EN © ABIGAIL LARSON")

        result = reparse_legal_line_proxy_marker([evidence.pk], run_id="run-1", dry_run=True)

        assert result.considered == 1
        assert result.flipped_false_to_true == 1
        assert result.still_false == 0
        evidence.refresh_from_db()
        # dry run - nothing persisted yet.
        assert evidence.legal_line_proxy_marker_detected is False

    def test_flips_original_design_example(self, db):
        card = CardFactory(name="Trix Card")
        evidence = _evidence(card, legal_line_raw_text="> JOHN AVON\nTrixAreforScoot Original Design")

        result = reparse_legal_line_proxy_marker([evidence.pk], run_id="run-1", dry_run=True)

        assert result.flipped_false_to_true == 1

    def test_write_persists_the_flip(self, db):
        card = CardFactory(name="Jesta Card Write")
        evidence = _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        result = reparse_legal_line_proxy_marker([evidence.pk], run_id="run-1", dry_run=False)

        assert result.flipped_false_to_true == 1
        evidence.refresh_from_db()
        assert evidence.legal_line_proxy_marker_detected is True

    def test_leaves_genuinely_clean_rows_false(self, db):
        card = CardFactory(name="Clean Card")
        evidence = _evidence(card, legal_line_raw_text="158/287 R MOM EN GREG STAPLES")

        result = reparse_legal_line_proxy_marker([evidence.pk], run_id="run-1", dry_run=False)

        assert result.flipped_false_to_true == 0
        assert result.still_false == 1
        evidence.refresh_from_db()
        assert evidence.legal_line_proxy_marker_detected is False

    def test_never_flips_true_to_false(self, db):
        # module docstring's ADDITIVE-ONLY INVARIANT, exercised directly: a hand-built id list
        # (bypassing select_evidence_ids' own True-excluding filter) still leaves a True row
        # completely untouched rather than re-evaluating and possibly clearing it.
        card = CardFactory(name="Already True Card")
        evidence = _evidence(card, legal_line_raw_text="NOT FOR SALE 2022", legal_line_proxy_marker_detected=True)

        result = reparse_legal_line_proxy_marker([evidence.pk], run_id="run-1", dry_run=False)

        assert result.already_true == 1
        assert result.flipped_false_to_true == 0
        evidence.refresh_from_db()
        assert evidence.legal_line_proxy_marker_detected is True

    def test_idempotent_second_pass_is_a_no_op(self, db):
        card = CardFactory(name="Idempotent Card")
        evidence = _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        reparse_legal_line_proxy_marker([evidence.pk], run_id="run-1", dry_run=False)
        # second pass: the selector itself now excludes this row (it's True), matching the
        # command's own real re-run behaviour end to end.
        second_pass_ids = select_evidence_ids()
        assert evidence.pk not in second_pass_ids

        result = reparse_legal_line_proxy_marker([evidence.pk], run_id="run-2", dry_run=False)
        assert result.already_true == 1
        assert result.flipped_false_to_true == 0

    def test_audit_sample_is_capped(self, db):
        CardFactory(name="Audit Card")
        evidence_ids = [
            _evidence(CardFactory(name=f"Audit Card {i}"), legal_line_raw_text=f"{i} JestaProxy MTG EN").pk
            for i in range(5)
        ]

        result = reparse_legal_line_proxy_marker(evidence_ids, run_id="run-1", dry_run=True, audit_sample_size=2)

        assert result.flipped_false_to_true == 5
        assert len(result.audit) == 2


class TestReparseLegalLineProxyMarkerCommand:
    def test_dry_run_writes_nothing(self, db):
        card = CardFactory(name="Command Dry Run Card")
        evidence = _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        call_command("reparse_legal_line_proxy_marker")

        evidence.refresh_from_db()
        assert evidence.legal_line_proxy_marker_detected is False
        ledger = PilotRunLedger.objects.get(command="reparse_legal_line_proxy_marker")
        assert ledger.dry_run is True
        assert ledger.counters["flipped_false_to_true"] == 1

    def test_write_persists_and_records_ledger(self, db):
        card = CardFactory(name="Command Write Card")
        evidence = _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        call_command("reparse_legal_line_proxy_marker")  # dry-run first (forced-dry-run guard)
        call_command("reparse_legal_line_proxy_marker", write=True)

        evidence.refresh_from_db()
        assert evidence.legal_line_proxy_marker_detected is True
        ledger = PilotRunLedger.objects.filter(command="reparse_legal_line_proxy_marker", dry_run=False).get()
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.votes_written == 1

    def test_no_candidates_is_a_clean_no_op(self, db, capsys):
        call_command("reparse_legal_line_proxy_marker")

        printed = capsys.readouterr().out
        assert "nothing to do" in printed
        assert not PilotRunLedger.objects.filter(command="reparse_legal_line_proxy_marker").exists()

    def test_refuses_to_run_against_a_stale_image(self, db):
        with patch(
            "cardpicker.management.commands.reparse_legal_line_proxy_marker.find_stale_applied_migrations",
            return_value=[("cardpicker", "0099_fake_future_migration")],
        ):
            with pytest.raises(CommandError, match="STALE IMAGE"):
                call_command("reparse_legal_line_proxy_marker")

    def test_failure_marks_the_ledger_row_failed(self, db):
        card = CardFactory(name="Failure Card")
        _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        call_command("reparse_legal_line_proxy_marker")  # dry-run first (forced-dry-run guard)
        with patch(
            "cardpicker.management.commands.reparse_legal_line_proxy_marker.reparse_legal_line_proxy_marker",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                call_command("reparse_legal_line_proxy_marker", write=True)

        ledger = PilotRunLedger.objects.filter(command="reparse_legal_line_proxy_marker", dry_run=False).get()
        assert ledger.status == PilotRunLedger.Status.FAILED


class TestReparseLegalLineProxyMarkerCommandDryRunGuard:
    """Phase 0 rails (issues #362/#153's milestone, PR #373): the forced-dry-run guard
    (`scope=None` - module docstring's own SCOPE paragraph) wired into this command's own
    `Command.handle()`."""

    def test_write_refused_without_a_prior_dry_run(self, db):
        card = CardFactory(name="Guard Card")
        _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("reparse_legal_line_proxy_marker", write=True)

    def test_write_succeeds_after_a_matching_dry_run(self, db):
        card = CardFactory(name="Guard Card 2")
        _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        call_command("reparse_legal_line_proxy_marker")  # dry-run (default)
        call_command("reparse_legal_line_proxy_marker", write=True)

        ledgers = list(PilotRunLedger.objects.filter(command="reparse_legal_line_proxy_marker").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True and ledgers[0].status == PilotRunLedger.Status.COMPLETED
        assert ledgers[1].dry_run is False and ledgers[1].status == PilotRunLedger.Status.COMPLETED

    def test_skip_dryrun_check_bypasses_the_guard_and_is_recorded(self, db, capsys):
        card = CardFactory(name="Guard Card 3")
        _evidence(card, legal_line_raw_text="2025 JestaProxy MTG EN")

        call_command("reparse_legal_line_proxy_marker", write=True, skip_dryrun_check=True)

        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" in printed
        ledger = PilotRunLedger.objects.get(command="reparse_legal_line_proxy_marker")
        assert ledger.counters["skip_dryrun_check_used"] is True
