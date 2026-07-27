import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0086_imageevidence_artbox_crop_px_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PrintingTagVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anonymous_id", models.CharField(max_length=40)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("user", "User"),
                            ("admin", "Admin"),
                            ("deduction", "Deduction"),
                            ("ocr", "OCR"),
                            ("federated", "Federated"),
                            ("implicit", "Implicit"),
                        ],
                        default="user",
                        max_length=10,
                    ),
                ),
                ("confidence", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "peer",
                    models.CharField(
                        blank=True,
                        help_text="Federation peer name; set only when source='federated'",
                        max_length=64,
                        null=True,
                    ),
                ),
                ("run_id", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("vote_surface", models.CharField(blank=True, max_length=64, null=True)),
                ("polarity", models.SmallIntegerField(choices=[(1, "Apply"), (-1, "Not applicable")])),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "printing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="printing_tag_votes",
                        to="cardpicker.canonicalcard",
                    ),
                ),
                (
                    "tag",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="printing_votes",
                        to="cardpicker.tag",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="printingtagvote",
            constraint=models.UniqueConstraint(
                fields=["printing", "tag", "anonymous_id"], name="printingtagvote_unique_vote"
            ),
        ),
    ]
