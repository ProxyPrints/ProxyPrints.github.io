"""
Populates `ExternalIpIllustration` - the illustration-grain derived store behind the
`external-ip` tag - and (optionally) denormalises the resulting tag onto `Card.tags` so
Elasticsearch can filter on it.

WHAT THIS COMMAND IS NOT: it is not a vote caster. Its predecessor
(`import_external_ip_tags`, retired with `PrintingTagVote` in PR #615) wrote machine
`PrintingTagVote` rows, which could never resolve - `vote_consensus.resolve_weighted_consensus`
gates on `has_human_backed` independently of the weight sum, so a machine-only vote set returns
`None` at any volume. This command writes a derived attribute and reads it back directly. There
is no threshold, no resolver, no consensus, and no `NOT_APPLICABLE` negative pass (an attribute
expresses absence by being absent, which is why the ~100k negative rows the old design would
have written are simply not a thing here).

THE PREDICATE LIVES IN `cardpicker/external_ip.py`, NOT HERE. This module is the thin
I/O-and-reporting shell: fetch the feed, call `build_external_ip_union`, upsert, report. Every
definitional decision - the union's two sources, the named exclusion list, the illustration
grain, the `promo_types` fallback for artwork-less printings - is stated and justified there, so
that a reader who wants to know WHAT `external-ip` means never has to read a management command
to find out.

RE-RUN SEMANTICS. Idempotent by construction: rows are upserted on `illustration_id`, and
`last_seen_at` is refreshed on every run that still finds the artwork. An artwork UN-tagged
upstream is therefore visible as a row whose `last_seen_at` lags the newest run rather than
silently persisting as truth; `--prune` deletes exactly those rows. Nothing is ever deleted
implicitly, because a Tagger feed that briefly failed to parse must not be able to empty the
catalogue's tagging in one run.
"""

import tempfile
from pathlib import Path
from typing import Any, Optional

import requests

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from cardpicker.documents import reindex_card_safely
from cardpicker.external_ip import (
    EXCLUDE_HOMAGE_ILLUSTRATIONS,
    EXTERNAL_IP_TAG_NAME,
    build_external_ip_union,
    get_external_ip_card_overlay,
    merge_external_ip_tag,
)
from cardpicker.integrations.game import scryfall_bulk_data
from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.models import Card, ExternalIpIllustration, PilotRunLedger, Tag
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha

COMMAND_NAME = "import_external_ip_illustrations"


def _download_art_tags() -> Path:
    """
    One download of the `art_tags` bulk entry's `.jsonl.gz`, to a tempfile the caller deletes.

    Kept GZIPPED on disk, unlike the persistent `default_cards` cache: this file is read exactly
    twice (subtree BFS, then taggings) and then discarded, and `iter_json_lines` gunzips `.gz`
    transparently, so inflating ~12MB in /tmp would buy nothing.
    """
    try:
        entry = scryfall_bulk_data.get_bulk_data_entry(scryfall_bulk_data.ART_TAGS)
    except RuntimeError as e:
        raise CommandError(str(e)) from e
    uri = entry.jsonl_download_uri
    print(f"Downloading art tags from {uri}")
    suffix = ".jsonl.gz" if uri.endswith(".gz") else ".jsonl"
    with tempfile.NamedTemporaryFile(prefix="art-tags-", suffix=suffix, delete=False) as tmp:
        path = Path(tmp.name)
        with requests.get(uri, stream=True, headers=scryfall_bulk_data.get_headers(), timeout=120) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                tmp.write(chunk)
    return path


class Command(BaseCommand):
    help = (
        "Rebuilds the `external-ip` illustration set from the union of Scryfall Tagger's "
        "art:external-ip subtree and the promo_types tokens universesbeyond/godzillaseries/"
        "draculaseries, minus the named exclusion list in cardpicker.external_ip. Defaults to "
        "dry-run; pass --write to persist. --sync-cards additionally denormalises the resulting "
        "tag onto Card.tags for catalogue images whose artwork is known."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--file",
            type=Path,
            default=None,
            help="Local art-tags JSONL(.gz) file to parse instead of downloading. Tests use this.",
        )
        parser.add_argument(
            "--write", action="store_true", default=False, help="Persist rows. Default is dry-run: count only."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Explicit dry-run (the default when --write is absent). Passing both is an error.",
        )
        parser.add_argument(
            "--sync-cards",
            action="store_true",
            default=False,
            help="Also denormalise `external-ip` onto Card.tags for catalogue images whose "
            "artwork is known (confirmed canonical_card link, or a resolved illustration vote), "
            "and push each changed card into Elasticsearch.",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            default=False,
            help="Delete stored rows this run did NOT re-find (an artwork un-tagged upstream). "
            "Off by default so a feed that briefly failed to parse cannot empty the set.",
        )
        parser.add_argument(
            "--include-homages",
            action="store_true",
            default=False,
            help="Keep the 11 homage artworks (Godzilla/Dracula basic lands, the Pusheen playtest "
            "card) that depict licensed-looking subject matter without being licensed art. "
            "Overrides cardpicker.external_ip.EXCLUDE_HOMAGE_ILLUSTRATIONS for this run - an "
            "owner decision, not a routine flag.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's own code doesn't "
                f"know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - this image is older than a "
                "previously-deployed one. Rebuild with the current code before running this command."
            )
        if kwargs["write"] and kwargs["dry_run"]:
            raise CommandError("Pass only one of --write / --dry-run.")

        dry_run = not kwargs["write"]
        run_id = kwargs["run_id"] or generate_run_id()
        mode = "DRY RUN" if dry_run else "WRITE"
        exclude_homages = False if kwargs["include_homages"] else EXCLUDE_HOMAGE_ILLUSTRATIONS
        print(f"[{mode}] {COMMAND_NAME} run_id={run_id} git_sha={get_baked_git_sha()}")

        # The `external-ip` Tag must EXIST but is not created here. It is seeded by
        # `manage.py seed_no_match_reason_tags`, which owns the whole no-match reason taxonomy;
        # a second creator would let this command silently invent the row with different
        # `display_name`/`moderation_class` than the human channel expects, and `Tag.name` is a
        # federation interchange contract. Fail loudly instead and name the fix.
        if not Tag.objects.filter(name=EXTERNAL_IP_TAG_NAME).exists():
            raise CommandError(
                f"Tag {EXTERNAL_IP_TAG_NAME!r} does not exist. Run `manage.py seed_no_match_reason_tags` first - "
                "that command owns this taxonomy (cardpicker.reason_tags) and is idempotent."
            )

        tags_path: Optional[Path] = Path(kwargs["file"]) if kwargs["file"] else None
        downloaded = tags_path is None
        if downloaded:
            tags_path = _download_art_tags()

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command=COMMAND_NAME,
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )
        try:
            assert tags_path is not None
            union = build_external_ip_union(tags_path, exclude_homages=exclude_homages)
            print(
                f"[external-ip] tags_seen={union.tags_seen} subtree_tags={union.subtree_tag_count} "
                f"tagger_illustrations={len(union.tagger_illustration_ids)} "
                f"(absent_from_catalogue={union.tagger_illustrations_absent_from_catalogue}) "
                f"promo_illustrations={len(union.promo_illustration_ids)} "
                f"tagger_only={len(union.tagger_only)} promo_only={len(union.promo_only)} "
                f"both={len(union.both)} excluded={len(union.excluded)} "
                f"UNION={len(union.illustration_ids)} "
                f"promo_printings_without_illustration={union.promo_printings_without_illustration}"
            )

            stored = set(ExternalIpIllustration.objects.values_list("illustration_id", flat=True))
            to_create = union.illustration_ids - stored
            to_refresh = union.illustration_ids & stored
            to_prune = stored - union.illustration_ids
            print(
                f"[external-ip] rows: stored={len(stored)} create={len(to_create)} refresh={len(to_refresh)} "
                f"stale={len(to_prune)}{' (will prune)' if kwargs['prune'] else ' (kept; pass --prune to delete)'}"
            )

            counters: dict[str, Any] = {
                "union_illustrations": len(union.illustration_ids),
                "tagger_only": len(union.tagger_only),
                "promo_only": len(union.promo_only),
                "both": len(union.both),
                "excluded": len(union.excluded),
                "rows_created": 0,
                "rows_refreshed": 0,
                "rows_pruned": 0,
                "cards_tagged": 0,
                "exclude_homages": exclude_homages,
            }

            if not dry_run:
                with transaction.atomic():
                    ExternalIpIllustration.objects.bulk_create(
                        [
                            ExternalIpIllustration(
                                illustration_id=illustration_id,
                                sources=union.sources_for(illustration_id),
                                tagger_slugs=sorted(union.tagger_slugs.get(illustration_id, ())),
                            )
                            for illustration_id in sorted(to_create, key=str)
                        ],
                        batch_size=1000,
                    )
                    counters["rows_created"] = len(to_create)
                    refreshed = [
                        ExternalIpIllustration(
                            illustration_id=illustration_id,
                            sources=union.sources_for(illustration_id),
                            tagger_slugs=sorted(union.tagger_slugs.get(illustration_id, ())),
                            last_seen_at=timezone.now(),
                        )
                        for illustration_id in sorted(to_refresh, key=str)
                    ]
                    if refreshed:
                        ExternalIpIllustration.objects.bulk_update(
                            refreshed, ["sources", "tagger_slugs", "last_seen_at"], batch_size=1000
                        )
                    counters["rows_refreshed"] = len(refreshed)
                    if kwargs["prune"] and to_prune:
                        ExternalIpIllustration.objects.filter(illustration_id__in=to_prune).delete()
                        counters["rows_pruned"] = len(to_prune)

            if kwargs["sync_cards"]:
                counters["cards_tagged"] = self._sync_cards(dry_run=dry_run)

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            ledger.counters = counters
            ledger.save(update_fields=["status", "finished_at", "counters"])
            print(f"[{mode}] done. run_id={run_id} counters={counters}")
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
        finally:
            if downloaded and tags_path is not None:
                tags_path.unlink(missing_ok=True)

    def _sync_cards(self, *, dry_run: bool) -> int:
        """
        Denormalises the derived tag onto `Card.tags` and pushes each changed card into
        Elasticsearch. `Card.tags` is the ES-indexed field (`documents.py`'s `KeywordField`), so
        this is what turns the stored union into an actual `tag:external-ip` search predicate.

        ADD-ONLY, never remove - see `external_ip.merge_external_ip_tag`'s own docstring. The
        derived channel can only see official printings; a tag it does not confirm may have come
        from the human `CardTagVote` channel, which is authoritative for the population this one
        cannot reach.

        Batched over card ids rather than loaded whole: the catalogue is 230,770 rows and the
        overlay query is an indexed join, so the working set stays bounded regardless of how many
        cards eventually match.
        """
        changed = 0
        card_ids = list(Card.objects.values_list("pk", flat=True).order_by("pk"))
        for start in range(0, len(card_ids), 5000):
            batch = card_ids[start : start + 5000]
            applies = get_external_ip_card_overlay(batch)
            if not applies:
                continue
            for card in Card.objects.filter(pk__in=applies).exclude(tags__contains=[EXTERNAL_IP_TAG_NAME]):
                changed += 1
                if dry_run:
                    continue
                card.tags = merge_external_ip_tag(card.tags, True)
                card.save(update_fields=["tags"])
                reindex_card_safely(card)
        print(f"[external-ip] cards {'that would gain' if dry_run else 'given'} the tag: {changed}")
        return changed
