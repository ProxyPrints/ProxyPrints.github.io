"""
Tests for cardpicker.local_illustration (Stage D illustration deduction calculator, issue #507).

Covers: IllustrationIndex construction, 0/1/N vote shapes, confidence division, single-faced
filtering, dry-run no-writes, live gate (verify_zero_resolutions), purgeability via run_id,
and eligibility constraints (no join-key vote, no artist-ocr, no evidence, multi-faced skip).
"""

import uuid

import pytest

from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.local_illustration import (
    BASE_CONFIDENCE,
    ILLUSTRATION_ANONYMOUS_ID,
    NO_ARTIST_OCR_SKIP_REASON,
    NO_CANDIDATE_MATCH_SKIP_REASON,
    NO_EVIDENCE_SKIP_REASON,
    NO_ILLUSTRATION_INDEX_ENTRY_SKIP_REASON,
    RESCANNABLE_SKIP_REASONS,
    IllustrationIndex,
    _eligible_illustration_cards_queryset,
    _get_cached_illustration_index,
    calculate_illustration_verdict,
    reset_illustration_index_cache_for_tests,
    run_illustration_calculator,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    ImageEvidenceFactory,
)


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

    def test_single_illustration_votes_all_printings(self, db):
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
        assert 100 in verdict.printing_pks

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

    def test_multiple_illustrations_spreads_confidence(self, db):
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

        assert verdict.skip_reason == ""
        assert verdict.illustration_count == 2
        assert verdict.confidence == pytest.approx(BASE_CONFIDENCE / 2)
        assert len(verdict.printing_pks) == 2


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

    def test_skips_multi_faced_cards(self, db):
        artist = CanonicalArtistFactory(name="Christopher Rush")
        expansion = CanonicalExpansionFactory(code="lea")
        cc = CanonicalCardFactory(name="Lightning Bolt", artist=artist, expansion=expansion)
        CanonicalPrintingMetadataFactory(canonical_card=cc, illustration_id=uuid.uuid4())

        card = _eligible_card(name="Lightning Bolt")
        _join_key_no_hit_card(card)
        _make_evidence(card, artist_ocr_name="Christopher Rush", layout_class="split")

        result = run_illustration_calculator(dry_run=True)

        assert result.multi_faced_skipped >= 1
        assert result.cards_considered == 0

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
