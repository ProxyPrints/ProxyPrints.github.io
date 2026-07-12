import logging
import time
import uuid
from collections import Counter
from datetime import date
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
