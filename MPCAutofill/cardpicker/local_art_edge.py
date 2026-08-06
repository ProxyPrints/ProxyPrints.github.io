"""
Art-edge continuity - the EXTENDED-ART channel.

Owner-directed design (2026-07-28): "we can measure by aiming our border pixel color measurement
at two locations, one of which is adjacent to the art crop location."

RETUNED 2026-08-06 (docs/reports/2026-08-06-art-edge-relative-comparison.md has the full
before/after numbers). The original method compared each band's pixel variance against
`local_fallback._BORDER_UNIFORMITY_STD_THRESHOLD`, an ABSOLUTE constant tuned for
`classify_border_color`'s different question ("is this whole band a painted border at all").
Measured against 467 real catalogue images: `extended` fired on 7 of them, and every one of
those 7 edge-band reads was DARK (RGB like `(14,13,26)`) with a correspondingly compressed pixel
value range, and therefore a low absolute std - EXACTLY as low as a genuine painted border reads,
even though nothing painted was there. A fixed variance cut cannot tell "this band is flat because
it is a border" apart from "this band is flat because it is dark, and dark content has a narrower
value range than bright content by construction" - it was measuring darkness and reporting it as
a border.

THE FIX IS RELATIVE, NOT A RETUNED CONSTANT. Instead of asking "is this band uniform" in
isolation, this module now asks "does this band's COLOUR match the border colour THIS card is
already known to have" - a comparison entirely within one image, between two samples of that
same image. `ImageEvidence.layout_class` (`classify_border_color`'s own output - black / white /
silver / borderless) already tells us which case applies:

  * `layout_class == "borderless"` - there is no border for anything to match, and a card with no
    border cannot be extended-art by definition. `open`, decided from the stored classification
    alone, no sampling required.
  * otherwise - `layout_class` names a real border colour this exact image was already measured
    to have. Sample the art-adjacent strip's own colour and compare it against that same border,
    resampled from the same image, with a colour distance:
      - close to the border colour -> the frame survives beside the art -> `framed`.
      - far from the border colour -> something other than the border sits beside the art, and
        `layout_class` already established the outer edge itself reads as a real border ->
        `extended`.

This is why the second sample point is still taken (the module is not reduced to reading
`layout_class` alone): `layout_class` tells us WHAT colour a border would be, not whether the
strip immediately beside THIS card's own art crop is that colour or something else. But the
EDGE BAND's own uniformity is no longer re-tested here - `layout_class` being anything other than
`None`/`"borderless"` already means `classify_border_color` found that band uniform enough to
call a colour on its own, real-fetched-image-validated threshold. Re-testing it a second time
here, on the same pixels, would just be paying for the same measurement twice.

WHY A WITHIN-IMAGE COMPARISON SURVIVES WHAT AN ABSOLUTE ONE DOES NOT: overall image darkness,
exposure, scan quality and JPEG artefacts shift a sampled band's raw colour, but they shift the
border sample and the art-adjacent sample of the SAME image by roughly the same amount - a
washed-out scan reads both bands lighter, a underexposed one reads both bands darker. The
DIFFERENCE between the two samples is far more stable across those confounds than either sample's
absolute value is, which is exactly the discriminator a fixed threshold cannot use because it
only ever looks at one band at a time.

WHY THIS IS ITS OWN MODULE AND NOT A NEW VALUE IN `local_fallback.BORDER_COLOR_TO_TAG`.
Measured read-only against production (2026-07-28): all **4,165** printings whose Scryfall
`frame_effects` contains `extendedart` have `border_color == "black"` - 4,165 of 4,165, with
**zero** overlap onto `border_color == "borderless"`. An extended-art card is black-bordered AND
extended, both at once. `classify_border_color` returns ONE value, so it structurally cannot say
both, and adding an "extendedart" member to its closed value space would force a false either/or
on every one of those 4,165 rows. Extended art is a FRAME property, not a border colour.

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
from typing import TYPE_CHECKING, Optional

from cardpicker.local_fallback import (
    _BORDER_SAMPLE_BANDS,
    _sample_band,
    normalize_crop_box,
)
from cardpicker.models import Card, CardTagVote, Tag, VotePolarity, VoteSource

if TYPE_CHECKING:
    from PIL import Image

# Its own calculator identity rather than borrowing `local_fallback.FALLBACK_ANONYMOUS_ID`: this
# is a different reading, of a different property, with its own failure modes, and a shared
# identity would make its votes indistinguishable from the border sample's in every audit that
# groups by `anonymous_id`. Declared before it goes live on purpose - the same reasoning
# `local_fallback`'s skip-reason block gives for declaring constants ahead of first write, so the
# docs_lint roster tether can see it BEFORE it starts producing rows. It has an entry in
# docs/pipeline-fidelity-gate.md's calculator roster recording that it is declared-not-yet-live.
ART_EDGE_ANONYMOUS_ID = "art-edge-continuity-v1"

# A PRE-EXISTING tag: "Extended" is already a `default_tags.DEFAULT_TAGS` row and already listed
# in `attribute_tags.ATTRIBUTE_CHIP_TAG_NAMES`. This channel therefore seeds NOTHING new and
# needs no owner seeding action in production - unlike a gold/yellow border tag, which would.
ART_EDGE_CONTINUITY_TAG_NAME = "Extended"
ART_EDGE_VOTE_CONFIDENCE = 0.7  # heuristic tier, matching the frame-style sample's own

ART_EDGE_FRAMED = "framed"
ART_EDGE_EXTENDED = "extended"
ART_EDGE_OPEN = "open"

# The full closed value space, enumerated so callers branching on it have something to check
# membership against rather than restating three string literals.
ART_EDGE_CLASSES: tuple[str, ...] = (ART_EDGE_FRAMED, ART_EDGE_EXTENDED, ART_EDGE_OPEN)

# The `layout_class` values that name an actual border colour to compare against. `None`
# (classify_border_color's own "uniform but not a colour this taxonomy covers" abstention) is
# deliberately excluded - there's no colour to compare the art-adjacent strip to, so the honest
# reading is to abstain here too, not to invent a comparison against nothing. `"borderless"` is
# also excluded from THIS set, but handled first as its own short-circuit (see the function body)
# rather than falling into the "no comparison possible" bucket, because it isn't ambiguous -
# borderless positively rules out `extended`.
_ART_EDGE_BORDER_LAYOUT_CLASSES: frozenset[str] = frozenset({"black", "white", "silver"})

# COLOUR-DISTANCE MEASURE: plain Euclidean distance between the art-adjacent strip's sampled mean
# RGB and the border's sampled mean RGB (both the same `_sample_band` mean-RGB triple
# `classify_border_color` already computes - no new extraction, no colour-space conversion added).
# Euclidean RGB is not perceptually uniform (a fixed numeric distance is not a fixed PERCEIVED
# difference everywhere in the space), and it is weakest exactly where two colours are both
# desaturated and differ mainly in a way human vision weights unevenly - which is the one case
# this taxonomy has to worry about: a genuinely grey/neutral patch of artwork sitting beside a
# "silver" border. A perceptually-corrected metric (Lab-space, CIEDE2000) would fix that, at the
# cost of a colour-space conversion this codebase performs nowhere else and that this module has
# no independent evidence it needs - the black/white cases (the overwhelming majority of the
# catalogue's borders; silver is rare) sit at the extremes of brightness where Euclidean distance
# and perceptual distance already track each other closely. Validated against real Scryfall
# extended-art/borderless/framed images before being trusted (see this module's validation
# report); silver-bordered cards were not a dedicated cohort in that pass (Scryfall silver-bordered
# printings are a small, mostly funny-set population) - if a future measurement finds silver
# specifically needs a perceptual metric, that is this constant's own follow-up, not a reason to
# add unproven colour machinery speculatively now.
_ART_EDGE_COLOR_DISTANCE_THRESHOLD = 70.0


def classify_art_edge_continuity(
    card_image: "Image.Image",
    art_crop_px: Optional[Sequence[int]],
    layout_class: Optional[str],
    bleed_class: Optional[str] = None,
) -> Optional[str]:
    """Returns 'framed' / 'extended' / 'open', or None when the reading is unusable. EVIDENCE-ONLY
    today - nothing votes on it yet (see `cast_art_edge_continuity_vote`'s docstring for the gate
    that has to clear first).

      'framed'   - normal card: the art-adjacent strip's colour matches the border this image is
                   already known to have (`layout_class`).
      'extended' - artwork reaches the card's left and right sides (the art-adjacent strip does
                   NOT match the border colour), but `layout_class` says a border still reads at
                   the very edge. Scryfall's `frame_effects` "extendedart".
      'open'     - `layout_class == "borderless"`: there is no border to compare against, and a
                   card with no border cannot be extended-art.
      None       - no usable `art_crop_px`/degenerate crop, or `layout_class` names no border to
                   compare against (`None` - `classify_border_color`'s own ambiguous reading).
                   Abstaining is the honest output; the alternative is inventing a comparison
                   against a colour nobody measured.

    `layout_class` is the caller's ALREADY-COMPUTED `classify_border_color(card_image, bleed_class)`
    result for this same image - not recomputed here. Passing it in (rather than this function
    calling `classify_border_color` itself) means the border-colour class and the art-edge class
    are always read off the SAME underlying sample, and Stage C pays for that classification once,
    not twice, per image.

    COORDINATE FRAMES - the one genuinely easy thing to get wrong here, and the reason
    `art_crop_px` is pixels rather than a fractional box. The edge band and the art crop arrive in
    DIFFERENT frames and must therefore be treated ASYMMETRICALLY:

      * `_BORDER_SAMPLE_BANDS` are raw fractions tuned against a BLEED-INCLUSIVE image, so the
        edge band still needs `normalize_crop_box(band, bleed_class)` applied here, exactly as
        `classify_border_color` applies it.
      * `art_crop_px` does NOT. `ImageEvidence` stores it already remapped: `image_evidence.
        _crop_box_to_pixels` takes `local_phash.ART_CROP_BOX`, passes it through
        `normalize_crop_box` for that row's own `bleed_class`, and only then multiplies out by
        width/height (see models.py's `art_crop_px` field comment). It is absolute pixels in
        THIS image's own space. Dividing by width/height recovers fractions that are already
        correct for this image; calling `normalize_crop_box` on them would apply the
        trimmed-image correction a SECOND time and walk the band off the art entirely, on
        precisely the ~2.5% trimmed minority the remap exists to serve.

    `bleed_class` is therefore consumed for the edge band ONLY. That asymmetry is load-bearing
    and is pinned by its own test.

    `art_crop_px` is preferred over `artbox_crop_px` deliberately: measured 2026-07-28, the
    former is populated on 220,579 of 220,579 `ImageEvidence` rows (100%) and the latter on
    64.6%, and this classifier has no fallback reading without one.
    """
    if layout_class == "borderless":
        return ART_EDGE_OPEN
    if layout_class not in _ART_EDGE_BORDER_LAYOUT_CLASSES:
        return None

    width, height = card_image.size
    if not art_crop_px or len(art_crop_px) != 4 or width <= 0 or height <= 0:
        return None
    art_left_px, art_top_px, art_right_px, art_bottom_px = art_crop_px
    art_left, art_right = art_left_px / width, art_right_px / width
    art_top, art_bottom = art_top_px / height, art_bottom_px / height
    if not (0 <= art_left < art_right <= 1) or not (0 <= art_top < art_bottom <= 1):
        return None

    # The left/right EDGE bands only. The top/bottom edge bands are deliberately not consulted:
    # both stay bordered on framed AND extended cards (title bar above, text box below - an
    # extended-art card keeps both), so they cannot discriminate; and on a borderless card the
    # left/right pair already short-circuited above.
    edge_boxes = [normalize_crop_box(_BORDER_SAMPLE_BANDS[i], bleed_class) for i in (0, 1)]

    # Sample the art-adjacent strips over the art's OWN vertical span - the only band of rows
    # where "is there frame to the side of the artwork?" is even a question.
    #
    # The outer bound of each strip is read off the REMAPPED edge box, not off the raw
    # `_BORDER_SAMPLE_BANDS` fractions. That is the coordinate-frame argument above cashed out
    # in one line: the strip runs between two landmarks that must BOTH be expressed in this
    # image's frame, and the edge band only gets there by being remapped. Using the raw 0.05
    # against an already-remapped `art_left` mixes frames, and on a trimmed image it collapses
    # the left strip to zero width outright (art_left remaps to ~0.027, inboard of the raw
    # 0.05) - which would silently degrade to an empty crop and a skipped reading rather than a
    # loud failure. Pinned by test_trimmed_image_reads_the_art_adjacent_strip_in_its_own_frame.
    left_gap_outer = min(edge_boxes[0][2], art_left)
    right_gap_outer = max(edge_boxes[1][0], art_right)
    adjacent_boxes = [
        (left_gap_outer, art_top, art_left, art_bottom),
        (art_right, art_top, right_gap_outer, art_bottom),
    ]

    border_samples = [s for s in (_sample_band(card_image, b) for b in edge_boxes) if s is not None]
    adjacent_samples = [s for s in (_sample_band(card_image, b) for b in adjacent_boxes) if s is not None]
    if not border_samples or not adjacent_samples:
        return None

    # Both sides averaged into one RGB triple each, matching the old code's own "mean of both
    # sides" precedent (there it averaged a scalar std; here it averages the mean-RGB triple
    # `_sample_band` already returns) - a card whose left and right bands read slightly
    # differently (uneven lighting across a scan) is still one comparison, not two disagreeing
    # ones.
    border_rgb = tuple(statistics.mean(sample[0][channel] for sample in border_samples) for channel in range(3))
    adjacent_rgb = tuple(statistics.mean(sample[0][channel] for sample in adjacent_samples) for channel in range(3))
    distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(adjacent_rgb, border_rgb)))

    return ART_EDGE_FRAMED if distance < _ART_EDGE_COLOR_DISTANCE_THRESHOLD else ART_EDGE_EXTENDED


def cast_art_edge_continuity_vote(
    card: Card,
    art_edge_class: Optional[str],
    confidence: float = ART_EDGE_VOTE_CONFIDENCE,
    run_id: Optional[str] = None,
) -> Optional[CardTagVote]:
    """An unsaved `CardTagVote` applying the pre-existing "Extended" tag, or None.

    ONLY the 'extended' reading votes. 'framed' and 'open' are deliberately silent rather than
    casting a negative "Extended" vote: 'open' is the class this classifier is least sure of (it
    shares the "edge reads as artwork" reading with every scan artefact, JPEG ring and noisy
    proxy render that already inflates `classify_border_color`'s borderless bucket), and a
    negative vote from an unvalidated class is a claim, not an abstention.

    NOT WIRED INTO ANY RUNNER YET - deliberately, and this is the honest limit of this PR. The
    retuned relative-comparison classifier (docs/reports/2026-08-06-art-edge-relative-comparison.md)
    is stored as `ImageEvidence.art_edge_class` evidence-only; whether it should ever cast a vote
    is a separate decision this PR does not make, and depends on that evidence existing first.
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


__all__ = [
    "ART_EDGE_ANONYMOUS_ID",
    "ART_EDGE_CONTINUITY_TAG_NAME",
    "ART_EDGE_VOTE_CONFIDENCE",
    "ART_EDGE_FRAMED",
    "ART_EDGE_EXTENDED",
    "ART_EDGE_OPEN",
    "ART_EDGE_CLASSES",
    "classify_art_edge_continuity",
    "cast_art_edge_continuity_vote",
]
