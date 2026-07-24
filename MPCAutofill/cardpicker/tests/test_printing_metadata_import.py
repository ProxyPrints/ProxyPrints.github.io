import json
import uuid
from pathlib import Path
from typing import Any

from cardpicker.models import CanonicalPrintingMetadata
from cardpicker.printing_metadata_import import (
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
        assert stats["skipped"] == 1
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
        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["created"] == 0
        assert stats["updated"] == 1  # bulk_sync always re-updates matched rows
        assert stats["deleted"] == 0
        assert CanonicalPrintingMetadata.objects.count() == 1

    def test_metadata_deleted_when_no_longer_in_bulk_data(self, db, tmp_path):
        canonical_card = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical_card)
        path = _write_bulk_data_file(tmp_path, [])  # bulk file no longer contains this card

        stats = import_scryfall_printing_metadata(default_cards_path=path)

        assert stats["deleted"] == 1
        assert CanonicalPrintingMetadata.objects.count() == 0


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
