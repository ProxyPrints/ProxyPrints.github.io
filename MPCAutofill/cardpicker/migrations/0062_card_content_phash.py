from typing import Any

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def clear_placeholder_zero_hashes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """
    Every existing Card.image_hash value is the literal placeholder 0 - cardpicker.sources.
    update_database always wrote it that way (see git history prior to 2026-07-16's
    hash-at-ingest work); nothing was ever really computed for this field. Migrating 0 -> NULL
    here means every existing row correctly reads as "not yet computed" (content_phash's own
    NULL contract, see the field's docstring in models.py) rather than a real hash value of 0 -
    the one-time backfill command (local_backfill_content_phash) then picks these up via its own
    NULL-only filter.
    """
    Card: Any = apps.get_model("cardpicker", "Card")
    Card.objects.filter(content_phash=0).update(content_phash=None)


def noop_reverse(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0061_pilotrunledger_cardartistvote_run_id_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="card",
            old_name="image_hash",
            new_name="content_phash",
        ),
        migrations.AlterField(
            model_name="card",
            name="content_phash",
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(clear_placeholder_zero_hashes, noop_reverse),
    ]
