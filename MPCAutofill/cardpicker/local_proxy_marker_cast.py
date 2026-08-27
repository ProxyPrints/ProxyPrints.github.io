"""
Proxy-marker caster (public issue #952) - casts a `CardTagVote` for the `proxy-marked` no-match-
reason tag straight off `ImageEvidence.legal_line_proxy_marker_detected`, a field Stage C already
extracts and persists for every card (`local_ocr.parse_legal_line`'s `_PROXY_MARKER_RE`, run as
part of the `legal_line` extractor - see `image_evidence.py`). Zero image fetches, zero new OCR:
this is a pure read over a column that already exists on 100% of `ImageEvidence` rows, so casting
this vote costs nothing beyond the write itself.

WHAT THE FIELD MEANS. `_PROXY_MARKER_RE` matches four token families - "proxy"/"proxies" (with or
without a maker name glued on, e.g. "JestaProxy"), "not for sale" (and spacing variants),
"playtest", and "original design" - against `legal_line_raw_text`, the OCR'd bottom strip of the
card. A hit is a literal textual observation, not an inference from combined signals the way
`local_detect_ai_art`'s marker match or `local_fallback`'s candidate-narrowing sub-checks are.

TRUE ONLY, DELIBERATELY. `legal_line_proxy_marker_detected` is `True`/`False`/`None`: `None` means
the extractor never ran (fetch failure); `False` means it ran and found no marker token in
whatever text the legal-line crop returned. That crop is measured to yield a genuine legal line
only 10.6% of the time (issue #959, not fixed here - see this module's own `PROXY_MARKER_REQUIRED_
EXTRACTOR_KEYS` gate for why an unrun extractor and a false reading are still kept apart in the
skip vocabulary below even though both currently produce no vote). A `False` reading is therefore
NOT evidence the card is unmarked - the crop may simply have missed text that is present elsewhere
on the card face, or the marker may use wording outside the four families above. This module casts
`VotePolarity.APPLY` on `True` only, and casts nothing at all on `False` or `None` - there is no
`NOT_APPLICABLE`/negative vote here, matching `local_detect_ai_art`'s own "positive-detection
only" discipline for the identical reason (a non-hit proves nothing about the underlying fact).

CONFIDENCE: `PROXY_MARKER_VOTE_CONFIDENCE = 0.75`, the same heuristic tier as `local_fallback.
BORDER_ATTRIBUTE_VOTE_CONFIDENCE` (a direct pixel/text sample) rather than `local_detect_ai_art.
AI_ART_CONFIDENCE_SINGLE_FIELD` (0.6, a fuzzy multi-marker inference) - a positive regex match
against already-extracted OCR text needs no combination of signals the way the AI-art detector's
tiered confidence does. `confidence` is informational only: `vote_consensus.
resolve_weighted_consensus`/`resolve_tag` weight strictly by `source`, never `confidence` (see
`local_calculate_verdicts.JOIN_KEY_CONFIDENCE_BOTH`'s own comment making the identical point), and
a single `VoteSource.OCR` vote can never resolve a tag alone regardless of the number attached to
it.

THE STAGE D VETO IS UNCHANGED. `legal_line_proxy_marker_detected` already has a role in
`local_calculate_verdicts.calculate_join_key_verdict` (the moderator-flag SIGNAL, no longer a veto
- see that function's own 2026-07-21 correction) and in `select_card_ids_proxy_marker_veto`. This
module adds a vote ALONGSIDE that existing read; it does not touch either call site, and casting
this tag says nothing new about whether a printing match is correct - the two channels read the
same field for two different, independent purposes.

OWN IDENTITY, OWN TAXONOMY. `PROXY_MARKER_CAST_ANONYMOUS_ID = "proxy-marker-cast-v1"` - distinct
from every other engine's identity, same "independently purgeable/re-runnable via `purge_machine_
votes --run-id`" reasoning every other `*-v1` identity in this tree already documents. The tag
itself, `proxy-marked` (`reason_tags.PROXY_MARKED_TAG_NAME`), belongs to the no-match-reason
taxonomy (`cardpicker.reason_tags`, seeded by `seed_no_match_reason_tags`) rather than
`default_tags.DEFAULT_TAGS`: its closest sibling is `no-collector-line` - a machine-derived
observation about what the RENDER shows, which a human could equally give as their reason for
picking "no match" - not an attribute of the printing itself, so it carries no Scryfall-side
`matches` predicate and cannot participate in `attributeChips.ts`'s candidate filtering the way
`Old Border`/`Full Art` do.
"""

from dataclasses import dataclass, field
from typing import Iterable, Optional

from django.db.models import QuerySet

from cardpicker.image_evidence import current_evidence_queryset
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import (
    Card,
    CardScanLog,
    CardTagVote,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.reason_tags import PROXY_MARKED_TAG_NAME
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.vote_write import purge_and_write_votes

PROXY_MARKER_CAST_ANONYMOUS_ID = "proxy-marker-cast-v1"

# The single extractor key that populates `legal_line_proxy_marker_detected` - see
# `image_evidence.py`'s own `extractor_versions["legal_line"] = ...` store.
PROXY_MARKER_REQUIRED_EXTRACTOR_KEYS: tuple[str, ...] = ("legal_line",)

PROXY_MARKER_VOTE_CONFIDENCE = 0.75

# THIS CALCULATOR'S OWN SKIP VOCABULARY (the 2026-07-29 declaration convention,
# docs/reference/skip-reasons.md). Values are reused from the shared vocabulary other casters
# already use; the prefix keeps this module's own declarations distinct from theirs.
PROXY_MARKER_NO_EVIDENCE_SKIP_REASON = "no-evidence"
PROXY_MARKER_INCOMPLETE_EVIDENCE_SKIP_REASON = "incomplete-evidence"
PROXY_MARKER_NOT_DETECTED_SKIP_REASON = "no-marker-hit"

PROXY_MARKER_RESCANNABLE_SKIP_REASONS = frozenset(
    {PROXY_MARKER_NO_EVIDENCE_SKIP_REASON, PROXY_MARKER_INCOMPLETE_EVIDENCE_SKIP_REASON}
)


def cast_proxy_marker_vote(
    card: Card,
    proxy_marker_detected: Optional[bool],
    confidence: float = PROXY_MARKER_VOTE_CONFIDENCE,
    run_id: Optional[str] = None,
) -> Optional[CardTagVote]:
    """An unsaved `CardTagVote` ready for `bulk_create`, or `None` on `False`/`None` (module
    docstring's TRUE ONLY section - `not proxy_marker_detected` covers both) or if the tag hasn't
    been seeded yet. Mirrors `local_fallback.cast_border_attribute_vote`'s own shape: does its own
    `Tag` lookup, never raises, `run_id` threaded through so the vote is revocable the same way
    every other machine vote here is."""
    if not proxy_marker_detected:
        return None
    tag = Tag.objects.filter(name=PROXY_MARKED_TAG_NAME).first()
    if tag is None:
        return None
    return CardTagVote(
        card=card,
        tag=tag,
        polarity=VotePolarity.APPLY,
        anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID,
        source=VoteSource.OCR,
        confidence=confidence,
        run_id=run_id,
    )


@dataclass
class ProxyMarkerCastResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    audit: list[dict[str, object]] = field(default_factory=list)


def _eligible_cards_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """Same idempotence/`card_ids`-scoping pattern as `local_attribute_chip_cast._eligible_cards_
    queryset`/`local_detect_ai_art._eligible_cards_queryset` - see either for the full reasoning
    on why `card_ids` is pushed into the `CardScanLog` subquery rather than applied after."""
    non_rescannable_scanned_card_ids_qs = CardScanLog.objects.filter(
        anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID
    ).exclude(skip_reason__in=PROXY_MARKER_RESCANNABLE_SKIP_REASONS)
    if card_ids is not None:
        non_rescannable_scanned_card_ids_qs = non_rescannable_scanned_card_ids_qs.filter(card_id__in=card_ids)
    queryset = (
        Card.objects.exclude(tag_votes__anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned_card_ids_qs.values_list("card_id", flat=True))
        .distinct()
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def run_proxy_marker_cast(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    card_ids: Optional[Iterable[int]] = None,
) -> ProxyMarkerCastResult:
    """Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row
    (`content_hash` matching the card's own live `content_phash`) that has completed the
    `legal_line` extractor. `dry_run=True` is the default, matching every other Stage 3+ command's
    own opt-in-to-write convention.

    GATE VERIFICATION lives in the management command / conveyor caller, not here - matching
    `run_attribute_chip_cast`/`run_ai_art_detector`'s own split.
    """
    run_id = run_id or generate_run_id()
    result = ProxyMarkerCastResult(dry_run=dry_run, run_id=run_id)

    tag = Tag.objects.filter(name=PROXY_MARKED_TAG_NAME).first()
    if tag is None:
        raise RuntimeError(
            f"Tag {PROXY_MARKED_TAG_NAME!r} does not exist yet - run `seed_no_match_reason_tags` "
            "before this calculator."
        )

    votes_batch: list[CardTagVote] = []
    scan_log_batch: list[CardScanLog] = []

    def _skip(card: Card, reason: str) -> None:
        result.skip_counts[reason] = result.skip_counts.get(reason, 0) + 1
        if not dry_run:
            scan_log_batch.append(
                CardScanLog(
                    card_id=card.pk, anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID, run_id=run_id, skip_reason=reason
                )
            )

    for card in _eligible_cards_queryset(card_ids=card_ids).iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = current_evidence_queryset(card).order_by("-updated_at").first()
        if evidence is None:
            _skip(card, PROXY_MARKER_NO_EVIDENCE_SKIP_REASON)
            continue

        if any(key not in evidence.extractor_versions for key in PROXY_MARKER_REQUIRED_EXTRACTOR_KEYS):
            _skip(card, PROXY_MARKER_INCOMPLETE_EVIDENCE_SKIP_REASON)
            continue

        result.cards_considered += 1
        vote = cast_proxy_marker_vote(card, evidence.legal_line_proxy_marker_detected, run_id=run_id)
        if vote is None:
            _skip(card, PROXY_MARKER_NOT_DETECTED_SKIP_REASON)
            continue

        result.votes_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk})
        if not dry_run:
            votes_batch.append(vote)

    if not dry_run:
        purge_and_write_votes(
            CardTagVote,
            votes_batch,
            anonymous_id=PROXY_MARKER_CAST_ANONYMOUS_ID,
            target_field="card_id",
            ignore_conflicts=True,
        )
        CardScanLog.objects.bulk_create(scan_log_batch)
        result.votes_written = len(votes_batch)

        touched_card_ids = [vote.card_id for vote in votes_batch]
        for card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_tag_votes(card)

    return result


__all__ = [
    "PROXY_MARKER_CAST_ANONYMOUS_ID",
    "PROXY_MARKER_REQUIRED_EXTRACTOR_KEYS",
    "PROXY_MARKER_VOTE_CONFIDENCE",
    "PROXY_MARKER_NO_EVIDENCE_SKIP_REASON",
    "PROXY_MARKER_INCOMPLETE_EVIDENCE_SKIP_REASON",
    "PROXY_MARKER_NOT_DETECTED_SKIP_REASON",
    "PROXY_MARKER_RESCANNABLE_SKIP_REASONS",
    "cast_proxy_marker_vote",
    "ProxyMarkerCastResult",
    "run_proxy_marker_cast",
]
