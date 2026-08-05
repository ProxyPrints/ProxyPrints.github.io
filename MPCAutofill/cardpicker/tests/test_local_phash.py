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


class TestCanonicalHashBackfill:
    """Completes the local phash reference corpus (docs/features/catalog-completion-plan.md):
    the one-time backfill for existing image_hash=0 CanonicalCard rows, mirroring
    run_content_phash_backfill's checkpoint discipline (test_local_identify_printing_tags.py's
    TestContentPhashBackfill) for this table instead of Card."""

    def test_hashes_every_unhashed_canonical_and_persists_the_result(self, db, monkeypatch):
        canonical_a = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical_a, art_crop_url="https://example.test/a.jpg")
        canonical_b = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical_b, art_crop_url="https://example.test/b.jpg")
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 42)

        result = module.run_canonical_hash_backfill(nice=False)

        assert result.total_backlog == 2
        assert result.total_candidates == 2
        assert result.hashed == 2
        assert result.failed == 0
        assert result.skipped_no_local_url == 0
        canonical_a.refresh_from_db()
        canonical_b.refresh_from_db()
        assert canonical_a.image_hash == 42
        assert canonical_b.image_hash == 42

    def test_already_hashed_canonicals_are_not_touched(self, db, monkeypatch):
        already_hashed = CanonicalCardFactory(image_hash=99)
        CanonicalPrintingMetadataFactory(canonical_card=already_hashed, art_crop_url="https://example.test/a.jpg")
        called: list[str] = []
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: called.append(url) or 42)

        result = module.run_canonical_hash_backfill(nice=False)

        assert result.total_backlog == 0
        assert result.total_candidates == 0
        assert called == []
        already_hashed.refresh_from_db()
        assert already_hashed.image_hash == 99

    def test_missing_local_url_is_skipped_not_fetched_remotely(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=0)  # no CanonicalPrintingMetadata row at all

        def _fail(*args: object, **kwargs: object) -> None:
            raise AssertionError("should never be called - allow_remote defaults to False")

        monkeypatch.setattr(module, "_fetch_scryfall_art_crop_url", _fail)
        monkeypatch.setattr(module, "_fetch_and_hash", _fail)

        result = module.run_canonical_hash_backfill(nice=False)

        assert result.hashed == 0
        assert result.skipped_no_local_url == 1
        canonical.refresh_from_db()
        assert canonical.image_hash == 0

    def test_allow_remote_falls_back_to_rest_when_no_local_url(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=0)

        monkeypatch.setattr(
            module, "_fetch_scryfall_art_crop_url", lambda scryfall_id: "https://example.test/fallback.jpg"
        )
        monkeypatch.setattr(
            module, "_fetch_and_hash", lambda url: 7 if url == "https://example.test/fallback.jpg" else None
        )

        result = module.run_canonical_hash_backfill(nice=False, allow_remote=True)

        assert result.hashed == 1
        assert result.skipped_no_local_url == 0
        canonical.refresh_from_db()
        assert canonical.image_hash == 7

    def test_a_failed_hash_stays_at_sentinel_and_is_counted_as_failed(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical, art_crop_url="https://example.test/a.jpg")
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: None)

        result = module.run_canonical_hash_backfill(nice=False)

        assert result.hashed == 0
        assert result.failed == 1
        canonical.refresh_from_db()
        assert canonical.image_hash == 0

    def test_dry_run_writes_nothing(self, db, monkeypatch):
        canonical = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical, art_crop_url="https://example.test/a.jpg")
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 42)

        result = module.run_canonical_hash_backfill(dry_run=True, nice=False)

        assert result.hashed == 1
        canonical.refresh_from_db()
        assert canonical.image_hash == 0

    def test_a_second_invocation_only_processes_what_the_first_missed(self, db, monkeypatch):
        # simulates a kill mid-backfill and a plain re-invocation - the image_hash=0 filter is
        # the checkpoint, no separate --resume flag needed.
        already_hashed = CanonicalCardFactory(image_hash=42)
        CanonicalPrintingMetadataFactory(canonical_card=already_hashed, art_crop_url="https://example.test/a.jpg")
        still_unhashed = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=still_unhashed, art_crop_url="https://example.test/b.jpg")
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 7)

        result = module.run_canonical_hash_backfill(nice=False)

        assert result.total_candidates == 1
        already_hashed.refresh_from_db()
        still_unhashed.refresh_from_db()
        assert already_hashed.image_hash == 42  # untouched
        assert still_unhashed.image_hash == 7  # newly hashed

    def test_limit_narrows_the_run_but_reports_the_full_backlog(self, db, monkeypatch):
        for _ in range(3):
            canonical = CanonicalCardFactory(image_hash=0)
            CanonicalPrintingMetadataFactory(canonical_card=canonical, art_crop_url="https://example.test/x.jpg")
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 1)

        result = module.run_canonical_hash_backfill(nice=False, limit=1)

        assert result.total_backlog == 3
        assert result.total_candidates == 1


class TestCanonicalHashBackfillCommandCLI:
    """Mirrors TestBackfillCommandCLI (test_local_identify_printing_tags.py) - exercises the
    real add_arguments()/parser path, not just run_canonical_hash_backfill() directly."""

    def test_real_cli_invocation_with_no_flags_at_all(self, db, monkeypatch):
        from django.core.management import call_command

        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 1)
        call_command("local_backfill_canonical_hash", "--limit=0")

    def test_skip_checks_flag_does_not_conflict_with_djangos_own(self, db, monkeypatch):
        from django.core.management import call_command

        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 1)
        call_command("local_backfill_canonical_hash", "--skip-checks", "--limit=0")

    def test_dry_run_flag_reports_without_writing(self, db, monkeypatch, capsys):
        from django.core.management import call_command

        canonical = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical, art_crop_url="https://example.test/a.jpg")
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 42)

        call_command("local_backfill_canonical_hash", "--skip-checks", "--dry-run")
        captured = capsys.readouterr()

        assert "Dry run - nothing written." in captured.out
        canonical.refresh_from_db()
        assert canonical.image_hash == 0

    def test_allow_remote_flag_wires_through(self, db, monkeypatch, capsys):
        from django.core.management import call_command

        canonical = CanonicalCardFactory(image_hash=0)  # no local metadata row

        monkeypatch.setattr(
            module, "_fetch_scryfall_art_crop_url", lambda scryfall_id: "https://example.test/fallback.jpg"
        )
        monkeypatch.setattr(module, "_fetch_and_hash", lambda url: 9)

        call_command("local_backfill_canonical_hash", "--skip-checks", "--allow-remote")
        captured = capsys.readouterr()

        assert "--allow-remote=True" in captured.out
        canonical.refresh_from_db()
        assert canonical.image_hash == 9


class TestCanonicalHashBackfillPipelineOutOfOrder:
    """Same proof as TestPipelinedBackfillOutOfOrder (test_local_identify_printing_tags.py) for
    this backfill's own pipeline: completion order isn't submission order once more than one
    worker thread is in flight, and persistence must be keyed by which future belongs to which
    canonical, not by completion position."""

    def test_persists_correctly_when_completion_order_differs_from_submission_order(self, db, monkeypatch):
        import time

        canonical_a = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical_a, art_crop_url="https://example.test/a.jpg")
        canonical_b = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical_b, art_crop_url="https://example.test/b.jpg")
        canonical_c = CanonicalCardFactory(image_hash=0)
        CanonicalPrintingMetadataFactory(canonical_card=canonical_c, art_crop_url="https://example.test/c.jpg")

        # canonical_a is submitted first (lower pk, since the queryset orders by pk) but its
        # fetch is made to finish LAST - proves the persisted result is keyed by which canonical
        # the future belongs to, not by submission/completion position.
        delays = {
            "https://example.test/a.jpg": 0.3,
            "https://example.test/b.jpg": 0.05,
            "https://example.test/c.jpg": 0.15,
        }
        hashes = {
            "https://example.test/a.jpg": 111,
            "https://example.test/b.jpg": 222,
            "https://example.test/c.jpg": 333,
        }

        def slow_variable_hash(url: str) -> int:
            time.sleep(delays[url])
            return hashes[url]

        monkeypatch.setattr(module, "_fetch_and_hash", slow_variable_hash)

        # workers=3 keeps all three in flight simultaneously (window_size = max(batch_size *
        # queue_depth_batches, workers) = max(1, 3) = 3), so completion order is purely
        # determined by the delays above (b, then c, then a) - the reverse of submission order.
        result = module.run_canonical_hash_backfill(nice=False, batch_size=1, workers=3, queue_depth_batches=1)

        assert result.hashed == 3
        assert result.failed == 0
        canonical_a.refresh_from_db()
        canonical_b.refresh_from_db()
        canonical_c.refresh_from_db()
        assert canonical_a.image_hash == 111
        assert canonical_b.image_hash == 222
        assert canonical_c.image_hash == 333
