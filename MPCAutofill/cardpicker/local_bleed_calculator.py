"""
Bleed calculator: derives per-card bleed-in-millimetres from two independent, cross-checking
methods and casts the resulting `appropriate-bleed` verdict as a machine vote - a Stage D-style
calculator in the same "read persisted Stage C evidence, fetch nothing" family as
`local_layout_class_cast.py`/`local_attribute_chip_cast.py`, which this module mirrors
structurally (own anonymous_id, own skip vocabulary, same eligibility/idempotence shape).

TWO METHODS, ONE CROSS-CHECK.

METHOD A - closed form from aspect ratio. A card image's own pixel aspect ratio alone determines
its symmetric bleed under the standard 63x88mm trim size. `local_fallback.compute_bleed_diff_mm`
(PROTECTED CORE, imported not re-derived) already computes this and stores it on every card's
`ImageEvidence.bleed_diff_mm` at Stage C - no canonical, no metadata, no frame class required, so
it is available for every card with a fetched, non-degenerate image. This module recovers the
actual bleed value from that stored diff (`BLEED_MARGIN_MM - bleed_diff_mm`) rather than
re-deriving the formula a second time.

METHOD B - the pinline ruler. `local_pinline_inset.measure_pinline_inset` (also Stage C,
`ImageEvidence.pinline_inset_frac_*`/`pinline_inset_call_*`) measures, per edge, the distance from
the image's own edge to the pinline as a fraction of that edge's perpendicular dimension.
Subtracting a calibrated trim-to-pinline constant (`CALIBRATED_PINLINE_INSET_MM` below, keyed by
`(CanonicalPrintingMetadata.border_color, CanonicalPrintingMetadata.frame)` - the one thing this
module reads beyond `ImageEvidence`) yields a per-edge bleed. A constant's absence (missing table
key) or explicit `None` entry (an abstention this module honours, never guesses past) both mean
Method B is skipped for that edge; Method A alone still applies.

SCALE, PER EDGE INDEPENDENTLY. `px_per_mm` is derived once per card from whichever axis (left/
right preferred, top/bottom as fallback) has BOTH opposite edges' constants usable and
`CALL_MEASURED` - the pinline-ruler report's own derivation (pinline span in px over the
calibrated span in mm). Once that scale exists, each individual edge's bleed is computed from
its OWN frac and OWN constant alone, so an edge whose partner is abstained (2015-frame bottom,
paired with a perfectly usable top) still reports - see `_pinline_edge_bleed_mm`.

WHY UNKNOWN-ERA CARDS FALL BACK TO METHOD A ALONE - the per-era constants differ by more than the
cross-method agreement does, so guessing the era would inject more error than the measurement it
feeds. `border_color` is available on every resolved canonical (`local_fallback.classify_border_color`,
93.75% measured accuracy) but `frame` (the era) is only meaningful together with it for selecting
a Method B constant, and both live on the same 10.08%-covered `CanonicalPrintingMetadata` row -
so "unknown era" here really means "no CanonicalPrintingMetadata resolved at all" in the overwhelming
majority of cases, not a card whose border colour is known but era genuinely ambiguous. Checked
anyway, because the question is well-posed independent of that: pooling `black_2003` (top/left/
right medians 2.960-2.962mm) with `black_2015` (2.454-2.537mm) gives an era-to-era GAP of
0.42-0.51mm per edge. That number passes the calibration's own raw usability rule (n>=5,
spread<~1.5mm - a floor-and-ceiling sanity check: enough distinct cards for a per-class median
to be meaningful, and per-class spread narrow enough that the constant is stable card-to-card)
with room to spare. It does
NOT pass the standard the calibration was actually held to everywhere else: every class this
module marks usable has WITHIN-class spread at or below the ~0.24mm cross-method agreement floor
(pinline-ruler report's own median agreement against the independent NCC/closed-form checks -
`black_2003` 0.169mm, `white_2003` 0.055-0.085mm), and a 0.42-0.51mm pooled gap is 2-3x that floor
- an avoidable, era-attributable bias roughly the same size as the entire method's measured
precision, in a case (~10% of the catalogue) where the finer, era-split constant is directly
selectable instead. So: no pooled cross-era entry exists in `CALIBRATED_PINLINE_INSET_MM` for
`black`/`white` at all - a card whose `CanonicalPrintingMetadata.frame` cannot be read falls back
to Method A alone, full stop, rather than trading Method B's whole reason for existing (finer
precision than Method A) for slightly wider coverage.

THE ABSTAIN GATE. When both methods produce a number and they disagree by more
than `METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM`, this calculator emits no vote and records
`BLEED_CALC_METHOD_DISAGREEMENT_SKIP_REASON` instead - the two methods fail in DIFFERENT ways
(Method B is fooled by an unusually thick printed border reading as extra bleed; Method A is not,
since it only sees the image's own aspect ratio), so a disagreement this large means at least one
of them is wrong for this specific card, and the honest output is "a human should look," not a
guess at which method to trust. Cost, per the pinline-ruler/geometry-bleed calibration sample: 1 of
68 ordinary cards exceeded the threshold; a card independently known to have a genuinely thick
printed border sat at 3.3mm past it.

CONFIDENCE TIERS, AND WHY THEY ARE NOT A CONSENSUS-WEIGHT INPUT. `vote_consensus.
resolve_vote_weight`'s own docstring is explicit that a vote's weight is a function of WHO cast it
(`source`) and by what method, never of its self-reported `confidence` - "confidence belongs in a
calculator's own emit-or-skip decision, upstream of any vote row existing at all," and letting a
calculator's own confidence buy extra consensus weight is exactly the failure mode the
distinct-agent quorum rule exists to prevent. So this module does not invent a confidence number
to express "the two methods agreed": it reuses the SAME two-tier split `local_fallback.py`
already draws for its own multi-evidence-vs-single-evidence distinction
(`FALLBACK_CONFIDENCE_MULTI_EVIDENCE=0.8` vs `FALLBACK_CONFIDENCE_SINGLE_EVIDENCE=0.7`, imported
verbatim, never duplicated) - a card where both methods agree within the gate is exactly that
same "two independent evidence sources concur" case that pair of constants already names, and a
card carried by Method A alone (Method B unavailable or abstained for this card's class/edge) is
exactly the "single evidence source" case. The confidence value is still stored on the
`CardTagVote` row, same as every other machine caster in this codebase - an honest record of how
the calculator itself rates the evidence, informational per `vote_consensus.py`, not read by it.

NEGATIVE-ONLY, SAME CONVENTION AS `cast_bleed_edge_vote`: a vote is cast only when this
calculator's own (cross-checked) reading agrees with Stage C's `bleed_class == "trimmed"` - the
~2.5% real exception, not the ~97.5% ordinary "bleed" case. Voting APPLY on the routine case
would flood moderation with confirmations of normalcy, which is the opposite of what
`appropriate-bleed`, a SENSITIVE tag, is for. This calculator REPLACES the `bleed-edge-cast-v1`
identity in `local_attribute_chip_cast`, which cast on `bleed_class == "trimmed"` alone and is now
retired: this calculator's whole reason to exist is withholding the vote when Method B's
independent, per-edge measurement contradicts that "trimmed" reading past the abstain gate - the
same 1.5% the gate itself measures - and the old single-signal caster would have voted on exactly
those cards, defeating the abstention and double-counting one signal. As the sole machine channel
it covers everything the old caster covered: it skips only when BOTH methods are unavailable, and
abstains only when both are present and disagree past the gate - otherwise Method A alone still
votes.

ZERO IMAGE FETCHES. Every input (`ImageEvidence.bleed_diff_mm`/`bleed_class`/`pinline_inset_*`,
`CanonicalPrintingMetadata.border_color`/`frame`) is already in the database.
"""

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, Optional

from django.db.models import QuerySet

from cardpicker.image_evidence import current_evidence_queryset
from cardpicker.local_fallback import (
    BLEED_EDGE_TAG_NAME,
    FALLBACK_CONFIDENCE_MULTI_EVIDENCE,
    FALLBACK_CONFIDENCE_SINGLE_EVIDENCE,
)
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.local_pinline_inset import CALL_MEASURED
from cardpicker.models import (
    CanonicalPrintingMetadata,
    Card,
    CardScanLog,
    CardTagVote,
    ImageEvidence,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.vote_write import purge_and_write_votes

# Own anonymous_id (distinct from `local_fallback.FALLBACK_ANONYMOUS_ID` and from the retired
# `local_attribute_chip_cast.BLEED_EDGE_CAST_ANONYMOUS_ID` - see module docstring's
# "NEGATIVE-ONLY" section for why this identity is the SOLE machine channel for
# `appropriate-bleed`, replacing that retired chip caster).
BLEED_CALCULATOR_CAST_ANONYMOUS_ID = "bleed-calculator-cast-v1"

# Method A's own extractor family (bleed_diff_mm/bleed_class/width/height all persisted together
# - image_evidence.py's geometry_bleed block). Method B ("pinline_inset") is opportunistic, not
# required: its absence never blocks a Method-A-only vote.
REQUIRED_EXTRACTOR_KEYS: tuple[str, ...] = ("geometry_bleed",)

# mirrors local_fallback._BLEED_MARGIN_MM/_CARD_TRIM_WIDTH_MM/_CARD_TRIM_HEIGHT_MM (PROTECTED
# CORE) - reproduced rather than imported across the module boundary, the same convention
# local_pinline_inset.py's own UNIFORMITY_STD_THRESHOLD comment documents for the identical
# reason (that file cannot import a private, underscore-prefixed name from protected core).
BLEED_MARGIN_MM = 3.175
CARD_TRIM_WIDTH_MM = 63.0
CARD_TRIM_HEIGHT_MM = 88.0

# Named rather than a bare literal - the abstain gate and the unit test that exercises it both
# reference this constant, and a bare literal at either call site would let them drift apart
# silently.
METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM = 2.0

_EDGE_NAMES = ("top", "bottom", "left", "right")

# Calibrated trim-to-pinline inset, mm, from the pinline-ruler + calib-expand calibration
# sessions (41 + 275 trim-exact Scryfall PNGs, n and spread reported per class in each session's
# own report). Keyed by (CanonicalPrintingMetadata.border_color, CanonicalPrintingMetadata.frame).
# `None` = an explicit abstention (spread over the calibration's own ~1.5mm usability ceiling, or
# n below the 5-card floor) - never a guessed number. A missing (border_color, frame) key means no
# calibration was attempted for that combination at all; both cases fall back to Method A alone
# for that edge/card. See module docstring's "WHY UNKNOWN-ERA CARDS FALL BACK TO METHOD A ALONE"
# for why no pooled cross-era entry is offered instead of splitting further.
CALIBRATED_PINLINE_INSET_MM: dict[tuple[str, str], dict[str, Optional[float]]] = {
    ("black", "2003"): {"top": 2.962, "bottom": 2.962, "left": 2.960, "right": 2.960},
    # bottom ABSTAIN: n=34, spread 3.334mm - far wider than the other edges' 0.085-0.241mm,
    # and no era/release-date/frame-effect split reduced it; the 2015 frame's collector-info
    # text line reads as a pinline overrun on some cards but not others. A constant varying
    # that much card-to-card is not a class constant.
    # top/left/right remain tight and usable.
    ("black", "2015"): {"top": 2.454, "bottom": None, "left": 2.496, "right": 2.537},
    # top: a 12% (5/43) sharp-outlier rate - individual extreme single-edge readings on
    # specific artwork, not class-wide spread, and no era/release-date/frame-effect split
    # explains them - read as detector mis-fires, not genuine border-geometry variation.
    # Shipped anyway: the full-sample median equals the filtered core median at this precision.
    ("black", "1993"): {"top": 2.623, "bottom": 3.131, "left": 2.833, "right": 2.283},
    # coverage caveat: 37-44% of edges are CALL_NO_TRANSITION/CALL_INDETERMINATE_BLACK on this
    # frame era (not modelled here - _pinline_edge_bleed_mm's own CALL_MEASURED gate already
    # skips those cards' edges individually, so this constant is simply unreached more often for
    # this class, not silently wrong).
    ("black", "1997"): {"top": 3.385, "bottom": 3.469, "left": 2.964, "right": 2.879},
    ("white", "2003"): {"top": 2.877, "bottom": 2.877, "left": 2.875, "right": 2.960},
    # ABSTAIN all 4 edges: spread 1.6-1.8mm on top/left/right is over the ~1.5mm usability
    # ceiling; bottom's usable n=6 comes from 11/17 edges returning no detectable transition
    # at all (black-indeterminate), an effective-coverage sliver too thin to anchor a constant.
    ("white", "2015"): {"top": None, "bottom": None, "left": None, "right": None},
    # n=2, below the 5-card floor - reported for completeness in the calibration sessions, never
    # usable here.
    ("white", "1993"): {"top": None, "bottom": None, "left": None, "right": None},
}

# Borderless is a STRUCTURAL abstention, not a per-era gap in the table above: an inward scan
# has nothing to stop at on a card whose art runs to the edge, so it halts at whatever artwork
# it meets first - not a frame feature (n=97 across two independently-fetched pulls; spread
# stayed 2.9-4.5mm on every edge both times). A second, independent method - fitting the known
# frame geometry (title plate, type-line band, rules and P/T boxes) for scale and offset -
# failed the same way: on trim-exact borderless images, whose own bounds ARE the trim, its
# median absolute edge error was 5.4mm and the optimizer settled on a wrong solution scoring
# roughly 3x the correct one, because artwork gradients outweigh the frame's own. Two unrelated
# methods failing is stronger grounds for permanent abstention than one - Method A's
# aspect-ratio closed form still covers these cards; only per-edge pinline detail is
# unavailable. Checked before any (border_color, frame) lookup so a future calibration entry
# for one specific borderless era could never accidentally re-enable it for the others.
_STRUCTURALLY_UNUSABLE_BORDER_COLORS = frozenset({"borderless"})


def _method_a_bleed_mm(evidence: ImageEvidence) -> Optional[float]:
    """Recovers Method A's own bleed value from the already-persisted `bleed_diff_mm`
    (`local_fallback.compute_bleed_diff_mm`, PROTECTED CORE - imported and read, never
    re-derived). `None` when that extractor itself abstained (image aspect ratio too far from
    both the trim-exact and standard-bleed reference ratios to classify confidently) - the same
    "genuinely non-standard image" outcome `classify_bleed_edge` documents."""
    if evidence.bleed_diff_mm is None:
        return None
    return round(BLEED_MARGIN_MM - evidence.bleed_diff_mm, 4)


def _resolve_frame_class(card: Card) -> Optional[tuple[str, str]]:
    """`(border_color, frame)` for `card`'s resolved canonical printing, or `None` if unresolved.
    Reuses the SAME `canonical_card or inferred_canonical_card` fallback
    `printing_candidates.get_ranked_printing_candidates` already establishes for "the printing
    this card is currently linked to" - not re-derived, so this module's frame-class reading can
    never silently drift from what the rest of the codebase already treats as the linked
    printing."""
    linked = card.canonical_card or card.inferred_canonical_card
    if linked is None:
        return None
    metadata = CanonicalPrintingMetadata.objects.filter(canonical_card=linked).first()
    if metadata is None or not metadata.border_color or not metadata.frame:
        return None
    return metadata.border_color, metadata.frame


def _pinline_edge_bleed_mm(
    evidence: ImageEvidence, constants: dict[str, Optional[float]]
) -> dict[str, Optional[float]]:
    """Method B, per edge. `px_per_mm` is derived ONCE per card from whichever axis has both
    opposite edges usable (left/right preferred, top/bottom fallback - module docstring's SCALE
    section); each edge's own bleed is then computed from its own frac/constant alone, so an
    edge whose partner is abstained (e.g. 2015-frame bottom, paired with a usable top) still
    reports independently. Returns all-`None` when no axis can supply a scale at all."""
    fracs = {
        "top": evidence.pinline_inset_frac_top,
        "bottom": evidence.pinline_inset_frac_bottom,
        "left": evidence.pinline_inset_frac_left,
        "right": evidence.pinline_inset_frac_right,
    }
    calls = {
        "top": evidence.pinline_inset_call_top,
        "bottom": evidence.pinline_inset_call_bottom,
        "left": evidence.pinline_inset_call_left,
        "right": evidence.pinline_inset_call_right,
    }

    def _usable_pair(near: str, far: str) -> Optional[tuple[float, float, float, float]]:
        """`(near_frac, far_frac, near_const, far_const)` when both edges are usable, else
        `None` - a single narrowing point so mypy can see every value is a real `float` past it,
        rather than re-deriving `Optional`-ness from three separate dict lookups per call site."""
        near_frac, far_frac = fracs[near], fracs[far]
        near_const, far_const = constants.get(near), constants.get(far)
        if (
            near_frac is None
            or far_frac is None
            or calls[near] != CALL_MEASURED
            or calls[far] != CALL_MEASURED
            or near_const is None
            or far_const is None
        ):
            return None
        return near_frac, far_frac, near_const, far_const

    width, height = evidence.width, evidence.height
    px_per_mm: Optional[float] = None
    horizontal = _usable_pair("left", "right")
    if width and horizontal is not None:
        left_frac, right_frac, left_const, right_const = horizontal
        span_px = width * (1.0 - left_frac - right_frac)
        span_mm = CARD_TRIM_WIDTH_MM - left_const - right_const
        if span_px > 0 and span_mm > 0:
            px_per_mm = span_px / span_mm
    vertical = _usable_pair("top", "bottom")
    if px_per_mm is None and height and vertical is not None:
        top_frac, bottom_frac, top_const, bottom_const = vertical
        span_px = height * (1.0 - top_frac - bottom_frac)
        span_mm = CARD_TRIM_HEIGHT_MM - top_const - bottom_const
        if span_px > 0 and span_mm > 0:
            px_per_mm = span_px / span_mm

    if px_per_mm is None:
        return {edge: None for edge in _EDGE_NAMES}

    result: dict[str, Optional[float]] = {}
    for edge in _EDGE_NAMES:
        edge_frac = fracs[edge]
        edge_const = constants.get(edge)
        if edge_frac is None or calls[edge] != CALL_MEASURED or edge_const is None:
            result[edge] = None
            continue
        walk_dim = height if edge in ("top", "bottom") else width
        if walk_dim is None:
            result[edge] = None
            continue
        edge_px = edge_frac * walk_dim
        result[edge] = round(edge_px / px_per_mm - edge_const, 4)
    return result


def _method_b_bleed_mm(card: Card, evidence: ImageEvidence) -> dict[str, Optional[float]]:
    """Method B's entry point: resolves the card's frame class, honours the structural
    borderless abstention and the calibration table's own per-edge `None` abstain flags, and
    delegates the actual per-edge arithmetic to `_pinline_edge_bleed_mm`. Returns all-`None`
    whenever Method B does not apply at all (no `pinline_inset` extractor run, no resolved
    canonical, borderless, or no calibration entry for this card's frame class)."""
    if "pinline_inset" not in evidence.extractor_versions:
        return {edge: None for edge in _EDGE_NAMES}
    frame_class = _resolve_frame_class(card)
    if frame_class is None:
        return {edge: None for edge in _EDGE_NAMES}
    border_color, frame_era = frame_class
    if border_color in _STRUCTURALLY_UNUSABLE_BORDER_COLORS:
        return {edge: None for edge in _EDGE_NAMES}
    constants = CALIBRATED_PINLINE_INSET_MM.get((border_color, frame_era))
    if constants is None:
        return {edge: None for edge in _EDGE_NAMES}
    return _pinline_edge_bleed_mm(evidence, constants)


# THIS CALCULATOR'S OWN SKIP VOCABULARY (docs/reference/skip-reasons.md's declaration
# convention). Every string written to `CardScanLog.skip_reason` here is a module-level
# `BLEED_CALC_*_SKIP_REASON` constant. The `BLEED_CALC_` prefix is deliberate: `ambiguous` in
# particular is also emitted by other calculators under a different `anonymous_id`, and a shared
# bare constant would falsely imply one shared concept.
BLEED_CALC_NO_EVIDENCE_SKIP_REASON = "no-evidence"
BLEED_CALC_INCOMPLETE_EVIDENCE_SKIP_REASON = "incomplete-evidence"
# Neither method produced a number at all (Method A's own aspect-ratio classification abstained,
# AND Method B never applied) - genuinely nothing to vote from.
BLEED_CALC_AMBIGUOUS_SKIP_REASON = "ambiguous"
# The abstain gate itself (module docstring): both methods produced a number
# and they disagree by more than METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM.
BLEED_CALC_METHOD_DISAGREEMENT_SKIP_REASON = "method-disagreement"
# A bleed value WAS produced (by one or both methods, agreeing where both applied) but this
# card's own Stage C bleed_class is not "trimmed" - the ordinary ~97.5% case. Negative-only
# convention, same as cast_bleed_edge_vote's own documented "absence of a vote is normal" meaning.
BLEED_CALC_NOT_TRIMMED_SKIP_REASON = "not-trimmed"

# Same convention as LAYOUT_CLASS_RESCANNABLE_SKIP_REASONS: both describe a transient "nothing to
# look at YET" state a later Stage C pass can change. The other three are permanent conclusions
# against this content_hash's current stored evidence (and, for method-disagreement, this card's
# current canonical resolution) - not rescannable until that evidence itself changes, which the
# idempotence query's `current_evidence_queryset`/content_hash keying already re-admits.
BLEED_CALC_RESCANNABLE_SKIP_REASONS = frozenset(
    {BLEED_CALC_NO_EVIDENCE_SKIP_REASON, BLEED_CALC_INCOMPLETE_EVIDENCE_SKIP_REASON}
)


@dataclass(frozen=True)
class BleedCalculatorVerdict:
    """Pure result of reading one card's current `ImageEvidence` (+ its resolved canonical's
    `CanonicalPrintingMetadata`, for Method B) - no DB write has happened yet, mirroring
    `LayoutClassVerdict`/`AttributeChipVerdict`'s own compute/persist split."""

    card_id: int
    method_a_mm: Optional[float] = None
    method_b_edges_mm: dict[str, Optional[float]] = field(default_factory=dict)
    method_b_mean_mm: Optional[float] = None
    tag_name: Optional[str] = None
    confidence: Optional[float] = None
    skip_reason: Optional[str] = None

    @property
    def is_hit(self) -> bool:
        return self.tag_name is not None


def calculate_bleed_verdict(card: Card, evidence: ImageEvidence) -> BleedCalculatorVerdict:
    """The bleed calculator. Pure function: no DB write, no image fetch, no re-classification -
    Method A reads `evidence.bleed_diff_mm` (already computed at Stage C); Method B reads
    `evidence.pinline_inset_*` plus `card`'s resolved canonical's `CanonicalPrintingMetadata`.
    See module docstring for the abstain gate and confidence-tier derivation this function
    implements."""
    method_a_mm = _method_a_bleed_mm(evidence)
    method_b_edges = _method_b_bleed_mm(card, evidence)
    measured_b = [v for v in method_b_edges.values() if v is not None]
    method_b_mean_mm = round(mean(measured_b), 4) if measured_b else None

    if method_a_mm is None and method_b_mean_mm is None:
        return BleedCalculatorVerdict(
            card_id=card.pk,
            method_a_mm=None,
            method_b_edges_mm=method_b_edges,
            method_b_mean_mm=None,
            skip_reason=BLEED_CALC_AMBIGUOUS_SKIP_REASON,
        )

    if method_a_mm is not None and method_b_mean_mm is not None:
        if abs(method_a_mm - method_b_mean_mm) > METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM:
            return BleedCalculatorVerdict(
                card_id=card.pk,
                method_a_mm=method_a_mm,
                method_b_edges_mm=method_b_edges,
                method_b_mean_mm=method_b_mean_mm,
                skip_reason=BLEED_CALC_METHOD_DISAGREEMENT_SKIP_REASON,
            )
        confidence = FALLBACK_CONFIDENCE_MULTI_EVIDENCE
    else:
        confidence = FALLBACK_CONFIDENCE_SINGLE_EVIDENCE

    if evidence.bleed_class != "trimmed":
        return BleedCalculatorVerdict(
            card_id=card.pk,
            method_a_mm=method_a_mm,
            method_b_edges_mm=method_b_edges,
            method_b_mean_mm=method_b_mean_mm,
            skip_reason=BLEED_CALC_NOT_TRIMMED_SKIP_REASON,
        )

    return BleedCalculatorVerdict(
        card_id=card.pk,
        method_a_mm=method_a_mm,
        method_b_edges_mm=method_b_edges,
        method_b_mean_mm=method_b_mean_mm,
        tag_name=BLEED_EDGE_TAG_NAME,
        confidence=confidence,
    )


@dataclass
class BleedCalculatorCastResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)
    audit: list[dict[str, object]] = field(default_factory=list)


def _eligible_cards_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """Every card not already voted on by this calculator's own identity, and not already
    carrying a non-rescannable `CardScanLog` row from a prior invocation - the same
    `LAYOUT_CLASS_CAST_ANONYMOUS_ID`-shaped idempotence pattern `local_layout_class_cast.
    _eligible_cards_queryset` establishes, including its `card_ids` push-down into BOTH the outer
    query and the `CardScanLog` subquery (issue #469/#533 - see that function's own docstring for
    why the subquery push matters at 2M+ rows). Deliberately unrestricted by
    `card_type`/`printing_tag_status` - bleed is orthogonal to printing identification, same
    reasoning every sibling caster in this family gives for its own chip."""
    non_rescannable_scanned_card_ids_qs = CardScanLog.objects.filter(
        anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID
    ).exclude(skip_reason__in=BLEED_CALC_RESCANNABLE_SKIP_REASONS)
    if card_ids is not None:
        non_rescannable_scanned_card_ids_qs = non_rescannable_scanned_card_ids_qs.filter(card_id__in=card_ids)
    non_rescannable_scanned_card_ids = non_rescannable_scanned_card_ids_qs.values_list("card_id", flat=True)
    queryset = (
        Card.objects.exclude(tag_votes__anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned_card_ids)
        .distinct()
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def run_bleed_calculator_cast(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
    card_ids: Optional[Iterable[int]] = None,
) -> BleedCalculatorCastResult:
    """Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row that
    has completed the `geometry_bleed` extractor (`REQUIRED_EXTRACTOR_KEYS`). `dry_run=True`
    (the default, matching every other Stage 3+ command's opt-in-to-write convention) computes
    and counts everything without writing any `CardTagVote`/`CardScanLog` row. Gate verification
    (`purge_machine_votes.verify_no_machine_only_resolutions`) lives in the management command,
    matching `run_layout_class_cast`/`run_attribute_chip_cast`'s own split."""
    run_id = run_id or generate_run_id()
    result = BleedCalculatorCastResult(dry_run=dry_run, run_id=run_id)

    tag = Tag.objects.filter(name=BLEED_EDGE_TAG_NAME).first()
    if tag is None:
        raise RuntimeError(
            f"Tag '{BLEED_EDGE_TAG_NAME}' does not exist yet - run `seed_attribute_tags`/"
            "`seed_default_tags` before this calculator."
        )

    votes_batch: list[CardTagVote] = []
    scan_log_batch: list[CardScanLog] = []

    def _skip(card_id: int, reason: str) -> None:
        result.skip_counts[reason] = result.skip_counts.get(reason, 0) + 1
        if not dry_run:
            scan_log_batch.append(
                CardScanLog(
                    card_id=card_id, anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID, run_id=run_id, skip_reason=reason
                )
            )

    for card in _eligible_cards_queryset(card_ids=card_ids).iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = current_evidence_queryset(card).order_by("-updated_at").first()
        if evidence is None:
            _skip(card.pk, BLEED_CALC_NO_EVIDENCE_SKIP_REASON)
            continue

        if any(key not in evidence.extractor_versions for key in REQUIRED_EXTRACTOR_KEYS):
            _skip(card.pk, BLEED_CALC_INCOMPLETE_EVIDENCE_SKIP_REASON)
            continue

        result.cards_considered += 1
        verdict = calculate_bleed_verdict(card, evidence)

        if not verdict.is_hit:
            assert verdict.skip_reason is not None
            _skip(card.pk, verdict.skip_reason)
            continue

        result.votes_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append(
                {
                    "card_id": card.pk,
                    "method_a_mm": verdict.method_a_mm,
                    "method_b_mean_mm": verdict.method_b_mean_mm,
                    "confidence": verdict.confidence,
                }
            )

        if not dry_run:
            assert verdict.tag_name is not None  # is_hit already checked this
            votes_batch.append(
                CardTagVote(
                    card_id=card.pk,
                    tag=tag,
                    polarity=VotePolarity.NOT_APPLICABLE,
                    anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID,
                    source=VoteSource.OCR,
                    confidence=verdict.confidence,
                    run_id=run_id,
                )
            )

    if not dry_run:
        purge_and_write_votes(
            CardTagVote,
            votes_batch,
            anonymous_id=BLEED_CALCULATOR_CAST_ANONYMOUS_ID,
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
    "BLEED_CALCULATOR_CAST_ANONYMOUS_ID",
    "REQUIRED_EXTRACTOR_KEYS",
    "BLEED_MARGIN_MM",
    "CARD_TRIM_WIDTH_MM",
    "CARD_TRIM_HEIGHT_MM",
    "METHOD_DISAGREEMENT_ABSTAIN_THRESHOLD_MM",
    "CALIBRATED_PINLINE_INSET_MM",
    "BLEED_CALC_NO_EVIDENCE_SKIP_REASON",
    "BLEED_CALC_INCOMPLETE_EVIDENCE_SKIP_REASON",
    "BLEED_CALC_AMBIGUOUS_SKIP_REASON",
    "BLEED_CALC_METHOD_DISAGREEMENT_SKIP_REASON",
    "BLEED_CALC_NOT_TRIMMED_SKIP_REASON",
    "BLEED_CALC_RESCANNABLE_SKIP_REASONS",
    "BleedCalculatorVerdict",
    "calculate_bleed_verdict",
    "BleedCalculatorCastResult",
    "run_bleed_calculator_cast",
]
