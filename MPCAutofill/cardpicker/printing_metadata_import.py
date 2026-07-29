import json
import logging
import uuid
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction

from cardpicker.integrations.game import scryfall_bulk_data
from cardpicker.integrations.game.scryfall_bulk_data import BulkDataEntry
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


# NOTE: this module used to declare its OWN `BulkDataEntry`/`BulkDataResponse` models here.
# They now live in ONE place - `cardpicker.integrations.game.scryfall_bulk_data` - which is what
# `_get_default_cards_entry` below returns and what `_is_fresh`/`_write_sidecar` annotate
# against. See that module's docstring for why three separate copies of this same model existed
# across three importers, and why exactly one of them survived Scryfall's 2026-07-20 retirement
# of `download_uri`/`size`.


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
    # Scryfall's own illustration UUID — identifies the artwork independently of any specific
    # printing. Single-faced cards carry it at the top level; double-faced cards nest it inside
    # each element of card_faces (one illustration per face). The resolved_illustration_id
    # property below normalises both shapes into one value for the import path.
    illustration_id: uuid.UUID | None = None
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
    def resolved_illustration_id(self) -> uuid.UUID | None:
        if self.illustration_id is not None:
            return self.illustration_id
        if self.card_faces:
            raw = self.card_faces[0].get("illustration_id")
            if raw is not None:
                return uuid.UUID(raw) if isinstance(raw, str) else raw
        return None

    @property
    def face_illustrations(self) -> list[dict[str, Any]]:
        """
        EVERY face's own `illustration_id`, paired with that face's own name, in `card_faces`
        order (index 0 is the front) - the data `resolved_illustration_id` above flattens away.
        Persisted to `CanonicalPrintingMetadata.face_illustrations`; see that field's own comment
        for the storage-shape reasoning.

        RETURNS `[]` FOR ANYTHING THAT IS NOT A GENUINE DOUBLE-FACED CARD, gated on the SAME
        `DOUBLE_FACED_LAYOUTS` allowlist `get_back_face_names` uses (see that constant's own
        comment). `split`/`adventure`/`flip`/`aftermath`/`mutate`/`prototype` rows also nest
        multiple named modes under `card_faces`, but those modes share ONE printed face - emitting
        an entry per mode would assert a second scannable side that does not physically exist,
        and would let a scan of "Bonecrusher Giant" be attributed to the "Stomp" artwork. Rows
        with fewer than two faces return `[]` for the same reason: there is no second side to
        record, and the scalar `illustration_id` already covers the only artwork present.

        A face with no `illustration_id` of its own (Scryfall omits it for faces without art)
        records `None` rather than being dropped, so the list's INDEX still corresponds to the
        face's position - a consumer that walks `card_faces[1]` must not have the list silently
        shift under it.
        """
        if self.layout not in DOUBLE_FACED_LAYOUTS:
            return []
        if not self.card_faces or len(self.card_faces) < 2:
            return []
        faces: list[dict[str, Any]] = []
        for face in self.card_faces:
            raw = face.get("illustration_id")
            faces.append(
                {
                    "name": face.get("name") or "",
                    "illustration_id": str(raw) if raw is not None else None,
                }
            )
        return faces

    @property
    def art_crop_url(self) -> str:
        if self.image_uris is not None:
            return self.image_uris.get("art_crop", "")
        if self.card_faces:
            return self.card_faces[0].get("image_uris", {}).get("art_crop", "")
        return ""


def _cache_path() -> Path:
    return Path(settings.BASE_DIR) / "scryfall_cache" / "default_cards.json"


def _sidecar_path(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def _write_sidecar(path: Path, entry: BulkDataEntry) -> None:
    """
    Issue #513: records the remote `updated_at`/size of the bulk entry `path` was just
    downloaded from, next to the cache itself (e.g. `default_cards.meta.json`) - `_is_fresh`'s
    only input on later runs. Written AFTER `_download_default_cards`'s atomic replace has
    landed, so a sidecar on disk always describes the cache file beside it; if this write
    itself fails, the next run simply sees no/stale sidecar and re-downloads once (the safe
    direction).

    THE `size` KEY NOW CARRIES A DIFFERENT QUANTITY. Scryfall retired the entry's `size`
    (uncompressed byte count) in favour of `compressed_size` (the size of the gzipped `.jsonl.gz`
    artefact actually served - ~77MB against ~620MB uncompressed for default_cards). The sidecar
    key is deliberately left named `size` so an already-deployed sidecar written before the
    cutover still parses, and because `_is_fresh` compares `updated_at` ONLY - this value is a
    recorded secondary change detector, never a byte budget. DO NOT read a sidecar's `size` as
    "how many bytes the cache file on disk is": before 2026-07-20 it was, and now it is not.
    """
    _sidecar_path(path).write_text(json.dumps({"updated_at": entry.updated_at, "size": entry.compressed_size}))


def _is_fresh(path: Path, entry: BulkDataEntry) -> bool:
    """
    Issue #513's remote-diff freshness check - replaces the old `_is_stale` 7-day mtime
    heuristic with the remote bulk entry's own `updated_at` as the authority: the cache is
    fresh only if it exists on disk AND the sidecar written at its download time records the
    same `updated_at` the /bulk-data API currently reports. An unchanged remote therefore never
    re-downloads (whatever the local mtime), and a changed remote always does. A missing or
    unreadable sidecar means stale - the first run after this deploys has no sidecar yet, so it
    re-downloads once (intended).
    """
    if not path.exists():
        return False
    try:
        meta = json.loads(_sidecar_path(path).read_text())
    except (OSError, ValueError):  # missing/unreadable sidecar, invalid UTF-8, invalid JSON
        return False
    return isinstance(meta, dict) and meta.get("updated_at") == entry.updated_at


def ensure_scryfall_cache_present(default_cards_path: Path | None = None) -> None:
    """
    Fail-loud staleness guard (issue #402). The Scryfall bulk-data cache
    (`scryfall_cache/default_cards.json`, ~558MB) lived as a plain file inside the django/worker
    container filesystem with no persistent volume mounted over it - every image rebuild silently
    destroyed it. Deploy-2 (2026-07-23) did exactly that, and `local_calculate_verdicts` went on
    to run degraded: `get_back_face_names`/`is_back_face` (see their own docstrings) treat a
    missing file as "no back faces known yet" - logging one warning and returning an empty
    `frozenset()` - which is the right behaviour for THAT function (a per-card lookup has no
    business raising), but left the whole run silently degraded with nothing loud enough to catch
    in a routine log skim.

    This is the loud counterpart: call it ONCE, at a long-running command's own start (see
    `local_calculate_verdicts`'s `Command.handle()`), BEFORE any card-by-card work begins. Raises
    `CommandError` immediately if the cache file does not exist. Callers that have deliberately
    decided to accept the degraded (empty back-face lookup) mode - e.g. a fresh bootstrap that
    hasn't run `import_scryfall_printing_metadata`/`import_canonical_card_data` yet - should catch
    this by not calling the guard at all (an explicit `--allow-missing-scryfall-cache`-style flag
    at the call site), rather than this function growing its own bypass flag.

    Deliberately checks EXISTENCE only, not staleness - freshness is a completely separate,
    already-working concern (`import_scryfall_printing_metadata` re-fetches whenever the remote
    bulk entry's `updated_at` differs from the download-time sidecar - see `_is_fresh` - and
    `import_canonical_card_data` applies its own heuristic, each on its own next run); this
    guard only exists to catch the file being GONE.
    """
    path = default_cards_path or _cache_path()
    if not path.exists():
        raise CommandError(
            f"SCRYFALL CACHE MISSING: {path} does not exist. This is the persistent "
            "scryfall_cache volume (docker/docker-compose.prod.yml) backing "
            "get_back_face_names/is_back_face's back-face lookup - proceeding without it "
            "silently degrades that lookup to an empty set (see printing_metadata_import."
            "ensure_scryfall_cache_present's own docstring), not a loud failure. Populate it by "
            "running import_scryfall_printing_metadata or import_canonical_card_data first, or "
            "pass --allow-missing-scryfall-cache to explicitly accept the degraded mode."
        )


@section_timer(name="get default_cards bulk data URL")
def _get_default_cards_entry() -> BulkDataEntry:
    # Fails LOUD on any API error on purpose: per issue #513, a failed bulk-data lookup must
    # never silently fall back to reusing a cache of unknown age. Both the HTTP assert and the
    # "no such entry type" RuntimeError now live in `scryfall_bulk_data` so all three importers
    # share one implementation of that rule - this stays a named function because
    # `stream_full_catalog`'s stage-0 imports it directly to ask for the freshness verdict
    # without triggering a download.
    return scryfall_bulk_data.get_bulk_data_entry(scryfall_bulk_data.DEFAULT_CARDS)


@section_timer(name="download default_cards bulk data")
def _download_default_cards(url: str, path: Path) -> None:
    """
    Downloads the gzipped-JSONL bulk file at `url` and lands it DECOMPRESSED at `path`,
    atomically. Both properties are delegated to
    `scryfall_bulk_data.download_and_decompress`, which is where the reasoning lives:

      * the atomic temp-file + `os.replace` swap (PR #515) is preserved exactly - a mid-stream
        failure can never truncate the real cache;
      * since 2026-07-20 the remote artefact is a `.jsonl.gz` that is gzipped ON DISK rather
        than served with `Content-Encoding: gzip`, so `requests` no longer decompresses it for
        us and we inflate the stream ourselves as it arrives;
      * a non-gzip or truncated body raises `BulkDataDownloadError` instead of quietly landing a
        short file that would "successfully import" a fraction of the catalog.

    Kept as a named function in this module rather than inlined at the call site: the download
    step is what `@section_timer` reports as its own phase in this command's log, and the
    existing tests target it directly.
    """
    scryfall_bulk_data.download_and_decompress(url, path)


def _parse_rows(path: Path) -> list[PrintingMetadataRow]:
    """
    Parses the on-disk bulk cache into rows, one line at a time.

    The file is JSONL as of Scryfall's 2026-07-20 cutover - one card object per line, no
    wrapping array, no separating commas - and this has always read line-by-line rather than
    `json.load`ing 620MB at once, so the format change needs nothing here. The tolerance for the
    RETIRED pretty-printed-array shape (bare `[`/`]` lines, trailing commas) lives in
    `scryfall_bulk_data.iter_json_lines` and is deliberately retained: the deployed persistent
    volume still holds a pre-cutover `default_cards.json` that must stay readable until the next
    refresh replaces it.
    """
    rows = []
    for line in scryfall_bulk_data.iter_json_lines(path):
        try:
            rows.append(PrintingMetadataRow.model_validate_json(line))
        except ValidationError:
            logger.warning("failed to validate line: %s", line)
    return rows


@lru_cache(maxsize=8)
def _load_back_face_names(path_str: str) -> frozenset[str]:
    """
    Cached worker behind `get_back_face_names` - keyed on the resolved path string so distinct
    bulk-data files (e.g. one per test) never share a cache entry, while repeated lookups against
    the same real on-disk file within one process (the common case - this is called once per
    card, not once per run) only ever parse it once. The cache is intentionally never invalidated
    within a process lifetime: the bulk file itself only refreshes when the remote bulk entry
    actually changes (see `_is_fresh`), matching the same "reused within a run" tolerance
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


# The fields `_sync_printing_metadata` writes on CanonicalPrintingMetadata - the single source
# of truth for both the diff comparison (which fields count as "changed") and the bulk_update
# call (which columns the UPDATE statements touch). `canonical_card_id` is the table's primary
# key and the diff's join key, so it is deliberately not in this list.
_METADATA_SYNC_FIELDS = [
    "full_art",
    "border_color",
    "frame",
    "frame_effects",
    "promo_types",
    "edhrec_rank",
    "printings_count",
    "released_at",
    "lang",
    "art_crop_url",
    "illustration_id",
    "face_illustrations",
]

# Read/write chunk sizes for `_sync_printing_metadata`. The read side streams existing rows so
# the whole table is never materialised at once; the write side bounds every INSERT/UPDATE/
# DELETE statement to this many rows so no single statement ever spans the table again (see
# `_sync_printing_metadata`'s docstring for the prod OOM this guards against).
_METADATA_READ_CHUNK_SIZE = 2000
_METADATA_WRITE_BATCH_SIZE = 1000


def _sync_printing_metadata(metadata_rows: list[CanonicalPrintingMetadata]) -> dict[str, int]:
    """
    Diff-aware, batched replacement for the django-bulk-sync call this import used to make.

    `bulk_sync(filters=None)` issued ONE giant CASE-WHEN UPDATE spanning the whole
    CanonicalPrintingMetadata table on every run; on this command's first prod run
    (2026-07-28 11:01Z) that single statement ballooned a postgres backend to 15.5GB
    anon-RSS and the kernel OOM-killed it (signal 9, crash recovery). This sync instead:

    1. DIFFS desired rows against existing rows, joined on `canonical_card_id` (the table's
       primary key): no existing match -> CREATE; at least one synced field differs ->
       UPDATE; identical on every synced field -> SKIP (no write at all); an existing key
       absent from the desired set -> DELETE (preserving `bulk_sync(filters=None)`'s
       full-sync delete semantics).
    2. STREAMS the existing table via `.values()` + `.iterator(chunk_size=...)`, so the
       comparison never materialises the table as model instances - peak memory stays
       bounded by the desired row list (already in memory from `_parse_rows`) plus one
       chunk of plain dicts and the (int-keyed) existing-id set.
    3. WRITES in batches of `_METADATA_WRITE_BATCH_SIZE` (`bulk_create` / `bulk_update` /
       chunked `filter(...).delete()`), so no single statement ever spans the whole table.

    Comparison correctness: DB values come from `.values()` and desired values from the model
    instances built in `import_scryfall_printing_metadata` - both sides carry the same Python
    types (date, UUID, JSONField lists, None), so `!=` cannot produce a false "unchanged"
    verdict. A false "changed" verdict (e.g. an equivalent-but-not-identical JSON
    representation) costs one redundant single-row UPDATE - the safe direction.

    All writes run in ONE transaction: readers never observe a half-synced table, and the
    incident this fixes was statement size, not transaction size. The diff read happens
    outside the transaction deliberately - this command is the table's only writer, and a
    chunked `iterator()` holds no server-side cursor on PostgreSQL.

    Returns stats {created, updated, deleted, skipped} where `skipped` counts unchanged rows.
    """
    desired_by_id = {row.canonical_card_id: row for row in metadata_rows}
    existing_ids: set[int] = set()
    to_update: list[CanonicalPrintingMetadata] = []
    stale_ids: list[int] = []
    unchanged = 0

    existing_rows = CanonicalPrintingMetadata.objects.values("canonical_card_id", *_METADATA_SYNC_FIELDS).iterator(
        chunk_size=_METADATA_READ_CHUNK_SIZE
    )
    for existing in existing_rows:
        canonical_card_id = existing["canonical_card_id"]
        existing_ids.add(canonical_card_id)
        desired = desired_by_id.get(canonical_card_id)
        if desired is None:
            stale_ids.append(canonical_card_id)
        elif any(existing[field] != getattr(desired, field) for field in _METADATA_SYNC_FIELDS):
            to_update.append(desired)
        else:
            unchanged += 1

    to_create = [row for key, row in desired_by_id.items() if key not in existing_ids]

    with transaction.atomic():
        CanonicalPrintingMetadata.objects.bulk_create(to_create, batch_size=_METADATA_WRITE_BATCH_SIZE)
        if to_update:
            CanonicalPrintingMetadata.objects.bulk_update(
                to_update, fields=_METADATA_SYNC_FIELDS, batch_size=_METADATA_WRITE_BATCH_SIZE
            )
        for i in range(0, len(stale_ids), _METADATA_WRITE_BATCH_SIZE):
            CanonicalPrintingMetadata.objects.filter(
                canonical_card_id__in=stale_ids[i : i + _METADATA_WRITE_BATCH_SIZE]
            ).delete()

    return {"created": len(to_create), "updated": len(to_update), "deleted": len(stale_ids), "skipped": unchanged}


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
    `import_canonical_card_data` uses. Freshness is issue #513's remote-diff check
    (`_is_fresh`): the /bulk-data entry's `updated_at` is compared against the sidecar written
    at the last download, and the ~558MB file is only re-fetched when the remote has actually
    changed (a missing/unreadable sidecar re-downloads once - intended on the first run after
    deploy).

    The write phase is diff-aware (`_sync_printing_metadata`): existing rows are compared
    field-by-field against the parsed bulk data and only deltas are written (created /
    updated / deleted), in bounded batches - a re-import against an unchanged bulk file
    issues no row writes at all. The returned stats dict's `skipped` therefore counts
    unchanged rows; bulk-data rows with no matching `CanonicalCard` are reported separately
    under `no_matching_card`.
    """
    path = default_cards_path or _cache_path()
    if default_cards_path is None:
        entry = _get_default_cards_entry()
        if _is_fresh(path, entry):
            logger.info("Using cached default cards at %s (remote updated_at %s unchanged)", path, entry.updated_at)
        else:
            _download_default_cards(entry.jsonl_download_uri, path)
            _write_sidecar(path, entry)

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
    no_matching_card = 0
    for row in rows:
        canonical_card_pk = identifier_to_pk.get(row.id)
        if canonical_card_pk is None:
            no_matching_card += 1
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
                illustration_id=row.resolved_illustration_id,
                face_illustrations=row.face_illustrations,
            )
        )

    logger.info("Skipped %d row(s) with no matching CanonicalCard", no_matching_card)
    stats = _sync_printing_metadata(metadata_rows)
    stats["no_matching_card"] = no_matching_card
    logger.info(
        "CanonicalPrintingMetadata sync: %(created)d created, %(updated)d updated, "
        "%(deleted)d deleted, %(skipped)d skipped",
        stats,
    )
    return stats
