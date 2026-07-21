import datetime as dt
import json
import time
from math import floor
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, cast

import ratelimit
import requests

from django.conf import settings

TEXT_BOLD = "\033[1m"
TEXT_END = "\033[0m"


def time_to_hours_minutes_seconds(t: float) -> tuple[int, int, int]:
    hours = int(floor(t / 3600))
    mins = int(floor(t / 60) - hours * 60)
    secs = int(t - (mins * 60) - (hours * 3600))
    return hours, mins, secs


def log_hours_minutes_seconds_elapsed(t0: float) -> None:
    hours, mins, secs = time_to_hours_minutes_seconds(time.time() - t0)
    print("Elapsed time: ", end="")
    if hours > 0:
        print(f"{hours} hour{'s' if hours != 1 else ''}, ", end="")
    print(f"{mins} minute{'s' if mins != 1 else ''} and {secs} second{'s' if secs != 1 else ''}.")


@ratelimit.sleep_and_retry  # type: ignore  # `ratelimit` does not implement decorator typing correctly
@ratelimit.limits(calls=1, period=0.1)  # type: ignore  # `ratelimit` does not implement decorator typing correctly
def get_json_endpoint_rate_limited(url: str, headers: dict[str, Any] | None = None) -> dict[str, Any]:
    return json.loads(requests.get(url, headers=headers).content)


# https://mypy.readthedocs.io/en/stable/generics.html#declaring-decorators
F = TypeVar("F", bound=Callable[..., Any])


def section_timer(name: str) -> Callable[[F], F]:
    def section_timer_decorator(func: F) -> F:
        def wrapper(*args: Any, **kwargs: dict[str, Any]) -> F:
            t0 = time.time()
            print(f"[{name}]: start {dt.datetime.fromtimestamp(t0).isoformat()}")
            ret = func(*args, **kwargs)
            t1 = time.time()
            print(f"[{name}]: end {dt.datetime.fromtimestamp(t1).isoformat()}, elapsed {round(t1 - t0, 2)} seconds.")
            return ret

        return cast(F, wrapper)

    return section_timer_decorator


def twos_complement(hexstr: str, bits: int) -> int:
    """
    retrieved from https://github.com/KDJDEV/imagehash-reverse-image-search-tutorial
    """

    value = int(hexstr, 16)  # convert hexadecimal to integer

    # convert from unsigned number to signed number with "bits" bits
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def get_baked_git_sha() -> Optional[str]:
    """
    Iteration safety (docs/features/catalog-completion-plan.md's Part 1): the git SHA baked
    into this image at build time (docker/django/Dockerfile's GIT_SHA build ARG), if the build
    was invoked with one - `None` for a local non-Docker dev run, or a build that skipped the
    now-required `GIT_SHA=$(git rev-parse --short HEAD)` prefix on the build command.

    Best-effort VISIBILITY only - logged prominently at each pilot command's startup and stored
    on the PilotRunLedger row, but never the thing that blocks a start. Capturing it correctly
    depends on a host-side step that could be forgotten; find_stale_applied_migrations below is
    the actual hard gate, and is deliberately independent of whether this file exists.
    """
    path = Path(settings.BASE_DIR) / "GIT_SHA"
    try:
        sha = path.read_text().strip()
    except OSError:
        return None
    return sha or None


def find_stale_applied_migrations() -> list[tuple[str, str]]:
    """
    (app, migration_name) pairs recorded as applied in the DB that THIS image's own migrations
    directory doesn't know about - the signature of a stale image (docs/features/
    catalog-completion-plan.md's Part 1): a NEWER image applied these migrations before being
    replaced by an older/stale rebuild (the known BuildKit layer-caching bug where "Successfully
    built" can still ship old code underneath - the PR #24/#26 lesson this assertion automates).
    Empty is the only healthy result.

    Deliberately DB+code introspection only, independent of get_baked_git_sha above - that file
    is best-effort visibility and could itself be skipped by a forgotten build-arg; this check
    can't be silently bypassed the same way, since it only depends on what's actually in this
    image's own migrations/ directory and what the DB itself reports as applied.
    """
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.recorder import MigrationRecorder

    disk = set(MigrationLoader(connection, ignore_no_migrations=True).disk_migrations.keys())
    applied = set(MigrationRecorder(connection).applied_migrations().keys())
    return sorted(applied - disk)


def read_card_ids_file(path: str) -> list[int]:
    """
    Shared `--card-ids-file` parsing (issue #259's reparse_collector_evidence +
    run_image_evidence_cohort's own targeted-cohort flag) - one card pk per line, blank lines
    and `#`-prefixed comment lines ignored, order preserved (not deduplicated or sorted - a
    caller that cares about either does so itself; this is a plain, honest file read). Raises
    `ValueError` (via `int()`) on a genuinely malformed line rather than silently skipping it -
    a typo'd card id in an owner-authored targeting file should fail loudly, not vanish.
    """
    ids: list[int] = []
    for line in Path(path).read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ids.append(int(stripped))
    return ids
