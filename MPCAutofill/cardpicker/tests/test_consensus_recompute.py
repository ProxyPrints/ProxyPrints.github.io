"""
Tests for cardpicker.management.commands.consensus_recompute - the apply-mode sibling of
consensus_impact_report. Uses the real default consensus weights/thresholds (unmodified
`settings.PRINTING_TAG_*`), same convention as test_consensus_impact_report.py/
test_purge_machine_votes.py's own header comments.
"""

from unittest.mock import patch

import pytest

from django.core.management import CommandError, call_command

from cardpicker.management.commands.consensus_recompute import run_consensus_recompute
from cardpicker.models import (
    ArtistVoteStatus,
    PilotRunLedger,
    PrintingTagStatus,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    TagFactory,
)


class TestRunConsensusRecomputeDryRun:
    def test_dry_run_performs_no_writes(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        prior_status = card.printing_tag_status
        prior_printing_id = card.inferred_canonical_card_id

        report = run_consensus_recompute(apply=False)

        card.refresh_from_db()
        assert card.printing_tag_status == prior_status
        assert card.inferred_canonical_card_id == prior_printing_id
        assert report["printing"]["written"] == 0
        assert report["artist"]["written"] == 0
        assert report["tag"]["written"] == 0

    def test_dry_run_reports_printing_promotion(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)

        report = run_consensus_recompute(apply=False)

        key = f"{PrintingTagStatus.UNRESOLVED}->{PrintingTagStatus.RESOLVED}"
        assert report["printing"]["transitions"][key] == 1
        assert card.identifier in report["printing"]["samples"][key]

    def test_dry_run_reports_artist_promotion(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)

        report = run_consensus_recompute(apply=False)

        key = f"{ArtistVoteStatus.UNRESOLVED}->{ArtistVoteStatus.RESOLVED}"
        assert report["artist"]["transitions"][key] == 1

    def test_dry_run_materializes_none_to_unresolved_for_a_machine_voted_tag_pair(self, db):
        # today's real-world shape: an OCR-only vote with no persisted tag_vote_statuses entry
        # at all - "before" reads as None, matching consensus_impact_report's own handling.
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)

        report = run_consensus_recompute(apply=False)

        key = f"None->{TagVoteStatus.UNRESOLVED}"
        assert report["tag"]["transitions"][key] == 1
        assert (card.identifier, "Borderless") in report["tag"]["samples"][key]
        assert report["tag"]["written"] == 0

    def test_dry_run_tag_batching_matches_unbatched_shape_across_many_pairs(self, db):
        # Several cards/tags at once, several with the same tag name across different cards -
        # exercises the batched grouping logic (_batched_tag_would_be_statuses) beyond a single
        # trivial pair, while still asserting against the exact same per-pair shape
        # consensus_impact_report's own (unbatched) _would_be_tag_status produces.
        borderless = TagFactory(name="Borderless")
        extended_art = TagFactory(name="Extended Art")
        cards = [CardFactory(tags=[]) for _ in range(4)]
        for card in cards:
            CardTagVoteFactory(card=card, tag=borderless, polarity=VotePolarity.APPLY, source=VoteSource.OCR)
        CardTagVoteFactory(card=cards[0], tag=extended_art, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        CardTagVoteFactory(card=cards[0], tag=extended_art, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        report = run_consensus_recompute(apply=False, batch_size=2)

        assert report["tag"]["checked"] == 5
        borderless_key = f"None->{TagVoteStatus.UNRESOLVED}"
        assert report["tag"]["transitions"][borderless_key] == 4
        extended_art_key = f"None->{TagVoteStatus.RESOLVED_APPLY}"
        assert report["tag"]["transitions"][extended_art_key] == 1


class TestRunConsensusRecomputeApply:
    def test_apply_materializes_unresolved_for_machine_voted_pair_with_no_status_row(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)
        assert card.tag_vote_statuses == {}

        report = run_consensus_recompute(apply=True)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.UNRESOLVED}
        assert card.tags == []  # UNRESOLVED never touches card.tags
        key = f"None->{TagVoteStatus.UNRESOLVED}"
        assert report["tag"]["transitions"][key] == 1
        assert report["tag"]["written"] == 1

    def test_apply_on_already_consistent_printing_pair_records_no_transition(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        resolve_and_persist_printing(card)  # already RESOLVED and consistent
        card.refresh_from_db()
        prior_status = card.printing_tag_status
        prior_printing_id = card.inferred_canonical_card_id

        report = run_consensus_recompute(apply=True)

        card.refresh_from_db()
        assert card.printing_tag_status == prior_status
        assert card.inferred_canonical_card_id == prior_printing_id
        assert dict(report["printing"]["transitions"]) == {}
        # printing always re-saves (no changed-guard in resolve_and_persist_printing itself) -
        # "written" still counts this card, but zero *transitions* is the correctness signal.
        assert report["printing"]["written"] == 1

    def test_apply_on_already_consistent_tag_pair_performs_zero_additional_writes(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.RESOLVED_APPLY}

        report = run_consensus_recompute(apply=True)

        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.RESOLVED_APPLY}
        assert dict(report["tag"]["transitions"]) == {}
        # resolve_and_persist_tag_votes' own changed-guard means a stable card performs zero
        # writes on re-run, unlike printing/artist above.
        assert report["tag"]["written"] == 0

    def test_apply_is_idempotent_across_two_runs(self, db):
        card = CardFactory(tags=[])
        printing = CanonicalCardFactory()
        artist = CanonicalArtistFactory()
        tag = TagFactory(name="Borderless")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.DEDUCTION)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.DEDUCTION)

        run_consensus_recompute(apply=True)
        card.refresh_from_db()
        state_after_first = (
            card.printing_tag_status,
            card.inferred_canonical_card_id,
            card.artist_vote_status,
            card.inferred_canonical_artist_id,
            dict(card.tag_vote_statuses),
            list(card.tags),
        )

        second_report = run_consensus_recompute(apply=True)
        card.refresh_from_db()
        state_after_second = (
            card.printing_tag_status,
            card.inferred_canonical_card_id,
            card.artist_vote_status,
            card.inferred_canonical_artist_id,
            dict(card.tag_vote_statuses),
            list(card.tags),
        )

        assert state_after_first == state_after_second
        assert dict(second_report["printing"]["transitions"]) == {}
        assert dict(second_report["artist"]["transitions"]) == {}
        assert dict(second_report["tag"]["transitions"]) == {}
        assert second_report["tag"]["written"] == 0  # second run changes nothing tag-side


class TestRunConsensusRecomputeBatchBoundary:
    def test_batch_size_one_still_processes_every_card_correctly(self, db):
        cards = []
        printing = CanonicalCardFactory()
        for _ in range(3):
            card = CardFactory()
            CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
            CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
            cards.append(card)

        report_batch_one = run_consensus_recompute(apply=True, batch_size=1)

        assert report_batch_one["printing"]["checked"] == 3
        assert report_batch_one["printing"]["written"] == 3
        for card in cards:
            card.refresh_from_db()
            assert card.printing_tag_status == PrintingTagStatus.RESOLVED

    def test_batch_boundary_does_not_change_dry_run_results_vs_a_single_batch(self, db):
        borderless = TagFactory(name="Borderless")
        for _ in range(5):
            card = CardFactory(tags=[])
            CardTagVoteFactory(card=card, tag=borderless, polarity=VotePolarity.APPLY, source=VoteSource.OCR)

        report_chunked = run_consensus_recompute(apply=False, batch_size=2)
        report_whole = run_consensus_recompute(apply=False, batch_size=10_000)

        assert dict(report_chunked["tag"]["transitions"]) == dict(report_whole["tag"]["transitions"])
        assert report_chunked["tag"]["checked"] == report_whole["tag"]["checked"] == 5


class TestConsensusRecomputeCommand:
    def test_command_defaults_to_dry_run_and_performs_no_writes(self, db, capsys):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)

        call_command("consensus_recompute")

        output = capsys.readouterr().out
        assert "[DRY RUN]" in output
        assert "Dry run complete - zero writes performed." in output
        card.refresh_from_db()
        assert card.tag_vote_statuses == {}

    def test_command_apply_materializes_status(self, db, capsys):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)

        # --skip-dryrun-check: this test exercises the apply path in isolation, not the
        # forced-dry-run guard (issue #362) - that guard has its own dedicated test class below.
        call_command("consensus_recompute", "--apply", "--skip-dryrun-check")

        output = capsys.readouterr().out
        assert "[APPLY]" in output
        assert "APPLY complete" in output
        card.refresh_from_db()
        assert card.tag_vote_statuses == {"Borderless": TagVoteStatus.UNRESOLVED}

    def test_command_refuses_to_run_against_a_stale_image(self, db):
        with patch(
            "cardpicker.management.commands.consensus_recompute.find_stale_applied_migrations",
            return_value=[("cardpicker", "0099_fake_future_migration")],
        ):
            with pytest.raises(CommandError, match="STALE IMAGE"):
                call_command("consensus_recompute")


class TestConsensusRecomputeLedger:
    """Phase 0 rails (issues #362/#153's milestone): consensus_recompute previously had NO
    PilotRunLedger row at all - this class covers the self-recording lifecycle added here,
    following local_calculate_verdicts's own exact RUNNING-at-start/COMPLETED-or-FAILED-at-end
    pattern, plus the counters-before-output hardening and forced-dry-run guard (issue #362)."""

    def test_dry_run_writes_a_completed_ledger_row_with_per_family_counters(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)

        call_command("consensus_recompute")

        ledger = PilotRunLedger.objects.get(command="consensus_recompute")
        assert ledger.dry_run is True
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None
        assert ledger.counters["tag"]["pairs_checked"] == 1
        assert ledger.counters["tag"]["rows_written"] == 0
        assert ledger.counters["tag"]["transitions"] == {f"None->{TagVoteStatus.UNRESOLVED}": 1}
        assert ledger.counters["printing"]["pairs_checked"] == 0
        assert ledger.counters["artist"]["pairs_checked"] == 0
        assert ledger.counters["total_written"] == 0

    def test_apply_writes_a_completed_ledger_row_with_rows_written(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)

        call_command("consensus_recompute", "--apply", "--skip-dryrun-check")

        ledger = PilotRunLedger.objects.get(command="consensus_recompute")
        assert ledger.dry_run is False
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["tag"]["rows_written"] == 1
        assert ledger.counters["total_written"] == 1

    def test_a_genuine_failure_marks_the_ledger_row_failed(self, db):
        with patch(
            "cardpicker.management.commands.consensus_recompute.run_consensus_recompute",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError):
                call_command("consensus_recompute", "--apply", "--skip-dryrun-check")

        ledger = PilotRunLedger.objects.get(command="consensus_recompute")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert ledger.finished_at is not None

    def test_broken_pipe_during_terminal_summary_does_not_flip_completed_to_failed(self, db, monkeypatch):
        """Production incident 2026-07-23: a client-side timeout severed stdout AFTER every write
        had already committed and the ledger row had already been saved COMPLETED - the terminal
        summary print must never be able to flip that back to FAILED."""
        import cardpicker.management.commands.consensus_recompute as cmd_module

        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.OCR)

        real_print = print

        def raising_print(*args, **kwargs):
            msg = args[0] if args else ""
            if isinstance(msg, str) and msg.startswith("APPLY complete"):
                raise BrokenPipeError("stdout severed")
            real_print(*args, **kwargs)

        monkeypatch.setattr(cmd_module, "print", raising_print, raising=False)

        call_command("consensus_recompute", "--apply", "--skip-dryrun-check")

        ledger = PilotRunLedger.objects.get(command="consensus_recompute")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.finished_at is not None


class TestConsensusRecomputeDryRunGuard:
    """The forced-dry-run guard itself (issue #362) - consensus_recompute always operates over
    the WHOLE voted pool, so scope=None: any matching recent dry-run of this command satisfies
    the guard, regardless of --batch-size/--sample-limit."""

    def test_apply_refused_without_a_prior_matching_dry_run(self, db):
        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("consensus_recompute", "--apply")
        assert not PilotRunLedger.objects.filter(command="consensus_recompute").exists()

    def test_apply_succeeds_after_a_matching_dry_run(self, db):
        call_command("consensus_recompute")  # dry-run (default)
        call_command("consensus_recompute", "--apply")

        ledgers = list(PilotRunLedger.objects.filter(command="consensus_recompute").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True and ledgers[0].status == PilotRunLedger.Status.COMPLETED
        assert ledgers[1].dry_run is False and ledgers[1].status == PilotRunLedger.Status.COMPLETED

    def test_skip_dryrun_check_bypasses_the_guard_and_is_recorded(self, db, capsys):
        call_command("consensus_recompute", "--apply", "--skip-dryrun-check")

        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" in printed
        ledger = PilotRunLedger.objects.get(command="consensus_recompute")
        assert ledger.counters["skip_dryrun_check_used"] is True
