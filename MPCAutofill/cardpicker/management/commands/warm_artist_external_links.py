"""
Refreshes the MTGAC artist-external-links cache (see cardpicker.artist_external_links's own
module docstring for the full daily-cached-bulk-consumer architecture this belongs to).

Intended for a daily cron. Idempotent and safe to re-run: it always fetches the FULL bulk export
and overwrites the cache with a freshly-normalised blob keyed by artist name, never merges with
or diffs against the previous run - re-running twice in a row (or ten times) leaves the cache in
exactly the same state a single run would.

**On fetch failure this command changes NOTHING and exits non-zero.** See
`warm_artist_external_links_cache`'s own docstring: a refresh that can't complete cleanly - a
network error, an unexpected response shape, an empty export - must leave whatever cache entry
was already there (yesterday's good data, or nothing at all on a first run) untouched. Never
poison the cache with a partial or empty result; a stale-but-correct cache degrading gracefully
to "no data for this artist" beats a fresh-but-broken one that quietly drops every artist's links.

**OPEN OPERATIONAL ITEM - read before wiring up the actual cron (not resolved by this command):**
this project's `CACHES` setting has no override (`MPCAutofill/settings.py`), so Django falls back
to its default `LocMemCache` - a cache that lives in ONE PYTHON PROCESS's memory only. That's a
documented, load-bearing assumption for this project's other cache/rate-limit code (see
`cardpicker.review_clusters`'s module docstring and `views.py`'s
`_printing_tag_rate_limit_rate` comment: "the app runs a single gunicorn worker with Django's
default (per-process) LocMemCache backend"). A `python manage.py warm_artist_external_links` run
from a SEPARATE OS process (a system cron entry, a one-off django-q2 task - anything that isn't
literally the running gunicorn worker) writes to ITS OWN process-local cache, then exits; nothing
it wrote is visible to the gunicorn process actually serving `2/artistExternalLinks/` requests.
As specified, this command's cache writes will not reach the read path until the deployment
either (a) gains a shared cache backend (e.g. Redis) that both the cron invocation and the
gunicorn process point at, or (b) this command is triggered to run INSIDE the gunicorn process
itself (e.g. from a scheduled in-process task, not an external `manage.py` invocation). This is
flagged here explicitly rather than silently shipped as a working cron job - resolving it is an
infrastructure decision for the owner, out of scope for this change.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from cardpicker.artist_external_links import warm_artist_external_links_cache


class Command(BaseCommand):
    help = (
        "Fetches MTG Artist Connection's bulk artist export, normalises it, and writes the "
        "artist-external-links cache blob. Intended for a daily cron. On any fetch/shape "
        "failure, leaves the existing cache untouched and exits non-zero."
    )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        try:
            blob = warm_artist_external_links_cache()
        except Exception as e:
            raise CommandError(f"MTGAC artist-external-links warm run failed, cache left untouched: {e}")

        artist_count = len(blob)
        link_count = sum(len(record["links"]) for record in blob.values())
        signature_count = sum(1 for record in blob.values() if record["hasSignatureService"])

        self.stdout.write(
            self.style.SUCCESS(
                f"MTGAC artist-external-links cache warmed: {artist_count} artists, "
                f"{link_count} total links, {signature_count} with a signature service flag."
            )
        )
