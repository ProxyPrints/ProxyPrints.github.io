# Hand-written (not `manage.py makemigrations`-generated - same convention as migration 0080
# `questionfeedservedlog.py`) to exactly match `cardpicker.models.CardQuestionAbstention` as of
# this migration.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0103_canonicalprintingmetadata_layout"),
    ]

    operations = [
        migrations.CreateModel(
            name="CardQuestionAbstention",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anonymous_id", models.CharField(max_length=40)),
                ("question_type", models.CharField(max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "card",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="question_abstentions",
                        to="cardpicker.card",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="cardquestionabstention",
            constraint=models.UniqueConstraint(
                fields=("card", "anonymous_id", "question_type"), name="cardquestionabstention_unique"
            ),
        ),
    ]
