import io
import json
import logging
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import patch

import imagehash
import pytest
import requests_mock
from PIL import Image

from django.conf import settings as conf_settings

from cardpicker.integrations.game.mtg import (
    Moxfield,
    MTGIntegration,
    format_decklist_line,
)
from cardpicker.integrations.integrations import get_configured_game_integration
from cardpicker.models import CanonicalCard
from cardpicker.schema_types import Game
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
)
from cardpicker.utils import twos_complement


def _make_test_image_for_phash() -> tuple[bytes, int]:
    img = Image.new("RGB", (100, 140))
    pixels = img.load()
    for x in range(100):
        for y in range(140):
            pixels[x, y] = (x * 2 % 256, y % 256, 64)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()
    img_hash = twos_complement(str(imagehash.phash(Image.open(io.BytesIO(img_bytes)))), 64)
    return img_bytes, img_hash


_TEST_IMAGE_BYTES, _TEST_IMAGE_HASH = _make_test_image_for_phash()
_TEST_IMAGE_URL = "http://test.example.com/card.jpg"


class TestFormatDecklistLine:
    def test_includes_set_and_collector_number_when_both_present(self):
        assert format_decklist_line(1, "Lightning Bolt", "lea", "233") == "1 Lightning Bolt (LEA) 233"

    def test_uppercases_the_set_code(self):
        assert format_decklist_line(4, "Brainstorm", "mmq", 123) == "4 Brainstorm (MMQ) 123"

    def test_falls_back_to_bare_name_when_set_code_missing(self):
        assert format_decklist_line(1, "Lightning Bolt", None, "233") == "1 Lightning Bolt"

    def test_falls_back_to_bare_name_when_collector_number_missing(self):
        assert format_decklist_line(1, "Lightning Bolt", "lea", None) == "1 Lightning Bolt"

    def test_falls_back_to_bare_name_when_collector_number_is_blank(self):
        assert format_decklist_line(1, "Lightning Bolt", "lea", "  ") == "1 Lightning Bolt"

    def test_accepts_an_integer_collector_number(self):
        # Archidekt's API returns collectorNumber as an int, not a string
        assert format_decklist_line(1, "Brainstorm", "mmq", 55) == "1 Brainstorm (MMQ) 55"


class TestGetIntegration:
    @pytest.mark.parametrize("environment_variable, integration_class", [(Game.MTG.value, MTGIntegration)])
    def test_get_integration(self, db, environment_variable, integration_class, settings):
        settings.GAME = environment_variable
        assert get_configured_game_integration() == integration_class


class TestMTGIntegration:
    # region constants

    class Decks(Enum):
        # all of these decks have 4x brainstorm, 3x past in flames, and 1x delver of secrets // insectile aberration
        # AETHERHUB = "https://aetherhub.com/Deck/test-796905"
        # AETHERHUB_WITH_WWW = "https://www.aetherhub.com/Deck/test-796905"
        ARCHIDEKT = "https://archidekt.com/decks/3380653"
        ARCHIDEKT_WITH_WWW = "https://www.archidekt.com/decks/3380653"
        ARCHIDEKT_WITH_HASH = "https://archidekt.com/decks/3380653#test"
        ARCHIDEKT_WITH_SLASH = "https://archidekt.com/decks/3380653/test"
        CUBECOBRA = "https://cubecobra.com/cube/overview/2fj4"
        CUBECOBRA_WITH_WWW = "https://www.cubecobra.com/cube/overview/2fj4"
        # DECKSTATS = "https://deckstats.net/decks/216625/2754468-test"
        # DECKSTATS_WITH_WWW = "https://www.deckstats.net/decks/216625/2754468-test"
        MAGICVILLE = "https://magic-ville.com/fr/decks/showdeck?ref=948045"
        MAGICVILLE_WITH_WWW = "https://www.magic-ville.com/fr/decks/showdeck?ref=948045"
        MANASTACK = "https://manastack.com/deck/test-426"
        MOXFIELD = "https://www.moxfield.com/decks/D42-or9pCk-uMi4XzRDziQ"
        MOXFIELD_WITHOUT_WWW = "https://moxfield.com/decks/D42-or9pCk-uMi4XzRDziQ"
        # MTGGOLDFISH = "https://www.mtggoldfish.com/deck/5149750"
        # MTGGOLDFISH_WITHOUT_WWW = "https://mtggoldfish.com/deck/5149750"
        SCRYFALL = "https://scryfall.com/@mpcautofill/decks/71bb2d40-c922-4a01-a63e-7ba2dde29a5c"
        SCRYFALL_WITH_WWW = "https://www.scryfall.com/@mpcautofill/decks/71bb2d40-c922-4a01-a63e-7ba2dde29a5c"
        TAPPEDOUT = "https://tappedout.net/mtg-decks/09-10-22-DoY-test"
        TAPPEDOUT_WITH_WWW = "https://www.tappedout.net/mtg-decks/09-10-22-DoY-test"

    # endregion

    # region fixtures

    @pytest.fixture()
    def moxfield_secret_setter(self):
        def _callable(moxfield_secret: str | None):
            conf_settings.MOXFIELD_SECRET = moxfield_secret

        old_secret = conf_settings.MOXFIELD_SECRET
        yield _callable
        conf_settings.MOXFIELD_SECRET = old_secret

    # endregion

    # region tests

    def test_get_double_faced_card_pairs(self):
        assert len(MTGIntegration.get_double_faced_card_pairs()) > 0

    def test_get_meld_pairs(self):
        assert len(MTGIntegration.get_meld_pairs()) > 0

    @pytest.mark.parametrize("url", [item.value for item in Decks], ids=[item.name.lower() for item in Decks])
    def test_valid_url(self, client, django_settings, snapshot, url: str):
        decklist = MTGIntegration.query_import_site(url)
        assert decklist
        assert Counter(decklist.splitlines()) == snapshot

    @pytest.mark.parametrize(
        "moxfield_secret, is_moxfield_enabled",
        [
            (None, False),
            ("", False),
            ("lorem ipsum", True),
        ],
    )
    def test_moxfield_enabled(self, moxfield_secret_setter, moxfield_secret, is_moxfield_enabled):
        moxfield_secret_setter(moxfield_secret)
        import_sites = MTGIntegration.get_import_sites()
        if is_moxfield_enabled:
            assert Moxfield in import_sites
        else:
            assert Moxfield not in import_sites

    def test_moxfield_rate_limit(self, monkeypatch):
        with requests_mock.Mocker() as mock:
            mock.get("https://api.moxfield.com/v2/decks/all/D42-or9pCk-uMi4XzRDziQ", json={})

            with ThreadPoolExecutor(max_workers=3) as pool:
                t0 = time.time()
                pool.map(lambda _: [Moxfield.retrieve_card_list(self.Decks.MOXFIELD.value) for _ in range(2)], range(3))
            t1 = time.time()
            t = t1 - t0
            assert t > 5  # one second between calls

    @dataclass
    class TestCard:
        identifier: uuid.UUID
        name: str
        is_default: bool
        artist: str
        image_hash: int | None = None

    @dataclass
    class TestArtist:
        name: str

    class TestUUIDs:
        UUID_1 = uuid.UUID("a5750af9-5f0b-4662-baaf-55186f16e6cc")
        UUID_2 = uuid.UUID("ebf975f5-e439-4502-be21-8d0b7a6c79b7")
        UUID_3 = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        UUID_4 = uuid.UUID("2f6b9e0a-8b8b-4b8e-8b8e-8b8e8b8e8b8e")

    _IMAGE_URIS_EMPTY: dict[str, str] = {
        "small": "",
        "normal": "",
        "large": "",
        "png": "",
        "art_crop": "",
        "border_crop": "",
    }

    _SWAMP_RECORD = {
        "id": str(TestUUIDs.UUID_1),
        "oracle_id": "b34bb2dc-c1af-4d77-b0b3-a0fb342a5fc6",
        "name": "swamp",
        "set": "lea",
        "collector_number": "001",
        "artist": "john avon",
        "image_uris": _IMAGE_URIS_EMPTY,
        "layout": "normal",
    }
    _FOREST_RECORD = {
        "id": str(TestUUIDs.UUID_2),
        "oracle_id": "44623693-51d6-49ad-8cd7-140505caf02f",
        "name": "forest",
        "set": "lea",
        "collector_number": "002",
        "artist": "wayne reynolds",
        "image_uris": _IMAGE_URIS_EMPTY,
        "layout": "normal",
    }
    _MOUNTAIN_RECORD = {
        "id": str(TestUUIDs.UUID_3),
        "oracle_id": "8ae3562f-28b7-4462-96ed-be0cf7052ccc",
        "name": "mountain",
        "set": "lea",
        "collector_number": "003",
        "artist": "ron spears",
        "image_uris": _IMAGE_URIS_EMPTY,
        "layout": "normal",
    }
    _ART_SERIES_RECORD = {
        "id": str(TestUUIDs.UUID_1),
        "oracle_id": "b34bb2dc-c1af-4d77-b0b3-a0fb342a5fc6",
        "name": "swamp art series",
        "set": "lea",
        "collector_number": "001",
        "artist": "john avon",
        "image_uris": _IMAGE_URIS_EMPTY,
        "layout": "art_series",
    }
    _SWAMP_WITH_IMAGE_URL_RECORD = {
        **_SWAMP_RECORD,
        "image_uris": {**_IMAGE_URIS_EMPTY, "small": _TEST_IMAGE_URL},
    }
    _FOREST_WITH_NEW_ARTIST_RECORD = {**_FOREST_RECORD, "artist": "new artist not in db"}
    _SWAMP_MISSING_EXPANSION_RECORD = {**_SWAMP_RECORD, "set": "xyz"}
    _SWAMP_ITALIAN_RECORD = {
        **_SWAMP_RECORD,
        "id": str(TestUUIDs.UUID_4),
        "name": "palude",
        "lang": "it",
    }

    def get_scryfall_data_file(self, records: list[dict[str, Any]]) -> str:
        return "[\n" + "\n".join(json.dumps(record) + "," for record in records) + "\n]"

    @pytest.mark.parametrize(
        "existing_artists, existing_cards, default_cards_records, oracle_cards_records, expected_cards, mock_image_url, expected_log_messages",
        [
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data
                [_SWAMP_RECORD, _FOREST_RECORD, _MOUNTAIN_RECORD],
                [],
                # expected state
                [
                    TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon"),
                    TestCard(TestUUIDs.UUID_2, "forest", False, "wayne reynolds"),
                    TestCard(TestUUIDs.UUID_3, "mountain", False, "ron spears"),
                ],
                None,
                [],
                id="import three cards into empty db",
            ),
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data
                [_SWAMP_RECORD, _FOREST_RECORD],
                [_SWAMP_RECORD],
                # expected state
                [
                    TestCard(TestUUIDs.UUID_1, "swamp", True, "john avon"),
                    TestCard(TestUUIDs.UUID_2, "forest", False, "wayne reynolds"),
                ],
                None,
                [],
                id="card in oracle_cards dataset is marked with is_default=True",
            ),
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data
                [],
                [_SWAMP_RECORD],
                # expected state
                [TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon")],
                None,
                [],
                id="card present in oracle_cards but not in default_cards is still added to db",
            ),
            pytest.param(
                # existing DB state
                [TestArtist(name="john avon")],
                [TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon")],
                # incoming data
                [_SWAMP_RECORD, _FOREST_RECORD],
                [],
                # expected state
                [
                    TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon"),
                    TestCard(TestUUIDs.UUID_2, "forest", False, "wayne reynolds"),
                ],
                None,
                [],
                id="card A exists in db, import cards A and B, B should be added and A left as-is",
            ),
            pytest.param(
                # existing DB state
                [TestArtist(name="john avon"), TestArtist(name="wayne reynolds")],
                [
                    TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon"),
                    TestCard(TestUUIDs.UUID_2, "forest", False, "wayne reynolds"),
                ],
                # incoming data
                [_SWAMP_RECORD, _FOREST_RECORD],
                [],
                # expected state
                [
                    TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon"),
                    TestCard(TestUUIDs.UUID_2, "forest", False, "wayne reynolds"),
                ],
                None,
                [],
                id="no op if all cards present",
            ),
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data
                [_SWAMP_WITH_IMAGE_URL_RECORD],
                [],
                # expected state
                [TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon", image_hash=_TEST_IMAGE_HASH)],
                _TEST_IMAGE_URL,
                [],
                id="image phash computed",
            ),
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data
                [_ART_SERIES_RECORD],
                [],
                # expected state
                [],
                None,
                [],
                id="art series card skipped",
            ),
            pytest.param(
                # existing DB state
                [TestArtist(name="john avon")],
                [],
                # incoming data
                [_SWAMP_RECORD, _FOREST_WITH_NEW_ARTIST_RECORD],
                [],
                # expected state
                [
                    TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon"),
                    TestCard(TestUUIDs.UUID_2, "forest", False, "new artist not in db"),
                ],
                None,
                [],
                id="new artist created",
            ),
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data
                [_SWAMP_MISSING_EXPANSION_RECORD],
                [],
                # expected state
                [],
                None,
                ["xyz"],
                id="card with an expansion code not in db is skipped",
            ),
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data - english printing first, italian variant of the same slot second
                [_SWAMP_RECORD, _SWAMP_ITALIAN_RECORD],
                [],
                # expected state - only the english printing is kept
                [TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon")],
                None,
                [],
                id="duplicate language variant for same slot keeps the english printing (english first)",
            ),
            pytest.param(
                # existing DB state
                [],
                [],
                # incoming data - italian variant first, english printing of the same slot second
                [_SWAMP_ITALIAN_RECORD, _SWAMP_RECORD],
                [],
                # expected state - the later english printing displaces the earlier italian claim
                [TestCard(TestUUIDs.UUID_1, "swamp", False, "john avon")],
                None,
                [],
                id="duplicate language variant for same slot keeps the english printing (italian first)",
            ),
        ],
    )
    def test_import_canonical_cards_and_artists(
        self,
        django_settings,
        tmp_path: Path,
        caplog,
        existing_artists: list,
        existing_cards: list,
        default_cards_records: list[dict],
        oracle_cards_records: list[dict],
        expected_cards: list,
        mock_image_url: str | None,
        expected_log_messages: list[str],
    ):
        # arrange
        caplog.set_level(logging.WARNING, logger="cardpicker.integrations.game.mtg")
        expansion = CanonicalExpansionFactory(code="lea")
        artists_in_db = {artist.name: CanonicalArtistFactory(name=artist.name) for artist in existing_artists}
        for card in existing_cards:
            CanonicalCardFactory(
                identifier=card.identifier,
                name=card.name,
                is_default=card.is_default,
                artist=artists_in_db[card.artist],
                expansion=expansion,
            )
        default_path = tmp_path / "default_cards.json"
        oracle_path = tmp_path / "oracle_cards.json"
        default_path.write_text(self.get_scryfall_data_file(default_cards_records))
        oracle_path.write_text(self.get_scryfall_data_file(oracle_cards_records))

        # act
        image_mock_ctx = (
            patch(
                "cardpicker.integrations.game.mtg.requests.get",
                side_effect=lambda url, **kwargs: type("_R", (), {"raw": io.BytesIO(_TEST_IMAGE_BYTES)})(),
            )
            if mock_image_url is not None
            else nullcontext()
        )
        with image_mock_ctx:
            MTGIntegration.import_canonical_cards_and_artists(
                default_cards_path=default_path,
                oracle_cards_path=oracle_path,
            )

        # assert
        assert CanonicalCard.objects.count() == len(expected_cards)
        for expected_card in expected_cards:
            db_card = CanonicalCard.objects.get(identifier=expected_card.identifier)
            assert db_card.name == expected_card.name
            assert db_card.is_default == expected_card.is_default
            assert db_card.artist.name == expected_card.artist
            if expected_card.image_hash is not None:
                assert db_card.image_hash == expected_card.image_hash
        for msg in expected_log_messages:
            assert msg in caplog.text

    def test_import_canonical_cards_and_artists_skip_image_hash(self, django_settings, tmp_path: Path):
        # arrange
        CanonicalExpansionFactory(code="lea")
        default_path = tmp_path / "default_cards.json"
        oracle_path = tmp_path / "oracle_cards.json"
        default_path.write_text(self.get_scryfall_data_file([self._SWAMP_WITH_IMAGE_URL_RECORD]))
        oracle_path.write_text(self.get_scryfall_data_file([]))

        # act
        with patch("cardpicker.integrations.game.mtg.requests.get") as mock_get:
            MTGIntegration.import_canonical_cards_and_artists(
                default_cards_path=default_path,
                oracle_cards_path=oracle_path,
                skip_image_hash=True,
            )

        # assert - the per-card image fetch is skipped entirely, not just discarded
        mock_get.assert_not_called()
        db_card = CanonicalCard.objects.get(identifier=self.TestUUIDs.UUID_1)
        assert db_card.image_hash == 0

    # endregion
