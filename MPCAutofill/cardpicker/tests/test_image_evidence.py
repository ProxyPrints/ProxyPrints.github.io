"""
Stage C substrate tests (docs/features/catalog-completion-plan.md, task #145): the per-card
callable extraction unit + persistence split, the fetch_health extractor riding along as
end-to-end proof, and the reconciliation ledger (task #155). No network - `fetch_card_image`
is monkeypatched throughout.
"""

import pytest

import cardpicker.image_evidence as module
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_evidence import (
    FETCH_HEALTH_EXTRACTOR_VERSION,
    ExtractionResult,
    build_reconciliation_report,
    extract_card_evidence,
    persist_evidence,
)
from cardpicker.models import CardScanLog, ImageEvidence
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CardFactory,
    SourceFactory,
)

_SHARED_FACTORIES = [CardFactory, SourceFactory, CanonicalArtistFactory, CanonicalExpansionFactory]


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


class TestExtractCardEvidence:
    def test_successful_fetch_marks_fetch_ok_and_records_no_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())

        result = extract_card_evidence(card)

        assert result.card_id == card.pk
        assert result.content_hash == 12345
        assert result.fields == {"fetch_ok": True, "fetch_error_class": ""}
        assert result.extractor_versions == {"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION}
        assert result.skip_reasons == {}

    def test_failed_fetch_marks_fetch_not_ok_and_records_a_named_skip(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        result = extract_card_evidence(card)

        assert result.fields == {"fetch_ok": False, "fetch_error_class": "fetch_failed"}
        # extractor_versions is still set - fetch_health ran to completion, it just found a
        # negative result. Only a crash omits this key (see ExtractionResult's docstring).
        assert result.extractor_versions == {"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION}
        assert result.skip_reasons == {"fetch_health": "fetch_failed"}

    def test_null_content_phash_surfaces_as_none(self, db, monkeypatch):
        card = CardFactory(content_phash=None)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())

        result = extract_card_evidence(card)

        assert result.content_hash is None

    def test_lockout_error_propagates_not_swallowed(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)

        def _raise_lockout(card, dpi=None):
            raise GoogleFetchLockoutError("locked out")

        monkeypatch.setattr(module, "fetch_card_image", _raise_lockout)

        with pytest.raises(GoogleFetchLockoutError):
            extract_card_evidence(card)

    def test_no_db_writes_happen(self, db, monkeypatch):
        card = CardFactory(content_phash=12345)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: object())

        extract_card_evidence(card)

        assert ImageEvidence.objects.count() == 0
        assert CardScanLog.objects.count() == 0


class TestPersistEvidence:
    def test_writes_a_new_row(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": True, "fetch_error_class": ""},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
        )

        evidence = persist_evidence(result, run_id="run-1")

        assert evidence is not None
        assert evidence.card_id == card.pk
        assert evidence.content_hash == 999
        assert evidence.fetch_ok is True
        assert evidence.run_id == "run-1"
        assert evidence.extractor_versions == {"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION}

    def test_null_content_hash_refuses_to_write(self, db):
        card = CardFactory(content_phash=None)
        result = ExtractionResult(card_id=card.pk, content_hash=None, fields={"fetch_ok": True})

        evidence = persist_evidence(result)

        assert evidence is None
        assert ImageEvidence.objects.count() == 0

    def test_rerun_against_same_card_and_hash_updates_in_place(self, db):
        card = CardFactory(content_phash=999)
        first = persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                skip_reasons={"fetch_health": "fetch_failed"},
            )
        )
        second = persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={"fetch_ok": True, "fetch_error_class": ""},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )

        assert ImageEvidence.objects.count() == 1
        assert first is not None
        assert second is not None
        assert second.pk == first.pk
        assert second.fetch_ok is True

    def test_different_extractors_merge_without_clobbering(self, db):
        card = CardFactory(content_phash=999)
        persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={"fetch_ok": True, "fetch_error_class": ""},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )

        evidence = persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=999,
                fields={},
                extractor_versions={"some_future_extractor": "v1"},
            )
        )

        assert evidence is not None
        assert evidence.extractor_versions == {
            "fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION,
            "some_future_extractor": "v1",
        }
        # fetch_health's own fields survive an unrelated extractor's pass untouched.
        assert evidence.fetch_ok is True

    def test_different_content_hash_creates_a_new_row_not_overwrite(self, db):
        card = CardFactory(content_phash=1)
        persist_evidence(ExtractionResult(card_id=card.pk, content_hash=1, fields={"fetch_ok": True}))
        persist_evidence(ExtractionResult(card_id=card.pk, content_hash=2, fields={"fetch_ok": False}))

        assert ImageEvidence.objects.filter(card=card).count() == 2

    def test_skip_reasons_write_a_card_scan_log_row(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            skip_reasons={"fetch_health": "fetch_failed"},
        )

        persist_evidence(result, run_id="run-1")

        log = CardScanLog.objects.get(card=card)
        assert log.anonymous_id == "fetch_health"
        assert log.skip_reason == "fetch_failed"
        assert log.run_id == "run-1"

    def test_no_skip_reasons_writes_no_card_scan_log_row(self, db):
        card = CardFactory(content_phash=999)
        result = ExtractionResult(
            card_id=card.pk,
            content_hash=999,
            fields={"fetch_ok": True, "fetch_error_class": ""},
            extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
        )

        persist_evidence(result)

        assert CardScanLog.objects.count() == 0


class TestBuildReconciliationReport:
    def test_all_voted(self, db):
        cards = [CardFactory(content_phash=i) for i in range(1, 4)]
        for card in cards:
            persist_evidence(
                ExtractionResult(
                    card_id=card.pk,
                    content_hash=card.content_phash,
                    fields={"fetch_ok": True},
                    extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                )
            )

        report = build_reconciliation_report("fetch_health", [c.pk for c in cards])

        assert report.attempted == 3
        assert report.voted == 3
        assert report.skipped_by_reason == {}
        assert report.dropped == 0
        assert report.is_consistent()

    def test_mixed_voted_skipped_dropped(self, db):
        voted_card = CardFactory(content_phash=1)
        skipped_card = CardFactory(content_phash=2)
        dropped_card = CardFactory(content_phash=3)  # attempted but never persisted at all

        persist_evidence(
            ExtractionResult(
                card_id=voted_card.pk,
                content_hash=1,
                fields={"fetch_ok": True},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )
        persist_evidence(
            ExtractionResult(
                card_id=skipped_card.pk,
                content_hash=2,
                fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                skip_reasons={"fetch_health": "fetch_failed"},
            )
        )

        report = build_reconciliation_report("fetch_health", [voted_card.pk, skipped_card.pk, dropped_card.pk])

        assert report.attempted == 3
        assert report.voted == 1
        assert report.skipped_by_reason == {"fetch_failed": 1}
        assert report.dropped == 1
        assert report.is_consistent()

    def test_run_id_scopes_the_skip_side(self, db):
        card = CardFactory(content_phash=1)
        persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=1,
                fields={"fetch_ok": False, "fetch_error_class": "fetch_failed"},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
                skip_reasons={"fetch_health": "fetch_failed"},
            ),
            run_id="run-a",
        )

        report_matching_run = build_reconciliation_report("fetch_health", [card.pk], run_id="run-a")
        report_other_run = build_reconciliation_report("fetch_health", [card.pk], run_id="run-b")

        assert report_matching_run.skipped_by_reason == {"fetch_failed": 1}
        assert report_other_run.skipped_by_reason == {}
        # the card still "ran" (extractor_versions is unscoped by run_id) but with no matching
        # skip row for run-b, it counts as voted rather than dropped or skipped.
        assert report_other_run.voted == 1

    def test_different_extractor_name_is_independent(self, db):
        card = CardFactory(content_phash=1)
        persist_evidence(
            ExtractionResult(
                card_id=card.pk,
                content_hash=1,
                fields={"fetch_ok": True},
                extractor_versions={"fetch_health": FETCH_HEALTH_EXTRACTOR_VERSION},
            )
        )

        report = build_reconciliation_report("some_other_extractor", [card.pk])

        assert report.attempted == 1
        assert report.voted == 0
        assert report.dropped == 1
        assert report.is_consistent()
