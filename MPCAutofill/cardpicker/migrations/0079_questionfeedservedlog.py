# Hand-written (not `manage.py makemigrations`-generated - see the PR this migration ships
# with for why) to exactly match `cardpicker.models.QuestionFeedServedLog`/
# `QuestionFeedServedPool` as of this migration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0078_pilotrunledger_counters"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuestionFeedServedLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anonymous_id", models.CharField(db_index=True, max_length=40)),
                (
                    "pool",
                    models.CharField(
                        choices=[("likely_resolve", "Likely resolve"), ("remainder", "Remainder")], max_length=16
                    ),
                ),
                ("question_type", models.CharField(max_length=32)),
                ("origin_reason", models.CharField(blank=True, default="", max_length=64)),
                ("served_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [models.Index(fields=["anonymous_id", "served_at"], name="qf_served_log_anon_served_idx")],
            },
        ),
    ]
