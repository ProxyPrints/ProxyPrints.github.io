"""
Create `ArchivedCardPrintingTag` - the table a superseded machine printing vote moves to instead
of being deleted (owner ruling, 2026-07-29: "keep at least one prior generation of votes, whose
votes are NOT counted"). See the model's own docstring in `cardpicker/models.py` for why this is a
separate table rather than retained generations in `cardpicker_cardprintingtag` itself; the short
version is that nine of the thirteen modules reading printing tags never consult
`vote_consensus.resolve_vote_weight`, so a zero-weight-by-run_id rule would not stop a retained
generation being displayed, counted, or - fatally - treated as "already voted" by the eligibility
querysets this work exists to un-suppress.

PURE `CreateModel`. No existing row is read, written or migrated: the table is created empty and
fills only from the moment `purge_stale_machine_votes` next supersedes something. Reversing this
migration drops the table and loses whatever archive it accumulated, which is correct - nothing
else's integrity depends on it.

DEPENDENCY NUMBERING
-------------------
Depends on `0099_rename_printings_count_catalogued` (PR #601), which is `cardpicker`'s single leaf
on `master`. Verified against the real file, not assumed: #601 merged as 7afff071 and its migration
declares `0098_card_illustration_consensus_fields` as its own sole dependency, so the chain is
0097 -> 0098 (#573) -> 0099 (#601) -> 0100 (this).

WHY A CHAIN AT ALL, RATHER THAN THREE MIGRATIONS ALL DECLARING 0098. There is no ordering
constraint between any of these three in substance - #601 renames a column on
`cardpicker_canonicalcard`, #573 added columns to `cardpicker_cardillustrationvote`, and this
creates a new table; no shared column, constraint or trigger. The chain exists purely to keep
`cardpicker` at a SINGLE LEAF NODE. Two leaves is not a cosmetic problem: `manage.py migrate`
refuses to run at all ("Conflicting migrations detected; multiple leaf nodes"), which breaks
test-database setup on EVERY branch in the repository, not just the offender's. That is the exact
failure PR #576 had to repair by hand after #568 and #570 both declared 0095 as their sole
dependency.

THIS MIGRATION'S OWN HISTORY, RECORDED SO THE REASONING IS NOT REPEATED WRONGLY. It was first
numbered 0098-on-0097, on the then-correct reasoning that #573 was still open and that depending on
a migration absent from `master` makes a branch unmigratable today, with certainty, in order to
avoid a collision that might never happen. #573 then merged, which inverted the trade-off: the
collision stopped being hypothetical and became a fact on `master` - and one invisible to every
normal signal, since different filenames mean no textual conflict, GitHub still reported the PR
mergeable, and CI stayed green because it had run against the pre-#573 tree. It was then renumbered
0100 and pointed at a 0099 that did not exist yet, which is why CI on this branch was legitimately
red for a while: `NodeNotFoundError`, the honest signal, kept until #601 actually landed rather
than papered over by pointing at a node that did exist.

THE GENERAL LESSON, now enforced mechanically rather than by attention: a migration's graph
position is a property of the MERGED result, not of the branch, and every branch-local signal -
textual conflict, mergeability, CI - is blind to it. PR #611's "One leaf per app (merged with the
base branch)" job is what checks it now.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cardpicker", "0099_rename_printings_count_catalogued"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArchivedCardPrintingTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_no_match", models.BooleanField(default=False)),
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
                ("peer", models.CharField(blank=True, max_length=64, null=True)),
                ("run_id", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("vote_surface", models.CharField(blank=True, max_length=64, null=True)),
                ("created_at", models.DateTimeField()),
                ("original_id", models.BigIntegerField()),
                ("superseded_by_run_id", models.CharField(blank=True, db_index=True, max_length=64, null=True)),
                ("archived_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "card",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="+", to="cardpicker.card"
                    ),
                ),
                (
                    "printing",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="cardpicker.canonicalcard",
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
            options={
                "indexes": [models.Index(fields=["card", "anonymous_id"], name="archived_printing_tag_idx")],
            },
        ),
    ]
