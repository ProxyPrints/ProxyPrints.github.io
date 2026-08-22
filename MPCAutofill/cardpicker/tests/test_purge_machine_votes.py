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

from cardpicker.local_calculate_verdicts import _eligible_cards_queryset
from cardpicker.management.commands.purge_machine_votes import Command as PurgeCommand
from cardpicker.management.commands.purge_machine_votes import (
    purge_by_anonymous_id,
    purge_run,
    verify_no_machine_only_resolutions,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardArtistVote,
    CardPrintingTag,
    CardScanLog,
    CardTypes,
    PilotRunLedger,
    PrintingTagStatus,
    VoteSource,
    calculator_family,
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

    def test_a_card_resolved_via_a_human_vote_on_an_identity_group_twin_is_not_flagged(self, db):
        """
        issue #857: `resolve_printing` pools votes across a card's md5/phash identity group, so a
        human vote on ONE member resolves every member via that shared tally - `card`'s own
        `CardPrintingTag` rows can legitimately be machine-only while the resolution behind them
        is human-backed via a twin. The gate must pool the same way `resolve_printing` does, not
        flag the twin.
        """
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card, twin = (
            CardFactory(name="Forest", md5_checksum="shared-checksum"),
            CardFactory(name="Forest", md5_checksum="shared-checksum"),
        )
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-b")
        CardPrintingTagFactory(card=twin, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        twin.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED
        assert twin.printing_tag_status == PrintingTagStatus.RESOLVED

        assert verify_no_machine_only_resolutions([card.pk, twin.pk]) == []

    def test_a_genuinely_machine_only_resolution_across_the_group_still_fails(self, db):
        """The pooled check must still bite: no human vote anywhere in the identity group means
        a real violation, not just no human vote on the flagged card itself."""
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card, twin = (
            CardFactory(name="Forest", md5_checksum="shared-checksum-2"),
            CardFactory(name="Forest", md5_checksum="shared-checksum-2"),
        )
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-a")
        CardPrintingTagFactory(card=twin, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-b")
        # deliberately bypasses resolve_and_persist_printing - directly forces the DB into the
        # state the human-backed gate is supposed to make unreachable, same as the single-card
        # violation test above, but across the whole identity group this time.
        for c in (card, twin):
            c.printing_tag_status = PrintingTagStatus.RESOLVED
            c.inferred_canonical_card = printing
            c.save(update_fields=["printing_tag_status", "inferred_canonical_card"])

        assert verify_no_machine_only_resolutions([card.pk, twin.pk]) == [card.pk, twin.pk]


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


class TestPurgeByAnonymousId:
    """
    2026-07-28 `--anonymous-id` mode: one exact machine calculator's votes, across every run_id.
    Motivated by a defect in which `stage-d-illustration-v1` wrote votes for several mutually
    exclusive printings per card across many run_ids - unreachable by `--run-id` without
    replaying every run involved, and entirely unreachable for NULL-run_id rows.

    Deliberately NOT a `--all-machine` mode (PR #517, closed unmerged as too blunt) and
    deliberately not a wildcard/prefix/family mode - see the command module's own docstring.
    """

    # a real client-generated anonymous id shape (frontend/src/common/anonymousId.ts)
    HUMAN_UUID = "3f2a9c1e-7b64-4a0d-9c88-1e5f2b3d4a60"
    CALC = "stage-d-illustration-v1"

    def test_refuses_a_human_uuid(self, db):
        # THE human-vote guard: enforced in code, not by convention. calculator_family() returns
        # None for a UUID, and there is no flag that turns this off.
        assert calculator_family(self.HUMAN_UUID) is None
        with pytest.raises(CommandError, match="REFUSED"):
            purge_by_anonymous_id(self.HUMAN_UUID)

    @pytest.mark.parametrize(
        "anonymous_id", ["3f2a9c1e-7b64-4a0d-9c88-1e5f2b3d4a60", "", "not-versioned", "stage-d-illustration", "*"]
    )
    def test_refuses_anything_without_a_calculator_family(self, db, anonymous_id):
        with pytest.raises(CommandError):
            purge_by_anonymous_id(anonymous_id)

    def test_a_refused_id_deletes_nothing_at_all(self, db):
        card = CardFactory(name="Forest")
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id=self.HUMAN_UUID)
        CardScanLog.objects.create(card=card, anonymous_id=self.HUMAN_UUID, skip_reason="no-evidence")

        with pytest.raises(CommandError):
            purge_by_anonymous_id(self.HUMAN_UUID, include_scan_log=True)

        assert CardPrintingTag.objects.filter(anonymous_id=self.HUMAN_UUID).count() == 1
        assert CardScanLog.objects.filter(anonymous_id=self.HUMAN_UUID).count() == 1

    def test_deletes_that_ids_votes_across_every_run_id_including_null(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card_a, card_b, card_c = CardFactory(name="Forest"), CardFactory(name="Forest"), CardFactory(name="Forest")
        # the same calculator, three different run_ids - one of them NULL, which --run-id can
        # never reach because a NULL matches no run_id filter.
        CardPrintingTagFactory(
            card=card_a, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id="run-A"
        )
        CardPrintingTagFactory(
            card=card_b, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id="run-B"
        )
        CardPrintingTagFactory(
            card=card_c, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id=None
        )

        result = purge_by_anonymous_id(self.CALC)

        assert result.printing_votes_deleted == 3
        assert result.affected_card_count == 3
        assert not CardPrintingTag.objects.filter(anonymous_id=self.CALC).exists()

    def test_reaches_null_run_id_rows_that_the_run_id_mode_provably_cannot(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id=None)

        # the pre-existing mode cannot touch it, whatever run_id is supplied
        assert purge_run("run-A").printing_votes_deleted == 0
        assert CardPrintingTag.objects.filter(anonymous_id=self.CALC).count() == 1

        assert purge_by_anonymous_id(self.CALC).printing_votes_deleted == 1
        assert not CardPrintingTag.objects.filter(anonymous_id=self.CALC).exists()

    def test_covers_every_vote_table(self, db):
        """Three vote tables since 2026-07-29, not four: `PrintingTagVote` was retired (migration
        0101) with 0 rows, and `PurgeResult.printing_tag_votes_deleted` went with it. If a fourth
        vote model is ever added, it belongs in this assertion the same day it is added."""
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id=None)
        CardArtistVoteFactory(card=card, source=VoteSource.OCR, anonymous_id=self.CALC, run_id="run-A")
        CardTagVoteFactory(card=card, source=VoteSource.OCR, anonymous_id=self.CALC, run_id="run-B")

        result = purge_by_anonymous_id(self.CALC)

        assert (
            result.printing_votes_deleted,
            result.artist_votes_deleted,
            result.tag_votes_deleted,
        ) == (1, 1, 1)

    def test_other_calculators_and_other_versions_are_untouched(self, db):
        """One EXACT id per invocation - not a family, not a prefix. `-v2` of the same
        calculator is a different id and survives, and so does every other calculator."""
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC)
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id="stage-d-illustration-v2"
        )
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="local-ocr-v1")

        purge_by_anonymous_id(self.CALC)

        assert sorted(CardPrintingTag.objects.values_list("anonymous_id", flat=True)) == [
            "local-ocr-v1",
            "stage-d-illustration-v2",
        ]

    def test_human_backed_votes_are_never_deleted_even_under_a_calculator_id(self, db):
        """Second, independent layer of the human guard: `source__in=_MACHINE_SOURCES`. Even a
        well-formed calculator id cannot take a human-backed row with it."""
        expansion = CanonicalExpansionFactory(code="aaa")
        # two distinct printings: cardprintingtag_unique_printing_vote is (card, printing,
        # anonymous_id), so one id cannot hold two rows for the same printing on one card
        printing_human = CanonicalCardFactory(name="Forest", expansion=expansion, collector_number="1")
        printing_machine = CanonicalCardFactory(name="Forest", expansion=expansion, collector_number="2")
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing_human, source=VoteSource.USER, anonymous_id=self.CALC)
        CardPrintingTagFactory(card=card, printing=printing_machine, source=VoteSource.OCR, anonymous_id=self.CALC)

        result = purge_by_anonymous_id(self.CALC)

        assert result.printing_votes_deleted == 1
        assert [v.source for v in CardPrintingTag.objects.all()] == [VoteSource.USER]

    def test_dry_run_reports_per_table_counts_and_deletes_nothing(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC)
        CardArtistVoteFactory(card=card, source=VoteSource.OCR, anonymous_id=self.CALC)
        CardScanLog.objects.create(card=card, anonymous_id=self.CALC, skip_reason="no-text")

        result = purge_by_anonymous_id(self.CALC, dry_run=True, include_scan_log=True)

        assert result.dry_run is True
        assert result.printing_votes_deleted == 1
        assert result.artist_votes_deleted == 1
        assert result.scan_log_rows_deleted == 1
        assert CardPrintingTag.objects.count() == 1
        assert CardArtistVote.objects.count() == 1
        assert CardScanLog.objects.count() == 1

    def test_re_resolves_affected_cards_and_runs_the_gate(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        # 1 human (1.0) + 2 machine (0.5 each) = 2.0 -> resolves; removing one machine vote
        # correctly drops it back below quorum.
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="human-1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="local-ocr-v1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id=None)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = purge_by_anonymous_id(self.CALC)

        card.refresh_from_db()
        assert card.printing_tag_status != PrintingTagStatus.RESOLVED
        assert result.cards_unresolved_by_purge == 1
        assert result.gate_violations == []

    def test_does_not_stamp_the_pilot_run_ledger(self, db):
        """Contrast with `--run-id`: this mode removes ONE calculator's rows from a run whose
        other calculators' votes remain, so that run has not been purged and must not be
        recorded as purged."""
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(
            card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id="run-A"
        )
        ledger = PilotRunLedger.objects.create(run_id="run-A", command="local_calculate_verdicts")

        purge_by_anonymous_id(self.CALC)

        ledger.refresh_from_db()
        assert ledger.purged_at is None


class TestPurgeByAnonymousIdScanLog:
    """
    The `--include-scan-log` half. A vote purge alone does NOT make a calculator's cards eligible
    again: `local_calculate_verdicts._eligible_cards_queryset` excludes a card for EITHER an
    existing vote from that anonymous_id OR a non-rescannable `CardScanLog` row for it, and
    scan-log rows outnumber votes by roughly an order of magnitude live. Opt-in, because
    deleting them destroys the calculator's abstention audit trail.
    """

    CALC = "stage-d-illustration-v1"
    HUMAN_UUID = "3f2a9c1e-7b64-4a0d-9c88-1e5f2b3d4a60"

    def test_scan_logs_survive_when_the_flag_is_not_passed(self, db):
        card = CardFactory(name="Forest")
        CardScanLog.objects.create(card=card, anonymous_id=self.CALC, skip_reason="no-text")

        result = purge_by_anonymous_id(self.CALC)

        assert result.scan_log_rows_deleted == 0
        assert result.include_scan_log is False
        assert CardScanLog.objects.filter(anonymous_id=self.CALC).count() == 1

    def test_scan_logs_are_deleted_only_for_that_exact_id_when_the_flag_is_passed(self, db):
        card = CardFactory(name="Forest")
        CardScanLog.objects.create(card=card, anonymous_id=self.CALC, skip_reason="no-text")
        CardScanLog.objects.create(card=card, anonymous_id="stage-d-illustration-v2", skip_reason="no-text")
        CardScanLog.objects.create(card=card, anonymous_id="local-ocr-v1", skip_reason="no-text")

        result = purge_by_anonymous_id(self.CALC, include_scan_log=True)

        assert result.scan_log_rows_deleted == 1
        assert result.include_scan_log is True
        assert sorted(CardScanLog.objects.values_list("anonymous_id", flat=True)) == [
            "local-ocr-v1",
            "stage-d-illustration-v2",
        ]

    def test_the_human_uuid_refusal_covers_the_scan_log_path_too(self, db):
        card = CardFactory(name="Forest")
        CardScanLog.objects.create(card=card, anonymous_id=self.HUMAN_UUID, skip_reason="no-text")

        with pytest.raises(CommandError, match="REFUSED"):
            purge_by_anonymous_id(self.HUMAN_UUID, include_scan_log=True)

        assert CardScanLog.objects.filter(anonymous_id=self.HUMAN_UUID).count() == 1

    def test_dry_run_reports_scan_log_counts_without_deleting_them(self, db):
        card = CardFactory(name="Forest")
        for reason in ("no-text", "ambiguous", "no-evidence"):
            CardScanLog.objects.create(card=card, anonymous_id=self.CALC, skip_reason=reason)

        result = purge_by_anonymous_id(self.CALC, dry_run=True, include_scan_log=True)

        assert result.scan_log_rows_deleted == 3
        assert CardScanLog.objects.filter(anonymous_id=self.CALC).count() == 3

    def test_a_card_excluded_solely_by_a_scan_log_row_becomes_eligible_again(self, db):
        """
        The whole point of the flag, proved against the REAL eligibility query rather than a
        restatement of it: a card whose only exclusion is a non-rescannable scan-log row is
        still ineligible after a vote-only purge, and eligible again after one with the flag.
        """
        card = CardFactory(name="Forest", card_type=CardTypes.CARD, dpi=800)
        CardScanLog.objects.create(card=card, anonymous_id=self.CALC, skip_reason="unknown-set-code")

        assert card.pk not in set(_eligible_cards_queryset(self.CALC).values_list("pk", flat=True))

        purge_by_anonymous_id(self.CALC)  # votes only - the scan-log exclusion still stands
        assert card.pk not in set(_eligible_cards_queryset(self.CALC).values_list("pk", flat=True))

        purge_by_anonymous_id(self.CALC, include_scan_log=True)
        assert card.pk in set(_eligible_cards_queryset(self.CALC).values_list("pk", flat=True))


class TestPurgeModeMutualExclusivity:
    """
    Exactly one of --run-id / --anonymous-id is required, enforced in TWO places.

    Django 4.2's `call_command` maps a required mutually-exclusive group onto its kwargs form
    too, so both the CLI and `call_command(run_id=..., anonymous_id=...)` are caught by argparse
    (verified below by asserting argparse's OWN message, so this test fails loudly if a future
    Django stops doing that). `handle`'s own check is the layer beneath: it catches a direct
    `Command().handle(**kwargs)` call, which no parser ever sees.
    """

    def test_neither_flag_is_an_error(self, db):
        with pytest.raises(CommandError, match="one of the arguments"):
            call_command("purge_machine_votes")

    def test_both_flags_are_an_error_via_the_command_line(self, db):
        with pytest.raises(CommandError, match="not allowed with argument"):
            call_command("purge_machine_votes", "--run-id=run-A", "--anonymous-id=local-ocr-v1")

    def test_both_flags_are_an_error_via_call_command_kwargs(self, db):
        with pytest.raises(CommandError, match="not allowed with argument"):
            call_command("purge_machine_votes", run_id="run-A", anonymous_id="local-ocr-v1")

    def test_neither_flag_via_call_command_kwargs_is_an_error(self, db):
        with pytest.raises(CommandError, match="one of the arguments"):
            call_command("purge_machine_votes", dry_run=True)

    def test_handle_re_checks_beneath_the_parser(self, db):
        # the parser is bypassed entirely here - this is what handle()'s own check is for
        with pytest.raises(CommandError, match="exactly one"):
            PurgeCommand().handle(run_id="run-A", anonymous_id="local-ocr-v1", dry_run=True)
        with pytest.raises(CommandError, match="exactly one"):
            PurgeCommand().handle(dry_run=True)

    def test_include_scan_log_is_rejected_with_run_id(self, db):
        with pytest.raises(CommandError, match="only valid with --anonymous-id"):
            call_command("purge_machine_votes", "--run-id=run-A", "--include-scan-log")


class TestPurgeByAnonymousIdCommandOutput:
    CALC = "stage-d-illustration-v1"

    def test_write_output_names_the_exact_id_and_says_deleted_not_would_delete(self, db, capsys):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC, run_id=None)

        call_command("purge_machine_votes", f"--anonymous-id={self.CALC}")

        printed = capsys.readouterr().out
        assert "[WRITE]" in printed
        assert f"DELETED (target: --anonymous-id={self.CALC})" in printed
        assert "WOULD DELETE" not in printed
        assert "printing votes: 1" in printed
        assert "Gate check passed" in printed

    def test_dry_run_output_says_would_delete(self, db, capsys):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id=self.CALC)

        call_command("purge_machine_votes", f"--anonymous-id={self.CALC}", "--dry-run")

        printed = capsys.readouterr().out
        assert "[DRY RUN]" in printed
        assert f"WOULD DELETE (target: --anonymous-id={self.CALC})" in printed
        assert CardPrintingTag.objects.filter(anonymous_id=self.CALC).exists()

    def test_output_warns_about_scan_log_rows_left_in_place(self, db, capsys):
        card = CardFactory(name="Forest")
        CardScanLog.objects.create(card=card, anonymous_id=self.CALC, skip_reason="no-text")

        call_command("purge_machine_votes", f"--anonymous-id={self.CALC}")

        printed = capsys.readouterr().out
        assert "LEFT IN PLACE" in printed
        assert "--include-scan-log" in printed

    def test_output_reports_scan_log_deletions_separately_from_votes(self, db, capsys):
        card = CardFactory(name="Forest")
        CardScanLog.objects.create(card=card, anonymous_id=self.CALC, skip_reason="no-text")

        call_command("purge_machine_votes", f"--anonymous-id={self.CALC}", "--include-scan-log")

        printed = capsys.readouterr().out
        assert "CardScanLog rows (abstention audit trail, NOT votes): 1" in printed
        assert "LEFT IN PLACE" not in printed
        assert not CardScanLog.objects.exists()

    def test_a_refused_human_uuid_is_reported_at_the_command_level(self, db):
        with pytest.raises(CommandError, match="REFUSED"):
            call_command("purge_machine_votes", "--anonymous-id=3f2a9c1e-7b64-4a0d-9c88-1e5f2b3d4a60")
