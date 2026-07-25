"""
Tests for `ocr_engine_ab` (issue #423's real-image A/B validation command - see that command's
own module docstring for the full contract). Fetches are always mocked here - this test suite
never makes a real network call, matching `test_run_image_evidence_cohort.py`'s own convention
(`_stub_pools`/stubbed fetch step) of never spawning genuine I/O for a command test. Real
pytesseract runs throughout (tesseract is installed in CI - see CLAUDE.md's tooling-rules entry);
the tesserocr side runs for real too when the optional dependency happens to be installed, and
transparently falls back to pytesseract (silently, per local_ocr.py's own failure-tolerance
contract) when it isn't - either way, this suite is about the COMMAND's own dispatch/argument/
reporting/ledger behavior, not about proving engine parity (that's local_ocr.py's own test file's
job, plus this command's real intended use as a live diagnostic tool).

`@pytest.mark.django_db(transaction=True)` is used for every test that reaches `handle()`'s real
fetch `ThreadPoolExecutor` - matching `test_run_image_evidence_cohort.py`'s own documented reason
(a worker THREAD's own DB connection can't see data committed only inside the outer test's atomic
savepoint under the plain `django_db` marker; `transaction=True` swaps in real commit-and-truncate
isolation instead).
"""

from io import BytesIO
from typing import Any, Optional

import pytest
from PIL import Image, ImageDraw

from django.core.management import call_command

from cardpicker.management.commands import ocr_engine_ab as ab_command
from cardpicker.models import ImageEvidence, PilotRunLedger
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory


def _fake_card_jpeg_bytes(text: str = "158/287 R MOM EN") -> bytes:
    """A small synthetic "card" image with collector-line-shaped text placed roughly where
    `local_ocr.DEFAULT_CROP_BOX`'s own bottom band would crop it - large enough that the
    fractional crop box never degenerates to a zero-area region (see that constant's own
    module comment for the exact fractions)."""
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 730), text, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _stub_fetch_bytes_factory(image_bytes: Optional[bytes]):
    def _stub(card: Any, dpi: Any = None) -> Optional[bytes]:
        return image_bytes

    return _stub


@pytest.mark.django_db
class TestArgumentHandling:
    def test_sample_defaults_to_200(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
        captured: dict[str, Any] = {}

        def _fake_run_ab(sample: int, seed: Optional[int], stdout_write: Any) -> "ab_command._AbSummary":
            captured["sample"] = sample
            captured["seed"] = seed
            return ab_command._AbSummary(sample_requested=sample, sample_drawn=0, seed=seed or 0)

        monkeypatch.setattr(ab_command, "run_ab", _fake_run_ab)
        call_command("ocr_engine_ab")
        assert captured["sample"] == ab_command.DEFAULT_SAMPLE

    def test_explicit_sample_and_seed_are_forwarded(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}

        def _fake_run_ab(sample: int, seed: Optional[int], stdout_write: Any) -> "ab_command._AbSummary":
            captured["sample"] = sample
            captured["seed"] = seed
            return ab_command._AbSummary(sample_requested=sample, sample_drawn=0, seed=seed or 0)

        monkeypatch.setattr(ab_command, "run_ab", _fake_run_ab)
        call_command("ocr_engine_ab", sample=5, seed=42)
        assert captured["sample"] == 5
        assert captured["seed"] == 42

    def test_negative_sample_is_clamped_to_zero(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}

        def _fake_run_ab(sample: int, seed: Optional[int], stdout_write: Any) -> "ab_command._AbSummary":
            captured["sample"] = sample
            return ab_command._AbSummary(sample_requested=sample, sample_drawn=0, seed=0)

        monkeypatch.setattr(ab_command, "run_ab", _fake_run_ab)
        call_command("ocr_engine_ab", sample=-5)
        assert captured["sample"] == 0


@pytest.mark.django_db
class TestLedgerConvention:
    def test_ledger_row_is_always_dry_run(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            ab_command,
            "run_ab",
            lambda sample, seed, stdout_write: ab_command._AbSummary(sample_requested=sample, sample_drawn=0, seed=0),
        )
        call_command("ocr_engine_ab", sample=0)
        ledger = PilotRunLedger.objects.get(command="ocr_engine_ab")
        assert ledger.dry_run is True
        assert ledger.status == PilotRunLedger.Status.COMPLETED

    def test_command_never_writes_to_image_evidence(self, monkeypatch: pytest.MonkeyPatch):
        card = CardFactory(content_phash=123)
        ImageEvidenceFactory(card=card, content_hash=123, extractor_versions={"collector_line_ocr": 1})
        before_count = ImageEvidence.objects.count()

        monkeypatch.setattr(ab_command, "fetch_card_image_bytes", _stub_fetch_bytes_factory(_fake_card_jpeg_bytes()))
        call_command("ocr_engine_ab", sample=1, seed=1)

        assert ImageEvidence.objects.count() == before_count

    def test_ledger_records_a_failure_reason_on_exception(self, monkeypatch: pytest.MonkeyPatch):
        def _boom(sample: int, seed: Optional[int], stdout_write: Any) -> Any:
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(ab_command, "run_ab", _boom)
        with pytest.raises(RuntimeError):
            call_command("ocr_engine_ab", sample=0)
        ledger = PilotRunLedger.objects.get(command="ocr_engine_ab")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert "simulated failure" in ledger.counters["failure_reason"]


@pytest.mark.django_db(transaction=True)
class TestEndToEndWithMockedFetch:
    def test_no_candidate_cards_reports_zero_sample(self, capsys: pytest.CaptureFixture):
        call_command("ocr_engine_ab", sample=10, seed=1)
        out = capsys.readouterr().out
        assert "sample_drawn=0" in out
        ledger = PilotRunLedger.objects.get(command="ocr_engine_ab")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["n"] == 0

    def test_fetch_failure_is_counted_not_crashed(self, monkeypatch: pytest.MonkeyPatch):
        card = CardFactory(content_phash=999)
        ImageEvidenceFactory(card=card, content_hash=999, extractor_versions={"collector_line_ocr": 1})

        monkeypatch.setattr(ab_command, "fetch_card_image_bytes", _stub_fetch_bytes_factory(None))
        call_command("ocr_engine_ab", sample=1, seed=1)

        ledger = PilotRunLedger.objects.get(command="ocr_engine_ab")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["fetch_failures"] == 1
        assert ledger.counters["n"] == 0

    def test_full_run_produces_a_per_card_result_and_stored_vs_fresh_comparison(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        card = CardFactory(content_phash=555)
        ImageEvidenceFactory(
            card=card,
            content_hash=555,
            extractor_versions={"collector_line_ocr": 1},
            collector_line_raw_text="158/287 R MOM EN",
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        monkeypatch.setattr(ab_command, "fetch_card_image_bytes", _stub_fetch_bytes_factory(_fake_card_jpeg_bytes()))
        call_command("ocr_engine_ab", sample=1, seed=1)

        out = capsys.readouterr().out
        assert str(card.pk) in out
        ledger = PilotRunLedger.objects.get(command="ocr_engine_ab")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["n"] == 1
        assert ledger.counters["sample_drawn"] == 1
        # every real ImageEvidence write from this run must be exactly zero (see
        # TestLedgerConvention.test_command_never_writes_to_image_evidence for the direct check;
        # this asserts the ledger's own counters reflect a genuine comparison happened).
        assert ledger.counters["byte_identical_count"] in (0, 1)

    def test_reproducible_sampling_with_the_same_seed(self, monkeypatch: pytest.MonkeyPatch):
        cards = [CardFactory(content_phash=n) for n in range(2000, 2010)]
        for card in cards:
            ImageEvidenceFactory(
                card=card, content_hash=card.content_phash, extractor_versions={"collector_line_ocr": 1}
            )

        seen_ids = []

        def _record_and_fetch(card: Any, dpi: Any = None) -> Optional[bytes]:
            seen_ids.append(card.pk)
            return None  # fetch_failed is fine - only sampling identity is under test here

        monkeypatch.setattr(ab_command, "fetch_card_image_bytes", _record_and_fetch)
        call_command("ocr_engine_ab", sample=3, seed=7)
        first_run_ids = sorted(seen_ids)

        seen_ids.clear()
        call_command("ocr_engine_ab", sample=3, seed=7)
        second_run_ids = sorted(seen_ids)

        assert first_run_ids == second_run_ids
        assert len(first_run_ids) == 3
