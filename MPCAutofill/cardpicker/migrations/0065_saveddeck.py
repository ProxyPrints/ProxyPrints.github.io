import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cardpicker", "0064_cardartistvote_vote_surface_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedDeck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("state", models.JSONField(blank=True, default=dict)),
                (
                    "kind",
                    models.CharField(
                        choices=[("deck", "Deck"), ("snapshot", "Snapshot")], default="deck", max_length=20
                    ),
                ),
                ("is_public", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_decks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="saveddeck",
            constraint=models.UniqueConstraint(
                condition=models.Q(("kind", "deck")),
                fields=("owner", "name"),
                name="saveddeck_owner_name_unique_for_decks",
            ),
        ),
    ]
