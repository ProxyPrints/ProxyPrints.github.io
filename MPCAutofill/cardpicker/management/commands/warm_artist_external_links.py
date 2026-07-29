"""
Refreshes the MTGAC artist-external-links cache (see cardpicker.artist_external_links's own
module docstring for the full daily-cached-bulk-consumer architecture this belongs to).

Intended for a daily cron. Idempotent and safe to re-run: it always fetches the FULL bulk export
and overwrites the cache with a freshly-normalised blob keyed by artist name, never merges with
or diffs against the previous run - re-running twice in a row (or ten times) leaves the cache in
exactly the same state a single run would.

**Makes AT MOST ONE bulk request per invocation - no retry, deliberately.** MTGAC's own disclosed
limit on the bulk endpoint this command calls is 12 requests/hour (as of 2026-07-29, from their
reply granting permission for this integration to be open-source - they offered to adjust it if
needed; see `cardpicker.artist_external_links`'s module docstring for the full numbers, including
their separate single-artist-lookup limit this command never touches). One daily/weekly cron run
is negligible against that budget; a RETRY LOOP is not - hammering a partner's infrastructure
immediately after they granted access would be a genuinely bad outcome. `warm_artist_external_
links_cache`/`fetch_bulk_export` contain no retry logic at all, and this command adds none of its
own on top - a failed run is simply not retried until the next scheduled invocation. Do not
"helpfully" add retry/backoff here without re-reading `fetch_bulk_export`'s own docstring first.

**On fetch failure this command changes NOTHING and exits non-zero.** See
`warm_artist_external_links_cache`'s own docstring: a refresh that can't complete cleanly - a
network error, an unexpected response shape, an empty export - must leave whatever cache entry
was already there (yesterday's good data, or nothing at all on a first run) untouched. Never
poison the cache with a partial or empty result; a stale-but-correct cache degrading gracefully
to "no data for this artist" beats a fresh-but-broken one that quietly drops every artist's links.
A cron that fails today and isn't re-run until tomorrow's scheduled invocation is the desired
behaviour, not a bug to paper over.

**Writes a NAMED `"shared"` cache, not Django's `default` (issue #538) - and FAILS LOUDLY if it
isn't configured.** `default` stays `LocMemCache` on purpose (django-ratelimit and
`cardpicker.review_clusters` both depend on that - see `cardpicker.artist_external_links`'s own
module docstring for why moving them would be actively worse, not just unnecessary). This
command instead writes `caches["shared"]`, resolved BEFORE any outbound MTGAC call so a
misconfigured environment never wastes rate-limit budget on a fetch it couldn't have written down
anyway. If `"shared"` isn't configured, this command exits non-zero with a clear, actionable
`CommandError` (unlike the read endpoint, which degrades a missing `"shared"` cache to its
ordinary not-found response, never a 500 - see the module docstring's "Graceful degradation"
section) - a cron run that silently writes nowhere and reports success is exactly the bug this
feature originally shipped with, and this command must not repeat it a second way. Once `"shared"`
is configured (a separate infrastructure PR, issue #538), this command needs no further edit -
merge/deploy order between that PR and this one doesn't matter. Scheduling the actual daily cron
entry is a separate, still-open owner item too.
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
