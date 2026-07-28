"""
Tests for cardpicker.management.commands.purge_machine_votes (docs/features/
catalog-completion-plan.md's Part 1). Uses the real default consensus weights
(settings.PRINTING_TAG_MIN_VOTES=2, PRINTING_TAG_MACHINE_WEIGHT=0.5, USER vote weight 1.0 -
confirmed live in vote_consensus._SOURCE_WEIGHTS) rather than overriding them, so the
arithmetic in these tests matches what a real purge would actually do in production.
"""

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cardpicker.management.commands.purge_machine_votes import (
    purge_all_machine,
    purge_run,
    verify_no_machine_only_resolutions,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardArtistVote,
    CardPrintingTag,
    CardTagVote,
    PilotRunLedger,
    PrintingTagStatus,
    PrintingTagVote,
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
    CardTagVoteFactory,
    PrintingTagVoteFactory,
    TagFactory,
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


class TestPurgeAllMachine:
    def test_deletes_machine_votes_with_null_and_stamped_run_ids_across_all_tables(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        artist = CanonicalArtistFactory()
        tag = TagFactory(name="funny")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        # NULL run_id - the rows purge_run can never reach
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ded-a")
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.OCR, anonymous_id="ocr-b", run_id="run-B")
        CardTagVoteFactory(card=card, tag=tag, source=VoteSource.OCR, anonymous_id="ocr-c")
        PrintingTagVoteFactory(
            printing=printing, tag=tag, source=VoteSource.DEDUCTION, anonymous_id="ded-b", run_id="run-C"
        )

        result = purge_all_machine(dry_run=False)

        assert result.all_machine is True
        assert result.printing_votes_deleted == 2
        assert result.artist_votes_deleted == 1
        assert result.tag_votes_deleted == 1
        assert result.printing_tag_votes_deleted == 1
        assert not CardPrintingTag.objects.exists()
        assert not CardArtistVote.objects.exists()
        assert not CardTagVote.objects.exists()
        assert not PrintingTagVote.objects.exists()
        assert result.affected_card_count == 1

    def test_human_votes_survive_in_every_table_including_null_and_shared_run_ids(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        artist = CanonicalArtistFactory()
        tag = TagFactory(name="funny")
        # one machine vote per table, all stamped run-A ...
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        CardArtistVoteFactory(
            card=card, artist=artist, source=VoteSource.DEDUCTION, anonymous_id="ded-a", run_id="run-A"
        )
        CardTagVoteFactory(card=card, tag=tag, source=VoteSource.OCR, anonymous_id="ocr-b", run_id="run-A")
        PrintingTagVoteFactory(printing=printing, tag=tag, source=VoteSource.OCR, anonymous_id="ocr-c", run_id="run-A")
        # ... alongside human votes - one SHARING the machine votes' run_id (proves the delete
        # filter is source-based, never run_id-based), the rest NULL run_id.
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1", run_id="run-A"
        )
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.ADMIN, anonymous_id="human-2")
        CardTagVoteFactory(card=card, tag=tag, source=VoteSource.USER, anonymous_id="human-3")
        PrintingTagVoteFactory(printing=printing, tag=tag, source=VoteSource.USER, anonymous_id="human-4")

        result = purge_all_machine(dry_run=False)

        assert result.printing_votes_deleted == 1
        assert result.artist_votes_deleted == 1
        assert result.tag_votes_deleted == 1
        assert result.printing_tag_votes_deleted == 1
        assert list(CardPrintingTag.objects.values_list("source", flat=True)) == [VoteSource.USER]
        assert CardArtistVote.objects.get().source == VoteSource.ADMIN
        assert CardTagVote.objects.get().source == VoteSource.USER
        assert PrintingTagVote.objects.get().source == VoteSource.USER

    def test_dry_run_deletes_nothing_and_reports_per_table_per_source_counts(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        artist = CanonicalArtistFactory()
        tag = TagFactory(name="funny")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ded-a")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        CardTagVoteFactory(card=card, tag=tag, source=VoteSource.OCR, anonymous_id="ocr-b")
        PrintingTagVoteFactory(printing=printing, tag=tag, source=VoteSource.OCR, anonymous_id="ocr-c", run_id="run-B")
        # not machine - must appear in no count
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER, anonymous_id="human-1")

        result = purge_all_machine(dry_run=True)

        assert result.dry_run is True
        assert result.all_machine is True
        assert result.per_table_source_counts == {
            "printing": {"deduction": 1, "ocr": 1},
            "artist": {},
            "tag": {"ocr": 1},
            "printing tag": {"ocr": 1},
        }
        assert result.printing_votes_deleted == 2
        assert result.artist_votes_deleted == 0
        assert result.tag_votes_deleted == 1
        assert result.printing_tag_votes_deleted == 1
        assert result.affected_card_count == 1
        assert CardPrintingTag.objects.count() == 2
        assert CardArtistVote.objects.count() == 1
        assert CardTagVote.objects.count() == 1
        assert PrintingTagVote.objects.count() == 1

    def test_federated_and_implicit_sources_count_as_machine_by_derivation(self, db):
        # _MACHINE_SOURCES is DERIVED from vote_consensus.is_human_backed_source, whose
        # machine-derived set includes FEDERATED (federation stub, no importer exists yet) and
        # IMPLICIT (the 2026-07-22 filter-chip signal) alongside DEDUCTION/OCR - this pins the
        # derivation so --all-machine's blast radius is explicit, not assumed.
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        tag = TagFactory(name="funny")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.FEDERATED, anonymous_id="fed-a", peer="peer-1"
        )
        CardTagVoteFactory(card=card, tag=tag, source=VoteSource.IMPLICIT, anonymous_id="imp-a")

        result = purge_all_machine(dry_run=False)

        assert result.printing_votes_deleted == 1
        assert result.tag_votes_deleted == 1
        assert not CardPrintingTag.objects.exists()
        assert not CardTagVote.objects.exists()

    def test_affected_cards_are_re_resolved_and_the_gate_runs(self, db):
        # mirrors TestPurgeRun.test_purging_the_only_machine_votes_correctly_unresolves_the_card,
        # with the machine votes split across a stamped run_id and NULL run_id (the combination
        # only --all-machine can reach).
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="phash-a")
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = purge_all_machine(dry_run=False)

        card.refresh_from_db()
        assert result.printing_votes_deleted == 2
        assert result.cards_unresolved_by_purge == 1  # re-resolution actually ran
        assert result.gate_violations == []  # and the machine-only-resolution gate ran clean
        assert card.printing_tag_status != PrintingTagStatus.RESOLVED
        assert CardPrintingTag.objects.filter(card=card).count() == 1

    def test_deletes_are_chunked_by_pk(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        for i in range(5):
            CardPrintingTagFactory(
                card=card, printing=printing, source=VoteSource.OCR, anonymous_id=f"ocr-{i}", run_id=f"run-{i}"
            )

        with CaptureQueriesContext(connection) as captured:
            result = purge_all_machine(dry_run=False, delete_chunk_size=2)

        assert result.printing_votes_deleted == 5
        assert not CardPrintingTag.objects.exists()
        deletes = [
            query["sql"]
            for query in captured
            if query["sql"].startswith("DELETE FROM") and "cardprintingtag" in query["sql"]
        ]
        # 5 rows in chunks of 2 = 3 DELETE statements; a single unbounded delete would be 1.
        assert len(deletes) == 3

    def test_stamps_purged_at_on_every_ledger_row_whose_run_id_had_votes(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a", run_id="run-A"
        )
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-b", run_id="run-B"
        )
        # NULL run_id - no ledger row by definition
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-c")
        # stamped run_id with no ledger row - skipped silently
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-d", run_id="run-orphan"
        )
        ledger_a = PilotRunLedger.objects.create(
            run_id="run-A", command="local_identify_printing_tags", status=PilotRunLedger.Status.COMPLETED
        )
        ledger_b = PilotRunLedger.objects.create(
            run_id="run-B", command="local_identify_printing_tags", status=PilotRunLedger.Status.COMPLETED
        )
        # a ledger row whose run_id had NO votes - must not be stamped
        ledger_z = PilotRunLedger.objects.create(
            run_id="run-Z", command="local_identify_printing_tags", status=PilotRunLedger.Status.COMPLETED
        )

        result = purge_all_machine(dry_run=False)

        assert result.ledger_rows_stamped == 2
        ledger_a.refresh_from_db()
        ledger_b.refresh_from_db()
        ledger_z.refresh_from_db()
        assert ledger_a.purged_at is not None
        assert ledger_b.purged_at is not None
        assert ledger_z.purged_at is None


class TestPurgeMachineVotesCommand:
    def test_refuses_with_neither_mode_flag(self, db):
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

    def test_refuses_with_both_run_id_and_all_machine(self, db):
        with pytest.raises(CommandError):
            call_command("purge_machine_votes", "--run-id=run-A", "--all-machine")

    def test_all_machine_dry_run_prints_per_source_counts_and_deletes_nothing(self, db, capsys):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.DEDUCTION, anonymous_id="ded-a", run_id="run-A"
        )

        call_command("purge_machine_votes", "--all-machine", "--dry-run")

        printed = capsys.readouterr().out
        assert "[DRY RUN]" in printed
        assert "--all-machine" in printed
        assert "printing votes: deduction=1, ocr=1 (total 2)" in printed
        assert "affected cards: 1" in printed
        assert CardPrintingTag.objects.count() == 2

    def test_all_machine_write_purges_and_passes_gate_check(self, db, capsys):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="phash-a", run_id="run-A"
        )
        resolve_and_persist_printing(card)

        call_command("purge_machine_votes", "--all-machine")

        printed = capsys.readouterr().out
        assert "[WRITE]" in printed
        assert "stamped purged_at on 0 PilotRunLedger row(s)." in printed
        assert "Gate check passed" in printed
        assert list(CardPrintingTag.objects.values_list("source", flat=True)) == [VoteSource.USER]

    def test_all_machine_gate_violation_raises_command_error(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a")

        # forces the structurally-impossible state (same trick as TestVerifyNoMachineOnlyResolutions)
        # to prove the --all-machine path still routes gate failures to CommandError.
        monkeypatch.setattr(
            "cardpicker.management.commands.purge_machine_votes.verify_no_machine_only_resolutions",
            lambda card_ids: [card.pk],
        )

        with pytest.raises(CommandError, match="GATE VIOLATION"):
            call_command("purge_machine_votes", "--all-machine")
