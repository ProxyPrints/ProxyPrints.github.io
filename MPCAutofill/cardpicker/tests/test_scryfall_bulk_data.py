"""
The regression suite for `cardpicker.integrations.game.scryfall_bulk_data` - the one module that
knows what Scryfall's `/bulk-data` index looks like and how to turn an entry into bytes on disk.

WHAT THIS SUITE EXISTS TO CATCH. On 2026-07-20 Scryfall retired `download_uri`/`size` in favour
of `jsonl_download_uri`/`compressed_size`, switched the payload from a pretty-printed JSON array
to JSONL, and switched from `Content-Encoding: gzip` transfer compression to serving a `.gz`
file that the client must inflate itself. Two of three importers hard-failed in production (a
`stream_full_catalog` stage-0 abort on pydantic `data.N.download_uri` errors); the third had been
hardened by hand. The three checks below are what would have turned that into a red CI run:

  * `TestCapturedRealResponse` parses a CAPTURED COPY OF THE REAL API RESPONSE
    (`fixtures/scryfall_bulk_data_index.json`, fetched 2026-07-29) so the next upstream field
    change surfaces here rather than in a production abort;
  * `TestSchemaFailsLoudly` asserts that removing any required field raises rather than
    degrading, INCLUDING that the retired pre-cutover shape is now rejected outright;
  * `TestDownloadAndDecompress` drives the whole download path against a REAL gzipped-JSONL
    sample of Scryfall card objects (`fixtures/scryfall_default_cards_sample.jsonl.gz`), and
    pins that a truncated or non-gzip body fails LOUDLY rather than silently landing a short
    file that would "successfully import" a fraction of the catalog.

NO TEST HERE TOUCHES THE NETWORK by default. `TestLiveApiContract` is the single exception and
is skipped unless `SCRYFALL_LIVE_CONTRACT=1` is set - it makes one small `/bulk-data` index
request (a few KB, no bulk download) and is intended to be run by hand when verifying against
today's live API. It is opt-in rather than marker-gated because `pytest.ini`'s marker list is
not ours to extend here.
"""

import gzip
import json
import os
import uuid
import zlib
from pathlib import Path
from typing import Any

import pytest
import requests
from pydantic import ValidationError

from cardpicker.integrations.game import scryfall_bulk_data
from cardpicker.integrations.game.scryfall_bulk_data import (
    BulkDataDownloadError,
    BulkDataEntry,
    BulkDataIndex,
    download_and_decompress,
    iter_json_lines,
)

_FIXTURES = Path(__file__).parent / "fixtures"

# A verbatim capture of https://api.scryfall.com/bulk-data taken 2026-07-29, i.e. after the
# 2026-07-20 retirement. Refresh it deliberately (and read the diff) when upstream changes -
# never edit it to make a test pass.
_CAPTURED_INDEX = _FIXTURES / "scryfall_bulk_data_index.json"

# Six real, unmodified Scryfall card objects taken from the head of the live
# default-cards .jsonl.gz on 2026-07-29, re-gzipped. Covers one plain single-faced card and one
# each of transform / modal_dfc (genuine double-faced), adventure / split (two modes on ONE
# physical face), and art_series - the exact distinctions the back-face lookup turns on.
_SAMPLE_GZ = _FIXTURES / "scryfall_default_cards_sample.jsonl.gz"

# Exactly the entry shape the /bulk-data index carried BEFORE 2026-07-20. Kept as a literal so a
# future reader can see what broke; every test that uses it asserts it is now REJECTED.
_RETIRED_ENTRY_SHAPE = {
    "object": "bulk_data",
    "id": "27bf3214-1271-490b-bdfe-c0be6c23d02e",
    "type": "default_cards",
    "updated_at": "2026-07-19T23:50:06.858+00:00",
    "uri": "https://api.scryfall.com/bulk-data/27bf3214-1271-490b-bdfe-c0be6c23d02e",
    "name": "Default Cards",
    "description": "A JSON file containing every card object on Scryfall in English.",
    "size": 620000000,
    "download_uri": "https://data.scryfall.io/default-cards/default-cards-20260719235006.json",
    "content_type": "application/json",
    "content_encoding": "gzip",
}


def _captured_payload() -> dict[str, Any]:
    return json.loads(_CAPTURED_INDEX.read_text())


class _FakeStreamResponse:
    """
    Stand-in for a streamed download response: context manager + status_code + iter_content.
    `error`, when given, is raised AFTER every chunk has been yielded (a mid-stream transport
    failure).
    """

    def __init__(self, chunks: list[bytes], status_code: int = 200, error: Exception | None = None):
        self.status_code = status_code
        self._chunks = chunks
        self._error = error

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192) -> Any:
        yield from self._chunks
        if self._error is not None:
            raise self._error


def _serve(monkeypatch: pytest.MonkeyPatch, chunks: list[bytes], **kwargs: Any) -> list[str]:
    """Routes every `requests.get` to a fake streamed response. Returns the requested URLs."""
    requested: list[str] = []

    def fake_get(url: str, **_: Any) -> Any:
        requested.append(url)
        return _FakeStreamResponse(chunks=chunks, **kwargs)

    monkeypatch.setattr(requests, "get", fake_get)
    return requested


def _chunked(raw: bytes, size: int = 64) -> list[bytes]:
    """Splits `raw` into small network-sized chunks so streaming decompression is exercised
    across chunk boundaries rather than receiving a whole gzip member in one call."""
    return [raw[i : i + size] for i in range(0, len(raw), size)] or [b""]


class TestCapturedRealResponse:
    """
    THE REGRESSION TEST THE INCIDENT ASKED FOR: the model is validated against a captured copy of
    the CURRENT real `/bulk-data` response, so an upstream field change fails in CI instead of in
    a production stage-0 abort.
    """

    def test_captured_response_parses(self):
        index = BulkDataIndex.model_validate(_captured_payload())
        assert len(index.data) == 7

    def test_every_entry_type_this_codebase_consumes_is_present_and_resolvable(self):
        index = BulkDataIndex.model_validate(_captured_payload())
        for entry_type in (
            scryfall_bulk_data.DEFAULT_CARDS,
            scryfall_bulk_data.ORACLE_CARDS,
            scryfall_bulk_data.ART_TAGS,
        ):
            entry = index.entry_for(entry_type)
            assert entry.type == entry_type
            # Every download URL is a gzipped JSONL file: gzip ON DISK, not transfer encoding.
            assert entry.jsonl_download_uri.endswith(".jsonl.gz")
            assert entry.compressed_size > 0
            assert entry.updated_at

    def test_captured_response_no_longer_carries_the_retired_fields(self):
        """
        Pins the FACT this whole change is about, straight off the captured response: the fields
        two importers required are gone. If a future capture reintroduces them, this fails and
        forces a deliberate decision rather than a silent divergence.
        """
        for entry in _captured_payload()["data"]:
            assert "download_uri" not in entry
            assert "size" not in entry
            assert "content_type" not in entry
            assert "content_encoding" not in entry
            assert "jsonl_download_uri" in entry
            assert "compressed_size" in entry

    def test_unknown_entry_type_raises_with_the_available_types_named(self):
        index = BulkDataIndex.model_validate(_captured_payload())
        with pytest.raises(RuntimeError) as excinfo:
            index.entry_for("cards_that_do_not_exist")
        message = str(excinfo.value)
        assert "cards_that_do_not_exist" in message
        # The error must name what IS available - that is what turns "index changed shape" into
        # a diagnosable failure instead of a bare IndexError from a `.pop()`.
        assert "default_cards" in message


class TestSchemaFailsLoudly:
    """
    Every declared field is REQUIRED, deliberately. A disappearing upstream field must raise, not
    default to None and let the importer download from nothing or write a null sidecar.
    """

    @pytest.mark.parametrize("field", ["type", "jsonl_download_uri", "updated_at", "compressed_size"])
    def test_missing_required_field_raises(self, field):
        payload = _captured_payload()
        for entry in payload["data"]:
            entry.pop(field)
        with pytest.raises(ValidationError) as excinfo:
            BulkDataIndex.model_validate(payload)
        assert field in str(excinfo.value)

    def test_retired_pre_cutover_entry_shape_is_rejected(self):
        """
        The exact response shape that existed before 2026-07-20 must NOT validate. Had this
        assertion existed, the cutover would have gone red in CI on the day the blog post landed
        rather than aborting a production stage-0 run nine days later.
        """
        with pytest.raises(ValidationError) as excinfo:
            BulkDataIndex.model_validate({"data": [_RETIRED_ENTRY_SHAPE]})
        message = str(excinfo.value)
        assert "jsonl_download_uri" in message
        assert "compressed_size" in message

    def test_extra_unknown_fields_are_tolerated(self):
        """Additive upstream changes are not breakage - only removals are."""
        payload = _captured_payload()
        for entry in payload["data"]:
            entry["some_brand_new_field"] = {"nested": True}
        assert len(BulkDataIndex.model_validate(payload).data) == 7

    def test_compressed_size_is_typed_as_an_integer_not_a_string(self):
        entry = BulkDataEntry.model_validate(
            {
                "type": "default_cards",
                "jsonl_download_uri": "https://data.scryfall.io/default-cards/x.jsonl.gz",
                "updated_at": "2026-07-28T23:57:10.831+00:00",
                "compressed_size": 77013126,
            }
        )
        assert entry.compressed_size == 77013126


class TestFetchBulkDataIndex:
    def test_non_200_is_loud(self, monkeypatch):
        """
        Issue #513's rule: a failed bulk-data lookup must never silently fall back to reusing a
        cache of unknown age.
        """

        class _Resp:
            status_code = 503
            text = "{}"

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        with pytest.raises(AssertionError):
            scryfall_bulk_data.fetch_bulk_data_index()

    def test_get_bulk_data_entry_resolves_by_type(self, monkeypatch):
        class _Resp:
            status_code = 200
            text = _CAPTURED_INDEX.read_text()

        requested: list[str] = []

        def fake_get(url: str, **kwargs: Any) -> Any:
            requested.append(url)
            return _Resp()

        monkeypatch.setattr(requests, "get", fake_get)
        entry = scryfall_bulk_data.get_bulk_data_entry(scryfall_bulk_data.DEFAULT_CARDS)

        assert requested == ["https://api.scryfall.com/bulk-data"]
        assert entry.type == "default_cards"
        assert entry.jsonl_download_uri.endswith(".jsonl.gz")


class TestDownloadAndDecompress:
    """
    THE GZIP-ON-DISK PATH, end to end, against a real gzipped-JSONL sample. Scryfall serves
    `.jsonl.gz` with `Content-Type: application/gzip` and NO `Content-Encoding: gzip`, so
    `requests` does not inflate it and this code must.
    """

    def test_real_gzipped_jsonl_sample_lands_decompressed_and_parses(self, tmp_path, monkeypatch):
        raw = _SAMPLE_GZ.read_bytes()
        expected = gzip.decompress(raw)
        _serve(monkeypatch, _chunked(raw))
        path = tmp_path / "default_cards.json"

        download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert path.read_bytes() == expected
        # JSONL: no wrapping array, no commas, one whole card object per line.
        lines = path.read_text().splitlines()
        assert len(lines) == 6
        assert not any(line.strip() in ("[", "]") or line.rstrip().endswith(",") for line in lines)
        for line in lines:
            card = json.loads(line)
            assert card["object"] == "card"
            uuid.UUID(card["id"])

    def test_landed_file_is_readable_by_the_shared_line_reader(self, tmp_path, monkeypatch):
        _serve(monkeypatch, _chunked(_SAMPLE_GZ.read_bytes()))
        path = tmp_path / "default_cards.json"
        download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        names = [json.loads(line)["name"] for line in iter_json_lines(path)]
        assert len(names) == 6
        assert "Forest" in names

    def test_atomic_swap_is_preserved(self, tmp_path, monkeypatch):
        """PR #515's behaviour, unchanged: temp file BESIDE the target, landed by `os.replace`."""
        _serve(monkeypatch, _chunked(_SAMPLE_GZ.read_bytes()))
        path = tmp_path / "default_cards.json"
        replaced: list[tuple[Path, Path]] = []
        real_replace = os.replace

        def spy_replace(src: Any, dst: Any) -> None:
            replaced.append((Path(src), Path(dst)))
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy_replace)
        download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert replaced == [(Path(str(path) + ".tmp"), path)]
        assert Path(replaced[0][0]).parent == path.parent  # same filesystem, so replace is atomic
        assert not Path(str(path) + ".tmp").exists()

    def test_truncated_gzip_fails_loudly_and_leaves_the_cache_untouched(self, tmp_path, monkeypatch):
        """
        The catastrophic case: a stream that stops early would otherwise land a valid-looking
        short file and "successfully import" a fraction of the catalog. No gzip trailer is ever
        seen, so this must raise and never reach `os.replace`.
        """
        raw = _SAMPLE_GZ.read_bytes()
        _serve(monkeypatch, _chunked(raw[: len(raw) // 2]))
        path = tmp_path / "default_cards.json"
        original = b"the previous, complete cache\n"
        path.write_bytes(original)

        with pytest.raises(BulkDataDownloadError) as excinfo:
            download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert "truncated" in str(excinfo.value)
        assert path.read_bytes() == original
        assert not Path(str(path) + ".tmp").exists()

    def test_non_gzip_payload_fails_loudly(self, tmp_path, monkeypatch):
        """A 200 carrying an HTML error page / plain JSON is not silently written over the cache."""
        _serve(monkeypatch, _chunked(b"<!doctype html><html><body>503 from the CDN</body></html>"))
        path = tmp_path / "default_cards.json"
        original = b"the previous, complete cache\n"
        path.write_bytes(original)

        with pytest.raises(BulkDataDownloadError) as excinfo:
            download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert "not a valid gzip stream" in str(excinfo.value)
        assert path.read_bytes() == original
        assert not Path(str(path) + ".tmp").exists()

    def test_plain_uncompressed_jsonl_body_fails_loudly(self, tmp_path, monkeypatch):
        """
        The specific near-miss this cutover invites: pointing the downloader at a body that is
        already plain JSONL (e.g. a stale `download_uri`-era URL, or a proxy that inflated it).
        It must NOT be accepted just because the bytes happen to be parseable text.
        """
        _serve(monkeypatch, _chunked(gzip.decompress(_SAMPLE_GZ.read_bytes())))
        path = tmp_path / "default_cards.json"

        with pytest.raises(BulkDataDownloadError):
            download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert not path.exists()

    def test_empty_body_fails_loudly_rather_than_importing_nothing(self, tmp_path, monkeypatch):
        _serve(monkeypatch, [b""])
        path = tmp_path / "default_cards.json"

        with pytest.raises(BulkDataDownloadError):
            download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert not path.exists()

    def test_non_200_is_loud(self, tmp_path, monkeypatch):
        _serve(monkeypatch, _chunked(_SAMPLE_GZ.read_bytes()), status_code=404)
        path = tmp_path / "default_cards.json"

        with pytest.raises(AssertionError):
            download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert not path.exists()

    def test_mid_stream_transport_failure_leaves_no_temp_file(self, tmp_path, monkeypatch):
        raw = _SAMPLE_GZ.read_bytes()
        _serve(
            monkeypatch,
            _chunked(raw[:512]),
            error=requests.exceptions.ConnectionError("connection dropped mid-stream"),
        )
        path = tmp_path / "default_cards.json"

        with pytest.raises(requests.exceptions.ConnectionError):
            download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert not path.exists()
        assert not Path(str(path) + ".tmp").exists()

    def test_multi_member_gzip_stream_is_fully_inflated(self, tmp_path, monkeypatch):
        """
        `gzip` permits concatenated members and `zlib.decompressobj` stops at the FIRST trailer,
        which would silently drop everything after it. Assert the whole payload lands - this is
        the one shape where "decompressed successfully" and "decompressed completely" differ.
        """
        first, second = b'{"n": 1}\n', b'{"n": 2}\n'
        raw = gzip.compress(first) + gzip.compress(second)
        _serve(monkeypatch, _chunked(raw))
        path = tmp_path / "default_cards.json"

        download_and_decompress("https://data.scryfall.io/default-cards/x.jsonl.gz", path)

        assert path.read_bytes() == first + second


class TestIterJsonLines:
    """
    The shared reader all three importers now use. It must handle today's JSONL, a `.gz`
    pointed at directly, AND the retired pretty-array shape still sitting on the deployed
    persistent volume.
    """

    def test_reads_plain_jsonl(self, tmp_path):
        path = tmp_path / "cards.jsonl"
        path.write_text('{"a": 1}\n{"a": 2}\n')
        assert [json.loads(line)["a"] for line in iter_json_lines(path)] == [1, 2]

    def test_reads_gzipped_jsonl_by_extension(self, tmp_path):
        path = tmp_path / "cards.jsonl.gz"
        path.write_bytes(gzip.compress(b'{"a": 1}\n{"a": 2}\n'))
        assert [json.loads(line)["a"] for line in iter_json_lines(path)] == [1, 2]

    def test_reads_the_retired_pretty_printed_array_still_on_the_deployed_volume(self, tmp_path):
        """
        Prod's `scryfall_cache/default_cards.json` was written before the cutover and is a
        620MB pretty-printed array. Dropping this tolerance would turn a format migration into
        an outage between deploy and the next refresh.
        """
        path = tmp_path / "default_cards.json"
        path.write_text('[\n{"a": 1},\n{"a": 2}\n]\n')
        assert [json.loads(line)["a"] for line in iter_json_lines(path)] == [1, 2]

    def test_blank_lines_are_skipped(self, tmp_path):
        path = tmp_path / "cards.jsonl"
        path.write_text('{"a": 1}\n\n   \n{"a": 2}\n')
        assert len(list(iter_json_lines(path))) == 2

    def test_real_sample_round_trips(self, tmp_path):
        path = tmp_path / "sample.jsonl.gz"
        path.write_bytes(_SAMPLE_GZ.read_bytes())
        layouts = [json.loads(line)["layout"] for line in iter_json_lines(path)]
        # Genuine double-faced layouts and same-face multi-mode layouts both present - the
        # distinction `printing_metadata_import.DOUBLE_FACED_LAYOUTS` turns on.
        assert {"transform", "modal_dfc"} <= set(layouts)
        assert {"adventure", "split", "art_series"} <= set(layouts)


class TestHeadersAreSharedWithTheMtgIntegration:
    def test_scryfall_import_site_delegates_to_the_shared_definition(self):
        from cardpicker.integrations.game.mtg import Scryfall

        assert Scryfall.get_headers() == scryfall_bulk_data.get_headers()
        assert Scryfall.get_headers()["User-Agent"] == "mpc-autofill/1.0"


@pytest.mark.skipif(
    os.environ.get("SCRYFALL_LIVE_CONTRACT") != "1",
    reason="opt-in live contract check - set SCRYFALL_LIVE_CONTRACT=1 to make one small "
    "/bulk-data index request (no bulk download). The default suite never touches the network.",
)
class TestLiveApiContract:
    """
    Verifies the model against the ACTUAL live `/bulk-data` response rather than the capture.
    Run this by hand when the captured fixture is refreshed; a divergence between this and
    `TestCapturedRealResponse` means the capture is stale and should be re-taken deliberately.
    """

    def test_live_index_parses_and_resolves_every_consumed_type(self):
        index = scryfall_bulk_data.fetch_bulk_data_index()
        for entry_type in (
            scryfall_bulk_data.DEFAULT_CARDS,
            scryfall_bulk_data.ORACLE_CARDS,
            scryfall_bulk_data.ART_TAGS,
        ):
            entry = index.entry_for(entry_type)
            assert entry.jsonl_download_uri.endswith(".jsonl.gz")
            assert entry.compressed_size > 0

    def test_live_download_is_gzip_on_disk_not_transfer_encoding(self):
        """
        The distinction the blog drew, checked against the CDN: the body arrives as raw gzip
        bytes with no `Content-Encoding: gzip`, so `requests` does not inflate it for us. A
        64KB ranged request is enough to prove the magic number and inflate the first whole
        JSONL record without pulling 77MB.
        """
        entry = scryfall_bulk_data.get_bulk_data_entry(scryfall_bulk_data.DEFAULT_CARDS)
        response = requests.get(
            entry.jsonl_download_uri,
            headers={**scryfall_bulk_data.get_headers(), "Range": "bytes=0-65535"},
            timeout=30,
        )
        assert response.status_code in (200, 206)
        assert response.headers.get("Content-Encoding") is None
        assert response.content[:2] == b"\x1f\x8b"  # gzip magic, i.e. gzip ON DISK
        # ...and it really is a gzip stream carrying JSONL: whole objects, one per line, with no
        # wrapping array and no trailing commas.
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        inflated = decompressor.decompress(response.content).decode("utf-8", "ignore")
        complete_lines = inflated.split("\n")[:-1]
        assert len(complete_lines) >= 2
        for line in complete_lines[:2]:
            assert not line.startswith("[") and not line.endswith(",")
            assert json.loads(line)["object"] == "card"


def test_no_importer_declares_its_own_bulk_data_model_any_more():
    """
    THE UNIFICATION, asserted rather than trusted to review. Three separate pydantic models of
    this one endpoint are why exactly one of three importers had been hardened for the cutover.
    If a fourth copy (or a resurrected third) appears, this fails and points at the shared
    module instead.
    """
    root = Path(__file__).resolve().parents[1]
    offenders = []
    # `management/commands/import_external_ip_tags.py` was the third importer this tether
    # covered; it was retired on 2026-07-29 with `PrintingTagVote` and is dropped from the list
    # rather than left behind to `FileNotFoundError`. The assertion's point is unchanged - it
    # fails if ANY importer re-declares a bulk-data field outside the shared module.
    for relative in (
        "printing_metadata_import.py",
        "integrations/game/mtg.py",
    ):
        source = (root / relative).read_text()
        for line in source.splitlines():
            stripped = line.strip()
            # A field DECLARATION, not a mention in a comment or docstring.
            if stripped.startswith(("download_uri:", "jsonl_download_uri:", "compressed_size:", "size:")):
                offenders.append(f"{relative}: {stripped}")
    assert offenders == [], (
        "A bulk-data field is declared outside integrations/game/scryfall_bulk_data.py again - "
        "that duplication is exactly what let two of three importers miss the 2026-07-20 "
        f"deprecation: {offenders}"
    )


def test_sample_fixture_is_genuinely_gzipped_on_disk():
    """Guards the fixture itself: if it is ever re-committed uncompressed, the download tests
    would be exercising a path that cannot happen against the real API."""
    assert _SAMPLE_GZ.read_bytes()[:2] == b"\x1f\x8b"
    with gzip.open(_SAMPLE_GZ, "rt", encoding="utf-8") as f:
        assert sum(1 for _ in f) == 6
