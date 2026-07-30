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

MIGRATION NUMBERING - READ BEFORE MERGING, AND WHY THIS BRANCH'S CI IS RED ON PURPOSE.
This depends on `0100_superseded_card_printing_tag_archive` (PR #604). THAT MIGRATION IS NOT ON
`master` YET, so `migrate` on this branch alone fails with `NodeNotFoundError` and every test
errors at `pytest-django`'s test-database setup. That red is expected and correct, and it clears
the moment #604 merges. Do not "fix" it by repointing at `0099`.

    => MERGE ORDER IS FIXED: #604 FIRST, THEN THIS. Chosen deliberately on 2026-07-30 while
       repairing both PRs together. #604 is the larger change and the Stage-D monolith's core, so
       it is the one that gets to be verifiable and green on its own branch; this PR is small and
       cheap to hold. The two orders are symmetric - exactly one of the two branches can be
       migratable at a time, because only one of them can own the dependency on `master`'s real
       leaf - so the choice is which PR to leave unverifiable, not whether to leave one.

The rejected alternative, recorded so it is not re-proposed: depend on `0099_rename_printings_count_catalogued`
(`master`'s real leaf today) and renumber this 0100. That makes THIS branch green immediately, but
#604 already holds 0100-on-0099, so after both merge `cardpicker` has TWO leaves - 0100 and 0100's
sibling - and a two-leaf graph is not a cosmetic problem: `pytest-django` builds its test database
by running `migrate`, so it takes EVERY branch's CI in the repository down at test-database setup,
not just the offender's. PR #576 exists to repair exactly that, by hand. A local red on one PR
costs one PR; a forked graph costs the whole repo. The earlier version of this docstring preferred
the green-now convention, on the then-true premise that no other PR had claimed a number on top of
`master`'s leaf. #604 has now claimed 0100, which inverts the trade-off.

The chain is therefore 0098 (#573) -> 0099 (#601) -> 0100 (#604) -> 0101 (this), and it is
verified mechanically rather than by eye: `MigrationLoader(None).graph.leaf_nodes("cardpicker")`
returns exactly one node on the simulated merge of `master` + #604 + this branch. PR #611's
"One leaf per app (merged with the base branch)" job is what enforces it from here on.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0100_superseded_card_printing_tag_archive"),
    ]

    operations = [
        migrations.DeleteModel(name="PrintingTagVote"),
    ]
