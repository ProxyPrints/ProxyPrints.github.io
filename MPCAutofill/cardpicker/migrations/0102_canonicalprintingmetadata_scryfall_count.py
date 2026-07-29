"""
Add `CanonicalPrintingMetadata.scryfall_default_cards_printings_count`.

WHY THIS MIGRATION EXISTS
-------------------------
`deductive_backfill`'s D1 tier advertised, and cast votes at `confidence=0.95` on, a guarantee it
did not implement: that a name matching exactly one `CanonicalCard` row was "cross-verified
against Scryfall's own printings_count (not just 'our table happens to have one row')". The
column it read is a count of OUR OWN rows (renamed `catalogued_printings_count` in 0099), so the
check restated the name-uniqueness test above it and excluded nothing - 137 D1 candidates before
it and 137 after, measured against the live catalogue on 2026-07-29 (issue #600).

This column is the missing half. It holds how many rows SCRYFALL's `default_cards` bulk export
lists for this row's oracle card, so that D1 can gate on the two counts AGREEING - which is the
guarantee it was advertised as having, and which cannot be derived from our own table.

NO NEW SCRYFALL TRAFFIC. `import_scryfall_printing_metadata` already downloads and parses
`default_cards`; the value is a second `Counter` over rows it has already read. Per-card API
lookups for the same figure would be ~113k requests against Scryfall, which is forbidden here.

WHAT IT TOUCHES, EXACTLY
------------------------
One nullable integer column, added with `default=None`. On PostgreSQL an `ADD COLUMN` whose
default is NULL is a catalogue-metadata update: no table rewrite, no row data read or written,
brief ACCESS EXCLUSIVE lock only. Fully reversible. Every row starts NULL and stays NULL until
the next `import_scryfall_printing_metadata` run populates it.

NULL IS LOAD-BEARING, NOT A PLACEHOLDER. It means "Scryfall publishes no count for this row" -
`canonical_id` is NULL (81 rows in production, exactly the 81 bulk rows Scryfall itself ships
with no `oracle_id`), or the oracle id is absent from the bulk file. D1 treats NULL as
unverifiable and excludes it, rather than repeating the previous defect of substituting a
fabricated 1. This is also why no data migration backfills the column: a value invented here,
outside the import pass that reads the bulk file, would be exactly such a fabrication. Until
the importer next runs, every row reads NULL and D1 correctly declines to vote.

MIGRATION-GRAPH NOTE - THE FILE NUMBER AND THE DEPENDENCY DO NOT MATCH, DELIBERATELY
------------------------------------------------------------------------------------
Depends on `0099_rename_printings_count_catalogued` (PR #601), which renames the column this one
is designed to be compared against: gating D1 on `catalogued_printings_count` requires the renamed
column to exist. #601 HAS MERGED (master commit 7afff071) and `0099` is `cardpicker`'s single leaf
on `master`, so this dependency is REAL, resolvable today, and leaves the app single-leaf when
this branch is merged with `master`.

The FILE is numbered `0102` because the orchestrator has allocated the intervening numbers to two
still-open PRs: `0100_superseded_card_printing_tag_archive` (PR #604) and
`0101_delete_printingtagvote` (PR #615). NEITHER OF THOSE EXISTS ON `master`. The number is
reserved to avoid a filename-prefix collision; the dependency edge is deliberately NOT pointed at
them, because a dependency on a node that does not exist is not a "temporary" cost - it is a hard
`NodeNotFoundError` at `migrate` time, which means `pytest-django` cannot build a test database
and EVERY test on this branch fails at setup. It is also an explicit finding in
`.github/scripts/check_migration_leaves.py` ("depends on cardpicker.X, which does not exist"), so
PR #611's merge-result leaf guard would fail as well. Forward-declaring here would trade a
certain, total CI outage for the avoidance of a merge-order collision that is loud, cheap, and
caught automatically.

This follows PR #615's convention (file numbered at its allocated slot, `dependencies` pointed at
the real leaf on `master`) rather than PR #604's forward declaration. The two authors reached
opposite conclusions and both gave reasons; the difference now is that #611's guard exists and
turns the collision #604 was insuring against into an automatic, blocking signal, which removes
the only argument for paying for it up front.

    => WHICHEVER OF #604 / #615 MERGES BEFORE THIS ONE, THIS MIGRATION'S `dependencies` MUST BE
       REPOINTED AT THE NEW LEAF ON REBASE. Leaving it on `0099` after `0100`/`0101` land gives
       `cardpicker` two leaf nodes, which takes test-database setup down on EVERY branch in the
       repo, not just this one. PR #611's `migration-graph` job evaluates the graph AS MERGED with
       the base at run time, so it catches this the moment it becomes true - that is what it is
       for. Repointing costs one dependency tuple and this paragraph; this is a pure additive
       column with no ordering constraint in substance against either of those migrations.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0099_rename_printings_count_catalogued"),
    ]

    operations = [
        migrations.AddField(
            model_name="canonicalprintingmetadata",
            name="scryfall_default_cards_printings_count",
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
    ]
