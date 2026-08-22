"""
Pinline-inset measurement (Stage C extraction): measures, per edge of a card's fetched image, the
distance from the image's own outer boundary inward to the first sustained colour transition -
and persists that distance as a fraction of the relevant dimension. MEASURES AND PERSISTS ONLY -
no crop box computation anywhere in this pipeline reads these fields yet (see this module's one
call site, `image_evidence.compute_card_evidence`); a later change is what will act on them.

WHAT THE NUMBER ACTUALLY IS. A card's fetched image typically shows, from the outside in: a
narrow band of upload margin (if any), then the card's own printed border, then the pinline where
the border's ink gives way to the coloured card frame or to bleeding art. A colour-distance scan
walking inward from the image edge does not know which of these it is crossing - it simply stops
at the first sustained colour departure from the edge's own reference colour. On a bordered card,
that is almost always the pinline, not the outer edge of any upload margin: the border itself is
usually the same or a similar colour as any surrounding margin (most commonly black-on-black), so
the scan passes straight through the margin and the border without triggering, and only stops
where the ink actually changes colour. The distance this module reports is therefore the trim-to-
pinline inset, a near-constant of the card's frame geometry (the printed border's own width plus
whatever consistent bleed a print run used) - not a measurement of how a particular upload was
cropped, and not evidence that any upload margin exists at all. A borderless card, where art runs
to the printed trim with no ink band to stop at, is the case this module cannot usefully measure
past its uniformity gate (see below) - by construction, a scan that never crosses two
colour-distinct printed regions has nothing to report.

HOW THIS WAS VALIDATED: calibrated against 41 trim-exact reference images (the image's own edge
IS the trim line, by construction), the black-bordered inset comes out as a tight, near-constant
per-edge figure - left and right agreeing to within half a millimetre of each other across dozens
of cards, top almost as tight, only the bottom edge showing real spread (plausibly frame furniture
that varies by print run, e.g. an attribution line). Treating a real upload's measured value as
this trim-to-pinline distance and offsetting by that calibrated constant reproduces the expected
print bleed to a median of a few tenths of a millimetre against an independently derived crop-box
geometry - agreement two unrelated measurement paths would not show if the pixel this module
stops at were actually a canvas boundary rather than the pinline. A separate check across the
available real-upload sample found every image's own aspect ratio consistent with an ordinary
bleed-card or trim-exact card, with no example of an image letterboxed onto an oversized canvas -
the shape this module's field names originally implied it was finding.

THE ALGORITHM: per edge, walk inward along `N_SAMPLE_LINES` sample lines spaced between
`LINE_FRACTION_LO` and `LINE_FRACTION_HI` along that edge's own length (the same fractional band
`local_fallback._BORDER_SAMPLE_BANDS` already samples its own top/bottom bands across, chosen
there for the same reason it is reused here: it avoids the rounded-corner zone right at each
edge's own ends). For each line, find the first index where `SUSTAIN_RUN_LENGTH` consecutive
pixels all differ from that edge's own reference colour (the mean of the first `SMOOTH_WINDOW`
pixels) by more than `COLOR_DISTANCE_THRESHOLD` in Euclidean RGB distance, searching no further
inward than `SEARCH_CAP_FRACTION` of the perpendicular dimension.

TWO GUARDS ARE LOAD-BEARING:

1. THE UNIFORMITY GATE. A transition only counts if the zone between the image's own edge and
   that transition is itself internally uniform (per-channel population std dev below
   `UNIFORMITY_STD_THRESHOLD` - the same value, and the same statistic, `local_fallback`'s own
   private `_BORDER_UNIFORMITY_STD_THRESHOLD` is tuned against for its border-color sample; not
   imported from there, since `local_fallback.py` is PROTECTED CORE, but deliberately kept
   numerically identical). Without this gate, a scan walking inward through a borderless card's
   own artwork would report the first colour change IN THAT ART as though it were the pinline -
   this is the difference between measuring the frame and measuring the picture.

2. BLACK-ON-BLACK ABSTENTION. When no transition is found within the search cap AND the edge's
   own mean colour is itself near-black (every channel below `BLACK_EDGE_MAX_BRIGHTNESS`), that
   edge is INDETERMINATE, not a measured zero-distance reading - a black upload margin (or a
   black canvas of any kind) sitting against a black-bordered card produces no colour departure
   a plain colour scan can see at all, so there is nothing to distinguish "the pinline is right at
   the edge" from "the scan simply could not see through two adjacent black zones". This module
   represents "not measured" as a null `inset_frac` (see `EdgeReading`) so a null read can never
   be mistaken for a measured zero.

THE SECOND TRANSITION. The scan above stops at the first sustained colour departure and reports
one number. Whether that number is trim-to-pinline inset (the module's own validated reading) or
something else has been argued at length elsewhere and is not re-litigated here - what this
module can do without taking a side in that argument is keep scanning PAST the first transition
for a second one, and report both distances rather than collapsing them into a single number.
`EdgeReading.second_inset_frac`/`second_call` hold that second reading, same units and same
per-line-median-then-call shape as the first (`inset_frac`/`call` above) - a fraction of the same
perpendicular dimension, measured from the image's own edge (not from the first transition), so
the two fields are directly comparable and a caller can derive either "distance from edge to
second transition" or "distance between the two transitions" (`second_inset_frac - inset_frac`)
without this module deciding which one means "padding" and which means "border width".

The second scan reuses `_scan_line`'s own machinery unchanged (`SUSTAIN_RUN_LENGTH`,
`COLOR_DISTANCE_THRESHOLD`, and the SAME uniformity gate applied to the zone between the two
transitions rather than between the edge and the first) - see `_scan_second_transition`'s own
docstring. Two consequences of reusing rather than re-tuning, both exercised in this module's own
test suite: a text stroke narrower than `SUSTAIN_RUN_LENGTH` pixels can never fill a
sustained-departure window on its own, so it cannot register as a transition candidate at all -
but if it sits inside the zone leading up to the REAL boundary further in, it still breaks that
zone's own uniformity, and the gate abstains (`CALL_NO_TRANSITION`) rather than confidently
reporting a reading it cannot vouch for. A stroke wide enough to fill the window on its own is NOT
specially detected; it is indistinguishable from a genuine transition to a pure colour scan, and
this module does not attempt to solve that (text detection is out of scope here, same as
everywhere else in this file). This is exactly the failure mode `local_bleed_calculator`'s own
calibration table already names and works around for the FIRST transition on one specific class -
its `("black", "2015")` bottom entry abstains because "the 2015 frame's collector-info text line
reads as a pinline overrun on some cards but not others." A `second_call == CALL_MEASURED` reading
on an edge/class known to carry collector-line text at this search depth deserves the same
scepticism a consumer already has to apply to that documented case, not blind trust - this module
reports the raw measurement and its own call, and leaves the "is this actually the border's far
edge, or did it stop on text" judgment to whichever future calculator chooses to consume this
field (deferred, same as every other interpretation question this module raises without
answering).

When the first transition itself is never found for an edge (`call` is `CALL_INDETERMINATE_BLACK`
or `CALL_NO_TRANSITION`), no second scan is attempted for that edge at all - `second_inset_frac`
is `None` and `second_call` is set to the SAME value as `call`. There is nothing about "second"
that edge's own first-transition failure doesn't already explain, so this avoids inventing a
fourth call value whose only meaning would be "see the first call instead."

PER-EDGE CALL (from the MEDIAN of that edge's `N_SAMPLE_LINES` readings) describes MEASUREMENT
QUALITY, not the size of the reading:
  - `CALL_MEASURED`: at least one sample line found a qualifying transition - the median
    `inset_frac` is a real reading, whatever its magnitude.
  - `CALL_INDETERMINATE_BLACK`: no line found a transition, and the edge itself reads near-black
    - see guard 2 above.
  - `CALL_NO_TRANSITION`: no line found a transition, and the edge does not read as black - the
    edge colour persisted flat all the way to the search cap without a confident departure;
    treated as a genuine non-read rather than guessed at either boundary.

WHOLE-IMAGE VERDICT, again a statement about measurement quality rather than about what was
found: 3 or more `CALL_INDETERMINATE_BLACK` edges is `VERDICT_INDETERMINATE` (too much of the
image is unreadable black-on-black to trust); otherwise 2 or more `CALL_MEASURED` edges is
`VERDICT_MEASURED` (a usable reading exists on a majority of edges); anything else (too few
successful reads, and not enough black-indeterminate edges to call it indeterminate outright) is
`VERDICT_AMBIGUOUS`.

WHAT THIS MODULE DOES NOT DO: it does not change, remap, or correct any existing crop box - every
`*_crop_px` field `image_evidence.py` computes is derived exactly as before, from the same fixed
fractions. It also cannot see through two adjacent black zones (guard 2 above) - that case is
indeterminate, not a measured zero. And it does not derive a bleed-in-millimetres figure itself -
that requires the per-frame-class calibration constants described above, which are a separate,
independently-validated input this module does not compute or store.
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

CALL_MEASURED = "measured"
CALL_INDETERMINATE_BLACK = "indeterminate_black"
CALL_NO_TRANSITION = "no_transition"

VERDICT_MEASURED = "measured"
VERDICT_AMBIGUOUS = "ambiguous"
VERDICT_INDETERMINATE = "indeterminate"

_EDGE_NAMES = ("top", "bottom", "left", "right")


@dataclass(frozen=True)
class EdgeReading:
    """One edge's own measurement. `inset_frac` is the MEDIAN of that edge's `N_SAMPLE_LINES`
    per-line readings, as a fraction of the perpendicular dimension - `None` when no line found a
    transition at all (`call` says why: black-on-black abstention vs. a genuine non-black
    non-read). A null fraction can therefore never be mistaken for a measured zero - see this
    module's own docstring for why that distinction is load-bearing.

    `second_inset_frac`/`second_call` are the SAME shape, one scan further in - see module
    docstring's "THE SECOND TRANSITION" section. `second_inset_frac` is a fraction of the same
    perpendicular dimension, measured from the image's own edge (not from the first transition).
    When `inset_frac` is `None`, no second scan is attempted and `second_call` is set to the same
    value as `call` - there is nothing about "second" a failed first transition doesn't already
    explain."""

    inset_frac: Optional[float]
    call: str
    second_inset_frac: Optional[float] = None
    second_call: str = ""


@dataclass(frozen=True)
class PinlineInsetResult:
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


def _scan_second_transition(
    line: "np.ndarray[Any, np.dtype[np.float32]]", first_index: int, cap_px: int
) -> Optional[int]:
    """Continues the same scan past an already-found first transition (`first_index`) for a
    second sustained colour departure. Reference colour is the mean of `SMOOTH_WINDOW` pixels
    immediately inward of `first_index` (the band's own colour, not the image edge's), and the
    uniformity gate checks the zone BETWEEN the two transitions (`line[first_index:i]`) rather
    than between the edge and the first - otherwise identical to `_scan_line`: same
    `SUSTAIN_RUN_LENGTH`, same `COLOR_DISTANCE_THRESHOLD`, same `UNIFORMITY_STD_THRESHOLD`, bounded
    by the SAME `cap_px` the first transition used, so total scan depth from the image's own edge
    never grows past `SEARCH_CAP_FRACTION` regardless of how many transitions are found. Returns
    None if there isn't room to smooth a reference before the cap, or no qualifying departure is
    found within it - see module docstring's "THE SECOND TRANSITION" section for what this can and
    cannot distinguish (a text stroke narrower than `SUSTAIN_RUN_LENGTH` cannot register as a
    candidate at all; a wider one is not specially detected)."""
    band_smooth_end = first_index + SMOOTH_WINDOW
    if band_smooth_end >= cap_px or len(line) <= band_smooth_end + SUSTAIN_RUN_LENGTH:
        return None
    reference = line[first_index:band_smooth_end].mean(axis=0)
    for i in range(band_smooth_end, min(cap_px, len(line) - SUSTAIN_RUN_LENGTH)):
        window = line[i : i + SUSTAIN_RUN_LENGTH]
        distance = np.linalg.norm(window - reference, axis=1)
        if not (distance > COLOR_DISTANCE_THRESHOLD).all():
            continue
        zone = line[first_index:i]
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
    inset_fracs: list[Optional[float]] = []
    second_fracs: list[Optional[float]] = []
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
        inset_fracs.append(transition_index / walk_dim if transition_index is not None else None)
        if transition_index is not None:
            second_index = _scan_second_transition(line, transition_index, cap_px)
            second_fracs.append(second_index / walk_dim if second_index is not None else None)
        else:
            second_fracs.append(None)

    mean_edge_color = np.mean(edge_colors, axis=0)
    is_black = bool(float(mean_edge_color.max()) < BLACK_EDGE_MAX_BRIGHTNESS)
    measured = [v for v in inset_fracs if v is not None]
    median_inset_frac = float(np.median(measured)) if measured else None

    if median_inset_frac is None:
        call = CALL_INDETERMINATE_BLACK if is_black else CALL_NO_TRANSITION
    else:
        call = CALL_MEASURED

    if median_inset_frac is None:
        # No first transition, so no second scan was ever attempted for this edge - propagate the
        # SAME call rather than inventing a distinct "second unknown" state (module docstring's
        # "THE SECOND TRANSITION" section).
        median_second_frac: Optional[float] = None
        second_call = call
    else:
        measured_second = [v for v in second_fracs if v is not None]
        median_second_frac = float(np.median(measured_second)) if measured_second else None
        second_call = CALL_MEASURED if median_second_frac is not None else CALL_NO_TRANSITION

    return EdgeReading(
        inset_frac=median_inset_frac,
        call=call,
        second_inset_frac=median_second_frac,
        second_call=second_call,
    )


def measure_pinline_inset(image: "Image.Image") -> Optional[PinlineInsetResult]:
    """Entry point - one card's fetched image in, a per-edge/whole-image measurement out, or
    `None` for a degenerate image (zero/negative width or height): abstains rather than raising,
    the same "sub-floor" guard convention `image_evidence.py`'s own geometry_bleed/symbol_region
    extractors use for their own divisions/crops."""
    width, height = image.size
    if width <= 0 or height <= 0:
        return None

    pixels = np.asarray(image.convert("RGB"))
    edges = {side: _scan_edge(pixels, side) for side in _EDGE_NAMES}

    n_indeterminate_black = sum(1 for edge in edges.values() if edge.call == CALL_INDETERMINATE_BLACK)
    n_measured = sum(1 for edge in edges.values() if edge.call == CALL_MEASURED)

    if n_indeterminate_black >= 3:
        verdict = VERDICT_INDETERMINATE
    elif n_measured >= 2:
        verdict = VERDICT_MEASURED
    else:
        verdict = VERDICT_AMBIGUOUS

    return PinlineInsetResult(
        top=edges["top"],
        bottom=edges["bottom"],
        left=edges["left"],
        right=edges["right"],
        verdict=verdict,
    )
