"""
Drop `cardpicker_printingtagvote` (owner ruling, 2026-07-29: retire `PrintingTagVote`).

SAFE TO RUN BECAUSE THE TABLE IS EMPTY, VERIFIED AGAINST PRODUCTION RATHER THAN ASSUMED.
`PrintingTagVote.objects.count()` was `0` on the live database on 2026-07-29 (read-only shell,
re-confirmed by the author of this migration on top of PR #599's own measurement), with 0 rows of
any source and therefore 0 human votes. Human votes are the one thing in this system that cannot
be re-derived; there are none here, so there is nothing to migrate, export or rescue. If a future
operator finds this migration unapplied on a database where the table is NOT empty, STOP: dump the
rows before proceeding. `DeleteModel` is not reversible in the sense that matters - reversing it
recreates an EMPTY table, never the rows.

WHY, IN ONE LINE: it had no consensus resolver anywhere in the repo's history, no reader outside
the Django admin, no frontend caller of its submit endpoint, and its only machine writer
(`manage.py import_external_ip_tags`, retired in the same change) never ran once. See PR #599 §§3.1,
7.1 and 8 (its report, `2026-07-29-printing-vs-illustration-tag-grain.md`, lands under docs/reports/
when that PR merges), and the retirement record in docs/features/printing-tags.md.

NOT `CardPrintingTag`, WHICH HAS 167,229 ROWS AND IS THE ENTIRE STAGE D PRINTING CHANNEL. The two
names share four characters and nothing else; an earlier orchestrator conflated the two while
briefing this very change, and a closely-related identity-vs-channel confusion destroyed 53,966
vote rows on this project on 2026-07-27 (operations correction log OPS-CORR-0008). The table this
migration drops is `cardpicker_printingtagvote`. `cardpicker_cardprintingtag` is untouched.

MIGRATION NUMBERING - READ BEFORE MERGING. `cardpicker`'s single leaf on `master` at the time of
writing is `0098_card_illustration_consensus_fields`, and that is what this depends on, so this
branch is migratable and single-leaf on its own today. The FILE is numbered 0101 because the
orchestrator has allocated 0099 to PR #601 (already renumbered to
`0099_rename_printings_count_catalogued` on its branch) and 0100 to PR #604 (still numbered 0098
on its branch as `0098_superseded_card_printing_tag_archive`; expected to become
`0100_superseded_card_printing_tag_archive`).

    => WHICHEVER OF #601 / #604 MERGES BEFORE THIS ONE, THIS MIGRATION'S `dependencies` MUST BE
       REPOINTED AT THE NEW LEAF ON REBASE. Leaving it on 0098 after 0099/0100 land gives
       `cardpicker` two leaf nodes, which is not a cosmetic problem: `pytest-django` builds its
       test database by running `migrate`, so a two-leaf graph takes EVERY branch's CI down at
       test-database setup, not just this one. PR #576 exists to repair exactly that.

Depending on the not-yet-existent `0100_...` instead was considered and rejected for the reason
`0098_superseded_card_printing_tag_archive`'s own docstring gives: "a dependency on a migration
that does not exist on `master` makes THIS branch unmigratable today, with certainty, in exchange
for avoiding a collision that may never happen. A collision, by contrast, is loud and caught at
merge time by `makemigrations --check`." That is this repo's established convention and it is
followed here rather than diverged from.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0098_card_illustration_consensus_fields"),
    ]

    operations = [
        migrations.DeleteModel(name="PrintingTagVote"),
    ]
