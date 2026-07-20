"""
Shared CDN image-fetch helpers for OUR OWN uploaded card images (image-cdn/, docs/features/
image-cdn.md's Worker + R2 bucket) - Google Drive sources only, matching that Worker's current
scope. Extracted from cardpicker.local_identify_printing_tags (2026-07-16, hash-at-ingest work)
since a second, non-pilot caller (cardpicker.sources.update_database's ingest hook) now needs
the exact same fetch, and that ingest pipeline should not depend on the pilot orchestration
module for something this foundational.

Not for Scryfall/candidate images - see cardpicker.local_phash's own Scryfall fetch helpers for
that separate concern.

`fetch_card_image` is paced via `cardpicker.harvest_fetch_limiter.GOOGLE_IMAGE` (Stage B split
limiter, docs/features/catalog-completion-plan.md's "Harvest-calculate pipeline" section,
2026-07-19) - every caller (this pilot, the harvest pipeline, the ingest hook) shares one
process-wide ceiling on Google lh3/lh4, regardless of which caller's thread pool is doing the
fetching.
"""

import logging
from io import BytesIO
from typing import TYPE_CHECKING, Optional

from django.conf import settings

from cardpicker.harvest_fetch_limiter import (
    GOOGLE_IMAGE,
    GoogleFetchLockoutError,
    rate_limited_get,
)
from cardpicker.sources.source_types import SourceTypeChoices

if TYPE_CHECKING:
    from PIL import Image

    from cardpicker.models import Card

logger = logging.getLogger(__name__)

# Print/PDF-export-quality default, used by the pilot's OCR/phash/fallback engines - a safety
# margin above the empirically-best 200 (see docs/features/printing-tags.md's addendum item 4),
# not the raw optimum. PILOT-ONLY in spirit: this constant predates hash-at-ingest and stays the
# default for engines that need to actually read the image (OCR text, fine phash detail);
# hash-at-ingest deliberately overrides it with a much smaller size (see local_phash's
# INGEST_HASH_FETCH_DPI) since phash's own internal downsampling makes the extra resolution
# unnecessary for hashing specifically.
DEFAULT_FETCH_DPI: Optional[int] = 250


def get_worker_image_url(card: "Card", dpi: Optional[int] = DEFAULT_FETCH_DPI) -> Optional[str]:
    """
    The card's image via the image CDN Worker's "full" tier (image-cdn/, docs/features/image-cdn.md)
    - the same route the PDF export path uses, but at a resolution capped via `dpi` rather than
    the print-quality original PDF export needs. Google Drive sources only, matching that
    Worker's current scope (frontend/src/common/image.ts's getWorkerImageURL has the identical
    restriction) - any other source type returns None, counted by the caller as an
    "unsupported-source-type" skip.

    `dpi` MUST be a multiple of 10 - the Worker's dpi-to-pixel-height conversion
    (image-cdn/src/url.ts, height = dpi * 1110 / 300) isn't rounded, and Google's own `lh4`
    resize endpoint flat-out rejects a non-integer height param with a 400 (confirmed live,
    2026-07-16 - see "Phash accuracy at small CDN sizes" in docs/features/printing-tags.md).
    Not validated here (the caller already only ever passes known-good constants); documented so
    a future caller doesn't get bitten by an opaque 400.
    """
    if card.get_source_type_choices() != SourceTypeChoices.GOOGLE_DRIVE:
        return None
    dpi_param = f"&dpi={dpi}" if dpi is not None else ""
    return f"{settings.IMAGE_WORKER_URL}/images/google_drive/full/{card.identifier}.jpg?jpgQuality=100{dpi_param}"


def fetch_card_image_bytes(card: "Card", dpi: Optional[int] = DEFAULT_FETCH_DPI) -> Optional[bytes]:
    """
    Fetch-only half of `fetch_card_image` below - does the paced network call and returns the
    raw (still-encoded, e.g. JPEG) response bytes, without ever decoding them into a `PIL.Image`.
    Split out 2026-07-20 (Stage C fetch/compute decoupling design,
    docs/features/catalog-completion-plan.md's Stage C section, #228) so a fetch-stage caller
    (`run_image_evidence_cohort.py`'s fetch thread pool) can hand a buffer across a process
    boundary as plain `bytes` - cheap to pickle, no forced pixel decode - and let the RECEIVING
    compute worker do the actual `Image.open()` lazily, preserving the same "decode only happens
    where the compute cost is meant to be spent" property this function's own caller below
    already had before this split (`Image.open()` itself is lazy - the real pixel decode happens
    on first access like `.crop()`/`.size`, which now happens inside the compute-only step).
    """
    url = get_worker_image_url(card, dpi)
    if url is None:
        return None
    try:
        response = rate_limited_get(GOOGLE_IMAGE, url, timeout=15)
        response.raise_for_status()
        return response.content
    except GoogleFetchLockoutError:
        # Deliberately NOT caught by the broad except below - a 403 lockout is a hard stop
        # (see GoogleFetchLockoutError's own docstring), not an ordinary per-card fetch failure.
        # Swallowing this here would silently let a long-running harvest keep hammering a
        # destination that has already locked us out, risking the live site's own image
        # serving (which shares this same Google endpoint) for an extended cooldown window.
        raise
    except Exception:
        logger.exception("Failed to fetch image for card %s", card.identifier)
        return None


def fetch_card_image(card: "Card", dpi: Optional[int] = DEFAULT_FETCH_DPI) -> Optional["Image.Image"]:
    """Thin decode wrapper around `fetch_card_image_bytes` above - unchanged signature/behavior
    for this function's existing callers (`extract_card_evidence`, the ingest hook in
    `cardpicker.sources.update_database`). Not used by the decoupled fetch stage in
    `run_image_evidence_cohort.py` - that caller wants the raw bytes above instead, precisely to
    avoid decoding on the fetch side (see that function's own docstring)."""
    from PIL import Image

    data = fetch_card_image_bytes(card, dpi)
    if data is None:
        return None
    return Image.open(BytesIO(data))


__all__ = ["DEFAULT_FETCH_DPI", "get_worker_image_url", "fetch_card_image", "fetch_card_image_bytes"]
