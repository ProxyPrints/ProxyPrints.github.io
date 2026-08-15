"""
Tests for `cardpicker.local_attribute_chip_cast` - the evidence-reading caster for the FRAME-STYLE
(`Old Border`/`Modern Border`) attribute chip, plus the proof that it is reachable from the
conveyor. The BLEED-EDGE half this module used to cast is RETIRED (identity `bleed-edge-cast-v1`,
superseded by `bleed-calculator-cast-v1` in `local_bleed_calculator`, the sole machine channel for
`appropriate-bleed`) - so a load-bearing property here is that the retired identity never casts,
while the frame chip keeps casting exactly as before.

WHAT THESE GUARD. The 2026-07-29 composition audit measured the frame chip at ZERO machine rows
with no substitute: the only code that ever cast it lived in `local_identify_printing_tags.
run_pilot` (a live-FETCH pilot, one completed run ever) and in `image_evidence.
extract_card_evidence`, which had zero production callers. So the properties worth pinning are
(a) the chip is derivable from stored evidence, (b) nothing here fetches, (c) the caster is
actually WIRED into an engine, (d) the frame chip gates on `artist_ocr` rather than reading a
missing `illus_anchor_fired` as a real `False`, and (e) the retired bleed identity no longer casts
while frame-style casting continues.

No network calls, no live image fetch - same "host venv, no network" precedent
`test_local_layout_class_cast.py`/`test_local_detect_ai_art.py` already establish.
"""

from typing import Any

import pytest

from cardpicker.attribute_tags import seed_attribute_tags
from cardpicker.default_tags import seed_default_tags
from cardpicker.local_attribute_chip_cast import (
    BLEED_EDGE_CAST_ANONYMOUS_ID,
    CHIP_ABSTAINED_SKIP_REASON,
    CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON,
    CHIP_NO_EVIDENCE_SKIP_REASON,
    FRAME_STYLE_CAST_ANONYMOUS_ID,
    calculate_attribute_chip_verdict,
    run_attribute_chip_cast,
)
from cardpicker.local_bleed_calculator import BLEED_CALCULATOR_CAST_ANONYMOUS_ID
from cardpicker.local_fallback import FRAME_STYLE_TO_TAG, FRAME_VOTE_CONFIDENCE
from cardpicker.models import CardScanLog, CardTagVote, VotePolarity, VoteSource
from cardpicker.sensitive_tags import seed_sensitive_tags
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

_COMPLETE_EXTRACTOR_VERSIONS = {
    "collector_line_ocr": "collector-line-ocr-v2",
    "artist_ocr": "artist-ocr-v3",
    "geometry_bleed": "geometry-bleed-v1",
}


def _seed_tags() -> None:
    seed_default_tags()
    seed_attribute_tags()  # Old Border / Modern Border
    seed_sensitive_tags()  # appropriate-bleed


def _evidence(card: Any, **overrides: Any) -> Any:
    defaults: dict[str, Any] = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(_COMPLETE_EXTRACTOR_VERSIONS),
        collector_line_collector_number="",
        illus_anchor_fired=False,
        bleed_class="bleed",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestCalculateAttributeChipVerdict:
    def test_a_parsed_collector_number_reads_modern(self, db):
        """The 133,627-row population: `.exclude(collector_line_collector_number="")`."""
        card = CardFactory(content_phash=1)
        verdict = calculate_attribute_chip_verdict(card.pk, _evidence(card, collector_line_collector_number="123"))

        assert verdict.frame_class == "modern"
        assert verdict.frame_tag_name == FRAME_STYLE_TO_TAG["modern"]

    def test_no_collector_number_but_a_fired_illus_anchor_reads_old(self, db):
        """The 9,006-row population - the retro frame prints no collector line at all, just a
        centred artist credit, so the `Illus.` anchor firing IS the old-frame signal."""
        card = CardFactory(content_phash=1)
        verdict = calculate_attribute_chip_verdict(card.pk, _evidence(card, illus_anchor_fired=True))

        assert verdict.frame_class == "old"
        assert verdict.frame_tag_name == FRAME_STYLE_TO_TAG["old"]

    def test_neither_signal_abstains_rather_than_guessing_modern(self, db):
        """The 77,946-row abstain population. This is the one that must NOT default to `modern`."""
        card = CardFactory(content_phash=1)
        verdict = calculate_attribute_chip_verdict(card.pk, _evidence(card))

        assert verdict.frame_class is None
        assert verdict.frame_tag_name is None
        assert verdict.frame_skip_reason == CHIP_ABSTAINED_SKIP_REASON

    def test_a_missing_artist_ocr_extractor_skips_the_frame_chip_rather_than_reading_false(self, db):
        """THE BUG CLASS THIS MODULE EXISTS NOT TO REPEAT (audit §5, the `artist_ocr` ->
        frame-veto row). `illus_anchor_fired` is nullable, and `bool(None)` is `False`, which is
        indistinguishable from "the extractor ran and found no anchor". Without the
        `FRAME_REQUIRED_EXTRACTOR_KEYS` gate this card would read `modern` - a manufactured vote
        from evidence that does not exist. It must be an `incomplete-evidence` skip instead.

        The fixture is deliberately the OLD-frame shape (no collector number, anchor unknown): a
        card that would be right about `modern` regardless proves nothing here."""
        card = CardFactory(content_phash=1)
        versions = dict(_COMPLETE_EXTRACTOR_VERSIONS)
        del versions["artist_ocr"]
        verdict = calculate_attribute_chip_verdict(
            card.pk, _evidence(card, extractor_versions=versions, illus_anchor_fired=None)
        )

        assert verdict.frame_class is None
        assert verdict.frame_tag_name is None
        assert verdict.frame_skip_reason == CHIP_INCOMPLETE_EVIDENCE_SKIP_REASON

    def test_a_missing_geometry_bleed_extractor_leaves_the_frame_chip_unaffected(self, db):
        """The two families USED to gate independently - a card missing one extractor still got
        the other family's chip. The bleed half is retired now, so this pins the surviving half:
        missing `geometry_bleed` must not disturb the frame reading."""
        card = CardFactory(content_phash=1)
        versions = dict(_COMPLETE_EXTRACTOR_VERSIONS)
        del versions["geometry_bleed"]
        verdict = calculate_attribute_chip_verdict(
            card.pk, _evidence(card, extractor_versions=versions, collector_line_collector_number="123")
        )

        assert verdict.frame_tag_name == FRAME_STYLE_TO_TAG["modern"]

    @pytest.mark.parametrize("bleed_class", ["bleed", "trimmed", ""])
    def test_bleed_class_is_irrelevant_to_the_frame_verdict(self, db, bleed_class):
        """The verdict no longer carries a bleed dimension at all - the retired bleed half cast
        on `bleed_class == "trimmed"` alone, and `bleed-calculator-cast-v1` owns that decision
        now. Whatever the reading, the frame chip must produce the identical frame verdict."""
        card = CardFactory(content_phash=1)
        verdict = calculate_attribute_chip_verdict(
            card.pk, _evidence(card, collector_line_collector_number="123", bleed_class=bleed_class)
        )

        assert verdict.frame_class == "modern"
        assert verdict.frame_tag_name == FRAME_STYLE_TO_TAG["modern"]
        assert not hasattr(verdict, "bleed_tag_name")


class TestRunAttributeChipCast:
    def test_a_write_run_casts_frame_style_only_and_never_the_retired_bleed_identity(self, db):
        """THE RETIREMENT, END TO END. The frame chip votes with its shared confidence and
        polarity; the retired `bleed-edge-cast-v1` identity writes NOTHING - not even on a
        `trimmed` card, which is exactly the reading its old single-signal logic used to vote on
        (that decision now belongs to `bleed-calculator-cast-v1` alone)."""
        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, collector_line_collector_number="123", bleed_class="trimmed")

        result = run_attribute_chip_cast(run_id="r1", dry_run=False)

        assert result.frame_votes_written == 1
        assert result.votes_written == 1  # the frame vote is the ONLY vote the caster can produce now
        frame_vote = CardTagVote.objects.get(anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID)
        assert frame_vote.tag.name == FRAME_STYLE_TO_TAG["modern"]
        assert frame_vote.polarity == VotePolarity.APPLY
        assert frame_vote.confidence == FRAME_VOTE_CONFIDENCE
        assert frame_vote.source == VoteSource.OCR
        assert frame_vote.run_id == "r1"
        assert CardTagVote.objects.filter(anonymous_id=BLEED_EDGE_CAST_ANONYMOUS_ID).count() == 0
        assert CardScanLog.objects.filter(anonymous_id=BLEED_EDGE_CAST_ANONYMOUS_ID).count() == 0

    def test_a_dry_run_writes_nothing_at_all(self, db):
        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, collector_line_collector_number="123", bleed_class="trimmed")

        result = run_attribute_chip_cast(run_id="r1", dry_run=True)

        assert result.votes_would_cast == 1
        assert CardTagVote.objects.count() == 0
        assert CardScanLog.objects.count() == 0

    def test_the_retired_bleed_identity_is_not_resurrected_by_a_later_pass(self, db):
        """The old bleed logic's re-selection contract (a frame vote must never strand the bleed
        chip) is now satisfied structurally: the bleed calculator owns its own identity. What this
        module must guarantee instead is that the retired identity stays dead across passes - a
        card re-presented as `trimmed` on a SECOND run still gets no `bleed-edge-cast-v1` vote
        (nor scan-log row), while the frame chip keeps its own re-selection semantics."""
        _seed_tags()
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, collector_line_collector_number="123", bleed_class="bleed")
        run_attribute_chip_cast(run_id="r1", dry_run=False)
        assert CardTagVote.objects.filter(anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID).count() == 1
        assert CardTagVote.objects.filter(anonymous_id=BLEED_EDGE_CAST_ANONYMOUS_ID).count() == 0

        evidence.bleed_class = "trimmed"
        evidence.save()
        # `ambiguous` is deliberately NOT rescannable, so the abstention row must be cleared for
        # the card to be reconsidered - the same re-selection contract every other caster has.
        CardScanLog.objects.filter(anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID).delete()
        run_attribute_chip_cast(run_id="r2", dry_run=False)

        assert CardTagVote.objects.filter(anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID).count() == 1
        assert CardTagVote.objects.filter(anonymous_id=BLEED_EDGE_CAST_ANONYMOUS_ID).count() == 0
        assert CardScanLog.objects.filter(anonymous_id=BLEED_EDGE_CAST_ANONYMOUS_ID).count() == 0

    def test_a_second_run_is_idempotent(self, db):
        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, collector_line_collector_number="123", bleed_class="trimmed")

        run_attribute_chip_cast(run_id="r1", dry_run=False)
        second = run_attribute_chip_cast(run_id="r2", dry_run=False)

        assert second.votes_written == 0
        assert CardTagVote.objects.count() == 1

    def test_a_card_with_no_current_evidence_is_a_named_skip_not_a_crash(self, db):
        """A stale evidence row (content_hash != the card's live content_phash) is not consulted -
        `current_evidence_queryset`'s shared staleness rule - and produces `no-evidence`, which IS
        rescannable, so the card returns to the pool once Stage C re-extracts it. One identity is
        skipped now (the retired bleed identity never enters the pool)."""
        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, content_hash=999, collector_line_collector_number="123")

        result = run_attribute_chip_cast(run_id="r1", dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts[CHIP_NO_EVIDENCE_SKIP_REASON] == 1
        assert set(
            CardScanLog.objects.filter(skip_reason=CHIP_NO_EVIDENCE_SKIP_REASON).values_list("anonymous_id", flat=True)
        ) == {FRAME_STYLE_CAST_ANONYMOUS_ID}

    def test_card_ids_scoping_narrows_the_pass(self, db):
        _seed_tags()
        wanted = CardFactory(content_phash=1)
        other = CardFactory(content_phash=2)
        _evidence(wanted, collector_line_collector_number="123")
        _evidence(other, collector_line_collector_number="456")

        run_attribute_chip_cast(run_id="r1", dry_run=False, card_ids=[wanted.pk])

        assert list(CardTagVote.objects.values_list("card_id", flat=True)) == [wanted.pk]

    def test_no_vote_ever_resolves_a_tag_on_its_own(self, db):
        """The human-backed gate (`vote_consensus.resolve_weighted_consensus`), checked
        empirically rather than argued - the same verification the management command layers on."""
        from cardpicker.management.commands.purge_machine_votes import (
            verify_no_machine_only_resolutions,
        )

        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, collector_line_collector_number="123", bleed_class="trimmed")

        run_attribute_chip_cast(run_id="r1", dry_run=False)

        assert verify_no_machine_only_resolutions([card.pk]) == []

    def test_the_caster_never_fetches_an_image(self, db, monkeypatch):
        """ZERO IMAGE FETCHES - the whole reason this module exists rather than re-running the
        pilot, which would have meant re-fetching ~220,000 images to recompute facts already in
        storage. Booby-traps the fetch entry points rather than asserting on a counter."""
        import cardpicker.image_cdn_fetch as image_cdn_fetch

        def _explode(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the attribute-chip caster must never fetch an image")

        monkeypatch.setattr(image_cdn_fetch, "fetch_card_image", _explode)
        monkeypatch.setattr(image_cdn_fetch, "fetch_card_image_bytes", _explode)

        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, collector_line_collector_number="123", bleed_class="trimmed")

        assert run_attribute_chip_cast(run_id="r1", dry_run=False).votes_written == 1


class TestConveyorWiring:
    """THE POINT OF THE WHOLE PR. Both chip casters were reachable from NEITHER engine - the audit's
    §2a table has `POOLED=N, CONVEYOR=N` for channels 9, 10, 11 and 12. These prove the conveyor now
    reaches them, which no assertion about the calculator in isolation can."""

    def test_run_stage_d_casts_frame_chip_and_bleed_calculator(self, db):
        """THE REPLACEMENT, THROUGH THE CONVEYOR. The frame chip and the bleed calculator both
        vote on one card in a single dispatch, the retired `bleed-edge-cast-v1` identity writes
        nothing, and the old chip counter is GONE from the outcome (one channel per tag)."""
        from cardpicker.stage_e_dispatch import DispatchOutcome, _run_stage_d

        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(
            card,
            collector_line_collector_number="123",
            bleed_class="trimmed",
            bleed_diff_mm=0.5,  # Method A's stored input - gives the calculator a reading to vote from
        )

        outcome = DispatchOutcome(status="dispatched")
        _run_stage_d([card.pk], run_id="r1", outcome=outcome)

        assert outcome.stage_d_frame_chip_votes == 1
        assert outcome.stage_d_bleed_calculator_votes == 1
        assert not hasattr(outcome, "stage_d_bleed_chip_votes")
        assert CardTagVote.objects.filter(anonymous_id=FRAME_STYLE_CAST_ANONYMOUS_ID).count() == 1
        assert CardTagVote.objects.filter(anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID).count() == 1
        assert CardTagVote.objects.filter(anonymous_id=BLEED_EDGE_CAST_ANONYMOUS_ID).count() == 0

    def test_run_stage_d_casts_the_border_chip_too(self, db):
        """Border colour survived the 2026-07-29 purge only because `local_layout_class_cast`
        independently re-derives it - but that caster was reachable ONLY from its own standalone
        management command, so the conveyor could not produce a border chip either. It can now."""
        from cardpicker.local_layout_class_cast import LAYOUT_CLASS_CAST_ANONYMOUS_ID
        from cardpicker.stage_e_dispatch import DispatchOutcome, _run_stage_d

        _seed_tags()
        card = CardFactory(content_phash=1)
        _evidence(
            card,
            layout_class="borderless",
            extractor_versions={**_COMPLETE_EXTRACTOR_VERSIONS, "layout_class": "layout-class-v1"},
        )

        outcome = DispatchOutcome(status="dispatched")
        _run_stage_d([card.pk], run_id="r1", outcome=outcome)

        assert outcome.stage_d_border_chip_votes == 1
        assert CardTagVote.objects.filter(anonymous_id=LAYOUT_CLASS_CAST_ANONYMOUS_ID).count() == 1


class TestExtractCardEvidenceCastsNoVote:
    """`image_evidence.fetch_and_compute_card_evidence_for_tests` (until 2026-07-30,
    `extract_card_evidence`) ended with a real `cast_border_attribute_vote(...).save()` from a
    function with ZERO production callers. That is the shape that made this whole hole invisible:
    a vote cast in an uncalled function looks like a wired channel to any grep."""

    def test_the_test_only_wrapper_writes_no_cardtagvote(self, db, monkeypatch):
        """The fixture must force a CONFIDENT `layout_class`. A failed fetch leaves it `""`, and
        the deleted `cast_border_attribute_vote(card, None)` would have returned None and saved
        nothing anyway - so a stub-the-fetch-to-None version of this test passes whether the vote
        cast is present or not. Verified by mutation: with the cast restored, the None-image form
        stayed green and this form goes red."""
        import cardpicker.image_evidence as image_evidence
        from cardpicker.image_evidence import ExtractionResult

        _seed_tags()
        card = CardFactory(content_phash=1)

        monkeypatch.setattr(image_evidence, "fetch_card_image", lambda *a, **k: object())
        monkeypatch.setattr(
            image_evidence,
            "compute_card_evidence",
            lambda *a, **k: ExtractionResult(
                card_id=card.pk, content_hash=1, fields={"layout_class": "black"}, extractor_versions={}
            ),
        )
        image_evidence.fetch_and_compute_card_evidence_for_tests(card)

        assert CardTagVote.objects.count() == 0

    def test_an_unseeded_tag_table_does_not_fail_the_dispatch(self, db, caplog):
        """A dispatch reaching this point has ALREADY written its printing votes. An operator gap
        in seeding an advisory chip's Tag row must not mark that dispatch FAILED and throw the
        printing verdicts' provenance away with it. Deliberately NOT a silent swallow: the counters
        stay at zero (the audit's own "this channel never ran" signal) and an ERROR names the fix."""
        import logging

        from cardpicker.stage_e_dispatch import (
            DispatchOutcome,
            _run_attribute_chip_casters,
        )

        card = CardFactory(content_phash=1)  # no _seed_tags() call - that is the point
        _evidence(card, collector_line_collector_number="123", bleed_class="trimmed")

        outcome = DispatchOutcome(status="dispatched")
        with caplog.at_level(logging.ERROR):
            _run_attribute_chip_casters(run_id="r1", card_ids=[card.pk], outcome=outcome)

        assert outcome.stage_d_frame_chip_votes == 0
        assert outcome.stage_d_bleed_calculator_votes == 0
        assert outcome.stage_d_border_chip_votes == 0
        assert "Attribute-chip casters skipped" in caplog.text
        assert "seed_attribute_tags" in caplog.text
