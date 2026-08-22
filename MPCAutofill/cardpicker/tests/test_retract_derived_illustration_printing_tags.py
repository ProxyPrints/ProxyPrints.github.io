"""
Tests for cardpicker.management.commands.retract_derived_illustration_printing_tags - see that
module's own docstring for the pre-#900 bug and the identification method under test here.

Pre-#900 derived rows are constructed directly via `CardPrintingTag.objects.create(...)` /
`CardArtistVote.objects.create(...)` (matching the shape the buggy `cast_illustration_vote` code
path actually wrote - `source=VoteSource.USER` on the printing tag, `DERIVED_ARTIST_VOTE_SURFACE`
on the sibling artist vote) rather than through `cast_illustration_vote` itself, which - post-#900
- can no longer produce this shape at all; that is the entire point of #900's fix.
"""

from datetime import timedelta

from django.utils import timezone

from cardpicker.illustration_vote import DERIVED_ARTIST_VOTE_SURFACE
from cardpicker.management.commands.retract_derived_illustration_printing_tags import (
    SIBLING_CORRELATION_WINDOW,
    annotate_would_leave_resolved,
    find_derived_printing_tags,
)
from cardpicker.models import (
    CardArtistVote,
    CardPrintingTag,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardArtistVoteFactory,
    CardFactory,
    CardPrintingTagFactory,
)


def _cast_derived_pair(card, anonymous_id: str, printing=None, artist=None):
    """Writes the exact pre-#900 shape: a source=USER CardPrintingTag and its same-transaction
    DERIVED_ARTIST_VOTE_SURFACE CardArtistVote sibling, both at "now" (matching the two
    back-to-back .create() calls cast_illustration_vote makes inside one transaction)."""
    tag = CardPrintingTag.objects.create(
        card=card,
        printing=printing or CanonicalCardFactory(),
        is_no_match=False,
        anonymous_id=anonymous_id,
        source=VoteSource.USER,
        vote_surface="question-feed",
    )
    vote = CardArtistVoteFactory(
        card=card,
        anonymous_id=anonymous_id,
        source=VoteSource.USER,
        vote_surface=DERIVED_ARTIST_VOTE_SURFACE,
        **({"artist": artist} if artist is not None else {}),
    )
    return tag, vote


class TestFindDerivedPrintingTags:
    def test_identifies_a_derived_row_and_not_an_unrelated_explicit_one(self, db):
        card = CardFactory(name="Brainstorm")
        derived_tag, _ = _cast_derived_pair(card, "voter-1")

        other_card = CardFactory(name="Forest")
        explicit_tag = CardPrintingTagFactory(card=other_card, anonymous_id="voter-2", source=VoteSource.USER)

        result = find_derived_printing_tags()

        derived_ids = {row.tag_id for row in result.derived}
        assert derived_ids == {derived_tag.pk}
        assert explicit_tag.pk not in derived_ids
        assert result.skipped_ambiguous_ids == []

    def test_does_not_select_deduction_sourced_rows(self, db):
        # the #900-fixed shape - a real DEDUCTION vote paired with a DERIVED_ARTIST_VOTE_SURFACE
        # sibling - must never be selected: this command retracts the MISLABELLED (source=USER)
        # rows only, never the correctly-cast ones #900 already produces.
        card = CardFactory(name="Brainstorm")
        CardPrintingTagFactory(card=card, anonymous_id="voter-1", source=VoteSource.DEDUCTION)
        CardArtistVoteFactory(card=card, anonymous_id="voter-1", vote_surface=DERIVED_ARTIST_VOTE_SURFACE)

        result = find_derived_printing_tags()

        assert result.derived == []

    def test_explicit_vote_with_no_sibling_artist_vote_is_untouched(self, db):
        card = CardFactory(name="Brainstorm")
        CardPrintingTagFactory(card=card, anonymous_id="voter-1", source=VoteSource.USER)

        result = find_derived_printing_tags()

        assert result.derived == []
        assert result.skipped_ambiguous_ids == []

    def test_later_genuine_resubmission_outside_the_correlation_window_is_skipped_not_retracted(self, db):
        """A voter derived-voted, then LATER (via the separate, always-explicit printing-tag
        endpoint) submitted a genuine explicit answer for the same (card, anonymous_id) - that
        endpoint's own delete-then-create leaves a source=USER row sharing the pair with the
        original, unrelated CardArtistVote sibling, but created long after it. Must be reported
        as ambiguous, never retracted - see this command's own module docstring."""
        card = CardFactory(name="Brainstorm")
        tag, vote = _cast_derived_pair(card, "voter-1")
        # simulate the ORIGINAL derived tag being overwritten by a later genuine explicit
        # resubmission - same row identity is impossible (delete-then-create), so instead
        # backdate the sibling artist vote to simulate the gap directly on created_at.
        stale_sibling_at = timezone.now() - (SIBLING_CORRELATION_WINDOW + timedelta(days=3))
        CardArtistVote.objects.filter(pk=vote.pk).update(created_at=stale_sibling_at)

        result = find_derived_printing_tags()

        assert result.derived == []
        assert result.skipped_ambiguous_ids == [tag.pk]

    def test_pair_just_inside_the_window_is_still_retracted(self, db):
        card = CardFactory(name="Brainstorm")
        tag, vote = _cast_derived_pair(card, "voter-1")
        nudged_sibling_at = tag.created_at - (SIBLING_CORRELATION_WINDOW - timedelta(seconds=1))
        CardArtistVote.objects.filter(pk=vote.pk).update(created_at=nudged_sibling_at)

        result = find_derived_printing_tags()

        assert {row.tag_id for row in result.derived} == {tag.pk}
        assert result.skipped_ambiguous_ids == []

    def test_is_no_match_escape_vote_within_the_window_is_not_retracted(self, db):
        """Pre-#713 (question_feed._voter_answered_printing_card_ids's own docstring), an
        illustration vote that derived ONLY the artist channel (N>1 matching printings - no
        CardPrintingTag written by that same transaction) did not exclude the card from re-serve,
        so the SAME card was served again immediately; production evidence there was an
        is_no_match escape vote within seconds of the artist-vote sibling. That is a genuine
        explicit answer, not a derivation - the derivation can never write is_no_match=True (the
        model's own printing/is_no_match XOR constraint) - so it must never be retracted, even
        though it shares (card, anonymous_id) with the sibling and lands inside the correlation
        window."""
        card = CardFactory(name="Brainstorm")
        vote = CardArtistVoteFactory(card=card, anonymous_id="voter-1", vote_surface=DERIVED_ARTIST_VOTE_SURFACE)
        escape_vote = CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id="voter-1",
            source=VoteSource.USER,
            vote_surface="question-feed",
        )
        assert abs(escape_vote.created_at - vote.created_at) <= SIBLING_CORRELATION_WINDOW

        result = find_derived_printing_tags()

        assert result.derived == []
        assert result.skipped_ambiguous_ids == []
        assert CardPrintingTag.objects.filter(pk=escape_vote.pk).exists()


class TestAnnotateWouldLeaveResolved:
    def test_true_when_the_derived_row_is_the_sole_human_backed_vote(self, db):
        printing = CanonicalCardFactory()
        card = CardFactory(name="Brainstorm")
        derived_tag, _ = _cast_derived_pair(card, "voter-1", printing=printing)
        # two OCR (machine-weight 0.5 each) votes agreeing with the derived row: total weight
        # 2.0 clears PRINTING_TAG_MIN_VOTES (2), but neither is human-backed on its own - the
        # derived USER row is the sole vote satisfying has_human_backed here.
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-run-1")
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.OCR, anonymous_id="ocr-run-2")
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = find_derived_printing_tags()
        annotate_would_leave_resolved(result)

        row = next(row for row in result.derived if row.tag_id == derived_tag.pk)
        assert row.card_would_leave_resolved is True

    def test_false_when_another_human_backed_vote_remains(self, db):
        printing = CanonicalCardFactory()
        card = CardFactory(name="Brainstorm")
        derived_tag, _ = _cast_derived_pair(card, "voter-1", printing=printing)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER, anonymous_id="voter-2")
        resolve_and_persist_printing(card)
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.RESOLVED

        result = find_derived_printing_tags()
        annotate_would_leave_resolved(result)

        row = next(row for row in result.derived if row.tag_id == derived_tag.pk)
        assert row.card_would_leave_resolved is False

    def test_false_when_the_card_is_not_currently_resolved(self, db):
        card = CardFactory(name="Brainstorm")
        derived_tag, _ = _cast_derived_pair(card, "voter-1")
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

        result = find_derived_printing_tags()
        annotate_would_leave_resolved(result)

        row = next(row for row in result.derived if row.tag_id == derived_tag.pk)
        assert row.card_would_leave_resolved is False


class TestCommand:
    def test_dry_run_deletes_nothing(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Brainstorm")
        derived_tag, _ = _cast_derived_pair(card, "voter-1")

        call_command("retract_derived_illustration_printing_tags")

        assert CardPrintingTag.objects.filter(pk=derived_tag.pk).exists()

    def test_write_deletes_exactly_the_identified_set(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Brainstorm")
        derived_tag, _ = _cast_derived_pair(card, "voter-1")

        other_card = CardFactory(name="Forest")
        untouched_explicit_tag = CardPrintingTagFactory(card=other_card, anonymous_id="voter-2", source=VoteSource.USER)
        untouched_deduction_tag = CardPrintingTagFactory(
            card=other_card, anonymous_id="voter-3", source=VoteSource.DEDUCTION
        )

        call_command("retract_derived_illustration_printing_tags", "--write")

        assert not CardPrintingTag.objects.filter(pk=derived_tag.pk).exists()
        assert CardPrintingTag.objects.filter(pk=untouched_explicit_tag.pk).exists()
        assert CardPrintingTag.objects.filter(pk=untouched_deduction_tag.pk).exists()

    def test_write_never_touches_the_sibling_artist_vote_table(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Brainstorm")
        derived_tag, sibling_vote = _cast_derived_pair(card, "voter-1")

        call_command("retract_derived_illustration_printing_tags", "--write")

        assert CardArtistVote.objects.filter(pk=sibling_vote.pk).exists()

    def test_a_card_with_only_an_explicit_non_derived_user_vote_is_untouched(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Forest")
        explicit_tag = CardPrintingTagFactory(card=card, anonymous_id="voter-1", source=VoteSource.USER)

        call_command("retract_derived_illustration_printing_tags", "--write")

        assert CardPrintingTag.objects.filter(pk=explicit_tag.pk).exists()

    def test_ambiguous_row_survives_the_write_path(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Brainstorm")
        tag, vote = _cast_derived_pair(card, "voter-1")
        stale_sibling_at = timezone.now() - (SIBLING_CORRELATION_WINDOW + timedelta(days=3))
        CardArtistVote.objects.filter(pk=vote.pk).update(created_at=stale_sibling_at)

        call_command("retract_derived_illustration_printing_tags", "--write")

        assert CardPrintingTag.objects.filter(pk=tag.pk).exists()

    def test_is_no_match_escape_vote_survives_the_write_path(self, db):
        from django.core.management import call_command

        card = CardFactory(name="Brainstorm")
        CardArtistVoteFactory(card=card, anonymous_id="voter-1", vote_surface=DERIVED_ARTIST_VOTE_SURFACE)
        escape_vote = CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id="voter-1",
            source=VoteSource.USER,
            vote_surface="question-feed",
        )

        call_command("retract_derived_illustration_printing_tags", "--write")

        assert CardPrintingTag.objects.filter(pk=escape_vote.pk).exists()
