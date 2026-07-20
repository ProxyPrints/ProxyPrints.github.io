"""
Stage D's calculator layer (docs/features/catalog-completion-plan.md's "Harvest-calculate
pipeline", public issue #152, "Stage D: calculators D1-D6") - the deduction step that consumes
Stage C's `ImageEvidence` rows (pure extracted signals) plus the on-disk Scryfall bulk data and
casts real votes via the EXISTING, unchanged vote-consensus machinery
(`cardpicker.printing_consensus`/`cardpicker.vote_consensus`, both PROTECTED CORE - imported and
called, never re-derived or modified, per docs/upstreaming/license-provenance.md SS2). Nothing
here writes a verdict directly onto a `Card` - every calculator casts a `CardPrintingTag` (or
skips with a `CardScanLog` row) exactly the way the live pilot's OCR/phash/fallback engines
already do, and `resolve_and_persist_printing` (printing_consensus.py) decides the actual
outcome from the accumulated votes. This is a funnel to human review, not an auto-committing
pipeline: a single calculator's vote at `VoteSource.OCR` weight
(`settings.PRINTING_TAG_MACHINE_WEIGHT`, currently 0.5) can never alone resolve a card - the
same human-backed gate every other machine engine in this codebase is subject to.

ISSUE #152's OWN TITLE ("calculators D1-D6") NAMES SIX CALCULATORS BUT NO NUMBERED SPEC EXISTS
ANYWHERE (checked: the issue body/comments, this doc's own "Stages C-F" section, the private
orchestration orientation doc) - confirmed before building, not assumed. What DOES exist and is
binding: the design frame in the dispatching directive (funnel-to-review, fast/slow path split,
collector-line-OCR-plus-set-symbol as ONE near-unique join key, the pipeline-fidelity gate's
"call the existing shipped identification code paths, don't re-derive"), `docs/theory.md`'s
candidate-constrained-decoding model, and the Governing posture section. Per the directive's own
SCOPE MGMT clause, this PR builds the calculator FRAMEWORK plus ONE coherent first slice - the
join-key calculator - and defers the rest, enumerated at the bottom of this docstring, to
follow-up PRs. Building six speculative calculators against an unwritten spec would be inventing
the spec, which the directive explicitly forbids.

THE JOIN-KEY CALCULATOR (this PR's only calculator): collector-line OCR + set-symbol phash are
ONE near-unique join key into Scryfall data, not two separate calculators run in sequence - see
the design frame's own "set+collector# = near-unique Scryfall key" framing. Concretely: a
pre-M15 card's collector line never printed a set code, so `local_ocr.validate_against_candidates`
can only match on collector number alone - when that number is shared across more than one of
the card's own candidates (different expansions, since (expansion, collector_number) is unique
per `CanonicalCard`), the result is `"ambiguous"`, not a match, even though a genuine printing
identity exists. Stage C's `symbol_phash` (issue #160) is exactly the second half of the same key
that resolves this: the card's actual set symbol, hashed, is compared against each ambiguous
candidate's own expansion glyph (`local_fallback.render_set_symbol`, PROTECTED CORE, called not
modified) via plain Hamming-distance arithmetic on the stored hash ints - the same
"reimplement the arithmetic, don't reach into the protected module's private decision logic"
pattern `local_identify_printing_tags._classify_no_clear_winner` already established for phash
distance re-derivation. Both halves of the join key are therefore inside ONE calculator
function (`calculate_join_key_verdict`), not split across D1/D2 - reconciled here after an
advisor review flagged the initial draft's D1/D2 split as contradicting the design frame's own
"one join key" framing (2026-07-20).

THE MODERATOR-FLAG VETO (the design frame's own explicit ask): `legal_line_proxy_marker_detected`
(issue #151/#212's real motivating case - a "NOT FOR SALE"/proxy watermark that misparses as a
plausible-looking collector line) is checked ONLY at the moment a join-key match would otherwise
be trusted - not before, and not against a genuine no-match/ambiguous outcome. A proxy marker
doesn't mean "this card definitely isn't printing P" (P might still be right); it means "this
specific OCR reading is untrustworthy as evidence for P", which is exactly the false-accept risk
`docs/theory.md`'s candidate-constrained-decoding model is built to bound. A vetoed match is
therefore a named SKIP (`"proxy-marker-veto"`, a genuine, non-rescannable, evidence-gathered
conclusion - not a `CardPrintingTag(is_no_match=True)` vote, since a vetoed reading is not
evidence against every one of the card's other candidates either).

DEFERRED (explicitly out of scope for this PR, tracked as follow-up - NOT invented/stubbed here):
  - Geometry/border agreement calculator: cross-check `layout_class`/`bleed_class` against a
    join-key match's own `CanonicalPrintingMetadata.border_color`/`frame` and withhold (mirroring
    the live pilot's existing frame-mismatch-withholding logic in `local_identify_printing_tags`)
    when they disagree, operating over stored `ImageEvidence` instead of a live re-fetch.
  - Artist-OCR corroboration calculator: `artist_ocr_name` cross-checked via
    `local_fallback.match_artist` (PROTECTED CORE, call not modify) against a join-key match's
    candidate artist, or used LANDS-style to narrow candidates on the slow path.
  - Back-face-aware lookup: fold `printing_metadata_import.is_back_face`
    (issue #199/#213, name-based, no `ImageEvidence` field) into join-key candidate selection for
    double-faced cards.
  - Quality/integrity gating: `image_is_truncated`/`blur_variance`/`image_entropy` as a
    trust modifier, or a routing signal into Part 5's residual classification.
  - Visual/phash slow-path candidate matching: explicitly NOT bulk server-side phash - issue
    #150's own 2026-07-20 re-spec dropped that half in favor of user-submitted phash (task #203,
    a distinct, not-yet-designed mechanism). A slow-path calculator here would need to be
    redesigned against whatever #203 actually ships, not against the original bulk-phash idea.

None of the above is built or stubbed in this PR - each is its own follow-up calculator PR,
golden-gated (synthetic `ImageEvidence`/`Card`/`CanonicalCard` DB fixtures, not a live fetch -
Stage D consumes stored evidence + Scryfall-backed models, it never touches a live image, so
Stage C's golden-set convention of a real network fetch over 30 pinned cards doesn't apply here)
per docs/features/catalog-completion-plan.md's Stage C-established "one PR per unit, tested
before merge" discipline, applied to calculators instead of extractors.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import imagehash

from django.db.models import QuerySet

from cardpicker.local_fallback import (
    SYMBOL_DISTANCE_THRESHOLD,
    SYMBOL_MARGIN,
    render_set_symbol,
)
from cardpicker.local_identify_printing_tags import (
    CandidateNameIndex,
    CandidatePrinting,
    generate_run_id,
)
from cardpicker.local_ocr import (
    OcrParseResult,
    find_matching_candidates,
    validate_against_candidates,
)
from cardpicker.models import (
    Card,
    CardPrintingTag,
    CardScanLog,
    CardTypes,
    ImageEvidence,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.printing_consensus import resolve_and_persist_printing
from cardpicker.utils import twos_complement

logger = logging.getLogger(__name__)

# Own anonymous_id (distinct from OCR_ANONYMOUS_ID/PHASH_ANONYMOUS_ID/FALLBACK_ANONYMOUS_ID -
# this calculator votes on a DIFFERENT population, cards with a CURRENT ImageEvidence row, not
# a fresh per-run fetch, and must be independently purgeable/re-runnable via the same
# purge_machine_votes --run-id mechanism every other engine already uses).
JOIN_KEY_ANONYMOUS_ID = "stage-d-join-key-v1"

# Same two-tier split OCR_CONFIDENCE_BOTH/OCR_CONFIDENCE_COLLECTOR_ONLY already use in
# local_identify_printing_tags.py (set+number both matched vs. collector-number-only pre-M15
# match) - duplicated as literals rather than imported, matching DEDUCTIVE_BACKFILL_ANONYMOUS_ID's
# own "avoid a hard import-time dependency between sibling engines over one constant" precedent
# in that same module. Purely informational (resolve_weighted_consensus weights by `source`
# alone, never `confidence` - see GROUND_TRUTH_ATTRIBUTE_VOTE_CONFIDENCE's own comment for the
# same point made elsewhere in this codebase).
JOIN_KEY_CONFIDENCE_BOTH = 0.85
JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY = 0.75
# Symbol-phash tie-break resolves the ambiguous pre-M15 case using a SECOND, independent signal
# (the card's own rendered set symbol) rather than trusting the collector-number-only match
# alone - between the two tiers above: stronger than a bare unresolved ambiguity, weaker than a
# genuine set-code-in-text match (the symbol crop/threshold has its own known noise floor - see
# local_fallback.py's own SYMBOL_DISTANCE_THRESHOLD comment).
JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK = 0.75
# issue #207's precedent (OCR_NO_MATCH_CONFIDENCE/FALLBACK_NO_MATCH_CONFIDENCE, both 0.6) -
# a validated non-match is real but weaker evidence than a validated match (the parse could
# still be a misread of a candidate that does exist), duplicated as a literal for the same
# import-independence reason as the confidences above.
JOIN_KEY_NO_MATCH_CONFIDENCE = 0.6

# A degenerate/skip outcome that stays eligible for re-selection on a future invocation, same
# convention as local_identify_printing_tags.RESCANNABLE_SKIP_REASONS - "no-evidence" here
# because ImageEvidence simply hadn't been extracted yet for this card at selection time is a
# transient state (a future extraction run may still land it), not a permanent conclusion.
JOIN_KEY_RESCANNABLE_SKIP_REASONS = frozenset({"no-evidence"})

_SYMBOL_HASH_BITS = 64


@dataclass(frozen=True)
class JoinKeyVerdict:
    """
    Pure result of one card's join-key calculation - no DB write has happened yet (mirrors
    `image_evidence.ExtractionResult`'s own compute/persist split). Exactly one of three shapes:
    a positive match (`printing_pk` set), a genuine no-match (`is_no_match=True`), or a named
    skip (`skip_reason` set, `printing_pk` is None and `is_no_match` is False) - never more than
    one of these three at once.
    """

    card_id: int
    printing_pk: Optional[int] = None
    is_no_match: bool = False
    confidence: Optional[float] = None
    detail: str = ""
    skip_reason: str = ""


def _hamming_distance(a: int, b: int, bits: int = _SYMBOL_HASH_BITS) -> int:
    """Popcount of XOR between two `bits`-wide two's-complement ints - the same pure-arithmetic
    pattern `local_identify_printing_tags._classify_no_clear_winner` already uses to re-derive a
    phash distance ranking without reaching into `local_phash.py`'s own PROTECTED CORE private
    helpers. Duplicated here (not imported - that helper is private, leading-underscore, to its
    own module) rather than shared, matching this module's own "duplicate the arithmetic,
    reimplement nothing decision-shaped" convention for confidence constants above."""
    mask = (1 << bits) - 1
    return bin((a & mask) ^ (b & mask)).count("1")


def _symbol_phash_tiebreak(
    symbol_phash: Optional[int], ambiguous_candidates: list[CandidatePrinting]
) -> Optional[CandidatePrinting]:
    """
    The second half of the join key (see module docstring): compares the card's own stored
    `symbol_phash` against each ambiguous candidate's DISTINCT expansion's rendered keyrune
    glyph (`local_fallback.render_set_symbol`, PROTECTED CORE - called, not modified), using the
    SAME threshold/margin constants (`SYMBOL_DISTANCE_THRESHOLD`/`SYMBOL_MARGIN`) that module's
    own `find_symbol_matches` applies to a live image scan - reimplemented as pure Hamming-
    distance arithmetic over the already-computed hash ints (no image, no re-fetch), the same
    "reimplement the arithmetic, don't touch the protected decision logic" pattern
    `_classify_no_clear_winner` already established for phash. Returns the unique winning
    candidate, or `None` if no glyph could be rendered, the best distance exceeds the threshold,
    or a runner-up sits within the margin (an unresolved tie, same as `find_symbol_matches`'s
    own `None` return).
    """
    if symbol_phash is None:
        return None

    distances: list[tuple[CandidatePrinting, int]] = []
    seen_expansions: set[str] = set()
    for candidate in ambiguous_candidates:
        if candidate.expansion_code in seen_expansions:
            continue  # distinct expansions only - see find_symbol_matches's own precedent
        seen_expansions.add(candidate.expansion_code)
        reference = render_set_symbol(candidate.expansion_code)
        if reference is None:
            continue
        reference_hash_int = twos_complement(str(imagehash.phash(reference)), _SYMBOL_HASH_BITS)
        distances.append((candidate, _hamming_distance(symbol_phash, reference_hash_int)))

    if not distances:
        return None

    distances.sort(key=lambda pair: pair[1])
    best_candidate, best_distance = distances[0]
    if best_distance > SYMBOL_DISTANCE_THRESHOLD:
        return None
    if len(distances) > 1 and (distances[1][1] - best_distance) <= SYMBOL_MARGIN:
        return None
    # the winning candidate's OWN expansion may still have more than one candidate sharing it
    # (e.g. two different collector numbers on the exact same ambiguous ballot - shouldn't
    # happen given find_matching_candidates already filtered to one shared number, but resolved
    # defensively rather than assumed): every ambiguous candidate on the winning expansion.
    return next(c for c in ambiguous_candidates if c.expansion_code == best_candidate.expansion_code)


def calculate_join_key_verdict(
    card_id: int, evidence: ImageEvidence, candidates: list[CandidatePrinting]
) -> JoinKeyVerdict:
    """
    The join-key calculator (this PR's only calculator - see module docstring). Pure function,
    no DB write - reconstructs an `OcrParseResult` from Stage C's already-persisted
    `collector_line_set_code`/`collector_line_collector_number` fields (no re-OCR, no re-fetch)
    and calls the EXISTING, unmodified `local_ocr.validate_against_candidates` - the pipeline-
    fidelity gate's own "call the existing shipped identification code paths, don't re-derive"
    requirement, satisfied by direct reuse rather than a parallel implementation.
    """
    parsed = OcrParseResult(
        raw_text=evidence.collector_line_raw_text,
        set_code=evidence.collector_line_set_code or None,
        collector_number=evidence.collector_line_collector_number or None,
    )
    matched, reason = validate_against_candidates(parsed, candidates)

    if matched is not None:
        if evidence.legal_line_proxy_marker_detected:
            # THE MODERATOR-FLAG VETO (module docstring) - a would-be match is rejected as
            # untrustworthy, not accepted and not converted into is_no_match evidence either.
            return JoinKeyVerdict(card_id=card_id, skip_reason="proxy-marker-veto", detail=parsed.raw_text)
        confidence = JOIN_KEY_CONFIDENCE_BOTH if parsed.set_code is not None else JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY
        return JoinKeyVerdict(card_id=card_id, printing_pk=matched.pk, confidence=confidence, detail=parsed.raw_text)

    if reason == "ambiguous":
        ambiguous_candidates = find_matching_candidates(parsed, candidates)
        tie_broken = _symbol_phash_tiebreak(evidence.symbol_phash, ambiguous_candidates)
        if tie_broken is not None:
            if evidence.legal_line_proxy_marker_detected:
                return JoinKeyVerdict(card_id=card_id, skip_reason="proxy-marker-veto", detail=parsed.raw_text)
            return JoinKeyVerdict(
                card_id=card_id,
                printing_pk=tie_broken.pk,
                confidence=JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK,
                detail=f"{parsed.raw_text} + symbol_phash tiebreak",
            )
        return JoinKeyVerdict(card_id=card_id, skip_reason="ambiguous", detail=parsed.raw_text)

    if reason == "parsed-but-no-match":
        # genuine whole-candidate-set negative evidence - same issue #207 "the vote IS the
        # record" convention every other engine's real is_no_match cast already follows.
        return JoinKeyVerdict(
            card_id=card_id,
            is_no_match=True,
            confidence=JOIN_KEY_NO_MATCH_CONFIDENCE,
            detail=parsed.raw_text,
        )

    # reason == "no-text": nothing was parsed at all - a genuine, non-rescannable abstention
    # (an already-extracted ImageEvidence row with no collector_number found is a real, repeat-
    # able negative outcome, not a transient one - see JOIN_KEY_RESCANNABLE_SKIP_REASONS's own
    # comment for the one skip reason that IS treated as transient).
    return JoinKeyVerdict(card_id=card_id, skip_reason="no-text")


@dataclass
class JoinKeyCalculatorResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    no_match_votes_would_cast: int = 0
    votes_written: int = 0
    no_match_votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    # capped audit sample, mirroring PilotResult/FrameMismatchRecoveryResult's own "up to N, for
    # the report" convention elsewhere in this codebase.
    audit: list[dict[str, object]] = field(default_factory=list)


def _eligible_cards_queryset(anonymous_id: str) -> "QuerySet[Card]":
    """
    Mirrors `local_identify_printing_tags._eligible_base_queryset`'s shape (unresolved, no
    confirmed indexing match, card_type=CARD only, no existing vote from this calculator's own
    anonymous_id, no non-rescannable scan-log row for it) - a fresh, independent eligibility
    query rather than a call into that function directly, since this calculator's resume/skip
    population (cards with a CURRENT `ImageEvidence` row) is a genuinely different concept from
    the live pilot's own per-run candidate selection, not a variant of it.
    """
    non_rescannable_scanned_card_ids = (
        CardScanLog.objects.filter(anonymous_id=anonymous_id)
        .exclude(skip_reason__in=JOIN_KEY_RESCANNABLE_SKIP_REASONS)
        .values_list("card_id", flat=True)
    )
    return (
        Card.objects.filter(
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            canonical_card__isnull=True,
            card_type=CardTypes.CARD,
        )
        .exclude(printing_tags__anonymous_id=anonymous_id)
        .exclude(pk__in=non_rescannable_scanned_card_ids)
        .distinct()
        .select_related("source")
    )


def run_join_key_calculator(
    run_id: Optional[str] = None, dry_run: bool = True, chunk_size: int = 500, audit_sample_size: int = 20
) -> JoinKeyCalculatorResult:
    """
    Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row (its
    `content_hash` matching the card's own live `content_phash` - an evidence row from a prior
    image version is never trusted for a card whose upload has since changed) that ran the
    `collector_line_ocr`/`symbol_region` extractors. `dry_run=True` (the default, matching every
    other Stage 3+ command's own opt-in-to-write convention) computes and counts everything
    without writing any `CardPrintingTag`/`CardScanLog` row.
    """
    run_id = run_id or generate_run_id()
    index = CandidateNameIndex()
    result = JoinKeyCalculatorResult(dry_run=dry_run, run_id=run_id)

    votes_batch: list[CardPrintingTag] = []
    scan_log_batch: list[CardScanLog] = []
    touched_card_ids: list[int] = []

    for card in _eligible_cards_queryset(JOIN_KEY_ANONYMOUS_ID).iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = (
            ImageEvidence.objects.filter(card_id=card.pk, content_hash=card.content_phash)
            .filter(extractor_versions__has_key="collector_line_ocr")
            .order_by("-updated_at")
            .first()
        )
        if evidence is None:
            result.skip_counts["no-evidence"] = result.skip_counts.get("no-evidence", 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id=run_id, skip_reason="no-evidence"
                    )
                )
            continue

        result.cards_considered += 1
        candidates = index.candidates_for(card.name)
        verdict = calculate_join_key_verdict(card.pk, evidence, candidates)

        if verdict.skip_reason:
            result.skip_counts[verdict.skip_reason] = result.skip_counts.get(verdict.skip_reason, 0) + 1
            if not dry_run:
                scan_log_batch.append(
                    CardScanLog(
                        card_id=card.pk,
                        anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                        run_id=run_id,
                        skip_reason=verdict.skip_reason,
                    )
                )
            continue

        if verdict.is_no_match:
            result.no_match_votes_would_cast += 1
        else:
            result.votes_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk, "detail": verdict.detail, "is_no_match": verdict.is_no_match})

        if not dry_run:
            votes_batch.append(
                CardPrintingTag(
                    card_id=card.pk,
                    printing_id=verdict.printing_pk,
                    is_no_match=verdict.is_no_match,
                    anonymous_id=JOIN_KEY_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=verdict.confidence,
                    run_id=run_id,
                )
            )
            touched_card_ids.append(card.pk)

    if not dry_run:
        CardPrintingTag.objects.bulk_create(votes_batch)
        CardScanLog.objects.bulk_create(scan_log_batch)
        for touched_card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_printing(touched_card)

        result.votes_written = sum(1 for v in votes_batch if not v.is_no_match)
        result.no_match_votes_written = sum(1 for v in votes_batch if v.is_no_match)

    return result


__all__ = [
    "JOIN_KEY_ANONYMOUS_ID",
    "JOIN_KEY_CONFIDENCE_BOTH",
    "JOIN_KEY_CONFIDENCE_COLLECTOR_ONLY",
    "JOIN_KEY_CONFIDENCE_SYMBOL_TIEBREAK",
    "JOIN_KEY_NO_MATCH_CONFIDENCE",
    "JOIN_KEY_RESCANNABLE_SKIP_REASONS",
    "JoinKeyVerdict",
    "calculate_join_key_verdict",
    "JoinKeyCalculatorResult",
    "run_join_key_calculator",
]
