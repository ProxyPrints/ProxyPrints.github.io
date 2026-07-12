import os
from pathlib import Path

import pytest
from PIL import Image as PILImage

from django.urls import reverse

from cardpicker import views
from cardpicker.models import Card
from cardpicker.sources.api import PathTraversalError, resolve_within_root
from cardpicker.sources.source_types import LocalFile, SourceTypeChoices
from cardpicker.sources.update_database import update_database
from cardpicker.tests.factories import CardFactory, SourceFactory


def _make_png(path: Path, height: int, width: int = 10) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (width, height)).save(path)


class TestResolveWithinRoot:
    def test_path_within_root_is_returned(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file.png").touch()
        resolved = resolve_within_root(root=tmp_path, candidate=tmp_path / "sub" / "file.png")
        assert resolved == (tmp_path / "sub" / "file.png").resolve()

    def test_dot_dot_traversal_is_rejected(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        (tmp_path / "outside.png").touch()
        with pytest.raises(PathTraversalError):
            resolve_within_root(root=root, candidate=root / ".." / "outside.png")

    def test_symlink_escape_is_rejected(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.png"
        outside.touch()
        symlink = root / "escape.png"
        symlink.symlink_to(outside)
        with pytest.raises(PathTraversalError):
            resolve_within_root(root=root, candidate=symlink)


class TestLocalFileSourceType:
    def test_get_all_folders_valid_root(self, tmp_path: Path):
        source = SourceFactory.build(identifier=str(tmp_path))
        folders = LocalFile.get_all_folders([source])
        assert folders[source.key] is not None
        assert folders[source.key].id == str(tmp_path.resolve())
        assert folders[source.key].name == tmp_path.name

    def test_get_all_folders_missing_root(self, tmp_path: Path):
        source = SourceFactory.build(identifier=str(tmp_path / "does-not-exist"))
        folders = LocalFile.get_all_folders([source])
        assert folders[source.key] is None

    def test_get_all_folders_inside_folder(self, tmp_path: Path):
        (tmp_path / "Folder A").mkdir()
        (tmp_path / "Folder B").mkdir()
        (tmp_path / "not_a_folder.png").touch()
        os.symlink(tmp_path / "Folder A", tmp_path / "Symlinked Folder", target_is_directory=True)

        source = SourceFactory.build(identifier=str(tmp_path))
        root_folder = LocalFile.get_all_folders([source])[source.key]
        subfolders = LocalFile.get_all_folders_inside_folder(root_folder)

        assert sorted(x.name for x in subfolders) == ["Folder A", "Folder B"]
        assert all(x.parent is root_folder for x in subfolders)

    def test_get_all_images_inside_folder(self, tmp_path: Path):
        _make_png(tmp_path / "Card A.png", height=110)
        _make_png(tmp_path / "Card B.jpg", height=220)
        (tmp_path / "not_an_image.txt").write_text("hello")
        (tmp_path / "subfolder").mkdir()
        os.symlink(tmp_path / "Card A.png", tmp_path / "Escaped Symlink.png")

        source = SourceFactory.build(identifier=str(tmp_path))
        root_folder = LocalFile.get_all_folders([source])[source.key]
        images = LocalFile.get_all_images_inside_folder(root_folder)

        assert sorted((x.name, x.height) for x in images) == [("Card A.png", 110), ("Card B.jpg", 220)]
        for image in images:
            assert image.id == str(tmp_path.resolve() / image.name)
            assert image.folder is root_folder

    def test_get_small_and_medium_thumbnail_urls_point_at_local_file_image_view(self, settings):
        settings.LOCAL_FILE_SOURCE_BASE_URL = "http://example.com"
        small = LocalFile.get_small_thumbnail_url("/some/path/Card.png")
        medium = LocalFile.get_medium_thumbnail_url("/some/path/Card.png")
        assert small == "http://example.com/2/localFileImage/?identifier=%2Fsome%2Fpath%2FCard.png&size=small"
        assert medium == "http://example.com/2/localFileImage/?identifier=%2Fsome%2Fpath%2FCard.png&size=medium"


class TestLocalFileIndexing:
    def test_update_database_indexes_local_directory(self, django_settings, elasticsearch, tmp_path: Path):
        _make_png(tmp_path / "Card One.png", height=1110)
        _make_png(tmp_path / "Nested" / "Card Two [NSFW].png", height=1110)

        source = SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE, identifier=str(tmp_path))
        update_database(source_key=source.key)

        cards = {card.name: card for card in Card.objects.filter(source=source)}
        assert set(cards.keys()) == {"Card One", "Card Two"}
        assert cards["Card Two"].tags == ["NSFW"]
        assert cards["Card One"].dpi == 300  # 1110px height => 300 DPI, per DPI_HEIGHT_RATIO
        assert cards["Card One"].identifier == str(tmp_path.resolve() / "Card One.png")

    def test_update_database_reindexing_is_idempotent(self, django_settings, elasticsearch, tmp_path: Path):
        _make_png(tmp_path / "Card One.png", height=1110)
        source = SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE, identifier=str(tmp_path))

        update_database(source_key=source.key)
        pks_1 = {card.identifier: card.pk for card in Card.objects.filter(source=source)}
        update_database(source_key=source.key)
        pks_2 = {card.identifier: card.pk for card in Card.objects.filter(source=source)}

        assert pks_1 == pks_2


class TestGetLocalFileImageView:
    def test_serves_image_bytes_for_a_valid_identifier(self, django_settings, client, tmp_path: Path):
        image_path = tmp_path / "Card.png"
        _make_png(image_path, height=42)
        source = SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE, identifier=str(tmp_path))
        card = CardFactory(source=source, identifier=str(image_path))

        response = client.get(reverse(views.get_local_file_image), {"identifier": card.identifier})

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert b"".join(response.streaming_content) == image_path.read_bytes()

    def test_unknown_identifier_is_not_found(self, django_settings, client):
        response = client.get(reverse(views.get_local_file_image), {"identifier": "/does/not/exist.png"})
        assert response.status_code == 404

    def test_missing_identifier_is_a_bad_request(self, django_settings, client):
        response = client.get(reverse(views.get_local_file_image))
        assert response.status_code == 400

    def test_non_get_method_is_rejected(self, django_settings, client):
        response = client.post(reverse(views.get_local_file_image), {"identifier": "whatever"})
        assert response.status_code == 405

    def test_identifier_outside_current_root_is_not_found(self, django_settings, client, tmp_path: Path):
        # simulate a source whose root was reconfigured after indexing, leaving a stale Card whose
        # identifier now falls outside of the (new) configured root.
        outside_file = tmp_path / "outside" / "Card.png"
        _make_png(outside_file, height=42)
        new_root = tmp_path / "new_root"
        new_root.mkdir()
        source = SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE, identifier=str(new_root))
        card = CardFactory(source=source, identifier=str(outside_file))

        response = client.get(reverse(views.get_local_file_image), {"identifier": card.identifier})

        assert response.status_code == 404

    def test_identifier_for_a_deleted_file_is_not_found(self, django_settings, client, tmp_path: Path):
        image_path = tmp_path / "Card.png"
        _make_png(image_path, height=42)
        source = SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE, identifier=str(tmp_path))
        card = CardFactory(source=source, identifier=str(image_path))
        image_path.unlink()

        response = client.get(reverse(views.get_local_file_image), {"identifier": card.identifier})

        assert response.status_code == 404

    def test_identifier_belonging_to_a_non_local_file_source_is_not_found(self, django_settings, client):
        card = CardFactory()  # defaults to a GOOGLE_DRIVE source
        response = client.get(reverse(views.get_local_file_image), {"identifier": card.identifier})
        assert response.status_code == 404
