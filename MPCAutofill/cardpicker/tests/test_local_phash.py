"""
Local-first art-crop URL lookup (Stage B, 2026-07-19, docs/features/catalog-completion-plan.md):
`get_or_compute_canonical_hash` previously always hit Scryfall's live REST API per candidate for
the art-crop URL - measured as the dominant cost (93.6% of a 30-card Stage B wall-clock probe).
The same URL is already parsed from the weekly bulk-data import into
`CanonicalPrintingMetadata.art_crop_url` (see test_printing_metadata_import.py) - these tests
cover the local-first/REST-fallback ordering that change adds.
"""

import importlib

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


class TestContentPhashBandsMigrationMatchesLivePhashBands:
    """`0120_card_content_phash_bands.py`'s own `_content_phash_bands` duplicates this module's
    `content_phash_bands` rather than importing it (see that migration's own docstring for why:
    a migration is a dated historical artifact and must not depend on evolving app code). This
    pins the two to compute identically, so a future edit to either side that silently diverges
    the band encoding fails here instead of corrupting the retrieval guarantee between cards
    backfilled by the migration and cards hashed at ingest afterward."""

    def test_migration_and_live_bands_match_across_signed_and_unsigned_hashes(self):
        migration_module = importlib.import_module("cardpicker.migrations.0120_card_content_phash_bands")
        sample_hashes = [0, 1, -1, 0xFF, -0xFF, 0x7FFFFFFFFFFFFFFF, -0x8000000000000000, 0x123456789ABCDEF0]

        for phash in sample_hashes:
            assert migration_module._content_phash_bands(phash) == module.content_phash_bands(phash)
