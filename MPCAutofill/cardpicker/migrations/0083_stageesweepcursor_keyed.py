# Generated for issue #460 - generalizes StageESweepCursor from a singleton to keyed rows
# (name="stage_c"/"stage_d"), one independent cursor per backlog walk.

from django.db import migrations, models


def _rename_existing_row_to_stage_c(apps, schema_editor) -> None:  # type: ignore  # TODO: type this properly
    """The pre-#460 singleton row (seeded by issue #458, used by `_select_micro_batch`'s Stage C
    backlog walk) becomes the keyed `stage_c` row - `position`/`wrap_count` preserved untouched, so
    an in-progress Stage C sweep resumes from exactly where it left off. There is at most one row
    at this point in the migration (the pre-#460 `singleton_key` field was `unique=True`), so this
    is safe as an unconditional `update()` rather than a `get_or_create`."""
    StageESweepCursor = apps.get_model("cardpicker", "StageESweepCursor")
    StageESweepCursor.objects.update(name="stage_c")


def _noop_reverse(apps, schema_editor) -> None:  # type: ignore  # TODO: type this properly
    # Nothing to undo - the schema-reversal steps below (AlterField/AddField reversed) already
    # drop the `name` column entirely, taking the data with it.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0082_stageesweepcursor"),
    ]

    operations = [
        migrations.AddField(
            model_name="stageesweepcursor",
            name="name",
            field=models.CharField(max_length=16, null=True),
        ),
        migrations.RunPython(_rename_existing_row_to_stage_c, _noop_reverse),
        migrations.AlterField(
            model_name="stageesweepcursor",
            name="name",
            field=models.CharField(max_length=16, unique=True),
        ),
        migrations.RemoveField(
            model_name="stageesweepcursor",
            name="singleton_key",
        ),
    ]
