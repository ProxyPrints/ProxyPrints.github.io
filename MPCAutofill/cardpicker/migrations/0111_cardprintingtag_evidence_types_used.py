# Hand-written (not `manage.py makemigrations`-generated - same convention as migrations 0104/
# 0110) to add the nullable evidence_types_used field to cardpicker.models.CardPrintingTag
# (issue #797). Metadata-only on Postgres: AddField with null=True never rewrites existing rows,
# so every historical vote reads back with evidence_types_used=None until a later backfill pass
# populates it.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0110_cardquestionabstention_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardprintingtag",
            name="evidence_types_used",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
