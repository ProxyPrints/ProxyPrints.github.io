"""
Adds `cardpicker_externalipillustration` - the illustration-grain derived store behind the
`external-ip` tag (owner rulings, 2026-07-29: the tag is named `external-ip` and not `UB`, and
"I say printing but it is an illustration thing really"). See `cardpicker/external_ip.py` and
docs/features/external-ip.md.

ADDITIVE AND EMPTY ON APPLY. `CreateModel` only - no column is added to, removed from, or
rewritten on any existing table, nothing is backfilled, and no data migration runs. The table is
empty until `manage.py import_external_ip_illustrations --write` is run deliberately, and every
row it will ever hold is re-derivable from the Scryfall Tagger `art_tags` feed plus the already-
ingested `promo_types` column. Reversing this migration therefore loses nothing that cannot be
rebuilt by re-running one command - unlike a vote table, it contains no human judgement.

NOT A `CanonicalIllustration` TABLE, AND MUST NOT BECOME ONE. The codebase has twice explicitly
refused to model illustrations as entities (`CardIllustrationVote`'s "NOT A FOREIGN KEY" section;
`Card.inferred_illustration_id`'s deliberate plain-UUIDField choice). This is a membership set:
nothing FKs to it, it stores no artwork attributes, and its only semantic is "this artwork is
drawn from an external IP". The model docstring records the same constraint for future readers.

MIGRATION NUMBERING - READ BEFORE MERGING, AND CHECK AGAIN AT MERGE TIME.
`cardpicker`'s single leaf on `master` at the time of writing is
`0098_card_illustration_consensus_fields`, and that is what this migration DEPENDS on, so this
branch is single-leaf and migratable on its own today. The FILE is numbered 0103 because the
following numbers were already allocated to open PRs when this was written (2026-07-29):

    0099  PR #601  rename_printings_count_catalogued        (numbered 0099 on its branch)
    0100  PR #604  superseded_card_printing_tag_archive     (numbered 0100 on its branch)
    0100  PR #614  canonicalprintingmetadata_scryfall_count (COLLIDES with #604 - not this
                                                             branch's collision to resolve, but
                                                             it is real and one of the two must
                                                             renumber before the second merges)
    0101  PR #615  delete_printingtagvote                   (numbered 0101 on its branch)
    0102  reserved for the gold-border work, per the orchestrator's allocation

THE ASSUMPTION, STATED LOUDLY: 0102 is assumed taken and 0103 assumed free. If the gold-border
work never lands, this file is simply numbered one higher than it needed to be, which is
harmless - Django orders by the `dependencies` graph, not by filename. What is NOT harmless is
two migrations depending on the same parent, so whoever merges this SECOND after any of the
above must confirm `cardpicker` still has exactly one leaf as merged. PR #611 adds a CI guard
that fails on precisely that condition; this branch is written to pass it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0098_card_illustration_consensus_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalIpIllustration",
            fields=[
                ("illustration_id", models.UUIDField(primary_key=True, serialize=False)),
                ("sources", models.JSONField(blank=True, default=list)),
                ("tagger_slugs", models.JSONField(blank=True, default=list)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
