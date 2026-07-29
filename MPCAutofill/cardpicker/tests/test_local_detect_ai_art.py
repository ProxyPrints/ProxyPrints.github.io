"""
Tests for cardpicker.local_detect_ai_art (public issue #261) - the AI-art marker detector: marker
matching (exact + OCR-tolerant fuzzy substitution), the generator-site-URL exclusion (the owner's
2026-07-21 amendment), the pure per-card calculator, and the batch runner's dry-run/write/
idempotence/rescannability/gate-check behavior. No network calls, no live image fetch - this
module consumes stored `ImageEvidence` rows only, same "host venv, no network" precedent
`test_local_calculate_verdicts.py` already establishes for this pipeline's later stages.
"""

import pytest

from cardpicker.default_tags import seed_default_tags
from cardpicker.local_detect_ai_art import (
    AI_ART_ANONYMOUS_ID,
    AI_ART_CONFIDENCE_MULTI_FIELD,
    AI_ART_CONFIDENCE_SINGLE_FIELD,
    AI_GENERATED_TAG_NAME,
    _eligible_cards_queryset,
    calculate_ai_art_verdict,
    find_marker_hits,
    normalize_ocr_text,
    run_ai_art_detector,
)
from cardpicker.management.commands.purge_machine_votes import (
    verify_no_machine_only_resolutions,
)
from cardpicker.models import (
    CardScanLog,
    CardTagVote,
    Tag,
    TagModerationClass,
    TagVoteStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.sensitive_tags import seed_sensitive_tags
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

# extractor_versions covering every field this module reads - real evidence rows only get
# considered "complete" once all three have run (see REQUIRED_EXTRACTOR_KEYS).
_COMPLETE_EXTRACTOR_VERSIONS = {
    "collector_line_ocr": "collector-line-ocr-v1",
    "artist_ocr": "artist-ocr-v1",
    "legal_line": "legal-line-v1",
}


def _seed_tag() -> Tag:
    # AI-Generated is plain STANDARD (owner decision, 2026-07-21) - seeded via
    # cardpicker.default_tags (its DEFAULT_TAGS entry, the filename-bracket-tagging path), not
    # cardpicker.sensitive_tags. seed_sensitive_tags() is still called here too so this fixture
    # also exercises FORMERLY_SENSITIVE_TAG_NAMES' downgrade-sync no-op path on a fresh/never-
    # sensitive row (it's a harmless no-op either way, and matches real seeding order in
    # management commands, which run both).
    seed_default_tags()
    seed_sensitive_tags()
    return Tag.objects.get(name=AI_GENERATED_TAG_NAME)


def _evidence(card, **overrides):
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(_COMPLETE_EXTRACTOR_VERSIONS),
        artist_ocr_name="",
        legal_line_raw_text="",
        collector_line_raw_text="",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestNormalizeOcrText:
    def test_lowercases_and_strips_punctuation_and_whitespace(self):
        assert normalize_ocr_text("Mid-Journey!! v6") == "midjourneyv6"

    def test_empty_string(self):
        assert normalize_ocr_text("") == ""


class TestFindMarkerHits:
    # Real, observed-in-production OCR strings (tonight's run samples, per the task spec) -
    # both contain "midjourney" as an exact substring once normalized, no fuzzy tolerance needed.
    def test_real_sample_not_for_resale_trademark_line(self):
        hits = find_marker_hits("2024pnotforresaletrademtgenmidjourney")
        assert hits == ["Midjourney"]

    def test_real_sample_curated_by_credit_line(self):
        hits = find_marker_hits("alartmidjourneycuratedbydeathsushi")
        assert hits == ["Midjourney"]

    def test_clean_exact_marker(self):
        assert find_marker_hits("Illus. Stable Diffusion") == ["Stable Diffusion"]

    def test_multiple_distinct_markers_in_one_field(self):
        hits = find_marker_hits("made with midjourney and dall-e")
        assert set(hits) == {"Midjourney", "DALL-E"}

    def test_no_hit_on_ordinary_text(self):
        assert find_marker_hits("Illus. Rebecca Guay") == []

    def test_empty_text(self):
        assert find_marker_hits("") == []

    # OCR-tolerant fuzzy matching: single-character substitution on a marker >= 8 chars.
    def test_fuzzy_match_tolerates_one_substitution_on_long_marker(self):
        # "midj0urney" - a single 'o' -> '0' OCR misread of "midjourney" (10 chars, >= the
        # fuzzy floor).
        hits = find_marker_hits("trademtgenmidj0urney")
        assert hits == ["Midjourney"]

    def test_fuzzy_match_does_not_tolerate_two_substitutions(self):
        # documented limitation: only a SINGLE substitution is tolerated - two independent
        # misreads on the same marker window must not match, or the false-positive risk this
        # feature has to guard hardest against (mistagging a human artist) grows unbounded.
        hits = find_marker_hits("trademtgenmidj0urn3y")
        assert hits == []

    def test_short_marker_gets_no_fuzzy_tolerance(self):
        # "Gemini" (6 chars) is below FUZZY_MIN_MARKER_LENGTH (8) - a single-substitution mangle
        # must NOT match, since a short marker tolerating fuzz risks matching incidental text.
        hits = find_marker_hits("gem1ni")
        assert hits == []

    # OWNER AMENDMENT: generator-site URLs are excluded from the marker list entirely - a
    # CardConjurer credit/watermark must never be flagged as AI provenance.
    def test_cardconjurer_url_does_not_match(self):
        assert find_marker_hits("Rendered with CardConjurer.com") == []
        assert find_marker_hits("cardconjurer.com") == []
        assert find_marker_hits("www.cardconjurer.com/render") == []

    # Coverage proofs (2026-07-22 marker-list expansion): spacing/punctuation variants of existing
    # and newly-added markers must still hit via normalize_ocr_text, exactly like the "Mid-Journey"
    # example in TestNormalizeOcrText above.
    @pytest.mark.parametrize(
        ("text", "expected_marker"),
        [
            ("art made with Mid Journey", "Midjourney"),
            ("Illus. DALL·E 3", "DALL-E"),
            ("generated by Chat GPT", "ChatGPT"),
            ("credit: Niji-Journey", "Niji Journey"),
            ("rendered via stable-diffusion", "Stable Diffusion"),
        ],
    )
    def test_spacing_and_punctuation_variants_hit_via_normalization(self, text, expected_marker):
        assert expected_marker in find_marker_hits(text)

    # New-marker hits (2026-07-22 marker-list expansion) - one neutral fixture per new marker.
    # Deliberately no franchise/IP names in fixture text, even ones observed verbatim in real OCR
    # data (module docstring's own "never re-derive from source" discipline extended to fixtures:
    # a neutral fixture proves the marker works without laundering real observed evidence text into
    # the test suite).
    @pytest.mark.parametrize(
        ("text", "expected_marker"),
        [
            ("art by ChatGPT", "ChatGPT"),
            ("made using Playground AI", "Playground AI"),
            ("credit: Niji Journey", "Niji Journey"),
            ("art by Doubao", "Doubao"),
            ("generated with Jimeng", "Jimeng"),
            ("made with Dreamina", "Dreamina"),
            ("rendered by Seedream", "Seedream"),
            ("art by Kling", "Kling"),
            ("generated via Kolors", "Kolors"),
            ("made with Hunyuan", "Hunyuan"),
            ("credit Tongyi Wanxiang", "Tongyi Wanxiang"),
            ("credit Wanxiang", "Wanxiang"),
            ("generated by ERNIE-ViLG", "ERNIE-ViLG"),
            ("made with Wenxin Yige", "Wenxin Yige"),
            ("art by Hailuo", "Hailuo"),
            ("rendered by CogView", "CogView"),
            ("made with LiblibAI", "LiblibAI"),
            ("edited in Meitu", "Meitu"),
            ("generated by Wujie AI", "Wujie AI"),
            ("art by Qwen", "Qwen"),
            ("made with Recraft", "Recraft"),
            ("generated via Ideogram", "Ideogram"),
            ("made with Grok Imagine", "Grok Imagine"),
            ("rendered by Flux.1", "Flux.1"),
        ],
    )
    def test_new_marker_hits(self, text, expected_marker):
        assert expected_marker in find_marker_hits(text)

    # False-positive guards (2026-07-22 marker-list expansion) - the exact collision cases the
    # EXPLICIT EXCLUSIONS comment on AI_GENERATOR_MARKERS documents must never fire.
    @pytest.mark.parametrize(
        "text",
        [
            "Ai Desheng",
            "Sora Nakamura",
            "flux capacitor art",
            "Ernie Barnes",
        ],
    )
    def test_explicit_exclusions_do_not_match(self, text):
        assert find_marker_hits(text) == []


class TestCalculateAiArtVerdict:
    def test_no_hit_returns_empty_verdict(self, db):
        card = CardFactory(name="Some Card")
        evidence = _evidence(card, artist_ocr_name="Rebecca Guay")

        verdict = calculate_ai_art_verdict(card.pk, evidence)

        assert verdict.is_hit is False
        assert verdict.matched_markers == {}
        assert verdict.confidence is None

    def test_single_field_hit_gets_single_field_confidence(self, db):
        card = CardFactory(name="Some Card")
        evidence = _evidence(card, legal_line_raw_text="2024 not for resale trademtgen midjourney")

        verdict = calculate_ai_art_verdict(card.pk, evidence)

        assert verdict.is_hit is True
        assert verdict.matched_markers == {"legal_line_raw_text": ["Midjourney"]}
        assert verdict.confidence == AI_ART_CONFIDENCE_SINGLE_FIELD

    def test_multi_field_hit_gets_multi_field_confidence(self, db):
        card = CardFactory(name="Some Card")
        evidence = _evidence(
            card,
            artist_ocr_name="Midjourney",
            legal_line_raw_text="not for resale midjourney",
        )

        verdict = calculate_ai_art_verdict(card.pk, evidence)

        assert verdict.is_hit is True
        assert set(verdict.matched_markers.keys()) == {"artist_ocr_name", "legal_line_raw_text"}
        assert verdict.confidence == AI_ART_CONFIDENCE_MULTI_FIELD

    def test_cardconjurer_credit_line_is_not_a_hit(self, db):
        card = CardFactory(name="Some Card")
        evidence = _evidence(card, legal_line_raw_text="made with cardconjurer.com")

        verdict = calculate_ai_art_verdict(card.pk, evidence)

        assert verdict.is_hit is False


class TestRunAiArtDetector:
    def test_raises_if_tag_not_seeded(self, db):
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, legal_line_raw_text="midjourney")

        try:
            run_ai_art_detector(dry_run=True)
        except RuntimeError as e:
            assert "AI-Generated" in str(e)
        else:
            raise AssertionError("expected RuntimeError for an unseeded tag")

    def test_dry_run_counts_without_writing(self, db):
        _seed_tag()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, legal_line_raw_text="2024 not for resale trademtgen midjourney")

        result = run_ai_art_detector(dry_run=True)

        assert result.cards_considered == 1
        assert result.votes_would_cast == 1
        assert CardTagVote.objects.count() == 0
        assert CardScanLog.objects.count() == 0

    def test_write_casts_a_vote_and_never_resolves_alone(self, db):
        tag = _seed_tag()
        # owner decision 2026-07-21: AI-Generated is plain STANDARD, not SENSITIVE - ordinary
        # crowd consensus is fine for this tag; see sensitive_tags.py's SENSITIVE_TAGS comment.
        assert tag.moderation_class == TagModerationClass.STANDARD
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, legal_line_raw_text="2024 not for resale trademtgen midjourney")

        result = run_ai_art_detector(dry_run=False)

        assert result.votes_written == 1
        vote = CardTagVote.objects.get(card=card)
        assert vote.tag_id == tag.pk
        assert vote.polarity == VotePolarity.APPLY
        assert vote.anonymous_id == AI_ART_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.run_id == result.run_id

        card.refresh_from_db()
        # a single VoteSource.OCR vote (weight 0.5, no human-backed vote alongside it) can never
        # clear resolve_weighted_consensus's own human-backed gate, regardless of moderation_class -
        # exactly UNRESOLVED (not CONTESTED/PENDING_APPROVAL/RESOLVED_*), asserted against the real
        # enum value rather than a literal string.
        assert card.tag_vote_statuses.get(AI_GENERATED_TAG_NAME) == TagVoteStatus.UNRESOLVED
        assert AI_GENERATED_TAG_NAME not in card.tags

        # the same gate-check pattern Stage D uses (local_calculate_verdicts/purge_machine_votes) -
        # reused directly, not re-derived.
        assert verify_no_machine_only_resolutions([card.pk]) == []

    def test_write_records_a_scan_log_on_no_hit_and_casts_no_vote(self, db):
        _seed_tag()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, artist_ocr_name="Rebecca Guay")

        result = run_ai_art_detector(dry_run=False)

        assert result.votes_written == 0
        assert CardTagVote.objects.count() == 0
        log = CardScanLog.objects.get(card=card)
        assert log.anonymous_id == AI_ART_ANONYMOUS_ID
        assert log.skip_reason == "no-marker-hit"

    def test_idempotent_against_its_own_anonymous_id(self, db):
        _seed_tag()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, legal_line_raw_text="midjourney")

        first = run_ai_art_detector(dry_run=False)
        assert first.votes_written == 1

        second = run_ai_art_detector(dry_run=False)
        assert second.cards_considered == 0
        assert CardTagVote.objects.filter(card=card).count() == 1

    def test_no_hit_card_is_not_rescanned_on_a_later_run(self, db):
        _seed_tag()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, artist_ocr_name="Rebecca Guay")

        first = run_ai_art_detector(dry_run=False)
        assert first.cards_considered == 1

        second = run_ai_art_detector(dry_run=False)
        assert second.cards_considered == 0
        assert second.skip_counts == {}

    def test_card_without_evidence_is_a_rescannable_no_evidence_skip(self, db):
        _seed_tag()
        CardFactory(name="Some Card", content_phash=42)

        result = run_ai_art_detector(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("no-evidence") == 1
        log = CardScanLog.objects.get(skip_reason="no-evidence")
        assert log.anonymous_id == AI_ART_ANONYMOUS_ID

        # rescannable: adding evidence and re-running picks the card back up.
        card = log.card
        _evidence(card, legal_line_raw_text="midjourney")

        second = run_ai_art_detector(dry_run=False)
        assert second.cards_considered == 1
        assert second.votes_written == 1

    def test_incomplete_evidence_is_a_rescannable_skip(self, db):
        """A row missing one of REQUIRED_EXTRACTOR_KEYS (e.g. legal_line hasn't run yet) must
        not be trusted as a genuine no-hit - it may simply not have looked at that field yet."""
        _seed_tag()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(
            card,
            extractor_versions={"collector_line_ocr": "v1", "artist_ocr": "v1"},  # no legal_line yet
            legal_line_raw_text="",
        )

        result = run_ai_art_detector(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("incomplete-evidence") == 1
        assert CardTagVote.objects.count() == 0

        # rescannable: once the missing extractor completes (same content_hash, evidence row
        # enriched in place), a later run correctly considers the card.
        evidence = card.image_evidence.get()
        evidence.extractor_versions = dict(_COMPLETE_EXTRACTOR_VERSIONS)
        evidence.legal_line_raw_text = "midjourney"
        evidence.save(update_fields=["extractor_versions", "legal_line_raw_text"])

        second = run_ai_art_detector(dry_run=False)
        assert second.cards_considered == 1
        assert second.votes_written == 1

    def test_card_without_a_stable_content_hash_is_skipped_entirely(self, db):
        _seed_tag()
        CardFactory(name="Some Card", content_phash=None)

        result = run_ai_art_detector(dry_run=False)

        assert result.cards_considered == 0
        assert CardScanLog.objects.count() == 0

    def test_evidence_from_a_stale_content_hash_is_not_used(self, db):
        _seed_tag()
        card = CardFactory(name="Some Card", content_phash=99)
        _evidence(card, content_hash=42, legal_line_raw_text="midjourney")  # stale

        result = run_ai_art_detector(dry_run=False)

        assert result.cards_considered == 0
        assert result.skip_counts.get("no-evidence") == 1
        assert CardTagVote.objects.count() == 0

    def test_multiple_cards_only_hits_are_voted(self, db):
        _seed_tag()
        hit_card = CardFactory(name="AI Card", content_phash=1)
        _evidence(hit_card, artist_ocr_name="midjourney")
        clean_card = CardFactory(name="Human Card", content_phash=2)
        _evidence(clean_card, artist_ocr_name="Rebecca Guay")

        result = run_ai_art_detector(dry_run=False)

        assert result.votes_written == 1
        assert CardTagVote.objects.filter(card=hit_card).exists()
        assert not CardTagVote.objects.filter(card=clean_card).exists()


class TestPurgeWriteAtomicity:
    """Cancel-safety at this module's own vote-write site (2026-07-28, generalising PR #526's fix
    for the Stage D calculators): the purge and the insert are now one `transaction.atomic()`
    pair, so a run killed between them no longer leaves these cards with their previous
    same-family vote deleted and nothing written in its place."""

    def test_a_failed_insert_rolls_the_purge_back(self, db, monkeypatch):
        tag = _seed_tag()
        card = CardFactory(name="Some Card", content_phash=42)
        _evidence(card, legal_line_raw_text="2024 not for resale trademtgen midjourney")
        # an older version of THIS detector's own family - purged on write, and the row whose
        # survival proves the DELETE was rolled back. `-v0` is not the current anonymous_id, so
        # the eligibility query still selects the card and the run reaches the write.
        stale = CardTagVote.objects.create(
            card=card,
            tag=tag,
            polarity=VotePolarity.APPLY,
            anonymous_id="ai-art-detector-v0",
            source=VoteSource.OCR,
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")

        monkeypatch.setattr(CardTagVote.objects, "bulk_create", _boom)

        with pytest.raises(RuntimeError):
            run_ai_art_detector(dry_run=False)

        assert CardTagVote.objects.filter(pk=stale.pk).exists()


# ---------------------------------------------------------------------------
# Per-batch hot-path contract (issues #458/#460, via #533's first blocking
# prerequisite: anything a per-micro-batch caller invokes must cost O(batch),
# never O(catalog))
# ---------------------------------------------------------------------------

_MARKER_TEXT = "2024 not for resale trademtgen midjourney"


class TestEligibleCardsQuerysetCardIdScoping:
    """`_eligible_cards_queryset`/`run_ai_art_detector` gained a `card_ids` parameter, mirroring
    `local_calculate_verdicts._eligible_cards_queryset`'s issue-#469 fix and
    `local_illustration._eligible_illustration_cards_queryset`'s PR-#526 one. Both halves are
    pinned, because only the first can tell them apart: that the `CardScanLog` exclusion subquery
    is genuinely narrowed in the COMPILED SQL (result-set equivalence cannot distinguish "scoped
    in SQL" from "materialised catalog-wide and filtered in Python afterwards"), and that the
    eligible SET is identical either way."""

    @staticmethod
    def _scan_log_subquery(sql: str) -> str:
        """The `CardScanLog` exclusion subquery, sliced out of the compiled SQL by balanced
        parentheses. `U0` is Django's alias for exactly this subquery (`U1` is the correlated
        `tag_votes` EXISTS pair), so slicing keeps the assertions below from being satisfied by a
        literal appearing elsewhere - notably the OUTER `card.id IN (...)`, which the scoped and
        the pre-fix shape carry identically."""
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
        tag = _seed_tag()
        card_a = CardFactory(name="Scope A")
        card_b = CardFactory(name="Scope B")

        scoped_sql = str(_eligible_cards_queryset(tag, card_ids=[card_a.pk, card_b.pk]).query)
        # the pre-fix shape: function unscoped, caller filters afterwards.
        pre_fix_sql = str(_eligible_cards_queryset(tag).filter(pk__in=[card_a.pk, card_b.pk]).query)

        assert f'U0."card_id" IN ({card_a.pk}, {card_b.pk})' in self._scan_log_subquery(scoped_sql)
        assert 'U0."card_id" IN' not in self._scan_log_subquery(pre_fix_sql)
        assert f'"cardpicker_card"."id" IN ({card_a.pk}, {card_b.pk})' in scoped_sql
        assert f'"cardpicker_card"."id" IN ({card_a.pk}, {card_b.pk})' in pre_fix_sql

    def test_card_ids_none_leaves_bulk_mode_untouched(self, db):
        """BULK mode (the management command's only calling shape) must never take the
        `card_id__in` branch."""
        tag = _seed_tag()

        assert 'U0."card_id" IN' not in self._scan_log_subquery(str(_eligible_cards_queryset(tag).query))

    def test_scoped_and_unscoped_eligible_sets_agree(self, db):
        """Pure cost narrowing, not a behaviour change."""
        tag = _seed_tag()
        excluded_card = CardFactory(name="Excluded Card")
        # any skip reason OUTSIDE AI_ART_RESCANNABLE_SKIP_REASONS permanently excludes it.
        CardScanLog.objects.create(card=excluded_card, anonymous_id=AI_ART_ANONYMOUS_ID, skip_reason="no-marker-hit")
        eligible_card = CardFactory(name="Eligible Card")
        scope = [excluded_card.pk, eligible_card.pk]

        unscoped = set(_eligible_cards_queryset(tag).filter(pk__in=scope).values_list("pk", flat=True))
        scoped = set(_eligible_cards_queryset(tag, card_ids=scope).values_list("pk", flat=True))

        assert unscoped == scoped == {eligible_card.pk}

    def test_a_rescannable_scan_log_row_inside_the_scope_stays_eligible(self, db):
        tag = _seed_tag()
        card = CardFactory(name="Rescannable Card")
        CardScanLog.objects.create(card=card, anonymous_id=AI_ART_ANONYMOUS_ID, skip_reason="no-evidence")

        assert set(_eligible_cards_queryset(tag, card_ids=[card.pk]).values_list("pk", flat=True)) == {card.pk}

    def test_bulk_mode_eligible_set_is_unchanged(self, db):
        tag = _seed_tag()
        card_a = CardFactory(name="Bulk A")
        card_b = CardFactory(name="Bulk B")

        assert set(_eligible_cards_queryset(tag).values_list("pk", flat=True)) == {card_a.pk, card_b.pk}


class TestRunAiArtDetectorCardIdScoping:
    def test_a_scoped_run_only_votes_on_cards_inside_the_scope(self, db):
        _seed_tag()
        in_scope = CardFactory(name="In Scope", content_phash=42)
        _evidence(in_scope, legal_line_raw_text=_MARKER_TEXT)
        # deliberately marker-FREE: unscoped, this card would have earned a "no-marker-hit"
        # CardScanLog row, so the scan-log assertion below is a real one rather than vacuous.
        out_of_scope = CardFactory(name="Out Of Scope", content_phash=43)
        _evidence(out_of_scope, artist_ocr_name="Rebecca Guay")

        result = run_ai_art_detector(dry_run=False, card_ids=[in_scope.pk])

        assert result.votes_written == 1
        assert list(CardTagVote.objects.values_list("card_id", flat=True)) == [in_scope.pk]
        # the out-of-scope card is untouched in every table, not merely unvoted.
        assert not CardScanLog.objects.filter(card_id=out_of_scope.pk).exists()

    def test_card_ids_none_still_votes_on_the_whole_catalog(self, db):
        _seed_tag()
        card_a = CardFactory(name="Bulk A", content_phash=42)
        _evidence(card_a, legal_line_raw_text=_MARKER_TEXT)
        card_b = CardFactory(name="Bulk B", content_phash=43)
        _evidence(card_b, legal_line_raw_text=_MARKER_TEXT)

        result = run_ai_art_detector(dry_run=False)

        assert result.votes_written == 2
        assert set(CardTagVote.objects.values_list("card_id", flat=True)) == {card_a.pk, card_b.pk}
