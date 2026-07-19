"""
Permanent contract test, not a one-time check: federation-hash-tool/hash_my_cards.py is an
external artifact (docs/federation/public-export-v1.md §2) - any consumer who built their own
image-matching pipeline against its documented recipe expects our own content_phash computation
to keep matching it forever, not just as of whenever this test was written. If a future change to
classify_bleed_edge/normalize_crop_box/compute_card_art_hash ever drifts from what the reference
tool computes, this test turns that from a silent break in every external consumer's joins into a
red build with an explicit decision attached (version the recipe, or fix the drift) - see this
file's own tests for exactly what "drift" would look like.

Imports federation-hash-tool/hash_my_cards.py via sys.path, not a package install - that tool is
deliberately dependency-free of this Django app (see its own docstring), so the coupling only
exists here, in the direction that makes sense: the backend's tests depend on the tool's
reference implementation to check itself against, not the other way around.
"""

import sys
from pathlib import Path

from PIL import Image

from cardpicker.local_fallback import classify_bleed_edge, normalize_crop_box
from cardpicker.local_phash import ART_CROP_BOX, _int_to_hash, compute_card_art_hash

_FEDERATION_HASH_TOOL_DIR = Path(__file__).resolve().parents[3] / "federation-hash-tool"
if str(_FEDERATION_HASH_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_FEDERATION_HASH_TOOL_DIR))

from hash_my_cards import ART_CROP_BOX as reference_art_crop_box  # noqa: E402
from hash_my_cards import (  # noqa: E402
    classify_bleed_edge as reference_classify_bleed_edge,
)
from hash_my_cards import (  # noqa: E402
    compute_content_phash as reference_compute_content_phash,
)
from hash_my_cards import (  # noqa: E402
    normalize_crop_box as reference_normalize_crop_box,
)


def _make_striped_image(width: int, height: int) -> Image.Image:
    """A deterministic, non-uniform image - a solid color would hash identically regardless of
    crop-box drift, defeating the point of a parity check."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for x in range(0, width, 6):
        for y in range(0, height, 6):
            pixels[x, y] = (x % 256, y % 256, (x * y) % 256)
    return image


# A few real-shaped fixture images covering every branch classify_bleed_edge can take - not
# exhaustive, just enough that a crop-box or classification regression can't hide in an untested
# branch. Dimensions derived from the same reference geometry local_fallback.py itself uses
# (63x88mm trim, 3.175mm bleed margin), not arbitrary.
_BLEED_IMAGE = _make_striped_image(694, 944)  # ratio ~0.7351, close to BLEED_ASPECT_RATIO
_TRIMMED_IMAGE = _make_striped_image(630, 880)  # ratio 63/88 exactly = TRIM_ASPECT_RATIO
_ABSTAIN_IMAGE = _make_striped_image(500, 500)  # far from both references - classify_bleed_edge -> None
_LARGE_BLEED_IMAGE = _make_striped_image(1500, 2100)  # same "bleed" branch, different absolute size


class TestFederationHashToolParity:
    """Each test below independently confirms one property; test_full_hash_matches_on_every_fixture_image
    is the actual regression gate a future drift would trip - the individual tests exist to make a
    failure easy to localize (which step diverged) rather than just "something's different"."""

    def test_art_crop_box_constant_matches(self):
        assert ART_CROP_BOX == reference_art_crop_box

    def test_classify_bleed_edge_matches_on_every_fixture(self):
        for image in (_BLEED_IMAGE, _TRIMMED_IMAGE, _ABSTAIN_IMAGE, _LARGE_BLEED_IMAGE):
            assert classify_bleed_edge(image) == reference_classify_bleed_edge(image)

    def test_normalize_crop_box_matches_on_every_bleed_classification(self):
        for bleed_class in ("bleed", "trimmed", None):
            assert normalize_crop_box(ART_CROP_BOX, bleed_class) == reference_normalize_crop_box(
                reference_art_crop_box, bleed_class
            )

    def test_full_hash_matches_on_every_fixture_image(self):
        """The actual regression gate: end-to-end hash parity, not just its individual steps."""
        for image in (_BLEED_IMAGE, _TRIMMED_IMAGE, _ABSTAIN_IMAGE, _LARGE_BLEED_IMAGE):
            bleed_class = classify_bleed_edge(image)
            # compute_card_art_hash returns the internal signed two's-complement int
            # Card.content_phash is stored as - _int_to_hash converts it back to imagehash's own
            # hex-string form, matching what the reference tool and the export both use (see §1's
            # field note on this exact distinction; comparing raw ints here would be comparing
            # two different encodings, not the actual published contract).
            backend_int = compute_card_art_hash(image, bleed_class)
            backend_hex = str(_int_to_hash(backend_int))
            reference_hex = reference_compute_content_phash(image)
            assert backend_hex == reference_hex, (
                f"content_phash drift detected for a {bleed_class or 'ambiguous'} fixture image: "
                f"backend={backend_hex} reference_tool={reference_hex}. This means the published "
                "federation export recipe (docs/federation/public-export-v1.md §2) no longer "
                "matches what compute_card_art_hash actually computes - either update "
                "hash_my_cards.py to match the new backend behavior and bump record_version for "
                "any consumer relying on the old recipe, or this is an unintended regression in "
                "the backend change that introduced it."
            )
