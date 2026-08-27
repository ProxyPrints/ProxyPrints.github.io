"""
Adds `Card.content_phash_bands` (see that field's own comment in models.py) and backfills it for
every existing row that already carries a `content_phash` - the candidate-retrieval index
`question_feed._near_duplicate_serving_card_ids` needs to widen near-duplicate serving groups by
phash proximity instead of by matching `name`, without a catalogue-wide popcount scan.

The band-splitting logic is duplicated here rather than imported from `cardpicker.local_phash`
(this repo's migrations convention - see 0097's own docstring for why: a migration is a dated
historical artifact, and importing evolving app code into it lets a later, unrelated edit to that
code silently change what an already-applied migration is understood to have done). Keep this in
sync with `local_phash.content_phash_bands`/`PHASH_BAND_COUNT` if either ever changes; they are
pinned to compute identically by `TestContentPhashBandsMigrationMatchesLivePhashBands` in
`cardpicker/tests/test_local_phash.py`.
"""

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

_HASH_BITS = 64
_PHASH_BAND_COUNT = 5
_PHASH_BAND_WIDTHS = [_HASH_BITS // _PHASH_BAND_COUNT] * (_PHASH_BAND_COUNT - 1)
_PHASH_BAND_WIDTHS.append(_HASH_BITS - sum(_PHASH_BAND_WIDTHS))
_PHASH_BAND_TAG_SHIFT = 16
_BACKFILL_BATCH_SIZE = 5000


def _content_phash_bands(phash: int) -> list[int]:
    unsigned = phash & ((1 << _HASH_BITS) - 1)
    bands = []
    shift = 0
    for band_index, width in enumerate(_PHASH_BAND_WIDTHS):
        mask = (1 << width) - 1
        bands.append((band_index << _PHASH_BAND_TAG_SHIFT) | ((unsigned >> shift) & mask))
        shift += width
    return bands


def backfill_content_phash_bands(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Card = apps.get_model("cardpicker", "Card")
    to_persist = []
    updated = 0
    for card in Card.objects.filter(content_phash__isnull=False).only("pk", "content_phash").iterator():
        card.content_phash_bands = _content_phash_bands(card.content_phash)
        to_persist.append(card)
        if len(to_persist) >= _BACKFILL_BATCH_SIZE:
            Card.objects.bulk_update(to_persist, ["content_phash_bands"], batch_size=_BACKFILL_BATCH_SIZE)
            updated += len(to_persist)
            to_persist = []
    if to_persist:
        Card.objects.bulk_update(to_persist, ["content_phash_bands"], batch_size=_BACKFILL_BATCH_SIZE)
        updated += len(to_persist)
    print(f"  0120: backfilled content_phash_bands on {updated} Card rows")


def clear_content_phash_bands(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Card = apps.get_model("cardpicker", "Card")
    Card.objects.filter(content_phash_bands__isnull=False).update(content_phash_bands=None)


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0119_cardscanlog_frame_mismatch_direction"),
    ]

    operations = [
        migrations.AddField(
            model_name="card",
            name="content_phash_bands",
            field=ArrayField(models.IntegerField(), blank=True, null=True, size=None),
        ),
        migrations.RunPython(backfill_content_phash_bands, clear_content_phash_bands),
        migrations.AddIndex(
            model_name="card",
            index=GinIndex(fields=["content_phash_bands"], name="card_content_phash_bands_gin"),
        ),
    ]
