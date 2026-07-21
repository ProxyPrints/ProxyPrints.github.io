"""
Tests for cardpicker.local_detect_ai_art (public issue #261) - the AI-art marker detector: marker
matching (exact + OCR-tolerant fuzzy substitution), the generator-site-URL exclusion (the owner's
2026-07-21 amendment), the pure per-card calculator, and the batch runner's dry-run/write/
idempotence/rescannability/gate-check behavior. No network calls, no live image fetch - this
module consumes stored `ImageEvidence` rows only, same "host venv, no network" precedent
`test_local_calculate_verdicts.py` already establishes for this pipeline's later stages.
"""

from cardpicker.local_detect_ai_art import (
    AI_ART_ANONYMOUS_ID,
    AI_ART_CONFIDENCE_MULTI_FIELD,
    AI_ART_CONFIDENCE_SINGLE_FIELD,
    AI_GENERATED_TAG_NAME,
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
        assert tag.moderation_class == TagModerationClass.SENSITIVE
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
        # clear resolve_weighted_consensus's own human-backed gate, regardless of moderation_class.
        assert card.tag_vote_statuses.get(AI_GENERATED_TAG_NAME) != "resolved_apply"
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
