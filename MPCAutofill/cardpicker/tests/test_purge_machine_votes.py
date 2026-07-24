"""
Tests for cardpicker.management.commands.purge_machine_votes (docs/features/
catalog-completion-plan.md's Part 1). Uses the real default consensus weights
(settings.PRINTING_TAG_MIN_VOTES=2, PRINTING_TAG_MACHINE_WEIGHT=0.5, USER vote weight 1.0 -
confirmed live in vote_consensus._SOURCE_WEIGHTS) rather than overriding them, so the
arithmetic in these tests matches what a real purge would actually do in production.
"""

from django.core.management import call_command

from cardpicker.management.commands.purge_machine_votes import (
    purge_run,
    verify_no_machine_only_resolutions,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardPrintingTag,
    PilotRunLedger,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardPrintingTagFactory,
)


class TestPurgeRun:
    def test_dry_run_counts_without_deleting_anything(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )

        result = purge_run("run-A", dry_run=True)

        assert result.dry_run is True
        assert result.printing_votes_deleted == 1
        assert result.affected_card_count == 1
        assert CardPrintingTag.objects.filter(run_id="run-A").count() == 1  # untouched

    def test_purging_the_only_machine_votes_correctly_unresolves_the_card(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        # 1 human vote (weight 1.0) + 2 machine votes (weight 0.5 each) = 2.0, clears
        # min_weight=2 and is human-backed -> resolves.
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="phash-a", run_id="run-A"
        )
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = purge_run("run-A", dry_run=False)

        card.refresh_from_db()
        assert result.printing_votes_deleted == 2
        assert result.cards_unresolved_by_purge == 1
        assert result.gate_violations == []
        # 1.0 remaining < min_weight=2 - correctly un-resolved, NOT a violation (the task's
        # original "assert status returns to pre-run state" framing would have failed here,
        # since pre-run state was RESOLVED - this is the corrected invariant).
        assert card.printing_tag_status != PrintingTagStatus.RESOLVED
        assert CardPrintingTag.objects.filter(card=card).count() == 1  # the human vote survives

    def test_purging_one_of_several_runs_leaves_the_card_correctly_resolved(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        # 1 human (1.0) + 3 machine votes (0.5 each = 1.5) = 2.5 total. Purging ONE machine
        # vote (run-A) still leaves 1.0 + 1.0 = 2.0 >= min_weight=2 - stays resolved, and a
        # human-backed vote survives, so this must NOT be a violation.
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="phash-a", run_id="run-B"
        )
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="fallback-a", run_id="run-B"
        )
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = purge_run("run-A", dry_run=False)

        card.refresh_from_db()
        assert result.printing_votes_deleted == 1
        assert result.cards_unresolved_by_purge == 0
        assert result.gate_violations == []
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED
        assert card.inferred_canonical_card_id == printing.pk

    def test_purge_updates_the_ledger_purged_at(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        ledger_entry = PilotRunLedger.objects.create(
            run_id="run-A", command="local_identify_printing_tags", status=PilotRunLedger.Status.COMPLETED
        )
        assert ledger_entry.purged_at is None

        purge_run("run-A", dry_run=False)

        ledger_entry.refresh_from_db()
        assert ledger_entry.purged_at is not None

    def test_a_missing_ledger_row_does_not_block_the_purge(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-orphaned"
        )

        result = purge_run("run-orphaned", dry_run=False)

        assert result.printing_votes_deleted == 1
        assert not CardPrintingTag.objects.filter(run_id="run-orphaned").exists()


class TestVerifyNoMachineOnlyResolutions:
    """Directly exercises the assertion function against a manually-constructed 'impossible'
    state (resolve_weighted_consensus's own human-backed gate should make this unreachable
    through the normal purge flow - same 'structurally impossible but verify against real
    data' philosophy as local_identify_printing_tags.verify_zero_resolutions)."""

    def test_clean_state_produces_no_violations(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        resolve_and_persist_printing(card)

        assert verify_no_machine_only_resolutions([card.pk]) == []

    def test_catches_a_card_resolved_with_only_machine_sourced_survivors(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        # deliberately bypasses resolve_and_persist_printing - directly forces the DB into the
        # state the human-backed gate is supposed to make unreachable.
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a")
        card.printing_tag_status = PrintingTagStatus.RESOLVED
        card.inferred_canonical_card = printing
        card.save(update_fields=["printing_tag_status", "inferred_canonical_card"])

        assert verify_no_machine_only_resolutions([card.pk]) == [card.pk]

    def test_catches_an_artist_resolved_with_only_machine_sourced_survivors(self, db):
        artist = CanonicalArtistFactory()
        card = CardFactory(name="Forest")
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.OCR, anonymous_id="art-hash-a")
        card.artist_vote_status = ArtistVoteStatus.RESOLVED
        card.inferred_canonical_artist = artist
        card.save(update_fields=["artist_vote_status", "inferred_canonical_artist"])

        assert verify_no_machine_only_resolutions([card.pk]) == [card.pk]


class TestPurgeMachineVotesCommand:
    def test_refuses_without_run_id(self, db):
        import pytest

        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("purge_machine_votes")

    def test_dry_run_prints_counts_and_deletes_nothing(self, db, capsys):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )

        call_command("purge_machine_votes", "--run-id=run-A", "--dry-run")

        printed = capsys.readouterr().out
        assert "[DRY RUN]" in printed
        assert "printing votes: 1" in printed
        assert CardPrintingTag.objects.filter(run_id="run-A").exists()

    def test_real_run_purges_and_passes_gate_check(self, db, capsys):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="phash-a", run_id="run-A"
        )
        resolve_and_persist_printing(card)

        call_command("purge_machine_votes", "--run-id=run-A")

        printed = capsys.readouterr().out
        assert "[WRITE]" in printed
        assert "Gate check passed" in printed
        assert not CardPrintingTag.objects.filter(run_id="run-A").exists()
