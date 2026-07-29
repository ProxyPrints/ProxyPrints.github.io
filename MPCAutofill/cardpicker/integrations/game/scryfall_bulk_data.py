"""
ONE place that knows what Scryfall's `/bulk-data` index looks like and how to turn an entry of
a given `type` into bytes on disk.

WHY THIS MODULE EXISTS (2026-07-29). Three importers each carried their own pydantic model of
the same upstream endpoint:

  * `cardpicker/printing_metadata_import.py` (its own `BulkDataEntry`),
  * `cardpicker/integrations/game/mtg.py` (its own `BulkDataRow`/`BulkDataResponse`),
  * `cardpicker/management/commands/import_external_ip_tags.py` (its own `_BulkDataEntry`) -
    RETIRED 2026-07-29 along with `PrintingTagVote`; it is named here because it is half the
    reason this module exists, not because it still calls in. Two importers remain.

When Scryfall retired the old bulk format (blog "Two New Ways to Sync Scryfall Data",
2026-07-01; retirement 2026-07-20), exactly ONE of the three had been hardened for it - the
other two hard-failed pydantic validation, because the knowledge that would have let a single
fix cover all three had nowhere shared to live. This module is that place: importers ask for a
resolved download URL BY ENTRY TYPE and never re-declare the schema.

WHY IT LIVES UNDER `integrations/game/` RATHER THAN AT `cardpicker/` LEVEL. Scryfall is a
Magic-specific vendor, and `integrations/game/` is the pluggable per-game package (`base.py`'s
`GameIntegration`) that exists precisely to keep game-specific vendor knowledge out of
`cardpicker/`. Putting Scryfall's wire format at `cardpicker/` level would make the generic
layer own an MTG vendor's schema. The dependency direction is also already established and is
preserved here: `cardpicker.printing_metadata_import` ALREADY imports from
`cardpicker.integrations.game.mtg` (pulling `Scryfall` for its headers), i.e. cardpicker ->
integrations. Nothing in this module imports back out of the integrations package, so no game
integration is made to depend on a cardpicker-level module.

WHAT CHANGED UPSTREAM, precisely - all three are separate breaks and fixing only the first
leaves a broken importer:

1. FIELDS. `download_uri` -> `jsonl_download_uri`; `size` -> `compressed_size`. Also gone
   entirely: `content_type`, `content_encoding` (mtg.py's model required both). Today's live
   entry has exactly: compressed_size, description, id, jsonl_download_uri, name, object,
   type, updated_at, uri.
2. FORMAT. The payload is JSONL - one JSON object per line, NO wrapping array and NO commas
   between objects. Anything that did `json.load()` over the whole file must read it
   line-by-line. See `iter_json_lines`.
3. COMPRESSION. The file is gzipped ON DISK (`.jsonl.gz`), not gzip transfer-encoding. The old
   files were served with `Content-Encoding: gzip`, which an HTTP client decompressed
   transparently; the new ones are served as `Content-Type: application/gzip` with NO
   `Content-Encoding`, so `requests` hands back raw gzip bytes and WE decompress. This is the
   part the blog calls out explicitly and the part most likely to be missed. See
   `download_and_decompress`.

MANIFEST METHOD (the blog's second announcement) is deliberately NOT adopted here - see
`download_and_decompress`'s own note.
"""

import gzip
import logging
import os
import zlib
from pathlib import Path
from typing import Any, Iterator

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

BULK_DATA_URL = "https://api.scryfall.com/bulk-data"

# Scryfall asks every client to identify itself (https://scryfall.com/docs/api). This is the
# single definition for the whole codebase - `mtg.Scryfall.get_headers` delegates here rather
# than keeping a second copy, for the same "one place" reason this module exists at all.
USER_AGENT = "mpc-autofill/1.0"

# Bulk entry `type` values this codebase consumes, named rather than spelled as bare strings at
# each call site.
DEFAULT_CARDS = "default_cards"
ORACLE_CARDS = "oracle_cards"
# `ART_TAGS` has had NO consumer since `import_external_ip_tags` was retired on 2026-07-29 with
# `PrintingTagVote`. Kept, with its live-endpoint test, because the Scryfall Tagger art-tag feed
# is the named input of the unified-Scryfall-importer work item that inherits that capability
# (docs/features/printing-tags.md's retirement record) - a bare constant plus one test is a
# cheaper thing to carry than a re-derivation of which bulk entry type the feed lives under, and
# the test is what would tell us if the entry type disappeared upstream in the meantime.
ART_TAGS = "art_tags"

# gzip's zlib window-bits selector: 16 + MAX_WBITS means "expect a gzip (RFC 1952) wrapper",
# which is what a `.jsonl.gz` body is.
_GZIP_WBITS = 16 + zlib.MAX_WBITS

_DOWNLOAD_CHUNK_SIZE = 1 << 16


class _GzipStreamInflater:
    """
    Feeds network chunks through zlib and yields inflated bytes, handling the two things a bare
    `zlib.decompressobj` gets wrong for a downloaded `.gz`:

    * CONCATENATED MEMBERS. gzip permits several members back to back, and a single
      `decompressobj` stops at the FIRST trailer and parks the rest in `unused_data` - silently
      dropping everything after it. That is the nastiest possible failure here (a complete-
      looking file holding a fraction of the catalog), so a new decompressor is started per
      member until the stream is exhausted. Scryfall currently serves a single member; this
      costs nothing and removes the failure mode.
    * TRAILER VERIFICATION. `finish()` reports whether a gzip trailer was actually reached, which
      is the only way to tell a complete download from a truncated one - both produce valid
      inflated bytes right up to the cut.
    """

    def __init__(self) -> None:
        self._decompressor = zlib.decompressobj(_GZIP_WBITS)

    def feed(self, chunk: bytes) -> bytes:
        out = bytearray()
        data = chunk
        while data:
            out += self._decompressor.decompress(data)
            if not self._decompressor.eof:
                break
            # End of a member. Anything left over is the start of the next one; when there is
            # nothing left, this decompressor's `eof` stays True and `finish` reads it as a
            # complete stream.
            data = self._decompressor.unused_data
            if not data:
                break
            self._decompressor = zlib.decompressobj(_GZIP_WBITS)
        return bytes(out)

    def finish(self) -> tuple[bytes, bool]:
        """Returns (remaining inflated bytes, whether the stream ended on a gzip trailer)."""
        return self._decompressor.flush(), self._decompressor.eof


def get_headers() -> dict[str, Any]:
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


class BulkDataEntry(BaseModel):
    """
    One `/bulk-data` entry, declaring EXACTLY the fields this codebase reads - and declaring
    every one of them REQUIRED, with no default, on purpose.

    That strictness is the regression guard. The 2026-07-20 retirement surfaced in production as
    a stage-0 abort on `data.N.download_uri`/`data.N.size` validation errors precisely because
    these were required; had they been `Optional[...] = None` "for resilience", the importers
    would have sailed past validation and then downloaded from `None`, or silently written a
    freshness sidecar of `null` that never matches and re-downloads 77MB every run. A required
    field that vanishes upstream MUST fail loudly. `tests/test_scryfall_bulk_data.py` pins this
    against a captured copy of the real response so the NEXT upstream change surfaces in CI
    rather than in a production abort.

    Unknown extra keys (id, name, uri, object, description, ...) are ignored by pydantic as
    usual - additive upstream changes are not breakage.
    """

    type: str
    # Replaces the retired `download_uri`. Points at a `.jsonl.gz` - gzipped ON DISK, see the
    # module docstring's point 3.
    jsonl_download_uri: str
    # `updated_at` rides along on the same entry - issue #513's remote-diff freshness check
    # compares the remote `updated_at` against a sidecar written at download time and skips the
    # re-download when they match. Kept as the raw API string on purpose: the comparison is
    # exact-equality, so no datetime parsing/format drift can produce a spurious "unchanged"
    # verdict (a format change just re-downloads once, the safe direction).
    updated_at: str
    # Replaces the retired `size`. NOTE THE SEMANTICS CHANGED: `size` was the size of the
    # UNCOMPRESSED payload; `compressed_size` is the size of the gzipped artefact actually
    # served (~77MB for default_cards, against ~620MB uncompressed). Nothing in this codebase
    # treats it as a byte budget for anything on disk - it is recorded in the freshness sidecar
    # purely as a secondary change detector alongside `updated_at`, and it still works perfectly
    # for that. Do not read a sidecar's `compressed_size` as "how big the cache file is".
    compressed_size: int


class BulkDataIndex(BaseModel):
    data: list[BulkDataEntry]

    def entry_for(self, entry_type: str) -> BulkDataEntry:
        """
        The single lookup every importer goes through. Raises rather than returning None: a
        missing entry type means the upstream index changed shape, which must never be
        swallowed into "skip the refresh and reuse a cache of unknown age" (issue #513's rule).
        """
        matches = [entry for entry in self.data if entry.type == entry_type]
        if not matches:
            available = sorted({entry.type for entry in self.data})
            raise RuntimeError(
                f"Scryfall /bulk-data response contained no {entry_type!r} entry "
                f"(available types: {available}). The bulk-data index changed shape - check "
                f"https://scryfall.com/docs/api/bulk-data before re-running."
            )
        return matches[-1]


def fetch_bulk_data_index(timeout: int = 30) -> BulkDataIndex:
    """
    Fetches and validates the `/bulk-data` index. Small request (a handful of KB), safe to make
    on every run. Fails LOUD on any API error, per issue #513: a failed bulk-data lookup must
    never silently fall back to reusing a cache of unknown age.
    """
    response = requests.get(BULK_DATA_URL, headers=get_headers(), timeout=timeout)
    assert response.status_code == 200
    return BulkDataIndex.model_validate_json(response.text)


def get_bulk_data_entry(entry_type: str, timeout: int = 30) -> BulkDataEntry:
    """`fetch_bulk_data_index` + `entry_for` - the one-call form importers actually want."""
    return fetch_bulk_data_index(timeout=timeout).entry_for(entry_type)


class BulkDataDownloadError(RuntimeError):
    """
    Raised when a bulk download's body is not intact gzip. Distinct from `requests`' own
    transport exceptions so callers can tell "the network died" from "we got 200 OK and bytes
    that are not a gzip stream" (e.g. a CDN error page served with a 200, or a truncated
    object) - both must abort the download, but only the latter means the remote is lying.
    """


def download_and_decompress(url: str, path: Path, timeout: int = 60) -> None:
    """
    Downloads a `.jsonl.gz` bulk file and lands DECOMPRESSED JSONL at `path`, atomically.

    THREE PROPERTIES, all load-bearing:

    1. ATOMIC SWAP (preserved from PR #515). Streams into a temp file in the SAME directory as
       `path`, then `os.replace`s it over `path` only once the stream has fully completed and
       the gzip trailer has been verified. Previously this streamed directly over `path`, so a
       mid-stream failure left a truncated cache with a fresh mtime that later runs treated as
       valid (silent degradation - the same class as issue #402). The temp file must live beside
       `path` so the replace stays on one filesystem (`os.replace` is not atomic across
       filesystems); the try/finally guarantees no partial temp file is left behind and the
       original cache is untouched on any failure.

    2. DECOMPRESS AS WE STREAM. `requests` will NOT do this for us: Scryfall serves these as
       `Content-Type: application/gzip` with NO `Content-Encoding: gzip` header (verified
       against the live CDN 2026-07-29), which is exactly the distinction the announcement drew
       - "you will be downloading a gzipped file, not transmitting the file via gzip
       compression. You will need to un-gzip the file on disk once you have it." A single
       `zlib.decompressobj` is fed each network chunk and its output written straight through,
       so neither the ~77MB compressed nor the ~620MB decompressed payload is ever held in
       memory.

    3. FAIL LOUDLY, NEVER SILENTLY EMPTY. Two distinct failure modes are both caught:
         * NOT GZIP AT ALL (a 200-with-an-error-page, a plain-JSON body, an HTML redirect
           interstitial) - `zlib.error` on the first chunk.
         * TRUNCATED GZIP (connection dropped after some bytes) - the stream ends with
           `decompressor.eof` still False, i.e. no gzip trailer was ever seen.
       Both raise `BulkDataDownloadError`, so the cache is left untouched and the caller aborts.
       The catastrophic outcome this guards against is landing a valid-looking but short file
       and "successfully importing" a fraction of the catalog.

    ON-DISK FORMAT NOTE: we store the file DECOMPRESSED even though the remote is compressed.
    Keeping it gzipped would save ~596MB of the persistent `scryfall_cache` volume but would
    force every reader (`printing_metadata_import._parse_rows`, the back-face lookup) to
    re-inflate 620MB on every pass, and would
    invalidate the already-deployed on-disk cache and the `ensure_scryfall_cache_present` guard
    that points at it. Disk is already provisioned for the uncompressed size; CPU on every read
    is not worth trading for it.

    MANIFEST METHOD - NOT USED, deliberately. The same announcement added `/cards/manifest`, a
    paginated list of which cards exist and when their images last changed, for deciding whether
    a local system needs to sync an individual card or image. It is an INCREMENTAL-sync
    primitive; every consumer here does a whole-catalog pass over bulk data, and the
    "has anything changed at all" question is already answered for free by the entry's own
    `updated_at` against the freshness sidecar. Adopting it would be a new incremental-import
    design, not a fix for this break - out of scope, and recorded here so the next reader knows
    it was considered rather than missed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading gzipped JSONL bulk data from %s", url)
    tmp_path = Path(str(path) + ".tmp")
    inflater = _GzipStreamInflater()
    try:
        with requests.get(url, stream=True, headers=get_headers(), timeout=timeout) as r:
            assert r.status_code == 200
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                    if not chunk:
                        continue
                    try:
                        f.write(inflater.feed(chunk))
                    except zlib.error as e:
                        raise BulkDataDownloadError(
                            f"Bulk data body from {url} is not a valid gzip stream ({e}). Scryfall "
                            f"serves .jsonl.gz as gzip ON DISK (Content-Type: application/gzip, no "
                            f"Content-Encoding), so a decode failure here means the response was not "
                            f"the file we asked for - refusing to overwrite {path}."
                        ) from e
                tail, complete = inflater.finish()
                f.write(tail)
        if not complete:
            raise BulkDataDownloadError(
                f"Bulk data download from {url} ended without a gzip trailer - the stream was "
                f"truncated or was never gzip at all. Refusing to install a partial catalog at "
                f"{path}; the existing cache (if any) is untouched and the next run will retry."
            )
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def iter_json_lines(path: Path) -> Iterator[str]:
    """
    Yields one decoded JSON-object line at a time from a bulk file, accepting every shape this
    codebase can encounter on disk:

      * JSONL (`.jsonl`) - the only format Scryfall serves as of 2026-07-20;
      * gzipped JSONL (`.jsonl.gz`) - opened through `gzip` when the name ends in `.gz`, so a
        `--file` pointed straight at a downloaded artefact works without a manual gunzip;
      * the retired pretty-printed JSON array - bare `[`/`]` lines skipped and the trailing
        comma stripped. Kept deliberately: the deployed persistent volume still holds a
        620MB `default_cards.json` in the OLD format, written before the cutover, and it must
        stay readable until the next refresh replaces it. Dropping this tolerance would turn a
        format migration into an outage.

    Streams line-by-line - the full file is never held in memory.
    """
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:  # type: ignore[operator]
        for line in f:
            stripped = line.strip()
            if stripped in ("", "[", "]"):
                continue
            yield stripped.rstrip(",")


__all__ = [
    "ART_TAGS",
    "BULK_DATA_URL",
    "DEFAULT_CARDS",
    "ORACLE_CARDS",
    "BulkDataDownloadError",
    "BulkDataEntry",
    "BulkDataIndex",
    "download_and_decompress",
    "fetch_bulk_data_index",
    "get_bulk_data_entry",
    "get_headers",
    "iter_json_lines",
]
