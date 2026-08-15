# Hand-written (not `manage.py makemigrations`-generated - same convention as migrations 0104/
# 0110/0111) to add the blank-string-sentinel art_edge_class field to cardpicker.models.
# ImageEvidence (issue #830 defect 3). Metadata-only on Postgres: AddField with a fixed default
# never rewrites existing rows' own stored bytes on this column type.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0112_imageevidence_pinline_inset_call_bottom_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="imageevidence",
            name="art_edge_class",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
    ]
