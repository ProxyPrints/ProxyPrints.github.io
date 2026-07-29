"""
Add `CanonicalPrintingMetadata.scryfall_default_cards_printings_count`.

WHY THIS MIGRATION EXISTS
-------------------------
`deductive_backfill`'s D1 tier advertised, and cast votes at `confidence=0.95` on, a guarantee it
did not implement: that a name matching exactly one `CanonicalCard` row was "cross-verified
against Scryfall's own printings_count (not just 'our table happens to have one row')". The
column it read is a count of OUR OWN rows (renamed `catalogued_printings_count` in 0098), so the
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

MIGRATION-GRAPH NOTE
--------------------
Depends on `0099_rename_printings_count_catalogued` (PR #601), which renames the column this one
is designed to be compared against. #601 is not merged yet, so this migration is NOT reachable
from master on its own - it is stacked on that branch deliberately, because gating D1 on
`catalogued_printings_count` requires the renamed column to exist.

The numbering has already moved once: #601 originally added the rename as `0098`, was renumbered
to `0099` when PR #573's `0098_card_illustration_consensus_fields` merged to master first, and
this file was renumbered `0099` -> `0100` to follow. If #601 moves again, move this with it. It
is a pure additive column with no other ordering constraint, so renumbering costs nothing beyond
this docstring and the dependency tuple below.
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
