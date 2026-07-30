"""
END-TO-END COVER FOR THE MONOLITH (`manage.py run_pipeline`).

This suite drives the WHOLE command over a small fixture cohort and asserts that each stage ran
and produced rows - because the thing that ships in `run_pipeline.py` is the WIRING, and the only
defect class that matters for wiring is "a stage silently did not run". A unit test per stage
cannot catch that; the stages all had unit tests already, and were still not connected.

WHAT IS STUBBED, AND WHY IT IS EXACTLY THIS MUCH. Two seams, both of them the network:

  - `run_image_evidence_cohort._fetch_one_card` - the only place the pipeline touches the image
    CDN. The stub decides per card whether the "fetch" succeeded, which is how the propagation
    test below gets a cluster member with no evidence of its own.
  - `run_image_evidence_cohort._compute_one_card` - the CPU-bound extractor stage. The stub writes
    the `ImageEvidence` row a real extraction would have written. Running the real extractors
    would mean shipping real card images and a tesseract binary into this test for no wiring
    coverage at all: every extractor already has its own unit test, and none of them is what this
    file is about.
  - `run_pipeline.run_stage_zero_freshness` - a real Scryfall bulk download. Stage 0's own
    behaviour is covered by `test_stream_full_catalog.TestStageZeroFreshness`; what THIS file
    asserts is that the monolith calls it, once, at the front, and records the vintage it returned.

Everything downstream of those three - every Stage D calculator, all three attribute-chip casters,
the clustering, the propagation, the fidelity gate, `channel_report`, and every `run_id` handoff
between them - runs FOR REAL against the test database.

`transaction=True` throughout: `run_image_evidence_cohort.handle` closes its parent DB
connections before forking its pools (`_parent_connections.close_all()`), which under the plain
`django_db` marker's outer `atomic()` takes the `closed_in_transaction=True` path and makes the
next query raise. Same rule, same reason, as `test_run_image_evidence_cohort.py`'s own docstring.
"""

from typing import Any, Optional

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

from cardpicker.local_attribute_chip_cast import (
    BLEED_EDGE_CAST_ANONYMOUS_ID,
    FRAME_STYLE_CAST_ANONYMOUS_ID,
)
from cardpicker.local_calculate_verdicts import JOIN_KEY_ANONYMOUS_ID
from cardpicker.local_layout_class_cast import LAYOUT_CLASS_CAST_ANONYMOUS_ID
from cardpicker.management.commands import run_image_evidence_cohort as cohort_command
from cardpicker.management.commands import run_pipeline as pipeline_command
from cardpicker.management.commands.run_image_evidence_cohort import (
    MANIFEST_EXTRACTOR_CURRENT_VERSIONS,
)
from cardpicker.models import (
    CardPrintingTag,
    CardTagVote,
    ImageEvidence,
    PilotRunLedger,
)
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory

# A card whose name starts with this is treated by the fetch stub as a card the CDN could not
# serve. It therefore reaches Stage D with NO evidence row, abstains everywhere, and is the only
# way a distance-0 cluster member can still be missing a vote by the time propagation runs.
FETCH_FAILS_PREFIX = "FETCHFAIL"

CLUSTER_HASH = 0x0F0F0F0F0F0F0F0F
LONE_HASH = 0x1234567812345678

STAGE_ZERO_VINTAGE = {
    "remote_updated_at": "2026-07-30T00:00:00.000Z",
    "cache_path": "/tmp/default_cards.jsonl",
    "cache_age_days": 0.5,
    "refreshed": False,
    "import_stats": None,
}


class _SyncPoolStub:
    """Runs submitted work inline, so the pooled Stage C engine is exercised in-process."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "_SyncPoolStub":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        from concurrent.futures import Future

        future: "Future[Any]" = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - mirror a real pool's failure surfacing
            future.set_exception(exc)
        return future


def _stub_fetch(card_id: int, stop_event: Any, run_id: str = "", dry_run: bool = False) -> Any:
    from cardpicker.models import Card

    card = Card.objects.get(pk=card_id)
    if card.name.startswith(FETCH_FAILS_PREFIX):
        return cohort_command._FetchOutcome(card_id=card_id, outcome="fetch_failed", card_name=card.name)
    return cohort_command._FetchOutcome(
        card_id=card_id,
        content_hash=card.content_phash,
        md5_checksum=f"md5-{card_id}",
        sha256_checksum=f"sha-{card_id}",
        image_bytes=b"not-really-an-image",
        card_name=card.name,
    )


def _stub_compute(
    card_id: int,
    content_hash: Optional[int],
    image_bytes: Optional[bytes],
    fetch_latency_ms: float,
    dry_run: bool,
    run_id: str,
    profile: bool = False,
    short_circuit: Optional[bool] = None,
    known_set_codes: Optional[frozenset] = None,
    md5_checksum: Optional[str] = None,
    sha256_checksum: Optional[str] = None,
    card_artist_names: tuple = (),
) -> tuple:
    """
    Stands in for the extractor stage by writing the `ImageEvidence` row a real extraction of a
    well-behaved card would have written: a complete extractor manifest, a collector line that
    resolves against the fixture's `CanonicalCard`, and the three fields the attribute chips read
    (`layout_class` -> border, `collector_line_collector_number` + `illus_anchor_fired` -> frame
    style, `bleed_class` -> bleed edge).
    """
    if not dry_run:
        ImageEvidence.objects.update_or_create(
            card_id=card_id,
            defaults=dict(
                content_hash=content_hash or 0,
                run_id=run_id,
                extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
                fetch_ok=True,
                collector_line_raw_text="158/281 R",
                collector_line_set_code="mom",
                collector_line_collector_number="158",
                legal_line_proxy_marker_detected=False,
                symbol_phash=None,
                # Chip inputs. `trimmed` is the only bleed reading that casts a vote (the caster is
                # negative-only by design), and `black` is one of BORDER_COLOR_TO_TAG's keys.
                layout_class="black",
                bleed_class="trimmed",
                bleed_diff_mm=0.5,
                illus_anchor_fired=True,
            ),
        )
    return card_id, "ok", None, False


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cohort_command, "ThreadPoolExecutor", _SyncPoolStub)
    monkeypatch.setattr(cohort_command, "ProcessPoolExecutor", _SyncPoolStub)
    monkeypatch.setattr(cohort_command, "_fetch_one_card", _stub_fetch)
    monkeypatch.setattr(cohort_command, "_compute_one_card", _stub_compute)
    monkeypatch.setattr(
        pipeline_command,
        "run_stage_zero_freshness",
        lambda **kwargs: dict(STAGE_ZERO_VINTAGE),
    )


@pytest.fixture
def cohort(db: Any) -> dict[str, Any]:
    """
    Three cards and the reference row they resolve against.

    `representative` and `absorbed` share one `content_phash`, so they form a distance-0 cluster;
    `compute_exact_match_clusters` makes the LOWEST pk the representative, which is why the
    representative is created first. `absorbed`'s name makes the fetch stub fail it, so it reaches
    Stage D with no evidence and abstains - leaving it as the one card in the fixture whose only
    possible vote is a propagated one.
    """
    call_command("seed_default_tags")
    call_command("seed_attribute_tags")
    call_command("seed_sensitive_tags")

    printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
    representative = CardFactory(name="Some Card", content_phash=CLUSTER_HASH)
    absorbed = CardFactory(name=f"{FETCH_FAILS_PREFIX} Some Card", content_phash=CLUSTER_HASH)
    lone = CardFactory(name="Some Card", content_phash=LONE_HASH)
    return {"printing": printing, "representative": representative, "absorbed": absorbed, "lone": lone}


def _run(*argv: str, run_id: str = "test-monolith") -> None:
    call_command("run_pipeline", "--run-id", run_id, *argv)


# ==================================================================================================
# THE END-TO-END PASS
# ==================================================================================================
@pytest.mark.django_db(transaction=True)
class TestEndToEndPass:
    def test_a_bare_invocation_runs_every_stage_and_produces_rows(
        self, cohort: dict[str, Any], capsys: pytest.CaptureFixture
    ) -> None:
        """
        The whole point of the command, in one assertion block: no flag is required, and each of
        the seven stages both RAN and left evidence that it ran.
        """
        _run()
        out = capsys.readouterr().out

        ledger = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        counters = ledger.counters

        # Stage 0 ran and its bulk-file VINTAGE is on the run's own ledger row, so this run's
        # conclusions can be dated.
        assert counters["stage_0"]["remote_updated_at"] == STAGE_ZERO_VINTAGE["remote_updated_at"]

        # Stage E preflight ran.
        assert "operating envelope clear" in out

        # Stage C ran, stamped its rows with THIS run_id, and filled bleed_diff_mm on the way -
        # the field that was 97.9% NULL and that the brief says needs no separate backfill.
        evidence = ImageEvidence.objects.filter(run_id="test-monolith")
        assert evidence.count() == 2  # the two fetchable cards
        assert evidence.filter(bleed_diff_mm__isnull=True).count() == 0

        # Stage D ran: the join-key calculator resolved the fixture's collector line.
        assert CardPrintingTag.objects.filter(
            run_id="test-monolith", anonymous_id=JOIN_KEY_ANONYMOUS_ID, is_no_match=False
        ).exists()
        assert counters["stage_d"]["join_key_votes"] >= 1

        # All THREE attribute-chip families produced rows. These were conveyor-only before this
        # command existed, and two of them sat at literally zero machine rows.
        for identity in (
            LAYOUT_CLASS_CAST_ANONYMOUS_ID,
            FRAME_STYLE_CAST_ANONYMOUS_ID,
            BLEED_EDGE_CAST_ANONYMOUS_ID,
        ):
            assert CardTagVote.objects.filter(
                run_id="test-monolith", anonymous_id=identity
            ).exists(), f"no chip votes for {identity}"

        # Clustering ran and found the distance-0 pair.
        assert counters["clustering"]["cluster_count"] == 1
        assert counters["clustering"]["cards_absorbed_into_clusters"] == 1

        # The fidelity gate ran, INSPECTED CARDS, and is clear - a machine vote alone must never
        # resolve a card. Asserting the count alone would survive the gate never being called at
        # all, since "no violations" and "never looked" produce the same zero.
        assert counters["fidelity_gate"]["violations"] == 0
        assert "FIDELITY GATE: clear over " in out

        # channel_report ran at the end and its verdict is REPORTED, not folded into the exit.
        # The banner and the exit line are printed by THIS command either way, so they cannot
        # distinguish "the report ran" from "the call was deleted"; the roster family title is
        # emitted only by channel_report itself.
        assert "CHANNEL REPORT" in out
        assert "channel_report exit=" in out
        assert "VOTE CHANNELS" in out

    def test_cluster_propagation_gives_an_unfetched_member_its_groups_verdict(self, cohort: dict[str, Any]) -> None:
        """
        THE HIGHEST-VALUE CARRIED FEATURE. `absorbed` never fetched, never extracted and never
        reached any Stage D calculator with evidence - so on its own it has no printing vote at
        all. Because its stored `content_phash` is bit-identical to `representative`'s, it
        inherits `representative`'s verdict, under the same identity, with no fetch of its own.
        """
        _run()

        representative_vote = CardPrintingTag.objects.get(
            card_id=cohort["representative"].pk,
            anonymous_id=JOIN_KEY_ANONYMOUS_ID,
            run_id="test-monolith",
        )
        absorbed_vote = CardPrintingTag.objects.get(card_id=cohort["absorbed"].pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID)

        assert absorbed_vote.printing_id == representative_vote.printing_id
        assert absorbed_vote.confidence == representative_vote.confidence
        assert absorbed_vote.run_id == "test-monolith"
        # It genuinely never had evidence - the vote cannot have come from a calculator.
        assert not ImageEvidence.objects.filter(card_id=cohort["absorbed"].pk).exists()

        ledger = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert ledger.counters["clustering"]["votes_propagated"] == 1

    def test_the_run_id_is_printed_at_the_start_and_at_the_end(
        self, cohort: dict[str, Any], capsys: pytest.CaptureFixture
    ) -> None:
        """The run's identity is the only thing that marks its output, so it must be impossible to
        miss in a terminal an operator scrolls back through later."""
        _run(run_id="shakedown-01")
        out = capsys.readouterr().out
        assert "MONOLITH RUN  run_id=shakedown-01" in out
        assert "MONOLITH DONE  run_id=shakedown-01" in out
        assert "To resume this run after a stop: --run-id shakedown-01" in out

    def test_a_default_run_id_is_self_describing_not_an_opaque_timestamp(self, cohort: dict[str, Any]) -> None:
        call_command("run_pipeline")
        row = PilotRunLedger.objects.get(command="run_pipeline")
        assert row.run_id.startswith("monolith-")
        assert row.run_id.endswith(pipeline_command.LEDGER_RUN_ID_SUFFIX)

    def test_a_fresh_run_id_redoes_stage_c_from_scratch(self, cohort: dict[str, Any]) -> None:
        """
        The from-scratch default, at the seam that used to break it: Stage C's resume filter is
        run-scoped (PR #645), so a second run under a NEW run_id re-extracts every card rather
        than skipping cards a previous run finished.
        """
        _run(run_id="run-a")
        assert ImageEvidence.objects.filter(run_id="run-a").count() == 2

        _run(run_id="run-b")
        assert ImageEvidence.objects.filter(run_id="run-b").count() == 2
        assert ImageEvidence.objects.filter(run_id="run-a").count() == 0  # re-stamped, not skipped

    def test_a_failure_marks_the_ledger_row_failed_with_a_reason(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("stage d exploded")

        monkeypatch.setattr(pipeline_command, "_run_stage_d", _boom)
        with pytest.raises(RuntimeError):
            _run()
        row = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert row.status == PilotRunLedger.Status.FAILED
        assert "stage d exploded" in row.counters["failure_reason"]


# ==================================================================================================
# THE MUTATION TABLE - unwire a stage, go red
# ==================================================================================================
@pytest.mark.django_db(transaction=True)
class TestUnwiringAStageIsCaught:
    """
    Each case below simulates the exact regression this suite exists to catch: a stage that stops
    being called while the command still exits 0. The disable flags are the honest stand-in for
    "someone deleted the call" - they take the same code path (the stage does not run) without
    needing to monkeypatch the module under test into a shape it cannot really have.

    | stage unwired      | flag                    | the assertion that goes red                 |
    |--------------------|-------------------------|---------------------------------------------|
    | Stage 0            | --skip-freshness        | no bulk-file vintage on the ledger row      |
    | Stage C            | --skip-stage-c          | no ImageEvidence rows for this run          |
    | Stage D            | --skip-stage-d          | no printing votes, no chip votes            |
    | attribute chips    | (Stage D carries them)  | covered by the Stage D row above            |
    | clustering         | --skip-clustering       | the unfetched member never gets a verdict   |
    | fidelity gate      | --skip-gate             | no gate result recorded                     |
    | channel_report     | --skip-channel-report   | the report never runs                       |
    """

    def test_unwiring_stage_zero_loses_the_bulk_file_vintage(self, cohort: dict[str, Any]) -> None:
        _run("--skip-freshness")
        counters = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline").counters
        assert counters["stage_0"] == {"skipped": True, "reason": "--skip-freshness"}
        assert "remote_updated_at" not in counters["stage_0"]

    def test_unwiring_stage_c_produces_no_evidence(self, cohort: dict[str, Any]) -> None:
        _run("--skip-stage-c")
        assert not ImageEvidence.objects.filter(run_id="test-monolith").exists()

    def test_unwiring_stage_d_produces_no_printing_votes_and_no_chips(self, cohort: dict[str, Any]) -> None:
        _run("--skip-stage-d")
        assert not CardPrintingTag.objects.filter(run_id="test-monolith", anonymous_id=JOIN_KEY_ANONYMOUS_ID).exists()
        for identity in (
            LAYOUT_CLASS_CAST_ANONYMOUS_ID,
            FRAME_STYLE_CAST_ANONYMOUS_ID,
            BLEED_EDGE_CAST_ANONYMOUS_ID,
        ):
            assert not CardTagVote.objects.filter(run_id="test-monolith", anonymous_id=identity).exists()

    def test_unwiring_clustering_leaves_the_unfetched_member_with_no_verdict(self, cohort: dict[str, Any]) -> None:
        """The mutation that matters most: with propagation unwired the command still exits 0 and
        Stage D still reports votes, but the distance-0 member silently disagrees with its own
        identity group by having no verdict at all."""
        _run("--skip-clustering")
        assert not CardPrintingTag.objects.filter(card_id=cohort["absorbed"].pk).exists()

    def test_unwiring_the_gate_records_no_gate_result(self, cohort: dict[str, Any]) -> None:
        _run("--skip-gate")
        counters = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline").counters
        assert counters["fidelity_gate"] == {"skipped": True}

    def test_unwiring_channel_report_never_runs_it(self, cohort: dict[str, Any], capsys: pytest.CaptureFixture) -> None:
        _run("--skip-channel-report")
        assert "CHANNEL REPORT" not in capsys.readouterr().out


# ==================================================================================================
# STAGE E - the envelope actually gates
# ==================================================================================================
@pytest.mark.django_db(transaction=True)
class TestEnvelopeGating:
    def test_an_open_trip_halts_before_anything_is_written(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Trip:
            trip_id = "envtrip-test"
            bar = "host_load"

        monkeypatch.setattr(pipeline_command, "current_trip", lambda run_id=None: _Trip())
        with pytest.raises(CommandError) as excinfo:
            _run()
        assert excinfo.value.returncode == pipeline_command.EXIT_ENVELOPE_HALT
        assert not ImageEvidence.objects.filter(run_id="test-monolith").exists()

    def test_a_fresh_breach_halts_before_anything_is_written(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Trip:
            trip_id = "envtrip-fresh"
            bar = "rss"
            detail = "rss over ceiling"

        monkeypatch.setattr(pipeline_command, "current_trip", lambda run_id=None: None)
        monkeypatch.setattr(pipeline_command, "check_envelope", lambda signals, run_id=None: _Trip())
        with pytest.raises(CommandError) as excinfo:
            _run()
        assert excinfo.value.returncode == pipeline_command.EXIT_ENVELOPE_HALT
        assert not ImageEvidence.objects.filter(run_id="test-monolith").exists()

    def test_skip_envelope_lets_the_run_proceed(self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        class _Trip:
            trip_id = "envtrip-test"
            bar = "host_load"

        monkeypatch.setattr(pipeline_command, "current_trip", lambda run_id=None: _Trip())
        _run("--skip-envelope")
        assert ImageEvidence.objects.filter(run_id="test-monolith").exists()


# ==================================================================================================
# STAGE 0 - once, at the front
# ==================================================================================================
@pytest.mark.django_db(transaction=True)
class TestStageZeroIsCalledOnceAtTheFront:
    def test_stage_zero_runs_exactly_once_and_before_stage_c(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The binding constraint inherited from `stream_full_catalog`: a refresh rewrites
        `CanonicalPrintingMetadata`, which is the table Stage D's illustration deduction builds its
        index from. Refreshing more than once - or after Stage C has started - would have early
        and late cards deduced against different reference sets under one run_id.
        """
        calls: list[str] = []

        def _record_stage_zero(**kwargs: Any) -> dict[str, Any]:
            calls.append("stage_0")
            return dict(STAGE_ZERO_VINTAGE)

        def _record_fetch(*args: Any, **kwargs: Any) -> Any:
            calls.append("stage_c")
            return _stub_fetch(*args, **kwargs)

        monkeypatch.setattr(pipeline_command, "run_stage_zero_freshness", _record_stage_zero)
        monkeypatch.setattr(cohort_command, "_fetch_one_card", _record_fetch)

        _run()

        assert calls.count("stage_0") == 1
        assert calls[0] == "stage_0"

    def test_require_fresh_is_forwarded(self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return dict(STAGE_ZERO_VINTAGE)

        monkeypatch.setattr(pipeline_command, "run_stage_zero_freshness", _capture)
        _run("--require-fresh")
        assert seen["require_fresh"] is True


# ==================================================================================================
# WRITE POLARITY - the monolith writes by default; only --dry-run prevents it
# ==================================================================================================
@pytest.mark.django_db(transaction=True)
class TestWritesByDefault:
    """
    Owner ruling: "the eventual intention for the monolith is that default is to write and flags
    are what prevents it. (opposite)". This is the inverse of every organ the monolith calls, and
    the failure it guards against is the dangerous one - a pass that computes everything, logs
    everything, reports success and persists nothing is indistinguishable from a working run
    except by row counts, and on a 230k pass that is hours before anyone notices.

    THE ORGAN TABLE. Every write-capable organ this command reaches, its own gate, and what the
    monolith passes. A mutation restoring any organ's own default must fail
    `test_every_organ_persists_rows_with_no_flags` below.

    | organ                        | its own gate            | monolith passes           |
    |------------------------------|-------------------------|---------------------------|
    | import_scryfall_printing_... | none (always writes)    | called; skipped on dry-run|
    | run_image_evidence_cohort    | --dry-run (write-first) | forwards --dry-run only   |
    | run_join_key_calculator      | dry_run=True default    | dry_run=False             |
    | run_fallback_calculator      | dry_run=True default    | dry_run=False             |
    | run_illustration_calculator  | dry_run=True default    | dry_run=False             |
    | run_slow_path_calculator     | dry_run=True default    | dry_run=False             |
    | run_layout_class_cast        | dry_run=True default    | dry_run=False             |
    | run_attribute_chip_cast      | dry_run=True default    | dry_run=False             |
    | cluster vote propagation     | none (this command's)   | gated on `not dry_run`    |
    """

    def test_every_organ_persists_rows_with_no_flags(self, cohort: dict[str, Any]) -> None:
        """A bare invocation - no flags at all - must leave rows behind from EVERY organ."""
        _run()

        assert ImageEvidence.objects.filter(run_id="test-monolith").exists(), "Stage C wrote nothing"
        assert CardPrintingTag.objects.filter(
            run_id="test-monolith", anonymous_id=JOIN_KEY_ANONYMOUS_ID
        ).exists(), "the join-key calculator wrote nothing"
        for identity in (
            LAYOUT_CLASS_CAST_ANONYMOUS_ID,
            FRAME_STYLE_CAST_ANONYMOUS_ID,
            BLEED_EDGE_CAST_ANONYMOUS_ID,
        ):
            assert CardTagVote.objects.filter(
                run_id="test-monolith", anonymous_id=identity
            ).exists(), f"the {identity} caster wrote nothing"
        assert CardPrintingTag.objects.filter(
            card_id=cohort["absorbed"].pk
        ).exists(), "cluster propagation wrote nothing"

    def test_dry_run_persists_nothing_through_any_organ(self, cohort: dict[str, Any]) -> None:
        """A dry run that writes through ONE organ is worse than no dry run, because it is
        trusted. Nothing may reach the database through any of them."""
        _run("--dry-run")

        assert not ImageEvidence.objects.filter(run_id="test-monolith").exists()
        assert not CardPrintingTag.objects.filter(run_id="test-monolith").exists()
        assert not CardTagVote.objects.filter(run_id="test-monolith").exists()
        assert not CardPrintingTag.objects.filter(card_id=cohort["absorbed"].pk).exists()

    def test_dry_run_still_runs_every_stage_and_reports_what_it_would_write(
        self, cohort: dict[str, Any], capsys: pytest.CaptureFixture
    ) -> None:
        """A dry run must be a genuinely useful preview of a 230k pass, not a plan: every stage
        executes and reports, and it exits 0 because it did what was asked."""
        _run("--dry-run")
        out = capsys.readouterr().out

        assert "mode=DRY-RUN (writes nothing)" in out
        assert "STAGE 0 skipped (--dry-run)" in out
        assert "operating envelope clear" in out
        assert "STAGE C:" in out
        assert "STAGE D:" in out
        assert "STAGE C+:" in out
        assert "CHANNEL REPORT" in out
        assert "MONOLITH DONE" in out

        row = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert row.dry_run is True
        assert row.status == PilotRunLedger.Status.COMPLETED

    def test_stage_d_is_handed_write_mode_explicitly_never_by_inheritance(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The pin. `_run_stage_d`'s own `dry_run` parameter defaults to False, but the monolith must
        pass it EXPLICITLY - a future edit that drops the argument would silently re-inherit
        whatever that default becomes. This asserts the argument is actually sent.
        """
        seen: dict[str, Any] = {}

        def _capture(batch_ids: Any, run_id: str, outcome: Any, dry_run: bool = True) -> None:
            seen["dry_run"] = dry_run

        monkeypatch.setattr(pipeline_command, "_run_stage_d", _capture)
        _run()
        assert seen["dry_run"] is False

        seen.clear()
        _run("--dry-run", run_id="test-monolith-dry")
        assert seen["dry_run"] is True

    def test_a_bare_run_never_trips_the_forced_dry_run_precondition(self, cohort: dict[str, Any]) -> None:
        """
        `enforce_dry_run_precondition` (issue #362) is a FORCED dry-run, not just a default, and it
        would put a flag in front of the working run if it applied. Stage C arms it only for a
        `--card-ids-file` write (`write_mode=(not dry_run) and bool(card_ids_file_for_scope)`), and
        a bare monolith run goes down the `--limit` path - so it must be a no-op here.
        """
        _run()  # would raise CommandError("FORCED DRY-RUN GUARD: ...") if the guard applied
        assert ImageEvidence.objects.filter(run_id="test-monolith").exists()
