"""
Imports Scryfall Tagger's `art:external-ip` community art tag (tagger.scryfall.com) as
machine-cast `PrintingTagVote` rows (fix-batch plan 2026-07-27, work item W9, revised
per-printing spec) — Universes Beyond illustrations (Lord of the Rings, Doctor Who,
Warhammer 40K, etc.), identified by the Tagger community rather than by anything in our
own image pipeline.

Data flow (plan W9's own diagram, revised to per-printing):
    Art Tags bulk JSONL (https://api.scryfall.com/bulk-data, the `art_tags` entry's
    `jsonl_download_uri`, or a local file via --file)
      -> find tag slug "external-ip" -> BFS its child_ids subtree (the parent tag carries no
         direct taggings - Tagger bulk data only ever stores DIRECT taggings, on the leaf tags;
         see https://scryfall.com/docs/api/tags)
      -> collect taggings[].illustration_id across the subtree
      -> join through the already-on-disk default_cards bulk data (illustration_id -> card id;
         top-level on single-faced rows, per-face under card_faces for double-faced rows)
      -> match CanonicalCard.identifier DIRECTLY
      -> write PrintingTagVote rows (polarity=APPLY) for every matched CanonicalCard (printing).

PER-PRINTING DESIGN (revised 2026-07-27): votes target the Scryfall printing itself
(`CanonicalCard`) rather than the catalog images (`Card`) that depict it. The same
physical printing may be depicted by many `Card` images in the catalog; the Tagger
community tag belongs to the printing once, not duplicated per image. Card-level display/
attribution of external-ip flows FROM the printing via the metadata deduction seam
(see `printing_tag_consensus.py`), never stored per card.

SOURCE CHOICE (why not literally source="scryfall_tagger"): `AbstractWeightedVote.source` is a
CharField(max_length=10, choices=VoteSource.choices), the plan explicitly requires NO model/
migration change beyond PrintingTagVote itself, and "scryfall_tagger" (15 chars) is not a
VoteSource value. The established convention for a new machine caster is an existing machine
VoteSource plus its OWN anonymous_id
(local-ocr-v1/local-phash-v1/local-fallback-v1/deductive-backfill-v1/ai-art-detector-v1 -
see local_detect_ai_art.py's AI_ART_ANONYMOUS_ID comment). This import is pure logical
inference from already-trusted structured data with ZERO image inspection - exactly
`VoteSource.DEDUCTION`'s own definition (VoteSource's docstring) - so votes are written as
(source=DEDUCTION, anonymous_id="scryfall-tagger-v1"). Weight resolves to
PRINTING_TAG_MACHINE_WEIGHT (default 0.5) via vote_consensus._SOURCE_WEIGHTS, and the
2026-07-23 zero-weight override is scoped to (source=DEDUCTION, anonymous_id=
"deductive-backfill-v1") only, so these votes are unaffected by it.

RE-RUN SEMANTICS (matches the existing machine-vote casters exactly): the
(printing, tag, anonymous_id) uniqueness constraint on PrintingTagVote plus the eligibility
exclusion below makes re-runs idempotent - a printing this identity already voted on is
skipped, so a second invocation only ever votes on NEW matches (e.g. illustrations the Tagger
community tagged since the last run). RETRACTION is the existing run-scoped mechanism, not
anything bespoke: every invocation stamps a fresh run_id on its votes, and
`manage.py purge_machine_votes --run-id <id>` deletes exactly one invocation's votes. To
refresh against updated Tagger data where a printing was UN-tagged upstream: purge the old
run_id, then re-run.
"""

import gzip
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

import requests
from pydantic import BaseModel, ValidationError

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.integrations.game.mtg import Scryfall
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import (
    CanonicalCard,
    PilotRunLedger,
    PrintingTagVote,
    Tag,
    VotePolarity,
    VoteSource,
)
from cardpicker.printing_metadata_import import (
    _cache_path,
    ensure_scryfall_cache_present,
)
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha

# Own anonymous_id, per the per-engine convention (module docstring's SOURCE CHOICE section) -
# independently purgeable/re-runnable via the existing purge_machine_votes --run-id mechanism,
# and the (printing, tag, anonymous_id) uniqueness constraint is what makes "skip a printing
# already voted by this identity" a plain query rather than bespoke bookkeeping.
SCRYFALL_TAGGER_ANONYMOUS_ID = "scryfall-tagger-v1"

# The Tagger slug to look up in the art_tags bulk data (a URL-safe identifier that Scryfall
# warns may change over time - if a future run fails to find it, check the Tagger site for the
# tag's current slug; the tag `id` UUID is the stable reference, but slug lookup matches the
# plan's own data flow and keeps the fixture human-readable).
EXTERNAL_IP_TAG_SLUG = "external-ip"

# Our own Tag.name these votes are cast for. Tag.name is the immutable machine key (votes,
# Card.tags, federation) - deliberately the same string as the Tagger slug so the provenance is
# obvious, but the two are independent namespaces and must not be conflated elsewhere.
EXTERNAL_IP_TAG_NAME = "external-ip"

_BULK_DATA_METADATA_URL = "https://api.scryfall.com/bulk-data"
_ART_TAGS_BULK_TYPE = "art_tags"


class _BulkDataEntry(BaseModel):
    type: str
    download_uri: str
    # The .jsonl.gz streaming form - present on every entry today, but optional here so a
    # response predating it falls back to download_uri rather than hard-failing validation.
    jsonl_download_uri: Optional[str] = None


class _BulkDataResponse(BaseModel):
    data: list[_BulkDataEntry]


class _Tagging(BaseModel):
    # Nullable per Scryfall's own tags documentation (oracle taggings carry oracle_id instead) -
    # art_tags rows should always have it, but a null is skipped rather than crashing the pass.
    illustration_id: Optional[uuid.UUID] = None


class _TagRow(BaseModel):
    # A Tagger tag object (https://scryfall.com/docs/api/tags). Extra keys (label, uri, type,
    # description, parent_ids, aliases, weight on taggings, ...) are silently ignored by
    # pydantic, same convention as printing_metadata_import.PrintingMetadataRow.
    id: uuid.UUID
    slug: str
    child_ids: Optional[list[uuid.UUID]] = None
    taggings: list[_Tagging] = []


class _DefaultCardsRow(BaseModel):
    # Just the two shapes this import joins on, out of the full Scryfall card object - matching
    # PrintingMetadataRow's own "curated subset, extras ignored" convention. Single-faced cards
    # carry illustration_id top-level; double-faced cards nest one illustration_id per face
    # under card_faces (Scryfall's documented convention, same as PrintingMetadataRow's
    # art_crop_url handling).
    id: uuid.UUID
    illustration_id: Optional[uuid.UUID] = None
    card_faces: Optional[list[dict[str, Any]]] = None


def _iter_json_lines(path: Path) -> Iterator[str]:
    """
    Yields one decoded JSON-object line at a time from a JSONL(.gz) OR pretty-printed
    JSON-array(.gz) bulk file - the same tolerant line handling printing_metadata_import.
    _parse_rows already uses for the default_cards cache (skip bare "["/"]" lines, strip the
    trailing comma between array elements), so --file accepts any of the three shapes Scryfall
    actually publishes (`.jsonl`, `.jsonl.gz`, pretty `.json`). Streams line-by-line: the full
    art_tags file (~40MB compressed) is never held in memory.
    """
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        for line in f:
            stripped = line.strip()
            if stripped in ("", "[", "]"):
                continue
            yield stripped.rstrip(",")


def find_external_ip_subtree(tags_path: Path) -> tuple[set[uuid.UUID], int]:
    """
    Pass 1 over the tag bulk data: index every tag's (id -> slug + child_ids), find the tag
    whose slug is EXTERNAL_IP_TAG_SLUG, and BFS its child_ids subtree to the full set of tag ids
    whose taggings count (root included - it carries no direct taggings per Scryfall's docs, but
    including it is harmless if that ever changes). Returns (subtree tag ids, total tags seen).

    Deliberately BFS to fixpoint rather than plan W9's literal one-level "~56 child tags"
    traversal: the Tagger hierarchy may deepen under external-ip later (a child IP tag gaining
    its own children), and the subtree closure costs nothing extra since child_ids are already
    in memory. Raises RuntimeError if the slug is absent (slugs may change - see
    EXTERNAL_IP_TAG_SLUG's own comment) so a taxonomy rename fails LOUD rather than silently
    importing zero votes.
    """
    slug_by_id: dict[uuid.UUID, str] = {}
    child_ids_by_id: dict[uuid.UUID, list[uuid.UUID]] = {}
    tags_seen = 0
    for line in _iter_json_lines(tags_path):
        try:
            row = _TagRow.model_validate_json(line)
        except ValidationError:
            continue  # same skip-malformed tolerance as printing_metadata_import._parse_rows
        tags_seen += 1
        slug_by_id[row.id] = row.slug
        child_ids_by_id[row.id] = row.child_ids or []

    root_id = next((tag_id for tag_id, slug in slug_by_id.items() if slug == EXTERNAL_IP_TAG_SLUG), None)
    if root_id is None:
        raise RuntimeError(
            f"Tag slug {EXTERNAL_IP_TAG_SLUG!r} not found in {tags_path} ({tags_seen} tags parsed) - "
            "Tagger slugs may change over time (Scryfall's own tags documentation warns against "
            "treating them as permanent identifiers); check tagger.scryfall.com for the tag's "
            "current slug before re-running."
        )

    subtree: set[uuid.UUID] = {root_id}
    frontier = [root_id]
    while frontier:
        next_frontier = []
        for tag_id in frontier:
            for child_id in child_ids_by_id.get(tag_id, []):
                if child_id not in subtree:
                    subtree.add(child_id)
                    next_frontier.append(child_id)
        frontier = next_frontier
    return subtree, tags_seen


def collect_illustration_ids(tags_path: Path, subtree: set[uuid.UUID]) -> set[uuid.UUID]:
    """
    Pass 2 over the tag bulk data: the set of every illustration_id tagged by any tag in the
    subtree. Kept separate from find_external_ip_subtree so pass 1 never holds the (much
    larger) taggings payload in memory - only ids/slugs/child_ids survive it.
    """
    illustration_ids: set[uuid.UUID] = set()
    for line in _iter_json_lines(tags_path):
        try:
            row = _TagRow.model_validate_json(line)
        except ValidationError:
            continue
        if row.id not in subtree:
            continue
        for tagging in row.taggings:
            if tagging.illustration_id is not None:
                illustration_ids.add(tagging.illustration_id)
    return illustration_ids


def build_illustration_index(default_cards_path: Path) -> dict[uuid.UUID, set[uuid.UUID]]:
    """
    illustration_id -> set of Scryfall card ids (`id`, the printing UUID that CanonicalCard.
    identifier stores), from the same on-disk default_cards bulk data import_canonical_card_data/
    import_scryfall_printing_metadata already maintain. One illustration maps to N printings
    (reprints reusing the same art all count - the ART is what's tagged), and a double-faced
    row contributes one entry per face (each face is its own illustration).
    """
    index: dict[uuid.UUID, set[uuid.UUID]] = {}
    for line in _iter_json_lines(default_cards_path):
        try:
            row = _DefaultCardsRow.model_validate_json(line)
        except ValidationError:
            continue
        illustration_ids = [row.illustration_id] if row.illustration_id is not None else []
        if row.card_faces:
            for face in row.card_faces:
                face_illustration_id = face.get("illustration_id")
                if face_illustration_id:
                    illustration_ids.append(uuid.UUID(face_illustration_id))
        for illustration_id in illustration_ids:
            index.setdefault(illustration_id, set()).add(row.id)
    return index


@dataclass
class ExternalIpImportResult:
    dry_run: bool = False
    run_id: str = ""
    tags_seen: int = 0
    subtree_tag_count: int = 0
    illustrations_tagged: int = 0
    # skip-count reasons: illustrations no default_cards row mapped (art not in any English
    # printing - e.g. art-series-only illustrations), and printings no CanonicalCard row
    # matched (not canonical per import_canonical_card_data's own filtering).
    skip_counts: dict[str, int] = field(default_factory=dict)
    canonical_cards_matched: int = 0
    printings_eligible: int = 0
    votes_would_cast: int = 0
    votes_written: int = 0
    audit: list[dict[str, object]] = field(default_factory=list)


def run_external_ip_tag_import(
    tags_path: Path,
    default_cards_path: Path,
    run_id: Optional[str] = None,
    dry_run: bool = True,
    chunk_size: int = 500,
    audit_sample_size: int = 20,
) -> ExternalIpImportResult:
    """
    The import itself - a plain, testable function with Command.handle() kept thin, matching
    this module family's own convention (purge_machine_votes.purge_run, local_detect_ai_art.
    run_ai_art_detector). `dry_run=True` (the default, matching every other Stage 3+ command's
    opt-in-to-write convention) parses/joins/counts everything without writing any
    PrintingTagVote row. GATE VERIFICATION is layered on by the management command, not here
    - same split as run_ai_art_detector/purge_machine_votes (see their docstrings).
    """
    run_id = run_id or generate_run_id()
    result = ExternalIpImportResult(dry_run=dry_run, run_id=run_id)

    subtree, result.tags_seen = find_external_ip_subtree(tags_path)
    result.subtree_tag_count = len(subtree)
    illustration_ids = collect_illustration_ids(tags_path, subtree)
    result.illustrations_tagged = len(illustration_ids)

    illustration_index = build_illustration_index(default_cards_path)
    candidate_identifiers: set[uuid.UUID] = set()
    unmatched_illustrations = 0
    for illustration_id in illustration_ids:
        card_ids = illustration_index.get(illustration_id)
        if not card_ids:
            unmatched_illustrations += 1
            continue
        candidate_identifiers.update(card_ids)
    if unmatched_illustrations:
        result.skip_counts["illustration-not-in-default-cards"] = unmatched_illustrations

    tag, _ = Tag.objects.get_or_create(name=EXTERNAL_IP_TAG_NAME)

    # Count total canonical cards matched (for reporting, before eligibility exclusion).
    all_matched = CanonicalCard.objects.filter(identifier__in=candidate_identifiers)
    result.canonical_cards_matched = all_matched.count()
    unmatched_printings = len(candidate_identifiers) - result.canonical_cards_matched
    if unmatched_printings:
        result.skip_counts["printing-not-canonical"] = unmatched_printings

    # Eligible = matched minus already-voted by this identity for this tag (idempotency).
    # Direct printing-level join: no Card-level inference or effective-printing logic needed —
    # the illustration_id -> CanonicalCard.identifier join is the complete eligibility check.
    # The single-exclude-call form (both conditions on the same related row) is correct here,
    # matching the same pattern local_detect_ai_art._eligible_cards_queryset uses.
    eligible_printings = all_matched.exclude(
        printing_tag_votes__anonymous_id=SCRYFALL_TAGGER_ANONYMOUS_ID,
        printing_tag_votes__tag=tag,
    ).distinct()

    votes_batch: list[PrintingTagVote] = []
    for printing in eligible_printings.iterator(chunk_size=chunk_size):
        result.printings_eligible += 1
        result.votes_would_cast += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"printing_id": str(printing.identifier), "printing_name": printing.name})
        if not dry_run:
            votes_batch.append(
                PrintingTagVote(
                    printing_id=printing.pk,
                    tag=tag,
                    polarity=VotePolarity.APPLY,
                    anonymous_id=SCRYFALL_TAGGER_ANONYMOUS_ID,
                    source=VoteSource.DEDUCTION,
                    run_id=run_id,
                )
            )

    if not dry_run:
        # ignore_conflicts=True: belt-and-suspenders against the (printing, tag, anonymous_id)
        # uniqueness constraint - the eligibility query above already excludes any printing this
        # identity has voted on, so a conflict here would only ever come from two concurrent
        # invocations racing, not from this invocation's own logic.
        PrintingTagVote.objects.bulk_create(votes_batch, ignore_conflicts=True)
        result.votes_written = len(votes_batch)

    return result


def _find_art_tags_download_uri() -> str:
    response = requests.get(_BULK_DATA_METADATA_URL, headers=Scryfall.get_headers())
    response.raise_for_status()
    parsed = _BulkDataResponse.model_validate_json(response.text)
    matches = [entry for entry in parsed.data if entry.type == _ART_TAGS_BULK_TYPE]
    if not matches:
        raise CommandError(f"Scryfall bulk-data response did not contain an {_ART_TAGS_BULK_TYPE!r} entry")
    entry = matches.pop()
    return entry.jsonl_download_uri or entry.download_uri


class Command(BaseCommand):
    help = (
        "Imports Scryfall Tagger's art:external-ip community tag (and its child-IP tags) as "
        "machine PrintingTagVote rows (source=deduction, anonymous_id=scryfall-tagger-v1, "
        "machine weight 0.5) for CanonicalCard (printing) rows whose illustration the Tagger "
        "community tagged - fix-batch plan 2026-07-27 W9 (revised per-printing spec). Defaults "
        "to dry-run and requires an explicit --write to actually write, matching every other "
        "Stage 3+ command's own convention. Idempotent on re-run via the "
        "(printing, tag, anonymous_id) uniqueness constraint; retract one invocation's votes "
        "with purge_machine_votes --run-id <id>."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--file",
            type=Path,
            default=None,
            help="Local art-tags JSONL(.gz) file to parse instead of downloading the current "
            "bulk data from Scryfall (also accepts a pretty-printed .json array). Tests use this.",
        )
        parser.add_argument(
            "--default-cards",
            type=Path,
            default=None,
            help="Local default_cards bulk file for the illustration_id join. Default: the "
            "shared scryfall_cache/default_cards.json cache import_canonical_card_data/"
            "import_scryfall_printing_metadata already maintain (must exist - this command "
            "never downloads it).",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually write PrintingTagVote rows. Default is dry-run: parse, join, and "
            "count everything without writing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Explicit dry-run (the default when --write is absent) - counts only, no writes. "
            "Passing both --write and --dry-run is an error.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        parser.add_argument(
            "--chunk-size", type=int, default=500, help="Queryset .iterator() chunk size. Default: 500."
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code before running this command."
            )

        if kwargs["write"] and kwargs["dry_run"]:
            raise CommandError("Pass only one of --write / --dry-run.")
        dry_run = not kwargs["write"]
        run_id = kwargs["run_id"] or generate_run_id()
        mode = "DRY RUN" if dry_run else "WRITE"
        print(f"[{mode}] import_external_ip_tags run_id={run_id} git_sha={get_baked_git_sha()}")

        # The illustration join needs the default_cards bulk data. Explicit path wins (tests);
        # otherwise the shared cache MUST already exist - downloading 600MB implicitly inside a
        # vote-casting command would hide a big side effect, and the staleness guard's own
        # CommandError names the two commands that populate it.
        _raw_default_cards = kwargs["default_cards"]
        default_cards_path: Path = Path(_raw_default_cards) if _raw_default_cards else _cache_path()
        if _raw_default_cards is None:
            ensure_scryfall_cache_present(default_cards_path)

        _raw_file = kwargs["file"]
        tags_path: Optional[Path] = Path(_raw_file) if _raw_file is not None else None
        if tags_path is None:
            uri = _find_art_tags_download_uri()
            print(f"Downloading art tags from {uri}")
            suffix = ".jsonl.gz" if uri.endswith(".gz") else ".json"
            with tempfile.NamedTemporaryFile(prefix="art-tags-", suffix=suffix, delete=False) as tmp:
                tmp_path = Path(tmp.name)
                with requests.get(uri, stream=True, headers=Scryfall.get_headers()) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        tmp.write(chunk)
            tags_path = tmp_path
        print(f"Tag data: {tags_path} (default_cards: {default_cards_path})")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="import_external_ip_tags",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )

        try:
            result = run_external_ip_tag_import(
                tags_path=tags_path,
                default_cards_path=default_cards_path,
                run_id=run_id,
                dry_run=dry_run,
                chunk_size=kwargs["chunk_size"],
            )
            print(
                f"[external-ip] tags_seen={result.tags_seen} subtree_tags={result.subtree_tag_count} "
                f"illustrations={result.illustrations_tagged} canonical_cards={result.canonical_cards_matched} "
                f"eligible_printings={result.printings_eligible} "
                f"votes={'written=' + str(result.votes_written) if not dry_run else 'would_cast=' + str(result.votes_would_cast)} "
                f"skip_counts={dict(result.skip_counts)}"
            )
            for entry in result.audit[:10]:
                print(f"  sample: {entry}")

            # Note: verify_no_machine_only_resolutions (purge_machine_votes) is card-level
            # (checks Card.printing_tag_status / tag_vote_statuses). PrintingTagVote writes do
            # not affect any Card-level resolution status — per-printing consensus resolution
            # is a separate concern tracked in printing_tag_consensus.py, with no persisted
            # Card-side status field today. The gate is therefore not applicable here and is
            # omitted; it remains available for CardTagVote/CardPrintingTag/CardArtistVote runs.

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.votes_written = result.votes_written
            ledger.save(update_fields=["status", "finished_at", "votes_written"])
            print(
                f"[{mode}] done. run_id={run_id} "
                f"total_votes_{'written' if not dry_run else 'would_cast'}="
                f"{result.votes_written if not dry_run else result.votes_would_cast}"
            )
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
        finally:
            # Only the downloaded tempfile is ours to remove - a --file path is the caller's.
            if kwargs["file"] is None and tags_path is not None:
                tags_path.unlink(missing_ok=True)


__all__ = [
    "SCRYFALL_TAGGER_ANONYMOUS_ID",
    "EXTERNAL_IP_TAG_SLUG",
    "EXTERNAL_IP_TAG_NAME",
    "find_external_ip_subtree",
    "collect_illustration_ids",
    "build_illustration_index",
    "ExternalIpImportResult",
    "run_external_ip_tag_import",
]
