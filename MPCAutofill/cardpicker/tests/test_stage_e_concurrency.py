"""
Tests for cardpicker.stage_e_concurrency - the Stage E streaming dispatch concurrency cap
(docs/features/stage-e-operations.md; companion to PR #448's vote-collision fix, Tron gate round 1
"COMPANION" item). Runs against the real testcontainer Postgres (never sqlite/mocked) since the
whole point of this module is genuine Postgres advisory-lock semantics.

A DELIBERATE, LOAD-BEARING TEST-DESIGN CONSTRAINT, discovered while writing these tests (not just a
style choice): Postgres SESSION-level advisory locks are RE-ENTRANT within one session - a session
that already holds `pg_try_advisory_lock(ns, 0)` gets an immediate second success (not a move to
slot 1) if it calls the exact same lock again on the SAME connection, incrementing an internal
reference count that then needs a matching number of unlocks. Calling this module's own
`_try_acquire_slot`/`_release_slot` TWICE on the SAME connection WITHOUT releasing in between
therefore does NOT simulate "two independent dispatches" the way it would for two genuinely
separate sessions - it silently re-acquires the SAME slot instead. Every test below that needs more
than one concurrent "dispatcher" therefore gives each one its OWN genuinely SEPARATE `psycopg2`
connection (`_raw_connection`, `_try_acquire_on_connection`/`_release_on_connection`) - this is also
the production-faithful choice, since two real concurrent dispatches are always on two separate
django-q worker PROCESSES (separate connections), and (2026-07-25 rewrite) the module itself now
opens its OWN dedicated connection per call rather than ever touching Django's shared one - see
`stage_e_concurrency`'s own module docstring, "CONNECTION-LIFECYCLE CONTRACT" section, for the
production incident that made "a dedicated connection, not django.db.connection" the whole point of
this rewrite.
"""

import threading
import time
from typing import Any, Optional

import psycopg2
import pytest

from django.db import close_old_connections, connection
from django.test import override_settings

from cardpicker import stage_e_concurrency
from cardpicker.stage_e_concurrency import (
    _LOCK_NAMESPACE,
    _release_slot,
    _try_acquire_slot,
    try_acquire_dispatch_slot,
)

CAP_2 = override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=2)


def _raw_connection() -> "psycopg2.extensions.connection":
    """A genuinely independent DB session to the SAME database Django's own test connection is
    using - built from `connection.get_connection_params()` (not a guessed host/port/dbname) so
    this always matches whatever pytest-django actually connected to, including its own `test_`
    database-name prefixing. Forces Django's own connection to actually exist first
    (`connection.ensure_connection()`) since `get_connection_params()` alone doesn't establish one.
    `autocommit=True` - advisory locks are independent of transactions, and leaving a raw connection
    in Postgres's default (non-autocommit) mode would hold an idle transaction open for no reason.
    This is also EXACTLY the approach `stage_e_concurrency._open_dedicated_connection` itself now
    uses in production (2026-07-25 rewrite) - this test helper predates that rewrite and is the
    reason the task that produced it pointed the fix here."""
    connection.ensure_connection()
    params = connection.get_connection_params()
    raw = psycopg2.connect(**params)
    raw.autocommit = True
    return raw


def _try_acquire_on_connection(conn: "psycopg2.extensions.connection", cap: int) -> Optional[int]:
    """The exact same acquire loop `_try_acquire_slot` runs internally, against an explicit,
    caller-owned connection - kept as an independent re-implementation (not just a call to
    `stage_e_concurrency._try_acquire_slot`) deliberately, so these tests aren't purely tautological
    against the module's own acquire loop."""
    with conn.cursor() as cursor:
        for slot in range(cap):
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, slot])
            (acquired,) = cursor.fetchone()
            if acquired:
                return slot
    return None


def _release_on_connection(conn: "psycopg2.extensions.connection", slot: int) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_LOCK_NAMESPACE, slot])


def _slot_0_is_held_by_someone_else() -> bool:
    """From a genuinely separate, freshly-opened session: `True` if slot 0 is currently held by
    ANY other session (this function's own connection is closed again immediately either way, so
    it never itself holds the lock afterwards)."""
    raw = _raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, 0])
            (acquired,) = cursor.fetchone()
            if acquired:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_LOCK_NAMESPACE, 0])
        return not acquired
    finally:
        raw.close()


@pytest.fixture(autouse=True)
def _release_any_leaked_locks(db: Any):
    """Postgres advisory locks are SESSION-scoped, not transaction-scoped - pytest-django's own
    per-test transaction ROLLBACK (the `db` fixture) does NOT release them, unlike ordinary row
    writes. Every test below is expected to release everything it acquires (raw connections are
    always `close()`d in a `finally`, which auto-releases anything still held), but this fixture is
    a defensive safety net for Django's OWN long-lived connection specifically - the one thing nnot
    covered by a raw connection's own teardown: it fully DRAINS every plausible slot's lock count on
    Django's own test connection after each test (looping `pg_advisory_unlock` until it reports
    nothing left, not just once - a single call would only undo ONE level of the re-entrant
    reference count the module docstring describes, silently leaving a still-held lock behind for
    the next test in the same pytest session to trip over)."""
    yield
    with connection.cursor() as cursor:
        for slot in range(8):  # generous upper bound - real caps in this file never exceed 5
            while True:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_LOCK_NAMESPACE, slot])
                (released,) = cursor.fetchone()
                if not released:
                    break


class TestTryAcquireSlot:
    @CAP_2
    def test_two_independent_dispatchers_get_distinct_slots(self, db: Any) -> None:
        raw_a = _raw_connection()
        raw_b = _raw_connection()
        try:
            dispatcher_a = _try_acquire_slot(raw_a)
            dispatcher_b = _try_acquire_slot(raw_b)

            assert dispatcher_a == 0
            assert dispatcher_b == 1

            _release_slot(raw_a, dispatcher_a)
            _release_slot(raw_b, dispatcher_b)
        finally:
            raw_a.close()
            raw_b.close()

    @CAP_2
    def test_a_third_independent_dispatcher_is_refused_once_the_cap_is_exhausted(self, db: Any) -> None:
        raw_a = _raw_connection()
        raw_b = _raw_connection()
        raw_c = _raw_connection()
        try:
            dispatcher_a = _try_acquire_slot(raw_a)
            dispatcher_b = _try_acquire_slot(raw_b)
            dispatcher_c = _try_acquire_slot(raw_c)

            assert dispatcher_a is not None and dispatcher_b is not None
            assert dispatcher_c is None

            _release_slot(raw_a, dispatcher_a)
            _release_slot(raw_b, dispatcher_b)
        finally:
            raw_a.close()
            raw_b.close()
            raw_c.close()

    @CAP_2
    def test_releasing_a_slot_makes_it_acquirable_by_a_different_dispatcher(self, db: Any) -> None:
        raw_a = _raw_connection()
        raw_b = _raw_connection()
        raw_c = _raw_connection()
        try:
            dispatcher_a = _try_acquire_slot(raw_a)
            dispatcher_b = _try_acquire_slot(raw_b)
            assert dispatcher_a == 0 and dispatcher_b == 1

            _release_slot(raw_a, dispatcher_a)  # slot 0 freed

            dispatcher_c = _try_acquire_slot(raw_c)
            assert dispatcher_c == 0  # a THIRD, different dispatcher claims the freed slot

            _release_slot(raw_b, dispatcher_b)
            _release_slot(raw_c, dispatcher_c)
        finally:
            raw_a.close()
            raw_b.close()
            raw_c.close()

    def test_default_cap_is_six(self, db: Any) -> None:
        assert stage_e_concurrency._slot_count() == 6

    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=0)
    def test_a_zero_configured_cap_floors_to_one_and_warns(self, db: Any, caplog: Any) -> None:
        """STAGE_E_MAX_CONCURRENT_DISPATCHES=0 (a plausible ops typo) must not silently throttle
        every dispatch forever - `_try_acquire_slot`'s own `range(_slot_count())` would otherwise be
        empty, so no slot could ever be acquired, with no error and no envelope trip to surface it.
        The floor makes at least one slot available; the warning makes the typo itself visible."""
        with caplog.at_level("WARNING", logger="cardpicker.stage_e_concurrency"):
            assert stage_e_concurrency._slot_count() == 1
        assert "STAGE_E_MAX_CONCURRENT_DISPATCHES" in caplog.text
        assert "clamping to 1" in caplog.text

    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=-3)
    def test_a_negative_configured_cap_also_floors_to_one_and_warns(self, db: Any, caplog: Any) -> None:
        with caplog.at_level("WARNING", logger="cardpicker.stage_e_concurrency"):
            assert stage_e_concurrency._slot_count() == 1
        assert "clamping to 1" in caplog.text


class TestTryAcquireDispatchSlot:
    @CAP_2
    def test_context_manager_yields_and_releases_a_slot(self, db: Any) -> None:
        with try_acquire_dispatch_slot() as slot:
            assert slot == 0
            # still held while inside the block - an independent concurrent dispatcher sees
            # exactly the OTHER slot free, and nothing left after that.
            raw_b = _raw_connection()
            raw_c = _raw_connection()
            try:
                other_slot = _try_acquire_on_connection(raw_b, cap=2)
                nothing_left = _try_acquire_on_connection(raw_c, cap=2)
                assert other_slot == 1
                assert nothing_left is None
            finally:
                _release_on_connection(raw_b, other_slot)
                raw_b.close()
                raw_c.close()

        # released on clean exit - a fresh independent dispatcher can now claim slot 0 again.
        raw_d = _raw_connection()
        try:
            reacquired = _try_acquire_on_connection(raw_d, cap=2)
            assert reacquired == 0
            _release_on_connection(raw_d, reacquired)
        finally:
            raw_d.close()

    @CAP_2
    def test_slot_is_released_even_when_the_block_raises(self, db: Any) -> None:
        with pytest.raises(RuntimeError, match="simulated failure inside the dispatch"):
            with try_acquire_dispatch_slot() as slot:
                assert slot == 0
                raise RuntimeError("simulated failure inside the dispatch")

        # not leaked - an independent dispatcher can claim slot 0 despite the exception.
        raw = _raw_connection()
        try:
            reacquired = _try_acquire_on_connection(raw, cap=2)
            assert reacquired == 0
            _release_on_connection(raw, reacquired)
        finally:
            raw.close()

    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_yields_none_once_the_single_slot_is_already_held(self, db: Any) -> None:
        raw = _raw_connection()
        try:
            held = _try_acquire_on_connection(raw, cap=1)
            assert held == 0

            with try_acquire_dispatch_slot() as slot:
                assert slot is None  # PROACTIVE throttle - the only slot is already taken

            _release_on_connection(raw, held)
        finally:
            raw.close()

    @CAP_2
    def test_does_not_use_djangos_shared_connection_at_all(self, db: Any) -> None:
        """Companion assertion to the regression tests below, at the unit level: acquiring and
        releasing a slot must not touch `django.db.connection`'s own cursor - if it did, the
        pre-fix bug (lock held on a connection django-q's broker can close mid-dispatch) would be
        back. Patches `django.db.connection.cursor` to explode if called, for the duration of one
        acquire/release cycle only - restored via an explicit `finally`, NOT `pytest`'s
        `monkeypatch` fixture, because this test's own teardown (the autouse leaked-lock drain
        fixture, and pytest-django's own `_post_teardown` -> `check_constraints`) both call
        `connection.cursor()` themselves AFTER the test body returns but BEFORE a
        function-scoped `monkeypatch` fixture would have restored it, which made the patch leak
        into (and fail) teardown machinery that has nothing to do with this test's own
        assertion."""
        original_cursor = connection.cursor

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "stage_e_concurrency touched django.db.connection.cursor() - it must only ever "
                "use its own dedicated connection (see module docstring)"
            )

        connection.cursor = _boom  # type: ignore[method-assign]
        try:
            with try_acquire_dispatch_slot() as slot:
                assert slot == 0
        finally:
            connection.cursor = original_cursor  # type: ignore[method-assign]


class TestCrossConnectionRace:
    """Proves real cross-SESSION safety with independent raw connections standing in for separate
    django-q worker PROCESSES - the production shape this module exists to coordinate against."""

    @CAP_2
    def test_a_second_independent_session_cannot_exceed_the_cap(self, db: Any) -> None:
        raw_a = _raw_connection()
        raw_b = _raw_connection()
        try:
            dispatcher_a = _try_acquire_slot(raw_a)
            dispatcher_b = _try_acquire_slot(raw_b)
            assert dispatcher_a == 0 and dispatcher_b == 1

            raw_c = _raw_connection()
            try:
                with raw_c.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, 0])
                    (acquired_0,) = cursor.fetchone()
                    cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, 1])
                    (acquired_1,) = cursor.fetchone()
                # a genuinely independent third session sees BOTH slots as already held.
                assert acquired_0 is False
                assert acquired_1 is False
            finally:
                raw_c.close()

            _release_slot(raw_a, dispatcher_a)
            _release_slot(raw_b, dispatcher_b)
        finally:
            raw_a.close()
            raw_b.close()

    @CAP_2
    def test_killing_the_holding_session_auto_releases_its_slot(self, db: Any) -> None:
        """The crash-safety property this module's own docstring cites as the reason advisory
        locks were chosen over a DB-row counter: closing (simulating a killed process) the session
        that held a slot releases it with no explicit unlock call and no reconciliation code."""
        raw = _raw_connection()
        acquired = _try_acquire_on_connection(raw, cap=2)
        assert acquired == 0

        raw.close()  # simulates `kill -9` on the process holding this session - no unlock call

        # A fresh independent session now claims the same slot successfully - auto-released, not
        # leaked (production-faithful: this module never holds a lock on Django's own connection,
        # so a fresh dedicated connection standing in for a fresh worker is the right check here).
        raw2 = _raw_connection()
        try:
            reacquired = _try_acquire_slot(raw2)
            assert reacquired == 0
            _release_slot(raw2, reacquired)
        finally:
            raw2.close()


class TestSimulatedConcurrentDispatchers:
    """Exercises the cap the way the task brief asks for explicitly - 'simulated concurrency' -
    using real OS threads, each opening its OWN independent DB connection (never Django's shared
    per-thread `connection` reused across threads - see module docstring's re-entrancy note), each
    HOLDING its slot for a measurable duration (not releasing instantly) so genuine time-overlap
    between threads actually happens, and a shared counter proving the cap is never exceeded AT ANY
    INSTANT - not just "never exceeded across the whole run's own totals", which a purely
    sequential/non-overlapping execution could satisfy trivially even with a broken cap."""

    @CAP_2
    def test_the_cap_holds_under_genuine_concurrent_contention(self, db: Any) -> None:
        thread_count = 6
        hold_seconds = 0.2
        barrier = threading.Barrier(thread_count)
        lock = threading.Lock()
        state = {"currently_held": 0, "max_observed": 0}
        results: list[Optional[int]] = [None] * thread_count
        backend_pids: list[int] = []

        def _worker(index: int) -> None:
            raw = _raw_connection()
            try:
                with lock:
                    backend_pids.append(raw.get_backend_pid())
                barrier.wait()  # maximise real contention - every thread races to acquire at once
                slot = _try_acquire_on_connection(raw, cap=2)
                results[index] = slot
                if slot is None:
                    return
                with lock:
                    state["currently_held"] += 1
                    state["max_observed"] = max(state["max_observed"], state["currently_held"])
                time.sleep(hold_seconds)  # hold long enough to force real overlap between threads
                with lock:
                    state["currently_held"] -= 1
                _release_on_connection(raw, slot)
            finally:
                raw.close()

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # `raw.close()` above closes each client socket synchronously, but Postgres's own backend
        # process can take a moment longer to finish tearing down after that - poll (not a blind
        # sleep) until every one of this test's own backend pids has actually disappeared from
        # `pg_stat_activity`, so this test session's own final `DROP DATABASE` never races a
        # not-quite-gone-yet backend. A correctness requirement of clean test teardown, not of the
        # cap itself.
        deadline = time.monotonic() + 5.0
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute("SELECT pid FROM pg_stat_activity WHERE pid = ANY(%s)", [backend_pids])
                if not cursor.fetchall():
                    break
                time.sleep(0.05)

        acquired = [r for r in results if r is not None]
        throttled = [r for r in results if r is None]
        assert len(acquired) + len(throttled) == thread_count
        # the cap was genuinely exercised under real overlap (not a trivially-serial run) AND
        # never breached at any instant - both directions matter: `< 2` would mean this test
        # failed to create real contention at all (a false-positive pass), `> 2` would mean the
        # cap itself is broken.
        assert state["max_observed"] == 2
        # with a 0.2s hold and 6 racing threads all starting at once, MORE than 2 of them are
        # expected to eventually succeed (slots free up and get reused within the race), but never
        # simultaneously - that instant-in-time property is what max_observed pins down above.
        assert len(throttled) >= 1  # cap=2 with 6 simultaneous starters must throttle at least one


class TestRegressionDedicatedConnectionSurvivesFollowOnEnqueue:
    """
    Regression tests for the 2026-07-25T00:25Z production incident
    (`envtrip-20260725T002504-73e1eb6d`, `{'ceiling': 7.0, 'load_avg': 11.4013671875}`) - zero
    `throttled-concurrency-cap` outcomes despite 8 concurrent django-q workers, plus 8 occurrences of
    this module's own `pg_advisory_unlock reported slot N was not held by this connection` warning.
    See `stage_e_concurrency`'s own module docstring, "WHAT WENT WRONG IN PRODUCTION" section, for
    the full root-cause writeup this test reproduces: `cardpicker.stage_e_signals`'s `post_save`
    receivers call `django_q.tasks.async_task(...)` from INSIDE `dispatch_micro_batch`'s locked
    region (during Stage C's `persist_evidence`); `async_task` synchronously calls the installed ORM
    broker's `enqueue`, which calls `django.db.close_old_connections()` whenever not inside an atomic
    block - and with `CONN_MAX_AGE` unset (this project's `DATABASES["default"]` has no override,
    Django's own default is `0`), that call closes the connection UNCONDITIONALLY, not just past some
    age. A closed connection auto-releases every Postgres advisory lock its session held.

    PROVEN TO CATCH THE REGRESSION (verified by hand against the pre-fix module, not committed - see
    this change's own PR description): pointing `try_acquire_dispatch_slot` back at
    `django.db.connection` instead of a dedicated connection makes both tests below FAIL - the
    "genuinely separate session" check finds slot 0 free (silently reacquirable), instead of still
    held.

    `transactional_db`, not `db`: the `db` fixture wraps every test in an outer atomic block
    (`get_autocommit()` is `False` throughout the test), which is not the connection state a real
    django-q worker process is in when a signal receiver fires mid-dispatch - `ORM.get_connection`'s
    own `if transaction.get_autocommit(...)` check is exactly why the production trigger only fires
    OUTSIDE an atomic block, and calling `close_old_connections()` directly while genuinely inside
    the `db` fixture's own outer atomic block would corrupt that fixture's own transactional
    isolation for the rest of the test (Django's "didn't restore autocommit, drop the connection"
    rule in `close_if_unusable_or_obsolete` fires regardless of which code calls it).
    `transactional_db` gives this test a real, autocommit=True connection - the production-faithful
    state, and the same fixture this codebase's own `TestConcurrency`-style tests
    (`test_local_identify_printing_tags.py`) already use for the identical reason.
    """

    @CAP_2
    def test_slot_survives_a_follow_on_async_task_enqueue_inside_the_locked_region(self, transactional_db: Any) -> None:
        """The exact production trigger, reproduced end to end: a real `django_q.tasks.async_task`
        call, made from inside the locked region, exactly where `stage_e_signals` makes it."""
        from django_q.tasks import async_task

        with try_acquire_dispatch_slot() as slot:
            assert slot == 0

            async_task("cardpicker.stage_e_dispatch.dispatch_for_card", 1, "evidence-change")

            assert _slot_0_is_held_by_someone_else() is True

        # released cleanly on exit despite the mid-block connection churn.
        assert _slot_0_is_held_by_someone_else() is False

    @CAP_2
    def test_slot_survives_close_old_connections_called_directly_inside_the_locked_region(
        self, transactional_db: Any
    ) -> None:
        """A more minimal, django-q-version-independent reproduction of the identical root cause:
        directly calling `django.db.close_old_connections()` (what the ORM broker calls internally)
        from inside the locked region must not affect this module's own lock, because the lock is
        held on a connection `close_old_connections()` never touches."""
        with try_acquire_dispatch_slot() as slot:
            assert slot == 0

            close_old_connections()

            assert _slot_0_is_held_by_someone_else() is True

        assert _slot_0_is_held_by_someone_else() is False
