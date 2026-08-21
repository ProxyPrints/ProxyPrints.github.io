from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0113_imageevidence_art_edge_class"),
    ]

    operations = [
        migrations.AddField(
            model_name="canonicalprintingmetadata",
            name="color_identity",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="canonicalprintingmetadata",
            name="type_line",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
