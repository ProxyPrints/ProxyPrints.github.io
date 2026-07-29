"""
Rename `CanonicalPrintingMetadata.printings_count` -> `catalogued_printings_count`.

WHY THIS MIGRATION EXISTS
-------------------------
The old name asserted a source the column does not have. A reader - and, as it turned out, the
docs and three module docstrings - took `printings_count` on a model whose own docstring said
"Scryfall printing-level fields" to mean "how many printings of this card Scryfall publishes".
It never meant that. `import_scryfall_printing_metadata` builds a `Counter` over
`CanonicalCard.canonical_id` - OUR table - and stores each row's oracle-group size here. Rows
whose `canonical_id` is NULL (81 in production on 2026-07-29) are stored as 1 by fiat, since
there is no oracle group to count at all.

The gap is not academic. A column derived from our catalogue cannot detect that our catalogue is
incomplete, which is exactly what `deductive_backfill`'s D1 tier advertised it as doing. Counting
the Scryfall bulk-data file directly on 2026-07-29 finds 2 oracle ids where we hold one row and
Scryfall publishes more - invisible to this column by construction.

WHAT IT TOUCHES, EXACTLY
------------------------
One column name on one table. `RenameField` on PostgreSQL emits `ALTER TABLE ... RENAME COLUMN`,
which is a catalogue-metadata update: no table rewrite, no row locks held for the scan, no data
read or written. No value in any row changes. Fully reversible.

No raw SQL anywhere in the repo references this column (checked 2026-07-29 - every read and write
goes through the ORM), so renaming the database column as well as the Python attribute is safe.
Renaming only the Python attribute and pinning `db_column="printings_count"` was considered and
rejected: the column name is itself an assertion, and leaving the false one in the database for
anyone who opens a psql shell keeps the defect exactly where it did its damage.

MIGRATION-GRAPH NOTE
--------------------
This was written as `0098_rename_printings_count_catalogued` on top of
`0097_freeze_deductive_backfill_zero_weight_cohort` (master at 6bc3e166, which linearised an
earlier 0096 fork). **PR #573's own 0098 merged first** - `0098_card_illustration_consensus_fields`,
also depending on 0097 - so this one is the second to arrive and has been renumbered to 0099 and
repointed onto #573's migration, exactly as the note here originally said whichever merged second
must do.

Why it matters that this is not left forked: two 0098s both depending on 0097 give `cardpicker`
two leaf nodes, and `pytest-django` builds its test database by running `migrate`, so the fork
errors at test-database SETUP on *every* branch in the repo - not only the branch that introduced
it. That is the outage #576 had to repair at 0096. This migration is a pure rename with no
dependency on anything 0098 touches, so renumbering cost nothing.

A CI guard that fails a PR whose migration graph, MERGED WITH ITS BASE BRANCH, has more than one
leaf per app is in flight separately (branch `fix/migration-leaf-guard`). Checking a branch in
isolation cannot catch this: on this branch alone, before the renumber, the graph had exactly one
leaf and every check was green.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0098_card_illustration_consensus_fields"),
    ]

    operations = [
        migrations.RenameField(
            model_name="canonicalprintingmetadata",
            old_name="printings_count",
            new_name="catalogued_printings_count",
        ),
    ]
