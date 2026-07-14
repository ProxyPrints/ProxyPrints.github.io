import datetime as dt

import freezegun
import pytest

from django.core import management
from django.utils.timezone import make_aware, make_naive

from cardpicker.documents import CardSearch
from cardpicker.models import CanonicalArtist, CanonicalCard, Card, VotePolarity
from cardpicker.sources.api import Folder, Image
from cardpicker.sources.source_types import SourceTypeChoices
from cardpicker.sources.update_database import bulk_sync_objects, update_database
from cardpicker.tags import Tags
from cardpicker.tests import factories
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
)

DEFAULT_DATE = dt.datetime(2023, 1, 1)


class TestAPI:
    # region constants

    FOLDER_A = Folder(id="a", name="Folder A", parent=None)
    FOLDER_B = Folder(id="b", name="Folder B", parent=FOLDER_A)
    FOLDER_C = Folder(id="c", name="Folder C [NSFW]", parent=FOLDER_B)
    FOLDER_D = Folder(id="d", name="Folder D [Tag in data]", parent=FOLDER_B)
    FOLDER_E = Folder(id="e", name="Folder E [tagindata]", parent=FOLDER_B)  # refers to the tag's alias
    FOLDER_F = Folder(id="f", name="Folder F [tagindata]", parent=FOLDER_B)  # refers to the tag's alias
    FOLDER_G = Folder(id="g", name="Folder G [Tag in Data] (Some more words)", parent=FOLDER_B)
    FOLDER_H = Folder(id="h", name="Folder H [Tag in Data, Some more words]", parent=None)
    FOLDER_X = Folder(id="x", name="Folder X [NSFW, Extended, Full Art]", parent=None)
    FOLDER_Y = Folder(id="y", name="Folder Y [full art, Invalid Tag]", parent=None)
    FOLDER_Z = Folder(id="z", name="Folder z [Full Art", parent=None)
    FOLDER_FRENCH = Folder(id="french", name="{FR} Folder", parent=None)

    IMAGE_A = Image(
        id="a",
        name="Image A.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_B = Image(
        id="b",
        name="Image B [NSFW].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_C = Image(
        id="b",
        name="Image C.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_C,
    )
    IMAGE_D = Image(
        id="b",
        name="Image D [NSFW, full art].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_C,
    )
    IMAGE_E = Image(
        id="e",
        name="Image E [invalid tag.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_F = Image(
        id="F",
        name="Image F [NSFW, tag in data].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_G = Image(
        id="G",
        name="Image G [NSFW] (John Doe).png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_H = Image(
        id="H",
        name="Image H [A, NSFW, B] (John Doe).png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_I = Image(
        id="I",
        name="Image A.I.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_J = Image(
        id="J",
        name="Image J [Child Tag].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_K = Image(
        id="K",
        name="Image K [Grandchild Tag].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_L = Image(
        id="L",
        name="Image L [NSFW].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_D,
    )
    IMAGE_FRENCH = Image(
        id="french",
        name="French.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_FRENCH,
    )
    IMAGE_ENGLISH = Image(
        id="english",
        name="{EN} English.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_FRENCH,
    )
    IMAGE_NSFW = Image(
        id="nsfw",
        name="NSFW [NSFW].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_DOUBLE_NSFW = Image(
        id="double nsfw",
        name="NSFW (NSFW) [NSFW].png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_A,
    )
    IMAGE_IMPLICITLY_FRENCH = Image(
        id="implicitly_french",
        name="Implicitly French.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_FRENCH,
    )
    IMAGE_EXPLICITLY_ENGLISH = Image(
        id="explicitly_english",
        name="{EN} Explicitly English.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1,
        folder=FOLDER_FRENCH,
    )

    # endregion

    # region tests

    @pytest.mark.parametrize(
        "folder, full_path",
        [(FOLDER_A, "Folder A"), (FOLDER_B, "Folder A / Folder B"), (FOLDER_C, "Folder A / Folder B / Folder C")],
    )
    def test_folder_full_path(self, django_settings, folder, full_path):
        tags = Tags()
        assert folder.get_full_path(tags=tags) == full_path

    @pytest.mark.parametrize(
        "folder, expected_language",
        [
            (FOLDER_A, None),
            (FOLDER_FRENCH, "FR"),
        ],
    )
    def test_folder_language(self, django_settings, folder, expected_language):
        tags = Tags()
        if expected_language is None:
            assert folder.get_language(tags=tags) is None
        else:
            assert folder.get_language(tags=tags).alpha_2.lower() == expected_language.lower()

    @pytest.mark.parametrize(
        "folder, expected_tags",
        [
            (FOLDER_A, set()),
            (FOLDER_B, set()),
            (FOLDER_C, {"NSFW"}),
            (FOLDER_D, {"Tag in Data"}),
            (FOLDER_E, {"Tag in Data"}),
            (FOLDER_X, {"NSFW", "Extended", "Full Art"}),
            (FOLDER_Y, {"Full Art"}),
            (FOLDER_Z, set()),
        ],
    )
    def test_folder_tags(self, django_settings, tag_in_data, extended_tag, full_art_tag, folder, expected_tags):
        tags = Tags()
        assert folder.get_tags(tags=tags) == expected_tags

    @pytest.mark.parametrize(
        "folder, expected_language, expected_name, expected_tags",
        [
            (FOLDER_A, None, "Folder A", set()),
            (FOLDER_B, None, "Folder B", set()),
            (FOLDER_C, None, "Folder C", {"NSFW"}),
            (FOLDER_G, None, "Folder G (Some more words)", {"Tag in Data"}),
            (FOLDER_H, None, "Folder H [Some more words]", {"Tag in Data"}),
        ],
    )
    def test_folder_name(
        self,
        django_settings,
        tag_in_data,
        extended_tag,
        full_art_tag,
        folder,
        expected_language,
        expected_name,
        expected_tags,
    ):
        tags = Tags()
        language, name, extracted_tags = folder.unpack_name(tags=tags)
        if expected_language is None:
            assert language is None
        else:
            assert language.alpha_2.lower() == expected_language.lower()
        assert name == expected_name
        assert extracted_tags == expected_tags

    @pytest.mark.parametrize(
        "image, expected_language",
        [
            (IMAGE_A, None),
            (IMAGE_FRENCH, "FR"),
            (IMAGE_ENGLISH, "EN"),
            (IMAGE_IMPLICITLY_FRENCH, "FR"),
            (IMAGE_EXPLICITLY_ENGLISH, "EN"),  # despite being in a French folder
        ],
    )
    def test_image_language(self, django_settings, image, expected_language):
        tags = Tags()
        if expected_language is None:
            language, _, _, _, _, _, _ = image.unpack_name(tags=tags)
            assert language is None
        else:
            language, _, _, _, _, _, _ = image.unpack_name(tags=tags)
            assert language.alpha_2.lower() == expected_language.lower()

    @pytest.mark.parametrize(
        "image, expected_tags",
        [
            (IMAGE_A, set()),
            (IMAGE_B, {"NSFW"}),
            (IMAGE_C, {"NSFW"}),
            (IMAGE_D, {"NSFW", "Full Art"}),
            (IMAGE_E, set()),
            (IMAGE_F, {"NSFW", "Tag in Data"}),
            (IMAGE_H, {"NSFW"}),
            (IMAGE_J, {"Child Tag", "Tag in Data"}),  # `Tag in Data` is implied by `Child Tag`
            (IMAGE_K, {"Grandchild Tag", "Child Tag", "Tag in Data"}),  # `Child Tag` is implied by `Grandchild Tag`
        ],
    )
    def test_image_tags(self, django_settings, grandchild_tag, extended_tag, full_art_tag, image, expected_tags):
        tags = Tags()
        _, _, extracted_tags, _, _, _, _ = image.unpack_name(tags=tags)
        assert extracted_tags == expected_tags

    @pytest.mark.parametrize(
        "image, expected_language, expected_name, expected_tags, expected_extension",
        [
            (IMAGE_A, None, "Image A", set(), "png"),
            (IMAGE_B, None, "Image B", {"NSFW"}, "png"),
            (IMAGE_C, None, "Image C", {"NSFW"}, "png"),  # tag inherited from parent
            (IMAGE_D, None, "Image D", {"NSFW", "Full Art"}, "png"),
            (IMAGE_E, None, "Image E [invalid tag", set(), "png"),
            (IMAGE_F, None, "Image F", {"NSFW", "Tag in Data"}, "png"),
            (IMAGE_G, None, "Image G (John Doe)", {"NSFW"}, "png"),
            (IMAGE_H, None, "Image H [A, B] (John Doe)", {"NSFW"}, "png"),
            (IMAGE_I, None, "Image A.I", set(), "png"),
            (IMAGE_L, None, "Image L", {"NSFW", "Tag in Data"}, "png"),  # first tag from folder, second from image
            (IMAGE_NSFW, None, "NSFW", {"NSFW"}, "png"),
            (IMAGE_DOUBLE_NSFW, None, "NSFW", {"NSFW"}, "png"),
        ],
    )
    def test_unpack_name(
        self,
        django_settings,
        tag_in_data,
        extended_tag,
        full_art_tag,
        image,
        expected_language,
        expected_name,
        expected_tags,
        expected_extension,
    ):
        tags = Tags()
        language, name, extracted_tags, extension, _, _, _ = image.unpack_name(tags=tags)
        if expected_language is None:
            assert language is None
        else:
            assert language.alpha_2.lower() == expected_language.lower()
        assert name == expected_name
        assert extracted_tags == expected_tags
        assert extension == expected_extension


# endregion


class TestUpdateDatabase:
    # region tests

    def test_comprehensive_snapshot(self, snapshot, django_settings, elasticsearch, all_sources, tag_in_data):
        update_database()
        assert list(Card.objects.all().order_by("identifier")) == snapshot(name="cards")

    def test_upsert(self, django_settings, elasticsearch, all_sources):
        update_database()
        pk_to_identifier_1 = {x.pk: x.identifier for x in Card.objects.all()}
        update_database()
        pk_to_identifier_2 = {x.pk: x.identifier for x in Card.objects.all()}
        assert pk_to_identifier_1 == pk_to_identifier_2

    def test_all_sources_scanned_concurrently_local_file(
        self, transactional_db, settings, elasticsearch, tmp_path_factory
    ):
        # Local-file sources (no network) exercise the same all-sources outer loop the Google
        # Drive-backed fixtures above do, but deterministically and without depending on the
        # real test drives being reachable - see MAX_SOURCE_WORKERS in update_database.py.
        # `transactional_db` (real commits, TRUNCATE-based cleanup) rather than the default
        # rollback-wrapped `db` fixture - update_database() now spawns worker threads, each on
        # its own DB connection, and writes from those connections aren't visible to (or from)
        # a connection sitting inside `db`'s uncommitted wrapping transaction.
        settings.TIME_ZONE = "UTC"
        from cardpicker.tests.test_local_file_source import _make_png

        roots = [tmp_path_factory.mktemp(f"source_{i}") for i in range(4)]
        for i, root in enumerate(roots):
            _make_png(root / f"Card {i}.png", height=1110)
            factories.SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE, identifier=str(root))

        update_database()

        names = set(Card.objects.values_list("name", flat=True))
        assert names == {f"Card {i}" for i in range(len(roots))}

    def test_one_source_failure_does_not_abort_the_others(
        self, transactional_db, settings, elasticsearch, tmp_path_factory, monkeypatch
    ):
        settings.TIME_ZONE = "UTC"
        from cardpicker.sources import update_database as update_database_module
        from cardpicker.tests.test_local_file_source import _make_png

        roots = [tmp_path_factory.mktemp(f"source_{i}") for i in range(3)]
        sources = []
        for i, root in enumerate(roots):
            _make_png(root / f"Card {i}.png", height=1110)
            sources.append(factories.SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE, identifier=str(root)))
        failing_source_key = sources[1].key

        real_transform = update_database_module.transform_images_into_objects

        def flaky_transform(source, images, tags):
            if source.key == failing_source_key:
                raise RuntimeError("simulated failure for one source")
            return real_transform(source=source, images=images, tags=tags)

        monkeypatch.setattr(update_database_module, "transform_images_into_objects", flaky_transform)

        update_database()  # must not raise, despite one source failing

        names = set(Card.objects.values_list("name", flat=True))
        assert names == {"Card 0", "Card 2"}  # source 1's card was never written; 0 and 2 still were

    @pytest.mark.parametrize(
        "existing_cards, incoming_cards",
        [
            pytest.param(
                [],
                [],
                id="no changes to empty database",
            ),
            pytest.param(
                [("existing", "Existing Card", DEFAULT_DATE, tuple())],
                [("existing", "Existing Card", DEFAULT_DATE, tuple())],
                id="no changes to populated database",
            ),
            pytest.param(
                [],
                [("created", "Created Card", DEFAULT_DATE, tuple())],
                id="create one card",
            ),
            pytest.param(
                [("updated", "Card to Update", DEFAULT_DATE, tuple())],
                [("updated", "Updated Card", DEFAULT_DATE + dt.timedelta(days=1), tuple())],
                id="update one card",
            ),
            pytest.param(
                [("updated", "Card to Update (Tag in Data)", DEFAULT_DATE, tuple())],
                [("updated", "Updated Card (Tag in Data)", DEFAULT_DATE, ("Tag in Data",))],
                id="update one card - changes to tags but not modified on source side",
            ),
            pytest.param(
                [("deleted", "Card to Delete", DEFAULT_DATE, tuple())],
                [],
                id="delete one card",
            ),
            pytest.param(
                [("updated", "Card to Update", DEFAULT_DATE, set()), ("deleted", "Card to Delete", DEFAULT_DATE, [])],
                [
                    ("created", "Created Card", DEFAULT_DATE, tuple()),
                    ("updated", "Updated Card", DEFAULT_DATE + dt.timedelta(days=1), tuple()),
                ],
                id="create + update + delete",
            ),
            pytest.param(
                [("existing", "Existing Card", DEFAULT_DATE, tuple())],
                [
                    ("existing", "Existing Card", DEFAULT_DATE, tuple()),
                    ("created", "Created Card", DEFAULT_DATE, tuple()),
                ],
                id="create one card while another card exists and is not modified",
            ),
        ],
    )
    @freezegun.freeze_time(DEFAULT_DATE)
    def test_bulk_sync_objects(
        self, django_settings, elasticsearch, tag_in_data, example_drive_1, existing_cards, incoming_cards
    ):
        # arrange - set up database and elasticsearch according to `existing_cards`
        source = factories.SourceFactory()
        for (identifier, searchq, date_modified, tags) in existing_cards:
            factories.CardFactory(
                identifier=identifier,
                searchq=searchq,
                date_created=make_aware(DEFAULT_DATE),
                date_modified=make_aware(date_modified),
                source=source,
                tags=list(tags),
            )
        management.call_command("search_index", "--rebuild", "-f")

        # act
        bulk_sync_objects(
            source=source,
            cards=[
                Card(
                    identifier=identifier,
                    searchq=searchq,
                    date_created=make_aware(DEFAULT_DATE),
                    date_modified=make_aware(date_modified),
                    source=source,
                    tags=list(tags),
                    # not strictly relevant for this test, but values for these non-nullable fields are required.
                    size=0,
                    image_hash=0,
                )
                for (identifier, searchq, date_modified, tags) in incoming_cards
            ],
        )

        # assert - database and elasticsearch should now match `incoming_cards`
        assert {
            (card.identifier, card.searchq, make_naive(card.date_modified), tuple(sorted(card.tags)))
            for card in Card.objects.all()
        } == set(incoming_cards)
        assert {
            (result.identifier, result.searchq_keyword, make_naive(result.date_modified), tuple(sorted(result.tags)))
            for result in CardSearch().search().scan()
        } == set(incoming_cards)

    @freezegun.freeze_time(DEFAULT_DATE)
    def test_bulk_sync_objects_persists_expansion_hint_on_update(self, django_settings, elasticsearch):
        """
        Regression test for a real bug found via a live production re-scan:
        `expansion_hint` was added to `Card` for Stage 3 (set-code ranking hints), but
        `bulk_sync_objects`'s `bulk_update` field whitelist didn't include it, so a
        freshly-computed `expansion_hint` was silently never persisted for any card that
        already existed from a prior scan - only brand-new cards (via `bulk_create`, which
        isn't field-limited) ever picked it up. This also needs `expansion_hint` in the
        update-detection condition, since a card whose *only* change is its expansion_hint
        must still be recognised as needing an update.
        """
        source = factories.SourceFactory()
        factories.CardFactory(
            identifier="existing",
            searchq="mountain",
            date_created=make_aware(DEFAULT_DATE),
            date_modified=make_aware(DEFAULT_DATE),
            source=source,
            expansion_hint="",
        )
        management.call_command("search_index", "--rebuild", "-f")

        bulk_sync_objects(
            source=source,
            cards=[
                Card(
                    identifier="existing",
                    searchq="mountain",
                    date_created=make_aware(DEFAULT_DATE),
                    date_modified=make_aware(DEFAULT_DATE),
                    source=source,
                    expansion_hint="mh3",
                    size=0,
                    image_hash=0,
                )
            ],
        )

        assert Card.objects.get(identifier="existing").expansion_hint == "mh3"

    @freezegun.freeze_time(DEFAULT_DATE)
    def test_bulk_sync_objects_does_not_revert_a_resolved_tag_vote_on_reindex(self, django_settings, elasticsearch):
        """
        Regression test for the tag-vote reindex-durability hazard identified when designing
        artist/tag voting: `bulk_sync_objects` computes each incoming card's `tags` purely from
        fresh filename extraction and writes it straight to Postgres + Elasticsearch. Without a
        merge step, a scheduled re-scan would silently revert a consensus-resolved tag-vote
        correction back to whatever the filename currently says. A resolved `CardTagVote` for a
        tag the filename *doesn't* mention must survive a re-scan whose incoming tags are empty.
        """
        source = factories.SourceFactory()
        card = factories.CardFactory(
            identifier="existing",
            searchq="mountain",
            date_created=make_aware(DEFAULT_DATE),
            date_modified=make_aware(DEFAULT_DATE),
            source=source,
            tags=[],
        )
        tag = factories.TagFactory(name="Borderless")
        factories.CardTagVoteFactory(card=card, tag=tag, polarity=VotePolarity.APPLY, source="admin")
        management.call_command("search_index", "--rebuild", "-f")

        # a re-scan whose freshly-extracted tags are empty (the filename mentions nothing) -
        # date_modified is bumped so the pre-existing change-detection condition alone would
        # otherwise recognise this as an update and blindly overwrite `tags` with `[]`.
        bulk_sync_objects(
            source=source,
            cards=[
                Card(
                    identifier="existing",
                    searchq="mountain",
                    date_created=make_aware(DEFAULT_DATE),
                    date_modified=make_aware(DEFAULT_DATE) + dt.timedelta(days=1),
                    source=source,
                    tags=[],
                    size=0,
                    image_hash=0,
                )
            ],
        )

        assert Card.objects.get(identifier="existing").tags == ["Borderless"]

    @pytest.mark.parametrize(
        "canonical_cards, new_card, expected_expansion, expected_collector_number",
        [
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                "Lightning Bolt (LEA 161).jpg",
                "LEA",
                "161",
                id="card name specifies valid expansion+collector number, match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                    ("Lightning Bolt", "M10", "146"),
                ],
                "Lightning Bolt (LEA 161).jpg",
                "LEA",
                "161",
                id="card name specifies valid expansion+collector number, match between two options",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                    ("Lightning Bolt", "M10", "146"),
                ],
                "Lightning Bolt.jpg",
                None,
                None,
                id="card name does not specify expansion+collector number, no match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                    ("Lightning Bolt", "M10", "146"),
                ],
                "Lightning Bolt (LEA 123).jpg",
                None,
                None,
                id="card name specifies invalid option, no match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                    ("Lightning Bolt", "M10", "146"),
                ],
                "Lightning Bolt (LEA 161, M10 146).jpg",
                None,
                None,
                id="card name specifies multiple valid expansion+collector numbers, ambiguous, no match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                "Lightning Bolt (LEA) {161}.jpg",
                "LEA",
                "161",
                id="card name specifies valid expansion+collector number with special syntax, match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                "Lightning Bolt (LEA) {161} (some other tag).jpg",
                "LEA",
                "161",
                id="{collector number} specified not at end of name, match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                "Lightning Bolt (LEA 161) {161}.jpg",
                None,
                None,
                id="card name co-mingles expansion+collector number with special collector number syntax, no match",
            ),
        ],
    )
    def test_associate_with_canonical_card(
        self, django_settings, canonical_cards, new_card, expected_expansion, expected_collector_number
    ):
        for (name, expansion, collector_number) in canonical_cards:
            CanonicalCardFactory.create(
                name=name,
                expansion=CanonicalExpansionFactory(code=expansion),
                collector_number=collector_number,
                image_hash=0,
                small_thumbnail_url="",
                medium_thumbnail_url="",
            )
        _, _, _, _, match, _, _ = Image(
            id="",
            name=new_card,
            size=0,
            created_time=dt.datetime(2026, 1, 1),
            modified_time=dt.datetime(2026, 1, 1),
            height=0,
            folder=Folder(id="", name="", parent=None),
        ).unpack_name(tags=Tags())
        canonical_cards_by_pk = {card.pk: card for card in CanonicalCard.objects.all()}
        if expected_expansion is not None and expected_collector_number is not None:
            assert canonical_cards_by_pk[match].expansion.code == expected_expansion
            assert canonical_cards_by_pk[match].collector_number == expected_collector_number
        else:
            assert match is None

    @pytest.mark.parametrize(
        "canonical_cards, canonical_artists, new_card, expected_artist",
        [
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                [
                    "Wayne Reynolds",
                ],
                "Lightning Bolt.jpg",
                None,
                id="card name does not specify valid artist name, no match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                [
                    "Wayne Reynolds",
                ],
                "Lightning Bolt (Wayne Reynolds).jpg",
                "Wayne Reynolds",
                id="card name specifies valid artist name, match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                [
                    "Wayne Reynolds",
                    "Karl Kopinski",
                ],
                "Lightning Bolt (Wayne Reynolds).jpg",
                "Wayne Reynolds",
                id="card name specifies valid artist name out of two options, match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                [
                    "Wayne Reynolds",
                    "Karl Kopinski",
                ],
                "Lightning Bolt (Wayne Reynolds, Karl Kopinski).jpg",
                None,
                id="card name specifies multiple valid artist names, ambiguous, no match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                [
                    "Wayne Reynolds",
                ],
                "Lightning Bolt (LEA 161).jpg",
                None,
                id="card name specifies valid expansion+collector number, no artist match",
            ),
            pytest.param(
                [
                    ("Lightning Bolt", "LEA", "161"),
                ],
                [
                    "Wayne Reynolds",
                ],
                "Lightning Bolt (LEA 161, Wayne Reynolds).jpg",
                None,
                id="card name specifies valid expansion+collector number, no artist match even though artist specified",
            ),
        ],
    )
    def test_associate_with_canonical_artist(
        self, django_settings, canonical_cards, canonical_artists, new_card, expected_artist
    ):
        for (name, expansion, collector_number) in canonical_cards:
            CanonicalCardFactory.create(
                name=name,
                expansion=CanonicalExpansionFactory(code=expansion),
                collector_number=collector_number,
                image_hash=0,
                small_thumbnail_url="",
                medium_thumbnail_url="",
            )
        for artist_name in canonical_artists:
            CanonicalArtistFactory.create(name=artist_name)
        _, _, _, _, canonical_card_id, canonical_artist_id, _ = Image(
            id="",
            name=new_card,
            size=0,
            created_time=dt.datetime(2026, 1, 1),
            modified_time=dt.datetime(2026, 1, 1),
            height=0,
            folder=Folder(id="", name="", parent=None),
        ).unpack_name(tags=Tags())
        canonical_artists_by_pk = {artist.pk: artist for artist in CanonicalArtist.objects.all()}
        if expected_artist is not None:
            assert canonical_artists_by_pk[canonical_artist_id].name == expected_artist
            assert canonical_card_id is None
        else:
            assert canonical_artist_id is None

    # endregion
