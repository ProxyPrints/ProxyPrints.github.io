"""
Tests for cardpicker.local_proxy_marker_cast (public issue #952) - the evidence-reading caster for
the `proxy-marked` no-match-reason tag. No network calls, no live image fetch - the same "host
venv, no network" precedent every sibling evidence-reading caster's own test module establishes.
"""

from typing import Any

import pytest

from cardpicker.local_proxy_marker_cast import (
    PROXY_MARKER_CAST_ANONYMOUS_ID,
    PROXY_MARKER_INCOMPLETE_EVIDENCE_SKIP_REASON,
    PROXY_MARKER_NO_EVIDENCE_SKIP_REASON,
    PROXY_MARKER_NOT_DETECTED_SKIP_REASON,
    PROXY_MARKER_VOTE_CONFIDENCE,
    cast_proxy_marker_vote,
    run_proxy_marker_cast,
)
from cardpicker.models import CardScanLog, CardTagVote, VotePolarity, VoteSource
from cardpicker.reason_tags import PROXY_MARKED_TAG_NAME, seed_no_match_reason_tags
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

_COMPLETE_EXTRACTOR_VERSIONS = {"legal_line": "legal-line-v1"}


def _evidence(card: Any, **overrides: Any) -> Any:
    defaults: dict[str, Any] = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(_COMPLETE_EXTRACTOR_VERSIONS),
        legal_line_proxy_marker_detected=False,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestCastProxyMarkerVote:
    """The pure per-card caster - mirrors `local_fallback.cast_border_attribute_vote`'s own
    shape (own Tag lookup, `run_id` threaded through, no DB write itself)."""

    def test_true_casts_an_unsaved_apply_vote(self, db: Any) -> None:
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)

        vote = cast_proxy_marker_vote(card, True, run_id="run-1")

        assert vote is not None
        assert vote.pk is None  # unsaved, ready for bulk_create
        assert vote.card == card
        assert vote.tag.name == PROXY_MARKED_TAG_NAME
        assert vote.polarity == VotePolarity.APPLY
        assert vote.anonymous_id == PROXY_MARKER_CAST_ANONYMOUS_ID
        assert vote.source == VoteSource.OCR
        assert vote.confidence == PROXY_MARKER_VOTE_CONFIDENCE
        assert vote.run_id == "run-1"

    def test_false_casts_no_vote(self, db: Any) -> None:
        """A `False` reading is not evidence the card is unmarked (module docstring) - the crop
        may simply have missed the text - so this must be indistinguishable from `None` below."""
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)

        assert cast_proxy_marker_vote(card, False, run_id="run-1") is None

    def test_none_casts_no_vote(self, db: Any) -> None:
        """`None` means the extractor never reached a conclusion at all (fetch failure) - a
        different state from `False`, but both must produce no vote."""
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)

        assert cast_proxy_marker_vote(card, None, run_id="run-1") is None

    def test_true_with_unseeded_tag_casts_no_vote(self, db: Any) -> None:
        card = CardFactory(content_phash=1)

        assert cast_proxy_marker_vote(card, True, run_id="run-1") is None


class TestRunProxyMarkerCast:
    def test_true_marker_writes_a_vote(self, db: Any) -> None:
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, legal_line_proxy_marker_detected=True)

        result = run_proxy_marker_cast(run_id="run-1", dry_run=False)

        assert result.votes_written == 1
        assert result.cards_considered == 1
        vote = CardTagVote.objects.get(card=card, anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID)
        assert vote.tag.name == PROXY_MARKED_TAG_NAME
        assert vote.polarity == VotePolarity.APPLY

    def test_false_marker_writes_no_vote_and_records_a_scan_log_row(self, db: Any) -> None:
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, legal_line_proxy_marker_detected=False)

        result = run_proxy_marker_cast(run_id="run-1", dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts[PROXY_MARKER_NOT_DETECTED_SKIP_REASON] == 1
        assert not CardTagVote.objects.filter(card=card, anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID).exists()
        scan_log = CardScanLog.objects.get(card=card, anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID)
        assert scan_log.skip_reason == PROXY_MARKER_NOT_DETECTED_SKIP_REASON

    def test_null_marker_writes_no_vote(self, db: Any) -> None:
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, legal_line_proxy_marker_detected=None)

        result = run_proxy_marker_cast(run_id="run-1", dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts[PROXY_MARKER_NOT_DETECTED_SKIP_REASON] == 1
        assert not CardTagVote.objects.filter(card=card, anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID).exists()

    def test_no_current_evidence_skips_as_rescannable(self, db: Any) -> None:
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)

        result = run_proxy_marker_cast(run_id="run-1", dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts[PROXY_MARKER_NO_EVIDENCE_SKIP_REASON] == 1
        scan_log = CardScanLog.objects.get(card=card, anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID)
        assert scan_log.skip_reason == PROXY_MARKER_NO_EVIDENCE_SKIP_REASON

    def test_missing_legal_line_extractor_skips_as_incomplete_rather_than_reading_false(self, db: Any) -> None:
        """Load-bearing: `legal_line_proxy_marker_detected` defaults to `None`/unset the same as
        a genuine `False` reading in some fixture shapes - without this gate a card whose
        `legal_line` extractor never ran would be indistinguishable from one that ran and found
        nothing, silently undercounting the true no-marker-hit population."""
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, extractor_versions={}, legal_line_proxy_marker_detected=None)

        result = run_proxy_marker_cast(run_id="run-1", dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts[PROXY_MARKER_INCOMPLETE_EVIDENCE_SKIP_REASON] == 1

    def test_dry_run_computes_but_writes_nothing(self, db: Any) -> None:
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, legal_line_proxy_marker_detected=True)

        result = run_proxy_marker_cast(run_id="run-1", dry_run=True)

        assert result.votes_would_cast == 1
        assert result.votes_written == 0
        assert not CardTagVote.objects.filter(card=card).exists()
        assert not CardScanLog.objects.filter(card=card).exists()

    def test_a_card_already_voted_is_not_reconsidered_on_a_later_run(self, db: Any) -> None:
        seed_no_match_reason_tags()
        card = CardFactory(content_phash=1)
        _evidence(card, legal_line_proxy_marker_detected=True)
        run_proxy_marker_cast(run_id="run-1", dry_run=False)

        result = run_proxy_marker_cast(run_id="run-2", dry_run=False)

        assert result.cards_considered == 0
        assert CardTagVote.objects.filter(card=card, anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID).count() == 1

    def test_missing_tag_seed_raises(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _evidence(card, legal_line_proxy_marker_detected=True)

        with pytest.raises(RuntimeError):
            run_proxy_marker_cast(run_id="run-1", dry_run=False)
