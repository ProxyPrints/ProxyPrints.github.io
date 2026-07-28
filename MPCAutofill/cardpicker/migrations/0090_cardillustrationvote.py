import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cardpicker", "0089_canonicalprintingmetadata_illustration_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="CardIllustrationVote",
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
                ("illustration_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("is_unknown", models.BooleanField(default=False)),
                (
                    "card",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="illustration_votes",
                        to="cardpicker.card",
                    ),
                ),
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
            ],
        ),
        migrations.AddConstraint(
            model_name="cardillustrationvote",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(("illustration_id__isnull", False), ("is_unknown", False)),
                    models.Q(("illustration_id__isnull", True), ("is_unknown", True)),
                    _connector="OR",
                ),
                name="cardillustrationvote_illustration_xor_unknown",
            ),
        ),
        migrations.AddConstraint(
            model_name="cardillustrationvote",
            constraint=models.UniqueConstraint(
                fields=("card", "anonymous_id"), name="cardillustrationvote_unique_vote"
            ),
        ),
    ]
