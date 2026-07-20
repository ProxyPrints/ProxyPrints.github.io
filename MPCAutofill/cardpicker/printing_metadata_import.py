import logging
import time
import uuid
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from bulk_sync import bulk_sync
from pydantic import BaseModel, ValidationError

from django.conf import settings

from cardpicker.integrations.game.mtg import Scryfall
from cardpicker.models import CanonicalCard, CanonicalPrintingMetadata
from cardpicker.utils import section_timer

logger = logging.getLogger(__name__)

# Scryfall `layout` values that mean "a real double-faced physical card" (a distinct front and
# back, both represented on this same bulk-data row via `card_faces[0]`/`card_faces[1]`) - per
# public issue #199's owner-settled definition: "a name that is the second face of a
# double-faced-card layout is a back face." Deliberately narrower than "any row with 2+
# card_faces": `split`/`flip`/`adventure`/`aftermath`/`mutate`/`prototype` also nest multiple
# named modes under `card_faces`, but those modes are printed on the SAME (single) face of the
# card, not front/back - naively trusting card_faces length alone would misflag e.g. Adventure's
# spell side ("Stomp") as a back face of "Bonecrusher Giant" when it's just a second mode on the
# same face. `art_series` is excluded too (its own "back" is a generic Art Series card back, not
# a second face of THIS card) - the same exclusion `MTGIntegration.DFC_SCRYFALL_QUERY` already
# makes for its own (live-API-sourced) DFCPair table. `meld` is out of scope entirely: meld
# pieces are single-faced (no `card_faces` on their own bulk-data row at all - Scryfall
# represents the merged result via `all_parts` on the *meld_result* card instead, which is why
# `MTGIntegration.get_meld_pairs` reads a completely different shape), so this on-disk,
# card_faces-only definition structurally cannot see them - a real, owner-definition-driven scope
# gap, not an oversight. See `get_back_face_names`'s own docstring.
DOUBLE_FACED_LAYOUTS = frozenset({"transform", "modal_dfc", "double_faced_token", "battle", "reversible_card"})


class BulkDataEntry(BaseModel):
    type: str
    download_uri: str


class BulkDataResponse(BaseModel):
    data: list[BulkDataEntry]


class PrintingMetadataRow(BaseModel):
    id: uuid.UUID
    lang: str = "en"
    released_at: date | None = None
    full_art: bool = False
    border_color: str = ""
    frame: str = ""
    frame_effects: list[str] = []
    promo_types: list[str] = []
    edhrec_rank: int | None = None
    # Scryfall's bulk-data card object already carries this - single-faced cards have it
    # top-level, double-faced cards nest it under the first face instead (Scryfall's own
    # documented convention). Extra top-level keys the model doesn't declare (name, mana_cost,
    # etc.) are silently ignored by pydantic, same as every other field on this row.
    image_uris: dict[str, str] | None = None
    card_faces: list[dict[str, Any]] | None = None
    # Scryfall's own layout tag (e.g. "normal", "transform", "modal_dfc", "adventure") - used by
    # get_back_face_names below to tell a genuine double-faced card's second face apart from a
    # split/adventure/flip card's second MODE (both shapes nest under card_faces, only the former
    # is actually printed on the back of the physical card). See DOUBLE_FACED_LAYOUTS' own comment.
    layout: str = ""

    @property
    def art_crop_url(self) -> str:
        if self.image_uris is not None:
            return self.image_uris.get("art_crop", "")
        if self.card_faces:
            return self.card_faces[0].get("image_uris", {}).get("art_crop", "")
        return ""


def _cache_path() -> Path:
    return Path(settings.BASE_DIR) / "scryfall_cache" / "default_cards.json"


def _is_stale(path: Path) -> bool:
    return not path.exists() or time.time() - path.stat().st_mtime > 7 * 24 * 3600


@section_timer(name="get default_cards bulk data URL")
def _get_default_cards_url() -> str:
    response = requests.get("https://api.scryfall.com/bulk-data", headers=Scryfall.get_headers())
    assert response.status_code == 200
    parsed = BulkDataResponse.model_validate_json(response.text)
    matches = [entry for entry in parsed.data if entry.type == "default_cards"]
    assert matches, "Scryfall bulk-data response did not contain a 'default_cards' entry"
    return matches.pop().download_uri


@section_timer(name="download default_cards bulk data")
def _download_default_cards(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading default_cards bulk data from %s", url)
    with requests.get(url, stream=True, headers=Scryfall.get_headers()) as r:
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def _parse_rows(path: Path) -> list[PrintingMetadataRow]:
    rows = []
    with open(path, "rb") as f:
        for raw_line in f:
            line = raw_line.rstrip(b"\n")
            if line in [b"[", b"]"]:
                continue
            decoded_line = line.decode("utf-8").rstrip(",")
            try:
                rows.append(PrintingMetadataRow.model_validate_json(decoded_line))
            except ValidationError:
                logger.warning("failed to validate line: %s", decoded_line)
    return rows


@lru_cache(maxsize=8)
def _load_back_face_names(path_str: str) -> frozenset[str]:
    """
    Cached worker behind `get_back_face_names` - keyed on the resolved path string so distinct
    bulk-data files (e.g. one per test) never share a cache entry, while repeated lookups against
    the same real on-disk file within one process (the common case - this is called once per
    card, not once per run) only ever parse it once. The cache is intentionally never invalidated
    within a process lifetime: the bulk file itself only refreshes weekly at most (see
    `_is_stale`), matching the same "reused within the 7-day window" tolerance
    `import_scryfall_printing_metadata`'s own cache already assumes.
    """
    path = Path(path_str)
    if not path.exists():
        logger.warning(
            "Scryfall bulk-data file not found at %s - back-face lookup returning an empty set "
            "(no network fetch is performed here; see get_back_face_names' own docstring)",
            path,
        )
        return frozenset()

    back_face_names: set[str] = set()
    for row in _parse_rows(path):
        if row.layout not in DOUBLE_FACED_LAYOUTS:
            continue
        if row.card_faces is None or len(row.card_faces) < 2:
            continue
        back_name = row.card_faces[1].get("name")
        if back_name:
            back_face_names.add(back_name)
    return frozenset(back_face_names)


def get_back_face_names(default_cards_path: Path | None = None) -> frozenset[str]:
    """
    Public issue #199's back-face determination: a deterministic name -> "is this a back face"
    lookup built entirely from the Scryfall bulk data ALREADY on disk
    (`scryfall_cache/default_cards.json`, the same file `import_scryfall_printing_metadata`
    parses) - no network fetch, no downloader, per the owner's settled design
    ("back-face is determined from the card's NAME via Scryfall... reads the EXISTING on-disk
    bulk data"). For every row whose `layout` is a genuine double-faced layout (see
    DOUBLE_FACED_LAYOUTS), the SECOND face's name (`card_faces[1]["name"]`) is a back face -
    `card_faces[0]` is always the front. This is a small addition to the existing metadata-import
    parsing path (`_parse_rows`), not new plumbing: it does not download or cache-refresh the
    bulk file itself, and returns an empty set (logging a warning, never raising) if the file
    isn't present yet, rather than triggering a fetch.

    Deliberately does NOT cover meld back faces - meld pieces have no `card_faces` of their own in
    this bulk data at all (see DOUBLE_FACED_LAYOUTS' own comment for why), so this name/card_faces
    -based definition structurally cannot see them. That's a real, owner-definition-driven scope
    gap, not a bug in this function.
    """
    path = default_cards_path or _cache_path()
    return _load_back_face_names(str(path))


def is_back_face(name: str, default_cards_path: Path | None = None) -> bool:
    """
    True if `name` is a known back face per `get_back_face_names` - the single-string
    convenience form of the same lookup (e.g. for checking one `Card.name` at a time) rather than
    a caller pulling the whole set themselves.
    """
    return name in get_back_face_names(default_cards_path)


@section_timer(name="import scryfall printing metadata")
def import_scryfall_printing_metadata(default_cards_path: Path | None = None) -> dict[str, Any]:
    """
    Enriches every existing `CanonicalCard` with Scryfall printing metadata fields that
    `CanonicalCard` doesn't itself store (full art, border colour, frame, promo types,
    EDHREC rank, release date, language, and a denormalised printings-per-oracle-card
    count). Only enriches rows that `CanonicalCard`'s own weekly import
    (`import_canonical_card_data`) has already decided are canonical - this command does
    no filtering of its own (no separate paper/language/digital rules), since that
    filtering boundary already lives in `MTGIntegration.get_canonical_cards_and_artists`.

    Reuses the same bulk-data cache location (`scryfall_cache/default_cards.json`) that
    `import_canonical_card_data` uses, so if both commands run within the same 7-day
    window, only one of them actually downloads the file.
    """
    path = default_cards_path or _cache_path()
    if default_cards_path is None:
        if _is_stale(path):
            url = _get_default_cards_url()
            _download_default_cards(url, path)
        else:
            logger.info("Using cached default cards at %s", path)

    rows = _parse_rows(path)

    identifier_to_pk: dict[uuid.UUID, int] = {}
    pk_to_canonical_id: dict[int, uuid.UUID | None] = {}
    canonical_id_counts: Counter[uuid.UUID] = Counter()
    for identifier, pk, canonical_id in CanonicalCard.objects.values_list("identifier", "pk", "canonical_id"):
        identifier_to_pk[identifier] = pk
        pk_to_canonical_id[pk] = canonical_id
        if canonical_id is not None:
            canonical_id_counts[canonical_id] += 1

    metadata_rows: list[CanonicalPrintingMetadata] = []
    skipped = 0
    for row in rows:
        canonical_card_pk = identifier_to_pk.get(row.id)
        if canonical_card_pk is None:
            skipped += 1
            continue
        canonical_id = pk_to_canonical_id[canonical_card_pk]
        printings_count = canonical_id_counts[canonical_id] if canonical_id is not None else 1
        metadata_rows.append(
            CanonicalPrintingMetadata(
                canonical_card_id=canonical_card_pk,
                full_art=row.full_art,
                border_color=row.border_color,
                frame=row.frame,
                frame_effects=row.frame_effects,
                promo_types=row.promo_types,
                edhrec_rank=row.edhrec_rank,
                printings_count=printings_count,
                released_at=row.released_at,
                lang=row.lang,
                art_crop_url=row.art_crop_url,
            )
        )

    logger.info("Skipped %d row(s) with no matching CanonicalCard", skipped)
    result = bulk_sync(
        new_models=metadata_rows,
        key_fields=["canonical_card_id"],
        db_class=CanonicalPrintingMetadata,
        filters=None,
    )
    stats = dict(result["stats"])
    stats["skipped"] = skipped
    logger.info(
        "CanonicalPrintingMetadata sync: %(created)d created, %(updated)d updated, "
        "%(deleted)d deleted, %(skipped)d skipped",
        stats,
    )
    return stats
