"""
Creates the table backing the `"shared"` cache alias (see the `CACHES` block in
`MPCAutofill/settings.py` for what that cache is for and when to use it).

WHY A MIGRATION AND NOT `manage.py createcachetable`
----------------------------------------------------
`docker/django/entrypoint.sh` runs `manage.py migrate` on every container boot,
and pytest-django runs the full migration chain when it builds a test database.
Putting the table here therefore makes it appear automatically in production, in
CI, and in every developer's fresh database. A hand-run `createcachetable` would
have to be remembered - and forgetting it fails the same silent way the shared
cache exists to prevent: the writer succeeds, the reader misses forever.

THE IDIOM
---------
Django 4.2 ships no migration *operation* for cache tables; `createcachetable`
is only a management command. Its documented escape hatch is
`createcachetable --dry-run`, which prints the SQL "so you can customize it or
use the migrations framework" - i.e. paste vendor-specific DDL into a `RunSQL`.
We deliberately do not do that: hand-copied DDL is frozen against one database
vendor and drifts silently if Django ever changes the schema.

Instead we invoke the command itself through `RunPython`, which IS
"createcachetable's underlying operation" - `Command.create_table()` cannot be
called directly (it reads `self.verbosity`, which only `handle()` sets), so
`call_command` is the supported entry point. Consequences we want:

  * the table is built by `BaseDatabaseCache.cache_model_class`'s own field
    definitions, rendered through this connection's backend, so it is correct
    for Postgres here and for SQLite in anyone's local sandbox;
  * `createcachetable` no-ops if the table already exists, so this migration is
    safe on a database where an operator once ran the command by hand;
  * passing the table name positionally means the command does NOT iterate
    `settings.CACHES` - renaming or removing the cache alias later cannot change
    what this already-applied migration did.

`schema_editor.connection.alias` is threaded through so the table lands on the
database this migration is actually running against rather than always on
`default`.

REVERSAL
--------
Reversible: the backwards operation drops the table. It is guarded by
introspection so reversing a migration that never created the table (or one
reversed twice) is a no-op rather than a `ProgrammingError`, and the table name
is quoted through the backend's own `quote_name`.
"""

from django.core.management import call_command
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# Hardcoded deliberately: migrations must not read mutable settings, or replaying
# history would depend on today's config. `settings.SHARED_CACHE_TABLE` carries the
# same literal, and `cardpicker/tests/test_shared_cache.py` asserts the two agree.
SHARED_CACHE_TABLE = "shared_cache"


def create_shared_cache_table(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    call_command(
        "createcachetable",
        SHARED_CACHE_TABLE,
        database=schema_editor.connection.alias,
        verbosity=0,
    )


def drop_shared_cache_table(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    connection = schema_editor.connection
    if SHARED_CACHE_TABLE not in connection.introspection.table_names():
        return
    schema_editor.execute("DROP TABLE %s" % connection.ops.quote_name(SHARED_CACHE_TABLE))


class Migration(migrations.Migration):

    dependencies = [
        ("cardpicker", "0091_cardillustrationvote"),
    ]

    operations = [
        migrations.RunPython(create_shared_cache_table, drop_shared_cache_table),
    ]
