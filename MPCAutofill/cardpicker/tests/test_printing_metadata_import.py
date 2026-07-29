import gzip
import io
import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import requests

from django.db import connection
from django.test.utils import CaptureQueriesContext

from cardpicker import printing_metadata_import
from cardpicker.models import CanonicalPrintingMetadata
from cardpicker.printing_metadata_import import (
    _download_default_cards,
    _load_back_face_names,
    get_back_face_names,
    import_scryfall_printing_metadata,
    is_back_face,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
)


def _write_bulk_data_file(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    path = tmp_path / "default_cards.json"
    path.write_text("[\n" + "\n".join(json.dumps(record) + "," for record in records) + "\n]")
    return path


def _record(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid.uuid4()),
        "lang": "en",
        "released_at": "2015-01-01",
        "full_art": False,
        "border_color": "black",
        "frame": "2015",
        "frame_effects": [],
        "promo_types": [],
        "edhrec_rank": 1234,
    }
    base.update(overrides)
    return base


def _seed_row_matching_record(canonical_card: Any) -> None:
    """
    Seeds a CanonicalPrintingMetadata row field-identical to what `_record()`'s base bulk
    record produces for the same card - the "unchanged" leg of diff-aware sync tests.
    """
    CanonicalPrintingMetadataFactory(canonical_card=canonical_card, edhrec_rank=1234, released_at=date(2015, 1, 1))


class _BulkWriteSpy:
    """Records every bulk_create/bulk_update call (obj pks + kwargs) on the default manager."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.create_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        manager = CanonicalPrintingMetadata.objects
        real_create = manager.bulk_create
        real_update = manager.bulk_update

        def spy_create(objs: Any, **kwargs: Any) -> Any:
            self.create_calls.append({"pks": [obj.pk for obj in objs], "kwargs": kwargs})
            return real_create(objs, **kwargs)

        def spy_update(objs: Any, **kwargs: Any) -> Any:
            self.update_calls.append({"pks": [obj.pk for obj in objs], "kwargs": kwargs})
            return real_update(objs, **kwargs)

        monkeypatch.setattr(manager, "bulk_create", spy_create)
        monkeypatch.setattr(manager, "bulk_update", spy_update)


class TestImportScryfallPrintingMetadata:
    def test_creates_metadata_for_matching_card(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        record = _record(id=str(canonical_card.identifier), full_art=True, border_color="borderless")
        path = _write_bulk_data_file(tmp_path, [record])

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["created"] == 1
        assert stats["skipped"] == 0
        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=canonical_card)
        assert metadata.full_art is True
        assert metadata.border_color == "borderless"
        assert metadata.edhrec_rank == 1234

    def test_art_crop_url_taken_from_top_level_image_uris(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        record = _record(
            id=str(canonical_card.identifier),
            image_uris={"small": "https://example.test/small.jpg", "art_crop": "https://example.test/art.jpg"},
        )
        path = _write_bulk_data_file(tmp_path, [record])

        import_scryfall_printing_metadata(default_cards_path=path)

        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=canonical_card)
        assert metadata.art_crop_url == "https://example.test/art.jpg"

    def test_art_crop_url_falls_back_to_first_card_face(self, db, tmp_path):
        # double-faced cards nest image_uris under card_faces instead of top-level - Scryfall's
        # own documented convention.
        canonical_card = CanonicalCardFactory()
        record = _record(
            id=str(canonical_card.identifier),
            card_faces=[{"image_uris": {"art_crop": "https://example.test/face-a.jpg"}}, {"image_uris": {}}],
        )
        path = _write_bulk_data_file(tmp_path, [record])

        import_scryfall_printing_metadata(default_cards_path=path)

        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=canonical_card)
        assert metadata.art_crop_url == "https://example.test/face-a.jpg"

    def test_art_crop_url_empty_when_neither_present(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        record = _record(id=str(canonical_card.identifier))
        path = _write_bulk_data_file(tmp_path, [record])

        import_scryfall_printing_metadata(default_cards_path=path)

        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=canonical_card)
        assert metadata.art_crop_url == ""

    def test_skips_row_with_no_matching_canonical_card(self, db, tmp_path):
        record = _record(id=str(uuid.uuid4()))
        path = _write_bulk_data_file(tmp_path, [record])

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["created"] == 0
        assert stats["no_matching_card"] == 1
        assert stats["skipped"] == 0  # skipped counts unchanged rows, not unmatched bulk rows
        assert CanonicalPrintingMetadata.objects.count() == 0

    def test_printings_count_denormalised_per_oracle_card(self, db, tmp_path):
        oracle_id = uuid.uuid4()
        card_a = CanonicalCardFactory(canonical_id=oracle_id)
        card_b = CanonicalCardFactory(canonical_id=oracle_id)
        card_c = CanonicalCardFactory()  # different (unrelated) oracle card
        records = [
            _record(id=str(card_a.identifier)),
            _record(id=str(card_b.identifier)),
            _record(id=str(card_c.identifier)),
        ]
        path = _write_bulk_data_file(tmp_path, records)

        import_scryfall_printing_metadata(default_cards_path=path)

        assert CanonicalPrintingMetadata.objects.get(canonical_card=card_a).printings_count == 2
        assert CanonicalPrintingMetadata.objects.get(canonical_card=card_b).printings_count == 2
        assert CanonicalPrintingMetadata.objects.get(canonical_card=card_c).printings_count == 1

    def test_rerun_updates_existing_metadata(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical_card, full_art=False, edhrec_rank=999)
        record = _record(id=str(canonical_card.identifier), full_art=True, edhrec_rank=42)
        path = _write_bulk_data_file(tmp_path, [record])

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["created"] == 0
        assert stats["updated"] == 1
        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=canonical_card)
        assert metadata.full_art is True
        assert metadata.edhrec_rank == 42

    def test_rerun_is_idempotent(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        record = _record(id=str(canonical_card.identifier))
        path = _write_bulk_data_file(tmp_path, [record])

        import_scryfall_printing_metadata(default_cards_path=path)
        with CaptureQueriesContext(connection) as queries:
            stats = import_scryfall_printing_metadata(default_cards_path=path)

        # diff-aware sync: a row identical on every synced field is skipped outright - the
        # rerun issues no row writes at all (the OOM regression this test guards against was
        # a whole-table UPDATE on every run).
        assert stats["created"] == 0
        assert stats["updated"] == 0
        assert stats["deleted"] == 0
        assert stats["skipped"] == 1
        assert CanonicalPrintingMetadata.objects.count() == 1
        writes = [q for q in queries if q["sql"].startswith(("INSERT INTO", "UPDATE", "DELETE"))]
        assert writes == []

    def test_metadata_deleted_when_no_longer_in_bulk_data(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical_card)
        path = _write_bulk_data_file(tmp_path, [])  # bulk file no longer contains this card

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["deleted"] == 1
        assert CanonicalPrintingMetadata.objects.count() == 0

    def test_unchanged_row_is_excluded_from_bulk_update(self, db, tmp_path, monkeypatch):
        changed_card = CanonicalCardFactory()
        unchanged_card = CanonicalCardFactory()
        _seed_row_matching_record(changed_card)
        _seed_row_matching_record(unchanged_card)
        records = [
            _record(id=str(changed_card.identifier), full_art=True),  # one synced field differs
            _record(id=str(unchanged_card.identifier)),  # identical to the seeded row
        ]
        path = _write_bulk_data_file(tmp_path, records)
        spy = _BulkWriteSpy(monkeypatch)

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["updated"] == 1
        assert stats["skipped"] == 1
        assert [call["pks"] for call in spy.update_calls] == [[changed_card.pk]]

    def test_bulk_create_is_batched(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(printing_metadata_import, "_METADATA_WRITE_BATCH_SIZE", 2)
        cards = [CanonicalCardFactory() for _ in range(3)]
        path = _write_bulk_data_file(tmp_path, [_record(id=str(card.identifier)) for card in cards])
        spy = _BulkWriteSpy(monkeypatch)

        with CaptureQueriesContext(connection) as queries:
            stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["created"] == 3
        assert [call["kwargs"] for call in spy.create_calls] == [{"batch_size": 2}]
        inserts = [q for q in queries if q["sql"].startswith("INSERT INTO")]
        assert len(inserts) == 2  # 3 rows at batch_size=2 -> statements of 2 + 1

    def test_bulk_update_is_batched(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(printing_metadata_import, "_METADATA_WRITE_BATCH_SIZE", 2)
        cards = [CanonicalCardFactory() for _ in range(3)]
        for card in cards:
            _seed_row_matching_record(card)
        records = [_record(id=str(card.identifier), full_art=True) for card in cards]
        path = _write_bulk_data_file(tmp_path, records)
        spy = _BulkWriteSpy(monkeypatch)

        with CaptureQueriesContext(connection) as queries:
            stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["updated"] == 3
        update_kwargs = [call["kwargs"] for call in spy.update_calls]
        assert update_kwargs == [{"batch_size": 2, "fields": printing_metadata_import._METADATA_SYNC_FIELDS}]
        updates = [q for q in queries if q["sql"].startswith("UPDATE")]
        assert len(updates) == 2  # 3 rows at batch_size=2 -> statements of 2 + 1

    def test_stale_rows_deleted_in_batches(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(printing_metadata_import, "_METADATA_WRITE_BATCH_SIZE", 2)
        for _ in range(3):
            CanonicalPrintingMetadataFactory()
        path = _write_bulk_data_file(tmp_path, [])  # bulk file no longer contains any of them

        with CaptureQueriesContext(connection) as queries:
            stats = import_scryfall_printing_metadata(default_cards_path=path)

        # full-sync delete semantics survive batching: every stale row is gone
        assert stats["deleted"] == 3
        assert CanonicalPrintingMetadata.objects.count() == 0
        deletes = [q for q in queries if q["sql"].startswith("DELETE")]
        assert len(deletes) == 2  # 3 stale keys at batch_size=2 -> chunks of 2 + 1

    def test_stats_counts_across_a_mixed_scenario(self, db, tmp_path):
        unchanged_card = CanonicalCardFactory()
        changed_card = CanonicalCardFactory()
        new_card = CanonicalCardFactory()
        stale_card = CanonicalCardFactory()
        _seed_row_matching_record(unchanged_card)
        _seed_row_matching_record(changed_card)
        CanonicalPrintingMetadataFactory(canonical_card=stale_card)
        records = [
            _record(id=str(unchanged_card.identifier)),
            _record(id=str(changed_card.identifier), full_art=True),
            _record(id=str(new_card.identifier)),
        ]
        path = _write_bulk_data_file(tmp_path, records)

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats == {"created": 1, "updated": 1, "deleted": 1, "skipped": 1, "no_matching_card": 0}
        assert CanonicalPrintingMetadata.objects.count() == 3
        assert CanonicalPrintingMetadata.objects.get(canonical_card=changed_card).full_art is True

    def test_none_vs_value_changes_are_detected(self, db, tmp_path):
        none_to_value_card = CanonicalCardFactory()
        value_to_none_card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(
            canonical_card=none_to_value_card, edhrec_rank=None, released_at=date(2015, 1, 1)
        )
        _seed_row_matching_record(value_to_none_card)
        records = [
            _record(id=str(none_to_value_card.identifier)),  # edhrec_rank 1234 vs stored None
            _record(id=str(value_to_none_card.identifier), edhrec_rank=None),  # None vs stored 1234
        ]
        path = _write_bulk_data_file(tmp_path, records)

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["updated"] == 2
        assert CanonicalPrintingMetadata.objects.get(canonical_card=none_to_value_card).edhrec_rank == 1234
        assert CanonicalPrintingMetadata.objects.get(canonical_card=value_to_none_card).edhrec_rank is None

    def test_list_field_changes_are_detected(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        _seed_row_matching_record(canonical_card)
        record = _record(id=str(canonical_card.identifier), frame_effects=["showcase"], promo_types=["foil"])
        path = _write_bulk_data_file(tmp_path, [record])

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["updated"] == 1
        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=canonical_card)
        assert metadata.frame_effects == ["showcase"]
        assert metadata.promo_types == ["foil"]


class TestGetBackFaceNames:
    """
    Public issue #199: back-face determined from a card's NAME via the on-disk Scryfall bulk
    data (no network fetch, no live DB) - see get_back_face_names' own docstring for the full
    design. No `db` fixture needed anywhere here - this is a pure file-read/lookup, not a DB
    write.
    """

    def test_dfc_back_face_is_flagged_true(self, tmp_path):
        record = _record(
            layout="transform",
            card_faces=[{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}],
        )
        path = _write_bulk_data_file(tmp_path, [record])

        assert is_back_face("Insectile Aberration", default_cards_path=path) is True

    def test_dfc_front_face_is_flagged_false(self, tmp_path):
        record = _record(
            layout="transform",
            card_faces=[{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}],
        )
        path = _write_bulk_data_file(tmp_path, [record])

        assert is_back_face("Delver of Secrets", default_cards_path=path) is False

    def test_normal_single_faced_card_is_flagged_false(self, tmp_path):
        record = _record(layout="normal")
        path = _write_bulk_data_file(tmp_path, [record])

        assert is_back_face("Lightning Bolt", default_cards_path=path) is False

    def test_unknown_name_is_flagged_false(self, tmp_path):
        record = _record(
            layout="modal_dfc",
            card_faces=[{"name": "Front Face"}, {"name": "Back Face"}],
        )
        path = _write_bulk_data_file(tmp_path, [record])

        assert is_back_face("Some Other Card", default_cards_path=path) is False

    def test_adventure_second_mode_is_not_flagged_as_back_face(self, tmp_path):
        # Adventure cards nest two named MODES under card_faces, both printed on the same
        # (single) physical face - not a real front/back pair, so this must stay False even
        # though the shape superficially looks like a DFC row.
        record = _record(
            layout="adventure",
            card_faces=[{"name": "Bonecrusher Giant"}, {"name": "Stomp"}],
        )
        path = _write_bulk_data_file(tmp_path, [record])

        assert is_back_face("Stomp", default_cards_path=path) is False

    def test_split_card_second_half_is_not_flagged_as_back_face(self, tmp_path):
        record = _record(
            layout="split",
            card_faces=[{"name": "Fire"}, {"name": "Ice"}],
        )
        path = _write_bulk_data_file(tmp_path, [record])

        assert is_back_face("Ice", default_cards_path=path) is False

    def test_art_series_is_not_flagged_as_back_face(self, tmp_path):
        record = _record(
            layout="art_series",
            card_faces=[{"name": "Some Card"}, {"name": "Some Card Back"}],
        )
        path = _write_bulk_data_file(tmp_path, [record])

        assert is_back_face("Some Card Back", default_cards_path=path) is False

    def test_dfc_row_missing_second_face_is_ignored_without_raising(self, tmp_path):
        record = _record(layout="transform", card_faces=[{"name": "Only Face"}])
        path = _write_bulk_data_file(tmp_path, [record])

        assert get_back_face_names(default_cards_path=path) == frozenset()

    def test_missing_bulk_file_returns_empty_set_without_raising(self, tmp_path):
        missing_path = tmp_path / "does_not_exist.json"

        assert get_back_face_names(default_cards_path=missing_path) == frozenset()

    def test_multiple_dfc_rows_all_captured(self, tmp_path):
        records = [
            _record(layout="transform", card_faces=[{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}]),
            _record(layout="modal_dfc", card_faces=[{"name": "Front Two"}, {"name": "Back Two"}]),
        ]
        path = _write_bulk_data_file(tmp_path, records)

        assert get_back_face_names(default_cards_path=path) == frozenset({"Insectile Aberration", "Back Two"})

    def test_result_is_cached_per_path_not_reparsed_every_call(self, tmp_path, monkeypatch):
        record = _record(
            layout="transform",
            card_faces=[{"name": "Delver of Secrets"}, {"name": "Insectile Aberration"}],
        )
        path = _write_bulk_data_file(tmp_path, [record])
        _load_back_face_names.cache_clear()

        get_back_face_names(default_cards_path=path)
        get_back_face_names(default_cards_path=path)

        info = _load_back_face_names.cache_info()
        assert info.hits == 1
        assert info.misses == 1


class _FakeBulkDataResponse:
    """
    Stand-in for the (non-streamed) /bulk-data API response - status_code + text only.

    Carries TODAY'S entry shape: `jsonl_download_uri` + `compressed_size`. The retired
    `download_uri`/`size` pair is deliberately absent, so this fake can never let a call site
    that still reads the old names pass. `tests/test_scryfall_bulk_data.py` pins the same shape
    against a captured copy of the real API response.
    """

    def __init__(self, updated_at: str, size: int, status_code: int = 200):
        self.status_code = status_code
        self.text = json.dumps(
            {
                "object": "list",
                "data": [
                    {
                        "type": "default_cards",
                        "jsonl_download_uri": "https://example.test/default_cards.jsonl.gz",
                        "updated_at": updated_at,
                        "compressed_size": size,
                    }
                ],
            }
        )


class _FakeStreamResponse:
    """
    Stand-in for a streamed download response (context manager + status_code + iter_content).
    `error`, when given, is raised AFTER every chunk has been yielded - a mid-stream
    connection failure.
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


_DOWNLOAD_URL = "https://example.test/default_cards.jsonl.gz"


def _gzip_chunks(payload: bytes, chunk_size: int = 16) -> list[bytes]:
    """
    `payload` as a gzip stream, split across several network chunks - which is what the real
    download now delivers. Scryfall serves `.jsonl.gz` as `Content-Type: application/gzip` with
    NO `Content-Encoding: gzip` (verified against the live CDN), so `requests` hands the raw
    gzip bytes straight through and the downloader inflates them itself. Splitting small forces
    the streaming decompressor to be exercised across chunk boundaries rather than getting the
    whole member in one call.
    """
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as f:
        f.write(payload)
    raw = buffer.getvalue()
    return [raw[i : i + chunk_size] for i in range(0, len(raw), chunk_size)]


def _mock_scryfall_requests(
    monkeypatch: pytest.MonkeyPatch,
    updated_at: str = "2026-07-28T00:00:00.000Z",
    size: int = 123,
    download_payload: bytes | None = None,
) -> list[str]:
    """
    Routes `requests.get` to fakes: the /bulk-data API returns one default_cards entry carrying
    `updated_at`/`compressed_size`; any other URL is treated as the bulk download itself and is
    served as a GZIP STREAM of `download_payload` (the bytes expected to land on disk after
    decompression). Returns the list of requested URLs so tests can assert whether the download
    was actually hit.
    """
    requested_urls: list[str] = []
    payload = download_payload if download_payload is not None else b""

    def fake_get(url: str, **kwargs: Any) -> Any:
        requested_urls.append(url)
        if url == "https://api.scryfall.com/bulk-data":
            return _FakeBulkDataResponse(updated_at=updated_at, size=size)
        return _FakeStreamResponse(chunks=_gzip_chunks(payload))

    monkeypatch.setattr(requests, "get", fake_get)
    return requested_urls


def _use_tmp_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cache_path = tmp_path / "default_cards.json"
    monkeypatch.setattr(printing_metadata_import, "_cache_path", lambda: cache_path)
    return cache_path


class TestAtomicDownload:
    """
    Issue #513 download-side, part 1: `_download_default_cards` streams to a temp file in the
    same directory and atomically `os.replace`s it over the cache only on success, so a
    mid-stream failure can never truncate the real cache. Preserved verbatim across the
    2026-07-20 JSONL/gzip cutover - the only change is that the bytes arriving off the wire are
    now a gzip stream that the downloader inflates on the way to the temp file. All network is
    mocked - no real Scryfall calls, no real ~620MB files.
    """

    def test_successful_download_lands_via_os_replace_and_writes_sidecar(self, db, tmp_path, monkeypatch):
        cache_path = _use_tmp_cache(monkeypatch, tmp_path)
        # JSONL, as Scryfall now serves it: one object per line, no wrapping array, no commas.
        payload = b'{"id": "11111111-1111-1111-1111-111111111111"}\n'
        _mock_scryfall_requests(monkeypatch, download_payload=payload)
        replaced: list[tuple[Path, Path]] = []
        real_replace = os.replace

        def spy_replace(src: Any, dst: Any) -> None:
            replaced.append((Path(src), Path(dst)))
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy_replace)

        import_scryfall_printing_metadata()

        assert replaced == [(Path(str(cache_path) + ".tmp"), cache_path)]
        # DECOMPRESSED on disk - the persistent cache stays plain JSONL that every other
        # consumer reads without gunzipping on each pass.
        assert cache_path.read_bytes() == payload
        assert not Path(str(cache_path) + ".tmp").exists()
        sidecar = json.loads((tmp_path / "default_cards.meta.json").read_text())
        # The sidecar's `size` key now records the entry's `compressed_size` (the gzipped
        # artefact), not the retired uncompressed `size` - see `_write_sidecar`'s own note.
        assert sidecar == {"updated_at": "2026-07-28T00:00:00.000Z", "size": 123}

    def test_mid_stream_failure_leaves_original_cache_and_no_temp_file(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "default_cards.json"
        original = b"original cache contents"
        cache_path.write_bytes(original)
        # A VALID gzip prefix, then the connection dies - so the failure under test is the
        # transport dropping, not a decode error (that case is covered in
        # test_scryfall_bulk_data.py's truncation/corruption tests).
        valid_prefix = _gzip_chunks(b'{"id": "11111111-1111-1111-1111-111111111111"}\n')[0]

        def failing_get(url: str, **kwargs: Any) -> _FakeStreamResponse:
            return _FakeStreamResponse(
                chunks=[valid_prefix],
                error=requests.exceptions.ConnectionError("connection dropped mid-stream"),
            )

        monkeypatch.setattr(requests, "get", failing_get)

        with pytest.raises(requests.exceptions.ConnectionError):
            _download_default_cards(_DOWNLOAD_URL, cache_path)

        assert cache_path.read_bytes() == original
        assert not Path(str(cache_path) + ".tmp").exists()


class TestRemoteFreshness:
    """
    Issue #513 download-side, part 2: with no explicit path, `import_scryfall_printing_metadata`
    consults the /bulk-data entry's `updated_at` against the download-time sidecar (`_is_fresh`)
    and skips the ~558MB re-download while the remote is unchanged. All network is mocked.
    """

    def test_matching_sidecar_skips_download(self, db, tmp_path, monkeypatch):
        cache_path = _use_tmp_cache(monkeypatch, tmp_path)
        cache_path.write_bytes(b"[\n]\n")
        (tmp_path / "default_cards.meta.json").write_text(
            json.dumps({"updated_at": "2026-07-28T00:00:00.000Z", "size": 123})
        )
        requested_urls = _mock_scryfall_requests(monkeypatch)

        import_scryfall_printing_metadata()

        assert requested_urls == ["https://api.scryfall.com/bulk-data"]
        assert cache_path.read_bytes() == b"[\n]\n"

    def test_missing_sidecar_triggers_download(self, db, tmp_path, monkeypatch):
        cache_path = _use_tmp_cache(monkeypatch, tmp_path)
        cache_path.write_bytes(b"stale cache")
        requested_urls = _mock_scryfall_requests(monkeypatch, download_payload=b"")

        import_scryfall_printing_metadata()

        # The download URL now comes from the entry's `jsonl_download_uri` - the retired
        # `download_uri` no longer exists on any /bulk-data entry.
        assert requested_urls == ["https://api.scryfall.com/bulk-data", _DOWNLOAD_URL]
        assert cache_path.read_bytes() == b""
        sidecar = json.loads((tmp_path / "default_cards.meta.json").read_text())
        assert sidecar == {"updated_at": "2026-07-28T00:00:00.000Z", "size": 123}

    def test_mismatched_sidecar_triggers_download(self, db, tmp_path, monkeypatch):
        cache_path = _use_tmp_cache(monkeypatch, tmp_path)
        cache_path.write_bytes(b"[\n]\n")
        (tmp_path / "default_cards.meta.json").write_text(
            json.dumps({"updated_at": "2026-07-01T00:00:00.000Z", "size": 99})
        )
        requested_urls = _mock_scryfall_requests(monkeypatch)

        import_scryfall_printing_metadata()

        assert requested_urls == ["https://api.scryfall.com/bulk-data", _DOWNLOAD_URL]
        sidecar = json.loads((tmp_path / "default_cards.meta.json").read_text())
        assert sidecar == {"updated_at": "2026-07-28T00:00:00.000Z", "size": 123}

    def test_bulk_data_api_failure_is_loud_not_silent_cache_reuse(self, db, tmp_path, monkeypatch):
        cache_path = _use_tmp_cache(monkeypatch, tmp_path)
        cache_path.write_bytes(b"[\n]\n")

        def failing_get(url: str, **kwargs: Any) -> _FakeBulkDataResponse:
            return _FakeBulkDataResponse(updated_at="2026-07-28T00:00:00.000Z", size=123, status_code=503)

        monkeypatch.setattr(requests, "get", failing_get)

        with pytest.raises(AssertionError):
            import_scryfall_printing_metadata()


# =============================================================================================
# Per-face illustration ids (2026-07-29)
#
# `resolved_illustration_id` returns `card_faces[0].illustration_id` for a multi-faced row - the
# FRONT face - and the other faces' artwork was discarded entirely. That flattening is why a
# back-face scan had no artwork of its own to be attributed to, which is what
# `local_illustration`'s deleted `multi-faced-v1` gate was standing in for. These tests pin BOTH
# halves of the replacement: every face is retained for a genuine double-faced card, and NO face
# entry is invented for a layout whose "faces" are modes printed on one physical side.
# =============================================================================================


class TestFaceIllustrations:
    def test_a_transform_card_retains_both_faces_own_illustration_ids(self, db):
        front, back = str(uuid.uuid4()), str(uuid.uuid4())
        row = printing_metadata_import.PrintingMetadataRow.model_validate(
            _record(
                layout="transform",
                card_faces=[
                    {"name": "Invasion of Tolvada", "illustration_id": front},
                    {"name": "The Broken Sky", "illustration_id": back},
                ],
            )
        )

        assert row.face_illustrations == [
            {"name": "Invasion of Tolvada", "illustration_id": front},
            {"name": "The Broken Sky", "illustration_id": back},
        ]

    def test_the_scalar_illustration_id_is_still_the_front_face(self, db):
        """Four consumers read the scalar column; the per-face list is ADDITIVE, and must not
        change what `resolved_illustration_id` has always returned."""
        front, back = str(uuid.uuid4()), str(uuid.uuid4())
        row = printing_metadata_import.PrintingMetadataRow.model_validate(
            _record(
                layout="transform",
                card_faces=[
                    {"name": "Invasion of Tolvada", "illustration_id": front},
                    {"name": "The Broken Sky", "illustration_id": back},
                ],
            )
        )

        assert str(row.resolved_illustration_id) == front

    @pytest.mark.parametrize("layout", ["split", "adventure", "flip", "aftermath", "mutate", "prototype"])
    def test_a_second_MODE_on_one_printed_face_gains_no_face_entry(self, db, layout):
        """`split`/`adventure`/`flip`/... also nest multiple named modes under `card_faces`, but
        those modes share ONE physical face. Giving "Stomp" its own entry would assert a second
        scannable side of "Bonecrusher Giant" that does not exist - and would let a scan of the
        creature be attributed to the adventure's artwork."""
        row = printing_metadata_import.PrintingMetadataRow.model_validate(
            _record(
                layout=layout,
                card_faces=[
                    {"name": "Bonecrusher Giant", "illustration_id": str(uuid.uuid4())},
                    {"name": "Stomp", "illustration_id": str(uuid.uuid4())},
                ],
            )
        )

        assert row.face_illustrations == []

    @pytest.mark.parametrize("layout", ["transform", "modal_dfc", "double_faced_token", "battle", "reversible_card"])
    def test_every_genuine_double_faced_layout_is_covered(self, db, layout):
        row = printing_metadata_import.PrintingMetadataRow.model_validate(
            _record(
                layout=layout,
                card_faces=[
                    {"name": "A Front", "illustration_id": str(uuid.uuid4())},
                    {"name": "A Back", "illustration_id": str(uuid.uuid4())},
                ],
            )
        )

        assert [face["name"] for face in row.face_illustrations] == ["A Front", "A Back"]

    def test_a_single_faced_card_has_no_face_entries(self, db):
        row = printing_metadata_import.PrintingMetadataRow.model_validate(
            _record(layout="normal", illustration_id=str(uuid.uuid4()))
        )

        assert row.face_illustrations == []

    def test_a_face_without_art_records_none_rather_than_shifting_the_list(self, db):
        """Scryfall omits `illustration_id` on faces with no art of their own. Dropping such a
        face would silently renumber the list, so index 1 would stop meaning "the back"."""
        back = str(uuid.uuid4())
        row = printing_metadata_import.PrintingMetadataRow.model_validate(
            _record(
                layout="transform",
                card_faces=[{"name": "Artless Front"}, {"name": "A Back", "illustration_id": back}],
            )
        )

        assert row.face_illustrations == [
            {"name": "Artless Front", "illustration_id": None},
            {"name": "A Back", "illustration_id": back},
        ]

    def test_the_import_persists_face_illustrations_to_the_database(self, db, tmp_path):
        card = CanonicalCardFactory()
        front, back = str(uuid.uuid4()), str(uuid.uuid4())
        path = _write_bulk_data_file(
            tmp_path,
            [
                _record(
                    id=str(card.identifier),
                    layout="transform",
                    card_faces=[
                        {"name": "Delver of Secrets", "illustration_id": front},
                        {"name": "Insectile Aberration", "illustration_id": back},
                    ],
                )
            ],
        )

        import_scryfall_printing_metadata(default_cards_path=path)

        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=card)
        assert str(metadata.illustration_id) == front
        assert metadata.face_illustrations == [
            {"name": "Delver of Secrets", "illustration_id": front},
            {"name": "Insectile Aberration", "illustration_id": back},
        ]

    def test_a_face_illustration_change_alone_is_a_detected_diff(self, db, tmp_path):
        """`face_illustrations` is in `_METADATA_SYNC_FIELDS`, so a row whose ONLY change is a
        face's artwork must be UPDATEd rather than counted as unchanged and skipped - the same
        property every other synced column has."""
        card = CanonicalCardFactory()
        front, old_back, new_back = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

        def _run(back: str) -> dict[str, Any]:
            path = _write_bulk_data_file(
                tmp_path / back,
                [
                    _record(
                        id=str(card.identifier),
                        layout="transform",
                        card_faces=[
                            {"name": "Front", "illustration_id": front},
                            {"name": "Back", "illustration_id": back},
                        ],
                    )
                ],
            )
            return import_scryfall_printing_metadata(default_cards_path=path)

        (tmp_path / old_back).mkdir()
        (tmp_path / new_back).mkdir()
        _run(old_back)
        stats = _run(new_back)

        assert stats["updated"] == 1
        assert stats["skipped"] == 0
        metadata = CanonicalPrintingMetadata.objects.get(canonical_card=card)
        assert metadata.face_illustrations[1]["illustration_id"] == new_back
