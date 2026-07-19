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


def fetch_card_image(card: "Card", dpi: Optional[int] = DEFAULT_FETCH_DPI) -> Optional["Image.Image"]:
    from PIL import Image

    url = get_worker_image_url(card, dpi)
    if url is None:
        return None
    try:
        response = rate_limited_get(GOOGLE_IMAGE, url, timeout=15)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
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


__all__ = ["DEFAULT_FETCH_DPI", "get_worker_image_url", "fetch_card_image"]
