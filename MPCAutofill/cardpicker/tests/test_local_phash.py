"""
Local-first art-crop URL lookup (Stage B, 2026-07-19, docs/features/catalog-completion-plan.md):
`get_or_compute_canonical_hash` previously always hit Scryfall's live REST API per candidate for
the art-crop URL - measured as the dominant cost (93.6% of a 30-card Stage B wall-clock probe).
The same URL is already parsed from the weekly bulk-data import into
`CanonicalPrintingMetadata.art_crop_url` (see test_printing_metadata_import.py) - these tests
cover the local-first/REST-fallback ordering that change adds.
"""

import cardpicker.local_phash as module
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
)


class TestLocalArtCropUrl:
    def test_returns_url_when_metadata_present_and_populated(self, db):
        canonical = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical, art_crop_url="https://example.test/art.jpg")

        assert module._local_art_crop_url(canonical) == "https://example.test/art.jpg"

    def test_none_when_no_metadata_row_exists(self, db):
        canonical = CanonicalCardFactory()  # no CanonicalPrintingMetadata created for it

        assert module._local_art_crop_url(canonical) is None

    def test_none_when_metadata_present_but_url_empty(self, db):
        canonical = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=canonical, art_crop_url="")

        assert module._local_art_crop_url(canonical) is None


class TestGetOrComputeCanonicalHashArtCropSourcing:
    def test_cached_hash_short_circuits_before_any_lookup(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=999)

        def _fail(*args, **kwargs):
            raise AssertionError("should never be called - image_hash is already cached")

        monkeypatch.setattr(module, "_local_art_crop_url", _fail)
        monkeypatch.setattr(module, "_fetch_scryfall_art_crop_url", _fail)

        assert module.get_or_compute_canonical_hash(canonical) == 999

    def test_uses_local_url_without_calling_the_rest_api(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical, art_crop_url="https://example.test/art.jpg")

        rest_calls: list[str] = []
        monkeypatch.setattr(
            module,
            "_fetch_scryfall_art_crop_url",
            lambda scryfall_id: rest_calls.append(scryfall_id) or "https://should-not-be-used.test",
        )
        monkeypatch.setattr(
            module, "_fetch_and_hash", lambda url: 42 if url == "https://example.test/art.jpg" else None
        )

        result = module.get_or_compute_canonical_hash(canonical)

        assert result == 42
        assert rest_calls == []
        canonical.refresh_from_db()
        assert canonical.image_hash == 42

    def test_falls_back_to_rest_when_no_local_url(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=0)  # no CanonicalPrintingMetadata at all

        monkeypatch.setattr(
            module, "_fetch_scryfall_art_crop_url", lambda scryfall_id: "https://example.test/fallback.jpg"
        )
        monkeypatch.setattr(
            module, "_fetch_and_hash", lambda url: 7 if url == "https://example.test/fallback.jpg" else None
        )

        result = module.get_or_compute_canonical_hash(canonical)

        assert result == 7

    def test_none_when_neither_source_has_a_url(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=0)

        monkeypatch.setattr(module, "_fetch_scryfall_art_crop_url", lambda scryfall_id: None)

        assert module.get_or_compute_canonical_hash(canonical) is None
