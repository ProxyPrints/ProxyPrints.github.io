import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from cardpicker.models import CanonicalPrintingMetadata
from cardpicker.printing_metadata_import import import_scryfall_printing_metadata
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
)

# `factory.Sequence` counters are process-global, and some other test modules'
# snapshot assertions hardcode exact sequence-derived values (e.g. "Artist 0").
# Capture-and-restore keeps this module's use of these shared factories invisible
# to the rest of the suite, regardless of test collection order.
_SHARED_FACTORIES = [CanonicalArtistFactory, CanonicalExpansionFactory, CanonicalCardFactory]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


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
