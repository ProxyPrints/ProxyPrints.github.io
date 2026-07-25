"""
Tests for cardpicker.evidence_transfer - issue #473 PR-2's evidence transfer (folded with issue
#472). `Card.sha256_checksum` is a real model field on this branch (master already carries it via
migration 0084_card_checksums) - every sha256-pairing test here sets the real field via
`CardFactory(sha256_checksum=...)`, no monkeypatching needed.

TRANSFER-SOURCE INTEGRITY (Tron §8 gate condition): a sibling `ImageEvidence` row is only a valid
transfer source if its OWN stamped `md5_checksum` is non-null and equals the target card's live
md5 - every fixture below that builds a sibling INTENDED to be a valid transfer source stamps
`md5_checksum` on the `ImageEvidenceFactory` call explicitly (mirroring what a real
`persist_evidence`/`transfer_evidence` write would have stamped) rather than relying on the
`ImageEvidenceFactory`'s own default (`None`).
"""

from typing import Any

from django.test import override_settings

from cardpicker.evidence_transfer import (
    EVIDENCE_TRANSFER_ANONYMOUS_ID,
    EVIDENCE_TRANSFER_CONTENT_HASH_MISMATCH_SKIP_REASON,
    EVIDENCE_TRANSFER_SHA256_MISMATCH_SKIP_REASON,
    find_transfer_source,
    transfer_evidence,
)
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_KEYS,
)
from cardpicker.models import CardScanLog, ImageEvidence
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

FULL_MANIFEST = {key: f"{key}-v1" for key in MANIFEST_EXTRACTOR_KEYS}


class TestFindTransferSourceHappyPath:
    def test_current_full_manifest_sibling_is_returned(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions=FULL_MANIFEST,
            symbol_phash=999,
        )

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk

    def test_no_md5_on_target_returns_none(self, db: Any) -> None:
        target = CardFactory(md5_checksum=None, content_phash=111)
        assert find_transfer_source(target) is None

    def test_no_content_phash_on_target_returns_none(self, db: Any) -> None:
        target = CardFactory(md5_checksum="abc123", content_phash=None)
        assert find_transfer_source(target) is None

    def test_no_sibling_at_all_falls_through_to_none(self, db: Any) -> None:
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        assert find_transfer_source(target) is None

    def test_sibling_evidence_not_current_for_its_own_card_is_not_a_source(self, db: Any) -> None:
        """A sibling whose OWN evidence row has gone stale (content_hash no longer matches ITS
        OWN card's live content_phash) is never a transfer source, regardless of md5 agreement."""
        sibling = CardFactory(md5_checksum="abc123", content_phash=222)  # sibling's image changed
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,  # stale - sibling's own card.content_phash is now 222
            md5_checksum="abc123",
            extractor_versions=FULL_MANIFEST,
        )

        assert find_transfer_source(target) is None

    def test_partial_manifest_sibling_is_not_a_source(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions={"fetch_health": "fetch-health-v2"},  # not the full manifest
        )

        assert find_transfer_source(target) is None


class TestFindTransferSourceIntegrity:
    """Tron §8 gate condition 4 (2026-07-25): eligibility requires the source evidence row's own
    stamped md5_checksum to be NOT NULL and equal to the target card's - a sibling row that matches
    on md5 only through the Card-level join (never through its own stamp) must never mint a fresh
    stamp on the copy. Null-tolerance stays a CURRENCY-only rule (image_evidence.
    current_evidence_queryset), never a transfer-source-eligibility one."""

    def test_source_with_null_stamped_md5_is_not_eligible(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        # legacy row: content_hash is current, but it never got the md5 stamp at all.
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum=None,
            extractor_versions=FULL_MANIFEST,
        )

        assert find_transfer_source(target) is None

    def test_source_with_disagreeing_stamped_md5_is_not_eligible(self, db: Any) -> None:
        """Not reachable via the outer `card__md5_checksum=card.md5_checksum` filter today (the
        sibling's own card carries the same md5 the target does, by construction), but a
        stamped-vs-card-live disagreement on the SOURCE's own row is exactly the case the strict
        (non-null-tolerant) filter is there to catch if the two data points were ever able to
        diverge - proven directly against the queryset rather than assumed unreachable."""
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="stale-different-md5",
            extractor_versions=FULL_MANIFEST,
        )

        assert find_transfer_source(target) is None


class TestFindTransferSourcePairingRule:
    def test_sha256_absent_on_both_falls_back_to_md5_only(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum=None)
        target = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum=None)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST
        )

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk

    def test_sha256_present_on_both_and_matching_transfers(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum="deadbeef")
        target = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum="deadbeef")
        sibling_evidence = ImageEvidenceFactory(
            card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST
        )

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk

    def test_sha256_present_on_only_one_side_falls_back_to_md5_only(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum="deadbeef")
        target = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum=None)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST
        )

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk

    def test_sha256_mismatch_is_a_loud_anomaly_and_skips_transfer(self, db: Any, caplog: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum="deadbeef")
        target = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum="cafebabe")
        ImageEvidenceFactory(card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST)

        with caplog.at_level("ERROR"):
            found = find_transfer_source(target)

        assert found is None
        assert any("sha256_checksum disagrees" in record.message for record in caplog.records)

    def test_sha256_mismatch_writes_a_durable_card_scan_log_anomaly_row(self, db: Any) -> None:
        """Tron §8 gate condition 5 (2026-07-25): the ERROR log alone isn't queryable after a
        218k-card run - the anomaly must also land as a durable, per-card CardScanLog row."""
        sibling = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum="deadbeef")
        target = CardFactory(md5_checksum="abc123", content_phash=111, sha256_checksum="cafebabe")
        ImageEvidenceFactory(card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST)

        find_transfer_source(target)

        log = CardScanLog.objects.get(card=target, anonymous_id=EVIDENCE_TRANSFER_ANONYMOUS_ID)
        assert log.skip_reason == EVIDENCE_TRANSFER_SHA256_MISMATCH_SKIP_REASON


class TestFindTransferSourceContentHashAssertion:
    def test_content_phash_mismatch_is_a_loud_anomaly_and_skips_transfer(self, db: Any, caplog: Any) -> None:
        """An md5 match whose sibling evidence's own content_hash disagrees with the TARGET
        card's own content_phash is impossible for genuinely byte-identical files - a real
        anomaly, not a stale-sibling case (the sibling's own evidence IS current for ITS OWN
        card, per test_current_full_manifest_sibling_is_returned's own currency query - it's the
        cross-card comparison that disagrees)."""
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=222)  # different phash, same md5
        ImageEvidenceFactory(card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST)

        with caplog.at_level("ERROR"):
            found = find_transfer_source(target)

        assert found is None
        assert any("content_phash disagrees" in record.message for record in caplog.records)

    def test_content_phash_mismatch_writes_a_durable_card_scan_log_anomaly_row(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=222)
        ImageEvidenceFactory(card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST)

        find_transfer_source(target)

        log = CardScanLog.objects.get(card=target, anonymous_id=EVIDENCE_TRANSFER_ANONYMOUS_ID)
        assert log.skip_reason == EVIDENCE_TRANSFER_CONTENT_HASH_MISMATCH_SKIP_REASON


class TestFindTransferSourceKillSwitch:
    """Tron §8 gate condition 6 (2026-07-25): settings.STAGE_C_EVIDENCE_TRANSFER_ENABLED."""

    def test_disabled_returns_none_even_with_an_eligible_sibling(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST)

        with override_settings(STAGE_C_EVIDENCE_TRANSFER_ENABLED=False):
            assert find_transfer_source(target) is None

    def test_default_is_enabled(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST
        )

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk


class TestTransferEvidence:
    def test_copies_fields_and_stamps_target_values(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions=FULL_MANIFEST,
            symbol_phash=999,
            collector_line_raw_text="M15 123/456",
            collector_line_set_code="M15",
            collector_line_collector_number="123",
        )

        result = transfer_evidence(target, sibling_evidence, run_id="test-run")

        assert result.card_id == target.pk
        assert result.content_hash == 111
        assert result.symbol_phash == 999
        assert result.collector_line_raw_text == "M15 123/456"
        assert result.extractor_versions == FULL_MANIFEST
        assert result.md5_checksum == "abc123"
        assert result.transferred is True
        assert result.transferred_from_card_id == sibling.pk
        assert result.run_id == "test-run"

        # Persisted, not just returned.
        stored = ImageEvidence.objects.get(card_id=target.pk, content_hash=111)
        assert stored.transferred is True
        assert stored.symbol_phash == 999

    def test_get_or_create_updates_an_existing_row_in_place(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling, content_hash=111, md5_checksum="abc123", extractor_versions=FULL_MANIFEST, symbol_phash=999
        )
        existing = ImageEvidenceFactory(card=target, content_hash=111, extractor_versions={})

        result = transfer_evidence(target, sibling_evidence, run_id="test-run")

        assert result.pk == existing.pk
        assert ImageEvidence.objects.filter(card_id=target.pk).count() == 1
