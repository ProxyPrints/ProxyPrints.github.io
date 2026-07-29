"""
Tests for cardpicker.local_layout_class_cast (public issue #369, "the Hidden Courtyard should
register as borderless") - the layout-class caster: the mapping calculator (all four confident
`layout_class` values plus the blank/ambiguous and defensive unmapped-value cases), and the batch
runner's dry-run/write/idempotence/rescannability/gate-check behavior. No network calls, no live
image fetch - this module consumes stored `ImageEvidence` rows only, same "host venv, no network"
precedent `test_local_detect_ai_art.py` already establishes for this pipeline's later stages.
"""

import pytest

from cardpicker.attribute_tags import seed_attribute_tags
from cardpicker.default_tags import seed_default_tags
from cardpicker.local_fallback import (
    BORDER_ATTRIBUTE_VOTE_CONFIDENCE,
    BORDER_COLOR_TO_TAG,
)
from cardpicker.local_layout_class_cast import (
    LAYOUT_CLASS_CAST_ANONYMOUS_ID,
    _eligible_cards_queryset,
    calculate_layout_class_verdict,
    run_layout_class_cast,
)
from cardpicker.management.commands.purge_machine_votes import (
    verify_no_machine_only_resolutions,
)
from cardpicker.models import (
    CardScanLog,
    CardTagVote,
    Tag,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

_COMPLETE_EXTRACTOR_VERSIONS = {"geometry_bleed": "geometry-bleed-v1", "layout_class": "layout-class-v1"}


def _seed_tags() -> None:
    seed_default_tags()  # Borderless
    seed_attribute_tags()  # Black Border / White Border / Silver Border


def _evidence(card, **overrides):
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(_COMPLETE_EXTRACTOR_VERSIONS),
        layout_class="",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestCalculateLayoutClassVerdict:
    def test_blank_layout_class_is_not_a_hit(self, db):
        card = CardFactory(name="Some Card")
        evidence = _evidence(card, layout_class="")

        verdict = calculate_layout_class_verdict(card.pk, evidence)

        assert verdict.is_hit is False
        assert verdict.tag_name is None
        assert verdict.confidence is None

    def test_every_taxonomy_value_routes_through_the_shared_table_and_is_a_hit(self, db):
        """ROUTING, NOT MAPPING CONTENT. The expected tag name is read from
        BORDER_COLOR_TO_TAG, and `calculate_layout_class_verdict` IS a lookup in
        BORDER_COLOR_TO_TAG, so this compares the table against itself and cannot detect a
        wrong colour->tag pairing. What it does prove is the property worth proving here: no
        taxonomy value falls into the defensive non-hit branch, and the verdict carries the
        shared table's value rather than a second private copy.

        The table's CONTENTS are pinned to literals in
        test_local_fallback.py::test_each_taxonomy_color_maps_to_its_own_correct_tag - one
        place, deliberately, so the literals don't get copied into three files and drift.
        """
        for layout_class, tag_name in BORDER_COLOR_TO_TAG.items():
            card = CardFactory(name=f"Card {layout_class}")
            evidence = _evidence(card, layout_class=layout_class)

            verdict = calculate_layout_class_verdict(card.pk, evidence)

            assert verdict.is_hit is True
            assert verdict.tag_name == tag_name
            assert verdict.confidence == BORDER_ATTRIBUTE_VOTE_CONFIDENCE

    def test_hidden_courtyard_style_borderless_reading_maps_to_borderless_tag(self, db):
        # The exact motivating case (issue #369's own title).
        card = CardFactory(name="Hidden Courtyard")
        evidence = _evidence(card, layout_class="borderless")

        verdict = calculate_layout_class_verdict(card.pk, evidence)

        assert verdict.tag_name == "Borderless"

    def test_unmapped_layout_class_value_is_a_defensive_non_hit(self, db):
        # classify_border_color's own closed value space never actually produces this - a
        # synthetic value exercises the defensive branch directly.
        card = CardFactory(name="Some Card")
        evidence = _evidence(card, layout_class="gold")

        verdict = calculate_layout_class_verdict(card.pk, evidence)

        assert verdict.is_hit is False
        assert verdict.layout_class == "gold"
        assert verdict.tag_name is None


class TestRunLayoutClassCast:
    def test_raises_if_a_tag_is_not_seeded(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, layout_class="borderless")

        try:
            run_layout_class_cast(dry_run=True)
        except RuntimeError as e:
            assert "Borderless" in str(e)
        else:
            raise AssertionError("expected RuntimeError for unseeded tags")

    def test_dry_run_counts_without_writing(self, db):
        _seed_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, layout_class="borderless")

        result = run_layout_class_cast(dry_run=True)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert result.votes_by_class == {"borderless": 1}
        assert CardTagVote.objects.count() == 0
        assert CardScanLog.objects.count() == 0

    def test_write_casts_a_vote_and_never_resolves_alone(self, db):
        _seed_tags()
        tag = Tag.objects.get(name="Borderless")
        card = CardFactory(name="Hidden Courtyard", content_phash=42)
        _evidence(card, layout_class="borderless")

        result = run_layout_class_cast(dry_run=False)

        assert result.votes_written == 1
        vote = CardTagVote.objects.get(card=card)
        assert vote.tag_id == tag.pk
        assert vote.polarity == VotePolarity.APPLY
        assert vote.anonymous_id == LAYOUT_CLASS_CAST_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.confidence == BORDER_ATTRIBUTE_VOTE_CONFIDENCE
        assert vote.run_id == result.run_id

        card.refresh_from_db()
        # a single VoteSource.OCR vote (weight 0.5, no human-backed vote alongside it) can never
        # clear resolve_weighted_consensus's own human-backed gate - exactly UNRESOLVED, asserted
        # against the real enum value rather than a literal string.
        assert card.tag_vote_statuses.get("Borderless") == TagVoteStatus.UNRESOLVED
        assert "Borderless" not in card.tags

        # the same gate-check pattern Stage D uses (local_calculate_verdicts/purge_machine_votes/
        # local_detect_ai_art) - reused directly, not re-derived.
        assert verify_no_machine_only_resolutions([card.pk]) == []

    def test_black_white_silver_each_cast_their_own_tag(self, db):
        _seed_tags()
        cards = {}
        for layout_class in ("black", "white", "silver"):
            card = CardFactory(name=f"{layout_class} card", content_phash=hash(layout_class) % 1000)
            _evidence(card, layout_class=layout_class)
            cards[layout_class] = card

        result = run_layout_class_cast(dry_run=False)

        assert result.votes_written == 3
        for layout_class, card in cards.items():
            # Same table-against-itself caveat as
            # TestCalculateLayoutClassVerdict::test_every_taxonomy_value_routes_through_the_
            # shared_table_and_is_a_hit - what this leg proves is one vote per card carrying the
            # shared table's value end-to-end through the writer, not that the pairing is right.
            # The pairing is pinned in test_local_fallback.py.
            vote = CardTagVote.objects.get(card=card)
            assert vote.tag.name == BORDER_COLOR_TO_TAG[layout_class]

    def test_write_records_a_scan_log_on_ambiguous_and_casts_no_vote(self, db):
        _seed_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, layout_class="")

        result = run_layout_class_cast(dry_run=False)

        assert result.votes_written == 0
        assert CardTagVote.objects.count() == 0
        log = CardScanLog.objects.get(card=card)
        assert log.anonymous_id == LAYOUT_CLASS_CAST_ANONYMOUS_ID
        assert log.skip_reason == "ambiguous"

    def test_idempotent_against_its_own_anonymous_id(self, db):
        _seed_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, layout_class="borderless")

        first = run_layout_class_cast(dry_run=False)
        assert first.votes_written == 1

        second = run_layout_class_cast(dry_run=False)
        assert second.cards_considered == 0
        assert CardTagVote.objects.filter(card=card).count() == 1

    def test_ambiguous_card_is_not_rescanned_on_a_later_run(self, db):
        _seed_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, layout_class="")

        first = run_layout_class_cast(dry_run=False)
        assert first.cards_considered == 1

        second = run_layout_class_cast(dry_run=False)
        assert second.cards_considered == 0
        assert second.skip_counts == {}

    def test_card_without_evidence_is_a_rescannable_no_evidence_skip(self, db):
        _seed_tags()
        CardFactory(name="Some Card", content_phash=42)

        result = run_layout_class_cast(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("no-evidence") == 1
        log = CardScanLog.objects.get(skip_reason="no-evidence")
        assert log.anonymous_id == LAYOUT_CLASS_CAST_ANONYMOUS_ID

        # rescannable: adding evidence and re-running picks the card back up.
        card = log.card
        _evidence(card, layout_class="borderless")

        second = run_layout_class_cast(dry_run=False)
        assert second.cards_considered == 1
        assert second.votes_written == 1

    def test_incomplete_evidence_is_a_rescannable_skip(self, db):
        """A row missing the layout_class extractor key must not be trusted as a genuine
        ambiguous conclusion - it may simply not have run that extractor yet."""
        _seed_tags()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(
            card,
            extractor_versions={"geometry_bleed": "v1"},  # no layout_class yet
            layout_class="",
        )

        result = run_layout_class_cast(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("incomplete-evidence") == 1
        assert CardTagVote.objects.count() == 0

        # rescannable: once the missing extractor completes (same content_hash, evidence row
        # enriched in place), a later run correctly considers the card.
        evidence = card.image_evidence.get()
        evidence.extractor_versions = dict(_COMPLETE_EXTRACTOR_VERSIONS)
        evidence.layout_class = "borderless"
        evidence.save(update_fields=["extractor_versions", "layout_class"])

        second = run_layout_class_cast(dry_run=False)
        assert second.cards_considered == 1
        assert second.votes_written == 1

    def test_card_without_a_stable_content_hash_is_skipped_entirely(self, db):
        _seed_tags()
        CardFactory(name="Some Card", content_phash=None)

        result = run_layout_class_cast(dry_run=False)

        assert result.cards_considered == 0
        assert CardScanLog.objects.count() == 0

    def test_evidence_from_a_stale_content_hash_is_not_used(self, db):
        _seed_tags()
        card = CardFactory(name="Some Card", content_phash=99)
        _evidence(card, content_hash=42, layout_class="borderless")  # stale

        result = run_layout_class_cast(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("no-evidence") == 1
        assert CardTagVote.objects.count() == 0

    def test_multiple_cards_only_confident_readings_are_voted(self, db):
        _seed_tags()
        hit_card = CardFactory(name="Borderless Card", content_phash=1)
        _evidence(hit_card, layout_class="borderless")
        ambiguous_card = CardFactory(name="Ambiguous Card", content_phash=2)
        _evidence(ambiguous_card, layout_class="")

        result = run_layout_class_cast(dry_run=False)

        assert result.votes_written == 1
        assert CardTagVote.objects.filter(card=hit_card).exists()
        assert not CardTagVote.objects.filter(card=ambiguous_card).exists()

    def test_does_not_recast_over_an_existing_local_fallback_border_vote(self, db):
        """This caster mints its own anonymous_id rather than reusing
        local_fallback.FALLBACK_ANONYMOUS_ID (module docstring) - so a card the live pilot's
        fallback engine already cast a border-attribute vote for is NOT excluded by that prior
        vote; this caster independently evaluates and casts its own vote alongside it (two
        distinct identities agreeing is a stronger, not redundant, signal - vote_consensus counts
        distinct anonymous_id/source rows, not just presence of >=1 vote on the tag)."""
        _seed_tags()
        tag = Tag.objects.get(name="Borderless")
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, layout_class="borderless")
        CardTagVote.objects.create(
            card=card,
            tag=tag,
            polarity=VotePolarity.APPLY,
            anonymous_id="local-fallback-v1",
            source=VoteSource.OCR,
            confidence=BORDER_ATTRIBUTE_VOTE_CONFIDENCE,
        )

        result = run_layout_class_cast(dry_run=False)

        assert result.votes_written == 1
        assert CardTagVote.objects.filter(card=card, anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID).count() == 1
        assert CardTagVote.objects.filter(card=card).count() == 2


class TestPurgeWriteAtomicity:
    """Cancel-safety at this module's own vote-write site (2026-07-28, generalising PR #526's fix
    for the Stage D calculators). The purge is a DELETE and the insert a separate statement, so
    before `vote_write.purge_and_write_votes` a run killed between the two left these cards with
    their previous same-family vote deleted and nothing written back. This project's operator
    kills long runs deliberately and a full-catalog pass takes hours, so that is a routine event,
    not a disaster scenario."""

    def test_a_failed_insert_rolls_the_purge_back(self, db, monkeypatch):
        _seed_tags()
        tag = Tag.objects.get(name="Borderless")
        card = CardFactory(name="Hidden Courtyard", content_phash=42)
        _evidence(card, layout_class="borderless")
        # an older version of THIS calculator's own family: purged on write, and the row whose
        # survival is what proves the DELETE was rolled back. A `-v0` row does not make the card
        # ineligible (the eligibility query excludes the exact CURRENT anonymous_id only), so the
        # run genuinely reaches the write.
        stale = CardTagVote.objects.create(
            card=card,
            tag=tag,
            polarity=VotePolarity.APPLY,
            anonymous_id="layout-class-cast-v0",
            source=VoteSource.OCR,
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")

        monkeypatch.setattr(CardTagVote.objects, "bulk_create", _boom)

        with pytest.raises(RuntimeError):
            run_layout_class_cast(dry_run=False)

        assert CardTagVote.objects.filter(pk=stale.pk).exists()


# ---------------------------------------------------------------------------
# Per-batch hot-path contract (issues #458/#460, via #533's first blocking
# prerequisite: anything a per-micro-batch caller invokes must cost O(batch),
# never O(catalog))
# ---------------------------------------------------------------------------


class TestEligibleCardsQuerysetCardIdScoping:
    """`_eligible_cards_queryset`/`run_layout_class_cast` gained a `card_ids` parameter, mirroring
    `local_calculate_verdicts._eligible_cards_queryset`'s issue-#469 fix and
    `local_illustration._eligible_illustration_cards_queryset`'s PR-#526 one. These tests pin BOTH
    halves, because only the first can tell the two apart: that the `CardScanLog` exclusion
    subquery is genuinely narrowed in the COMPILED SQL (a result-set assertion cannot distinguish
    "scoped in SQL" from "materialised catalog-wide and filtered in Python afterwards", which is
    the whole defect class), and that the eligible SET is identical either way."""

    @staticmethod
    def _scan_log_subquery(sql: str) -> str:
        """The `CardScanLog` exclusion subquery, sliced out of the compiled SQL by balanced
        parentheses. `U0` is Django's alias for exactly this subquery (`U1` is the correlated
        `tag_votes` EXISTS), so slicing keeps the assertions below from being satisfied by a
        literal appearing elsewhere in the statement - notably the OUTER `card.id IN (...)`,
        which the scoped and the pre-fix shape carry identically."""
        start = sql.index('(SELECT U0."card_id" FROM "cardpicker_cardscanlog"')
        depth = 0
        for offset, char in enumerate(sql[start:], start=start):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return sql[start : offset + 1]
        raise AssertionError("unbalanced CardScanLog subquery in compiled SQL")

    def test_card_ids_narrows_the_cardscanlog_subquery_itself_not_just_the_outer_query(self, db):
        """The structural proof. Before this parameter existed the only way to scope this
        calculator was to filter the returned queryset, which narrows the outer `Card` query and
        leaves the `CardScanLog` subquery compiling to an unbounded scan of a 2,093,147-row,
        append-only, still-growing table on every 25-card micro-batch."""
        card_a = CardFactory(name="Scope A")
        card_b = CardFactory(name="Scope B")

        scoped_sql = str(_eligible_cards_queryset(card_ids=[card_a.pk, card_b.pk]).query)
        # the pre-fix shape: function unscoped, caller filters afterwards.
        pre_fix_sql = str(_eligible_cards_queryset().filter(pk__in=[card_a.pk, card_b.pk]).query)

        assert f'U0."card_id" IN ({card_a.pk}, {card_b.pk})' in self._scan_log_subquery(scoped_sql)
        assert 'U0."card_id" IN' not in self._scan_log_subquery(pre_fix_sql)
        # both shapes still bound the OUTER query identically - a narrowing of cost, not a change
        # of which cards are considered.
        assert f'"cardpicker_card"."id" IN ({card_a.pk}, {card_b.pk})' in scoped_sql
        assert f'"cardpicker_card"."id" IN ({card_a.pk}, {card_b.pk})' in pre_fix_sql

    def test_card_ids_none_leaves_bulk_mode_untouched(self, db):
        """BULK mode (the management command's only calling shape) must never take the
        `card_id__in` branch - the subquery stays exactly as unscoped as it was before."""
        assert 'U0."card_id" IN' not in self._scan_log_subquery(str(_eligible_cards_queryset().query))

    def test_scoped_and_unscoped_eligible_sets_agree(self, db):
        """Pure cost narrowing, not a behaviour change."""
        excluded_card = CardFactory(name="Excluded Card")
        # any skip reason OUTSIDE LAYOUT_CLASS_RESCANNABLE_SKIP_REASONS permanently excludes it.
        CardScanLog.objects.create(
            card=excluded_card, anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID, skip_reason="ambiguous"
        )
        eligible_card = CardFactory(name="Eligible Card")
        scope = [excluded_card.pk, eligible_card.pk]

        unscoped = set(_eligible_cards_queryset().filter(pk__in=scope).values_list("pk", flat=True))
        scoped = set(_eligible_cards_queryset(card_ids=scope).values_list("pk", flat=True))

        assert unscoped == scoped == {eligible_card.pk}

    def test_a_rescannable_scan_log_row_inside_the_scope_stays_eligible(self, db):
        card = CardFactory(name="Rescannable Card")
        CardScanLog.objects.create(card=card, anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID, skip_reason="no-evidence")

        assert set(_eligible_cards_queryset(card_ids=[card.pk]).values_list("pk", flat=True)) == {card.pk}

    def test_bulk_mode_eligible_set_is_unchanged(self, db):
        """The other half of the contract: `card_ids=None` still selects the whole catalog."""
        card_a = CardFactory(name="Bulk A")
        card_b = CardFactory(name="Bulk B")

        assert set(_eligible_cards_queryset().values_list("pk", flat=True)) == {card_a.pk, card_b.pk}


class TestRunLayoutClassCastCardIdScoping:
    def test_a_scoped_run_only_votes_on_cards_inside_the_scope(self, db):
        _seed_tags()
        in_scope = CardFactory(name="In Scope", content_phash=42)
        _evidence(in_scope, layout_class="borderless")
        out_of_scope = CardFactory(name="Out Of Scope", content_phash=43)
        _evidence(out_of_scope, layout_class="borderless")

        result = run_layout_class_cast(dry_run=False, card_ids=[in_scope.pk])

        assert result.votes_written == 1
        assert list(CardTagVote.objects.values_list("card_id", flat=True)) == [in_scope.pk]

    def test_card_ids_none_still_votes_on_the_whole_catalog(self, db):
        _seed_tags()
        card_a = CardFactory(name="Bulk A", content_phash=42)
        _evidence(card_a, layout_class="borderless")
        card_b = CardFactory(name="Bulk B", content_phash=43)
        _evidence(card_b, layout_class="black")

        result = run_layout_class_cast(dry_run=False)

        assert result.votes_written == 2
        assert set(CardTagVote.objects.values_list("card_id", flat=True)) == {card_a.pk, card_b.pk}
