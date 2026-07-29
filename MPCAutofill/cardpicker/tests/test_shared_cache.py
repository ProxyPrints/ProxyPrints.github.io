"""
Tests for the `"shared"` cache alias added alongside `"default"` in
`MPCAutofill/settings.py`, and for the migration that creates its table.

The point of the shared cache is that a value written by ONE OS process is
readable by ANOTHER - a cron-invoked management command warming a blob that the
gunicorn process later serves (issue #538). A same-process round trip proves
nothing about that: `LocMemCache` passes a same-process round trip perfectly and
is exactly the backend that fails in production. So every persistence assertion
here crosses a real `subprocess` boundary, and `test_default_cache_does_not_...`
runs the identical round trip against `default` and asserts it FAILS - if that
negative control ever passes, this file has stopped testing anything.
"""

import importlib
import json
import os
import subprocess
import sys
import uuid
from types import ModuleType

import pytest

from django.conf import settings
from django.core.cache import caches
from django.db import connection

MIGRATION_NAME = "0092_shared_cache_table"


def migration_module() -> ModuleType:
    """
    The migration that creates the shared cache table, imported as a module.

    `importlib` rather than a plain `import` only because the module name starts
    with a digit and so is not a legal identifier.
    """
    return importlib.import_module(f"cardpicker.migrations.{MIGRATION_NAME}")


# A child process that boots the REAL settings module (not a hand-rolled minimal
# config) and then performs one cache operation. Booting the real settings is the
# load-bearing part: it proves that `MPCAutofill.settings`' own `CACHES` block, as
# production loads it, produces a cache two processes can share.
CHILD_SCRIPT = """
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "MPCAutofill.settings")
django.setup()

from django.core.cache import caches

op, alias, key = sys.argv[1], sys.argv[2], sys.argv[3]
cache = caches[alias]
result = {"pid": os.getpid()}
if op == "set":
    cache.set(key, json.loads(sys.argv[4]), 300)
    result["wrote"] = True
else:
    result["value"] = cache.get(key)
sys.stdout.write("RESULT:" + json.dumps(result))
"""


def run_in_child(op: str, alias: str, key: str, payload=None) -> dict:
    """
    Run one cache operation in a genuinely separate OS process, against the same
    test database this process is connected to.

    The database connection parameters are handed over as the same environment
    variables `settings.py` already reads (`DATABASE_HOST` and friends), taken
    from this process's live connection - so the child talks to pytest-django's
    ephemeral test database, not to any real one.
    """
    db = connection.settings_dict
    child_env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "MPCAutofill.settings",
        "DATABASE_ENGINE": db["ENGINE"],
        "DATABASE_NAME": db["NAME"],
        "DATABASE_USER": db["USER"],
        "DATABASE_PASSWORD": db["PASSWORD"],
        "DATABASE_HOST": db["HOST"],
        "DATABASE_PORT": str(db["PORT"]),
    }
    argv = [sys.executable, "-c", CHILD_SCRIPT, op, alias, key]
    if op == "set":
        argv.append(json.dumps(payload))

    completed = subprocess.run(
        argv,
        cwd=settings.BASE_DIR,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, f"child failed:\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    marker = "RESULT:"
    assert (
        marker in completed.stdout
    ), f"child produced no result:\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    result = json.loads(completed.stdout.split(marker, 1)[1])
    # The whole exercise is meaningless if this is somehow not a separate process.
    assert result["pid"] != os.getpid()
    return result


# region configuration


class TestCacheConfiguration:
    def test_default_is_still_locmem(self):
        """
        `default` must remain a per-process `LocMemCache`. `django_ratelimit` and
        `cardpicker.review_clusters` both sit on it and are correct there; moving
        them onto a database cache would put database traffic on the rate-limit
        path and pickle a ~135k-row-derived object list through Postgres.
        """
        assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.locmem.LocMemCache"
        from django.core.cache.backends.locmem import LocMemCache

        assert isinstance(caches["default"], LocMemCache)

    def test_default_config_is_byte_identical_to_djangos_implicit_fallback(self):
        """
        Writing `default` out explicitly must not change its behaviour. Django's
        implicit fallback is LocMemCache with no LOCATION; `CacheHandler` pops
        LOCATION with a default of `""`, so stating `""` is the same object graph.
        """
        default = settings.CACHES["default"]
        assert set(default) <= {"BACKEND", "LOCATION"}
        assert default.get("LOCATION", "") == ""

    def test_shared_is_a_database_cache_on_the_configured_table(self):
        from django.core.cache.backends.db import DatabaseCache

        assert settings.CACHES["shared"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"
        assert isinstance(caches["shared"], DatabaseCache)
        assert caches["shared"]._table == settings.SHARED_CACHE_TABLE

    def test_cull_policy_is_stated_not_inherited(self):
        """
        Django's default is MAX_ENTRIES=300. A silent cull of a warmed blob looks
        exactly like the bug the shared cache exists to fix, so the number is a
        stated decision with large headroom, and CULL_FREQUENCY is not 0 (which
        would flush the whole table at once).
        """
        options = settings.CACHES["shared"]["OPTIONS"]
        assert options["MAX_ENTRIES"] == 1000
        assert options["CULL_FREQUENCY"] == 3
        assert caches["shared"]._max_entries == 1000
        assert caches["shared"]._cull_frequency == 3

    def test_settings_and_migration_agree_on_the_table_name(self):
        """
        The migration hardcodes the table name (migrations must not read mutable
        settings). This is the pin that stops the two drifting apart.
        """
        assert settings.SHARED_CACHE_TABLE == migration_module().SHARED_CACHE_TABLE

    def test_ratelimit_still_resolves_to_default(self):
        """
        `django_ratelimit` uses `RATELIMIT_USE_CACHE` (default `"default"`). Adding
        a second alias must not have quietly moved it onto the database cache.
        """
        assert getattr(settings, "RATELIMIT_USE_CACHE", "default") == "default"


# endregion

# region cross-process behaviour


@pytest.mark.django_db(transaction=True)
class TestCrossProcessPersistence:
    def test_value_written_in_another_process_is_readable_here(self):
        """
        THE failure mode from issue #538, in its actual direction: a separate
        process (stand-in for a cron-invoked management command) warms the cache
        and exits; this process (stand-in for the gunicorn worker) must see it.
        """
        key = f"cross-process-warm-{uuid.uuid4()}"
        payload = {"zones": {"high_match": 135_000}, "warmed_by": "child"}

        run_in_child("set", "shared", key, payload)

        assert caches["shared"].get(key) == payload

    def test_value_written_here_is_readable_in_another_process(self):
        """The reverse direction - the web tier writing something a worker reads."""
        key = f"cross-process-write-{uuid.uuid4()}"
        payload = {"written_by": "parent", "n": 7}

        caches["shared"].set(key, payload, 300)

        assert run_in_child("get", "shared", key)["value"] == payload

    def test_deletion_crosses_the_process_boundary_too(self):
        key = f"cross-process-delete-{uuid.uuid4()}"
        caches["shared"].set(key, "present", 300)
        assert run_in_child("get", "shared", key)["value"] == "present"

        run_in_child("set", "shared", key, "replaced")
        assert caches["shared"].get(key) == "replaced"

        caches["shared"].delete(key)
        assert run_in_child("get", "shared", key)["value"] is None

    def test_default_cache_does_not_cross_the_process_boundary(self):
        """
        NEGATIVE CONTROL. `default` is LocMem, so the identical round trip must
        come back empty. If this ever passes, the tests above have stopped proving
        anything - either the harness collapsed both aliases onto one backend, or
        someone repointed `default` at a shared backend without updating #538's
        reasoning in `settings.py`.
        """
        key = f"locmem-isolation-{uuid.uuid4()}"

        run_in_child("set", "default", key, {"written_by": "child"})

        assert caches["default"].get(key) is None

    def test_the_two_aliases_are_separate_stores(self):
        key = f"alias-isolation-{uuid.uuid4()}"
        caches["default"].set(key, "locmem", 300)
        caches["shared"].set(key, "database", 300)

        assert caches["default"].get(key) == "locmem"
        assert caches["shared"].get(key) == "database"

        caches["shared"].delete(key)
        assert caches["default"].get(key) == "locmem"


# endregion

# region migration


@pytest.mark.django_db(transaction=True)
class TestSharedCacheTableMigration:
    def test_migration_created_the_table(self):
        """
        No operator step: the table is present in a database built purely by
        `migrate`, which is how both production (`docker/django/entrypoint.sh`)
        and this test database are built.
        """
        assert settings.SHARED_CACHE_TABLE in connection.introspection.table_names()

    def test_table_has_the_schema_the_backend_expects(self):
        columns = {
            column.name: column
            for column in connection.introspection.get_table_description(
                connection.cursor(), settings.SHARED_CACHE_TABLE
            )
        }
        assert set(columns) == {"cache_key", "value", "expires"}

    def test_migration_declares_itself_reversible(self):
        operations = migration_module().Migration.operations
        assert len(operations) == 1
        assert operations[0].reversible is True

    def test_migration_reverses_and_reapplies_cleanly(self):
        """
        Drives the real migration executor backwards past 0092 and forwards again,
        asserting the table disappears and comes back. The `finally` guarantees the
        schema is restored even if an assertion fails, so a failure here cannot
        cascade into unrelated tests later in the session.

        THE `finally` MUST TARGET THE APP'S LEAF MIGRATION, NOT `MIGRATION_NAME`, and this
        class is the one place in the suite where that distinction has teeth: it carries
        `@pytest.mark.django_db(transaction=True)`, so every statement below REALLY COMMITS
        and nothing is rolled back at teardown. `migrate([("cardpicker", "0092")])` restores
        the state as of 0092 - and leaves EVERY LATER MIGRATION UNAPPLIED for the remainder
        of the pytest session, in a database later tests go on using.

        That was latent for a long time and cost nothing only by alphabetical luck: 0093/0094
        are data-only `RunPython` migrations, and the one schema migration between here and the
        leaf (0095's `CanonicalPrintingMetadata.face_illustrations`) happens to be read only by
        test modules that sort BEFORE `test_shared_cache.py`. It stopped being free the moment a
        migration added a column to `Card` (0098): `test_sources.py` and
        `test_stage_e_dispatch.py` sort after this module and use `transactional_db`, so they
        write real `Card` rows through a connection that cannot be saved by a rollback, and
        failed with `column "inferred_illustration_id" ... does not exist` - a failure whose
        message points at the new migration and whose cause is entirely here.

        `graph.leaf_nodes("cardpicker")` is derived, never a hardcoded number, so this stays
        correct for every future migration without anyone having to remember this file exists.
        """
        from django.db.migrations.executor import MigrationExecutor

        table = settings.SHARED_CACHE_TABLE
        forwards = [("cardpicker", MIGRATION_NAME)]
        backwards = [("cardpicker", "0091_cardillustrationvote")]

        assert table in connection.introspection.table_names()
        try:
            MigrationExecutor(connection).migrate(backwards)
            assert table not in connection.introspection.table_names()

            MigrationExecutor(connection).migrate(forwards)
            assert table in connection.introspection.table_names()
        finally:
            executor = MigrationExecutor(connection)
            executor.loader.build_graph()
            executor.migrate(executor.loader.graph.leaf_nodes("cardpicker"))
        assert table in connection.introspection.table_names()

    def test_reverse_is_idempotent_when_the_table_is_absent(self):
        """
        The backwards operation is introspection-guarded, so reversing a database
        that never had the table (or reversing twice) must be a no-op rather than a
        `ProgrammingError` that strands a rollback halfway.
        """
        module = migration_module()

        class _FakeSchemaEditor:
            connection = connection

            def execute(self, sql, params=()):  # pragma: no cover - must not be reached
                raise AssertionError(f"DROP attempted against an absent table: {sql}")

        original = module.SHARED_CACHE_TABLE
        module.SHARED_CACHE_TABLE = "shared_cache_table_that_does_not_exist"
        try:
            module.drop_shared_cache_table(None, _FakeSchemaEditor())
        finally:
            module.SHARED_CACHE_TABLE = original


# endregion
