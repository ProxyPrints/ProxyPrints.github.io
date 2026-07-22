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
    CanonicalExpansionFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardPrintingTagFactory,
    CardTagVoteFactory,
    SourceFactory,
    TagFactory,
)

# see test_consensus_impact_report.py for why this capture-and-restore fixture exists
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


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

        call_command("consensus_recompute", "--apply")

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
