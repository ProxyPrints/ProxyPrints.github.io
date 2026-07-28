from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0088_printingtagvote"),
    ]

    operations = [
        migrations.AddField(
            model_name="canonicalprintingmetadata",
            name="illustration_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
