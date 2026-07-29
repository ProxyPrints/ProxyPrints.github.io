"""THROWAWAY. Reconstructs the #573-vs-#601 collision so the guard can be seen going red in
real CI. This PR is a demonstration and must never merge."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0097_freeze_deductive_backfill_zero_weight_cohort"),
    ]

    operations = []
