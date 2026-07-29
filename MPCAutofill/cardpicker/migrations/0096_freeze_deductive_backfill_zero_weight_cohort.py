"""
Freeze the 2026-07-14 deductive-name-backfill cohort by stamping its `run_id`.

WHY THIS MIGRATION EXISTS
-------------------------
The 2026-07-23 owner ruling zeroed the consensus weight of the 28,112 `CardPrintingTag` votes
that backfill run wrote. The 2026-07-29 owner clarification is that the ruling zeroed THAT COHORT
(so it can serve as a measurement control), and did NOT disqualify name-matching deductive
inference as a method - votes cast by the same calculator in future carry ordinary machine weight.

`cardpicker.vote_consensus.resolve_vote_weight` therefore has to be able to tell a 2026-07-14 row
apart from a row the same calculator writes tomorrow. Those rows carry `run_id = NULL` (the run
predated run_id stamping) and are otherwise identical in every field consensus reads. This
migration gives them the provenance marker they never got, so the override can be scoped to the
run rather than to a `created_at` coincidence. See `DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID`'s own
comment in `vote_consensus.py` for the full trade-off (why a run stamp and not a timestamp cutoff,
and why a one-time metadata write to production vote rows is the price worth paying).

WHAT IT TOUCHES, EXACTLY
------------------------
One column - `run_id` - on rows that currently hold NULL there. No `source`, no `printing`, no
`card`, no `is_no_match`, no `confidence`: nothing any consensus computation reads other than the
zero-weight override this stamp is for. No vote's content or outcome changes. Fully reversible.

THE SELECTION PREDICATE
-----------------------
Three conjuncts, all measured read-only against production on 2026-07-29 before this was written:

  - `anonymous_id = "deductive-backfill-v1"` - 28,112 rows, and the ONLY rows in the whole
    `deductive-backfill` calculator family (no -v2 exists; zero rows whose anonymous_id merely
    contains the string sit outside the family);
  - `run_id IS NULL` - true of all 28,112, and the thing that makes this migration idempotent in
    substance as well as in Django's bookkeeping: a row already stamped is not re-stamped, and a
    row stamped by some future run is not stolen;
  - `created_at < 2026-07-14 18:30 UTC` - the cohort landed in a 16-second window
    (18:21:49.219827 to 18:22:05.243476 UTC). This is the belt-and-braces conjunct: it bounds the
    blast radius to rows that already existed when this was authored, so a deductive-backfill run
    executed between authoring and deployment (whose votes should COUNT under the new ruling)
    cannot be swept into the frozen control by accident.

That timestamp is the ONE place a datetime is allowed to encode this cohort, and the reason is
that a migration is a dated historical artifact by construction: it runs once, against the data as
it stood, and nothing consults it afterwards. `vote_consensus.py` never sees a datetime.

EXPECTED EFFECT IN PRODUCTION: 28,112 rows updated. On any other database (a fresh deploy, CI, a
developer's test DB) the expected effect is 0 rows, which is correct and not an error - there is no
cohort there to freeze. The count is therefore printed, not asserted: a hard assert on 28,112 would
make this migration unrunnable everywhere except one machine.
"""

from datetime import datetime, timezone

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# The frozen cohort's provenance marker. `cardpicker.vote_consensus` carries this same literal as
# DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID and matches the zero-weight override on it; the two are
# pinned equal by `test_vote_consensus.TestZeroWeightCohortScopeIsPinned`, which imports THIS
# module to read it. That test is the anti-drift guard for the scoping: a migration is append-only
# history, so an edit to the constant in `vote_consensus.py` that was not also an edit to the
# database fails loudly there instead of silently restoring weight to a ratified control cohort.
# DO NOT EDIT THIS STRING. It is a record of what was written, not a setting.
ZERO_WEIGHT_RUN_ID = "deductive-backfill-v1/20260714-ratified-zero-weight"

COHORT_ANONYMOUS_ID = "deductive-backfill-v1"
# Upper bound of the measured 16-second write window, rounded up - see the module docstring.
COHORT_CREATED_BEFORE = datetime(2026, 7, 14, 18, 30, 0, tzinfo=timezone.utc)
# Measured read-only against production 2026-07-29; informational, deliberately not asserted.
EXPECTED_PRODUCTION_ROWS = 28112


def stamp_cohort_run_id(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    CardPrintingTag = apps.get_model("cardpicker", "CardPrintingTag")
    updated = CardPrintingTag.objects.filter(
        anonymous_id=COHORT_ANONYMOUS_ID,
        run_id__isnull=True,
        created_at__lt=COHORT_CREATED_BEFORE,
    ).update(run_id=ZERO_WEIGHT_RUN_ID)
    print(
        f"  0096: stamped run_id={ZERO_WEIGHT_RUN_ID!r} on {updated} CardPrintingTag rows "
        f"(production expects {EXPECTED_PRODUCTION_ROWS}; 0 is correct on any other database)"
    )


def unstamp_cohort_run_id(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Reverse: return the marker to NULL, which is exactly the state these rows were in before.

    This un-scopes the zero-weight override (the cohort stops matching and its votes resolve to
    ordinary machine weight), so reversing this migration without also reverting the code change
    that introduced it reverses a ratified owner ruling. The two move together.
    """
    CardPrintingTag = apps.get_model("cardpicker", "CardPrintingTag")
    reverted = CardPrintingTag.objects.filter(run_id=ZERO_WEIGHT_RUN_ID).update(run_id=None)
    print(f"  0096 (reverse): cleared run_id on {reverted} CardPrintingTag rows")


class Migration(migrations.Migration):
    dependencies = [
        ("cardpicker", "0095_canonicalprintingmetadata_face_illustrations"),
    ]

    operations = [
        migrations.RunPython(stamp_cohort_run_id, unstamp_cohort_run_id),
    ]
