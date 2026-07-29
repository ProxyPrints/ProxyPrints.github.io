"""
Tests for cardpicker.local_residual_classify (docs/features/catalog-completion-plan.md's
Part 3, HOLD #P3) - the shared frame-mismatch evidence-recovery module (dual yield: artist
vote + altered-frame tag) and d=0 sibling artist propagation. No network calls: the
OCR-refetch path is mocked exactly like test_local_identify_printing_tags.py mocks
fetch_card_image/run_ocr_for_card.
"""

import pytest

from django.db import connection
from django.test.utils import CaptureQueriesContext

import cardpicker.local_residual_classify as module
from cardpicker.local_fallback import FALLBACK_ANONYMOUS_ID, FallbackOutcome
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
    CardArtistVoteFactory,
    CardFactory,
    TagFactory,
)


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

    def test_fallback_flagged_rows_default_budget_zero_stays_unrecovered(self, db):
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=FALLBACK_ANONYMOUS_ID, skip_reason="frame-mismatch")

        result = run_frame_mismatch_recovery(dry_run=True)

        assert result.fallback_refetch_attempted == 0
        assert result.unrecovered == 1
        assert result.phash_recovered == 0
        assert result.ocr_refetch_attempted == 0

    def test_fallback_refetch_path_respects_budget(self, db, monkeypatch):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(name="Forest", artist=artist)
        card_a = CardFactory(name="Forest")
        card_b = CardFactory(name="Forest")
        CardScanLog.objects.create(card=card_a, anonymous_id=FALLBACK_ANONYMOUS_ID, skip_reason="frame-mismatch")
        CardScanLog.objects.create(card=card_b, anonymous_id=FALLBACK_ANONYMOUS_ID, skip_reason="frame-mismatch")

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())
        monkeypatch.setattr(
            module,
            "run_fallback_for_card",
            lambda selected, image, ocr_raw_texts=None, **kw: FallbackOutcome(printing_pk=printing.pk),
        )

        result = run_frame_mismatch_recovery(dry_run=True, fallback_refetch_budget=1)

        assert result.fallback_refetch_attempted == 1
        assert result.fallback_refetch_recovered == 1
        assert result.unrecovered == 1  # the second card hit the budget wall

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


class TestPurgeWriteAtomicity:
    """Cancel-safety at all three of this module's vote-write sites (2026-07-28, generalising PR
    #526's fix for the Stage D calculators): purge and insert are now one `transaction.atomic()`
    pair, so a run killed between them no longer leaves the affected cards with their previous
    same-family vote deleted and nothing written in its place."""

    @staticmethod
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")

    def _frame_mismatch_fixture(self):
        """The same recipe as `TestRunFrameMismatchRecovery::test_write_casts_dual_yield_votes` -
        a phash-recoverable frame-mismatch card, which yields BOTH an artist vote and an
        altered-frame tag vote (this module's two adjacent write sites)."""
        artist = CanonicalArtistFactory()
        CanonicalCardFactory(name="Forest", image_hash=100, artist=artist)
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        TagFactory(name=ALTERED_FRAME_TAG_NAME)
        return card, artist

    def test_frame_mismatch_artist_vote_insert_failure_rolls_its_purge_back(self, db, monkeypatch):
        card, artist = self._frame_mismatch_fixture()
        stale = CardArtistVote.objects.create(
            card=card, artist=artist, is_unknown=False, anonymous_id="residual-classify-v0", source=VoteSource.OCR
        )

        monkeypatch.setattr(CardArtistVote.objects, "bulk_create", self._boom)

        with pytest.raises(RuntimeError):
            run_frame_mismatch_recovery(dry_run=False)

        assert CardArtistVote.objects.filter(pk=stale.pk).exists()

    def test_frame_mismatch_tag_vote_insert_failure_rolls_its_purge_back(self, db, monkeypatch):
        card, _artist = self._frame_mismatch_fixture()
        tag = module.Tag.objects.get(name=ALTERED_FRAME_TAG_NAME)
        stale = CardTagVote.objects.create(
            card=card,
            tag=tag,
            polarity=VotePolarity.APPLY,
            anonymous_id="residual-classify-v0",
            source=VoteSource.OCR,
        )

        monkeypatch.setattr(CardTagVote.objects, "bulk_create", self._boom)

        with pytest.raises(RuntimeError):
            run_frame_mismatch_recovery(dry_run=False)

        assert CardTagVote.objects.filter(pk=stale.pk).exists()

    def test_d0_sibling_propagation_insert_failure_rolls_its_purge_back(self, db, monkeypatch):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        sibling = CardFactory(content_phash=555)
        stale = CardArtistVote.objects.create(
            card=sibling, artist=artist, is_unknown=False, anonymous_id="art-hash-artist-v0", source=VoteSource.OCR
        )

        monkeypatch.setattr(CardArtistVote.objects, "bulk_create", self._boom)

        with pytest.raises(RuntimeError):
            run_d0_sibling_artist_propagation(dry_run=False)

        assert CardArtistVote.objects.filter(pk=stale.pk).exists()


# ---------------------------------------------------------------------------
# Per-batch hot-path contract (issues #458/#460, via #533's first blocking
# prerequisite: anything a per-micro-batch caller invokes must cost O(batch),
# never O(catalog))
# ---------------------------------------------------------------------------


class TestFrameMismatchRecoveryCardIdScoping:
    """`run_frame_mismatch_recovery` gained a `card_ids` parameter. Its single catalog-scale read
    is the `CardScanLog` frame-mismatch scan, whose result it materialises into Python `set`s -
    so scoping has to reach the SQL, not the sets. `_frame_mismatch_scan_log_queryset` exists as
    the assertable seam for exactly that; a result-set assertion alone cannot distinguish "scoped
    in SQL" from "read catalog-wide and intersected in Python afterwards"."""

    def test_card_ids_narrows_the_scan_log_read_itself(self, db):
        card_a = CardFactory(name="Scope A")
        card_b = CardFactory(name="Scope B")

        scoped_sql = str(module._frame_mismatch_scan_log_queryset([card_a.pk, card_b.pk]).query)

        assert f'"cardpicker_cardscanlog"."card_id" IN ({card_a.pk}, {card_b.pk})' in scoped_sql
        assert '"cardpicker_cardscanlog"."skip_reason" = frame-mismatch' in scoped_sql

    def test_card_ids_none_leaves_bulk_mode_untouched(self, db):
        """BULK mode (the management command's only calling shape) reads the whole table exactly
        as it did before."""
        bulk_sql = str(module._frame_mismatch_scan_log_queryset().query)

        assert '"cardpicker_cardscanlog"."card_id" IN' not in bulk_sql
        assert '"cardpicker_cardscanlog"."skip_reason" = frame-mismatch' in bulk_sql

    def test_scoped_and_unscoped_flagged_sets_agree(self, db):
        flagged = CardFactory(name="Forest")
        CardScanLog.objects.create(card=flagged, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        unflagged = CardFactory(name="Island")
        CardScanLog.objects.create(card=unflagged, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="unfetchable-image")
        scope = [flagged.pk, unflagged.pk]

        unscoped = set(module._frame_mismatch_scan_log_queryset().filter(card_id__in=scope).values_list("card_id"))
        scoped = set(module._frame_mismatch_scan_log_queryset(scope).values_list("card_id"))

        assert unscoped == scoped == {(flagged.pk,)}

    def test_a_scoped_run_only_recovers_cards_inside_the_scope(self, db):
        artist = CanonicalArtistFactory()
        CanonicalCardFactory(name="Forest", image_hash=100, artist=artist)
        TagFactory(name=ALTERED_FRAME_TAG_NAME)
        in_scope = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=in_scope, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        out_of_scope = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=out_of_scope, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")

        result = run_frame_mismatch_recovery(dry_run=False, card_ids=[in_scope.pk])

        assert result.cards_considered == 1
        assert result.phash_recovered == 1
        assert list(CardArtistVote.objects.values_list("card_id", flat=True)) == [in_scope.pk]

    def test_card_ids_none_still_recovers_the_whole_catalog(self, db):
        artist = CanonicalArtistFactory()
        CanonicalCardFactory(name="Forest", image_hash=100, artist=artist)
        TagFactory(name=ALTERED_FRAME_TAG_NAME)
        card_a = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card_a, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        card_b = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card_b, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")

        result = run_frame_mismatch_recovery(dry_run=False)

        assert result.cards_considered == 2
        assert set(CardArtistVote.objects.values_list("card_id", flat=True)) == {card_a.pk, card_b.pk}

    def test_scoping_does_not_relax_the_fetch_budget_defaults(self, db, monkeypatch):
        """Scoping is not a fetch decision (issue #533): the OCR/fallback refetch budgets still
        default to 0, so a scoped run reaches the network exactly as never as an unscoped one."""
        CanonicalCardFactory(name="Forest", image_hash=100)
        card = CardFactory(name="Forest", content_phash=100)
        CardScanLog.objects.create(card=card, anonymous_id=OCR_ANONYMOUS_ID, skip_reason="frame-mismatch")

        def _unexpected_fetch(*args, **kwargs):
            raise AssertionError("a scoped run must not fetch at the default budget of 0")

        monkeypatch.setattr(module, "fetch_card_image", _unexpected_fetch)

        result = run_frame_mismatch_recovery(dry_run=True, card_ids=[card.pk])

        assert result.ocr_refetch_attempted == 0


class TestD0SiblingPropagationCardIdScoping:
    """`run_d0_sibling_artist_propagation` gained a `card_ids` parameter. Three reads had to be
    narrowed, not one: the `CardArtistVote` idempotence read, the target queryset, and - the one
    that would otherwise have left the pass O(catalog) while looking scoped - the artist-resolved
    SOURCE scan that builds the `phash_to_artist_id` index."""

    def test_card_ids_narrows_the_already_voted_cardartistvote_read(self, db):
        card_a = CardFactory(name="Scope A")
        card_b = CardFactory(name="Scope B")

        scoped_sql = str(module._art_hash_artist_voted_queryset([card_a.pk, card_b.pk]).query)

        assert f'"cardpicker_cardartistvote"."card_id" IN ({card_a.pk}, {card_b.pk})' in scoped_sql
        assert f'"cardpicker_cardartistvote"."anonymous_id" = {ART_HASH_ARTIST_ANONYMOUS_ID}' in scoped_sql

    def test_card_ids_none_leaves_the_already_voted_read_untouched(self, db):
        bulk_sql = str(module._art_hash_artist_voted_queryset().query)

        assert '"cardpicker_cardartistvote"."card_id" IN' not in bulk_sql
        assert f'"cardpicker_cardartistvote"."anonymous_id" = {ART_HASH_ARTIST_ANONYMOUS_ID}' in bulk_sql

    def test_the_source_index_scan_is_narrowed_by_a_subquery_over_the_batchs_hashes(self, db):
        """The one that matters most, asserted on the SQL Django actually EXECUTED rather than on
        a queryset built in the test: without this narrowing the source scan iterates every
        artist-resolved card in the catalog to build `phash_to_artist_id`, so the pass stays
        O(catalog) no matter how tightly the target query is scoped. `content_phash IN (SELECT
        ...)` proves the batch's hashes were pushed in as a subquery, not pulled through Python
        first."""
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        sibling = CardFactory(content_phash=555)

        with CaptureQueriesContext(connection) as captured:
            run_d0_sibling_artist_propagation(dry_run=True, card_ids=[sibling.pk])

        source_scans = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "cardpicker_card"' in query["sql"] and '"content_phash" IN (SELECT' in query["sql"]
        ]
        assert (
            source_scans
        ), f"no phash-subquery-narrowed source scan in: {[q['sql'] for q in captured.captured_queries]}"

    def test_card_ids_none_leaves_the_source_index_scan_unnarrowed(self, db):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        CardFactory(content_phash=555)

        with CaptureQueriesContext(connection) as captured:
            run_d0_sibling_artist_propagation(dry_run=True)

        assert not [query for query in captured.captured_queries if '"content_phash" IN (SELECT' in query["sql"]]

    def test_a_scoped_run_only_votes_on_cards_inside_the_scope(self, db):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        in_scope = CardFactory(content_phash=555)
        out_of_scope = CardFactory(content_phash=555)

        result = run_d0_sibling_artist_propagation(dry_run=False, card_ids=[in_scope.pk])

        assert result.votes_written == 1
        assert list(CardArtistVote.objects.values_list("card_id", flat=True)) == [in_scope.pk]
        assert not CardArtistVote.objects.filter(card_id=out_of_scope.pk).exists()

    def test_a_source_card_outside_the_scope_still_propagates_into_it(self, db):
        """Narrowing the SOURCE index by the batch's own hashes is result-equivalent, not an
        approximation: the entailment a scoped batch needs is "some card anywhere shares my
        hash and has an artist", and that source card is emphatically NOT required to be inside
        the batch. This is the assertion that would fail if the narrowing had been done by
        `pk__in=card_ids` on the source scan instead of by shared `content_phash`."""
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)  # deliberately outside the scope
        sibling = CardFactory(content_phash=555)

        result = run_d0_sibling_artist_propagation(dry_run=False, card_ids=[sibling.pk])

        assert result.votes_written == 1
        assert CardArtistVote.objects.get().artist_id == artist.pk

    def test_scoped_and_unscoped_runs_agree_on_the_scoped_card(self, db):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        sibling = CardFactory(content_phash=555)

        scoped = run_d0_sibling_artist_propagation(dry_run=True, card_ids=[sibling.pk])
        unscoped = run_d0_sibling_artist_propagation(dry_run=True)

        assert scoped.votes_would_cast == unscoped.votes_would_cast == 1

    def test_an_already_voted_card_inside_the_scope_stays_excluded(self, db):
        artist = CanonicalArtistFactory()
        printing = CanonicalCardFactory(artist=artist)
        CardFactory(content_phash=555, canonical_card=printing)
        sibling = CardFactory(content_phash=555)
        CardArtistVoteFactory(card=sibling, artist=artist, anonymous_id=ART_HASH_ARTIST_ANONYMOUS_ID)

        result = run_d0_sibling_artist_propagation(dry_run=True, card_ids=[sibling.pk])

        assert result.votes_would_cast == 0


class TestFrameMismatchRecoveryUsesTheSharedCandidateNameIndexCache:
    """Issue #533's THIRD blocking prerequisite (2026-07-29). `run_frame_mismatch_recovery` used
    to call `CandidateNameIndex()` directly at the top of every invocation - a 113,224-row scan,
    measured 1.48s. PR #541 made this function scopeable by `card_ids`, i.e. usable by a
    per-25-card-micro-batch caller; the index is keyed by card NAME over a different table, so
    `card_ids` cannot narrow it. At 25-card batches over a ~135,000-row queue that was ~5,400
    rebuilds.

    It now resolves through `local_calculate_verdicts._get_cached_candidate_name_index()` - the
    SAME per-worker-process, version-stamped cache the join-key/fallback/illustration calculators
    use, not a second implementation. These tests count REAL `CandidateNameIndex.__init__` calls,
    because a cache that silently rebuilds every time passes every behavioural test in this file
    while fixing nothing."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        import cardpicker.local_calculate_verdicts as verdicts_module

        verdicts_module.reset_candidate_name_index_cache_for_tests()
        yield
        verdicts_module.reset_candidate_name_index_cache_for_tests()

    @staticmethod
    def _count_constructions(monkeypatch) -> list[int]:
        """Patches the REAL `__init__` (not a replacement) so the indexes handed back stay fully
        functional - the recovery assertions below are on real behaviour, not a stub."""
        import cardpicker.local_calculate_verdicts as verdicts_module

        count = [0]
        real_init = CandidateNameIndex.__init__

        def counting_init(self, *args, **kwargs):
            count[0] += 1
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(verdicts_module.CandidateNameIndex, "__init__", counting_init)
        return count

    @staticmethod
    def _flagged_card(name: str, image_hash: int):
        """One canonical printing per NAME deliberately - `find_best_match` needs a clear winner,
        and two same-named printings with different hashes is an ambiguous candidate set, not a
        recovery."""
        CanonicalCardFactory(name=name, image_hash=image_hash)
        card = CardFactory(name=name, content_phash=image_hash)
        CardScanLog.objects.create(card=card, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")
        return card

    def test_the_index_is_built_once_across_two_invocations(self, db, monkeypatch):
        """Two invocations = two Stage E micro-batches in one worker process. No
        CanonicalCard/CanonicalExpansion/CanonicalPrintingMetadata write happens between them, so
        the version stamp is unchanged and the second invocation must reuse the first's index."""
        count = self._count_constructions(monkeypatch)
        card_one = self._flagged_card("Forest", 100)
        card_two = self._flagged_card("Island", 200)

        first = run_frame_mismatch_recovery(dry_run=True, card_ids=[card_one.pk])
        second = run_frame_mismatch_recovery(dry_run=True, card_ids=[card_two.pk])

        # both invocations did real work off the index - this is not "one built, one no-op".
        assert first.phash_recovered == 1
        assert second.phash_recovered == 1
        assert count[0] == 1

    def test_the_index_is_never_built_when_the_scope_has_no_flagged_cards(self, db, monkeypatch):
        """The LAZY half: resolution is deferred to the first card this pass actually recovers,
        so a micro-batch whose `card_ids` scope turns up no frame-mismatch scan logs pays neither
        the 1.48s build nor the version-stamp queries."""
        count = self._count_constructions(monkeypatch)
        self._flagged_card("Forest", 100)
        unflagged = CardFactory(name="Forest", content_phash=300)

        result = run_frame_mismatch_recovery(dry_run=True, card_ids=[unflagged.pk])

        assert result.cards_considered == 0
        assert count[0] == 0

    def test_a_canonical_card_write_between_invocations_still_rebuilds(self, db, monkeypatch):
        """The cache must not go stale for the scoped callers either - the invalidation event
        reaches this call site exactly as it reaches the join-key calculator's."""
        count = self._count_constructions(monkeypatch)
        card_one = self._flagged_card("Forest", 100)
        run_frame_mismatch_recovery(dry_run=True, card_ids=[card_one.pk])
        assert count[0] == 1

        CanonicalCardFactory(name="Island", image_hash=777)
        card_two = CardFactory(name="Island", content_phash=777)
        CardScanLog.objects.create(card=card_two, anonymous_id=PHASH_ANONYMOUS_ID, skip_reason="frame-mismatch")

        second = run_frame_mismatch_recovery(dry_run=True, card_ids=[card_two.pk])

        assert count[0] == 2
        assert second.phash_recovered == 1  # the REBUILT index actually sees "Island"

    def test_the_second_invocation_issues_no_catalog_scale_index_query(self, db, monkeypatch):
        """Construction counting proves the Python object is reused; this proves the DATABASE work
        is gone too - `CandidateNameIndex.__init__`'s own unaggregated `CanonicalCard` x
        `CanonicalPrintingMetadata` join is absent from the second invocation's SQL entirely. The
        `count(`/`sum(` exclusion is what separates it from the version stamp's own aggregates,
        which SHOULD still be there (they are the invalidation check)."""
        self._count_constructions(monkeypatch)
        card_one = self._flagged_card("Forest", 100)
        card_two = self._flagged_card("Island", 200)

        run_frame_mismatch_recovery(dry_run=True, card_ids=[card_one.pk])

        with CaptureQueriesContext(connection) as ctx:
            run_frame_mismatch_recovery(dry_run=True, card_ids=[card_two.pk])

        index_build_queries = [
            query["sql"]
            for query in ctx.captured_queries
            if "edhrec_rank" in query["sql"].lower()
            and "count(" not in query["sql"].lower()
            and "sum(" not in query["sql"].lower()
        ]
        assert index_build_queries == []
