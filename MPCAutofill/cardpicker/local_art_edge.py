"""
Art-edge continuity - the EXTENDED-ART channel.

Owner-directed design (2026-07-28): "we can measure by aiming our border pixel color measurement
at two locations, one of which is adjacent to the art crop location."

SELF-REFERENTIAL REDESIGN (issue #830 defect 3), superseding the 2026-08-06 retune
(docs/reports/2026-08-06-art-edge-relative-comparison.md). That retune compared the art-adjacent
strip against `ImageEvidence.layout_class` (`classify_border_color`'s own output) and measured
0/30 recall on Scryfall's own extended-art images - worse than the original 1/30. Two upstream
causes, both traced in that report: `classify_border_color`'s pooled-uniformity test misread 20 of
30 genuine extended-art images as `"borderless"` before this classifier ever ran (fixed here by
issue #830 defect 2, `local_fallback.classify_border_color`'s own per-band evaluation); and the
edge band it fed `layout_class` on collapsed to ~1-2px on a trim-exact image regardless of
resolution (fixed here by issue #830 defect 1, `local_fallback.project_mm_box_to_fractions`).

Rather than re-validate the old `layout_class`-dependent design against those two fixes, this
module now compares THREE regions, ALL FROM THE SAME IMAGE, and never calls
`classify_border_color` or consumes `layout_class` at all:

  - TEST     - the strip immediately beside the art crop (left and right), over the art's own
               vertical span - the module's pre-existing `adjacent_boxes` geometry, unchanged.
  - REFERENCE A - the same left/right x-zones, one art-span's height BELOW the art crop (level
               with the card's own rules-text box) - a second sample of "what colour is beside
               the art" that needs no external classification to interpret.
  - REFERENCE B - the top band (`local_fallback._BORDER_SAMPLE_BANDS_MM["top"]`), projected via
               `project_mm_box_to_fractions` - a region that is reliably border, never art, on
               every card this classifier can reach a verdict on.

`extended` iff the test strip differs from BOTH references (art reaches all the way to the
side); `framed` iff it matches BOTH (a real border survives beside the art); `mixed` when it
matches one but not the other - a genuinely ambiguous reading, not collapsed into either verdict.
Measured on Scryfall's own labelled cohorts (30 extended-art, 20 borderless, 20 ordinary framed,
at real Scryfall render resolutions - see this PR's own report): recall and false-positive rates
are reported in that report rather than restated here, since a number copied into a docstring
goes stale the moment the code it describes changes and nothing re-checks it.

WHY SELF-REFERENTIAL BEATS A layout_class-DEPENDENT DESIGN, EVEN AFTER DEFECTS 1 AND 2: comparing
against `layout_class` still asks a SINGLE stored classification (computed once, from bands that
may themselves be marginal) to carry the whole "is there a border here" judgement. Comparing the
test strip against a SECOND direct sample of this same image (Reference A, immediately below the
art) needs no intermediate classification to fail in-between - the two samples either match or
they don't, read fresh, every time.

WHY THIS IS ITS OWN MODULE AND NOT A NEW VALUE IN `local_fallback.BORDER_COLOR_TO_TAG`. Measured
read-only against production (2026-07-28): all **4,165** printings whose Scryfall `frame_effects`
contains `extendedart` have `border_color == "black"` - 4,165 of 4,165, with **zero** overlap onto
`border_color == "borderless"`. An extended-art card is black-bordered AND extended, both at once.
`classify_border_color` returns ONE value, so it structurally cannot say both, and adding an
"extendedart" member to its closed value space would force a false either/or on every one of those
4,165 rows. Extended art is a FRAME property, not a border colour.

That is also why this does not live beside `local_fallback.classify_frame_style`: that classifier
is TEXT-derived (collector-number parsing, "Illus." anchor) and answers a different question
(which frame ERA - old/modern/future). This one is pixel-derived and answers "how far does the
artwork spread?". Different evidence, different question, different channel.

TWO TRACKS, AND WHICH ONE THIS SERVES. For OFFICIAL printings nothing here is needed: Scryfall's
`frame_effects` already carries `extendedart` as an imported fact (4,165 printings), and an
imported fact is not a disputable claim that wants a pixel vote. This module exists for the OTHER
track - USER-UPLOADED PROXY IMAGES, where pixels are the only source and there is no printing to
read the fact off. That is what the local-fallback channel is for.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Optional

from django.db.models import QuerySet

from cardpicker.local_fallback import (
    _BORDER_SAMPLE_BANDS_MM,
    _sample_band,
    project_mm_box_to_fractions,
)
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import (
    Card,
    CardScanLog,
    CardTagVote,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.vote_write import purge_and_write_votes

if TYPE_CHECKING:
    from PIL import Image

# Its own calculator identity rather than borrowing `local_fallback.FALLBACK_ANONYMOUS_ID`: this
# is a different reading, of a different property, with its own failure modes, and a shared
# identity would make its votes indistinguishable from the border sample's in every audit that
# groups by `anonymous_id`. Declared before it went live on purpose - the same reasoning
# `local_fallback`'s skip-reason block gives for declaring constants ahead of first write, so the
# docs_lint roster tether could see it before it started producing rows. Issue #721's own gate
# (the catalog-specific question of whether this classifier is accurate enough on the real
# uploaded images already here to justify wiring the vote) cleared 2026-08-19, and this channel
# has been wired and voting since - its docs/pipeline-fidelity-gate.md calculator roster entry
# now records that.
ART_EDGE_ANONYMOUS_ID = "art-edge-continuity-v1"

# A PRE-EXISTING tag: "Extended" is already a `default_tags.DEFAULT_TAGS` row and already listed
# in `attribute_tags.ATTRIBUTE_CHIP_TAG_NAMES`. This channel therefore seeds NOTHING new and
# needs no owner seeding action in production - unlike a gold/yellow border tag, which would.
ART_EDGE_CONTINUITY_TAG_NAME = "Extended"
ART_EDGE_VOTE_CONFIDENCE = 0.7  # heuristic tier, matching the frame-style sample's own

ART_EDGE_FRAMED = "framed"
ART_EDGE_EXTENDED = "extended"
ART_EDGE_MIXED = "mixed"  # the test strip matches exactly one of the two references, not both

# The full closed value space, enumerated so callers branching on it have something to check
# membership against rather than restating three string literals.
ART_EDGE_CLASSES: tuple[str, ...] = (ART_EDGE_FRAMED, ART_EDGE_EXTENDED, ART_EDGE_MIXED)

# COLOUR-DISTANCE MEASURE: plain Euclidean distance between two `_sample_band` mean-RGB triples.
# Euclidean RGB is not perceptually uniform (a fixed numeric distance is not a fixed PERCEIVED
# difference everywhere in the space), and it is weakest exactly where two colours are both
# desaturated and differ mainly in a way human vision weights unevenly - measured directly against
# this cohort (this PR's own report): every one of the 10 undetected extended-art cards fails
# because its art-adjacent strip is dark/desaturated, within Euclidean reach of an equally dark
# reference. A perceptually-corrected metric (Lab-space, CIEDE2000) would likely rescue some of
# those, at the cost of a colour-space conversion this codebase performs nowhere else - flagged as
# this constant's own follow-up, not built speculatively now on no evidence it is the next-best
# lever. 70.0 sits at the pre-stated operating point this PR's report measures against (the
# module's own pre-existing validated value); the same report's threshold sweep shows the
# borderless false-positive/recall tradeoff at other values, for whoever picks up that follow-up.
_ART_EDGE_COLOR_DISTANCE_THRESHOLD = 70.0


def _mean_rgb_over_boxes(
    card_image: "Image.Image", boxes: Sequence[tuple[float, float, float, float]]
) -> Optional[tuple[float, float, float]]:
    """Mean RGB across every box in `boxes` that sampled successfully (each box's OWN mean,
    averaged together - not a pixel-weighted pool), or None if none did. Shared by every region
    this module samples (TEST/Reference A are two boxes each - left and right; Reference B is
    one), so a card whose left or right strip alone hits a degenerate crop still gets a reading
    from whichever side did sample, rather than losing the whole region."""
    means = [sampled[0] for sampled in (_sample_band(card_image, box) for box in boxes) if sampled is not None]
    if not means:
        return None
    r, g, b = (statistics.mean(m[channel] for m in means) for channel in range(3))
    return r, g, b


def _euclidean_rgb_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def classify_art_edge_continuity(
    card_image: "Image.Image",
    art_crop_px: Optional[Sequence[int]],
) -> Optional[str]:
    """Returns 'framed' / 'extended' / 'mixed', or None when the reading is unusable (a
    degenerate `art_crop_px`, or any of the three regions this classifier needs failed to sample
    - see module docstring). This function only classifies; `cast_art_edge_continuity_vote` is
    what casts the vote, wired since Issue #721's own gate cleared 2026-08-19 (see that
    function's own docstring for the measurement).

      'framed'   - the art-adjacent strip's colour matches BOTH references (Reference A, the
                   same x-zones below the art; Reference B, the top band) - a real border
                   survives beside the art.
      'extended' - the art-adjacent strip matches NEITHER reference - artwork reaches the
                   card's edge. Scryfall's `frame_effects` "extendedart".
      'mixed'    - the art-adjacent strip matches exactly one reference but not the other - a
                   genuinely ambiguous within-image reading, reported rather than forced into
                   either verdict.
      None       - `art_crop_px` is missing/degenerate, or the test strip / Reference A /
                   Reference B could not be sampled (see `_mean_rgb_over_boxes`/
                   `project_mm_box_to_fractions`'s own abstention conventions). Abstaining is the
                   honest output; the alternative is inventing a comparison against a region
                   nobody actually measured.

    `art_crop_px` is `ImageEvidence.art_crop_px` verbatim - already remapped absolute pixels in
    THIS image's own space (`image_evidence._crop_box_to_pixels` applies
    `local_fallback.normalize_crop_box` for that row's own `bleed_class` before scaling out to
    pixels - see that field's own model comment). Dividing by `card_image`'s own width/height
    recovers fractions that are already correct for this image; this function does not re-remap
    them - a second remap would apply the trimmed-image correction twice and walk the region off
    the art (the same hazard the pre-redesign module's own COORDINATE FRAMES note documented,
    still true here since `art_crop_px`'s own derivation is unchanged by this PR - see
    `docs/features/...`/issue #830's own "do NOT convert the four main crop boxes" scope note).

    `art_crop_px` is preferred over `artbox_crop_px` deliberately: measured 2026-07-28, the
    former is populated on 220,579 of 220,579 `ImageEvidence` rows (100%) and the latter on
    64.6%, and this classifier has no fallback reading without one.
    """
    width, height = card_image.size
    if width <= 0 or height <= 0:
        return None
    if not art_crop_px or len(art_crop_px) != 4:
        return None
    art_left_px, art_top_px, art_right_px, art_bottom_px = art_crop_px
    art_left, art_right = art_left_px / width, art_right_px / width
    art_top, art_bottom = art_top_px / height, art_bottom_px / height
    if not (0 <= art_left < art_right <= 1) or not (0 <= art_top < art_bottom <= 1):
        return None

    # The left/right edge bands, projected the same mm-relative way `classify_border_color`
    # projects them (issue #830 defect 1) - used ONLY as an outer bound for the TEST/Reference-A
    # strips below, never as a colour reference in their own right (this design never compares
    # against a border-band colour - see module docstring). A card whose edge bands don't
    # project (rare - see `project_mm_box_to_fractions`'s own MIN_USABLE_BAND_PX refusal) falls
    # back to the art's own edge as the outer bound instead of an additional clamp.
    left_edge_box = project_mm_box_to_fractions(_BORDER_SAMPLE_BANDS_MM["left"], card_image)
    right_edge_box = project_mm_box_to_fractions(_BORDER_SAMPLE_BANDS_MM["right"], card_image)
    left_gap_outer = min(left_edge_box[2], art_left) if left_edge_box is not None else art_left
    right_gap_outer = max(right_edge_box[0], art_right) if right_edge_box is not None else art_right

    test_boxes = [
        (left_gap_outer, art_top, art_left, art_bottom),
        (art_right, art_top, right_gap_outer, art_bottom),
    ]
    # Reference A: the same x-zones, one art-span's height below the art crop - level with the
    # card's own rules-text box, mirroring the art's own vertical extent so both regions cover
    # the same amount of card.
    art_span = art_bottom - art_top
    reference_a_bottom = min(1.0, art_bottom + art_span)
    reference_a_boxes = [
        (left_gap_outer, art_bottom, art_left, reference_a_bottom),
        (art_right, art_bottom, right_gap_outer, reference_a_bottom),
    ]
    reference_b_box = project_mm_box_to_fractions(_BORDER_SAMPLE_BANDS_MM["top"], card_image)

    test_rgb = _mean_rgb_over_boxes(card_image, test_boxes)
    reference_a_rgb = _mean_rgb_over_boxes(card_image, reference_a_boxes)
    reference_b_rgb = None if reference_b_box is None else _mean_rgb_over_boxes(card_image, [reference_b_box])
    if test_rgb is None or reference_a_rgb is None or reference_b_rgb is None:
        return None

    distance_a = _euclidean_rgb_distance(test_rgb, reference_a_rgb)
    distance_b = _euclidean_rgb_distance(test_rgb, reference_b_rgb)
    matches_a = distance_a < _ART_EDGE_COLOR_DISTANCE_THRESHOLD
    matches_b = distance_b < _ART_EDGE_COLOR_DISTANCE_THRESHOLD

    if matches_a and matches_b:
        return ART_EDGE_FRAMED
    if not matches_a and not matches_b:
        return ART_EDGE_EXTENDED
    return ART_EDGE_MIXED


def cast_art_edge_continuity_vote(
    card: Card,
    art_edge_class: Optional[str],
    confidence: float = ART_EDGE_VOTE_CONFIDENCE,
    run_id: Optional[str] = None,
) -> Optional[CardTagVote]:
    """An unsaved `CardTagVote` applying the pre-existing "Extended" tag, or None.

    ONLY the 'extended' reading votes. 'framed' and 'mixed' are deliberately silent rather than
    casting a negative "Extended" vote: a negative vote from an unvalidated class is a claim, not
    an abstention, and 'mixed' is by definition the class this classifier is least sure of.

    WIRED, via `run_art_edge_continuity_cast` below - called from `stage_e_dispatch.
    _run_evidence_only_calculators` (the streaming conveyor) and the standalone
    `local_art_edge_cast` management command. Issue #721's validation precondition was measured
    against real catalog images (2026-08-19, read-only) before this vote was wired. Scryfall
    printing `frame_effects`/`border_color` turned out not to be usable ground truth for it - a
    printing match describes which artwork the image DEPICTS, not whether the uploader reproduced
    that printing's frame treatment (see docs/pipeline-fidelity-gate.md's calculator roster and
    the 2026-08-19 addendum to docs/reference/self-referential-reasoning.md for the full
    measurement and the general lesson). Against ground truth that does describe the uploaded
    image instead: human votes on the pre-existing "Extended" attribute chip give recall 87.0%
    (20/23), false positives 0.0% (0/10), precision 100% (20/20), n=33 cards / 5 voters, 0
    disputed; uploader-declared filenames corroborate at much larger n, 90.7% agreement over
    n=13,117, holding per-source across every uploader with n>=15. That evidence is the basis for
    wiring this vote; the remaining limit is sample size on the human-vote channel (n=33) - a
    channel that grows on its own as people vote the existing chip, needing no new mechanism to
    enlarge it.
    """
    if art_edge_class != ART_EDGE_EXTENDED:
        return None
    tag = Tag.objects.filter(name=ART_EDGE_CONTINUITY_TAG_NAME).first()
    if tag is None:
        return None
    return CardTagVote(
        card=card,
        tag=tag,
        polarity=VotePolarity.APPLY,
        anonymous_id=ART_EDGE_ANONYMOUS_ID,
        source=VoteSource.OCR,
        confidence=confidence,
        run_id=run_id,
    )


# THIS CASTER'S OWN SKIP VOCABULARY (docs/reference/skip-reasons.md's declaration convention).
# Every string written to `CardScanLog.skip_reason` by `run_art_edge_continuity_cast` is one of
# these module-level `ART_EDGE_*_SKIP_REASON` constants, own-prefixed the same way
# `local_bleed_calculator.BLEED_CALC_*_SKIP_REASON` is - a shared bare "no-evidence" would
# collide with every other calculator's own use of that word under a different `anonymous_id`.
ART_EDGE_NO_EVIDENCE_SKIP_REASON = "no-evidence"  # no CURRENT ImageEvidence row for this card
# `art_edge_class` is blank - `local_fallback`'s "same blank-string-as-sentinel convention...
# for the ambiguous/not-yet-run case" applies here exactly as it does to layout_class/bleed_class
# (models.py's own field comment): this covers BOTH "the art_edge extractor group has not run
# against this evidence yet" and "it ran and `classify_art_edge_continuity` abstained" - the
# stored column cannot distinguish the two, and neither needs a different vote outcome (both are
# "nothing to vote from").
ART_EDGE_NO_READING_SKIP_REASON = "no-reading"
# A reading WAS stored, but it isn't 'extended' - see `cast_art_edge_continuity_vote`'s own
# docstring for why 'framed'/'mixed' abstain rather than cast a negative. Split into two distinct
# reasons (not one shared "not-extended") so a CardScanLog audit can tell which population is
# which - 'framed' is ~4.4x the size of 'mixed' in production and behaves very differently
# (0.0% measured false-positive rate vs. "by definition the class this classifier is least sure
# of").
ART_EDGE_FRAMED_SKIP_REASON = "framed"
ART_EDGE_MIXED_SKIP_REASON = "mixed"

# Same convention as `BLEED_CALC_RESCANNABLE_SKIP_REASONS`: describes a transient "nothing to
# look at YET" state a later Stage C pass can change (no evidence row at all, or the art_edge
# extractor hasn't produced a usable reading for this evidence yet). A stored 'framed'/'mixed'
# reading is a permanent conclusion against this content_hash's current evidence and is not
# rescannable until that evidence itself changes - which a fresh `current_evidence_queryset`
# lookup already re-admits, since it re-reads live evidence every call rather than trusting the
# scan-log row's own age.
ART_EDGE_RESCANNABLE_SKIP_REASONS = frozenset({ART_EDGE_NO_EVIDENCE_SKIP_REASON, ART_EDGE_NO_READING_SKIP_REASON})


@dataclass
class ArtEdgeCastResult:
    dry_run: bool = False
    run_id: str = ""
    cards_considered: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    skip_counts: dict[str, int] = field(default_factory=dict)


def _eligible_cards_queryset(card_ids: Optional[Iterable[int]] = None) -> "QuerySet[Card]":
    """Every card not already voted on by this caster's own identity, and not already carrying a
    non-rescannable `CardScanLog` row from a prior invocation - the same
    `BLEED_CALCULATOR_CAST_ANONYMOUS_ID`-shaped idempotence pattern
    `local_bleed_calculator._eligible_cards_queryset` establishes, including its `card_ids`
    push-down into BOTH the outer query and the `CardScanLog` subquery (issue #469/#533 - see
    that function's own docstring for why the subquery push matters at 2M+ rows). Deliberately
    unrestricted by `card_type`/`printing_tag_status` - frame treatment is orthogonal to printing
    identification, same reasoning every sibling caster in this family gives for its own chip."""
    non_rescannable_scanned_card_ids_qs = CardScanLog.objects.filter(anonymous_id=ART_EDGE_ANONYMOUS_ID).exclude(
        skip_reason__in=ART_EDGE_RESCANNABLE_SKIP_REASONS
    )
    if card_ids is not None:
        non_rescannable_scanned_card_ids_qs = non_rescannable_scanned_card_ids_qs.filter(card_id__in=card_ids)
    non_rescannable_scanned_card_ids = non_rescannable_scanned_card_ids_qs.values_list("card_id", flat=True)
    queryset = (
        Card.objects.exclude(tag_votes__anonymous_id=ART_EDGE_ANONYMOUS_ID)
        .exclude(pk__in=non_rescannable_scanned_card_ids)
        .distinct()
    )
    if card_ids is not None:
        queryset = queryset.filter(pk__in=card_ids)
    return queryset


def run_art_edge_continuity_cast(
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    card_ids: Optional[Iterable[int]] = None,
) -> ArtEdgeCastResult:
    """Batch runner over every currently-eligible card with a CURRENT `ImageEvidence` row -
    reads the already-persisted `art_edge_class` column and calls `cast_art_edge_continuity_vote`
    on it; fetches no image, runs no OCR, calls no external API (the column is populated entirely
    by Stage C's `image_evidence.extract_card_evidence`). `dry_run=True` (the default, matching
    every other Stage 3+ command's own opt-in-to-write convention) computes and counts everything
    without writing any `CardTagVote`/`CardScanLog` row.

    `current_evidence_queryset` is imported inside this function rather than at module scope:
    `image_evidence.py` itself imports `classify_art_edge_continuity` from this module at its own
    top level, so a top-level import the other way would be a circular import between the two
    modules - the same reason `stage_e_dispatch._run_evidence_only_calculators` imports its own
    sibling calculators lazily, inside the function, rather than at the top of that file."""
    from cardpicker.image_evidence import current_evidence_queryset

    run_id = run_id or generate_run_id()
    result = ArtEdgeCastResult(dry_run=dry_run, run_id=run_id)

    tag = Tag.objects.filter(name=ART_EDGE_CONTINUITY_TAG_NAME).first()
    if tag is None:
        raise RuntimeError(
            f"Tag '{ART_EDGE_CONTINUITY_TAG_NAME}' does not exist yet - run `seed_attribute_tags`/"
            "`seed_default_tags` before this caster."
        )

    votes_batch: list[CardTagVote] = []
    scan_log_batch: list[CardScanLog] = []

    def _skip(card_id: int, reason: str) -> None:
        result.skip_counts[reason] = result.skip_counts.get(reason, 0) + 1
        if not dry_run:
            scan_log_batch.append(
                CardScanLog(card_id=card_id, anonymous_id=ART_EDGE_ANONYMOUS_ID, run_id=run_id, skip_reason=reason)
            )

    for card in _eligible_cards_queryset(card_ids=card_ids).iterator(chunk_size=chunk_size):
        if card.content_phash is None:
            continue  # no stable hash yet to key a CURRENT ImageEvidence lookup against

        evidence = current_evidence_queryset(card).order_by("-updated_at").first()
        if evidence is None:
            _skip(card.pk, ART_EDGE_NO_EVIDENCE_SKIP_REASON)
            continue

        result.cards_considered += 1
        art_edge_class = evidence.art_edge_class or None

        if art_edge_class is None:
            _skip(card.pk, ART_EDGE_NO_READING_SKIP_REASON)
            continue
        if art_edge_class == ART_EDGE_FRAMED:
            _skip(card.pk, ART_EDGE_FRAMED_SKIP_REASON)
            continue
        if art_edge_class == ART_EDGE_MIXED:
            _skip(card.pk, ART_EDGE_MIXED_SKIP_REASON)
            continue

        result.votes_would_cast += 1
        if not dry_run:
            vote = cast_art_edge_continuity_vote(card, art_edge_class, run_id=run_id)
            assert vote is not None  # art_edge_class == ART_EDGE_EXTENDED, already checked above
            votes_batch.append(vote)

    if not dry_run:
        purge_and_write_votes(
            CardTagVote,
            votes_batch,
            anonymous_id=ART_EDGE_ANONYMOUS_ID,
            target_field="card_id",
            ignore_conflicts=True,
        )
        CardScanLog.objects.bulk_create(scan_log_batch)
        result.votes_written = len(votes_batch)

        touched_card_ids = [vote.card_id for vote in votes_batch]
        for touched_card in Card.objects.filter(pk__in=touched_card_ids):
            resolve_and_persist_tag_votes(touched_card)

    return result


__all__ = [
    "ART_EDGE_ANONYMOUS_ID",
    "ART_EDGE_CONTINUITY_TAG_NAME",
    "ART_EDGE_VOTE_CONFIDENCE",
    "ART_EDGE_FRAMED",
    "ART_EDGE_EXTENDED",
    "ART_EDGE_MIXED",
    "ART_EDGE_CLASSES",
    "ART_EDGE_NO_EVIDENCE_SKIP_REASON",
    "ART_EDGE_NO_READING_SKIP_REASON",
    "ART_EDGE_FRAMED_SKIP_REASON",
    "ART_EDGE_MIXED_SKIP_REASON",
    "ART_EDGE_RESCANNABLE_SKIP_REASONS",
    "ArtEdgeCastResult",
    "classify_art_edge_continuity",
    "cast_art_edge_continuity_vote",
    "run_art_edge_continuity_cast",
]
