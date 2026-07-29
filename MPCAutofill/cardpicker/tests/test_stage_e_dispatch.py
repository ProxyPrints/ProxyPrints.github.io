"""
Tests for cardpicker.stage_e_dispatch - Stage E Phase 2's streaming dispatch loop
(docs/proposals/stage-e-streaming.md, docs/features/stage-e-operations.md's "Phase 2" section).

No network calls, no live image fetch - `fetch_card_image_bytes`/`compute_card_evidence` are
monkeypatched at their SOURCE module (`cardpicker.image_cdn_fetch`/`cardpicker.image_evidence`),
never at `cardpicker.stage_e_dispatch` itself, because `_run_stage_c` imports both lazily (inside
the function body, module docstring's own "avoid a hard import-time dependency" convention) - a
patch applied to the source module before the call is what a fresh `from ... import ...` inside the
function body actually observes. `persist_evidence` itself is left REAL (unmocked) in every test
below - it's a small, already-tested, non-network function, and exercising it for real is what
proves ImageEvidence rows actually land, matching `_evidence()`'s own convention in
`test_local_calculate_verdicts.py`.
"""

import io
import threading
import time
from typing import Any

import psycopg2
import pytest
from PIL import Image

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from cardpicker import stage_e_dispatch
from cardpicker.harvest_fetch_limiter import GoogleFetchLockoutError
from cardpicker.image_evidence import ExtractionResult
from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
    MANIFEST_EXTRACTOR_KEYS,
)
from cardpicker.management.commands.stream_backstop_sweep import (
    _next_stage_d_backlog_ids,
)
from cardpicker.models import (
    CardPrintingTag,
    EnvelopeTrip,
    ImageEvidence,
    PilotRunLedger,
    PrintingTagStatus,
    StageESweepCursor,
    StageEThrottleCounter,
    VoteSource,
)
from cardpicker.operating_envelope import (
    FETCH_FAILURE_WINDOW,
    acknowledge_trip,
    check_envelope,
    current_trip,
)
from cardpicker.stage_e_concurrency import _LOCK_NAMESPACE
from cardpicker.stage_e_dispatch import (
    SweepLapTracker,
    _cursor_chunk_walk,
    _FetchOutcomeWindow,
    _select_micro_batch,
    dispatch_for_card,
    dispatch_micro_batch,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CardFactory,
    ImageEvidenceFactory,
)

STREAMING_ON = override_settings(STAGE_E_STREAMING_ENABLED=True)


@pytest.fixture(autouse=True)
def _reset_fetch_failure_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rolling fetch-outcome window (`stage_e_dispatch._window`) is a process-local module
    singleton spanning a worker process's whole uptime by design (module docstring) - reset it
    before every test in this file so no test observes another's fetch outcomes."""
    monkeypatch.setattr(stage_e_dispatch, "_window", _FetchOutcomeWindow())


def _png_bytes() -> bytes:
    """A tiny, genuinely-decodable PNG - `_run_stage_c` calls the real `PIL.Image.open` on
    whatever `fetch_card_image_bytes` returns before handing it to `compute_card_evidence` (which
    is separately stubbed below), so this needs to be real image bytes, not an arbitrary literal."""
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


def _stub_compute_card_evidence_ok(**field_overrides: Any):
    """Builds a stand-in for `cardpicker.image_evidence.compute_card_evidence` that returns an
    `ExtractionResult` carrying every Stage C manifest key (so the resume filter treats the card as
    fully processed after one pass) plus whatever join-key-relevant fields the caller wants to
    steer Stage D's own verdict."""

    def _stub(
        card_id: int,
        content_hash,
        image,
        fetch_latency_ms=0.0,
        profile=None,
        short_circuit=None,
        known_set_codes=None,
        artist_lexicon=None,
        printing_artist_lookup=None,
        md5_checksum=None,
        sha256_checksum=None,
    ):
        fields = {
            "fetch_ok": True,
            "collector_line_raw_text": "",
            "collector_line_set_code": "",
            "collector_line_collector_number": "",
            "legal_line_proxy_marker_detected": False,
            "symbol_phash": None,
        }
        fields.update(field_overrides)
        return ExtractionResult(
            card_id=card_id,
            content_hash=content_hash,
            fields=fields,
            extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
        )

    return _stub


def _install_stage_c_stub(monkeypatch: pytest.MonkeyPatch, fetch_result: Any = b"", **field_overrides: Any) -> None:
    import cardpicker.image_cdn_fetch as image_cdn_fetch_module
    import cardpicker.image_evidence as image_evidence_module

    if callable(fetch_result):
        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", fetch_result)
    else:
        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: fetch_result)
    monkeypatch.setattr(
        image_evidence_module, "compute_card_evidence", _stub_compute_card_evidence_ok(**field_overrides)
    )


class TestDefaultOff:
    def test_disabled_by_default_returns_disabled_status(self, db: Any) -> None:
        outcome = dispatch_micro_batch(card_ids=[1])
        assert outcome.status == "disabled"
        assert PilotRunLedger.objects.count() == 0
        assert EnvelopeTrip.objects.count() == 0

    def test_dispatch_for_card_is_a_silent_no_op_when_disabled(self, db: Any) -> None:
        card = CardFactory(content_phash=42)
        dispatch_for_card(card.pk, "card-create")
        assert PilotRunLedger.objects.count() == 0

    def test_backstop_sweep_is_a_no_op_when_disabled(self, db: Any, capsys: pytest.CaptureFixture) -> None:
        call_command("stream_backstop_sweep")
        assert PilotRunLedger.objects.count() == 0
        assert "no-op" in capsys.readouterr().out


class TestEnvelopeTripHaltsAndNoSelfResume:
    @STREAMING_ON
    def test_a_breached_envelope_halts_before_any_work_and_records_a_trip(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=42)
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=8.0),
        )

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "halted-new-trip"
        assert outcome.trip_id is not None
        trip = EnvelopeTrip.objects.get(trip_id=outcome.trip_id)
        assert trip.bar == EnvelopeTrip.Bar.HOST_LOAD
        # halted BEFORE any ledger row/Stage C/D work - a halted dispatch never partially starts.
        assert PilotRunLedger.objects.count() == 0
        assert ImageEvidence.objects.count() == 0

    @STREAMING_ON
    def test_an_open_trip_refuses_dispatch_even_with_healthy_signals_no_self_resume(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=42)
        open_trip = check_envelope(stage_e_dispatch.EnvelopeSignals(load_avg=9.0))
        assert open_trip is not None
        # Every signal is now healthy - the trip alone must still gate dispatch (no self-resume).
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=0.1),
        )

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "halted-open-trip"
        assert outcome.trip_id == open_trip.trip_id
        assert PilotRunLedger.objects.count() == 0
        open_trip.refresh_from_db()
        assert open_trip.acknowledged_at is None  # this module never clears a trip itself

    @STREAMING_ON
    def test_dispatch_resumes_only_after_an_explicit_acknowledge(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(content_phash=42)
        _full_evidence(card)  # already Stage-C-complete, isolates this to "did dispatch proceed"
        trip = check_envelope(stage_e_dispatch.EnvelopeSignals(load_avg=9.0))
        assert trip is not None
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=0.1),
        )

        still_halted = dispatch_micro_batch(card_ids=[card.pk])
        assert still_halted.status == "halted-open-trip"

        acknowledge_trip(trip.trip_id, "load confirmed back to normal")
        resumed = dispatch_micro_batch(card_ids=[card.pk])
        assert resumed.status in ("completed", "empty")
        assert current_trip() is None


class TestFetchFailureWindowSizing:
    def test_window_maxlen_matches_the_ratified_500_constant(self) -> None:
        window = _FetchOutcomeWindow()
        assert window._window.maxlen == FETCH_FAILURE_WINDOW == 500

    def test_window_caps_at_500_and_evicts_oldest(self) -> None:
        window = _FetchOutcomeWindow()
        for _ in range(500):
            window.record(success=False)
        failures, total = window.failures_and_total()
        assert (failures, total) == (500, 500)

        window.record(success=True)  # the 501st push evicts the oldest (a failure)
        failures, total = window.failures_and_total()
        assert total == 500  # capped, never grows past the ratified window size
        assert failures == 499  # one failure evicted, replaced by a success

    def test_window_feeds_check_envelope_at_exactly_the_ratified_rate(self, db: Any) -> None:
        """Ties the window's own sizing directly to operating_envelope's ratified >1%-over-500
        math (docs/proposals/stage-e-streaming.md §10(a)) - not just that this module's deque is
        sized 500, but that a real 500-card window built via this module trips (or doesn't) exactly
        where the primitive says it should."""
        window = _FetchOutcomeWindow()
        for _ in range(494):
            window.record(success=True)
        for _ in range(6):
            window.record(success=False)  # 6/500 = 1.2% > 1% ceiling
        failures, total = window.failures_and_total()
        signals = stage_e_dispatch.EnvelopeSignals(fetch_failures_in_window=failures, fetch_total_in_window=total)
        trip = check_envelope(signals)
        assert trip is not None
        assert trip.bar == EnvelopeTrip.Bar.FETCH_FAILURE_RATE

    def test_exactly_5_of_500_does_not_trip(self, db: Any) -> None:
        window = _FetchOutcomeWindow()
        for _ in range(495):
            window.record(success=True)
        for _ in range(5):
            window.record(success=False)  # exactly 1.0% - the ceiling itself, not a breach
        failures, total = window.failures_and_total()
        signals = stage_e_dispatch.EnvelopeSignals(fetch_failures_in_window=failures, fetch_total_in_window=total)
        assert check_envelope(signals) is None


def _full_evidence(card, **overrides: Any) -> ImageEvidence:
    """A CURRENT ImageEvidence row carrying every Stage C manifest key - makes Stage C's own resume
    filter treat this card as already-done, isolating a test to the Stage D leg (or to pure
    dispatch-gating behaviour) without needing to mock the fetch/compute chain at all."""
    defaults = dict(
        content_hash=card.content_phash or 0,
        extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
        collector_line_raw_text="",
        collector_line_set_code="",
        collector_line_collector_number="",
        legal_line_proxy_marker_detected=False,
        symbol_phash=None,
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestSelectMicroBatch:
    """Issue #458 - `_select_micro_batch`'s backlog fill now walks `StageESweepCursor.position`
    through the pk space in bounded chunks instead of anti-joining the whole catalog every call
    (see that function's own docstring for the full design). Seed handling itself (dedupe,
    seed-first, early return once the seed alone fills the batch) is untouched by #458 and is
    covered by the first two tests below exactly as before."""

    def test_seed_cards_come_first_and_are_deduplicated(self, db: Any) -> None:
        card = CardFactory(content_phash=42)
        _full_evidence(card)
        batch = _select_micro_batch([card.pk, card.pk], batch_size=5)
        assert batch == [card.pk]

    def test_seed_alone_already_at_batch_size_skips_the_backlog_query_and_the_cursor_entirely(self, db: Any) -> None:
        seed = CardFactory(content_phash=1)
        CardFactory(content_phash=2)  # would be backlog-eligible, but batch_size=1 leaves no room
        batch = _select_micro_batch([seed.pk], batch_size=1)
        assert batch == [seed.pk]
        # the cursor is never touched (not even created) when the seed alone fills the batch.
        assert StageESweepCursor.objects.count() == 0

    def test_backlog_fill_skips_fully_processed_cards_and_advances_the_cursor_to_the_last_examined_pk(
        self, db: Any
    ) -> None:
        done = CardFactory(content_phash=1)
        _full_evidence(done)
        pending_a = CardFactory(content_phash=2)
        pending_b = CardFactory(content_phash=3)
        no_hash = CardFactory(content_phash=None)

        # batch_size=2 is filled exactly by the two pending cards, so this dispatch stops there
        # rather than continuing on to hit (and wrap on) the end of the pk space - wrap-around is
        # its own separate scenario, covered below.
        batch = _select_micro_batch([], batch_size=2)

        assert done.pk not in batch
        assert no_hash.pk not in batch
        assert set(batch) == {pending_a.pk, pending_b.pk}
        # the cursor advances to the last pk this dispatch actually examined - `pending_b` is the
        # highest-pk candidate (content_phash is not None) in the single chunk this call verified.
        cursor = StageESweepCursor.objects.get()
        assert cursor.position == pending_b.pk
        assert cursor.wrap_count == 0

    def test_backlog_fill_is_bounded_by_batch_size(self, db: Any) -> None:
        for _ in range(5):
            CardFactory(content_phash=100)
        batch = _select_micro_batch([], batch_size=2)
        assert len(batch) == 2

    def test_wrap_around_resets_position_and_increments_wrap_count_returning_an_empty_batch(self, db: Any) -> None:
        card = CardFactory(content_phash=1)
        _full_evidence(card)  # already processed - nothing left to sweep past it
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_C, position=card.pk)  # cursor at the end

        batch = _select_micro_batch([], batch_size=5)

        assert batch == []  # empty is a valid outcome (mirrors dispatch_micro_batch's own "empty")
        cursor = StageESweepCursor.objects.get()
        assert cursor.position == 0
        assert cursor.wrap_count == 1

    def test_wrap_around_stops_this_dispatch_rather_than_resuming_from_zero_leaving_a_partial_batch(
        self, db: Any
    ) -> None:
        seed = CardFactory(content_phash=1)
        _full_evidence(seed)
        pending = CardFactory(content_phash=2)  # would be found immediately if this wrapped AND
        # kept scanning from 0 in the same call - the binding rule is that it must NOT, so this
        # dispatch's own batch must come back with the seed only, not [seed, pending].
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_C, position=pending.pk)

        batch = _select_micro_batch([seed.pk], batch_size=5)

        assert batch == [seed.pk]  # the seed only - partial, never resumed from 0 in this call
        cursor = StageESweepCursor.objects.get()
        assert cursor.position == 0
        assert cursor.wrap_count == 1

    def test_cas_race_discards_the_lost_chunk_and_retries_until_it_wins(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = [CardFactory(content_phash=i) for i in range(1, 4)]
        real_try_advance = StageESweepCursor.try_advance
        calls = {"n": 0}

        def _flaky_try_advance(name: str, from_position: int, to_position: int) -> bool:
            calls["n"] += 1
            if calls["n"] <= 2:
                return False  # simulate two concurrent dispatches winning the CAS race first
            return real_try_advance(name, from_position, to_position)

        monkeypatch.setattr(StageESweepCursor, "try_advance", staticmethod(_flaky_try_advance))

        batch = _select_micro_batch([], batch_size=10)

        assert calls["n"] == 3  # 2 losses + 1 winning attempt - well within the retry budget
        assert set(batch) == {c.pk for c in pending}

    def test_cas_race_gives_up_after_three_retries_and_returns_whatever_it_already_has(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for i in range(1, 4):
            CardFactory(content_phash=i)
        calls = {"n": 0}

        def _always_loses(name: str, from_position: int, to_position: int) -> bool:
            calls["n"] += 1
            return False

        monkeypatch.setattr(StageESweepCursor, "try_advance", staticmethod(_always_loses))

        batch = _select_micro_batch([], batch_size=10)

        assert batch == []  # never won a claim, so never verified a single candidate
        assert calls["n"] == 4  # 1 initial attempt + 3 retries, then this dispatch stops

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=2, STAGE_E_SELECTION_SCAN_CAP=6)
    def test_scan_cap_limits_examined_candidates_and_returns_a_partial_batch(self, db: Any) -> None:
        for i in range(1, 5):
            card = CardFactory(content_phash=i)
            _full_evidence(card)  # 4 already-processed cards - the first 2 chunks of 2
        eligible = CardFactory(content_phash=100)  # 5th candidate - inside the cap, genuinely eligible
        trailing_processed = CardFactory(content_phash=200)
        _full_evidence(trailing_processed)  # 6th and last candidate this dispatch examines
        beyond_cap = CardFactory(content_phash=300)  # 7th candidate - past SCAN_CAP=6, never reached

        batch = _select_micro_batch([], batch_size=5)

        assert batch == [eligible.pk]  # only the one eligible card inside the examined window
        assert beyond_cap.pk not in batch
        cursor = StageESweepCursor.objects.get()
        # exactly SCAN_CAP=6 candidates examined (3 chunks of CHUNK_SIZE=2), never more.
        assert cursor.position == trailing_processed.pk

    def test_selection_query_count_is_flat_regardless_of_catalog_size(self, db: Any) -> None:
        """Bounded queries (issue #458's own acceptance bar): the query COUNT `_select_micro_batch`
        issues must depend only on batch_size/CHUNK_SIZE/SCAN_CAP, never on how many rows already
        exist in `cardpicker_card` - asserted directly via query counts, not timing."""
        for i in range(1, 21):
            CardFactory(content_phash=i)  # a 20-card catalog

        with CaptureQueriesContext(connection) as small_catalog_queries:
            small_batch = _select_micro_batch([], batch_size=5)
        assert len(small_batch) == 5

        StageESweepCursor.objects.all().delete()  # reset the cursor for a fair second measurement
        for i in range(21, 421):
            CardFactory(content_phash=i)  # grow the catalog by 20x

        with CaptureQueriesContext(connection) as large_catalog_queries:
            large_batch = _select_micro_batch([], batch_size=5)
        assert len(large_batch) == 5

        assert len(large_catalog_queries.captured_queries) == len(small_catalog_queries.captured_queries)

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=250, STAGE_E_SELECTION_SCAN_CAP=1500)
    def test_bulk_scale_selection_with_version_aware_resume_filter(self, db: Any) -> None:
        """Bulk-scale (1200 cards): version-aware resume filter correctly re-processes cards with
        old version tags while skipping cards with current versions, and micro-batch selection
        respects batch_size. Creates 1200 cards: 200 with current-version evidence (should be
        skipped), 200 with stale-version evidence (should be re-processed), 800 with no evidence
        (should be eligible)."""
        from cardpicker.management.commands.run_image_evidence_cohort import (
            MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
        )

        current_versions = MANIFEST_EXTRACTOR_CURRENT_VERSIONS
        stale_versions = {k: f"{k}-v0" for k in current_versions}

        stale_cards = []
        current_cards = []
        eligible_cards = []
        for i in range(1, 1201):
            if i <= 200:
                card = CardFactory(content_phash=i)
                ImageEvidenceFactory(
                    card=card,
                    content_hash=i,
                    extractor_versions=stale_versions,
                )
                stale_cards.append(card)
            elif i <= 400:
                card = CardFactory(content_phash=i)
                ImageEvidenceFactory(
                    card=card,
                    content_hash=i,
                    extractor_versions=current_versions,
                )
                current_cards.append(card)
            else:
                card = CardFactory(content_phash=i)
                eligible_cards.append(card)

        batch = _select_micro_batch([], batch_size=500)

        assert len(batch) == 500

        current_pks = {c.pk for c in current_cards}
        assert current_pks.isdisjoint(batch), "current-version cards must be skipped"

        stale_pks = {c.pk for c in stale_cards}
        eligible_pks = {c.pk for c in eligible_cards}
        batched_stale = stale_pks & set(batch)
        batched_eligible = eligible_pks & set(batch)
        assert len(batched_stale) > 0, "stale-version cards must be re-processed"
        assert len(batched_eligible) > 0, "no-evidence cards must be eligible"
        assert len(batched_stale) + len(batched_eligible) == 500


class TestEndToEndMicroBatch:
    """event -> batch -> Stage C extraction + Stage D calculators invoked -> counters written."""

    @STREAMING_ON
    def test_dispatch_for_card_runs_the_full_conveyor(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _install_stage_c_stub(
            monkeypatch,
            fetch_result=_png_bytes(),
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        dispatch_for_card(card.pk, "card-create")

        evidence = ImageEvidence.objects.get(card=card)
        assert MANIFEST_EXTRACTOR_KEYS.issubset(evidence.extractor_versions.keys())

        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        assert vote.is_no_match is False
        # a single VoteSource.OCR vote can never resolve a card alone (the human-backed gate).
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED

        ledger = PilotRunLedger.objects.get(command="stage_e_streaming_dispatch")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["trigger_reason"] == "card-create"
        assert ledger.counters["stage_c_completed"] == 1
        assert ledger.counters["stage_d_join_key_votes"] == 1
        assert "peak_rss_mb" in ledger.counters
        assert "elapsed_s" in ledger.counters

    @STREAMING_ON
    def test_a_card_with_current_evidence_skips_stage_c_but_still_runs_stage_d(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        def _fail_if_called(card, dpi=None):
            raise AssertionError("Stage C should have been skipped - evidence is already current")

        _install_stage_c_stub(monkeypatch, fetch_result=_fail_if_called)

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "completed"
        assert outcome.stage_c_completed == 0
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk


class TestForceStageCReextract:
    """Issue #465's one conveyor change (`force_stage_c_reextract`, threaded through
    `dispatch_micro_batch` -> `_run_stage_c`) - `False` (the default, exercised by every other test
    in this file) must stay byte-identical; `True` is exercised here directly, isolated from the
    real `stage_e_shakedown` command (which has its own test module)."""

    @STREAMING_ON
    def test_default_false_still_skips_a_card_with_current_full_manifest_evidence(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Byte-identical-path proof, stated explicitly (not just implied by every pre-existing
        test in this file passing unmodified): calling dispatch_micro_batch with
        force_stage_c_reextract's own default (False, not even passed) behaves exactly like
        `test_a_card_with_current_evidence_skips_stage_c_but_still_runs_stage_d` above."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        def _fail_if_called(card, dpi=None):
            raise AssertionError("Stage C should have been skipped - evidence is already current")

        _install_stage_c_stub(monkeypatch, fetch_result=_fail_if_called)

        outcome = dispatch_micro_batch(card_ids=[card.pk])  # force_stage_c_reextract not passed

        assert outcome.status == "completed"
        assert outcome.stage_c_completed == 0
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk

    @STREAMING_ON
    def test_force_true_re_extracts_a_card_with_current_but_blank_evidence(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Bug-A tail's own shape: a card already carries a CURRENT, full-manifest
        ImageEvidence row (so the ordinary already-done check would skip it), but every field on
        that row is blank - force_stage_c_reextract=True is what makes the conveyor re-fetch and
        re-extract it anyway, overwriting the same (card, content_hash) row (persist_evidence's own
        get_or_create semantics, unchanged)."""
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card)  # every field blank - the tail's own signature

        _install_stage_c_stub(
            monkeypatch,
            fetch_result=_png_bytes(),
            collector_line_set_code="mom",
            collector_line_collector_number="158",
        )

        outcome = dispatch_micro_batch(card_ids=[card.pk], force_stage_c_reextract=True)

        assert outcome.status == "completed"
        assert outcome.stage_c_completed == 1  # re-extracted despite already-current evidence
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        # exactly one ImageEvidence row for this card - the re-extraction overwrote it in place,
        # never duplicated it (UniqueConstraint on (card, content_hash), persist_evidence's own
        # get_or_create).
        assert ImageEvidence.objects.filter(card=card).count() == 1

    @STREAMING_ON
    @pytest.mark.parametrize(
        "dispatch_kwargs, expected_short_circuit",
        [
            # THE DECOUPLING ITSELF (2026-07-28): force_stage_c_reextract no longer implies
            # short_circuit=False. `_run_stage_c` used to hardcode
            # `False if force_stage_c_reextract else None`, because its only caller
            # (stage_e_shakedown) wanted both - see that function's own "WHY THE TWO WERE
            # CONFLATED, AND WHY THEY NO LONGER ARE" docstring note. A forced re-extraction now
            # leaves short_circuit at None, i.e. compute_card_evidence resolves it from the
            # STAGE_C_NO_SHORTCIRCUIT env var at call time.
            ({"force_stage_c_reextract": True}, None),
            # The escalation-forcing behaviour is still reachable, now on its own parameter (the
            # equivalent of run_image_evidence_cohort's own --no-shortcircuit flag) - this exact
            # pair is what stage_e_shakedown now passes explicitly.
            ({"force_stage_c_reextract": True, "short_circuit": False}, False),
            # ...and the other direction of the independence: short_circuit reaches
            # compute_card_evidence with no forced re-extraction at all.
            ({"short_circuit": False}, False),
            ({"short_circuit": True}, True),
            ({}, None),
        ],
    )
    def test_short_circuit_is_independent_of_force_stage_c_reextract(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, dispatch_kwargs: dict, expected_short_circuit: Any
    ) -> None:
        """`short_circuit` and `force_stage_c_reextract` are two INDEPENDENT parameters of
        `dispatch_micro_batch`: the first is forwarded verbatim to `compute_card_evidence`, the
        second only controls whether the already-done manifest check is skipped. Neither implies
        anything about the other."""
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        if dispatch_kwargs.get("force_stage_c_reextract"):
            # A card the already-done check WOULD otherwise skip, so reaching compute_card_evidence
            # at all also proves the force flag is still doing its own half of the job.
            _full_evidence(card)

        observed_short_circuit: list[Any] = []

        def _recording_stub(
            card_id: int,
            content_hash,
            image,
            fetch_latency_ms=0.0,
            profile=None,
            short_circuit=None,
            known_set_codes=None,
            artist_lexicon=None,
            printing_artist_lookup=None,
            md5_checksum=None,
            sha256_checksum=None,
        ):
            observed_short_circuit.append(short_circuit)
            return _stub_compute_card_evidence_ok()(
                card_id,
                content_hash,
                image,
                fetch_latency_ms,
                profile,
                short_circuit,
                known_set_codes,
                md5_checksum,
                sha256_checksum,
            )

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module
        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", lambda card, dpi=None: _png_bytes())
        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", _recording_stub)

        dispatch_micro_batch(card_ids=[card.pk], **dispatch_kwargs)

        assert observed_short_circuit == [expected_short_circuit]


class TestConcurrencyCapIntegration:
    """The concurrency-cap companion change (`cardpicker.stage_e_concurrency`), exercised through
    the REAL, post-#448 `dispatch_micro_batch` body - not just the module-level unit coverage in
    `test_stage_e_concurrency.py`. A raw, independent `psycopg2` connection holds every available
    slot (standing in for another concurrent dispatch on a separate django-q worker process, the
    same "genuinely separate session" discipline `test_stage_e_concurrency.py`'s own module
    docstring establishes - Postgres session-level advisory locks are re-entrant within one
    session, so simulating a second dispatcher via Django's own connection would be a false test)."""

    def _raw_connection_holding_every_slot(self, cap: int) -> "psycopg2.extensions.connection":
        connection.ensure_connection()
        raw = psycopg2.connect(**connection.get_connection_params())
        raw.autocommit = True
        with raw.cursor() as cursor:
            for slot in range(cap):
                cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, slot])
                (acquired,) = cursor.fetchone()
                assert acquired is True, f"test setup failed to claim slot {slot}"
        return raw

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_dispatch_is_throttled_when_the_only_slot_is_already_held(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")

        def _fail_if_called(card, dpi=None):
            raise AssertionError("Stage C must never run once the concurrency cap has throttled")

        _install_stage_c_stub(monkeypatch, fetch_result=_fail_if_called)

        raw = self._raw_connection_holding_every_slot(cap=1)
        try:
            outcome = dispatch_micro_batch(card_ids=[card.pk])
        finally:
            raw.close()  # auto-releases the advisory lock, same crash-safety property tested above

        assert outcome.status == "throttled-concurrency-cap"
        # a throttled dispatch never partially starts, matching halted-open-trip/halted-new-trip's
        # own convention - no ledger row, no evidence, no vote.
        assert PilotRunLedger.objects.count() == 0
        assert ImageEvidence.objects.count() == 0
        assert CardPrintingTag.objects.count() == 0
        # observability signal (Tron gate anomaly 4, 2026-07-25) - the ONE durable, queryable
        # record that this throttle happened, since no ledger row was written above.
        counter = StageEThrottleCounter.objects.get()
        assert counter.count == 1
        assert counter.last_throttled_at is not None

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_dispatch_proceeds_normally_once_the_slot_is_released(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        raw = self._raw_connection_holding_every_slot(cap=1)
        raw.close()  # released before dispatching - the cap must not still be considered "held"

        outcome = dispatch_micro_batch(card_ids=[card.pk])

        assert outcome.status == "completed"
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk


class TestGoogleLockoutMidBatch:
    @STREAMING_ON
    def test_lockout_stops_stage_c_trips_the_envelope_and_refuses_the_next_dispatch(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card_a = CardFactory(name="Card A", content_phash=1)
        card_b = CardFactory(name="Card B", content_phash=2)

        def _lockout_fetch(card, dpi=None):
            raise GoogleFetchLockoutError("locked out")

        _install_stage_c_stub(monkeypatch, fetch_result=_lockout_fetch)

        outcome = dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk])

        assert outcome.status == "completed-with-trip"
        assert outcome.trip_id is not None
        trip = EnvelopeTrip.objects.get(trip_id=outcome.trip_id)
        assert trip.bar == EnvelopeTrip.Bar.GOOGLE_LOCKOUT
        assert ImageEvidence.objects.count() == 0  # lockout hit before any card's fetch succeeded

        ledger = PilotRunLedger.objects.get(run_id=outcome.run_id)
        assert ledger.counters["lockout_trip_id"] == trip.trip_id

        # no self-resume: the next dispatch call refuses outright.
        refused = dispatch_micro_batch(card_ids=[card_a.pk])
        assert refused.status == "halted-open-trip"


class TestKillSafetyResumeContract:
    """Extends the batch kill-test's own assertions (scripts/ops/crash_drill.sh, docs/proposals/
    stage-e-streaming.md §7) to a streamed micro-batch: a mid-batch crash leaves a truthful FAILED
    ledger row and every already-committed card durably written, and a re-invocation over the same
    (or an overlapping) card set completes idempotently with zero manual cleanup."""

    @STREAMING_ON
    def test_mid_batch_crash_leaves_truthful_ledger_and_durable_partial_work(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card_a = CardFactory(name="Card A", content_phash=1)
        card_b = CardFactory(name="Card B", content_phash=2)
        card_c = CardFactory(name="Card C", content_phash=3)
        calls = {"n": 0}

        def _fetch_crashes_on_second_card(card, dpi=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated kill mid-batch")
            return _png_bytes()

        _install_stage_c_stub(monkeypatch, fetch_result=_fetch_crashes_on_second_card)

        with pytest.raises(RuntimeError, match="simulated kill mid-batch"):
            dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk, card_c.pk], run_id="kill-drill-1")

        ledger = PilotRunLedger.objects.get(run_id="kill-drill-1")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert "RuntimeError" in ledger.counters["failure_reason"]

        # durable partial work: the first card's evidence committed before the crash.
        assert ImageEvidence.objects.filter(card=card_a).count() == 1
        # nothing committed for the card that crashed or anything after it in this pass.
        assert ImageEvidence.objects.filter(card=card_b).count() == 0
        assert ImageEvidence.objects.filter(card=card_c).count() == 0

        # RESUME: fix the fault and re-invoke over the SAME card set - zero manual cleanup.
        _install_stage_c_stub(monkeypatch, fetch_result=_png_bytes())
        resumed = dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk, card_c.pk], run_id="kill-drill-2")

        assert resumed.status == "completed"
        # idempotent re-entry: card_a's evidence is not duplicated, despite being re-included.
        assert ImageEvidence.objects.filter(card=card_a).count() == 1
        assert ImageEvidence.objects.filter(card=card_b).count() == 1
        assert ImageEvidence.objects.filter(card=card_c).count() == 1
        resumed_ledger = PilotRunLedger.objects.get(run_id="kill-drill-2")
        assert resumed_ledger.status == PilotRunLedger.Status.COMPLETED
        # only the two cards the crashed run never reached needed real Stage C work this time.
        assert resumed_ledger.counters["stage_c_completed"] == 2


class TestConcurrentDispatchVoteCollision:
    """Regression for the VOTE-COLLISION half of the Stage E Phase 2 shakedown's first live
    incident (failed run_ids stage-e-stream-20260724T2144*, seven losers + the one winner = eight
    total concurrent dispatches, exactly Q_CLUSTER["workers"]=8) - see
    `local_calculate_verdicts._split_new_printing_tag_votes`' own docstring for the full
    root-cause writeup, INCLUDING why this is a separate failure from the same run's
    `envtrip-20260724T214616-be6e5db9` host-load envelope trip (a resource-contention problem this
    change does not address - see that docstring's own "SEPARATE FAILURE" section). Two CONCURRENT
    `dispatch_micro_batch` calls scoped to an overlapping card set (django-q2 runs 8 workers; the
    backstop sweep can also overlap an event trigger) used to abort a WHOLE micro-batch with an
    `IntegrityError` the instant the losing dispatch's own Stage D `bulk_create` raced a winner's.
    Reproduced here at the full conveyor level (not just the calculator level
    `test_local_calculate_verdicts.py` covers) by seeding the winner's vote directly and
    confirming the loser's own `dispatch_micro_batch` call completes rather than raising."""

    @STREAMING_ON
    def test_a_losing_race_completes_instead_of_raising_integrity_error(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cardpicker.local_calculate_verdicts as local_calculate_verdicts_module

        card = CardFactory(name="Some Card", content_phash=42)
        CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_collector_number="999")  # doesn't match "158" -> is_no_match=True
        monkeypatch.setattr(
            local_calculate_verdicts_module,
            "_eligible_cards_queryset",
            lambda *args, **kwargs: local_calculate_verdicts_module.Card.objects.filter(pk=card.pk),
        )

        # the WINNER of the race: another (concurrent, not modeled here) dispatch's own vote
        # already landed for this exact (card, anonymous_id) pair.
        CardPrintingTag.objects.create(
            card=card,
            printing=None,
            is_no_match=True,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            source=VoteSource.OCR,
        )

        outcome = dispatch_micro_batch(card_ids=[card.pk])  # must not raise IntegrityError

        assert outcome.status == "completed"
        # 2026-07-28: the calculator's split/count now runs BEFORE its purge, so the loser skips
        # and the counter this field exists to surface is genuinely non-zero. Under the previous
        # ordering the purge deleted the winner's row before the split looked for it, so this
        # counter read 0 in EVERY deployment - the literal "zero forever would suggest the guard
        # itself is dead code" case this field's own definition comment warns about.
        assert outcome.stage_d_join_key_already_voted == 1
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).count() == 1

        ledger = PilotRunLedger.objects.get(run_id=outcome.run_id)
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["stage_d_join_key_already_voted"] == 1


class TestBackstopSweep:
    @STREAMING_ON
    def test_sweep_processes_the_stage_d_backlog_and_is_idempotent_on_rerun(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        card = CardFactory(name="Some Card", content_phash=42)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        call_command("stream_backstop_sweep")
        first_output = capsys.readouterr().out
        assert "batches_dispatched=1" in first_output or "stage_d_votes_or_routes=1" in first_output

        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        votes_after_first_run = CardPrintingTag.objects.count()

        call_command("stream_backstop_sweep")
        second_output = capsys.readouterr().out
        assert "batches_dispatched=0" in second_output

        assert CardPrintingTag.objects.count() == votes_after_first_run  # idempotent - no dup votes

    @STREAMING_ON
    def test_sweep_stops_on_an_envelope_halt(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        CardFactory(name="Some Card", content_phash=42)
        monkeypatch.setattr(
            stage_e_dispatch,
            "_sample_envelope_signals",
            lambda google_lockout=False: stage_e_dispatch.EnvelopeSignals(load_avg=9.0),
        )

        call_command("stream_backstop_sweep")

        assert EnvelopeTrip.objects.filter(bar=EnvelopeTrip.Bar.HOST_LOAD).count() == 1
        assert PilotRunLedger.objects.count() == 0  # halted before any batch ledger row was written

    @STREAMING_ON
    @override_settings(STAGE_E_MAX_CONCURRENT_DISPATCHES=1)
    def test_sweep_stops_on_a_throttled_concurrency_cap_without_looping(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        """Tron gate defect fix: pre-fix, "throttled-concurrency-cap" matched neither
        `_HALT_STATUSES` nor "empty" and fell through to `batches_dispatched += 1` with an immediate
        re-entry into `dispatch_micro_batch` - a hot, backoff-free loop up to `--max-batches`,
        precisely when the host is already saturated, reporting a success-shaped
        `batches_dispatched=N` for a sweep that did nothing. Mirrors
        `TestConcurrencyCapIntegration`'s own "genuinely separate session" discipline (that class's
        own docstring) - a raw, independent `psycopg2` connection holds the only slot, standing in
        for another concurrent dispatch (a django-q worker, or the event trigger racing this same
        sweep) - reusing the SAME session for both would be a false test (re-entrant advisory
        locks, this file's own `stage_e_concurrency` test module docstring)."""
        CardFactory(name="Some Card", content_phash=42)

        connection.ensure_connection()
        raw = psycopg2.connect(**connection.get_connection_params())
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_LOCK_NAMESPACE, 0])
            (acquired,) = cursor.fetchone()
            assert acquired is True, "test setup failed to claim the only slot"
        try:
            call_command("stream_backstop_sweep", "--max-batches", "5")
        finally:
            raw.close()  # auto-releases the advisory lock, same crash-safety property tested above

        output = capsys.readouterr().out
        assert "sweep stopped: dispatch slots saturated (throttled-concurrency-cap)" in output
        # exactly one occurrence - proves the loop actually STOPPED on the first throttled outcome
        # rather than re-entering dispatch_micro_batch up to --max-batches=5 with no backoff.
        assert output.count("sweep stopped: dispatch slots saturated") == 1
        assert "batches_dispatched=0" in output
        assert "stopped_reason=throttled-concurrency-cap" in output
        # no ledger row - the throttled attempt never started real work, matching a halt's own
        # convention (TestConcurrencyCapIntegration's own assertion for dispatch_micro_batch
        # directly).
        assert PilotRunLedger.objects.count() == 0


def _voted_card(content_phash: int = 1) -> Any:
    """A Stage-C-complete card carrying a JOIN_KEY_ANONYMOUS_ID vote already - INELIGIBLE for the
    Stage D backlog (`_eligible_cards_queryset`'s own `.exclude(printing_tags__anonymous_id=...)`),
    used across `TestStageDBacklog`/`TestBackstopSweepBacklogBExhaustedVsCapHit` below to build a
    "not what we're looking for" candidate that a cursor walk must still examine (and skip)
    without mistaking it for backlog exhaustion."""
    card = CardFactory(content_phash=content_phash)
    _full_evidence(card)
    CardPrintingTag.objects.create(
        card=card, printing=None, is_no_match=True, anonymous_id=JOIN_KEY_ANONYMOUS_ID, source=VoteSource.OCR
    )
    return card


class TestSweepCursorMigration:
    """Issue #460 - migration `0083_stageesweepcursor_keyed` renames the pre-#460 singleton row
    (`singleton_key=1`, issue #458) to the keyed `stage_c` row, `position`/`wrap_count` preserved.
    Exercised via `MigrationExecutor` directly (migrate back to 0082, create the pre-#460 row
    shape, migrate forward to 0083, assert the row survived under its new key) - the one-time
    transition every existing deployment's own database goes through."""

    def test_existing_singleton_row_becomes_the_stage_c_row_with_position_preserved(self, db: Any) -> None:
        executor = MigrationExecutor(connection)
        executor.migrate([("cardpicker", "0082_stageesweepcursor")])
        old_apps = executor.loader.project_state(("cardpicker", "0082_stageesweepcursor")).apps
        old_cursor_model = old_apps.get_model("cardpicker", "StageESweepCursor")
        old_cursor_model.objects.create(singleton_key=1, position=777, wrap_count=3)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([("cardpicker", "0083_stageesweepcursor_keyed")])

        new_apps = executor.loader.project_state(("cardpicker", "0083_stageesweepcursor_keyed")).apps
        new_cursor_model = new_apps.get_model("cardpicker", "StageESweepCursor")
        row = new_cursor_model.objects.get()
        assert row.name == "stage_c"
        assert row.position == 777
        assert row.wrap_count == 3

        # Restore the schema to the latest migration state - this test is the only one in the
        # suite that ever moves the schema backward, so every later test must see it forward again.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


class TestKeyedCursorIsolation:
    """Issue #460 - `StageESweepCursor.STAGE_C`/`STAGE_D` are independent rows; advancing/wrapping
    one must never move the other."""

    def test_advancing_stage_d_never_moves_stage_c(self, db: Any) -> None:
        stage_c = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_C)
        stage_d = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_D)

        assert StageESweepCursor.try_advance(StageESweepCursor.STAGE_D, stage_d.position, 500) is True

        stage_c.refresh_from_db()
        assert stage_c.position == 0
        stage_d.refresh_from_db()
        assert stage_d.position == 500

    def test_advancing_stage_c_never_moves_stage_d(self, db: Any) -> None:
        stage_c = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_C)
        stage_d = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_D)

        assert StageESweepCursor.try_advance(StageESweepCursor.STAGE_C, stage_c.position, 300) is True

        stage_d.refresh_from_db()
        assert stage_d.position == 0
        stage_c.refresh_from_db()
        assert stage_c.position == 300

    def test_wrapping_stage_d_never_touches_stage_cs_wrap_count(self, db: Any) -> None:
        StageESweepCursor.get_cursor(StageESweepCursor.STAGE_C)
        stage_d = StageESweepCursor.get_cursor(StageESweepCursor.STAGE_D)
        StageESweepCursor.try_advance(StageESweepCursor.STAGE_D, stage_d.position, 100)

        assert StageESweepCursor.try_wrap(StageESweepCursor.STAGE_D, 100) is True

        stage_c = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C)
        assert stage_c.wrap_count == 0
        stage_d.refresh_from_db()
        assert stage_d.position == 0
        assert stage_d.wrap_count == 1


class TestStageDBacklog:
    """Issue #460 - `_next_stage_d_backlog_ids` (`stream_backstop_sweep.py`), walking
    `StageESweepCursor.STAGE_D` via the shared `_cursor_chunk_walk` helper
    (`stage_e_dispatch.py`). Mirrors `TestSelectMicroBatch`'s own structure for the Stage C
    cursor, one test per behavior this function's own docstring documents."""

    def test_finds_an_evidence_complete_vote_missing_card_and_advances_the_cursor(self, db: Any) -> None:
        eligible = CardFactory(content_phash=1)
        _full_evidence(eligible)

        # batch_size=1 matches exactly the one candidate available, so this call stops the instant
        # it's found rather than continuing on to hit (and wrap on) the end of the pk space - wrap
        # while carrying an already-found id is its own separate scenario (the CAS-race test below).
        ids, exhausted = _next_stage_d_backlog_ids(1)

        assert ids == [eligible.pk]
        assert exhausted is False
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_D)
        assert cursor.position == eligible.pk

    def test_skips_a_card_that_already_has_a_join_key_vote(self, db: Any) -> None:
        voted = _voted_card(content_phash=1)
        pending = CardFactory(content_phash=2)
        _full_evidence(pending)

        ids, exhausted = _next_stage_d_backlog_ids(5)

        assert ids == [pending.pk]
        assert voted.pk not in ids

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=2, STAGE_E_SELECTION_SCAN_CAP=2)
    def test_scan_cap_hit_with_backlog_still_unscanned_returns_exhausted_false(self, db: Any) -> None:
        # Two already-voted (ineligible) cards fill the SCAN_CAP=2 examined window this call
        # spends - a genuinely eligible card sits just past it, unscanned.
        _voted_card(content_phash=1)
        _voted_card(content_phash=2)
        beyond_cap = CardFactory(content_phash=100)
        _full_evidence(beyond_cap)

        ids, exhausted = _next_stage_d_backlog_ids(5)

        assert ids == []
        assert exhausted is False  # cap-hit-empty, NOT exhaustion - beyond_cap is still unscanned
        assert beyond_cap.pk not in ids

    def test_wrap_around_with_nothing_eligible_returns_exhausted_true(self, db: Any) -> None:
        _voted_card(content_phash=1)

        ids, exhausted = _next_stage_d_backlog_ids(5)

        assert ids == []
        assert exhausted is True
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_D)
        assert cursor.position == 0
        assert cursor.wrap_count == 1

    def test_cas_race_on_the_stage_d_cursor_discards_the_lost_chunk_and_retries_until_it_wins(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mirrors `TestSelectMicroBatch.test_cas_race_discards_the_lost_chunk_and_retries_until_
        it_wins` for the Stage C cursor - same shared `_cursor_chunk_walk`, exercised here against
        the Stage D cursor instead, proving the CAS retry logic isn't accidentally Stage-C-specific."""
        pending = []
        for i in range(1, 4):
            card = CardFactory(content_phash=i)
            _full_evidence(card)
            pending.append(card)
        real_try_advance = StageESweepCursor.try_advance
        calls = {"n": 0}

        def _flaky_try_advance(name: str, from_position: int, to_position: int) -> bool:
            calls["n"] += 1
            if calls["n"] <= 2:
                return False  # simulate two concurrent dispatches winning the CAS race first
            return real_try_advance(name, from_position, to_position)

        monkeypatch.setattr(StageESweepCursor, "try_advance", staticmethod(_flaky_try_advance))

        ids, exhausted = _next_stage_d_backlog_ids(10)

        assert calls["n"] == 3  # 2 losses + 1 winning attempt - well within the retry budget
        assert set(ids) == {c.pk for c in pending}
        assert exhausted is True  # the walk reached (and wrapped past) the end of the pk space


class TestBackstopSweepBacklogBExhaustedVsCapHit:
    """Issue #460 §4 - the sweep loop's own distinction between backlog (b)'s cap-hit-empty result
    (`wrapped=False`, continue to the next batch) and any conclusion of emptiness. As of the
    2026-07-29 lap-evidence fix a wrap alone no longer ends the sweep either (see
    `TestWrapIsNotExhaustion` below), so the "continue past a cap hit" behaviour these two tests
    pin is now the ONLY behaviour short of a full observed empty lap."""

    @STREAMING_ON
    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=1, STAGE_E_SELECTION_SCAN_CAP=1)
    def test_sweep_continues_past_a_cap_hit_empty_backlog_b_result_and_still_finds_the_later_card(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        _voted_card(content_phash=1)  # examined and skipped on the sweep's first pass - cap-hit
        card = CardFactory(name="Some Card", content_phash=2)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")

        call_command("stream_backstop_sweep", "--max-batches", "5")

        output = capsys.readouterr().out
        assert "batches_dispatched=1" in output
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        # PRE-2026-07-29 this asserted "Backlog exhausted - nothing left to dispatch." here, on the
        # strength of a single backlog-(b) wrap. That assertion encoded the defect: with
        # SCAN_CAP=1 neither cursor gets anywhere near a COMPLETE observed lap inside five batches,
        # so the sweep has no evidence its backlogs are empty and must not claim they are. It stops
        # on `--max-batches` instead - the work still gets done (asserted above), the overstated
        # claim is gone.
        assert "Backlog exhausted" not in output

    @STREAMING_ON
    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=1, STAGE_E_SELECTION_SCAN_CAP=1)
    def test_sweep_stays_bounded_by_max_batches_when_cap_hit_empty_never_resolves(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        # Five already-voted, Stage-C-complete cards - with SCAN_CAP=1 each sweep iteration's own
        # backlog (b) walk examines exactly one of them and comes back cap-hit-empty every time,
        # never reaching the end of the pk space (so never `exhausted`) within the two-batch
        # budget this test allows - proving `range(max_batches)` alone is what stops this loop,
        # not the exhausted/halt/throttle paths.
        for i in range(1, 6):
            _voted_card(content_phash=i)

        call_command("stream_backstop_sweep", "--max-batches", "2")

        output = capsys.readouterr().out
        assert "batches_dispatched=0" in output
        assert "Backlog exhausted" not in output
        assert "Envelope halt" not in output
        assert "sweep stopped" not in output


class TestSweepLapTracker:
    """2026-07-29 - `stage_e_dispatch.SweepLapTracker`, the bookkeeping that turns a sequence of
    `_cursor_chunk_walk` results into the ONE thing `stream_backstop_sweep` is allowed to stop on:
    evidence that a COMPLETE observed lap of a cursor yielded zero eligible cards. Pure in-memory
    logic, no DB."""

    def test_the_first_wrap_only_arms_the_tracker_and_never_proves_emptiness(self) -> None:
        tracker = SweepLapTracker()
        # The cursor was somewhere mid-pk-space when this sweep started, so the stretch that just
        # ended is a PARTIAL lap - it never examined the range behind its own starting position.
        assert tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True) is False
        assert tracker.empty_lap_observed(StageESweepCursor.STAGE_C) is False

    def test_a_second_wrap_with_nothing_found_in_between_is_the_proof(self) -> None:
        tracker = SweepLapTracker()
        tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True)  # arms
        tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=False)  # a cap-hit call mid-lap
        assert tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True) is True

    def test_a_lap_that_dispatched_work_is_not_an_empty_lap(self) -> None:
        tracker = SweepLapTracker()
        tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True)  # arms
        tracker.record(StageESweepCursor.STAGE_C, found=7, wrapped=False)  # work this lap
        assert tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True) is False

    def test_work_found_in_the_same_call_as_the_wrap_still_disqualifies_that_lap(self) -> None:
        """The exact shape of the live 2026-07-28 incident: a walk that finds cards AND then runs
        off the end of the pk space. The wrap is not a licence to stop - the lap dispatched work."""
        tracker = SweepLapTracker()
        tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True)  # arms
        assert tracker.record(StageESweepCursor.STAGE_C, found=3, wrapped=True) is False
        # ...and the next lap starts clean, so it can prove emptiness on its own merits.
        assert tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True) is True

    def test_a_proof_is_revoked_the_moment_work_reappears(self) -> None:
        tracker = SweepLapTracker()
        tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True)
        assert tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True) is True
        assert tracker.record(StageESweepCursor.STAGE_C, found=1, wrapped=False) is False
        assert tracker.empty_lap_observed(StageESweepCursor.STAGE_C) is False

    def test_the_two_cursors_are_tracked_independently(self) -> None:
        tracker = SweepLapTracker()
        tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True)
        assert tracker.record(StageESweepCursor.STAGE_C, found=0, wrapped=True) is True
        assert tracker.empty_lap_observed(StageESweepCursor.STAGE_D) is False


class TestDenseBacklogDrainsWithoutLapping:
    """2026-07-29 - the "walk skips most of a dense backlog, permanently, per lap" defect.

    PRE-FIX the CAS claimed the whole chunk (`chunk[-1]`) before verification and the fill loop
    then stopped the instant `limit` ids had been found, so with the production
    `STAGE_E_SELECTION_CHUNK_SIZE=250`/`STAGE_E_MICRO_BATCH_SIZE=25` ratio a chunk holding 250
    eligible cards yielded 25 and the cursor had already moved past the other 225 - a dense backlog
    drained at ~10% per lap, each lap costing a full traversal of the pk space. POST-FIX the claim
    is sized to what the call actually consumes, so the unconsumed tail is never claimed and the
    next call resumes inside the same chunk."""

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=250, STAGE_E_SELECTION_SCAN_CAP=1000)
    def test_a_chunk_sized_dense_backlog_drains_in_batch_sized_calls_without_a_single_wrap(self, db: Any) -> None:
        # Exactly one chunk's worth of eligible cards - the brief's own 250/25 scenario.
        cards = [CardFactory(content_phash=i) for i in range(1, 251)]
        expected = {card.pk for card in cards}

        drained: list[int] = []
        for _ in range(10):  # ceil(250 / 25) calls, and not one more
            drained.extend(_select_micro_batch([], batch_size=25))

        assert len(drained) == 250
        assert len(set(drained)) == 250, "no card may be dispatched twice while draining one lap"
        assert set(drained) == expected
        # THE point: every card was reached inside a single pass of the pk space. Pre-fix this
        # cursor would have wrapped after the first call (position already at the chunk end) and
        # only 25 of the 250 would be drained per lap.
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C)
        assert cursor.wrap_count == 0

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=250, STAGE_E_SELECTION_SCAN_CAP=1000)
    def test_the_unconsumed_tail_of_a_chunk_is_never_claimed(self, db: Any) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 101)]

        batch = _select_micro_batch([], batch_size=25)

        assert batch == [card.pk for card in cards[:25]]
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C)
        # The claim stops at the LAST CONSUMED pk, not at the end of the 100-candidate chunk the
        # walk read and verified - so `pk__gt=position` on the next call starts at card 26.
        assert cursor.position == cards[24].pk
        assert cursor.position != cards[-1].pk

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=250, STAGE_E_SELECTION_SCAN_CAP=11)
    def test_a_partially_consumed_chunk_still_advances_fully_when_the_limit_is_not_reached(self, db: Any) -> None:
        """The non-dense case is unchanged: a chunk that does not fill the batch is claimed whole,
        exactly as before, so a sparse backlog still crosses ineligible cards at chunk speed. (The
        scan cap is set to the candidate count so the call stops on the cap rather than running on
        to wrap - a wrap would reset `position` to 0 and hide what this test is measuring.)"""
        done = [CardFactory(content_phash=i) for i in range(1, 11)]
        for card in done:
            _full_evidence(card)
        eligible = CardFactory(content_phash=100)

        batch = _select_micro_batch([], batch_size=25)

        assert batch == [eligible.pk]
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C)
        assert cursor.position == eligible.pk  # the whole chunk was consumed, so the whole chunk is claimed


class TestConcurrentWalkersStayDisjoint:
    """2026-07-29 - the claim protocol still holds after the read/verify/claim reordering.
    `StageESweepCursor`'s own docstring: the CAS on `position` is the ONE ownership mechanism, and
    two concurrent walkers on the SAME cursor must sweep disjoint ranges. What changed is only
    WHERE a lost race's wasted work lands (the loser has already spent one bounded `verify_chunk`
    query on a range it turns out not to own, and discards it) - never WHICH cards a winner
    returns. The interleaving below is deterministic rather than threaded: a hook fires inside
    walker A's own pre-CAS window and runs walker B's entire walk there, which is the worst case
    the CAS exists to survive."""

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=5, STAGE_E_SELECTION_SCAN_CAP=5)
    def test_a_walker_that_loses_the_claim_returns_none_of_the_other_walkers_cards(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = [CardFactory(content_phash=i) for i in range(1, 21)]

        def _everything_eligible(chunk: list[int]) -> list[int]:
            return list(chunk)

        real_try_advance = StageESweepCursor.try_advance
        walker_b: dict[str, Any] = {}
        state = {"nested": False}

        def _hooked_try_advance(name: str, from_position: int, to_position: int) -> bool:
            if not state["nested"]:
                # Walker A has read and verified its chunk and is about to claim. Walker B runs its
                # WHOLE walk right here, inside that window, and claims first.
                state["nested"] = True
                walker_b["result"] = _cursor_chunk_walk(StageESweepCursor.STAGE_C, _everything_eligible, 3)
            return real_try_advance(name, from_position, to_position)

        monkeypatch.setattr(StageESweepCursor, "try_advance", staticmethod(_hooked_try_advance))

        a_ids, _a_wrapped = _cursor_chunk_walk(StageESweepCursor.STAGE_C, _everything_eligible, 3)
        b_ids, _b_wrapped = walker_b["result"]

        assert b_ids == [card.pk for card in cards[:3]], "walker B won the claim it made first"
        assert a_ids == [card.pk for card in cards[3:6]], "walker A retried from B's new position"
        assert set(a_ids).isdisjoint(b_ids), "two walkers on one cursor must sweep disjoint ranges"
        assert len(set(a_ids) | set(b_ids)) == len(a_ids) + len(b_ids), "no card dispatched twice"

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=5, STAGE_E_SELECTION_SCAN_CAP=100)
    def test_interleaved_walkers_partition_a_dense_backlog_with_no_overlap_and_no_gaps(self, db: Any) -> None:
        """Two walkers alternating on the same cursor until it wraps: between them they must cover
        every eligible card exactly once. (Sequential calls model the settled outcome of any
        interleaving - the CAS is what makes every interleaving settle this way.)"""
        cards = [CardFactory(content_phash=i) for i in range(1, 21)]

        def _everything_eligible(chunk: list[int]) -> list[int]:
            return list(chunk)

        walker_a: list[int] = []
        walker_b: list[int] = []
        for turn in range(20):
            target = walker_a if turn % 2 == 0 else walker_b
            ids, wrapped = _cursor_chunk_walk(StageESweepCursor.STAGE_C, _everything_eligible, 3)
            target.extend(ids)
            if wrapped:
                break

        assert set(walker_a).isdisjoint(walker_b)
        assert sorted(walker_a + walker_b) == sorted(card.pk for card in cards)
        assert len(walker_a + walker_b) == 20, "no card dispatched twice across the two walkers"


class TestCursorWalkStaysBounded:
    """Invariant the fixes above must not cost (issues #458/#460): every query a walk issues is
    shaped by `STAGE_E_SELECTION_CHUNK_SIZE`/`STAGE_E_SELECTION_SCAN_CAP`, never by catalog size.
    Asserted on captured query counts and on the compiled SQL's own LIMIT, not by inspection."""

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=10, STAGE_E_SELECTION_SCAN_CAP=40)
    def test_the_chunk_read_is_compiled_with_the_chunk_size_as_its_sql_limit(self, db: Any) -> None:
        catalog = []
        for i in range(1, 201):
            card = CardFactory(content_phash=i)
            _full_evidence(card)  # nothing eligible - forces the walk to spend its whole scan cap
            catalog.append(card)

        with CaptureQueriesContext(connection) as captured:
            found, wrapped = _cursor_chunk_walk(StageESweepCursor.STAGE_C, lambda chunk: [], 25)

        assert found == []
        assert wrapped is False  # scan cap hit with 160 candidates still ahead of the cursor
        chunk_reads = [
            q["sql"] for q in captured.captured_queries if "cardpicker_card" in q["sql"] and "LIMIT" in q["sql"]
        ]
        assert chunk_reads, "the walk must issue at least one chunk read"
        for sql in chunk_reads:
            assert "LIMIT 10" in sql, f"chunk read not bounded by STAGE_E_SELECTION_CHUNK_SIZE: {sql}"
        # SCAN_CAP=40 / CHUNK_SIZE=10 = exactly four chunk reads, whatever the catalog holds.
        assert len(chunk_reads) == 4
        cursor = StageESweepCursor.objects.get(name=StageESweepCursor.STAGE_C)
        # Exactly SCAN_CAP=40 candidates examined, never the 200 in the catalog.
        assert cursor.position == catalog[39].pk

    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=10, STAGE_E_SELECTION_SCAN_CAP=40)
    def test_dense_backlog_query_count_is_flat_regardless_of_catalog_size(self, db: Any) -> None:
        """The dense-drain fix must not have made cost depend on how much backlog is ahead: a call
        against a 30-card dense backlog and a call against a 600-card dense backlog issue the same
        number of queries."""
        for i in range(1, 31):
            CardFactory(content_phash=i)
        with CaptureQueriesContext(connection) as small_catalog:
            assert len(_select_micro_batch([], batch_size=5)) == 5

        StageESweepCursor.objects.all().delete()
        for i in range(31, 601):
            CardFactory(content_phash=i)
        with CaptureQueriesContext(connection) as large_catalog:
            assert len(_select_micro_batch([], batch_size=5)) == 5

        assert len(large_catalog.captured_queries) == len(small_catalog.captured_queries)


class TestWrapIsNotExhaustion:
    """2026-07-29 - the "a completed lap is reported as an empty backlog" defect, both legs.
    `_cursor_chunk_walk`'s second return value means "this walk crossed a lap boundary", and the
    sweep used to break on it with "Backlog exhausted - nothing left to dispatch." A live run on
    2026-07-28 did exactly that after 41 batches with the stage_c cursor at position 46,297 and
    `wrap_count` 7, mid-catalog against 230,753 cards."""

    def test_dispatch_micro_batch_reports_the_stage_c_walk_status_instead_of_discarding_it(self, db: Any) -> None:
        """Issue #468's own half: `_select_micro_batch` used to drop the flag, so a Stage-C
        cap-hit-empty and a genuinely-wrapped empty were the same "empty" status to any caller."""
        with override_settings(
            STAGE_E_STREAMING_ENABLED=True, STAGE_E_SELECTION_CHUNK_SIZE=1, STAGE_E_SELECTION_SCAN_CAP=1
        ):
            done = CardFactory(content_phash=1)
            _full_evidence(done)
            beyond_cap = CardFactory(content_phash=2)
            _full_evidence(beyond_cap)

            cap_hit = dispatch_micro_batch(card_ids=None)
            assert cap_hit.status == "empty"
            assert cap_hit.stage_c_backlog_found == 0
            assert cap_hit.stage_c_backlog_wrapped is False  # more pk space still unscanned ahead

            dispatch_micro_batch(card_ids=None)  # consumes the second (and last) candidate
            wrapped = dispatch_micro_batch(card_ids=None)
            assert wrapped.status == "empty"
            assert wrapped.stage_c_backlog_wrapped is True  # ran off the end of the pk space

    @STREAMING_ON
    def test_a_wrap_with_work_still_outstanding_does_not_end_the_sweep(
        self, db: Any, capsys: pytest.CaptureFixture
    ) -> None:
        """The cursor starts PAST the only eligible card, so backlog (b)'s very first walk wraps
        having found nothing - while a card that has never had a Stage D pass sits behind it. Under
        the pre-fix break-on-wrap rule the sweep printed "Backlog exhausted" and ended with that
        card unvoted and no other recovery path (django-q2 runs `max_attempts=1`)."""
        card = CardFactory(name="Some Card", content_phash=1)
        printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
        _full_evidence(card, collector_line_set_code="mom", collector_line_collector_number="158")
        StageESweepCursor.objects.create(name=StageESweepCursor.STAGE_D, position=card.pk)

        call_command("stream_backstop_sweep", "--max-batches", "10")

        output = capsys.readouterr().out
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk, "the card behind the wrapping cursor still got swept"
        assert "batches_dispatched=1" in output
        # And once BOTH cursors have a complete, empty observed lap behind them, the sweep does
        # still conclude - on evidence this time, and worded as the evidence it actually has.
        assert "Backlog exhausted - a full lap of both sweep cursors dispatched nothing." in output

    @STREAMING_ON
    def test_a_genuinely_empty_backlog_still_terminates_and_promptly(
        self, db: Any, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fix that never concludes "done" would be worse than the bug. With nothing eligible,
        each walk runs straight off the end of the pk space, so the arming lap and the proving lap
        are one iteration each - two `dispatch_micro_batch` calls, not `--max-batches` of them."""
        for i in range(1, 4):
            _voted_card(content_phash=i)

        from cardpicker.management.commands import stream_backstop_sweep as sweep_module

        real_dispatch = sweep_module.dispatch_micro_batch
        calls = {"n": 0}

        def _counting_dispatch(*args: Any, **kwargs: Any) -> Any:
            calls["n"] += 1
            return real_dispatch(*args, **kwargs)

        monkeypatch.setattr(sweep_module, "dispatch_micro_batch", _counting_dispatch)

        call_command("stream_backstop_sweep", "--max-batches", "1000")

        output = capsys.readouterr().out
        assert "Backlog exhausted - a full lap of both sweep cursors dispatched nothing." in output
        assert "batches_dispatched=0" in output
        assert calls["n"] == 2, "an empty backlog must cost one arming lap plus one proving lap"
        assert PilotRunLedger.objects.count() == 0

    @STREAMING_ON
    @override_settings(STAGE_E_SELECTION_CHUNK_SIZE=250, STAGE_E_SELECTION_SCAN_CAP=1000)
    def test_a_dense_stage_c_backlog_is_fully_swept_in_one_invocation(
        self, db: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """End-to-end version of the dense-drain fix, through the sweep command itself: 120 cards
        with no evidence at all, `--batch-size 25`. Pre-fix the first batch claimed the whole
        120-card chunk, dispatched 25, and the next walk wrapped - so a single invocation left 95
        cards untouched behind a cursor that had already passed them."""
        cards = [CardFactory(content_phash=i) for i in range(1, 121)]
        _install_stage_c_stub(monkeypatch, fetch_result=_png_bytes())

        call_command("stream_backstop_sweep", "--max-batches", "50", "--batch-size", "25")

        capsys.readouterr()
        evidenced = set(
            ImageEvidence.objects.filter(
                card_id__in=[c.pk for c in cards], extractor_versions__contains=MANIFEST_EXTRACTOR_CURRENT_VERSIONS
            ).values_list("card_id", flat=True)
        )
        assert evidenced == {c.pk for c in cards}, "every card in the dense backlog was swept in ONE invocation"


class TestEvidenceTransferInDispatch:
    """Issue #473 PR-2's evidence transfer, wired into `_run_stage_c`'s own phase 1 (checked
    BEFORE a card is ever handed to the fetch-ahead thread)."""

    @STREAMING_ON
    def test_md5_sibling_transfers_without_ever_fetching(self, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        sibling = CardFactory(name="Sibling", md5_checksum="abc123", content_phash=111)
        target = CardFactory(name="Target", md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
            symbol_phash=999,
        )

        def _fail_if_called(card: Any, dpi: Any = None) -> Any:
            raise AssertionError("a transfer-eligible card must never reach the fetch stage")

        _install_stage_c_stub(monkeypatch, fetch_result=_fail_if_called)

        outcome = dispatch_micro_batch(card_ids=[target.pk])

        assert outcome.status == "completed"
        assert outcome.stage_c_completed == 1
        assert outcome.stage_c_transferred == 1
        evidence = ImageEvidence.objects.get(card=target)
        assert evidence.transferred is True
        assert evidence.transferred_from_card_id == sibling.pk
        assert evidence.symbol_phash == 999
        assert evidence.md5_checksum == "abc123"

    @STREAMING_ON
    def test_a_real_extraction_card_alongside_a_transfer_card_both_land(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sibling = CardFactory(name="Sibling", md5_checksum="abc123", content_phash=111)
        transfer_target = CardFactory(name="Target", md5_checksum="abc123", content_phash=111)
        ImageEvidenceFactory(
            card=sibling,
            content_hash=111,
            md5_checksum="abc123",
            extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
        )
        real_card = CardFactory(name="Real", content_phash=222)  # no md5 - always real extraction

        fetched_card_ids: list[int] = []

        def _tracking_fetch(card: Any, dpi: Any = None) -> Any:
            fetched_card_ids.append(card.pk)
            return _png_bytes()

        _install_stage_c_stub(monkeypatch, fetch_result=_tracking_fetch)

        outcome = dispatch_micro_batch(card_ids=[transfer_target.pk, real_card.pk])

        assert outcome.stage_c_completed == 2
        assert outcome.stage_c_transferred == 1
        assert fetched_card_ids == [real_card.pk]  # the transfer target never hits the fetch stage
        assert ImageEvidence.objects.get(card=transfer_target).transferred is True
        assert ImageEvidence.objects.get(card=real_card).transferred is False


class TestDecoupledFetchAhead:
    """Issue #472's fetch-ahead thread + bounded queue, retrofitted into `_run_stage_c`."""

    @STREAMING_ON
    def test_fetch_ahead_overlaps_with_the_current_cards_own_compute(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves genuine OVERLAP, not just correctness: the second card's own fetch must start
        before the first card's own compute finishes - if fetch and compute were still bundled
        sequentially (the pre-#472 design), card B's fetch would only ever start AFTER card A's
        compute (and persist) had already completed."""
        card_a = CardFactory(name="A", content_phash=1)
        card_b = CardFactory(name="B", content_phash=2)
        events: list[tuple[str, int, float]] = []

        def fake_fetch(card: Any, dpi: Any = None) -> Any:
            events.append(("fetch_start", card.pk, time.monotonic()))
            time.sleep(0.05)
            events.append(("fetch_end", card.pk, time.monotonic()))
            return _png_bytes()

        def fake_compute(
            card_id: int,
            content_hash: Any,
            image: Any,
            fetch_latency_ms: float = 0.0,
            profile: Any = None,
            short_circuit: Any = None,
            known_set_codes: Any = None,
            artist_lexicon: Any = None,
            printing_artist_lookup: Any = None,
            md5_checksum: Any = None,
            sha256_checksum: Any = None,
        ) -> Any:
            events.append(("compute_start", card_id, time.monotonic()))
            time.sleep(0.1)
            events.append(("compute_end", card_id, time.monotonic()))
            return _stub_compute_card_evidence_ok()(
                card_id,
                content_hash,
                image,
                fetch_latency_ms,
                profile,
                short_circuit,
                known_set_codes,
                md5_checksum,
                sha256_checksum,
            )

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module
        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", fake_fetch)
        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", fake_compute)

        outcome = dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk])

        assert outcome.status == "completed"
        assert outcome.stage_c_completed == 2
        fetch_b_start = next(t for (name, cid, t) in events if name == "fetch_start" and cid == card_b.pk)
        compute_a_end = next(t for (name, cid, t) in events if name == "compute_end" and cid == card_a.pk)
        assert fetch_b_start < compute_a_end

    @STREAMING_ON
    def test_lockout_mid_prefetch_drains_the_already_fetched_card_but_starts_no_more(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card_a = CardFactory(name="A", content_phash=1)
        card_b = CardFactory(name="B", content_phash=2)
        card_c = CardFactory(name="C", content_phash=3)
        fetched_card_ids: list[int] = []

        def fake_fetch(card: Any, dpi: Any = None) -> Any:
            fetched_card_ids.append(card.pk)
            if card.pk == card_b.pk:
                raise GoogleFetchLockoutError("locked out")
            return _png_bytes()

        _install_stage_c_stub(monkeypatch, fetch_result=fake_fetch)

        outcome = dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk, card_c.pk])

        assert outcome.status == "completed-with-trip"
        # in-flight work drains: card A's already-fetched image still gets computed+persisted.
        assert ImageEvidence.objects.filter(card=card_a).count() == 1
        assert ImageEvidence.objects.filter(card=card_b).count() == 0
        assert ImageEvidence.objects.filter(card=card_c).count() == 0
        # halts NEW fetches immediately - card C is never even attempted.
        assert card_c.pk not in fetched_card_ids

    @STREAMING_ON
    def test_fetch_outcome_window_records_in_fetch_submission_order(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = [CardFactory(name=f"Card {i}", content_phash=i) for i in range(1, 5)]
        succeeds_by_pk = {cards[0].pk: True, cards[1].pk: False, cards[2].pk: True, cards[3].pk: False}

        def fake_fetch(card: Any, dpi: Any = None) -> Any:
            return _png_bytes() if succeeds_by_pk[card.pk] else None

        _install_stage_c_stub(monkeypatch, fetch_result=fake_fetch)

        outcome = dispatch_micro_batch(card_ids=[c.pk for c in cards])

        assert outcome.status == "completed"
        assert outcome.stage_c_fetch_failures == 2
        # the window's own recorded order matches the cards' own submission order, despite the
        # fetch-ahead thread running concurrently with compute - a single serial fetch worker's
        # own completion order IS its submission order (module docstring's own argument).
        assert list(stage_e_dispatch._window._window) == [True, False, True, False]

    @STREAMING_ON
    def test_a_non_lockout_fetch_crash_propagates_instead_of_hanging(
        self, db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression pin (2026-07-25, found during this PR's own review): an uncaught exception
        raised INSIDE the fetch-ahead thread must propagate to the caller, not silently hang the
        main thread's own `queue.get()` waiting for an outcome that will never arrive. Mirrors
        TestKillSafetyResumeContract's own mid-batch-crash scenario, narrowed to pin the fetch-ahead
        thread's own exception-forwarding mechanism specifically."""
        card_a = CardFactory(name="A", content_phash=1)
        card_b = CardFactory(name="B", content_phash=2)

        def fake_fetch(card: Any, dpi: Any = None) -> Any:
            if card.pk == card_b.pk:
                raise RuntimeError("simulated non-lockout fetch crash")
            return _png_bytes()

        _install_stage_c_stub(monkeypatch, fetch_result=fake_fetch)

        with pytest.raises(RuntimeError, match="simulated non-lockout fetch crash"):
            dispatch_micro_batch(card_ids=[card_a.pk, card_b.pk], run_id="crash-drill")

        ledger = PilotRunLedger.objects.get(run_id="crash-drill")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert "RuntimeError" in ledger.counters["failure_reason"]
        # card A's own already-fetched work still committed before the crash.
        assert ImageEvidence.objects.filter(card=card_a).count() == 1
        assert ImageEvidence.objects.filter(card=card_b).count() == 0

    @STREAMING_ON
    def test_a_compute_crash_does_not_wedge_the_fetch_ahead_thread(
        self, transactional_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression pin (Tron §8 gate condition 3, 2026-07-25, HIGH severity): a crash during
        COMPUTE (not fetch) - e.g. a PIL error decoding a corrupt download - must not wedge the
        fetch-ahead thread forever on a full `out_queue.put(...)` (see `_run_stage_c`'s own
        `finally` block docstring for the full mechanism this pins: `stop_event.set()` BEFORE
        `fetch_thread.join()`, plus draining the queue). More cards than the fetch-ahead queue
        depth so the fetch thread reliably races ahead of compute and is genuinely blocked on its
        own `put()` by the time compute raises - a bare `join()` with no signal/drain first would
        hang this test (and, in prod, wedge the dispatch slot with a lying RUNNING ledger row)
        indefinitely; the `run_thread.join(timeout=...)` below is what actually proves "does not
        hang" rather than merely "eventually completes if given long enough".

        `transactional_db`, not the plain `db` fixture (2026-07-25, found running this test):
        `dispatch_micro_batch` runs on a REAL background thread here (needed so the test itself can
        enforce a wall-clock timeout, since a hang is exactly the bug being pinned) - a thread with
        its own DB connection reading/writing against fixture data created inside the plain `db`
        fixture's own uncommitted SAVEPOINT-wrapped transaction is precisely the class of problem
        `test_run_image_evidence_cohort.py`'s own module docstring documents needing
        `transaction=True` for (real commit-and-truncate isolation, matching prod's own
        "no surrounding atomic block" shape) - the plain `db` fixture reproduced a SEPARATE,
        fixture-level hang (the background thread blocked waiting on the main thread's own
        transaction) that had nothing to do with the fetch-ahead bug this test exists to pin."""
        cards = [CardFactory(name=f"Card {i}", content_phash=i) for i in range(1, 6)]  # > queue depth

        def fake_fetch(card: Any, dpi: Any = None) -> Any:
            return _png_bytes()  # fast, no sleep - lets fetch race ahead of compute

        compute_calls = {"n": 0}

        def fake_compute(
            card_id: int,
            content_hash: Any,
            image: Any,
            fetch_latency_ms: float = 0.0,
            profile: Any = None,
            short_circuit: Any = None,
            known_set_codes: Any = None,
            artist_lexicon: Any = None,
            printing_artist_lookup: Any = None,
            md5_checksum: Any = None,
            sha256_checksum: Any = None,
        ) -> Any:
            compute_calls["n"] += 1
            if compute_calls["n"] == 2:
                raise RuntimeError("simulated compute-side crash")
            return _stub_compute_card_evidence_ok()(
                card_id,
                content_hash,
                image,
                fetch_latency_ms,
                profile,
                short_circuit,
                known_set_codes,
                md5_checksum,
                sha256_checksum,
            )

        import cardpicker.image_cdn_fetch as image_cdn_fetch_module
        import cardpicker.image_evidence as image_evidence_module

        monkeypatch.setattr(image_cdn_fetch_module, "fetch_card_image_bytes", fake_fetch)
        monkeypatch.setattr(image_evidence_module, "compute_card_evidence", fake_compute)

        result_holder: dict[str, Any] = {}

        def _run() -> None:
            try:
                dispatch_micro_batch(card_ids=[c.pk for c in cards], run_id="compute-crash-drill")
            except Exception as exc:  # noqa: BLE001 - captured for the assertion below, not swallowed
                result_holder["exc"] = exc

        run_thread = threading.Thread(target=_run, daemon=True)
        run_thread.start()
        run_thread.join(timeout=10)

        assert not run_thread.is_alive(), (
            "dispatch_micro_batch hung - the fetch-ahead thread was likely wedged on a full "
            "queue after the compute-side crash (Tron §8 gate condition 3)"
        )
        assert isinstance(result_holder.get("exc"), RuntimeError)
        ledger = PilotRunLedger.objects.get(run_id="compute-crash-drill")
        assert ledger.status == PilotRunLedger.Status.FAILED
