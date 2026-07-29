"""
Art-edge continuity - the EXTENDED-ART channel.

Owner-directed design (2026-07-28): "we can measure by aiming our border pixel color measurement
at two locations, one of which is adjacent to the art crop location."

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

WHAT THE SECOND SAMPLE POINT BUYS - the discriminator one point cannot make:

                    | LEFT/RIGHT EDGE band | LEFT/RIGHT ART-ADJACENT band
  normal ("framed") | uniform (border)     | uniform (frame sits between art and edge)
  extended art      | uniform (border)     | NON-uniform (art runs out to the card's sides)
  borderless/full   | NON-uniform (art)    | NON-uniform (art)

The edge band alone cannot separate "framed" from "extended" (both uniform); the art-adjacent
band alone cannot separate "extended" from "borderless" (both non-uniform). Only the pair does,
which is exactly the owner's point.

MEASUREMENT-INDEPENDENT ON PURPOSE. This module introduces no colour threshold and no new tuned
number. The only threshold it reads is the EXISTING `local_fallback._BORDER_UNIFORMITY_STD_
THRESHOLD`; the only geometry it uses is derived from the EXISTING `_BORDER_SAMPLE_BANDS` plus
the stored `ImageEvidence.art_crop_px`. A colour-keyed signal (gold/yellow border) genuinely does
need fresh measurements of real cards before it can ship; a uniformity COMPARISON does not, which
is why this half could be built while that half waits on a measurement pass.

TWO TRACKS, AND WHICH ONE THIS SERVES. For OFFICIAL printings nothing here is needed: Scryfall's
`frame_effects` already carries `extendedart` as an imported fact (4,165 printings), and an
imported fact is not a disputable claim that wants a pixel vote. This module exists for the OTHER
track - USER-UPLOADED PROXY IMAGES, where pixels are the only source and there is no printing to
read the fact off. That is what the local-fallback channel is for.

THE DEFECT IT TARGETS, measured against production ground truth (2026-07-28; 90,857
`ImageEvidence` rows whose card has a confirmed printing, joined to that printing's Scryfall
`border_color`). Among cards Scryfall calls black-bordered, `classify_border_color`'s
"not uniform -> borderless" catch-all fires on:

    plain black    16.5%  (11,844 of 71,840)
    full_art       22.8%  (191 of 836)
    EXTENDED ART   54.9%  (620 of 1,129)   <- 3.3x the plain-black base rate

Extended art is thus the single population that most reliably breaks the border classifier, and
it breaks it into a confident WRONG answer ("Borderless") rather than an abstention. This module
is the reading that catch-all has been standing in for. NOTE that fixing the catch-all itself is
out of scope here and tracked separately - see this module's report and the OPEN ITEMS on
`classify_border_color`'s silver/gold behaviour.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Optional

from cardpicker.local_fallback import (
    _BORDER_SAMPLE_BANDS,
    _BORDER_UNIFORMITY_STD_THRESHOLD,
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


def classify_art_edge_continuity(
    card_image: "Image.Image",
    art_crop_px: Optional[Sequence[int]],
    bleed_class: Optional[str] = None,
) -> Optional[str]:
    """Returns 'framed' / 'extended' / 'open', or None when the reading is unusable or
    self-contradictory. EVIDENCE-ONLY today - nothing votes on it yet (see
    `cast_art_edge_continuity_vote`'s docstring for the gate that has to clear first).

      'framed'   - normal card: frame sits between the artwork and both side edges.
      'extended' - artwork reaches the card's left and right sides, but a border survives at the
                   very edge. Scryfall's `frame_effects` "extendedart".
      'open'     - artwork reaches the edges themselves: borderless, or a full-art land.
      None       - no usable art_crop_px, a degenerate crop, or the contradictory reading
                   "edge is artwork but the strip further IN is flat", which no real card
                   produces and which therefore means the geometry assumption failed rather
                   than describing a card. Abstaining is the honest output; the alternative is
                   inventing a class for an impossible observation.

    COORDINATE FRAMES - the one genuinely easy thing to get wrong here, and the reason this
    argument is `art_crop_px` (pixels) rather than a fractional box. The two band families
    arrive in DIFFERENT frames and must therefore be treated ASYMMETRICALLY:

      * `_BORDER_SAMPLE_BANDS` are raw fractions tuned against a BLEED-INCLUSIVE image, so they
        still need `normalize_crop_box(band, bleed_class)` applied here, exactly as
        `classify_border_color` applies it.
      * `art_crop_px` does NOT. `ImageEvidence` stores it already remapped: `image_evidence.
        _crop_box_to_pixels` takes `local_phash.ART_CROP_BOX`, passes it through
        `normalize_crop_box` for that row's own `bleed_class`, and only then multiplies out by
        width/height (see models.py's `art_crop_px` field comment). It is absolute pixels in
        THIS image's own space. Dividing by width/height recovers fractions that are already
        correct for this image; calling `normalize_crop_box` on them would apply the
        trimmed-image correction a SECOND time and walk the band off the art entirely, on
        precisely the ~2.5% trimmed minority the remap exists to serve.

    `bleed_class` is therefore consumed for the edge bands ONLY. That asymmetry is load-bearing
    and is pinned by its own test.

    `art_crop_px` is preferred over `artbox_crop_px` deliberately: measured 2026-07-28, the
    former is populated on 220,579 of 220,579 `ImageEvidence` rows (100%) and the latter on
    64.6%, and this classifier has no fallback reading without one.
    """
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
    # left/right pair already reads open without their help.
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

    adjacent_stds = [s[1] for s in (_sample_band(card_image, b) for b in adjacent_boxes) if s is not None]
    edge_stds = [s[1] for s in (_sample_band(card_image, b) for b in edge_boxes) if s is not None]
    if not adjacent_stds or not edge_stds:
        return None

    import statistics

    adjacent_uniform = statistics.mean(adjacent_stds) < _BORDER_UNIFORMITY_STD_THRESHOLD
    edge_uniform = statistics.mean(edge_stds) < _BORDER_UNIFORMITY_STD_THRESHOLD

    if adjacent_uniform:
        # Flat beside the art. If the edge outboard of it is flat too, that is an ordinary
        # framed card; if the edge is busy while the strip INBOARD of it is flat, the geometry
        # assumption has failed - real cards do not put artwork outside their own frame.
        return ART_EDGE_FRAMED if edge_uniform else None
    # Artwork beside the art crop. Whether a border survives at the very edge is what separates
    # extended art from a genuinely borderless card.
    return ART_EDGE_EXTENDED if edge_uniform else ART_EDGE_OPEN


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

    NOT WIRED INTO ANY RUNNER YET - deliberately, and this is the honest limit of this PR.
    `classify_art_edge_continuity` is validated against CONSTRUCTED cases (its tests), not
    against real card images, and the established precedent in this codebase is that every
    fixed-fraction crop box was tuned against real fetched images before it was trusted
    (`local_fallback`'s own module comment on the 40-source validation).

    THE GATE BEFORE THIS MAY VOTE, stated concretely so it is checkable rather than aspirational:
    run the classifier over the `ImageEvidence` rows whose confirmed printing carries Scryfall's
    own `frame_effects` "extendedart" (1,129 such rows in the 2026-07-28 join) and report
    agreement against that imported fact, plus the false-positive rate over a same-sized sample
    of confirmed NON-extended black-bordered cards. That labelling is free and needs no human
    pass - it is the same ground truth this module's docstring quotes. Until that runs, this
    function exists so the wiring is reviewable, and casts nothing.
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
