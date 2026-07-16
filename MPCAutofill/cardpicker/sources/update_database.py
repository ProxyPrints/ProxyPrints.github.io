import socket
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from typing import Optional, Type

from django.conf import settings
from django.db import transaction

from cardpicker import local_phash
from cardpicker.constants import DEFAULT_LANGUAGE, MAX_SIZE_MB
from cardpicker.documents import CardSearch
from cardpicker.models import Card, CardTypes, Source, VotePolarity
from cardpicker.search.sanitisation import to_searchable
from cardpicker.sources.api import Folder, Image
from cardpicker.sources.source_types import SourceType, SourceTypeChoices
from cardpicker.tag_consensus import get_resolved_tag_overlay
from cardpicker.tags import Tags
from cardpicker.utils import TEXT_BOLD, TEXT_END

MAX_WORKERS = 5
# Bounds concurrent *sources* being scanned at once (each of which internally opens its own
# MAX_WORKERS-sized pool above for its own folder tree) - not to be confused with MAX_WORKERS.
# At MAX_SOURCE_WORKERS=8 x MAX_WORKERS=5, peak concurrent Drive API threads is ~40, well under
# the 200 req/s quota ceiling (see execute_google_drive_api_call) given today's multi-second
# per-call latencies - this is latency-bound, not quota-bound.
MAX_SOURCE_WORKERS = 8
DPI_HEIGHT_RATIO = 300 / 1110  # 300 DPI for image of vertical resolution 1110 pixels


def add_images_in_folder_to_list(source_type: Type[SourceType], folder: Folder, images: deque[Image]) -> None:
    try:
        images.extend(source_type.get_all_images_inside_folder(folder))
    except Exception as e:
        print(f"Uncaught exception while adding images in folder to list: **{e}**")


def explore_folder(source: Source, source_type: Type[SourceType], root_folder: Folder) -> list[Image]:
    """
    Explore `folder` and all nested folders to extract all images contained within them.
    """

    t0 = time.time()
    print(f"Locating images for source {TEXT_BOLD}{source.name}{TEXT_END}...", end="", flush=True)
    images: deque[Image] = deque()
    folders: list[Folder] = [root_folder]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        while len(folders) > 0:
            folder = folders.pop()
            pool.submit(add_images_in_folder_to_list, source_type=source_type, folder=folder, images=images)
            sub_folders = source_type.get_all_folders_inside_folder(folder)
            folders += list(filter(lambda x: not x.name.startswith("!"), sub_folders))
    image_list = list(images)
    print(
        f" and done! Located {TEXT_BOLD}{len(image_list):,}{TEXT_END} images "
        f"in {TEXT_BOLD}{(time.time() - t0):.2f}{TEXT_END} seconds."
    )
    return image_list


def transform_image_into_object(source: Source, image: Image, tags: Tags) -> Card:
    # reasons why an image might be invalid
    assert image.size <= (
        MAX_SIZE_MB * 1_000_000
    ), f"Image size is greater than {MAX_SIZE_MB} MB at **{int(image.size / 1_000_000)}** MB"
    # this can also raise AssertionError
    (
        language,
        name,
        extracted_tags,
        extension,
        canonical_card_pk,
        canonical_artist_pk,
        expansion_hint,
    ) = image.unpack_name(tags=tags)

    searchable_name = to_searchable(name)
    dpi = 10 * round(int(image.height) * DPI_HEIGHT_RATIO / 10)
    source_verbose = source.name
    priority = 1 if ("(" in name and ")" in name) or len(extracted_tags) > 0 else 2

    folder_location = image.folder.get_full_path(tags=tags)
    if folder_location == settings.DEFAULT_CARDBACK_FOLDER_PATH:
        if name == settings.DEFAULT_CARDBACK_IMAGE_NAME:
            priority += 10
        priority += 5
    if "basic" in image.folder.name.lower():
        priority += 5
        source_verbose += " Basics"

    card_type = CardTypes.CARD
    if "token" in image.folder.name.lower():
        card_type = CardTypes.TOKEN
        source_verbose = f"{source_verbose} Tokens"
    elif "cardbacks" in image.folder.name.lower() or "card backs" in image.folder.name.lower():
        card_type = CardTypes.CARDBACK
        source_verbose = f"{source_verbose} Cardbacks"

    return Card(
        identifier=image.id,
        card_type=card_type,
        name=name,
        priority=priority,
        source=source,
        source_verbose=source_verbose,
        folder_location=folder_location,
        dpi=dpi,
        searchq=searchable_name,
        extension=extension,
        date_created=image.created_time,
        date_modified=image.modified_time,
        size=image.size,
        tags=list(extracted_tags),
        language=(language or DEFAULT_LANGUAGE).alpha_2.upper(),
        canonical_card_id=canonical_card_pk,
        canonical_artist_id=canonical_artist_pk,
        expansion_hint=expansion_hint or "",
        # content_phash deliberately left unset (defaults to None/NULL - "not yet computed") -
        # populated by hash_newly_created_cards below, for CREATED cards only. This function
        # builds an in-memory, not-yet-persisted Card from folder-listing metadata only (no
        # image fetch here at all).
    )


def transform_images_into_objects(source: Source, images: list[Image], tags: Tags) -> list[Card]:
    """
    Transform `images`, which are all associated with `source`, into a set of Django ORM objects ready to be
    synchronised to the database.
    """

    print(f"Generating objects for source {TEXT_BOLD}{source.name}{TEXT_END}...", end="", flush=True)
    t0 = time.time()

    cards: list[Card] = []
    card_count = 0
    cardback_count = 0
    token_count = 0
    errors: list[str] = []  # report on all exceptions at the end

    for image in images:
        try:
            card = transform_image_into_object(source, image, tags)
            cards.append(card)
            if card.card_type == CardTypes.CARD:
                card_count += 1
            elif card.card_type == CardTypes.CARDBACK:
                cardback_count += 1
            elif card.card_type == CardTypes.TOKEN:
                token_count += 1
        except AssertionError as e:
            errors.append(
                f"Assertion error while processing **{image.name}** (identifier **{image.id}**) will not be indexed "
                f"for the following reason: **{e}**"
            )
        except Exception as e:
            errors.append(
                f"Uncaught exception while processing image **{image.name}** (identifier **{image.id}**): **{e}**"
            )
    print(
        f" and done! Generated {TEXT_BOLD}{card_count:,}{TEXT_END} card/s, {TEXT_BOLD}{cardback_count:,}{TEXT_END} "
        f"cardback/s, and {TEXT_BOLD}{token_count:,}{TEXT_END} token/s in "
        f"{TEXT_BOLD}{(time.time() - t0):.2f}{TEXT_END} seconds."
    )
    if errors:
        print("The following cards failed to process:", flush=True)
        for error in errors:
            print(f"* {error}", flush=True)

    return cards


def hash_newly_created_cards(created: list[Card]) -> None:
    """
    Hash-at-ingest (docs/features/printing-tags.md, 2026-07-16): computes and sets
    `content_phash` in-memory on every card in `created`, before it's ever written to the DB.
    CREATED cards only, deliberately - an UPDATED card (existing identifier, some metadata
    changed) already has a `content_phash` in the DB that this sync's own `bulk_update` call
    never touches (see bulk_sync_objects - content_phash isn't in that field list), so there is
    nothing to hash for that cohort here; a genuinely changed image at the same Drive file id
    (rare - Drive normally assigns a new id on real content replacement) isn't detected or
    corrected by this function - the standalone backfill command's NULL-only filter is the
    correction path if that's ever suspected for a specific card.

    A real, per-card network fetch (see image_cdn_fetch.fetch_card_image) - this pipeline
    doesn't touch image bytes anywhere else (explore_folder only reads Drive folder-listing
    metadata), so this is genuine new cost, not a free byproduct of existing work. Threaded to
    match this module's own MAX_WORKERS concurrency for Drive scanning. Best-effort per card: a
    fetch/hash failure just leaves that card's content_phash unset (NULL) for the backfill
    command to retry later - never blocks the sync.
    """
    if not created:
        return
    print(f"Hashing {TEXT_BOLD}{len(created)}{TEXT_END} newly-created card image/s...", end="", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        hashes = list(executor.map(local_phash.compute_content_phash_for_card, created))
    hashed_count = 0
    for card, content_hash in zip(created, hashes):
        if content_hash is not None:
            card.content_phash = content_hash
            hashed_count += 1
    print(
        f" and done! Hashed {TEXT_BOLD}{hashed_count}{TEXT_END}/{TEXT_BOLD}{len(created)}{TEXT_END} in "
        f"{TEXT_BOLD}{(time.time() - t0):.2f}{TEXT_END} seconds."
    )


def bulk_sync_objects(source: Source, cards: list[Card]) -> None:
    print(f"Synchronising objects to database for source {TEXT_BOLD}{source.name}{TEXT_END}...", end="", flush=True)
    t0 = time.time()

    incoming = {card.identifier: card for card in cards}
    incoming_ids = set(incoming.keys())
    existing = {card.identifier: card for card in Card.objects.filter(source=source)}
    existing_ids = set(existing.keys())
    common_ids = incoming_ids & existing_ids

    # Merge any resolved tag-vote consensus into the freshly re-extracted tags *before* the
    # change-detection check below runs, so a scheduled re-scan can never silently revert a
    # community-resolved tag correction back to whatever the filename currently says (only
    # `common_ids` can have prior votes at all - a vote's `card` FK requires an existing PK,
    # so a brand-new card being `bulk_create`d can't yet have any).
    tag_overlay = get_resolved_tag_overlay(existing[identifier].pk for identifier in common_ids)
    for identifier in common_ids:
        overlay = tag_overlay.get(existing[identifier].pk)
        if not overlay:
            continue
        tags = set(incoming[identifier].tags)
        for tag_name, polarity in overlay.items():
            if polarity == VotePolarity.APPLY:
                tags.add(tag_name)
            else:
                tags.discard(tag_name)
        incoming[identifier].tags = sorted(tags)

    created = [incoming[identifier] for identifier in incoming_ids - existing_ids]
    updated: list[Card] = []
    for identifier in common_ids:
        if (
            # if an update has been recorded on the source's end...
            (incoming[identifier].date_modified > existing[identifier].date_modified)
            # or if the card's tags have changed...
            | (set(incoming[identifier].tags) != set(existing[identifier].tags))
            # or if the card's name has changed...
            | (incoming[identifier].name != existing[identifier].name)
            # or if the canonical card this card is associated with has changed...
            | (incoming[identifier].canonical_card_id != existing[identifier].canonical_card_id)
            # or if the canonical artist this card is associated with has changed...
            | (incoming[identifier].canonical_artist_id != existing[identifier].canonical_artist_id)
            # or if the expansion hint has changed.
            | (incoming[identifier].expansion_hint != existing[identifier].expansion_hint)
        ):
            # record an update for this card
            incoming[identifier].pk = existing[identifier].pk  # this must be explicitly set for bulk_update.
            updated.append(incoming[identifier])
    deleted_ids = existing_ids - incoming_ids
    deleted = [existing[identifier] for identifier in deleted_ids]

    hash_newly_created_cards(created)

    with transaction.atomic():
        if created:
            Card.objects.bulk_create(created)
            CardSearch().update(list(created), action="index")
        if updated:
            Card.objects.bulk_update(
                updated,
                # update every field except for `identifier`
                [
                    "card_type",
                    "name",
                    "priority",
                    "source",
                    "source_verbose",
                    "folder_location",
                    "dpi",
                    "searchq",
                    "extension",
                    "date_created",
                    "date_modified",
                    "size",
                    "tags",
                    "language",
                    "canonical_card",
                    "canonical_artist",
                    "expansion_hint",
                ],
                batch_size=1000,
            )
            # as per this thread https://github.com/django-es/django-elasticsearch-dsl/issues/224#issuecomment-551955511
            # action type "index" is used for indexing new objects as well as updating existing objects
            CardSearch().update(list(updated), action="index")
        if deleted_ids:
            Card.objects.filter(identifier__in=deleted_ids).delete()
            CardSearch().update(list(deleted), action="delete")
    print(
        f" and done! That took {TEXT_BOLD}{(time.time() - t0):.2f}{TEXT_END} seconds.\n"
        f"Created {TEXT_BOLD}{len(created)}{TEXT_END}, "
        f"updated {TEXT_BOLD}{len(updated)}{TEXT_END}, "
        f"and deleted {TEXT_BOLD}{len(deleted_ids)}{TEXT_END} cards."
    )


def update_database_for_source(source: Source, source_type: Type[SourceType], root_folder: Folder, tags: Tags) -> None:
    images = explore_folder(source=source, source_type=source_type, root_folder=root_folder)
    cards = transform_images_into_objects(source=source, images=images, tags=tags)
    bulk_sync_objects(source=source, cards=cards)


def _update_database_for_source_isolated(
    source: Source, source_type: Type[SourceType], root_folder: Folder, tags: Tags
) -> None:
    """
    One source's failure (e.g. a stray duplicate-key race against a concurrent scan of the
    same source, or a since-deleted file) must never abort every other source's scan - each
    `Card.objects.filter(source=source)` in `bulk_sync_objects` only ever touches that one
    source's own rows, so sources are already fully independent units of work; this just makes
    sure an exception in one doesn't propagate past its own future.
    """
    try:
        update_database_for_source(source=source, source_type=source_type, root_folder=root_folder, tags=tags)
    except Exception as e:
        print(f"Failed to update source {TEXT_BOLD}{source.name}{TEXT_END}: **{e}**")


def update_database(source_key: Optional[str] = None) -> None:
    """
    Update the contents of the database against the configured sources.
    If `source_key` is specified, only update that source; otherwise, update all sources.
    """

    # try to work around https://github.com/googleapis/google-api-python-client/issues/2186
    socket.setdefaulttimeout(15 * 60)
    tags = Tags()
    if source_key:
        try:
            source = Source.objects.get(key=source_key)
            source_type = SourceTypeChoices.get_source_type(SourceTypeChoices[source.source_type])
            if (root_folder := source_type.get_all_folders([source])[source.key]) is not None:
                update_database_for_source(source=source, source_type=source_type, root_folder=root_folder, tags=tags)
        except Source.DoesNotExist:
            print(
                f"Invalid source specified: {TEXT_BOLD}{source_key}{TEXT_END}"
                f"\nYou may specify one of the following sources: "
                f"{', '.join([f'{TEXT_BOLD}{x.key}{TEXT_END}' for x in Source.objects.all()])}"
            )
            exit(-1)
    else:
        print("Updating the database for all sources.")
        sources = sorted(Source.objects.all(), key=lambda x: x.source_type)
        for source_type_name, grouped_sources_iterable in groupby(sources, lambda x: x.source_type):
            grouped_sources = list(grouped_sources_iterable)
            source_type = SourceTypeChoices.get_source_type(SourceTypeChoices[source_type_name])
            folders = source_type.get_all_folders(grouped_sources)
            print(
                f"Identified the following sources of type "
                f"{TEXT_BOLD}{SourceTypeChoices[source_type_name].label}{TEXT_END}: "
                f"{', '.join([f'{TEXT_BOLD}{x.name}{TEXT_END}' for x in grouped_sources])}\n"
            )
            # Sources are scanned concurrently (bounded by MAX_SOURCE_WORKERS) - each is an
            # independent unit of work (its own Drive folder tree, its own `Card` rows), so
            # this only shortens wall-clock time; it doesn't change what gets written. Submitted
            # up front and gathered at the end (rather than one-in-one-out) so a slow source
            # never blocks the pool from picking up the next one.
            with ThreadPoolExecutor(max_workers=MAX_SOURCE_WORKERS) as pool:
                futures = [
                    pool.submit(
                        _update_database_for_source_isolated,
                        source=grouped_source,
                        source_type=source_type,
                        root_folder=root_folder,
                        tags=tags,
                    )
                    for grouped_source in grouped_sources
                    if (root_folder := folders[grouped_source.key]) is not None
                ]
                for future in futures:
                    future.result()
                    print("")


__all__ = ["update_database"]
