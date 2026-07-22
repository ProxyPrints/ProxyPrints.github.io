"""
Tests for cardpicker.management.commands.consensus_impact_report - the read-only DRY-RUN audit
for the owner-ratified 2026-07-22 vote-weight scenario matrix. Uses the real default consensus
weights/thresholds (unmodified `settings.PRINTING_TAG_*`) so the arithmetic matches what a real
gated recompute would actually do in production, same convention as
test_purge_machine_votes.py's own header comment.
"""

import pytest

from django.core.management import call_command

from cardpicker.artist_consensus import resolve_and_persist_artist
from cardpicker.management.commands.consensus_impact_report import (
    compute_consensus_impact_report,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardTagVote,
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

# see test_printing_consensus.py for why this capture-and-restore fixture exists
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


class TestComputeConsensusImpactReportZeroWrites:
    def test_performs_no_writes_at_all(self, db):
        # decision B4's own shape: RESOLVED(2 USER) + 3 DEDUCTION dissent would, under the
        # RATIFIED resolver, stay RESOLVED (no transition) - but the point of this test is that
        # regardless of outcome, nothing on disk changes from calling the report function.
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        prior_status = card.printing_tag_status
        prior_printing_id = card.inferred_canonical_card_id

        compute_consensus_impact_report()

        card.refresh_from_db()
        assert card.printing_tag_status == prior_status
        assert card.inferred_canonical_card_id == prior_printing_id


class TestComputeConsensusImpactReportPrinting:
    def test_no_transition_when_unaffected(self, db):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        resolve_and_persist_printing(card)  # persists RESOLVED

        report = compute_consensus_impact_report()

        assert report["printing"]["checked"] == 1
        assert dict(report["printing"]["transitions"]) == {}

    def test_reports_a_b4_shaped_de_resolution_that_the_ratified_fix_prevents(self, db):
        # B4: RESOLVED(2 USER) persisted under OLD code's arithmetic, then 3 DEDUCTION dissent
        # votes arrive. Under the RATIFIED resolver (this repo's current code), this must NOT
        # be reported as a transition at all - D4 keeps it RESOLVED. This is the report's own
        # regression guard that the fix is actually wired in, not a hypothetical.
        card = CardFactory()
        printing_a = CanonicalCardFactory()
        printing_b = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing_a, source=VoteSource.USER)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        for _ in range(3):
            CardPrintingTagFactory(card=card, printing=printing_b, source=VoteSource.DEDUCTION)

        report = compute_consensus_impact_report()

        assert dict(report["printing"]["transitions"]) == {}

    def test_reports_a_real_unresolved_to_resolved_promotion(self, db):
        # D2 promotion: a lone human vote is persisted UNRESOLVED, then agreeing machine votes
        # arrive - the ratified resolver promotes this to RESOLVED, a real, reportable transition.
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)

        report = compute_consensus_impact_report()

        key = f"{PrintingTagStatus.UNRESOLVED}->{PrintingTagStatus.RESOLVED}"
        assert report["printing"]["transitions"][key] == 1
        assert card.identifier in report["printing"]["samples"][key]

    def test_sample_limit_is_respected(self, db):
        for _ in range(3):
            card = CardFactory()
            printing = CanonicalCardFactory()
            CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
            resolve_and_persist_printing(card)
            CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
            CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)
            CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.DEDUCTION)

        report = compute_consensus_impact_report(sample_limit=2)

        key = f"{PrintingTagStatus.UNRESOLVED}->{PrintingTagStatus.RESOLVED}"
        assert report["printing"]["transitions"][key] == 3
        assert len(report["printing"]["samples"][key]) == 2


class TestComputeConsensusImpactReportArtist:
    def test_no_transition_when_unaffected(self, db):
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        resolve_and_persist_artist(card)

        report = compute_consensus_impact_report()

        assert report["artist"]["checked"] == 1
        assert dict(report["artist"]["transitions"]) == {}

    def test_reports_a_real_unresolved_to_resolved_transition(self, db):
        # the persisted status simply hasn't caught up with the votes yet (e.g.
        # resolve_and_persist_artist was never called for this card) - a genuine, reportable
        # transition, not a false positive.
        card = CardFactory()
        artist = CanonicalArtistFactory()
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)

        report = compute_consensus_impact_report()

        key = f"{ArtistVoteStatus.UNRESOLVED}->{ArtistVoteStatus.RESOLVED}"
        assert report["artist"]["transitions"][key] == 1


class TestComputeConsensusImpactReportTag:
    def test_no_transition_when_unaffected(self, db):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()

        report = compute_consensus_impact_report()

        assert dict(report["tag"]["transitions"]) == {}

    def test_reports_the_d3_contested_to_unresolved_de_escalation(self, db):
        # D3: this pair was persisted CONTESTED under old code (both polarities voted, source-
        # agnostic); the ratified fix reclassifies it UNRESOLVED, since the only dissent is
        # machine-derived. Simulate the stale persisted status directly (as if written before
        # this fix landed), then confirm the report surfaces the reclassification.
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)
        for _ in range(3):
            CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.NOT_APPLICABLE, source=VoteSource.DEDUCTION)
        card.tag_vote_statuses = {"Borderless": TagVoteStatus.CONTESTED}
        card.save(update_fields=["tag_vote_statuses"])

        report = compute_consensus_impact_report()

        key = f"{TagVoteStatus.CONTESTED}->{TagVoteStatus.UNRESOLVED}"
        assert report["tag"]["transitions"][key] == 1
        assert (card.identifier, "Borderless") in report["tag"]["samples"][key]

    def test_a_pair_with_votes_but_no_persisted_entry_is_handled(self, db):
        # tag_vote_statuses has no entry for a tag that's never been through
        # resolve_and_persist_tag_votes - "before" reads as None, not a KeyError.
        card = CardFactory(tags=[])
        tag = TagFactory(name="Never Resolved")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.USER)

        report = compute_consensus_impact_report()

        key = f"None->{TagVoteStatus.UNRESOLVED}"
        assert report["tag"]["transitions"][key] == 1


class TestConsensusImpactReportCommand:
    def test_command_runs_end_to_end_without_error(self, db, capsys):
        card = CardFactory()
        printing = CanonicalCardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)

        call_command("consensus_impact_report")

        output = capsys.readouterr().out
        assert "DRY RUN" in output
        assert "Dry run complete - zero writes performed." in output

    def test_command_performs_no_writes(self, db, capsys):
        card = CardFactory(tags=[])
        tag = TagFactory(name="Borderless")
        CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source=VoteSource.ADMIN)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        prior_statuses = dict(card.tag_vote_statuses)
        prior_tags = list(card.tags)

        call_command("consensus_impact_report")

        card.refresh_from_db()
        assert dict(card.tag_vote_statuses) == prior_statuses
        assert list(card.tags) == prior_tags
        assert CardTagVote.objects.filter(card=card, tag=tag).count() == 1
