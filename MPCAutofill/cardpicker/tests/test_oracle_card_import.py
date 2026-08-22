import json
import uuid
from pathlib import Path
from typing import Any

from cardpicker.models import CanonicalCard, CanonicalOracleCard
from cardpicker.oracle_card_import import import_scryfall_oracle_cards
from cardpicker.tests.factories import CanonicalCardFactory, CanonicalOracleCardFactory


def _write_oracle_cards_file(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    path = tmp_path / "oracle_cards.json"
    path.write_text("[\n" + "\n".join(json.dumps(record) + "," for record in records) + "\n]")
    return path


def _record(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid.uuid4()),  # the printing scryfall chose to represent this oracle card - NOT the join key
        "oracle_id": str(uuid.uuid4()),
        "name": "Test Card",
        "cmc": 2.0,
        "color_identity": ["U"],
        "type_line": "Instant",
        "legalities": {"standard": "legal"},
        "layout": "normal",
    }
    base.update(overrides)
    return base


class TestImportScryfallOracleCards:
    def test_creates_oracle_card_from_fixture(self, db, tmp_path):
        oracle_id = uuid.uuid4()
        record = _record(
            oracle_id=str(oracle_id),
            oracle_text="Deal 3 damage to any target.",
            cmc=1.0,
            colors=["R"],
            color_identity=["R"],
            type_line="Instant",
            legalities={"standard": "legal", "modern": "legal"},
        )
        path = _write_oracle_cards_file(tmp_path, [record])

        stats = import_scryfall_oracle_cards(oracle_cards_path=path)

        assert stats == {"created": 1, "updated": 0, "deleted": 0, "skipped": 0}
        oracle_card = CanonicalOracleCard.objects.get(canonical_id=oracle_id)
        assert oracle_card.oracle_text == "Deal 3 damage to any target."
        assert oracle_card.cmc == 1.0
        assert oracle_card.colors == ["R"]
        assert oracle_card.color_identity == ["R"]
        assert oracle_card.type_line == "Instant"
        assert oracle_card.legalities == {"standard": "legal", "modern": "legal"}

    def test_join_key_is_oracle_id_not_bulk_rows_own_id(self, db, tmp_path):
        # Scryfall's oracle_cards bulk row's own "id" is the identifier of whichever printing
        # was chosen to represent the oracle card - not the oracle id. Confirmed against the
        # live bulk file: the two differ on every row.
        oracle_id = uuid.uuid4()
        printing_id = uuid.uuid4()
        assert oracle_id != printing_id
        record = _record(id=str(printing_id), oracle_id=str(oracle_id))
        path = _write_oracle_cards_file(tmp_path, [record])

        import_scryfall_oracle_cards(oracle_cards_path=path)

        assert CanonicalOracleCard.objects.filter(canonical_id=oracle_id).exists()
        assert not CanonicalOracleCard.objects.filter(canonical_id=printing_id).exists()

    def test_double_faced_row_falls_back_to_card_faces_for_oracle_text_and_colors(self, db, tmp_path):
        # transform/modal_dfc/double_faced_token layouts omit top-level oracle_text/colors
        # entirely and nest each face's own values under card_faces instead - measured against
        # the live bulk file on 2026-08-22.
        oracle_id = uuid.uuid4()
        record = _record(
            oracle_id=str(oracle_id),
            layout="transform",
            card_faces=[
                {"oracle_text": "Front face text.", "colors": ["B"]},
                {"oracle_text": "Back face text.", "colors": ["B", "W"]},
            ],
        )
        record.pop("colors", None)
        path = _write_oracle_cards_file(tmp_path, [record])

        import_scryfall_oracle_cards(oracle_cards_path=path)

        oracle_card = CanonicalOracleCard.objects.get(canonical_id=oracle_id)
        assert oracle_card.oracle_text == "Front face text.\n//\nBack face text."
        assert oracle_card.colors == ["B", "W"]

    def test_missing_colors_and_oracle_text_default_cleanly(self, db, tmp_path):
        oracle_id = uuid.uuid4()
        record = _record(oracle_id=str(oracle_id))
        record.pop("colors", None)
        path = _write_oracle_cards_file(tmp_path, [record])

        import_scryfall_oracle_cards(oracle_cards_path=path)

        oracle_card = CanonicalOracleCard.objects.get(canonical_id=oracle_id)
        assert oracle_card.oracle_text == ""
        assert oracle_card.colors == []

    def test_rerun_is_idempotent(self, db, tmp_path):
        oracle_id = uuid.uuid4()
        record = _record(oracle_id=str(oracle_id))
        path = _write_oracle_cards_file(tmp_path, [record])

        import_scryfall_oracle_cards(oracle_cards_path=path)
        stats = import_scryfall_oracle_cards(oracle_cards_path=path)

        assert stats == {"created": 0, "updated": 0, "deleted": 0, "skipped": 1}
        assert CanonicalOracleCard.objects.count() == 1

    def test_rerun_updates_changed_fields(self, db, tmp_path):
        oracle_id = uuid.uuid4()
        CanonicalOracleCardFactory(canonical_id=oracle_id, cmc=1.0, type_line="Instant")
        record = _record(oracle_id=str(oracle_id), cmc=5.0, type_line="Sorcery")
        path = _write_oracle_cards_file(tmp_path, [record])

        stats = import_scryfall_oracle_cards(oracle_cards_path=path)

        assert stats["updated"] == 1
        oracle_card = CanonicalOracleCard.objects.get(canonical_id=oracle_id)
        assert oracle_card.cmc == 5.0
        assert oracle_card.type_line == "Sorcery"

    def test_stale_oracle_card_deleted_when_no_longer_in_bulk_data(self, db, tmp_path):
        oracle_id = uuid.uuid4()
        CanonicalOracleCardFactory(canonical_id=oracle_id)
        path = _write_oracle_cards_file(tmp_path, [])  # bulk file no longer contains it

        stats = import_scryfall_oracle_cards(oracle_cards_path=path)

        assert stats["deleted"] == 1
        assert CanonicalOracleCard.objects.count() == 0


class TestOracleCardPrintingRelationship:
    def test_one_oracle_card_relates_to_many_printings(self, db):
        oracle_id = uuid.uuid4()
        card_a = CanonicalCardFactory(canonical_id=oracle_id)
        card_b = CanonicalCardFactory(canonical_id=oracle_id)
        unrelated_card = CanonicalCardFactory()  # different oracle card entirely
        oracle_card = CanonicalOracleCardFactory(canonical_id=oracle_id)

        printings = set(CanonicalCard.objects.filter(canonical_id=oracle_card.canonical_id))

        assert printings == {card_a, card_b}
        assert unrelated_card not in printings

    def test_canonical_card_with_no_canonical_id_has_no_matching_oracle_card(self, db):
        # 81 CanonicalCard rows in production (measured 2026-07-29) carry canonical_id=None -
        # this must not raise and must not spuriously match anything.
        card = CanonicalCardFactory(canonical_id=None)
        CanonicalOracleCardFactory()  # unrelated oracle card, must not be matched

        assert CanonicalOracleCard.objects.filter(canonical_id=card.canonical_id).first() is None
