"""Measure border-colour statistics exactly as cardpicker.local_fallback.classify_border_color does.

Geometry constants, band definitions, statistics and the decision ladder are copied VERBATIM from
MPCAutofill/cardpicker/local_fallback.py (as of commit e6c6429a).

Three band placements are measured for every image:

  raw          - _BORDER_SAMPLE_BANDS as literally written (normalize_crop_box(..., None) no-op)
  production   - what production actually samples: classify_bleed_edge(image) then
                 normalize_crop_box(band, that_class). This is the placement whose numbers decide
                 a real ImageEvidence.layout_class.
  cardspace    - the placement the bands were INTENDED to have: the raw fractions interpreted as
                 fractions of the TRIMMED CARD, then mapped forward into whatever coordinate space
                 the image actually uses. For a trimmed image this equals `raw`; for a
                 bleed-inclusive image it shifts each band inward past the bleed margin.

Images are fetched once and cached on disk; a re-run re-uses the cache and makes no network calls.
"""

import hashlib
import io
import json
import os
import statistics
import sys
import time

import requests
from PIL import Image

SCRATCH = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(SCRATCH, "imgcache")
os.makedirs(CACHE, exist_ok=True)

# --------------------------------------------------------------------------------------------
# verbatim from local_fallback.py
# --------------------------------------------------------------------------------------------
_BORDER_SAMPLE_BANDS = [
    (0.03, 0.15, 0.05, 0.85),  # left edge
    (0.95, 0.15, 0.97, 0.85),  # right edge
    (0.15, 0.02, 0.85, 0.035),  # top edge
    (0.15, 0.965, 0.85, 0.98),  # bottom edge
]
_BAND_NAMES = ["left", "right", "top", "bottom"]
_BORDER_UNIFORMITY_STD_THRESHOLD = 18.0
_BLACK_MAX_BRIGHTNESS = 60
_WHITE_MIN_BRIGHTNESS = 210
_SILVER_BRIGHTNESS_RANGE = (140, 200)
_SILVER_MAX_SATURATION = 20

_CARD_TRIM_WIDTH_MM = 63
_CARD_TRIM_HEIGHT_MM = 88
_BLEED_MARGIN_MM = 3.175
TRIM_ASPECT_RATIO = _CARD_TRIM_WIDTH_MM / _CARD_TRIM_HEIGHT_MM
BLEED_ASPECT_RATIO = (_CARD_TRIM_WIDTH_MM + 2 * _BLEED_MARGIN_MM) / (_CARD_TRIM_HEIGHT_MM + 2 * _BLEED_MARGIN_MM)
_WIDTH_MARGIN_FRACTION = _BLEED_MARGIN_MM / (_CARD_TRIM_WIDTH_MM + 2 * _BLEED_MARGIN_MM)
_HEIGHT_MARGIN_FRACTION = _BLEED_MARGIN_MM / (_CARD_TRIM_HEIGHT_MM + 2 * _BLEED_MARGIN_MM)
_BLEED_CLASSIFICATION_TOLERANCE = 0.03


def classify_bleed_edge(size):
    width, height = size
    if height == 0:
        return None
    ratio = width / height
    dist_to_trim = abs(ratio - TRIM_ASPECT_RATIO)
    dist_to_bleed = abs(ratio - BLEED_ASPECT_RATIO)
    if min(dist_to_trim, dist_to_bleed) > _BLEED_CLASSIFICATION_TOLERANCE:
        return None
    return "bleed" if dist_to_bleed < dist_to_trim else "trimmed"


def normalize_crop_box(box, bleed_class):
    if bleed_class != "trimmed":
        return box
    left, top, right, bottom = box

    def _rescale(fraction, margin_fraction):
        return min(1.0, max(0.0, (fraction - margin_fraction) / (1 - 2 * margin_fraction)))

    return (
        _rescale(left, _WIDTH_MARGIN_FRACTION),
        _rescale(top, _HEIGHT_MARGIN_FRACTION),
        _rescale(right, _WIDTH_MARGIN_FRACTION),
        _rescale(bottom, _HEIGHT_MARGIN_FRACTION),
    )


# --------------------------------------------------------------------------------------------
# end verbatim
# --------------------------------------------------------------------------------------------


def cardspace_box(box, bleed_class):
    """Inverse of normalize_crop_box's intent: treat `box`'s fractions as fractions OF THE CARD
    and map them into the image's own coordinate space. Identity for 'trimmed' (card == image);
    for 'bleed' the card occupies [margin, 1-margin] on each axis, so a card fraction f maps to
    margin + f*(1-2*margin)."""
    if bleed_class != "bleed":
        return box
    left, top, right, bottom = box

    def _fwd(fraction, margin_fraction):
        return margin_fraction + fraction * (1 - 2 * margin_fraction)

    return (
        _fwd(left, _WIDTH_MARGIN_FRACTION),
        _fwd(top, _HEIGHT_MARGIN_FRACTION),
        _fwd(right, _WIDTH_MARGIN_FRACTION),
        _fwd(bottom, _HEIGHT_MARGIN_FRACTION),
    )


# cards.scryfall.io 400s python-requests' default UA (verified: default -> 400, curl/8.5.0 -> 200,
# browser UA -> 200), so a recognised UA is required to fetch at all.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/jpeg,image/png,image/*,*/*",
}
DELAY = 1.0


def fetch(url):
    key = hashlib.sha256(url.encode()).hexdigest()[:32] + ".img"
    path = os.path.join(CACHE, key)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return open(path, "rb").read()
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    with open(path, "wb") as fh:
        fh.write(resp.content)
    time.sleep(DELAY)
    return resp.content


def classify(brightness, saturation, uniform):
    """Verbatim decision ladder from classify_border_color."""
    if not uniform:
        return "borderless"
    if brightness <= _BLACK_MAX_BRIGHTNESS:
        return "black"
    if brightness >= _WHITE_MIN_BRIGHTNESS:
        return "white"
    if (
        _SILVER_BRIGHTNESS_RANGE[0] <= brightness <= _SILVER_BRIGHTNESS_RANGE[1]
        and saturation <= _SILVER_MAX_SATURATION
    ):
        return "silver"
    return None


def measure(image, boxes):
    width, height = image.size
    bands, samples, stds = [], [], []
    for name, (left, top, right, bottom) in zip(_BAND_NAMES, boxes):
        crop = image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height))).convert(
            "RGB"
        )
        pixels = list(crop.getdata())
        if not pixels:
            bands.append({"band": name, "n_px": 0, "degenerate": True})
            continue
        r = statistics.mean(p[0] for p in pixels)
        g = statistics.mean(p[1] for p in pixels)
        b = statistics.mean(p[2] for p in pixels)
        # the classifier keeps only the R-channel pstdev; G/B recorded for diagnosis
        std_r = statistics.pstdev([p[0] for p in pixels])
        samples.append((r, g, b))
        stds.append(std_r)
        bands.append(
            {
                "band": name,
                "box": [round(v, 5) for v in (left, top, right, bottom)],
                "r": round(r, 2),
                "g": round(g, 2),
                "b": round(b, 2),
                "brightness": round((r + g + b) / 3, 2),
                "saturation": round(max(r, g, b) - min(r, g, b), 2),
                "std_r": round(std_r, 2),
                "std_g": round(statistics.pstdev([p[1] for p in pixels]), 2),
                "std_b": round(statistics.pstdev([p[2] for p in pixels]), 2),
                "n_px": len(pixels),
            }
        )
    if not samples:
        return None
    avg_r = statistics.mean(s[0] for s in samples)
    avg_g = statistics.mean(s[1] for s in samples)
    avg_b = statistics.mean(s[2] for s in samples)
    brightness = (avg_r + avg_g + avg_b) / 3
    saturation = max(avg_r, avg_g, avg_b) - min(avg_r, avg_g, avg_b)
    mean_std = statistics.mean(stds)
    uniform = mean_std < _BORDER_UNIFORMITY_STD_THRESHOLD
    return {
        "avg_r": round(avg_r, 2),
        "avg_g": round(avg_g, 2),
        "avg_b": round(avg_b, 2),
        "brightness": round(brightness, 2),
        "saturation": round(saturation, 2),
        "mean_std_r": round(mean_std, 2),
        "uniform": uniform,
        "classifier_verdict": classify(brightness, saturation, uniform),
        "bands": bands,
    }


def main():
    samples = json.load(open(os.path.join(SCRATCH, "samples.json")))
    results = {"scryfall": [], "catalogue": []}
    for population in ("scryfall", "catalogue"):
        for rec in samples[population]:
            out = dict(rec)
            out["population"] = population
            try:
                img = Image.open(io.BytesIO(fetch(rec["url"])))
                img.load()
            except Exception as exc:  # noqa: BLE001
                out["error"] = f"{type(exc).__name__}: {exc}"
                results[population].append(out)
                print("FAIL", population, rec["border_color"], rec.get("name"), exc, file=sys.stderr, flush=True)
                continue
            bleed_class = classify_bleed_edge(img.size)
            out["image_w"], out["image_h"] = img.size
            out["aspect_ratio"] = round(img.size[0] / img.size[1], 5)
            out["bleed_class"] = bleed_class
            out["placements"] = {
                "raw": measure(img, _BORDER_SAMPLE_BANDS),
                "production": measure(img, [normalize_crop_box(b, bleed_class) for b in _BORDER_SAMPLE_BANDS]),
                "cardspace": measure(img, [cardspace_box(b, bleed_class) for b in _BORDER_SAMPLE_BANDS]),
            }
            results[population].append(out)
            p, c = out["placements"]["production"], out["placements"]["cardspace"]
            print(
                f"{population:9s} {rec['border_color']:10s} {str(bleed_class):8s} "
                f"prod[b={p['brightness']:6.1f} s={p['saturation']:6.1f} sd={p['mean_std_r']:5.1f} "
                f"-> {str(p['classifier_verdict']):10s}]  "
                f"card[b={c['brightness']:6.1f} s={c['saturation']:6.1f} sd={c['mean_std_r']:5.1f} "
                f"-> {str(c['classifier_verdict']):10s}]  {rec.get('name', '')[:30]}",
                flush=True,
            )
    with open(os.path.join(SCRATCH, "measurements.json"), "w") as fh:
        json.dump(results, fh, indent=1)


if __name__ == "__main__":
    main()
