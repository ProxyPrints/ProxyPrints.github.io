"""
Tests for `cardpicker.vote_write.purge_and_write_votes` (2026-07-28) - the generalised form of
PR #526's `_purge_and_write_printing_tag_votes`, now shared by every machine calculator that
purges same-family votes before writing new ones.

The three properties under test are the three the module docstring commits to: the purge+insert
pair is ATOMIC (this project's operator kills long runs mid-flight, and an untransacted
DELETE-then-INSERT loses votes outright when killed between the two), the purge is SCOPED TO THE
ROWS ACTUALLY WRITTEN (so a target the caller's already-voted split skipped keeps the winner's
committed row), and it is correct across all four vote models / both target fields the app uses.

`_purge_and_write_printing_tag_votes`' own tests in `test_local_calculate_verdicts.py` are kept as
they were - they now exercise this function through that binding.
"""

import pytest

from cardpicker.local_layout_class_cast import LAYOUT_CLASS_CAST_ANONYMOUS_ID
from cardpicker.models import (
    CardArtistVote,
    CardPrintingTag,
    CardTagVote,
    PrintingTagVote,
    VotePolarity,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CardFactory,
    TagFactory,
)
from cardpicker.vote_write import purge_and_write_votes


def _raise_instead_of_inserting(*args, **kwargs):
    """Stands in for the mid-flight kill this primitive exists to survive - the DELETE has already
    executed by the time `bulk_create` is reached, so anything short of a real transaction leaves
    it committed."""
    raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")


class TestAtomicity:
    def test_a_failed_insert_rolls_the_purge_back(self, db, monkeypatch):
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        stale = CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )

        monkeypatch.setattr(CardPrintingTag.objects, "bulk_create", _raise_instead_of_inserting)

        with pytest.raises(RuntimeError):
            purge_and_write_votes(
                CardPrintingTag,
                [
                    CardPrintingTag(
                        card_id=card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id="local-ocr-v2"
                    )
                ],
                anonymous_id="local-ocr-v2",
            )

        # without transaction.atomic() the family purge would already have committed and this row
        # would be gone, with nothing written in its place.
        assert CardPrintingTag.objects.filter(pk=stale.pk).exists()

    def test_the_happy_path_purges_the_stale_row_and_writes_the_new_one(self, db):
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        stale = CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )

        purge_and_write_votes(
            CardPrintingTag,
            [CardPrintingTag(card_id=card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id="local-ocr-v2")],
            anonymous_id="local-ocr-v2",
        )

        assert not CardPrintingTag.objects.filter(pk=stale.pk).exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id="local-ocr-v2").count() == 1


class TestPurgeScope:
    def test_an_empty_rows_list_purges_nothing(self, db):
        """The trap this signature exists to make unexpressible: a batch in which EVERY vote
        collided must purge NOTHING. Passing the pre-split batch here would delete each winner's
        row and then write nothing back in its place."""
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        winner = CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )

        purge_and_write_votes(CardPrintingTag, [], anonymous_id="local-ocr-v1")

        assert CardPrintingTag.objects.filter(pk=winner.pk).exists()

    def test_a_target_absent_from_rows_is_never_purged(self, db):
        """Partial-collision case: the split kept card B and dropped card A, so A's committed row
        must survive untouched even though A was in the pre-split batch."""
        skipped_card = CardFactory(name="Skipped")
        written_card = CardFactory(name="Written")
        printing = CanonicalCardFactory(name="Some Card")
        survivor = CardPrintingTag.objects.create(
            card=skipped_card,
            printing=printing,
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )

        purge_and_write_votes(
            CardPrintingTag,
            [
                CardPrintingTag(
                    card_id=written_card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id="local-ocr-v1"
                )
            ],
            anonymous_id="local-ocr-v1",
        )

        assert CardPrintingTag.objects.filter(pk=survivor.pk).exists()
        assert CardPrintingTag.objects.filter(card=written_card).count() == 1

    def test_a_human_vote_on_the_same_target_is_never_purged(self, db):
        """`purge_stale_machine_votes` only matches `^<family>-v\\d+$`; this asserts the guarantee
        survives the extra grouping layer this function adds around it."""
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        human = CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="11111111-2222-3333-4444-555555555555",
            source=VoteSource.USER,
        )

        purge_and_write_votes(
            CardPrintingTag,
            [CardPrintingTag(card_id=card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id="local-ocr-v1")],
            anonymous_id="local-ocr-v1",
        )

        assert CardPrintingTag.objects.filter(pk=human.pk).exists()


class TestIdentityGrouping:
    def test_an_explicit_anonymous_id_purges_only_that_family(self, db):
        """`local_lands_identify`'s shape: its batch mixes LANDS_ANONYMOUS_ID and
        OCR_ANONYMOUS_ID votes but has only ever purged the lands family. The explicit
        `anonymous_id` decides which family is purged, independently of what identities the rows
        themselves carry - so the other engine's committed vote must survive even though the row
        being written is one of ITS votes."""
        card = CardFactory(name="Some Card")
        printing = CanonicalCardFactory(name="Some Card")
        other_printing = CanonicalCardFactory(name="Some Other Card")
        other_family = CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=False,
            anonymous_id="local-ocr-v1",
            source=VoteSource.OCR,
        )
        # a no-match row carries NO printing - `cardprintingtag_printing_xor_no_match`.
        own_family = CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id="lands-artist-decomp-v0",
            source=VoteSource.OCR,
        )

        purge_and_write_votes(
            CardPrintingTag,
            [
                CardPrintingTag(
                    card_id=card.pk,
                    printing_id=other_printing.pk,
                    is_no_match=False,
                    anonymous_id="local-ocr-v1",
                )
            ],
            anonymous_id="lands-artist-decomp-v1",
        )

        assert CardPrintingTag.objects.filter(pk=other_family.pk).exists()
        assert not CardPrintingTag.objects.filter(pk=own_family.pk).exists()
        assert CardPrintingTag.objects.filter(card=card, printing=other_printing).count() == 1

    def test_anonymous_id_none_purges_each_row_under_its_own_family(self, db):
        """`local_identify_printing_tags.run_pilot`'s shape: one flush carrying several engines'
        votes, each of which must be purged under its OWN family, not one representative's."""
        ocr_card = CardFactory(name="OCR card")
        phash_card = CardFactory(name="phash card")
        printing = CanonicalCardFactory(name="Some Card")
        stale_ocr = CardPrintingTag.objects.create(
            card=ocr_card, printing=printing, is_no_match=False, anonymous_id="local-ocr-v0", source=VoteSource.OCR
        )
        stale_phash = CardPrintingTag.objects.create(
            card=phash_card, printing=printing, is_no_match=False, anonymous_id="local-phash-v0", source=VoteSource.OCR
        )

        purge_and_write_votes(
            CardPrintingTag,
            [
                CardPrintingTag(
                    card_id=ocr_card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id="local-ocr-v1"
                ),
                CardPrintingTag(
                    card_id=phash_card.pk, printing_id=printing.pk, is_no_match=False, anonymous_id="local-phash-v1"
                ),
            ],
        )

        assert not CardPrintingTag.objects.filter(pk=stale_ocr.pk).exists()
        assert not CardPrintingTag.objects.filter(pk=stale_phash.pk).exists()
        assert CardPrintingTag.objects.filter(anonymous_id="local-ocr-v1").count() == 1
        assert CardPrintingTag.objects.filter(anonymous_id="local-phash-v1").count() == 1


class TestOtherModelsAndTargetFields:
    def test_card_tag_vote_with_ignore_conflicts(self, db):
        """`CardTagVote` + `ignore_conflicts=True` (the layout-class/AI-art/pilot binding): a row
        colliding with the (card, tag, anonymous_id) constraint is swallowed rather than raising,
        exactly as those call sites relied on before."""
        card = CardFactory(name="Some Card")
        tag = TagFactory(name="Borderless")
        existing = CardTagVote.objects.create(
            card=card,
            tag=tag,
            polarity=VotePolarity.APPLY,
            anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        # First call: a DIFFERENT family from `existing`, so the purge deletes nothing and the
        # insert has no constraint to hit - `existing` survives untouched, and this is just the
        # setup that puts a `some-other-engine-v1` row in the table. The conflict path is the
        # SECOND call below, which re-offers that exact row while purging under a family that
        # doesn't match it, so the insert genuinely collides and `ignore_conflicts` has to
        # swallow it.
        purge_and_write_votes(
            CardTagVote,
            [
                CardTagVote(
                    card_id=card.pk, tag_id=tag.pk, polarity=VotePolarity.APPLY, anonymous_id="some-other-engine-v1"
                )
            ],
            anonymous_id="some-other-engine-v1",
            ignore_conflicts=True,
        )
        assert CardTagVote.objects.filter(pk=existing.pk).exists()

        purge_and_write_votes(
            CardTagVote,
            [
                CardTagVote(
                    card_id=card.pk, tag_id=tag.pk, polarity=VotePolarity.APPLY, anonymous_id="some-other-engine-v1"
                )
            ],
            anonymous_id="unrelated-family-v1",  # purges nothing, so the insert genuinely conflicts
            ignore_conflicts=True,
        )
        assert CardTagVote.objects.filter(card=card, anonymous_id="some-other-engine-v1").count() == 1

    def test_card_artist_vote_rolls_back(self, db, monkeypatch):
        card = CardFactory(name="Some Card")
        artist = CanonicalArtistFactory(name="Some Artist")
        stale = CardArtistVote.objects.create(
            card=card,
            artist=artist,
            is_unknown=False,
            anonymous_id="art-hash-artist-v0",
            source=VoteSource.OCR,
        )

        monkeypatch.setattr(CardArtistVote.objects, "bulk_create", _raise_instead_of_inserting)

        with pytest.raises(RuntimeError):
            purge_and_write_votes(
                CardArtistVote,
                [
                    CardArtistVote(
                        card_id=card.pk, artist_id=artist.pk, is_unknown=False, anonymous_id="art-hash-artist-v1"
                    )
                ],
                anonymous_id="art-hash-artist-v1",
            )

        assert CardArtistVote.objects.filter(pk=stale.pk).exists()

    def test_printing_tag_vote_keys_on_printing_id_not_card_id(self, db, monkeypatch):
        """The only `printing_id`-keyed call site in the app (`import_external_ip_tags`) - the
        target field is a real parameter, not a card_id assumption baked into the primitive."""
        printing = CanonicalCardFactory(name="Some Card")
        tag = TagFactory(name="External IP")
        stale = PrintingTagVote.objects.create(
            printing=printing,
            tag=tag,
            polarity=VotePolarity.APPLY,
            anonymous_id="scryfall-tagger-v0",
            source=VoteSource.DEDUCTION,
        )

        purge_and_write_votes(
            PrintingTagVote,
            [
                PrintingTagVote(
                    printing_id=printing.pk,
                    tag_id=tag.pk,
                    polarity=VotePolarity.APPLY,
                    anonymous_id="scryfall-tagger-v1",
                )
            ],
            anonymous_id="scryfall-tagger-v1",
            target_field="printing_id",
            ignore_conflicts=True,
        )

        assert not PrintingTagVote.objects.filter(pk=stale.pk).exists()
        assert PrintingTagVote.objects.filter(printing=printing, anonymous_id="scryfall-tagger-v1").count() == 1

    def test_printing_tag_vote_rolls_back(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Some Card")
        tag = TagFactory(name="External IP")
        stale = PrintingTagVote.objects.create(
            printing=printing,
            tag=tag,
            polarity=VotePolarity.APPLY,
            anonymous_id="scryfall-tagger-v0",
            source=VoteSource.DEDUCTION,
        )

        monkeypatch.setattr(PrintingTagVote.objects, "bulk_create", _raise_instead_of_inserting)

        with pytest.raises(RuntimeError):
            purge_and_write_votes(
                PrintingTagVote,
                [
                    PrintingTagVote(
                        printing_id=printing.pk,
                        tag_id=tag.pk,
                        polarity=VotePolarity.APPLY,
                        anonymous_id="scryfall-tagger-v1",
                    )
                ],
                anonymous_id="scryfall-tagger-v1",
                target_field="printing_id",
                ignore_conflicts=True,
            )

        assert PrintingTagVote.objects.filter(pk=stale.pk).exists()
