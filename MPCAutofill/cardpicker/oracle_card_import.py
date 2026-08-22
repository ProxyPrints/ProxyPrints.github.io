import logging
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from django.conf import settings
from django.db import transaction

from cardpicker.integrations.game import scryfall_bulk_data
from cardpicker.models import CanonicalOracleCard
from cardpicker.utils import section_timer

logger = logging.getLogger(__name__)


# NOTE ON WHY THIS MODULE OWNS NO FETCH/DOWNLOAD OF ITS OWN. Unlike
# `printing_metadata_import.py` (which owns `default_cards.json`'s full remote-diff freshness
# check), this module is purely a READER of `scryfall_cache/oracle_cards.json` - the file
# `MTGIntegration.get_canonical_cards_and_artists` (cardpicker/integrations/game/mtg.py) already
# downloads and refreshes as part of its own weekly `CanonicalCard` import, and which had no
# other consumer before this module. Mirrors `printing_metadata_import.get_back_face_names`'s
# own "read the existing on-disk file, fetch nothing" contract against `default_cards.json`,
# for the same reason: a second, independently-scheduled fetch/freshness policy against a file
# another importer already owns would just be two writers racing on one cache path.
#
# WHY A SEPARATE TABLE FROM `CanonicalPrintingMetadata`. Oracle-level facts (oracle text, mana
# value, colours, legalities) are identical across every printing of a card, but
# `CanonicalPrintingMetadata` is 1:1 with `CanonicalCard`, i.e. per PRINTING - measured
# 2026-08-22: 113,224 printing rows carried them duplicated across only 35,990 distinct oracle
# cards actually represented in this catalogue (~3.15x duplication). `CanonicalOracleCard`,
# keyed on `canonical_id` (the oracle id), removes that duplication for these fields.
#
# `color_identity`/`type_line` are ALSO copied here (duplicating what `CanonicalPrintingMetadata`
# already stores), not moved: neither field has any reader today besides
# `printing_metadata_import._sync_printing_metadata`'s own diff/write path and the model
# definitions themselves (checked across the whole codebase, frontend included - the fields are
# write-only). Dropping a live column from a 113,224-row production table is a separate,
# deliberately-not-bundled migration; this module's own migration only ADDS a table, so this
# stays additive and safe to merge and deploy alone.


class OracleCardRow(BaseModel):
    """
    One row of Scryfall's `oracle_cards` bulk data - one row per DISTINCT ORACLE CARD, at
    exactly the grain oracle-level facts belong at. Measured against the live bulk file on
    2026-08-22 (38,626 rows): `cmc`, `color_identity`, `type_line` and `legalities` are present
    on every row; `oracle_text` is missing on 3,212 (all of which carry `card_faces` instead -
    no row lacks both); `colors` is missing on 2,824 (the `art_series`/`transform`/`modal_dfc`/
    `double_faced_token` layouts, which nest colours per-face instead of at the top level).

    THE JOIN KEY IS `oracle_id`, NOT THIS ROW'S OWN `id`. Verified against the live bulk file:
    `id` is the identifier of whichever specific printing Scryfall chose to represent the oracle
    card with (an arbitrary real printing's scryfall id), while `oracle_id` is the oracle
    identifier every printing of the card shares - the same value `CanonicalCard.canonical_id`
    already stores (`mtg.CardRow.oracle_id` on the `default_cards` side). The two differ on
    every single one of the 38,626 sampled rows.
    """

    oracle_id: uuid.UUID
    oracle_text: str = ""
    cmc: float = 0.0
    colors: list[str] = []
    color_identity: list[str] = []
    type_line: str = ""
    legalities: dict[str, str] = {}
    # Present only on double-faced/modal layouts - see resolved_oracle_text/resolved_colors below.
    card_faces: list[dict[str, Any]] | None = None

    @property
    def resolved_oracle_text(self) -> str:
        """
        Double-faced/modal oracle rows omit the top-level `oracle_text` entirely and nest each
        face's own text under `card_faces` instead. Joined with "\\n//\\n" - the same
        two-side/two-mode text-joining convention used elsewhere for these layouts - so a
        multi-faced oracle card still carries readable full text rather than an empty string.
        """
        if self.oracle_text:
            return self.oracle_text
        if self.card_faces:
            return "\n//\n".join(face.get("oracle_text", "") for face in self.card_faces)
        return ""

    @property
    def resolved_colors(self) -> list[str]:
        """
        Same top-level-vs-`card_faces` split as `resolved_oracle_text`, for `colors`. Faces'
        colours are unioned (order-preserving, no duplicates): `colors` at the oracle grain
        describes the whole card, not one face of it.
        """
        if self.colors:
            return self.colors
        if self.card_faces:
            merged: list[str] = []
            for face in self.card_faces:
                for colour in face.get("colors", []):
                    if colour not in merged:
                        merged.append(colour)
            return merged
        return []


def _cache_path() -> Path:
    # Same directory + filename `MTGIntegration.get_canonical_cards_and_artists` already writes
    # to (cardpicker/integrations/game/mtg.py) - this module reads that file, it does not own it.
    return Path(settings.BASE_DIR) / "scryfall_cache" / "oracle_cards.json"


def _parse_rows(path: Path) -> list[OracleCardRow]:
    rows = []
    for line in scryfall_bulk_data.iter_json_lines(path):
        try:
            rows.append(OracleCardRow.model_validate_json(line))
        except ValidationError:
            logger.warning("failed to validate line: %s", line)
    return rows


# The fields `_sync_oracle_cards` writes on CanonicalOracleCard - the single source of truth for
# both the diff comparison and the bulk_update call, mirroring
# `printing_metadata_import._METADATA_SYNC_FIELDS`. `canonical_id` is the table's primary key
# and the diff's join key, so it is deliberately not in this list.
_ORACLE_SYNC_FIELDS = ["oracle_text", "cmc", "colors", "color_identity", "type_line", "legalities"]

# Read/write chunk sizes for `_sync_oracle_cards` - same shape and same reasoning as
# `printing_metadata_import._METADATA_READ_CHUNK_SIZE`/`_METADATA_WRITE_BATCH_SIZE`: the read
# side streams existing rows so the whole table is never materialised at once, and the write
# side bounds every INSERT/UPDATE/DELETE statement to this many rows.
_ORACLE_READ_CHUNK_SIZE = 2000
_ORACLE_WRITE_BATCH_SIZE = 1000


def _sync_oracle_cards(oracle_rows: list[CanonicalOracleCard]) -> dict[str, int]:
    """
    Diff-aware, batched sync of `CanonicalOracleCard` against the parsed bulk rows - the same
    shape as `printing_metadata_import._sync_printing_metadata`, adopted here on purpose rather
    than reaching for `bulk_sync(filters=None)` again: that call's single whole-table CASE-WHEN
    UPDATE is what OOM-killed a postgres backend on `CanonicalPrintingMetadata`'s first prod run
    (see that function's own docstring). `CanonicalOracleCard` is far smaller (~38,626 rows
    against 113,224), but the failure mode scales with statement size, not just row count, and
    there's no reason to reintroduce it here.

    Returns stats {created, updated, deleted, skipped} where `skipped` counts unchanged rows.
    """
    desired_by_id = {row.canonical_id: row for row in oracle_rows}
    existing_ids: set[uuid.UUID] = set()
    to_update: list[CanonicalOracleCard] = []
    stale_ids: list[uuid.UUID] = []
    unchanged = 0

    existing_rows = CanonicalOracleCard.objects.values("canonical_id", *_ORACLE_SYNC_FIELDS).iterator(
        chunk_size=_ORACLE_READ_CHUNK_SIZE
    )
    for existing in existing_rows:
        canonical_id = existing["canonical_id"]
        existing_ids.add(canonical_id)
        desired = desired_by_id.get(canonical_id)
        if desired is None:
            stale_ids.append(canonical_id)
        elif any(existing[field] != getattr(desired, field) for field in _ORACLE_SYNC_FIELDS):
            to_update.append(desired)
        else:
            unchanged += 1

    to_create = [row for key, row in desired_by_id.items() if key not in existing_ids]

    with transaction.atomic():
        CanonicalOracleCard.objects.bulk_create(to_create, batch_size=_ORACLE_WRITE_BATCH_SIZE)
        if to_update:
            CanonicalOracleCard.objects.bulk_update(
                to_update, fields=_ORACLE_SYNC_FIELDS, batch_size=_ORACLE_WRITE_BATCH_SIZE
            )
        for i in range(0, len(stale_ids), _ORACLE_WRITE_BATCH_SIZE):
            CanonicalOracleCard.objects.filter(canonical_id__in=stale_ids[i : i + _ORACLE_WRITE_BATCH_SIZE]).delete()

    return {"created": len(to_create), "updated": len(to_update), "deleted": len(stale_ids), "skipped": unchanged}


@section_timer(name="import scryfall oracle cards")
def import_scryfall_oracle_cards(oracle_cards_path: Path | None = None) -> dict[str, Any]:
    """
    Populates `CanonicalOracleCard` from the cached `oracle_cards` bulk-data file. Reads only -
    see this module's own docstring for why fetch/refresh is deliberately not this function's
    job. Does not touch `CanonicalCard` at all: this is a pure oracle_cards-bulk-data ->
    `CanonicalOracleCard` sync, with no join against our own printing rows (a `CanonicalCard`
    whose `canonical_id` is `None` simply has no matching row here - nothing about that state
    is read or written by this function).
    """
    path = oracle_cards_path or _cache_path()
    rows = _parse_rows(path)

    oracle_rows = [
        CanonicalOracleCard(
            canonical_id=row.oracle_id,
            oracle_text=row.resolved_oracle_text,
            cmc=row.cmc,
            colors=row.resolved_colors,
            color_identity=row.color_identity,
            type_line=row.type_line,
            legalities=row.legalities,
        )
        for row in rows
    ]

    stats = _sync_oracle_cards(oracle_rows)
    logger.info(
        "CanonicalOracleCard sync: %(created)d created, %(updated)d updated, "
        "%(deleted)d deleted, %(skipped)d skipped",
        stats,
    )
    return stats


__all__ = ["OracleCardRow", "import_scryfall_oracle_cards"]
