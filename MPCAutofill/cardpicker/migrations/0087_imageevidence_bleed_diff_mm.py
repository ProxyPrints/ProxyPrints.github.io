from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0086_imageevidence_artbox_crop_px_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="imageevidence",
            name="bleed_diff_mm",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
