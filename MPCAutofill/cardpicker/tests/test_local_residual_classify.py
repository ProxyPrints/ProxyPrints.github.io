"""
Tests for cardpicker.local_residual_classify (docs/features/catalog-completion-plan.md's
Part 3, HOLD #P3) - the shared frame-mismatch evidence-recovery module (dual yield: artist
vote + altered-frame tag) and d=0 sibling artist propagation. No network calls: the
OCR-refetch path is mocked exactly like test_local_identify_printing_tags.py mocks
fetch_card_image/run_ocr_for_card.
"""

import pytest

import cardpicker.local_residual_classify as module
from cardpicker.local_fallback import FALLBACK_ANONYMOUS_ID
from cardpicker.local_identify_printing_tags import (
    OCR_ANONYMOUS_ID,
    PHASH_ANONYMOUS_ID,
    EngineVote,
    OcrCardResult,
)
from cardpicker.local_residual_classify import (
    ALTERED_FRAME_TAG_NAME,
    ART_HASH_ARTIST_ANONYMOUS_ID,
    D0_SIBLING_ARTIST_CONFIDENCE,
    FRAME_MISMATCH_ARTIST_CONFIDENCE,
    FRAME_MISMATCH_TAG_CONFIDENCE,
    RESIDUAL_CLASSIFY_ANONYMOUS_ID,
    CandidateNameIndex,
    recover_frame_mismatch_printing_via_phash,
    run_d0_sibling_artist_propagation,
    run_frame_mismatch_recovery,
    verify_no_single_machine_vote_resolutions,
)
from cardpicker.models import (
    ArtistVoteStatus,
    CardArtistVote,
    CardScanLog,
    CardTagVote,
    VotePolarity,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardArtistVoteFactory,
    CardFactory,
    SourceFactory,
    TagFactory,
)

# see test_local_identify_printing_tags.py's identical fixture for the full rationale -
# factory.Sequence counters are process-global across the whole pytest run, so a new test file
# using these shared factories shifts snapshot-style assertions elsewhere (e.g.
# test_views.py::TestGetTags) unless the sequence is captured/restored around this file's tests.
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


class TestRecoverFrameMismatchPrintingViaPhash:
    def test_recovers_matching_candidate(self, db):
        printing = CanonicalCardFactory(name="Forest", image_hash=12345)
        card = CardFactory(name="Forest", content_phash=12345)
        index = CandidateNameIndex()
        assert recover_frame_mismatch_printing_via_phash(card, index) == printing.pk

    def test_none_when_content_phash_unset(self, db):
        CanonicalCardFactory(name="Forest", image_hash=12345)
        card = CardFactory(name="Forest", content_phash=None)
        index = CandidateNameIndex()
        assert recover_frame_mismatch_printing_via_phash(card, index) is None

    def test_none_when_no_candidates(self, db):
        card = CardFactory(name="Totally Unmatched Name", content_phash=12345)
        index = CandidateNameIndex()
        assert recover_frame_mismatch_printing_via_phash(card, index) is None


class TestRunFrameMismatchRecovery:
    def test_dry_run_writes_nothing(self, db):
        printing = CanonicalCardFactory(name="Forest", image_hash=100)
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        TagFactory(name=ALTERED_FRAME_TAG_NAME)

        result = run_frame_mismatch_recovery(dry_run=True)

        assert result.phash_recovered == 1
        assert result.artist_votes_written == 0
        assert result.tag_votes_written == 0
        assert CardArtistVote.objects.count() == 0
        assert CardTagVote.objects.count() == 0
        assert result.outcomes[0].recovered_printing_pk == printing.pk
        assert result.outcomes[0].artist_vote_would_cast is True

    def test_write_casts_dual_yield_votes(self, db):
        artist = CanonicalArtistFactory()
        CanonicalCardFactory(name="Forest", image_hash=100, artist=artist)
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        TagFactory(name=ALTERED_FRAME_TAG_NAME)

        result = run_frame_mismatch_recovery(run_id="test-run-1", dry_run=False)

        assert result.artist_votes_written == 1
        assert result.tag_votes_written == 1
        artist_vote = CardArtistVote.objects.get()
        assert artist_vote.card_id == card.pk
        assert artist_vote.artist_id == artist.pk
        assert artist_vote.anonymous_id == RESIDUAL_CLASSIFY_ANONYMOUS_ID
        assert artist_vote.source == VoteSource.OCR
        assert artist_vote.confidence == FRAME_MISMATCH_ARTIST_CONFIDENCE
        assert artist_vote.run_id == "test-run-1"
        assert artist_vote.vote_surface is None

        tag_vote = CardTagVote.objects.get()
        assert tag_vote.card_id == card.pk
        assert tag_vote.tag.name == ALTERED_FRAME_TAG_NAME
        assert tag_vote.polarity == VotePolarity.APPLY
        assert tag_vote.anonymous_id == RESIDUAL_CLASSIFY_ANONYMOUS_ID
        assert tag_vote.confidence == FRAME_MISMATCH_TAG_CONFIDENCE
        assert tag_vote.run_id == "test-run-1"
        assert tag_vote.vote_surface is None

    def test_no_altered_frame_tag_skips_tag_vote_only(self, db):
        # Tag.objects.get_or_create isn't called here - a fresh test DB genuinely has zero Tag
        # rows unless seeded (see reason_tags.py's own docstring on why this is deliberate).
        artist = CanonicalArtistFactory()
        CanonicalCardFactory(name="Forest", image_hash=100, artist=artist)
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")

        result = run_frame_mismatch_recovery(dry_run=False)

        assert result.artist_votes_written == 1
        assert result.tag_votes_written == 0

    def test_fallback_flagged_rows_are_out_of_scope(self, db):
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=FALLBACK_ANONYMOUS_ID, skip_reason="frame-mismatch")

        result = run_frame_mismatch_recovery(dry_run=True)

        assert result.fallback_skipped_out_of_scope == 1
        assert result.phash_recovered == 0
        assert result.ocr_refetch_attempted == 0

    def test_card_flagged_by_both_phash_and_ocr_recovers_once_via_phash(self, db):
        printing = CanonicalCardFactory(name="Forest", image_hash=100)
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        CardScanLog.objects.create(card=card, anonymous_id=OCR_ANONYMOUS_ID, skip_reason="frame-mismatch")

        result = run_frame_mismatch_recovery(dry_run=True, ocr_refetch_budget=10)

        assert result.cards_considered == 1
        assert result.phash_recovered == 1
        assert result.ocr_refetch_attempted == 0
        assert result.outcomes[0].recovered_printing_pk == printing.pk

    def test_ocr_refetch_path_respects_budget(self, db, monkeypatch):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(name="Forest", artist=artist)
        card_a = CardFactory(name="Forest")
        card_b = CardFactory(name="Forest")
        CardScanLog.objects.create(card=card_a, anonymous_id=OCR_ANONYMOUS_ID, skip_reason="frame-mismatch")
        CardScanLog.objects.create(card=card_b, anonymous_id=OCR_ANONYMOUS_ID, skip_reason="frame-mismatch")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, **kw: OcrCardResult(
                vote=EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.9, detail="")
            ),
        )

        result = run_frame_mismatch_recovery(dry_run=True, ocr_refetch_budget=1)

        assert result.ocr_refetch_attempted == 1
        assert result.ocr_refetch_recovered == 1
        assert result.unrecovered == 1  # the second card hit the budget wall

    def test_unrecoverable_phash_row_counted_not_crashed(self, db):
        # candidate exists but with a hash too far from the card's own - find_best_match
        # returns None, not an exception. -1 (all-ones in two's complement) is a valid signed
        # bigint, unlike the raw unsigned 0xFFFF...FFFF pattern a real phash would never be
        # stored as (local_phash's twos_complement conversion keeps stored values in signed
        # BigIntegerField range).
        CanonicalCardFactory(name="Forest", image_hash=1)
        card = CardFactory(name="Forest", content_phash=-1)
        CardScanLog.objects.create(card=card, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")

        result = run_frame_mismatch_recovery(dry_run=True)

        assert result.phash_recovered == 0
        assert result.unrecovered == 1


class TestRunD0SiblingArtistPropagation:
    def test_propagates_from_confirmed_indexing_match(self, db):
        # canonical_card (a confirmed indexing match, NOT vote-derived) is one of the four
        # "known artist" sources the spec text names ("resolved printing's Scryfall artist OR
        # resolved artist consensus") - this is the population the earlier volume check's
        # narrower inferred_canonical_card/inferred_canonical_artist-only query missed entirely.
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        source_card = CardFactory(content_phash=555, canonical_card=printing)
        sibling = CardFactory(content_phash=555)

        result = run_d0_sibling_artist_propagation(dry_run=False)

        assert result.votes_written == 1
        vote = CardArtistVote.objects.get()
        assert vote.card_id == sibling.pk
        assert vote.artist_id == artist.pk
        assert vote.anonymous_id == ART_HASH_ARTIST_ANONYMOUS_ID
        assert vote.confidence == D0_SIBLING_ARTIST_CONFIDENCE
        assert vote.vote_surface is None
        # the resolved source card itself never gets a redundant propagated vote
        assert not CardArtistVote.objects.filter(card=source_card).exists()

    def test_no_siblings_no_votes(self, db):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)  # no sibling shares this hash

        result = run_d0_sibling_artist_propagation(dry_run=False)

        assert result.votes_written == 0
        assert CardArtistVote.objects.count() == 0

    def test_idempotent_second_run_yields_nothing_new(self, db):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        CardFactory(content_phash=555)

        run_d0_sibling_artist_propagation(dry_run=False)
        second = run_d0_sibling_artist_propagation(dry_run=False)

        assert second.votes_written == 0
        assert CardArtistVote.objects.count() == 1

    def test_dry_run_writes_nothing(self, db):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        CardFactory(content_phash=555)

        result = run_d0_sibling_artist_propagation(dry_run=True)

        assert result.votes_would_cast == 1
        assert CardArtistVote.objects.count() == 0


class TestVerifyNoSingleMachineVoteResolutions:
    def test_clean_when_unresolved(self, db):
        card = CardFactory()
        assert verify_no_single_machine_vote_resolutions([card.pk]) == []

    def test_flags_a_resolved_card_with_only_machine_survivors(self, db):
        # constructed directly (bypassing resolve_and_persist_artist's own gate) to prove the
        # rail actually catches a real violation, not just a tautology against code that
        # already enforces it - mirrors purge_machine_votes' identical test pattern.
        artist = CanonicalArtistFactory()
        card = CardFactory(inferred_canonical_artist=artist, artist_vote_status=ArtistVoteStatus.RESOLVED)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.OCR)

        assert verify_no_single_machine_vote_resolutions([card.pk]) == [card.pk]

    def test_not_flagged_with_a_human_backed_survivor(self, db):
        artist = CanonicalArtistFactory()
        card = CardFactory(inferred_canonical_artist=artist, artist_vote_status=ArtistVoteStatus.RESOLVED)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.USER)
        CardArtistVoteFactory(card=card, artist=artist, source=VoteSource.OCR)

        assert verify_no_single_machine_vote_resolutions([card.pk]) == []
