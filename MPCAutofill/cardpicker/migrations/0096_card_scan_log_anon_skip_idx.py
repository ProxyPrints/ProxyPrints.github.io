"""
Adds a composite index on `CardScanLog(anonymous_id, skip_reason)` - hand-written (not
`manage.py makemigrations`-generated) to exactly match `cardpicker.models.CardScanLog.Meta`
as of this migration, same convention as `0080_questionfeedservedlog.py`'s own explicitly-named
index.

WHAT QUERY THIS SERVES
------------------------
`cardpicker.catalog_stats.compute_skip_breakdown`'s `byReasonAndEngine` panel (Proposal F chart
4's per-engine view - see that function's own docstring) groups `CardScanLog` by `skip_reason` +
`anonymous_id` with no `card` anywhere in the predicate. The same shape recurs in the
`distinctCardsRoutedToReview` aggregate this catalog-stats pass is building out (filters on
`anonymous_id` + `skip_reason`, again with no `card` in the predicate) - both queries hit
`CardScanLog` on exactly the two columns this index covers.

WHY THE EXISTING `(card, anonymous_id)` INDEX DOESN'T SERVE THIS
--------------------------------------------------------------------
`CardScanLog`'s only declared index before this migration is `(card, anonymous_id)`
(`0063_cardscanlog.py` - see that model's own `Meta`). A composite btree index can only be used
for a query that constrains a LEADING PREFIX of its columns; `card` is that index's leading
column, and neither query above filters or groups on `card` at all. Postgres therefore has no
usable index for either query and falls back to a sequential scan over the full `CardScanLog`
table - roughly 10^5 rows as of 2026-07-29 (see `compute_skip_breakdown`'s own docstring: "~11
distinct skip_reason values exist in production").

THIS RUNS HOURLY, NOT ONCE
----------------------------
A sequential scan is a one-off annoyance for an ad-hoc query, but `compute_skip_breakdown` runs
as part of `warm_catalog_stats`'s hourly django-q2 schedule (migration 0094) - every single hour,
forever, on every instance. A recurring 10^5-row sequential scan is a real, permanent cost this
index removes for the (small, one-time) price of write amplification on `CardScanLog` inserts,
which happen far less often than this hourly read.

COLUMN ORDER: `anonymous_id` LEADS, `skip_reason` TRAILS
------------------------------------------------------------
Chosen for selectivity, not alphabetically or by declaration order in the model. `anonymous_id`
holds this project's calculator/engine identity strings (`local-ocr-v1`/`local-phash-v1`/
`local-fallback-v1`, a handful of distinct values but with a skewed, engine-sized cardinality
spread across runs) - `skip_reason` has only ~11 distinct values total (measured 2026-07-29,
`compute_skip_breakdown`'s own docstring) spread much more evenly across the whole table, since
every engine can hit most reasons. A btree index's leading column is what narrows the scanned
range fastest: leading on the MORE selective column (`anonymous_id`) lets Postgres jump straight
to a small, contiguous slice of the index for `byReasonAndEngine`'s per-engine grouping and for
`distinctCardsRoutedToReview`'s per-engine filter, then scan `skip_reason` only within that
narrowed slice - the reverse order would force a much wider index range scan before the
`skip_reason` predicate/group narrows anything at all. `(anonymous_id, skip_reason)` also still
serves a plain `GROUP BY skip_reason` (no `anonymous_id` involved, `compute_skip_breakdown`'s
`byReason` panel) via a full index scan rather than a table scan, which is smaller either way -
so leading on the more selective column loses nothing for the less-selective-only query while
winning for both of the more targeted ones.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0095_canonicalprintingmetadata_face_illustrations"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="cardscanlog",
            index=models.Index(fields=["anonymous_id", "skip_reason"], name="card_scan_log_anon_skip_idx"),
        ),
    ]
