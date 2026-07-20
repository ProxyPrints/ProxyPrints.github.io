"""
Pure image-math helpers for Stage C's `color_profile`/`quality_signals` extractors (public issue
#150's re-spec, docs/features/catalog-completion-plan.md's Stage C section): color statistics
and blur/entropy/integrity signals, all computed against an already-fetched in-memory PIL Image
and returned as plain numbers - no DB access, no candidate matching, no verdicts. Metadata-only
per the Governing posture (CLAUDE.md's "Governing premise"): every function here returns scalars/
short lists of floats, never a crop or a re-encoded image.

NOT protected core (`docs/upstreaming/license-provenance.md` §2 lists the exact file set - this
module isn't on it) - unlike `local_fallback.py`/`local_phash.py`, new helpers land here directly,
the same convention `local_ocr.py`'s own module docstring precedent already established for
OCR-adjacent (non-protected) additions.

Every technique here is a standard, widely-documented generic image-processing method, not a
ported implementation from any specific external codebase (matching this repo's own provenance
sweep finding for `local_phash.py`/`local_fallback.py` - see license-provenance.md §1.7):

- `is_image_truncated`: attempts a full pixel decode (`Image.load()`); Pillow raises `OSError`
  for a genuinely truncated/corrupt download (verified empirically against a real half-written
  JPEG before this was wired into the extractor - see image_evidence.py's own module docstring
  for why this has to run before color/blur/entropy, not after).
- `compute_blur_variance`: the variance of a Laplacian-kernel edge response over the grayscale
  image - a standard sharpness/blur proxy (lower variance = flatter edge response = blurrier)
  described in countless public image-processing references, not any one paper or codebase.
  Implemented via `PIL.ImageFilter.Kernel` + `PIL.ImageStat.Stat.var` - both first-party Pillow
  APIs, no hand-rolled convolution or extra numpy dependency needed.
- `compute_entropy`: `PIL.Image.entropy()` - a built-in Pillow method, not reimplemented here at
  all.
- `compute_color_profile`: per-channel (R, G, B) mean and population standard deviation over the
  full image via `PIL.ImageStat.Stat` - again a first-party Pillow API, no manual pixel loop.
"""

from typing import TYPE_CHECKING

from PIL import ImageFilter, ImageStat

if TYPE_CHECKING:
    from PIL import Image

# A discrete 3x3 Laplacian kernel (the standard "4-neighbor" form: center weight -4, the four
# orthogonal neighbors weight 1, diagonals 0) - a generic edge-detection kernel, not tuned or
# calibrated against this project's own images. `scale=1` keeps the kernel's own literal weights
# (they already sum to zero, the customary normalization for a Laplacian - no additional scaling
# needed).
_LAPLACIAN_KERNEL = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1)


def is_image_truncated(image: "Image.Image") -> bool:
    """
    Forces a full pixel decode via `Image.load()` - Pillow only lazily decodes on `Image.open()`,
    so a download that was cut off partway through can open successfully (dimensions/format are
    readable from the header) and only raise `OSError` once something actually reads every pixel.
    True only for a genuine decode failure - any other exception is left to propagate, since this
    function's only job is answering "did the full image data decode cleanly," not swallowing
    unrelated errors.
    """
    try:
        image.load()
    except OSError:
        return True
    return False


def compute_blur_variance(image: "Image.Image") -> float:
    """
    Variance of a Laplacian-kernel edge response over the grayscale image - a standard blur proxy
    (lower variance = flatter/smoother edge response = blurrier). Raw signal only: this function
    does not decide what variance counts as "too blurry" - that's a Stage D calculator's job, once
    a real threshold is calibrated against real data (this project's own "config values land only
    from measurement, not automatically" rule - see docs/features/catalog-completion-plan.md's
    concurrency-probe section for the same rule applied elsewhere).

    The outermost 1-pixel border is cropped out of the filtered result before computing variance
    - `PIL.ImageFilter.Kernel`'s own documented edge behavior leaves a pixel it can't fully
    convolve (no full 3x3 neighborhood available) copied through from the SOURCE image rather
    than filtered, which would otherwise inject a spurious, image-independent contribution into
    the variance (verified empirically: a perfectly flat solid-color image reports an exact-zero
    interior Laplacian response, but a nonzero border-pixel-driven variance without this crop).
    """
    grayscale = image.convert("L")
    edges = grayscale.filter(_LAPLACIAN_KERNEL)
    width, height = edges.size
    interior = edges.crop((1, 1, width - 1, height - 1)) if width > 2 and height > 2 else edges
    return float(ImageStat.Stat(interior).var[0])


def compute_entropy(image: "Image.Image") -> float:
    """Shannon entropy of the grayscale pixel-value histogram, via Pillow's own `Image.entropy()`
    - a lower value flags a near-blank/near-solid-color image (a genuine integrity signal - a
    near-featureless "card" is often a fetch that returned a placeholder or error graphic rather
    than real card art), reported as a raw number, never a verdict."""
    return float(image.convert("L").entropy())


def compute_color_profile(image: "Image.Image") -> tuple[list[float], list[float]]:
    """
    Per-channel (R, G, B) mean and population standard deviation over the FULL fetched image, via
    `PIL.ImageStat.Stat` - "color statistics... store the math, not the strip" (FINAL POSTURE
    item 2). Returns `(mean_rgb, stddev_rgb)`, each a 3-element list of floats in `[0, 255]`.
    """
    stat = ImageStat.Stat(image.convert("RGB"))
    return list(stat.mean), list(stat.stddev)


__all__ = ["is_image_truncated", "compute_blur_variance", "compute_entropy", "compute_color_profile"]
