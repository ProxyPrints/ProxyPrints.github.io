"""
Tests for cardpicker.evidence_transfer - issue #473 PR-2's evidence transfer (folded with issue
#472). `checksum_pairing.card_sha256_checksum` is monkeypatched at `cardpicker.evidence_transfer`
(the name bound in THAT module's own namespace via its `from ... import ...`) rather than at
`cardpicker.checksum_pairing` itself, for the same "patch at the calling module" reason
`test_stage_e_dispatch.py`'s own module docstring gives for `fetch_card_image_bytes`/
`compute_card_evidence` - `Card.sha256_checksum` doesn't exist as a real model field on this
branch yet (it lands via a sibling PR on the same stacked base), so every sha256-pairing test here
exercises the tolerant `getattr`-based design by monkeypatching the read function directly, not by
setting a real field.
"""

from typing import Any

from cardpicker import evidence_transfer
from cardpicker.evidence_transfer import find_transfer_source, transfer_evidence
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_KEYS,
)
from cardpicker.models import ImageEvidence
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

FULL_MANIFEST = {key: f"{key}-v1" for key in MANIFEST_EXTRACTOR_KEYS}


def _stub_sha256(monkeypatch: Any, by_card_id: dict) -> None:
    monkeypatch.setattr(evidence_transfer, "card_sha256_checksum", lambda card: by_card_id.get(card.pk))


class TestFindTransferSourceHappyPath:
    def test_current_full_manifest_sibling_is_returned(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
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
            extractor_versions=FULL_MANIFEST,
        )

        assert find_transfer_source(target) is None

    def test_partial_manifest_sibling_is_not_a_source(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            extractor_versions={"fetch_health": "fetch-health-v2"},  # not the full manifest
        )

        assert find_transfer_source(target) is None


class TestFindTransferSourcePairingRule:
    def test_sha256_absent_on_both_falls_back_to_md5_only(self, db: Any, monkeypatch: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(card=sibling, content_hash=111, extractor_versions=FULL_MANIFEST)
        _stub_sha256(monkeypatch, {})  # neither card carries a sha256

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk

    def test_sha256_present_on_both_and_matching_transfers(self, db: Any, monkeypatch: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(card=sibling, content_hash=111, extractor_versions=FULL_MANIFEST)
        _stub_sha256(monkeypatch, {sibling.pk: "deadbeef", target.pk: "deadbeef"})

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk

    def test_sha256_present_on_only_one_side_falls_back_to_md5_only(self, db: Any, monkeypatch: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(card=sibling, content_hash=111, extractor_versions=FULL_MANIFEST)
        _stub_sha256(monkeypatch, {sibling.pk: "deadbeef"})  # target has none

        found = find_transfer_source(target)

        assert found is not None
        assert found.pk == sibling_evidence.pk

    def test_sha256_mismatch_is_a_loud_anomaly_and_skips_transfer(self, db: Any, monkeypatch: Any, caplog: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(card=sibling, content_hash=111, extractor_versions=FULL_MANIFEST)
        _stub_sha256(monkeypatch, {sibling.pk: "deadbeef", target.pk: "cafebabe"})

        with caplog.at_level("ERROR"):
            found = find_transfer_source(target)

        assert found is None
        assert any("sha256_checksum disagrees" in record.message for record in caplog.records)


class TestFindTransferSourceContentHashAssertion:
    def test_content_phash_mismatch_is_a_loud_anomaly_and_skips_transfer(
        self, db: Any, monkeypatch: Any, caplog: Any
    ) -> None:
        """An md5 match whose sibling evidence's own content_hash disagrees with the TARGET
        card's own content_phash is impossible for genuinely byte-identical files - a real
        anomaly, not a stale-sibling case (the sibling's own evidence IS current for ITS OWN
        card, per test_current_full_manifest_sibling_is_returned's own currency query - it's the
        cross-card comparison that disagrees)."""
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=222)  # different phash, same md5
        ImageEvidenceFactory(card=sibling, content_hash=111, extractor_versions=FULL_MANIFEST)
        _stub_sha256(monkeypatch, {})

        with caplog.at_level("ERROR"):
            found = find_transfer_source(target)

        assert found is None
        assert any("content_phash disagrees" in record.message for record in caplog.records)


class TestTransferEvidence:
    def test_copies_fields_and_stamps_target_values(self, db: Any) -> None:
        sibling = CardFactory(md5_checksum="abc123", content_phash=111)
        target = CardFactory(md5_checksum="abc123", content_phash=111)
        sibling_evidence = ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
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
            card=sibling, content_hash=111, extractor_versions=FULL_MANIFEST, symbol_phash=999
        )
        existing = ImageEvidenceFactory(card=target, content_hash=111, extractor_versions={})

        result = transfer_evidence(target, sibling_evidence, run_id="test-run")

        assert result.pk == existing.pk
        assert ImageEvidence.objects.filter(card_id=target.pk).count() == 1
