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

**Shared cache-backend prerequisite (issue #538, not this command's to fix).** This project's
`CACHES` setting has no override, so Django falls back to its default `LocMemCache` - a cache
that lives in one Python process's memory only. `get_funnel_counts`/`cardpicker.review_clusters`
depend on the same cache framework and work correctly today, because gunicorn runs a single
worker (`docker/django/Dockerfile`'s `CMD` has no `--workers` flag) and the SAME process both
writes and reads its own cache. THIS command is different, independent of worker count: it runs
as a separate `manage.py` invocation (a cron entry) - a different OS process from the running web
server - so its writes never reach whatever cache a gunicorn worker reads from. Until a shared
backend is configured (tracked as issue #538) this command will keep reporting success on every
run while the endpoint keeps returning its not-found fallback - not a bug in this command, a
known cross-process limitation of the standard `django.core.cache` API it already uses correctly
(via `warm_artist_external_links_cache`), fixed by a separate infrastructure PR, not an edit
here. See `cardpicker.artist_external_links`'s own module docstring and
`docs/features/artist-support-links.md`'s "Warming the cache" section for the full writeup.
Scheduling the actual daily cron entry is a separate, still-open owner item too.
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
