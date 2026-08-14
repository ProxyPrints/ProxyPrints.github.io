"""
Canvas-padding detector (Stage C extraction): measures, per edge, how far a card's own printed
content sits from the outer boundary of its fetched image - distinguishing a plain printed
border (a few percent of the dimension) from a much wider band of flat canvas colour left by an
uploader who scanned or exported the card onto an oversized page. MEASURES AND PERSISTS ONLY - no
crop box computation anywhere in this pipeline reads these fields yet (see this module's one call
site, `image_evidence.compute_card_evidence`); a follow-up change is what will act on them.

WHY THIS MEASUREMENT MATTERS: every fixed-fraction crop box this pipeline computes
(`collector_line_crop_px`, `artist_crop_px`, `art_crop_px`, `symbol_crop_px`, `legal_line_crop_px`
- see `image_evidence.py`'s own module docstring) is a fraction of the WHOLE fetched image. On an
upload with a padded canvas, that fraction lands inside the padding band rather than on the
card's own printed area - measured over 348 real padded cards, the collector-line crop misses the
collector line entirely on 72.1% of them and achieves adequate overlap on none, with a median
displacement of 8.0% of image height. Nothing upstream of this extractor measures the padding
band at all, so nothing downstream can correct for it.

THE ALGORITHM (ported from a validated reference implementation): per edge, walk inward along
`N_SAMPLE_LINES` sample lines spaced between `LINE_FRACTION_LO` and `LINE_FRACTION_HI` along that
edge's own length - the same fractional band `local_fallback._BORDER_SAMPLE_BANDS` already
samples its own top/bottom bands across (0.15-0.85), chosen there (and reused here for the same
reason) to avoid the rounded-corner zone right at each edge's own ends. For each line, find the
first index where `SUSTAIN_RUN_LENGTH` consecutive pixels all differ from that edge's own
reference colour (the mean of the first `SMOOTH_WINDOW` pixels) by more than
`COLOR_DISTANCE_THRESHOLD` in Euclidean RGB distance, searching no further inward than
`SEARCH_CAP_FRACTION` of the perpendicular dimension.

TWO GUARDS ARE LOAD-BEARING:

1. THE UNIFORMITY GATE. A transition only counts if the zone between the image's own edge and
   that transition is itself internally uniform (per-channel population std dev below
   `UNIFORMITY_STD_THRESHOLD` - the same value, and the same statistic, local_fallback's own
   private `_BORDER_UNIFORMITY_STD_THRESHOLD` is tuned against for its border-color sample; not
   imported from there, since `local_fallback.py` is PROTECTED CORE, but deliberately kept
   numerically identical). Without this gate, a scan walking inward through a borderless card's
   own artwork would report the first colour change IN THAT ART as though it were a canvas
   boundary - this is the difference between measuring padding and measuring the picture.

2. BLACK-ON-BLACK ABSTENTION. When no transition is found within the search cap AND the edge's
   own mean colour is itself near-black (every channel below `BLACK_EDGE_MAX_BRIGHTNESS`), that
   edge is INDETERMINATE, not zero - a black canvas around a black-bordered card produces no
   colour departure at all, so a plain colour scan genuinely cannot see the boundary. Recording
   this as "no padding" would be actively wrong: on the validation sample, 4 of 352
   otherwise-padded rows had exactly this failure on their top edge, and defaulting them to zero
   would under-crop by the full band width. This module represents "not measured" as a null
   `pad_frac` (see `EdgeReading`) so a null read can never be mistaken for a measured zero.

PER-EDGE CALL (from the MEDIAN of that edge's `N_SAMPLE_LINES` readings):
  - `CALL_CONFIDENT_NOPAD`: median pad fraction at or below `LOW_PAD_FRACTION` - a plain printed
    border is this thick or thinner.
  - `CALL_CONFIDENT_PADDED`: median pad fraction at or above `HIGH_PAD_FRACTION`.
  - `CALL_AMBIGUOUS`: median pad fraction between the two thresholds.
  - `CALL_BLACK_INDETERMINATE`: no line found a transition, and the edge itself reads near-black
    - see guard 2 above.
  - `CALL_NO_TRANSITION_NONBLACK`: no line found a transition, and the edge does not read as
    black - the edge colour persisted flat all the way to the search cap without a confident
    departure; treated as a genuine non-read rather than guessed at either boundary.

WHOLE-IMAGE VERDICT: 3 or more `CALL_BLACK_INDETERMINATE` edges abstains as `VERDICT_ABSTAIN_BLACK`
(padding may be present but cannot be seen); otherwise 2 or more `CALL_CONFIDENT_PADDED` edges is
`VERDICT_PADDED`; otherwise 2 or more `CALL_CONFIDENT_NOPAD` edges with zero
`CALL_CONFIDENT_PADDED` edges is `VERDICT_NOT_PADDED`; anything else (insufficient or conflicting
edge evidence) is `VERDICT_AMBIGUOUS`.

WHAT THIS MODULE DOES NOT DO: it does not change, remap, or correct any existing crop box - every
`*_crop_px` field `image_evidence.py` computes is derived exactly as before, from the same fixed
fractions. It also cannot see a black canvas behind a black-bordered card (guard 2 above) - that
case abstains, it does not measure zero.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

if TYPE_CHECKING:
    from PIL import Image

N_SAMPLE_LINES = 9
LINE_FRACTION_LO, LINE_FRACTION_HI = 0.15, 0.85
SEARCH_CAP_FRACTION = 0.20
SMOOTH_WINDOW = 4
SUSTAIN_RUN_LENGTH = 5
COLOR_DISTANCE_THRESHOLD = 28.0
# Same statistic (per-channel population std dev over the zone from the image's own edge to a
# candidate transition) and the same tuned value local_fallback's private
# _BORDER_UNIFORMITY_STD_THRESHOLD uses for its own border-color sample - see module docstring's
# "UNIFORMITY GATE" section for why this is reproduced rather than imported.
UNIFORMITY_STD_THRESHOLD = 18.0
BLACK_EDGE_MAX_BRIGHTNESS = 32
LOW_PAD_FRACTION = 0.035
HIGH_PAD_FRACTION = 0.050

CALL_CONFIDENT_NOPAD = "confident_nopad"
CALL_CONFIDENT_PADDED = "confident_padded"
CALL_AMBIGUOUS = "ambiguous"
CALL_BLACK_INDETERMINATE = "black_indeterminate"
CALL_NO_TRANSITION_NONBLACK = "no_transition_nonblack"

VERDICT_PADDED = "padded"
VERDICT_NOT_PADDED = "not_padded"
VERDICT_ABSTAIN_BLACK = "abstain_black"
VERDICT_AMBIGUOUS = "ambiguous"

_EDGE_NAMES = ("top", "bottom", "left", "right")


@dataclass(frozen=True)
class EdgeReading:
    """One edge's own measurement. `pad_frac` is the MEDIAN of that edge's `N_SAMPLE_LINES`
    per-line readings, as a fraction of the perpendicular dimension - `None` when no line found a
    transition at all (`call` says why: black-on-black abstention vs. a genuine non-black
    non-read). A null fraction can therefore never be mistaken for a measured zero - see this
    module's own docstring for why that distinction is load-bearing."""

    pad_frac: Optional[float]
    call: str


@dataclass(frozen=True)
class CanvasPaddingResult:
    top: EdgeReading
    bottom: EdgeReading
    left: EdgeReading
    right: EdgeReading
    verdict: str


def _scan_line(line: "np.ndarray[Any, np.dtype[np.float32]]", cap_px: int) -> Optional[int]:
    """`line`: an (L, 3) float array of pixel values from the image's own edge (index 0) inward,
    already sliced to one sample line. Returns the first index i such that
    pixels[i:i+SUSTAIN_RUN_LENGTH] all differ from the edge's own reference colour (the mean of
    the first SMOOTH_WINDOW pixels) by more than COLOR_DISTANCE_THRESHOLD in Euclidean RGB
    distance, AND the zone [0:i] is itself internally uniform (THE UNIFORMITY GATE - see module
    docstring) - or None if no such run is found within cap_px."""
    if cap_px <= SMOOTH_WINDOW or len(line) <= SMOOTH_WINDOW + SUSTAIN_RUN_LENGTH:
        return None
    reference = line[0:SMOOTH_WINDOW].mean(axis=0)
    for i in range(SMOOTH_WINDOW, min(cap_px, len(line) - SUSTAIN_RUN_LENGTH)):
        window = line[i : i + SUSTAIN_RUN_LENGTH]
        distance = np.linalg.norm(window - reference, axis=1)
        if not (distance > COLOR_DISTANCE_THRESHOLD).all():
            continue
        zone = line[0:i]
        zone_std = float(zone.std(axis=0).max()) if len(zone) > 1 else 0.0
        return i if zone_std < UNIFORMITY_STD_THRESHOLD else None
    return None


def _scan_edge(pixels: "np.ndarray[Any, np.dtype[np.uint8]]", side: str) -> EdgeReading:
    """`pixels`: the full (H, W, 3) uint8 array. Walks N_SAMPLE_LINES lines inward from `side`,
    each starting at that edge's own boundary, sampled between LINE_FRACTION_LO and
    LINE_FRACTION_HI along the edge's own length (the same fractional band local_fallback's
    private _BORDER_SAMPLE_BANDS already samples across, chosen there to avoid the
    rounded-corner zone)."""
    height, width, _ = pixels.shape
    if side in ("top", "bottom"):
        edge_length, walk_dim = width, height
    else:
        edge_length, walk_dim = height, width
    cap_px = int(walk_dim * SEARCH_CAP_FRACTION)

    positions = [int(edge_length * f) for f in np.linspace(LINE_FRACTION_LO, LINE_FRACTION_HI, N_SAMPLE_LINES)]
    edge_colors = []
    pad_fracs: list[Optional[float]] = []
    for position in positions:
        if side == "top":
            line = pixels[:, position, :].astype(np.float32)
        elif side == "bottom":
            line = pixels[::-1, position, :].astype(np.float32)
        elif side == "left":
            line = pixels[position, :, :].astype(np.float32)
        else:  # right
            line = pixels[position, ::-1, :].astype(np.float32)
        edge_colors.append(line[0:SMOOTH_WINDOW].mean(axis=0))
        transition_index = _scan_line(line, cap_px)
        pad_fracs.append(transition_index / walk_dim if transition_index is not None else None)

    mean_edge_color = np.mean(edge_colors, axis=0)
    is_black = bool(float(mean_edge_color.max()) < BLACK_EDGE_MAX_BRIGHTNESS)
    measured = [v for v in pad_fracs if v is not None]
    median_pad_frac = float(np.median(measured)) if measured else None

    if median_pad_frac is None:
        call = CALL_BLACK_INDETERMINATE if is_black else CALL_NO_TRANSITION_NONBLACK
    elif median_pad_frac <= LOW_PAD_FRACTION:
        call = CALL_CONFIDENT_NOPAD
    elif median_pad_frac >= HIGH_PAD_FRACTION:
        call = CALL_CONFIDENT_PADDED
    else:
        call = CALL_AMBIGUOUS

    return EdgeReading(pad_frac=median_pad_frac, call=call)


def detect_canvas_padding(image: "Image.Image") -> Optional[CanvasPaddingResult]:
    """Entry point - one card's fetched image in, a per-edge/whole-image measurement out, or
    `None` for a degenerate image (zero/negative width or height): abstains rather than raising,
    the same "sub-floor" guard convention `image_evidence.py`'s own geometry_bleed/symbol_region
    extractors use for their own divisions/crops."""
    width, height = image.size
    if width <= 0 or height <= 0:
        return None

    pixels = np.asarray(image.convert("RGB"))
    edges = {side: _scan_edge(pixels, side) for side in _EDGE_NAMES}

    n_black = sum(1 for edge in edges.values() if edge.call == CALL_BLACK_INDETERMINATE)
    n_padded = sum(1 for edge in edges.values() if edge.call == CALL_CONFIDENT_PADDED)
    n_nopad = sum(1 for edge in edges.values() if edge.call == CALL_CONFIDENT_NOPAD)

    if n_black >= 3:
        verdict = VERDICT_ABSTAIN_BLACK
    elif n_padded >= 2:
        verdict = VERDICT_PADDED
    elif n_nopad >= 2 and n_padded == 0:
        verdict = VERDICT_NOT_PADDED
    else:
        verdict = VERDICT_AMBIGUOUS

    return CanvasPaddingResult(
        top=edges["top"],
        bottom=edges["bottom"],
        left=edges["left"],
        right=edges["right"],
        verdict=verdict,
    )
