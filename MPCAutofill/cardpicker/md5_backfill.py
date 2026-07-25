"""
Checksum backfill (GitHub issue #473 PR-1 - "checksum substrate", `docs/features/
catalog-completion-plan.md`'s #442-sourced "index Drive checksums" leverage). Fills BOTH
`Card.md5_checksum` and `Card.sha256_checksum` in the one pass - the module keeps its original
name (`md5_backfill`/`backfill_md5_checksums`) since md5 is still the primary, grouping-defining
field (issue #473 ruling 1: groups key on md5 exclusively); sha256 was added to the same listing
walk and the same migration (owner-approved addition, 2026-07-25 evening) as a transfer-safety
pairing for PR-2, not a second grouping axis - see `Card.sha256_checksum`'s own docstring in
`cardpicker.models` for the full binding rule.

Re-walks every `GOOGLE_DRIVE` source's Drive folder listing (metadata only - ZERO image fetches,
the same guarantee `cardpicker.sources.update_database.explore_folder` already gives its other
callers) and reconciles each listing's `md5Checksum`/`sha256Checksum` against the currently-stored
`Card.md5_checksum`/`Card.sha256_checksum` for every `Card` row whose `identifier` (Drive file id)
appears in that listing. Reuses `explore_folder` (its own thread pool + progress printing) and
`cardpicker.sources.api.execute_google_drive_api_call` (the shared, already-rate-limited Drive API
client `get_all_images_inside_folder` calls through) - this module hand-rolls neither a new client
nor new pacing.

LOCAL_FILE sources carry neither checksum in their listings at all (see
`cardpicker.sources.source_types.LocalFile.get_all_images_inside_folder`, which never sets
`Image.md5_checksum`/`Image.sha256_checksum`) and are therefore skipped entirely by
`run_md5_backfill` - not walked, not counted as "unreachable" (that status is reserved for a
GOOGLE_DRIVE source whose root folder genuinely couldn't be resolved). This matches
`Card.md5_checksum`/`Card.sha256_checksum`'s own docstrings: null there is the correct, permanent
state for a checksum-less source, per the owner's ruling 3 on issue #473 ("a card with null or
unique md5 is a group of one... never invent a checksum") - the same never-invent posture applies
to sha256.

The two fields are tracked and written INDEPENDENTLY per card, since Drive's own coverage differs
between them (sha256Checksum is less consistently populated than md5Checksum for older files) -
an entry carrying one but not the other never has its missing field invented, and a stored value
is never overwritten with an absent listing value.

NEVER writes an invented/derived checksum, and NEVER nulls out an existing one: a Card whose Drive
file id no longer appears in its source's current listing (deleted/moved on the Drive side) is
left completely untouched here - deletion is a separate, already-covered code path
(`bulk_sync_objects`'s own `deleted_ids` handling), not something this reconciliation duplicates
or second-guesses.

DUPE-FACTOR RECONCILIATION (the PR-1 acceptance criterion - "backfill dry-run numbers reconcile
with #442's walk before --write"): `BackfillResult.matched_files`/`dupe_groups`/`dupe_files`/
`dupe_factor` are computed with the same definitions #442's own sizing walk used - "files with
both a Card row and an md5Checksum" (`matched_files`), grouped by checksum value across ALL
sources (`dupe_groups`/`dupe_files` - #442 measured cross-source dupes as the dominant case, so
grouping is deliberately global, never scoped to one source at a time). This dupe accounting is
MD5-ONLY, unchanged by the sha256 addition - per ruling 1, groups key on md5 exclusively, so there
is no analogous "sha256 dupe factor" to compute. `BackfillResult.sha256_matched_files`/
`sha256_planned_writes` are the parallel PER-FIELD COVERAGE counters for sha256 (module docstring
above), reported separately in the dry-run output since the two fields' coverage can differ.
"""

from dataclasses import dataclass, field
from typing import Optional

from cardpicker.models import Card, Source
from cardpicker.sources.source_types import SourceTypeChoices
from cardpicker.sources.update_database import explore_folder

DEFAULT_BULK_UPDATE_BATCH_SIZE = 1000


@dataclass
class ChecksumEntry:
    """One listing entry's checksum(s), for one Drive file id. Either field may be `None`
    independently - see module docstring's "tracked and written INDEPENDENTLY" note."""

    md5_checksum: Optional[str] = None
    sha256_checksum: Optional[str] = None


@dataclass
class SourceWalkResult:
    source_key: str
    reachable: bool = True
    # Drive file id -> ChecksumEntry, for every image in this source's CURRENT listing that
    # carries at least one of the two checksums (see this module's own docstring for why a
    # listing entry might carry neither, or only one).
    checksums_by_identifier: dict[str, ChecksumEntry] = field(default_factory=dict)


def walk_source_checksums(source: Source) -> SourceWalkResult:
    """
    One GOOGLE_DRIVE source's own listing walk - metadata only, no image fetch (see module
    docstring). `reachable=False` means the source's root folder itself couldn't be resolved
    (matches `SourceType.get_all_folders`'s own `None`-for-a-dead-source contract, e.g. a
    since-deleted or permission-revoked Drive folder) - distinct from "resolved fine, but this
    walk's checksums_by_identifier is empty", which is a genuine (if surprising) zero-checksum
    result, not a failure.
    """
    source_type = SourceTypeChoices.get_source_type(SourceTypeChoices[source.source_type])
    root_folder = source_type.get_all_folders([source]).get(source.key)
    if root_folder is None:
        return SourceWalkResult(source_key=source.key, reachable=False)

    images = explore_folder(source=source, source_type=source_type, root_folder=root_folder)
    checksums = {
        image.id: ChecksumEntry(md5_checksum=image.md5_checksum, sha256_checksum=image.sha256_checksum)
        for image in images
        if image.md5_checksum or image.sha256_checksum
    }
    return SourceWalkResult(source_key=source.key, checksums_by_identifier=checksums)


@dataclass
class BackfillResult:
    dry_run: bool = True
    sources_scanned: int = 0
    sources_skipped_no_checksum_support: list[str] = field(default_factory=list)
    sources_unreachable: list[str] = field(default_factory=list)
    # "files with both a Card row and an md5Checksum" - #442's own sizing-walk definition,
    # unchanged by the sha256 addition (this is the number that reconciles against #442's
    # 18.87%/12,275-group walk).
    matched_files: int = 0
    # of matched_files, how many have a stored Card.md5_checksum that differs from (or is NULL
    # against) the listing's own value.
    md5_planned_writes: int = 0
    # sha256 per-field coverage counters (owner-approved addition, 2026-07-25 evening) - same
    # definitions as the two md5 counters above, but for sha256, tracked SEPARATELY since Drive's
    # sha256Checksum coverage can differ from md5Checksum coverage for the same file set (see
    # module docstring).
    sha256_matched_files: int = 0
    sha256_planned_writes: int = 0
    # total distinct cards that need (or, post-write, received) an update this run - a card
    # needing BOTH an md5 and a sha256 write is counted once here, not twice (one bulk_update row
    # either way). What --write would actually persist / has actually persisted.
    planned_writes: int = 0
    # actually persisted; stays 0 for a dry run.
    written: int = 0
    # md5-only (issue #473 ruling 1: groups key on md5 exclusively) - see module docstring's
    # "DUPE-FACTOR RECONCILIATION" section.
    dupe_groups: int = 0
    dupe_files: int = 0

    @property
    def dupe_factor(self) -> float:
        return self.dupe_files / self.matched_files if self.matched_files else 0.0


def run_md5_backfill(
    dry_run: bool = True,
    source_keys: Optional[list[str]] = None,
    batch_size: int = DEFAULT_BULK_UPDATE_BATCH_SIZE,
) -> BackfillResult:
    """
    The actual re-walk + reconcile logic (module docstring), matching this codebase's own "keep
    Command.handle() thin" convention (e.g. `reparse_collector_evidence.reparse_and_retract`).

    `source_keys`, when given, restricts the walk to those sources only (still GOOGLE_DRIVE-only
    - a LOCAL_FILE key passed here is silently a no-op, same as an unfiltered run, since it's
    filtered out by the `source_type=GOOGLE_DRIVE` queryset below regardless) - useful for a
    targeted re-run or a test, never required for the full-catalog case.

    Global (cross-source) checksum grouping for `dupe_groups`/`dupe_files`/`dupe_factor` - see
    module docstring's "DUPE-FACTOR RECONCILIATION" section for why this must NOT be scoped
    per-source.
    """
    result = BackfillResult(dry_run=dry_run)
    checksum_counts: dict[str, int] = {}

    all_sources = Source.objects.all().order_by("key")
    if source_keys is not None:
        all_sources = all_sources.filter(key__in=source_keys)

    for source in all_sources:
        if source.source_type != SourceTypeChoices.GOOGLE_DRIVE:
            # Checksum-less source type (LOCAL_FILE today; any future non-Drive type by
            # default) - reported for --dry-run visibility, never walked or treated as an error.
            result.sources_skipped_no_checksum_support.append(source.key)
            continue

        result.sources_scanned += 1
        walk = walk_source_checksums(source)
        if not walk.reachable:
            result.sources_unreachable.append(source.key)
            continue
        if not walk.checksums_by_identifier:
            continue

        existing_by_identifier = {
            card.identifier: card
            for card in Card.objects.filter(source=source, identifier__in=walk.checksums_by_identifier.keys())
        }

        to_write: list[Card] = []
        for identifier, entry in walk.checksums_by_identifier.items():
            card = existing_by_identifier.get(identifier)
            if card is None:
                # The listing carries a file id we haven't indexed as a Card yet (e.g. a
                # concurrent update_database scan is still in flight) - never invented here;
                # a later update_database/backfill pass picks it up once the Card row exists.
                continue

            # Each field is tracked/compared independently - an entry missing one of the two
            # never invents it, and never overwrites a stored value with an absent one (module
            # docstring's "tracked and written INDEPENDENTLY" note).
            needs_md5_write = False
            if entry.md5_checksum is not None:
                result.matched_files += 1
                checksum_counts[entry.md5_checksum] = checksum_counts.get(entry.md5_checksum, 0) + 1
                if card.md5_checksum != entry.md5_checksum:
                    result.md5_planned_writes += 1
                    needs_md5_write = True

            needs_sha256_write = False
            if entry.sha256_checksum is not None:
                result.sha256_matched_files += 1
                if card.sha256_checksum != entry.sha256_checksum:
                    result.sha256_planned_writes += 1
                    needs_sha256_write = True

            if needs_md5_write or needs_sha256_write:
                result.planned_writes += 1
                if not dry_run:
                    if needs_md5_write:
                        card.md5_checksum = entry.md5_checksum
                    if needs_sha256_write:
                        card.sha256_checksum = entry.sha256_checksum
                    to_write.append(card)

        if not dry_run and to_write:
            for start in range(0, len(to_write), batch_size):
                Card.objects.bulk_update(
                    to_write[start : start + batch_size],
                    ["md5_checksum", "sha256_checksum"],
                    batch_size=batch_size,
                )
            result.written += len(to_write)

    for count in checksum_counts.values():
        if count > 1:
            result.dupe_groups += 1
            result.dupe_files += count

    return result


__all__ = ["ChecksumEntry", "SourceWalkResult", "walk_source_checksums", "BackfillResult", "run_md5_backfill"]
