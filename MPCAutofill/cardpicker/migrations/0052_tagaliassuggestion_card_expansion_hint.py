import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0051_remove_cardprintingtag_cardprintingtag_unique_printing_vote_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="card",
            name="expansion_hint",
            field=models.CharField(blank=True, db_index=True, max_length=10),
        ),
        migrations.CreateModel(
            name="TagAliasSuggestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("raw_text", models.CharField(max_length=200, unique=True)),
                ("confidence", models.FloatField()),
                ("occurrence_count", models.IntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("auto_accepted", "Auto-accepted"),
                            ("accepted", "Accepted"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "suggested_tag",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="cardpicker.tag"
                    ),
                ),
            ],
        ),
    ]
