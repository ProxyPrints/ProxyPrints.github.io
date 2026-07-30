"""
Tests for cardpicker.local_illustration (Stage D illustration deduction calculator, issue #507).

Covers: IllustrationIndex construction (including per-face keys), 0/1/N vote shapes, confidence
division, dry-run no-writes, live gate (verify_zero_resolutions), purgeability via run_id,
eligibility constraints (no join-key vote, no artist-ocr, no evidence), the deleted border-colour
misread that v1 called a faced-ness gate, back-face-named uploads end to end, and the v1 -> v2
version bump.
"""

import json
import uuid

import pytest

from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext

from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.local_illustration import (
    BASE_CONFIDENCE,
    ILLUSTRATION_ANONYMOUS_ID,
    MULTIPLE_ILLUSTRATIONS_SKIP_REASON,
    MULTIPLE_PRINTINGS_SKIP_REASON,
    NO_ARTIST_OCR_SKIP_REASON,
    NO_CANDIDATE_MATCH_SKIP_REASON,
    NO_EVIDENCE_SKIP_REASON,
    NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON,
    RESCANNABLE_SKIP_REASONS,
    IllustrationIndex,
    _eligible_illustration_cards_queryset,
    _get_cached_illustration_index,
    _split_new_illustration_votes,
    calculate_illustration_verdict,
    printings_for_illustration,
    reset_illustration_index_cache_for_tests,
    run_illustration_calculator,
)
from cardpicker.models import (
    CardArtistVote,
    CardIllustrationVote,
    CardPrintingTag,
    CardScanLog,
    DFCPair,
    PrintingTagStatus,
    VoteSource,
    calculator_family,
)
from cardpicker.printing_consensus import agent_dedupe_key
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    DFCPairFactory,
    ImageEvidenceFactory,
)
from cardpicker.vote_consensus import resolve_vote_weight


def _make_evidence(card, **overrides):
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions={"collector_line_ocr": "collector-line-ocr-v1"},
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
        legal_line_proxy_marker_detected=False,
        symbol_phash=None,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


def _eligible_card(**overrides):
    defaults = dict(
        name="Lightning Bolt",
        printing_tag_status=PrintingTagStatus.UNRESOLVED,
        canonical_card=None,
        content_phash=1,  # non-null required: run_illustration_calculator skips content_phash=None
    )
    defaults.update(overrides)
    return CardFactory(**defaults)


def _join_key_no_hit_card(card):
    CardPrintingTag.objects.create(
        card=card,
        printing=None,
        is_no_match=True,
        anonymous_id=JOIN_KEY_ANONYMOUS_ID,
        source=VoteSource.OCR,
    )


# ---------------------------------------------------------------------------
# IllustrationIndex
# ---------------------------------------------------------------------------


class TestIllustrationIndex:
    def test_basic_index_construction(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        illustration_uuid = uuid.uuid4()
        CanonicalPrintingMetadataFactory(
            canonical_card=cc,
            illustration_id=illustration_uuid,
        )

        index = IllustrationIndex()

        assert str(illustration_uuid) in index.illustration_printings(artist.pk, "lightning bolt")
        assert index.artist_by_pk[cc.pk] == "Christopher Rush"
        assert index.card_pk_to_artist_pk[cc.pk] == artist.pk

    def test_multiple_illustrations_for_same_artist_name(self, db):
        artist = CanonicalArtistFactory(name="Artist One")
        expansion = CanonicalExpansionFactory(code="m21")
        cc1 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        cc2 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        illustration1 = uuid.uuid4()
        illustration2 = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=cc1, illustration_id=illustration1)
        CanonicalPrintingMetadataFactory(canonical_card=cc2, illustration_id=illustration2)

        index = IllustrationIndex()

        illustrations = index.illustration_printings(artist.pk, "dragon")
        assert len(illustrations) == 2
        assert str(illustration1) in illustrations
        assert str(illustration2) in illustrations

    def test_different_artists_same_card_name(self, db):
        artist1 = CanonicalArtistFactory(name="Artist One")
        artist2 = CanonicalArtistFactory(name="Artist Two")
        expansion = CanonicalExpansionFactory(code="m21")
        cc1 = CanonicalCardFactory(name="Dragon", artist=artist1, expansion=expansion)
        cc2 = CanonicalCardFactory(name="Dragon", artist=artist2, expansion=expansion)
        illustration1 = uuid.uuid4()
        illustration2 = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=cc1, illustration_id=illustration1)
        CanonicalPrintingMetadataFactory(canonical_card=cc2, illustration_id=illustration2)

        index = IllustrationIndex()

        illustrations1 = index.illustration_printings(artist1.pk, "dragon")
        illustrations2 = index.illustration_printings(artist2.pk, "dragon")
        assert str(illustration1) in illustrations1
        assert str(illustration2) in illustrations2
        assert str(illustration2) not in illustrations1

    def test_index_skips_null_illustration_id(self, db):
        artist = CanonicalArtistFactory(name="Artist One")
        expansion = CanonicalExpansionFactory(code="m21")
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=None)

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "dragon") == {}

    def test_empty_index(self, db):
        index = IllustrationIndex()
        assert index.illustration_printings(999, "nonexistent") == {}


# ---------------------------------------------------------------------------
# calculate_illustration_verdict
# ---------------------------------------------------------------------------


class TestCalculateIllustrationVerdict:
    def _build_index_and_mocks(self, artist_name, card_name, illustration_uuid, printing_pk):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code="test")
        cc = CanonicalCardFactory(name=card_name, artist=artist, expansion=expansion, pk=printing_pk)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration_uuid)
        index = IllustrationIndex()
        candidate = type("_C", (), {"pk": cc.pk})()
        return index, [candidate]

    def test_one_illustration_one_printing_casts_exactly_one_vote(self, db):
        """The ONLY case that votes after issue #525's 1:1 rule. (Renamed from
        `test_single_illustration_votes_all_printings`: the old name described the pre-#525
        behaviour - "vote every printing at full BASE_CONFIDENCE" - which this fixture never
        actually exercised, since it only ever built one printing.)"""
        illustration_uuid = uuid.uuid4()
        index, candidates = self._build_index_and_mocks(
            "Christopher Rush", "Lightning Bolt", illustration_uuid, printing_pk=100
        )
        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Christopher Rush"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="lightning bolt",
        )

        assert verdict.skip_reason == ""
        assert verdict.confidence == BASE_CONFIDENCE
        assert verdict.illustration_count == 1
        assert verdict.printing_count == 1
        assert verdict.printing_pks == (100,)
        assert verdict.illustration_id == str(illustration_uuid)

    def test_no_artist_match_abstains(self, db):
        index, candidates = self._build_index_and_mocks(
            "Christopher Rush", "Lightning Bolt", uuid.uuid4(), printing_pk=100
        )

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Unknown Artist"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="lightning bolt",
        )

        assert verdict.skip_reason == NO_CANDIDATE_MATCH_SKIP_REASON
        assert verdict.printing_pks == ()

    def test_no_illustration_index_entry_abstains(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="test")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion, pk=200)
        index = IllustrationIndex()
        candidate = type("_C", (), {"pk": cc.pk})()

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Christopher Rush"})(),
            illustration_index=index,
            candidates=[candidate],
            searchable_card_name="lightning bolt",
        )

        assert verdict.skip_reason == NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON

    def test_multiple_illustrations_abstains_and_retains_no_identity(self, db):
        """Issue #525. THIS TEST PREVIOUSLY ASSERTED THE DEFECT
        (`test_multiple_illustrations_spreads_confidence`: `skip_reason == ""`, two `printing_pks`,
        `confidence == BASE_CONFIDENCE / 2`). The /N spread never reached the tally -
        `resolve_vote_weight` takes no confidence argument and `VoteTuple` has no confidence field
        - so those were two FULL-machine-weight votes for mutually exclusive printings under one
        anonymous_id. It now abstains. No illustration identity is retained: there is no single
        one, and inventing a representative would be picking an answer the evidence does not
        support."""
        artist = CanonicalArtistFactory(name="Artist X")
        expansion = CanonicalExpansionFactory(code="test")
        cc1 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion, pk=301)
        cc2 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion, pk=302)
        CanonicalPrintingMetadataFactory(canonical_card=cc1, illustration_id=uuid.uuid4())
        CanonicalPrintingMetadataFactory(canonical_card=cc2, illustration_id=uuid.uuid4())
        index = IllustrationIndex()
        candidates = [type("_C", (), {"pk": cc1.pk})(), type("_C", (), {"pk": cc2.pk})()]

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Artist X"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="dragon",
        )

        assert verdict.skip_reason == MULTIPLE_ILLUSTRATIONS_SKIP_REASON
        assert verdict.printing_pks == ()
        assert verdict.illustration_count == 2
        assert verdict.printing_count == 2
        assert verdict.illustration_id == ""
        assert verdict.candidate_printing_pks == ()

    def test_one_illustration_many_printings_abstains_but_retains_the_illustration(self, db):
        """Issue #525's most common case, not an edge case: `illustration_id → printing` is 1:N,
        so this fires for ANY reprinted artwork. The pre-#525 comment read "Exactly 1
        illustration: vote every printing at full BASE_CONFIDENCE" - N full-weight votes for
        mutually exclusive printings. It now abstains, but RETAINS the illustration identity and
        the candidate printings, because that narrowing is genuinely established and issue #524
        (`CardIllustrationVote`) is where it becomes persistable without re-deriving anything."""
        artist = CanonicalArtistFactory(name="Artist Y")
        expansion = CanonicalExpansionFactory(code="test")
        shared_illustration = uuid.uuid4()
        cc1 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion, pk=401)
        cc2 = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion, pk=402)
        CanonicalPrintingMetadataFactory(canonical_card=cc1, illustration_id=shared_illustration)
        CanonicalPrintingMetadataFactory(canonical_card=cc2, illustration_id=shared_illustration)
        index = IllustrationIndex()
        candidates = [type("_C", (), {"pk": cc1.pk})()]

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Artist Y"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="dragon",
        )

        assert verdict.skip_reason == MULTIPLE_PRINTINGS_SKIP_REASON
        assert verdict.printing_pks == ()  # nothing to cast
        assert verdict.illustration_count == 1
        assert verdict.printing_count == 2
        # the recoverable fact, retained for issue #524 - and NOT in `printing_pks`, so no
        # reordering of the runner's loop can turn it into cast votes.
        assert verdict.illustration_id == str(shared_illustration)
        assert set(verdict.candidate_printing_pks) == {401, 402}

    def test_the_two_abstain_reasons_are_distinguishable(self, db):
        """Only the single-illustration abstention carries a fact issue #524 can persist, so the
        two must be separable by a plain `WHERE skip_reason = '...'` query."""
        assert MULTIPLE_ILLUSTRATIONS_SKIP_REASON != MULTIPLE_PRINTINGS_SKIP_REASON

    def test_the_same_printing_reached_twice_is_still_one_to_one(self, db):
        """Two surviving candidates sharing an artist reach the same printing twice. That is a
        genuinely 1:1 narrowing and must still vote - the de-duplication in the verdict exists so
        it does not read as `MULTIPLE_PRINTINGS_SKIP_REASON`."""
        artist = CanonicalArtistFactory(name="Artist Z")
        expansion = CanonicalExpansionFactory(code="test")
        illustration = uuid.uuid4()
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion, pk=501)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration)
        # a second canonical card by the SAME artist under a DIFFERENT name - it contributes a
        # second surviving candidate pk that maps to the same artist, hence the same lookup.
        other = CanonicalCardFactory(name="Wyrm", artist=artist, expansion=expansion, pk=502)
        index = IllustrationIndex()
        candidates = [type("_C", (), {"pk": cc.pk})(), type("_C", (), {"pk": other.pk})()]

        verdict = calculate_illustration_verdict(
            card_id=1,
            evidence=type("E", (), {"artist_ocr_name": "Artist Z"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="dragon",
        )

        assert verdict.skip_reason == ""
        assert verdict.printing_pks == (501,)
        assert verdict.printing_count == 1


# ---------------------------------------------------------------------------
# run_illustration_calculator (integration)
# ---------------------------------------------------------------------------


class TestRunIllustrationCalculator:
    def test_dry_run_writes_nothing(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=True)

        assert result.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0

    def test_live_writes_votes_and_resolves(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=False)

        assert result.votes_written >= 1
        votes = CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        assert votes.count() >= 1
        vote = votes.first()
        assert vote.source == VoteSource.DEDUCTION
        assert vote.confidence == BASE_CONFIDENCE

    def test_skips_no_artist_ocr(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="")

        result = run_illustration_calculator(dry_run=True)

        assert result.skip_counts.get(NO_ARTIST_OCR_SKIP_REASON, 0) >= 1

    def test_skips_no_evidence(self, db):
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)

        result = run_illustration_calculator(dry_run=True)

        assert result.skip_counts.get(NO_EVIDENCE_SKIP_REASON, 0) >= 1

    def test_gate_check_passes(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=False)

        touched_ids = list(
            CardPrintingTag.objects.filter(run_id=result.run_id, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).values_list(
                "card_id", flat=True
            )
        )

        from cardpicker.local_identify_printing_tags import verify_zero_resolutions

        violations = verify_zero_resolutions(touched_ids)
        assert violations == []

    def test_purgeability_by_run_id(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")

        result = run_illustration_calculator(dry_run=False)
        run_id = result.run_id

        assert CardPrintingTag.objects.filter(run_id=run_id).count() >= 1

        from django.core.management import call_command

        call_command("purge_machine_votes", run_id=run_id)

        assert CardPrintingTag.objects.filter(run_id=run_id).count() == 0


# ---------------------------------------------------------------------------
# The 1:1 printing-resolution rule, end to end (issue #525)
# ---------------------------------------------------------------------------


class TestOneToOneRuleEndToEnd:
    """Issue #525 through `run_illustration_calculator`: what actually reaches the DB. The
    calculator emitted one `CardPrintingTag` per printing pk, so a multi-printing verdict wrote
    several full-machine-weight rows for mutually exclusive printings under a single
    `anonymous_id` - `cardprintingtag_unique_printing_vote` is on (card, printing, anonymous_id),
    so they all persisted."""

    def _artist_and_card(self, artist_name="Artist Q", card_name="Dragon"):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code="lea")
        card = _eligible_card(name=card_name)
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name=artist_name)
        return artist, expansion, card

    def test_one_illustration_many_printings_writes_no_vote(self, db):
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        for _ in range(3):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)

        result = run_illustration_calculator(dry_run=False)

        assert result.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0
        assert result.skip_counts.get(MULTIPLE_PRINTINGS_SKIP_REASON) == 1
        assert CardScanLog.objects.filter(
            card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason=MULTIPLE_PRINTINGS_SKIP_REASON
        ).exists()
        # the coverage cost, measurable from the result itself.
        assert result.cards_abstained_ambiguous == 1
        assert result.printing_votes_withheld == 3

    def test_multiple_illustrations_writes_no_vote(self, db):
        artist, expansion, card = self._artist_and_card()
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        result = run_illustration_calculator(dry_run=False)

        assert result.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0
        assert result.skip_counts.get(MULTIPLE_ILLUSTRATIONS_SKIP_REASON) == 1
        assert CardScanLog.objects.filter(
            card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason=MULTIPLE_ILLUSTRATIONS_SKIP_REASON
        ).exists()
        assert result.cards_abstained_ambiguous == 1
        assert result.printing_votes_withheld == 2

    def test_one_illustration_one_printing_writes_exactly_one_vote(self, db):
        artist, expansion, card = self._artist_and_card()
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        result = run_illustration_calculator(dry_run=False)

        assert result.votes_written == 1
        votes = CardPrintingTag.objects.filter(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        assert votes.count() == 1
        vote = votes.get()
        assert vote.printing_id == cc.pk
        assert vote.confidence == BASE_CONFIDENCE
        assert vote.source == VoteSource.DEDUCTION
        assert result.cards_abstained_ambiguous == 0
        assert result.printing_votes_withheld == 0

    def test_the_abstain_audit_sample_carries_the_retained_narrowing(self, db):
        """Not persisted anywhere (issue #524 owns persistence) - but an operator running a DRY
        RUN can still see exactly which illustration was resolved and which printings it narrowed
        to, without querying the catalog again."""
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        printing_pks = set()
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)
            printing_pks.add(cc.pk)

        result = run_illustration_calculator(dry_run=True)

        entry = next(e for e in result.audit if e["card_id"] == card.pk)
        assert entry["skip_reason"] == MULTIPLE_PRINTINGS_SKIP_REASON
        assert entry["illustration_id"] == str(shared_illustration)
        assert set(entry["candidate_printing_pks"]) == printing_pks
        # dry run - nothing written, but the coverage figure is still available.
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0
        assert CardScanLog.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0
        assert result.printing_votes_withheld == 2

    def test_the_multi_illustration_abstain_invents_no_representative(self, db):
        artist, expansion, card = self._artist_and_card()
        for _ in range(3):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        result = run_illustration_calculator(dry_run=True)

        entry = next(e for e in result.audit if e["card_id"] == card.pk)
        assert entry["skip_reason"] == MULTIPLE_ILLUSTRATIONS_SKIP_REASON
        assert entry["illustration_id"] == ""
        assert entry["candidate_printing_pks"] == []


# ---------------------------------------------------------------------------
# Stage E micro-batch hot-path contract (issues #458/#460: anything
# `dispatch_micro_batch` calls must cost O(batch), never O(catalog))
# ---------------------------------------------------------------------------


class TestEligibleIllustrationCardsQuerysetCardIdScoping:
    """`_eligible_illustration_cards_queryset` gained a `card_ids` parameter, mirroring
    `local_calculate_verdicts._eligible_cards_queryset`'s own issue-#469 fix. Before it, the
    caller applied `card_ids` AFTER the function returned, so the `CardScanLog` exclusion
    subquery inside it was compiled unscoped - a full pass over a 2,093,147-row, append-only
    table on every 25-card Stage E micro-batch. These tests pin BOTH halves: that the subquery
    is genuinely narrowed in the compiled SQL (not just that the outer result happens to match),
    and that the eligible SET is unchanged either way."""

    @staticmethod
    def _sql(join_key_population, card_ids):
        """`join_key_*` must be non-empty: two empty `pk__in` lists make the OR branch match
        nothing and Django short-circuits the whole query to `EmptyResultSet` before rendering."""
        return str(
            _eligible_illustration_cards_queryset(
                join_key_voted_card_ids=join_key_population,
                join_key_scanned_card_ids=join_key_population,
                card_ids=card_ids,
            ).query
        )

    @staticmethod
    def _scan_log_subquery(sql: str) -> str:
        """The `CardScanLog` exclusion subquery, sliced out of the compiled SQL - it renders as
        `... IN (SELECT U0."card_id" FROM "cardpicker_cardscanlog" U0 WHERE (...))` and is
        immediately followed by the `dpi` exclusion, both fixed by this function's own filter
        order."""
        start = sql.index('FROM "cardpicker_cardscanlog"')
        end = sql.index('AND NOT ("cardpicker_card"."dpi"', start)
        return sql[start:end]

    def test_card_ids_narrows_the_cardscanlog_subquery_itself_not_just_the_outer_query(self, db):
        """The structural proof: the scope literal must appear INSIDE the `CardScanLog` subquery,
        not only on the outer `Card` query. Before this fix the caller applied `card_ids` after
        the function returned, so the subquery compiled to an unbounded scan of a 2,093,147-row
        table on every 25-card micro-batch."""
        card_a = CardFactory(name="Scope A")
        card_b = CardFactory(name="Scope B")
        # a THIRD, distinct card carries the join-key population, so nothing in the assertions
        # below can be satisfied by that unrelated literal.
        join_key_population = [CardFactory(name="Join Key Population").pk]

        scoped_sql = self._sql(join_key_population, [card_a.pk, card_b.pk])
        # the pre-fix shape: function unscoped, caller filters afterwards.
        pre_fix_sql = str(
            _eligible_illustration_cards_queryset(
                join_key_voted_card_ids=join_key_population, join_key_scanned_card_ids=join_key_population
            )
            .filter(pk__in=[card_a.pk, card_b.pk])
            .query
        )

        assert f'U0."card_id" IN ({card_a.pk}, {card_b.pk})' in self._scan_log_subquery(scoped_sql)
        assert 'U0."card_id" IN' not in self._scan_log_subquery(pre_fix_sql)
        # both shapes still bound the OUTER query identically - this is a narrowing, not a change
        # of which cards are considered.
        assert f'"cardpicker_card"."id" IN ({card_a.pk}, {card_b.pk})' in scoped_sql
        assert f'"cardpicker_card"."id" IN ({card_a.pk}, {card_b.pk})' in pre_fix_sql

    def test_scoped_and_unscoped_eligible_sets_agree(self, db):
        """Pure cost narrowing, not a behaviour change - the same equivalence
        `test_local_calculate_verdicts.TestEligibleCardsQuerysetCardScanLogScoping` pins for the
        sibling calculator."""
        excluded_card = _eligible_card(name="Excluded Card")
        _join_key_no_hit_card(excluded_card)
        # any skip reason OUTSIDE RESCANNABLE_SKIP_REASONS permanently excludes the card.
        non_rescannable = next(iter({"no-candidate-match"} - set(RESCANNABLE_SKIP_REASONS)))
        CardScanLog.objects.create(
            card=excluded_card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason=non_rescannable
        )
        eligible_card = _eligible_card(name="Eligible Card")
        _join_key_no_hit_card(eligible_card)
        scope = [excluded_card.pk, eligible_card.pk]

        join_key_voted = list(
            CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True).values_list(
                "card_id", flat=True
            )
        )
        unscoped = set(
            _eligible_illustration_cards_queryset(join_key_voted_card_ids=join_key_voted, join_key_scanned_card_ids=[])
            .filter(pk__in=scope)
            .values_list("pk", flat=True)
        )
        scoped = set(
            _eligible_illustration_cards_queryset(
                join_key_voted_card_ids=join_key_voted, join_key_scanned_card_ids=[], card_ids=scope
            ).values_list("pk", flat=True)
        )

        assert excluded_card.pk not in unscoped
        assert unscoped == scoped == {eligible_card.pk}

    def test_card_ids_none_leaves_bulk_mode_untouched(self, db):
        """BULK mode (every management-command caller) must never take the `card_id__in` branch -
        the CardScanLog subquery stays exactly as unscoped as it was before this fix."""
        join_key_population = [CardFactory(name="Join Key Population").pk]

        bulk_sql = self._sql(join_key_population, None)

        assert 'U0."card_id" IN' not in self._scan_log_subquery(bulk_sql)

    def test_a_scan_logged_card_inside_the_scope_stays_excluded(self, db):
        excluded_card = _eligible_card(name="Excluded Card")
        _join_key_no_hit_card(excluded_card)
        CardScanLog.objects.create(
            card=excluded_card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason="no-candidate-match"
        )

        join_key_voted = list(
            CardPrintingTag.objects.filter(anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True).values_list(
                "card_id", flat=True
            )
        )
        scoped = set(
            _eligible_illustration_cards_queryset(
                join_key_voted_card_ids=join_key_voted,
                join_key_scanned_card_ids=[],
                card_ids=[excluded_card.pk],
            ).values_list("pk", flat=True)
        )

        assert scoped == set()


class TestJoinKeyPopulationsStayLazy:
    """`run_illustration_calculator` used to wrap both join-key no-hit populations in `list(...)`,
    materializing every join-key no-match vote and every join-key no-hit `CardScanLog` row into
    this process's memory on EVERY micro-batch, before any `card_ids` scoping could apply. They
    are now lazy querysets that compile into SQL subqueries, matching
    `local_calculate_verdicts._fallback_eligible_cards_queryset`."""

    def test_the_join_key_populations_are_never_materialized(self, db, monkeypatch):
        import cardpicker.local_illustration as module

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return module.Card.objects.none()

        monkeypatch.setattr(module, "_eligible_illustration_cards_queryset", _capture)

        run_illustration_calculator(dry_run=True, card_ids=[card.pk])

        for key in ("join_key_voted_card_ids", "join_key_scanned_card_ids"):
            population = captured[key]
            assert not isinstance(population, list), f"{key} was materialized"
            # a lazy ValuesListQuerySet with no result cache populated yet.
            assert population._result_cache is None
        # and `card_ids` reached the function rather than being applied afterwards.
        assert captured["card_ids"] == [card.pk]

    def test_the_join_key_populations_are_scoped_to_card_ids_in_the_compiled_sql(self, db, monkeypatch):
        """LAZY IS NOT ENOUGH (2026-07-29). `_eligible_illustration_cards_queryset` cannot scope
        these two - they arrive as caller-built arguments - and Django compiles
        `.filter(pk__in=<values_list qs>)` as an UNCORRELATED `IN (SELECT ...)`. An
        unscoped-but-lazy pair therefore still made the database scan `CardPrintingTag` (167,229
        rows live) and `CardScanLog` (2,617,333 rows live, append-only) in full on EVERY
        micro-batch: the
        outer `card_ids` filter bounded the ROWS RETURNED, not the WORK DONE, so a result-set
        assertion is green either way. This asserts on the COMPILED SQL of the querysets the
        runner actually handed over."""
        import cardpicker.local_illustration as module

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return module.Card.objects.none()

        monkeypatch.setattr(module, "_eligible_illustration_cards_queryset", _capture)

        run_illustration_calculator(dry_run=True, card_ids=[card.pk])

        for key in ("join_key_voted_card_ids", "join_key_scanned_card_ids"):
            assert f'"card_id" IN ({card.pk})' in str(captured[key].query), (
                f"{key} reached the eligibility query unscoped - it compiles into an uncorrelated "
                "IN (SELECT ...) over the whole table"
            )

    def test_bulk_mode_leaves_the_join_key_populations_unscoped(self, db, monkeypatch):
        """`card_ids=None` (the management command's only calling shape) must take no scoping
        branch at all - byte-identical to this runner's pre-2026-07-29 behaviour."""
        import cardpicker.local_illustration as module

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return module.Card.objects.none()

        monkeypatch.setattr(module, "_eligible_illustration_cards_queryset", _capture)

        run_illustration_calculator(dry_run=True)

        for key in ("join_key_voted_card_ids", "join_key_scanned_card_ids"):
            assert '"card_id" IN (' not in str(captured[key].query)


class TestIllustrationIndexProcessCache:
    """`IllustrationIndex.__init__` issues TWO catalog-wide `CanonicalCard` queries (113,224 rows
    live) and builds full-catalog dicts. It was constructed fresh inside every
    `run_illustration_calculator` call - i.e. once per 25-card Stage E micro-batch. It is now
    memoized per worker process behind a version stamp, exactly like
    `local_calculate_verdicts._get_cached_candidate_name_index()` (issue #469)."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        reset_illustration_index_cache_for_tests()
        yield
        reset_illustration_index_cache_for_tests()

    @staticmethod
    def _count_constructions(monkeypatch) -> list[int]:
        """Patches the REAL `__init__` (not a replacement) so returned indexes stay functional."""
        import cardpicker.local_illustration as module

        count = [0]
        real_init = IllustrationIndex.__init__

        def counting_init(self, *args, **kwargs):
            count[0] += 1
            real_init(self, *args, **kwargs)

        monkeypatch.setattr(module.IllustrationIndex, "__init__", counting_init)
        return count

    def _catalog_card(self, name="Lightning Bolt", artist_name="Christopher Rush", expansion_code="lea"):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code=expansion_code)
        cc = CanonicalCardFactory(name=name, artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())
        return cc

    def test_repeated_calls_reuse_one_index(self, db, monkeypatch):
        self._catalog_card()
        count = self._count_constructions(monkeypatch)

        first = _get_cached_illustration_index()
        second = _get_cached_illustration_index()

        assert first is second
        assert count[0] == 1

    def test_a_new_canonical_card_invalidates_the_cache(self, db, monkeypatch):
        self._catalog_card()
        count = self._count_constructions(monkeypatch)

        _get_cached_illustration_index()
        self._catalog_card(name="Counterspell", artist_name="Mark Poole", expansion_code="leb")
        _get_cached_illustration_index()

        assert count[0] == 2

    def test_an_in_place_illustration_id_backfill_invalidates_the_cache(self, db, monkeypatch):
        """The stamp's fifth term. `import_scryfall_printing_metadata` populates `illustration_id`
        on rows that ALREADY EXIST - an UPDATE that moves neither max pk nor row count, so a
        four-term stamp would serve a stale, under-populated index for the worker's whole life."""
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        metadata = CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=None)
        count = self._count_constructions(monkeypatch)

        before = _get_cached_illustration_index()
        assert before.illustration_printings(artist.pk, "lightning bolt") == {}

        backfilled = uuid.uuid4()
        metadata.illustration_id = backfilled
        metadata.save(update_fields=["illustration_id"])
        after = _get_cached_illustration_index()

        assert count[0] == 2
        assert str(backfilled) in after.illustration_printings(artist.pk, "lightning bolt")

    def test_an_empty_micro_batch_builds_no_index_at_all(self, db, monkeypatch):
        """The whole point of the laziness: a micro-batch whose `card_ids` scope has no eligible
        card must pay neither the index build nor the version-stamp query."""
        self._catalog_card()
        untouched_card = CardFactory(name="Not Eligible")  # no join-key no-hit marker
        count = self._count_constructions(monkeypatch)

        result = run_illustration_calculator(dry_run=True, card_ids=[untouched_card.pk])

        assert result.cards_considered == 0
        assert count[0] == 0

    def test_the_calculator_goes_through_the_cache_not_a_fresh_build(self, db, monkeypatch):
        self._catalog_card()
        card_one = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card_one)
        _make_evidence(card_one, artist_ocr_name="Christopher Rush")
        card_two = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card_two)
        _make_evidence(card_two, artist_ocr_name="Christopher Rush")
        count = self._count_constructions(monkeypatch)

        # two separate invocations, i.e. two Stage E micro-batches in one worker process.
        run_illustration_calculator(dry_run=True, card_ids=[card_one.pk])
        run_illustration_calculator(dry_run=True, card_ids=[card_two.pk])

        assert count[0] == 1

    def test_the_calculator_uses_the_shared_candidate_name_index_cache(self, db, monkeypatch):
        """Regression for the cache BYPASS: this module used to call `CandidateNameIndex()`
        directly while its own comment claimed "same cached pattern as
        `_get_cached_candidate_name_index()`". It now actually calls it."""
        import cardpicker.local_calculate_verdicts as verdicts_module

        verdicts_module.reset_candidate_name_index_cache_for_tests()
        try:
            self._catalog_card()
            card_one = _eligible_card(name="Lightning Bolt")
            _join_key_no_hit_card(card_one)
            _make_evidence(card_one, artist_ocr_name="Christopher Rush")
            card_two = _eligible_card(name="Lightning Bolt")
            _join_key_no_hit_card(card_two)
            _make_evidence(card_two, artist_ocr_name="Christopher Rush")

            count = [0]
            real_init = verdicts_module.CandidateNameIndex.__init__

            def counting_init(self, *args, **kwargs):
                count[0] += 1
                real_init(self, *args, **kwargs)

            monkeypatch.setattr(verdicts_module.CandidateNameIndex, "__init__", counting_init)

            run_illustration_calculator(dry_run=True, card_ids=[card_one.pk])
            run_illustration_calculator(dry_run=True, card_ids=[card_two.pk])

            assert count[0] == 1
        finally:
            verdicts_module.reset_candidate_name_index_cache_for_tests()


class TestPurgeAndInsertAreAtomic:
    """The purge is a DELETE and the vote insert is a separate statement. Untransacted, a process
    killed between them - which this project's operator does deliberately, mid-flight - leaves the
    affected cards with their previous vote deleted and nothing written back."""

    def _catalog_and_card(self):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")
        return cc, card

    def test_a_failed_insert_rolls_the_purge_back(self, db, monkeypatch):
        cc, card = self._catalog_and_card()
        # a STALE-VERSION row: same calculator FAMILY, so `purge_stale_machine_votes` deletes it,
        # but a different anonymous_id, so the skip-if-exists split does NOT treat it as a
        # collision - exactly the row a mid-flight kill would destroy.
        stale = CardPrintingTag.objects.create(
            card=card,
            printing=cc,
            is_no_match=False,
            anonymous_id="stage-d-illustration-v0",
            source=VoteSource.DEDUCTION,
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")

        monkeypatch.setattr(CardPrintingTag.objects, "bulk_create", _boom)

        with pytest.raises(RuntimeError):
            run_illustration_calculator(dry_run=False)

        assert CardPrintingTag.objects.filter(pk=stale.pk).exists()

    def test_the_happy_path_still_replaces_the_stale_vote(self, db):
        """The atomicity wrapper must not change the successful outcome: the stale-version row is
        still purged and the current-version vote still lands."""
        cc, card = self._catalog_and_card()
        stale = CardPrintingTag.objects.create(
            card=card,
            printing=cc,
            is_no_match=False,
            anonymous_id="stage-d-illustration-v0",
            source=VoteSource.DEDUCTION,
        )

        run_illustration_calculator(dry_run=False)

        assert not CardPrintingTag.objects.filter(pk=stale.pk).exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 1


class TestAlreadyVotedIsNotStructurallyZero:
    """`already_voted` is the concurrent-dispatch collision counter
    `stage_e_dispatch.DispatchOutcome.stage_d_illustration_already_voted` surfaces - documented
    there as something "a healthy streaming deployment should see occasionally, not never (zero
    forever would suggest the guard itself is dead code)". It WAS structurally zero: the purge ran
    first and deleted exactly the rows the split then looked for."""

    def test_a_concurrent_winners_vote_is_counted_and_left_alone(self, db, monkeypatch):
        """Reproduces the losing side of a concurrent dispatch exactly as
        `test_local_calculate_verdicts.test_concurrent_dispatch_collision_is_skipped_not_crashed`
        does: the eligibility read is held stale (representing the already-consumed queryset the
        real loser read BEFORE the winner committed) while the winner's row is seeded directly."""
        import cardpicker.local_illustration as module

        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")
        monkeypatch.setattr(
            module,
            "_eligible_illustration_cards_queryset",
            lambda *args, **kwargs: module.Card.objects.filter(pk=card.pk),
        )
        # the WINNER of the race - another dispatch's vote for this exact (card, anonymous_id).
        winner = CardPrintingTag.objects.create(
            card=card,
            printing=cc,
            is_no_match=False,
            anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
            source=VoteSource.DEDUCTION,
            confidence=BASE_CONFIDENCE,
        )

        result = run_illustration_calculator(dry_run=False)  # must not raise IntegrityError

        assert result.already_voted == 1
        assert result.votes_written == 0
        # the winner's row survives untouched - the purge must not have run for a skipped card.
        assert CardPrintingTag.objects.filter(pk=winner.pk).exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 1


# =============================================================================================
# CardIllustrationVote — the model's constraints (issue #524)
# =============================================================================================


class TestCardIllustrationVoteConstraints:
    """`CardIllustrationVote`'s two constraints, asserted at the DB level rather than trusted from
    the model definition. The uniqueness one deliberately DIVERGES from every sibling identity-vote
    model (`CardPrintingTag`, `CardArtistVote`) and the divergence is the point - see the model's
    own docstring and issue #525."""

    def test_a_row_may_name_an_illustration(self, db):
        card = _eligible_card()
        illustration = uuid.uuid4()
        vote = CardIllustrationVote.objects.create(
            card=card, illustration_id=illustration, is_unknown=False, anonymous_id="voter-a"
        )
        assert vote.illustration_id == illustration

    def test_a_row_may_declare_the_illustration_unknown(self, db):
        card = _eligible_card()
        vote = CardIllustrationVote.objects.create(
            card=card, illustration_id=None, is_unknown=True, anonymous_id="voter-a"
        )
        assert vote.is_unknown is True

    def test_naming_an_illustration_and_claiming_unknown_is_rejected(self, db):
        """The XOR check, mirroring `cardartistvote_artist_xor_unknown`."""
        card = _eligible_card()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CardIllustrationVote.objects.create(
                    card=card, illustration_id=uuid.uuid4(), is_unknown=True, anonymous_id="voter-a"
                )

    def test_naming_neither_is_rejected(self, db):
        card = _eligible_card()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CardIllustrationVote.objects.create(
                    card=card, illustration_id=None, is_unknown=False, anonymous_id="voter-a"
                )

    def test_one_identity_cannot_hold_two_illustration_opinions_on_one_card(self, db):
        """THE DIVERGENCE, AND THE WHOLE REASON THE CONSTRAINT IS UNCONDITIONAL (issue #525).

        `CardPrintingTag`'s key is (card, printing, anonymous_id) and `CardArtistVote`'s artist
        branch is (card, artist, anonymous_id) - under EITHER shape this insert would succeed,
        because the second row names a different illustration. Both models rely on the submit VIEW
        deleting prior rows to get one-vote-per-card, which machine writers using `bulk_create`
        never call; that is exactly how the illustration calculator came to hold several mutually
        exclusive printing votes under one identity. Here it is a DB error, not a convention."""
        card = _eligible_card()
        CardIllustrationVote.objects.create(
            card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id="voter-a"
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CardIllustrationVote.objects.create(
                    card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id="voter-a"
                )

    def test_one_identity_cannot_hold_a_named_and_an_unknown_opinion_on_one_card(self, db):
        """A `condition=`d constraint (either sibling's shape) would permit this pair; the
        unconditional one does not. "This is illustration X" and "the illustration is unknown" are
        contradictory claims and one identity may not hold both."""
        card = _eligible_card()
        CardIllustrationVote.objects.create(
            card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id="voter-a"
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CardIllustrationVote.objects.create(
                    card=card, illustration_id=None, is_unknown=True, anonymous_id="voter-a"
                )

    def test_different_identities_may_disagree_about_the_same_card(self, db):
        """The constraint scopes contradiction OUT of a single identity, not out of the tally -
        disagreement between voters is what the consensus layer exists to reconcile."""
        card = _eligible_card()
        CardIllustrationVote.objects.create(
            card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id="voter-a"
        )
        CardIllustrationVote.objects.create(
            card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id="voter-b"
        )
        assert CardIllustrationVote.objects.filter(card=card).count() == 2

    def test_one_identity_may_vote_on_many_cards(self, db):
        illustration = uuid.uuid4()
        for _ in range(3):
            CardIllustrationVote.objects.create(
                card=_eligible_card(), illustration_id=illustration, is_unknown=False, anonymous_id="voter-a"
            )
        assert CardIllustrationVote.objects.filter(anonymous_id="voter-a").count() == 3

    def test_deleting_the_card_deletes_its_illustration_votes(self, db):
        card = _eligible_card()
        CardIllustrationVote.objects.create(
            card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id="voter-a"
        )
        card.delete()
        assert CardIllustrationVote.objects.count() == 0

    def test_votes_are_reachable_from_the_card_by_related_name(self, db):
        card = _eligible_card()
        CardIllustrationVote.objects.create(
            card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id="voter-a"
        )
        assert card.illustration_votes.count() == 1


# =============================================================================================
# The read-side narrowing (issue #524, task 3)
# =============================================================================================


class TestPrintingsForIllustration:
    """`printings_for_illustration` is the narrowing an illustration vote implies, expressed as a
    READ. It must never be materialised as implied printing votes - that materialisation IS issue
    #525's defect."""

    def _catalog(self):
        artist = CanonicalArtistFactory(name="Artist Q")
        expansion = CanonicalExpansionFactory(code="lea")
        shared = uuid.uuid4()
        other = uuid.uuid4()
        shared_ccs = []
        for _ in range(3):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared)
            shared_ccs.append(cc)
        odd_one = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=odd_one, illustration_id=other)
        return shared, other, shared_ccs, odd_one

    def test_returns_every_printing_carrying_the_illustration(self, db):
        shared, _other, shared_ccs, odd_one = self._catalog()
        found = set(printings_for_illustration(shared).values_list("pk", flat=True))
        assert found == {cc.pk for cc in shared_ccs}
        assert odd_one.pk not in found

    def test_accepts_a_string_illustration_id(self, db):
        """`IllustrationVerdict.illustration_id` and `CardIllustrationVote.illustration_id` reach
        callers as a str and a UUID respectively; both must work."""
        shared, _other, shared_ccs, _odd = self._catalog()
        assert printings_for_illustration(str(shared)).count() == len(shared_ccs)

    def test_scoping_to_a_candidate_list_narrows_the_result(self, db):
        shared, _other, shared_ccs, _odd = self._catalog()
        scope = [shared_ccs[0].pk]
        found = set(printings_for_illustration(shared, candidate_printing_pks=scope).values_list("pk", flat=True))
        assert found == {shared_ccs[0].pk}

    def test_the_scope_intersects_rather_than_replaces(self, db):
        """A candidate pk that does NOT carry this illustration must not be returned just because
        the caller listed it - the scope narrows, it never adds."""
        shared, _other, shared_ccs, odd_one = self._catalog()
        found = set(
            printings_for_illustration(shared, candidate_printing_pks=[shared_ccs[0].pk, odd_one.pk]).values_list(
                "pk", flat=True
            )
        )
        assert found == {shared_ccs[0].pk}

    def test_the_scope_reaches_the_compiled_sql(self, db):
        """Batch-scale cost, asserted on the compiled SQL rather than only on the result set -
        the same evidence standard `TestEligibleIllustrationCardsQuerysetCardIdScoping` uses.

        ASSERTED ON THE PREDICATE, NOT ON A BARE PK SUBSTRING (fixed 2026-07-29). This test used
        to assert `str(pk) not in unscoped_sql`, which is only true while the pk happens to be a
        digit string that appears nowhere else in the query. It is not: the query embeds
        `illustration_id` UUIDs verbatim, and a single-digit pk ("1", "2", ...) is a substring of
        almost any UUID, so the assertion passed or failed purely on where Postgres' sequence
        happened to be when the test ran - i.e. on which OTHER test files ran first. Adding one
        row-creating test anywhere earlier in the suite was enough to flip it. The predicate
        itself is what the test means, so that is what it now checks."""
        shared, _other, shared_ccs, _odd = self._catalog()
        scoped_sql = str(printings_for_illustration(shared, candidate_printing_pks=[shared_ccs[0].pk]).query)
        unscoped_sql = str(printings_for_illustration(shared).query)
        scoping_predicate = f'"cardpicker_canonicalcard"."id" IN ({shared_ccs[0].pk})'
        assert scoping_predicate in scoped_sql
        assert scoping_predicate not in unscoped_sql
        assert '"cardpicker_canonicalcard"."id" IN (' not in unscoped_sql

    def test_an_unknown_illustration_narrows_to_nothing(self, db):
        self._catalog()
        assert printings_for_illustration(uuid.uuid4()).count() == 0

    def test_it_returns_a_lazy_queryset_and_writes_nothing(self, db):
        shared, _other, _shared_ccs, _odd = self._catalog()
        with CaptureQueriesContext(connection) as captured:
            queryset = printings_for_illustration(shared)
        assert len(captured) == 0, "constructing the narrowing must not hit the database"
        assert queryset.count() >= 1
        assert CardPrintingTag.objects.count() == 0


# =============================================================================================
# The machine illustration writer (issue #524, task 2)
# =============================================================================================


class TestIllustrationVoteWriter:
    """`run_illustration_calculator` writes a `CardIllustrationVote` whenever it resolves exactly
    ONE illustration - INCLUDING the cards issue #525's 1:1 rule makes abstain from a printing
    vote. #526 retained `illustration_id` on the verdict for exactly this consumer."""

    def _artist_and_card(self, artist_name="Artist Q", card_name="Dragon"):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code="lea")
        card = _eligible_card(name=card_name)
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name=artist_name)
        return artist, expansion, card

    def test_one_illustration_many_printings_writes_the_illustration_vote_and_no_printing_vote(self, db):
        """THE CASE THIS WHOLE ISSUE EXISTS FOR. Pre-#524 this card produced nothing but a
        `CardScanLog` skip string; the resolved artwork identity was discarded. The 1:1 printing
        rule is UNCHANGED - still zero printing votes."""
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        for _ in range(3):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)

        result = run_illustration_calculator(dry_run=False)

        assert result.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0
        assert result.illustration_votes_written == 1
        vote = CardIllustrationVote.objects.get(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        assert vote.illustration_id == shared_illustration
        assert vote.is_unknown is False
        assert vote.source == VoteSource.DEDUCTION
        assert vote.confidence == BASE_CONFIDENCE
        assert vote.run_id == result.run_id
        # #526's abstain reason is retained unchanged.
        assert CardScanLog.objects.filter(
            card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason=MULTIPLE_PRINTINGS_SKIP_REASON
        ).exists()

    def test_the_illustration_vote_is_not_expanded_into_printing_votes(self, db):
        """The narrowing stays a read. One artwork vote, never one vote per printing sharing it -
        that expansion is issue #525's defect, restated at a new grain."""
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        for _ in range(4):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)

        run_illustration_calculator(dry_run=False)

        assert CardIllustrationVote.objects.filter(card=card).count() == 1
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0
        # ...and the narrowing the single vote implies is still fully recoverable, as a READ.
        assert printings_for_illustration(shared_illustration).count() == 4

    def test_the_one_to_one_case_writes_both_grains(self, db):
        artist, expansion, card = self._artist_and_card()
        illustration = uuid.uuid4()
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration)

        result = run_illustration_calculator(dry_run=False)

        assert result.votes_written == 1
        assert CardPrintingTag.objects.get(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).printing_id == cc.pk
        assert result.illustration_votes_written == 1
        assert CardIllustrationVote.objects.get(card=card).illustration_id == illustration

    def test_multiple_illustrations_writes_no_illustration_vote(self, db):
        """N>1 illustrations: no single identity exists, so nothing is recorded at either grain and
        #526's skip reason is untouched. Inventing a representative would be picking an answer the
        evidence does not support."""
        artist, expansion, card = self._artist_and_card()
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        result = run_illustration_calculator(dry_run=False)

        assert result.illustration_votes_written == 0
        assert CardIllustrationVote.objects.count() == 0
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0
        assert CardScanLog.objects.filter(
            card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason=MULTIPLE_ILLUSTRATIONS_SKIP_REASON
        ).exists()

    def test_no_candidate_match_writes_no_illustration_vote(self, db):
        artist, expansion, card = self._artist_and_card(artist_name="Artist Q")
        cc = CanonicalCardFactory(
            name="Dragon", artist=CanonicalArtistFactory(name="Someone Else"), expansion=expansion
        )
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        result = run_illustration_calculator(dry_run=False)

        assert result.illustration_votes_written == 0
        assert CardIllustrationVote.objects.count() == 0

    def test_dry_run_writes_no_illustration_vote_but_still_counts_it(self, db):
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)

        result = run_illustration_calculator(dry_run=True)

        assert result.illustration_votes_would_cast == 1
        assert result.illustration_votes_written == 0
        assert CardIllustrationVote.objects.count() == 0

    def test_both_grains_share_the_one_identity(self, db):
        """#524's property: the printing grain and the illustration grain are written under ONE
        `anonymous_id`, not two. (The v1 → v2 bump that landed later moves that single string;
        it does not split it - see `TestCalculatorVersionBump`.)"""
        artist, expansion, card = self._artist_and_card()
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        run_illustration_calculator(dry_run=False)

        assert CardIllustrationVote.objects.get(card=card).anonymous_id == ILLUSTRATION_ANONYMOUS_ID

    def test_illustration_votes_carry_the_run_id(self, db):
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)

        result = run_illustration_calculator(dry_run=False)

        assert CardIllustrationVote.objects.filter(run_id=result.run_id).count() == 1


# =============================================================================================
# Idempotence, the changed-answer path, and cancel-safety for the illustration grain
# =============================================================================================


class TestIllustrationVoteIdempotenceAndCorrection:
    """The design point the unconditional UNIQUE(card, anonymous_id) forces: the pre-write split
    must compare the illustration_id VALUE, not just the (card, anonymous_id) KEY. A key-only
    comparison makes an unchanged answer AND a corrected answer both look like collisions, so the
    corrected one can never land - and `ignore_conflicts=True` swallows the attempt silently."""

    def _artist_and_card(self, artist_name="Artist Q", card_name="Dragon"):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code="lea")
        card = _eligible_card(name=card_name)
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name=artist_name)
        return artist, expansion, card

    def test_an_unchanged_answer_is_a_no_op_counted_as_already_voted(self, db):
        card = _eligible_card()
        illustration = uuid.uuid4()
        existing = CardIllustrationVote.objects.create(
            card=card, illustration_id=illustration, is_unknown=False, anonymous_id=ILLUSTRATION_ANONYMOUS_ID
        )
        proposed = CardIllustrationVote(
            card_id=card.pk,
            illustration_id=str(illustration),  # str, as the verdict carries it
            is_unknown=False,
            anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
        )

        new_votes, already_voted = _split_new_illustration_votes([proposed])

        assert new_votes == []
        assert already_voted == 1
        assert CardIllustrationVote.objects.get(pk=existing.pk).illustration_id == illustration

    def test_a_changed_answer_is_kept_by_the_split(self, db):
        """THE CASE A KEY-ONLY COMPARISON SILENTLY BREAKS. Same card, same identity, DIFFERENT
        illustration - a corrected conclusion, not a collision."""
        card = _eligible_card()
        CardIllustrationVote.objects.create(
            card=card, illustration_id=uuid.uuid4(), is_unknown=False, anonymous_id=ILLUSTRATION_ANONYMOUS_ID
        )
        corrected = uuid.uuid4()
        proposed = CardIllustrationVote(
            card_id=card.pk,
            illustration_id=str(corrected),
            is_unknown=False,
            anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
        )

        new_votes, already_voted = _split_new_illustration_votes([proposed])

        assert new_votes == [proposed]
        assert already_voted == 0

    def test_a_changed_answer_lands_end_to_end(self, db):
        """THE REGRESSION TEST FOR THE DESIGN POINT, through the real runner: a metadata refresh
        moves the card's artwork to a different illustration, and the stored vote must FOLLOW it.
        Under a key-only split this assertion fails with the stale UUID still in the row."""
        artist, expansion, card = self._artist_and_card()
        first_illustration = uuid.uuid4()
        ccs = []
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=first_illustration)
            ccs.append(cc)

        first = run_illustration_calculator(dry_run=False)
        assert first.illustration_votes_written == 1
        stored = CardIllustrationVote.objects.get(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        assert stored.illustration_id == first_illustration

        # A metadata refresh: `import_scryfall_printing_metadata` re-populates illustration_id in
        # place, and this card's artwork now resolves to a different illustration. (The scan-log
        # row and the index cache from the first run are cleared the way an operator's re-run
        # would clear them.)
        corrected_illustration = uuid.uuid4()
        for cc in ccs:
            cc.printing_metadata.illustration_id = corrected_illustration
            cc.printing_metadata.save(update_fields=["illustration_id"])
        CardScanLog.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).delete()
        reset_illustration_index_cache_for_tests()

        second = run_illustration_calculator(dry_run=False)

        assert second.illustration_votes_already_voted == 0
        assert second.illustration_votes_written == 1
        # ONE row, carrying the CORRECTED value - the unconditional constraint guarantees the first.
        rows = CardIllustrationVote.objects.filter(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID)
        assert rows.count() == 1
        assert rows.get().illustration_id == corrected_illustration

    def test_rerunning_with_an_unchanged_answer_writes_nothing_end_to_end(self, db):
        """The other half of the same seam: idempotence must survive the value comparison."""
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)

        first = run_illustration_calculator(dry_run=False)
        original_pk = CardIllustrationVote.objects.get(card=card).pk
        CardScanLog.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).delete()

        second = run_illustration_calculator(dry_run=False)

        assert first.illustration_votes_written == 1
        assert second.illustration_votes_written == 0
        assert second.illustration_votes_already_voted == 1
        # untouched, not deleted-and-reinserted.
        assert CardIllustrationVote.objects.get(card=card).pk == original_pk

    def test_a_stale_version_row_is_overwritten_not_counted_as_a_collision(self, db):
        """Calculator-version self-overwrite (#519/#520) at the new grain: a `...-v0` row is a
        different anonymous_id, so the split never sees it, and the family-scoped purge removes it
        before the current version's row lands."""
        artist, expansion, card = self._artist_and_card()
        stale = CardIllustrationVote.objects.create(
            card=card,
            illustration_id=uuid.uuid4(),
            is_unknown=False,
            anonymous_id="stage-d-illustration-v0",
            source=VoteSource.DEDUCTION,
        )
        illustration = uuid.uuid4()
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration)

        result = run_illustration_calculator(dry_run=False)

        assert result.illustration_votes_already_voted == 0
        assert not CardIllustrationVote.objects.filter(pk=stale.pk).exists()
        assert CardIllustrationVote.objects.get(card=card).illustration_id == illustration

    def test_a_human_vote_on_the_same_card_is_never_purged(self, db):
        """`purge_stale_machine_votes` returns 0 for a non-machine anonymous_id (human voters use
        UUIDs, which never match the `<family>-v<n>` shape), so a human's illustration answer
        survives every calculator re-run - and the unconditional constraint does not stand in the
        way, because it is scoped per identity."""
        artist, expansion, card = self._artist_and_card()
        human_illustration = uuid.uuid4()
        human = CardIllustrationVote.objects.create(
            card=card,
            illustration_id=human_illustration,
            is_unknown=False,
            anonymous_id=str(uuid.uuid4()),
            source=VoteSource.USER,
        )
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        run_illustration_calculator(dry_run=False)

        assert CardIllustrationVote.objects.get(pk=human.pk).illustration_id == human_illustration
        assert CardIllustrationVote.objects.filter(card=card).count() == 2

    def test_the_purge_is_scoped_to_the_rows_being_written(self, db):
        """A card whose vote the split skipped as unchanged must KEEP its row. Purging the full
        batch would delete it and then not re-insert it - the vote destroyed to replace it with
        nothing."""
        artist, expansion, card = self._artist_and_card()
        shared_illustration = uuid.uuid4()
        for _ in range(2):
            cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
            CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=shared_illustration)
        existing = CardIllustrationVote.objects.create(
            card=card,
            illustration_id=shared_illustration,
            is_unknown=False,
            anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
            source=VoteSource.DEDUCTION,
        )

        result = run_illustration_calculator(dry_run=False)

        assert result.illustration_votes_already_voted == 1
        assert result.illustration_votes_written == 0
        assert CardIllustrationVote.objects.filter(pk=existing.pk).exists()

    def test_a_failed_illustration_insert_rolls_its_purge_back(self, db, monkeypatch):
        """Cancel-safety, same shape as `TestPurgeAndInsertAreAtomic` for the printing grain: the
        DELETE and the INSERT are separate statements, and a mid-flight kill between them must not
        leave the card with its previous vote gone and nothing written back."""
        artist, expansion, card = self._artist_and_card()
        stale = CardIllustrationVote.objects.create(
            card=card,
            illustration_id=uuid.uuid4(),
            is_unknown=False,
            anonymous_id="stage-d-illustration-v0",
            source=VoteSource.DEDUCTION,
        )
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")

        monkeypatch.setattr(CardIllustrationVote.objects, "bulk_create", _boom)

        with pytest.raises(RuntimeError):
            run_illustration_calculator(dry_run=False)

        assert CardIllustrationVote.objects.filter(pk=stale.pk).exists()

    def test_the_split_runs_before_the_purge(self, db, monkeypatch):
        """Ordering, asserted directly: if the purge ran first it would delete exactly the rows the
        split then looks for, and `illustration_votes_already_voted` would read 0 forever - the
        "zero forever suggests the guard is dead code" failure `_purge_and_write_printing_tag_votes`
        documents, reproduced at the new grain."""
        import cardpicker.local_illustration as module

        calls: list[str] = []
        real_split = module._split_new_illustration_votes
        real_write = module._purge_and_write_illustration_votes

        def _tracked_split(batch):
            calls.append("split")
            return real_split(batch)

        def _tracked_write(anonymous_id, votes):
            calls.append("purge_and_write")
            return real_write(anonymous_id, votes)

        monkeypatch.setattr(module, "_split_new_illustration_votes", _tracked_split)
        monkeypatch.setattr(module, "_purge_and_write_illustration_votes", _tracked_write)

        artist, expansion, card = self._artist_and_card()
        cc = CanonicalCardFactory(name="Dragon", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        run_illustration_calculator(dry_run=False)

        assert calls == ["split", "purge_and_write"]

    def test_an_empty_batch_purges_nothing(self, db):
        from cardpicker.local_illustration import _purge_and_write_illustration_votes

        card = _eligible_card()
        untouched = CardIllustrationVote.objects.create(
            card=card,
            illustration_id=uuid.uuid4(),
            is_unknown=False,
            anonymous_id=ILLUSTRATION_ANONYMOUS_ID,
            source=VoteSource.DEDUCTION,
        )

        _purge_and_write_illustration_votes(ILLUSTRATION_ANONYMOUS_ID, [])

        assert CardIllustrationVote.objects.filter(pk=untouched.pk).exists()


# =============================================================================================
# Issue #523 — the invariant lock
# =============================================================================================


class TestArtistInputIsOcrDerivedNotVoteDerived:
    """ISSUE #523's INVARIANT: `stage-d-illustration-v1`'s artist input MUST come from OCR
    evidence, never from artist votes.

    WHY THIS LANDS WITH #524 AND NOT AFTER. `illustration_id -> artist` is functional, so an
    illustration answer can legitimately derive a `CardArtistVote`. This calculator runs the
    INVERSE direction - OCR artist name in, illustration out. Wire the derived artist vote back in
    as the calculator's artist input and the loop closes: the calculator re-confirms an artist that
    was itself derived from an illustration the calculator proposed, manufacturing multi-source
    agreement out of a single click. Before #524 there were no illustration votes at all, so the
    loop was unreachable; #524 is what makes it reachable, which is why the lock ships with it.

    #523 asks for the assertion to be on THE SEAM - the argument passed to `match_artist` - rather
    than on the verdict, because a rewire that changed the source could still produce an identical
    verdict on any given fixture."""

    def _index_and_candidates(self, artist_name, card_name, illustration_uuid):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name=card_name, artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration_uuid)
        return artist, cc, IllustrationIndex(), [type("_C", (), {"pk": cc.pk})()]

    def test_match_artist_receives_exactly_the_ocr_name(self, db, monkeypatch):
        """The seam assertion. Fails the moment the first argument stops being
        `evidence.artist_ocr_name`."""
        import cardpicker.local_illustration as module

        artist, cc, index, candidates = self._index_and_candidates("Christopher Rush", "Lightning Bolt", uuid.uuid4())
        captured: list = []
        real_match_artist = module.match_artist

        def _capture(ocr_name, cands, artist_by_pk):
            captured.append(ocr_name)
            return real_match_artist(ocr_name, cands, artist_by_pk)

        monkeypatch.setattr(module, "match_artist", _capture)
        evidence = type("E", (), {"artist_ocr_name": "Christopher Rush"})()

        module.calculate_illustration_verdict(
            card_id=1,
            evidence=evidence,
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="lightning bolt",
        )

        assert captured == [evidence.artist_ocr_name]

    def test_a_contradicting_artist_vote_does_not_change_the_artist_input(self, db, monkeypatch):
        """The adversarial version: a `CardArtistVote` naming a DIFFERENT artist exists for this
        card. If the artist input were ever sourced from votes, the captured value would be the
        vote's artist. It must remain the OCR string."""
        import cardpicker.local_illustration as module

        artist, cc, index, candidates = self._index_and_candidates("Christopher Rush", "Lightning Bolt", uuid.uuid4())
        voted_artist = CanonicalArtistFactory(name="Rebecca Guay")
        card = _eligible_card(name="Lightning Bolt")
        CardArtistVote.objects.create(
            card=card, artist=voted_artist, is_unknown=False, anonymous_id="voter-a", source=VoteSource.USER
        )

        captured: list = []
        real_match_artist = module.match_artist

        def _capture(ocr_name, cands, artist_by_pk):
            captured.append(ocr_name)
            return real_match_artist(ocr_name, cands, artist_by_pk)

        monkeypatch.setattr(module, "match_artist", _capture)

        module.calculate_illustration_verdict(
            card_id=card.pk,
            evidence=type("E", (), {"artist_ocr_name": "Christopher Rush"})(),
            illustration_index=index,
            candidates=candidates,
            searchable_card_name="lightning bolt",
        )

        assert captured == ["Christopher Rush"]
        assert "Rebecca Guay" not in captured

    def test_the_verdict_path_never_queries_cardartistvote(self, db):
        """The structural half: not one SQL statement issued while computing a verdict may touch
        the `CardArtistVote` table. This fails on ANY rewire that reads votes for the artist input,
        including one that reaches them through a helper rather than at this call site."""
        artist, cc, index, candidates = self._index_and_candidates("Christopher Rush", "Lightning Bolt", uuid.uuid4())
        card = _eligible_card(name="Lightning Bolt")
        CardArtistVote.objects.create(
            card=card,
            artist=CanonicalArtistFactory(name="Rebecca Guay"),
            is_unknown=False,
            anonymous_id="voter-a",
            source=VoteSource.USER,
        )

        with CaptureQueriesContext(connection) as captured:
            calculate_illustration_verdict(
                card_id=card.pk,
                evidence=type("E", (), {"artist_ocr_name": "Christopher Rush"})(),
                illustration_index=index,
                candidates=candidates,
                searchable_card_name="lightning bolt",
            )

        offending = [q["sql"] for q in captured.captured_queries if CardArtistVote._meta.db_table in q["sql"]]
        assert offending == [], f"artist input must never be vote-derived (issue #523); saw: {offending}"

    def test_the_whole_runner_never_queries_cardartistvote(self, db):
        """End to end, including the eligibility query and both write paths - the calculator as a
        whole must not read artist votes."""
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush")
        CardArtistVote.objects.create(
            card=card,
            artist=CanonicalArtistFactory(name="Rebecca Guay"),
            is_unknown=False,
            anonymous_id="voter-a",
            source=VoteSource.USER,
        )
        reset_illustration_index_cache_for_tests()

        with CaptureQueriesContext(connection) as captured:
            run_illustration_calculator(dry_run=True)

        offending = [q["sql"] for q in captured.captured_queries if CardArtistVote._meta.db_table in q["sql"]]
        assert offending == [], f"artist input must never be vote-derived (issue #523); saw: {offending}"


# =============================================================================================
# THE BORDER-COLOUR MISREAD, AND THE PER-FACE DATA THAT REPLACED THE GATE (2026-07-29)
#
# v1 skipped every card whose `ImageEvidence.layout_class` was non-blank, on the stated premise
# that the column records faced-ness. It does not: its only writer is
# `local_fallback.classify_border_color` and it holds a BORDER COLOUR. Measured live distribution
# at the time of the fix: black 138,728 / borderless 72,603 / white 7,475 / '' 1,455 /
# silver 408 - non-blank on 99.34% of rows, so the gate discarded 99.28% of every population
# handed to the calculator (3,409 `multi-faced-v1` scan-log rows out of 3,426 scanned; 3
# illustration votes cast in the calculator's entire existence against 230,753 catalog cards).
#
# WHY THE TEST THAT SHIPPED THIS WAS VACUOUS, stated here so it is not re-derived: the deleted
# `test_skips_multi_faced_cards` built its fixture with `layout_class="split"` - a value the
# field's only writer can never emit. It invented the taxonomy the production comment claimed,
# so it passed green while asserting behaviour the production predicate inverted. Every test
# below is parametrised over, or fixtured with, values `classify_border_color` ACTUALLY emits.
# =============================================================================================


# The live `ImageEvidence.layout_class` vocabulary, measured 2026-07-29 (counts above). Every
# non-blank one of these was a skip under v1.
_REAL_LAYOUT_CLASS_VALUES = ["black", "borderless", "white", "silver", ""]


class TestLayoutClassIsNotFacedness:
    def _single_faced_setup(self, layout_class):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        illustration = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration)
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush", layout_class=layout_class)
        reset_illustration_index_cache_for_tests()
        return card, cc, illustration

    @pytest.mark.parametrize("layout_class", _REAL_LAYOUT_CLASS_VALUES)
    def test_a_border_colour_no_longer_skips_a_single_faced_card(self, db, layout_class):
        """THE defect, directly: an ordinary single-faced Lightning Bolt with a black border was
        skipped as "multi-faced". Under v1 every non-blank parametrisation of this test produces
        `cards_considered == 0` and no vote."""
        card, cc, illustration = self._single_faced_setup(layout_class)

        result = run_illustration_calculator(dry_run=True)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert result.illustration_votes_would_cast == 1
        assert result.skip_counts == {}

    @pytest.mark.parametrize("layout_class", _REAL_LAYOUT_CLASS_VALUES)
    def test_the_vote_actually_lands_for_every_border_colour(self, db, layout_class):
        card, cc, illustration = self._single_faced_setup(layout_class)

        run_illustration_calculator(dry_run=False)

        assert CardPrintingTag.objects.get(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).printing_id == cc.pk
        assert CardIllustrationVote.objects.get(card=card).illustration_id == illustration

    def test_no_skip_reason_records_facedness_at_all(self, db):
        """The gate is DELETED, not renamed or relocated. Nothing in this module may reintroduce
        a faced-ness skip under any spelling, because faced-ness is now answered by per-face
        data rather than by refusing to look."""
        import cardpicker.local_illustration as module

        skip_reasons = [
            value for name, value in vars(module).items() if name.endswith("_SKIP_REASON") and isinstance(value, str)
        ]

        assert "multi-faced-v1" not in skip_reasons
        assert not [reason for reason in skip_reasons if "face" in reason]
        assert not hasattr(module.IllustrationCalculatorResult(), "multi_faced_skipped")


# =============================================================================================
# Per-face illustration ids in the index
# =============================================================================================


def _dfc_metadata(canonical_card, front_illustration, back_illustration, front_name, back_name):
    """A `CanonicalPrintingMetadata` row shaped exactly as `import_scryfall_printing_metadata`
    writes one for a genuine double-faced printing: scalar `illustration_id` = the FRONT face
    (backwards compatibility for the four consumers of that column), plus every face's own id
    under `face_illustrations` in `card_faces` order."""
    return CanonicalPrintingMetadataFactory(
        canonical_card=canonical_card,
        illustration_id=front_illustration,
        face_illustrations=[
            {"name": front_name, "illustration_id": str(front_illustration)},
            {"name": back_name, "illustration_id": str(back_illustration)},
        ],
    )


class TestIllustrationIndexPerFaceKeys:
    def _dfc(self):
        artist = CanonicalArtistFactory(name="Nils Hamm")
        expansion = CanonicalExpansionFactory(code="isd")
        cc = CanonicalCardFactory(name="Delver of Secrets // Insectile Aberration", artist=artist, expansion=expansion)
        front, back = uuid.uuid4(), uuid.uuid4()
        _dfc_metadata(cc, front, back, "Delver of Secrets", "Insectile Aberration")
        return artist, cc, front, back

    def test_the_back_faces_own_illustration_is_filed_under_the_back_faces_name(self, db):
        """The whole point of storing per-face ids: a back-face scan resolves to the artwork
        printed on the side that was scanned. Under the pre-fix index the only key for this
        printing was the combined name, carrying the FRONT face's id."""
        artist, cc, front, back = self._dfc()

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "insectile aberration") == {str(back): [cc.pk]}

    def test_the_front_faces_own_illustration_is_filed_under_the_front_faces_name(self, db):
        artist, cc, front, back = self._dfc()

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "delver of secrets") == {str(front): [cc.pk]}

    def test_the_combined_name_key_is_unchanged_and_still_the_front_face(self, db):
        """Four consumers read the scalar column and this key is what the pre-fix index built
        from it. The per-face keys are ADDITIVE; this one must not move."""
        artist, cc, front, back = self._dfc()

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "delver of secrets insectile aberration") == {
            str(front): [cc.pk]
        }

    def test_a_printing_with_no_face_illustrations_contributes_only_its_own_name_key(self, db):
        """The single-faced case, and the shape a split/adventure row is imported as
        (`face_illustrations == []`) - so no second MODE can become a second scannable artwork."""
        artist = CanonicalArtistFactory(name="Artist S")
        expansion = CanonicalExpansionFactory(code="eld")
        cc = CanonicalCardFactory(name="Bonecrusher Giant // Stomp", artist=artist, expansion=expansion)
        illustration = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration, face_illustrations=[])

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "bonecrusher giant stomp") == {str(illustration): [cc.pk]}
        assert index.illustration_printings(artist.pk, "stomp") == {}
        assert index.illustration_printings(artist.pk, "bonecrusher giant") == {}

    def test_a_face_with_no_artwork_of_its_own_is_not_indexed_as_the_string_none(self, db):
        artist = CanonicalArtistFactory(name="Artist T")
        expansion = CanonicalExpansionFactory(code="mid")
        cc = CanonicalCardFactory(name="A Front // A Back", artist=artist, expansion=expansion)
        front = uuid.uuid4()
        CanonicalPrintingMetadataFactory(
            canonical_card=cc,
            illustration_id=front,
            face_illustrations=[
                {"name": "A Front", "illustration_id": str(front)},
                {"name": "A Back", "illustration_id": None},
            ],
        )

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "a back") == {}
        assert "None" not in index.illustration_printings(artist.pk, "a front")

    def test_a_face_name_colliding_with_a_differently_illustrated_card_reads_as_ambiguous(self, db):
        """`reversible_card` basic lands are the real instance: the same artist can have both a
        single-faced "Island" and a reversible "Island" face with different art. The key
        accumulates both artworks and the calculator abstains - the safe AND honest direction,
        since such a scan genuinely does not say which artwork it is."""
        artist = CanonicalArtistFactory(name="John Avon")
        expansion = CanonicalExpansionFactory(code="sld")
        plain = CanonicalCardFactory(name="Island", artist=artist, expansion=expansion)
        plain_illustration = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=plain, illustration_id=plain_illustration)
        reversible = CanonicalCardFactory(name="Island // Island", artist=artist, expansion=expansion)
        _dfc_metadata(reversible, uuid.uuid4(), uuid.uuid4(), "Island", "Island")

        index = IllustrationIndex()

        assert len(index.illustration_printings(artist.pk, "island")) == 3


class TestIllustrationIndexCacheSeesFaceBackfill:
    def test_populating_face_illustrations_in_place_invalidates_the_cached_index(self, db):
        """`face_illustrations` is BACKFILLED BY UPDATE - `import_scryfall_printing_metadata`
        populates it on rows that already exist, moving neither max pk nor row count nor the
        non-null `illustration_id` count. Without its own version-stamp term a worker process
        that built the index before the backfill would serve a stale, face-less index for its
        whole lifetime."""
        artist = CanonicalArtistFactory(name="Nils Hamm")
        expansion = CanonicalExpansionFactory(code="isd")
        cc = CanonicalCardFactory(name="Delver of Secrets // Insectile Aberration", artist=artist, expansion=expansion)
        front, back = uuid.uuid4(), uuid.uuid4()
        metadata = CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=front, face_illustrations=[])
        reset_illustration_index_cache_for_tests()

        assert _get_cached_illustration_index().illustration_printings(artist.pk, "insectile aberration") == {}

        metadata.face_illustrations = [
            {"name": "Delver of Secrets", "illustration_id": str(front)},
            {"name": "Insectile Aberration", "illustration_id": str(back)},
        ]
        metadata.save(update_fields=["face_illustrations"])

        assert _get_cached_illustration_index().illustration_printings(artist.pk, "insectile aberration") == {
            str(back): [cc.pk]
        }


class TestPrintingsForIllustrationCoversBackFaces:
    def test_a_back_face_artwork_narrows_to_the_printing_that_carries_it(self, db):
        """The scalar column only ever holds the FRONT face's artwork, so a back-face
        illustration vote - which this calculator can now cast - would narrow to zero printings
        under a scalar-only filter: silently "no printing carries this artwork" when the truth is
        "the column we looked in never stores that side"."""
        artist = CanonicalArtistFactory(name="Nils Hamm")
        expansion = CanonicalExpansionFactory(code="isd")
        cc = CanonicalCardFactory(name="Delver of Secrets // Insectile Aberration", artist=artist, expansion=expansion)
        front, back = uuid.uuid4(), uuid.uuid4()
        _dfc_metadata(cc, front, back, "Delver of Secrets", "Insectile Aberration")

        assert list(printings_for_illustration(back).values_list("pk", flat=True)) == [cc.pk]
        assert list(printings_for_illustration(front).values_list("pk", flat=True)) == [cc.pk]

    def test_an_unrelated_artwork_still_narrows_to_nothing(self, db):
        artist = CanonicalArtistFactory(name="Nils Hamm")
        expansion = CanonicalExpansionFactory(code="isd")
        cc = CanonicalCardFactory(name="Delver of Secrets // Insectile Aberration", artist=artist, expansion=expansion)
        _dfc_metadata(cc, uuid.uuid4(), uuid.uuid4(), "Delver of Secrets", "Insectile Aberration")

        assert printings_for_illustration(uuid.uuid4()).count() == 0


# =============================================================================================
# End to end: a back-face-named upload votes the BACK face's own artwork
# =============================================================================================


def _write_bulk_data_file(tmp_path, records):
    """Same shape as `test_local_calculate_verdicts.py`'s own helper - deliberately duplicated
    (not imported cross-module) matching this test suite's per-module small-helper convention."""
    path = tmp_path / "default_cards.json"
    path.write_text("[\n" + "\n".join(json.dumps(record) + "," for record in records) + "\n]")
    return path


class TestBackFaceNamedUploadEndToEnd:
    """The cohort v1's gate could never reach, and the reason the gate could be DELETED rather
    than repaired. A source that splits a double-faced card into two image files names the second
    one after the BACK face; `CanonicalCard.name` is Scryfall's combined "{front} // {back}", so
    the candidate lookup has to widen - but the ILLUSTRATION lookup must NOT, or the scan gets
    attributed to the front's artwork, which is exactly the wrong-vote exposure the gate stood
    in for."""

    def _setup(self, tmp_path, upload_name="Insectile Aberration"):
        artist = CanonicalArtistFactory(name="Nils Hamm")
        expansion = CanonicalExpansionFactory(code="isd")
        cc = CanonicalCardFactory(name="Delver of Secrets // Insectile Aberration", artist=artist, expansion=expansion)
        front, back = uuid.uuid4(), uuid.uuid4()
        _dfc_metadata(cc, front, back, "Delver of Secrets", "Insectile Aberration")
        DFCPairFactory(front="Delver of Secrets", back="Insectile Aberration")
        path = _write_bulk_data_file(
            tmp_path,
            [
                {
                    "id": str(uuid.uuid4()),
                    "layout": "transform",
                    "card_faces": [{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}],
                }
            ],
        )
        card = _eligible_card(name=upload_name)
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Nils Hamm", layout_class="black")
        reset_illustration_index_cache_for_tests()
        return card, cc, front, back, path

    def test_the_vote_is_the_back_faces_artwork_not_the_fronts(self, db, tmp_path):
        card, cc, front, back, path = self._setup(tmp_path)

        result = run_illustration_calculator(dry_run=False, default_cards_path=path)

        assert result.back_face_resolved == 1
        vote = CardIllustrationVote.objects.get(card=card)
        assert vote.illustration_id == back
        assert vote.illustration_id != front

    def test_the_printing_vote_is_cast_for_the_one_double_faced_printing(self, db, tmp_path):
        card, cc, front, back, path = self._setup(tmp_path)

        run_illustration_calculator(dry_run=False, default_cards_path=path)

        assert CardPrintingTag.objects.get(card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID).printing_id == cc.pk

    def test_a_front_named_upload_still_takes_the_direct_path_unwidened(self, db, tmp_path):
        """`Card.name` matching a `CanonicalCard.name` directly must behave byte-identically to
        before: same candidates, same `to_searchable(card.name)` illustration key, no DFCPair
        lookup."""
        card, cc, front, back, path = self._setup(tmp_path, upload_name="Delver of Secrets // Insectile Aberration")

        result = run_illustration_calculator(dry_run=False, default_cards_path=path)

        assert result.back_face_resolved == 0
        assert CardIllustrationVote.objects.get(card=card).illustration_id == front

    def test_a_back_face_with_no_synced_dfc_pair_row_abstains_rather_than_guessing(self, db, tmp_path):
        card, cc, front, back, path = self._setup(tmp_path)
        DFCPair.objects.all().delete()
        reset_illustration_index_cache_for_tests()

        result = run_illustration_calculator(dry_run=False, default_cards_path=path)

        assert result.skip_counts.get(NO_CANDIDATE_MATCH_SKIP_REASON) == 1
        assert CardIllustrationVote.objects.count() == 0

    def test_an_unknown_name_that_is_not_a_back_face_abstains(self, db, tmp_path):
        card, cc, front, back, path = self._setup(tmp_path, upload_name="Some Totally Unknown Card")

        result = run_illustration_calculator(dry_run=False, default_cards_path=path)

        assert result.back_face_resolved == 0
        assert result.skip_counts.get(NO_CANDIDATE_MATCH_SKIP_REASON) == 1
        assert CardPrintingTag.objects.filter(anonymous_id=ILLUSTRATION_ANONYMOUS_ID).count() == 0


# =============================================================================================
# The v1 -> v2 calculator version bump (required for the fix to have any effect at all)
# =============================================================================================


class TestCalculatorVersionBump:
    def test_the_anonymous_id_is_v2(self, db):
        assert ILLUSTRATION_ANONYMOUS_ID == "stage-d-illustration-v2"

    def test_the_calculator_family_is_unchanged_by_the_bump(self, db):
        """`models.calculator_family` strips the `-vN` suffix, so every family-keyed behaviour
        (`purge_stale_machine_votes`' family-scoped DELETE, `printing_consensus.agent_dedupe_key`
        one-agent-one-vote pooling) follows the bump automatically rather than needing its own
        edit.

        `vote_consensus.resolve_vote_weight` used to belong on that list and no longer does: the
        deductive-backfill zero-weight override was re-scoped 2026-07-29 from the calculator
        FAMILY to one specific RUN's `run_id` (owner clarification - the ruling zeroed a cohort
        as a measurement control, not a method). It never applied to this calculator either way;
        what the last assertion pins is simply that a version bump does not change this
        calculator's weight, now true for the simpler reason that neither version is in that
        cohort - and `run_id` is passed explicitly because it is a required argument, deliberately
        not defaulted (see `test_vote_consensus.TestZeroWeightCohortScopeIsPinned`)."""
        assert calculator_family(ILLUSTRATION_ANONYMOUS_ID) == "stage-d-illustration"
        assert calculator_family("stage-d-illustration-v1") == calculator_family(ILLUSTRATION_ANONYMOUS_ID)
        assert agent_dedupe_key("stage-d-illustration-v1") == agent_dedupe_key(ILLUSTRATION_ANONYMOUS_ID)
        assert resolve_vote_weight(VoteSource.DEDUCTION, ILLUSTRATION_ANONYMOUS_ID, None) == resolve_vote_weight(
            VoteSource.DEDUCTION, "stage-d-illustration-v1", None
        )

    def test_a_v1_multi_faced_scan_log_no_longer_excludes_the_card(self, db):
        """THE reason the bump is load-bearing rather than cosmetic: 3,409 cards carry a
        `multi-faced-v1` `CardScanLog` row, that reason is NOT in `RESCANNABLE_SKIP_REASONS`
        (which holds only `no-evidence`), and `_eligible_illustration_cards_queryset` excludes
        cards with a non-rescannable scan log for its OWN `anonymous_id`. A repaired v1 would
        never re-examine them."""
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        CardScanLog.objects.create(card=card, anonymous_id="stage-d-illustration-v1", skip_reason="multi-faced-v1")

        eligible = _eligible_illustration_cards_queryset(
            join_key_voted_card_ids=CardPrintingTag.objects.filter(
                anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
            ).values_list("card_id", flat=True),
            join_key_scanned_card_ids=[],
        )

        assert card.pk in set(eligible.values_list("pk", flat=True))
        assert "multi-faced-v1" not in RESCANNABLE_SKIP_REASONS

    def test_a_v2_scan_log_still_excludes_the_card(self, db):
        """The bump must not make genuine skips permanently re-runnable - the exclusion still
        works, it is just keyed on the NEW identity."""
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        CardScanLog.objects.create(
            card=card, anonymous_id=ILLUSTRATION_ANONYMOUS_ID, skip_reason=NO_CANDIDATE_MATCH_SKIP_REASON
        )

        eligible = _eligible_illustration_cards_queryset(
            join_key_voted_card_ids=CardPrintingTag.objects.filter(
                anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=True
            ).values_list("card_id", flat=True),
            join_key_scanned_card_ids=[],
        )

        assert card.pk not in set(eligible.values_list("pk", flat=True))

    def test_a_v1_illustration_vote_is_overwritten_by_a_v2_run_not_left_beside_it(self, db):
        """Version self-overwrite (#519/#520) via the family-scoped purge - a stale `-v1` row for
        the same card is DELETED, not left to compete with the `-v2` answer."""
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        illustration = uuid.uuid4()
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=illustration)
        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush", layout_class="black")
        CardIllustrationVote.objects.create(
            card=card,
            illustration_id=uuid.uuid4(),
            is_unknown=False,
            anonymous_id="stage-d-illustration-v1",
            source=VoteSource.DEDUCTION,
        )
        reset_illustration_index_cache_for_tests()

        run_illustration_calculator(dry_run=False)

        votes = CardIllustrationVote.objects.filter(card=card)
        assert votes.count() == 1
        assert votes.get().anonymous_id == ILLUSTRATION_ANONYMOUS_ID
        assert votes.get().illustration_id == illustration


class TestNameOnlyFaceIllustrations:
    """
    THE NAME-ONLY ENTRY: a `face_illustrations` list that is NON-EMPTY but carries no usable
    illustration on any face — every entry shaped `{"name": ..., "illustration_id": None}`.

    WHY IT EXISTS AND MUST NOT BE COLLAPSED TO `[]`. A name-only entry is the RECORD THAT WE
    LOOKED AT THAT FACE AND SCRYFALL PUBLISHES NO ILLUSTRATION FOR IT. Emptying the list would
    make "we looked and found nothing" indistinguishable from "we never looked" — the same
    abstention-versus-silence collapse that let frame-style and bleed-edge chips sit at zero rows
    unnoticed until the 2026-07-29 composition audit. Nor may the `None` entries be FILTERED out
    of a partly-populated list: indices are positional, and index N must stay face N (see
    `printing_metadata_import.PrintingMetadataRow.face_illustrations`' own docstring). The data is
    correct; only a careless READING of it would be wrong.

    THE HAZARD THIS PINS. Such a row satisfies the partial index `cpm_face_illustrations_present`
    (`condition=~Q(face_illustrations=[])`), so any consumer testing LIST TRUTHINESS as a proxy
    for "has back-face art" is wrong for exactly these rows. Only a test of
    `illustration_id is not None` is correct. Measured expectation for the authorised importer
    run: 1,594 of 113,224 printings get a non-empty list, of which 1,534 carry a real
    `illustration_id` on every face and **60 are name-only**. The column is empty everywhere
    today, so nothing can be wrong yet — that changes on the next import.

    AUDIT RESULT (2026-07-30): every consumer of the field is ALREADY CORRECT. Both real readers
    are pinned below. Stated plainly rather than left implied, because "we checked and found
    nothing to fix" is a result, and an unpinned correct-by-accident reading is one refactor away
    from being a wrong one.
    """

    def _name_only(self, artist_name="Artist NameOnly", card_name="N Front // N Back"):
        artist = CanonicalArtistFactory(name=artist_name)
        expansion = CanonicalExpansionFactory(code="mid")
        cc = CanonicalCardFactory(name=card_name, artist=artist, expansion=expansion)
        front = uuid.uuid4()
        metadata = CanonicalPrintingMetadataFactory(
            canonical_card=cc,
            illustration_id=front,
            face_illustrations=[
                {"name": "N Front", "illustration_id": None},
                {"name": "N Back", "illustration_id": None},
            ],
        )
        return artist, cc, front, metadata

    def test_the_index_files_no_per_face_key_for_a_name_only_row(self, db):
        """CONSUMER 1 — `IllustrationIndex._build`. It tests `illustration_id is None`, not list
        truthiness, so a name-only face contributes nothing. Under a truthiness reading the loop
        would still run and file keys under `"None"`, which would then match every OTHER name-only
        printing by the same artist and read as ambiguity that does not exist."""
        artist, cc, front, _ = self._name_only()

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "n front") == {}
        assert index.illustration_printings(artist.pk, "n back") == {}

    def test_the_combined_name_key_still_carries_the_scalar_front_illustration(self, db):
        """THE CONTROL. The row is not invisible — the scalar `illustration_id` column still
        indexes normally. Without this, the test above would pass just as well against a consumer
        that ignored the row entirely, which is a different (and also wrong) behaviour."""
        artist, cc, front, _ = self._name_only()

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "n front n back") == {str(front): [cc.pk]}

    def test_printings_for_illustration_never_matches_a_name_only_row_on_the_face_term(self, db):
        """CONSUMER 2 — `printings_for_illustration`'s JSONB containment term, which asks for
        `{"illustration_id": "<uuid>"}`. A `None` entry cannot satisfy it. Asserted against a
        SECOND printing that legitimately carries the id, so the query is proven to be finding
        real matches while excluding the name-only row, rather than finding nothing at all."""
        artist, name_only_cc, front, _ = self._name_only()
        real_back = uuid.uuid4()
        other = CanonicalCardFactory(
            name="R Front // R Back", artist=artist, expansion=CanonicalExpansionFactory(code="vow")
        )
        _dfc_metadata(other, uuid.uuid4(), real_back, "R Front", "R Back")

        matched = set(printings_for_illustration(real_back).values_list("pk", flat=True))

        assert matched == {other.pk}
        assert name_only_cc.pk not in matched

    def test_a_partly_name_only_row_keeps_its_populated_face_and_its_positions(self, db):
        """The mixed shape, and the reason `None` is retained rather than dropped: index N must
        stay face N. The populated face still indexes; the name-only one still does not."""
        artist = CanonicalArtistFactory(name="Artist Mixed")
        cc = CanonicalCardFactory(
            name="M Front // M Back", artist=artist, expansion=CanonicalExpansionFactory(code="mid")
        )
        back = uuid.uuid4()
        metadata = CanonicalPrintingMetadataFactory(
            canonical_card=cc,
            illustration_id=uuid.uuid4(),
            face_illustrations=[
                {"name": "M Front", "illustration_id": None},
                {"name": "M Back", "illustration_id": str(back)},
            ],
        )

        index = IllustrationIndex()

        assert index.illustration_printings(artist.pk, "m back") == {str(back): [cc.pk]}
        assert index.illustration_printings(artist.pk, "m front") == {}
        # The position of the populated face is preserved in storage, not compacted away.
        metadata.refresh_from_db()
        assert [face["illustration_id"] for face in metadata.face_illustrations] == [None, str(back)]

    def test_the_cache_version_stamp_counts_a_name_only_row_as_present(self, db):
        """DELIBERATE, and the one place a truthiness-shaped test IS correct. The stamp's job is
        CHANGE DETECTION so a per-worker-cached index is rebuilt — not "does this row carry usable
        art". A name-only entry appearing where there was none IS a change to the column, and
        under-counting it would leave a stale index cached. Rebuilding on a row that turns out to
        contribute no key is harmless; missing the write is not."""
        from cardpicker.local_illustration import _illustration_index_version_stamp

        before = _illustration_index_version_stamp()
        self._name_only()
        after = _illustration_index_version_stamp()

        assert after != before
        assert after[5] == before[5] + 1
