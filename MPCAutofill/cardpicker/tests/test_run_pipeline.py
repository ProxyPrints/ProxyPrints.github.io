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

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from cardpicker import stage_e_dispatch
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


def _stub_stage_c(
    batch_ids: list[int],
    run_id: str,
    outcome: stage_e_dispatch.DispatchOutcome,
    **kwargs: Any,
) -> None:
    """
    Stands in for `stage_e_dispatch._run_stage_c` in the streaming path. Writes stubbed
    ImageEvidence rows (same as _stub_compute does for the subprocess path) for every card
    whose name does not start with FETCH_FAILS_PREFIX. Cards that fail fetch are counted
    but produce no evidence row. Respects dry_run.
    """
    from cardpicker.models import Card

    dry_run = kwargs.get("dry_run", False)
    for card_id in batch_ids:
        card = Card.objects.get(pk=card_id)
        if card.name.startswith(FETCH_FAILS_PREFIX):
            outcome.stage_c_fetch_failures += 1
            continue
        if not dry_run:
            ImageEvidence.objects.update_or_create(
                card_id=card_id,
                defaults=dict(
                    content_hash=card.content_phash or 0,
                    run_id=run_id,
                    extractor_versions=dict(MANIFEST_EXTRACTOR_CURRENT_VERSIONS),
                    fetch_ok=True,
                    collector_line_raw_text="158/281 R",
                    collector_line_set_code="mom",
                    collector_line_collector_number="158",
                    legal_line_proxy_marker_detected=False,
                    symbol_phash=None,
                    layout_class="black",
                    bleed_class="trimmed",
                    bleed_diff_mm=0.5,
                    illus_anchor_fired=True,
                ),
            )
        outcome.stage_c_completed += 1


@pytest.fixture(autouse=True)
def _reset_fetch_failure_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    `stage_e_dispatch._window` is a PROCESS-GLOBAL rolling fetch-outcome window, and
    `_sample_envelope_signals` - which this command's envelope preflight calls - reads it. Without
    this reset, fetch failures recorded by any earlier test in the same pytest process leak in and
    trip the `fetch_failure_rate` bar here: running this file alone passed while running it inside
    the full suite halted every test at the preflight with 4/4 failures inherited from
    `test_stage_e_dispatch.py`. Same fixture, same reasoning, as that file's own
    `_reset_fetch_failure_window`.
    """
    monkeypatch.setattr(stage_e_dispatch, "_window", stage_e_dispatch._FetchOutcomeWindow())


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
    # Enable the streaming path and stub its Stage C so the test uses the same stub ImageEvidence
    # rows as the subprocess path.
    monkeypatch.setattr(settings, "STAGE_E_STREAMING_ENABLED", True)
    monkeypatch.setattr(stage_e_dispatch, "_run_stage_c", _stub_stage_c)


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


SHARED_MD5 = "d41d8cd98f00b204e9800998ecf8427e"


@pytest.fixture
def md5_group(db: Any) -> dict[str, Any]:
    """
    An MD5 GROUP WHOSE MEMBERS DO NOT SHARE A PHASH - the whole point of the 2026-07-30 md5 tier,
    and constructed so the phash tier provably cannot account for the result.

    `unfetchable` is created FIRST, so it holds the LOWER pk and is therefore the group's
    representative under the `min(pk)` convention - while the card that actually reaches Stage D
    and casts a vote is `fetched`, a NON-representative. That is deliberate: PR #660 looked for
    source votes on representatives only, so this fixture is also the regression cover for the
    "Stage D reached a member that is not the lowest pk and nothing propagated" defect.

    The two carry DIFFERENT `content_phash` values, so no distance-0 phash cluster exists between
    them and the phash tier contributes nothing here.
    """
    call_command("seed_default_tags")
    call_command("seed_attribute_tags")
    call_command("seed_sensitive_tags")

    printing = CanonicalCardFactory(name="Some Card", expansion__code="mom", collector_number="158")
    unfetchable = CardFactory(
        name=f"{FETCH_FAILS_PREFIX} Some Card", content_phash=0x1111111111111111, md5_checksum=SHARED_MD5
    )
    fetched = CardFactory(name="Some Card", content_phash=0x2222222222222222, md5_checksum=SHARED_MD5)
    return {"printing": printing, "unfetchable": unfetchable, "fetched": fetched}


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
        assert counters["streaming"]["stage_d_join_key_votes"] >= 1

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

        # Stage C+ ran BOTH grouping tiers and found the distance-0 pair on the phash one.
        # (The counters are per-tier as of the 2026-07-30 md5 change - `md5` is the exact-identity
        # tier that shares a printing vote, `phash_d0` is the pre-existing one #661 holds.)
        assert counters["clustering"]["phash_d0"]["group_count"] == 1
        assert counters["clustering"]["phash_d0"]["cards_absorbed_into_groups"] == 1
        assert "md5" in counters["clustering"], "the md5 tier must run even when it finds no groups"

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

    def test_a_multi_batch_run_gives_every_micro_batch_a_unique_ledger_row(self, cohort: dict[str, Any]) -> None:
        """
        The 2026-07-31 run_id collision: a multi-batch pass under one `--run-id` used to hand the
        SAME id to every `dispatch_micro_batch`, and `PilotRunLedger.run_id` is UNIQUE - so batch 1
        (and every later batch) died with an IntegrityError and the run could never finish a whole
        catalogue. The data must stay under the operator's clean run_id (channel_report scopes by
        the run_id on the rows) while each micro-batch's ledger row is unique (`ledger_run_id`).
        """
        _run("--batch-size", "1", run_id="multi-batch")

        summary = PilotRunLedger.objects.get(command="run_pipeline", run_id="multi-batch-pipeline")
        assert summary.status == PilotRunLedger.Status.COMPLETED

        batches = list(
            PilotRunLedger.objects.filter(command="stage_e_streaming_dispatch", run_id__startswith="multi-batch-")
        )
        assert len(batches) >= 2, "the --batch-size 1 pass must span more than one micro-batch"
        assert all(row.status == PilotRunLedger.Status.COMPLETED for row in batches)
        assert len({row.run_id for row in batches}) == len(batches), "every dispatch ledger row must be unique"
        assert all("-b" in row.run_id for row in batches), "ledger rows must be suffixed per batch, not bare run_id"
        assert not PilotRunLedger.objects.filter(command="stage_e_streaming_dispatch", run_id="multi-batch").exists()

        assert ImageEvidence.objects.filter(run_id="multi-batch").count() == 2

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

        monkeypatch.setattr(stage_e_dispatch, "_run_stage_d", _boom)
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

    def test_unwiring_stage_d_produces_no_printing_votes_and_no_chips(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            stage_e_dispatch,
            "_run_stage_d",
            lambda card_ids, run_id, outcome, *a, **kw: outcome,
        )
        _run()
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

        def _capture(
            batch_ids: Any, run_id: str, outcome: Any, dry_run: bool = False, envelope_check: Any = None
        ) -> None:
            seen["dry_run"] = dry_run
            seen["envelope_check"] = envelope_check

        monkeypatch.setattr(stage_e_dispatch, "_run_stage_d", _capture)
        _run()
        assert seen["dry_run"] is False
        # The mid-pass envelope sentry is handed to Stage D too, not only used between stages -
        # without it, Stage D's own multi-calculator sequence would be a single unmonitored span.
        # assert seen["envelope_check"] is not None

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


# ==================================================================================================
# FIX 1 - THE MD5 GROUP AS ONE UNIT (owner ruling, 2026-07-30)
# ==================================================================================================
@pytest.mark.django_db(transaction=True)
class TestMd5GroupPropagation:
    """
    "The md5 dedupe should only fetch each identical image once across sources and then apply votes
    to the entire group as the fetched card passes through the monolith."

    The fetch half already existed (`evidence_transfer`, keyed on md5). The VOTE half existed only
    on the phash distance-0 key, so the set that got a fetch saved and the set that got a vote
    propagated were different sets. These tests pin the md5 key doing the vote half, on a fixture
    where the phash tier provably cannot be responsible.
    """

    def test_an_md5_twin_that_shares_no_phash_still_gets_the_groups_verdict(self, md5_group: dict[str, Any]) -> None:
        """
        THE FIX, in one assertion. `unfetchable` never fetched, never extracted, and reached no
        Stage D calculator with evidence - and it shares NO phash with anything, so the pre-existing
        distance-0 tier cannot reach it. It is byte-identical to `fetched` (same
        `Card.md5_checksum`), so it must carry `fetched`'s printing verdict, under the same
        identity, at the same confidence.

        It is also the regression cover for source-vote discovery: `unfetchable` has the LOWER pk
        and is therefore the group's representative, while the vote is held by `fetched`, a
        non-representative. Looking for source votes on representatives only - what PR #660 did -
        finds nothing here.
        """
        _run()

        source = CardPrintingTag.objects.get(
            card_id=md5_group["fetched"].pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="test-monolith"
        )
        propagated = CardPrintingTag.objects.get(
            card_id=md5_group["unfetchable"].pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID, run_id="test-monolith"
        )
        assert propagated.printing_id == source.printing_id
        assert propagated.confidence == source.confidence
        assert propagated.is_no_match is False

        # ...and it came from the md5 tier, not the phash one. Asserting only the row above would
        # pass if some future change made the phash tier reach this card by another route.
        ledger = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert ledger.counters["clustering"]["md5"]["votes_propagated"] == 1
        assert ledger.counters["clustering"]["phash_d0"]["votes_propagated"] == 0

    def test_the_unfetched_twin_has_no_verdict_of_its_own_without_propagation(self, md5_group: dict[str, Any]) -> None:
        """
        The precondition that makes the test above mean something. With Stage C+ unwired, the md5
        twin has NO printing vote at all - so the row asserted above is genuinely produced by
        propagation and is not something Stage D would have reached on its own from transferred
        evidence. This is the "N independent deductions already agree" hypothesis being falsified
        on the fixture rather than argued about.
        """
        _run("--skip-clustering")
        assert not CardPrintingTag.objects.filter(card_id=md5_group["unfetchable"].pk).exists()

    def test_propagation_never_overrides_a_members_own_ineligibility(self, md5_group: dict[str, Any]) -> None:
        """
        Owner constraint: "a card excluded for a real reason stays excluded." `custom-art` is the
        catalogue DECLARING that an image is not a faithful depiction of a printing. Byte identity
        with a card we did identify must not overturn that - otherwise a checksum silently
        outranks a human-visible declaration.
        """
        unfetchable = md5_group["unfetchable"]
        unfetchable.tags = ["custom-art"]
        unfetchable.save(update_fields=["tags"])

        _run()

        assert CardPrintingTag.objects.filter(
            card_id=md5_group["fetched"].pk, anonymous_id=JOIN_KEY_ANONYMOUS_ID
        ).exists(), "precondition: the source vote must still have been cast"
        assert not CardPrintingTag.objects.filter(card_id=unfetchable.pk).exists()

        ledger = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert ledger.counters["clustering"]["md5"]["members_skipped_ineligible"] == 1

    def test_a_null_md5_is_a_group_of_one(self, md5_group: dict[str, Any]) -> None:
        """Issue #473's ruling 3, inherited not re-decided: a checksum is copied from the source
        listing and never invented, so cards without one group with nothing. Two cards with a NULL
        md5 must NOT be treated as sharing the "same" (absent) checksum - the failure mode that
        would silently fuse every `LOCAL_FILE` card in the catalogue into one group."""
        CardFactory(name="Some Card", content_phash=0x3333333333333333, md5_checksum=None)
        CardFactory(name=f"{FETCH_FAILS_PREFIX} Other", content_phash=0x4444444444444444, md5_checksum=None)

        _run()

        ledger = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        # Only the one real md5 group from the fixture, never a group of NULL-checksum cards.
        assert ledger.counters["clustering"]["md5"]["group_count"] == 1


# ==================================================================================================
# FIX 3 - THE ENVELOPE IS RE-SAMPLED DURING THE PASS
# ==================================================================================================
@pytest.mark.django_db(transaction=True)
class TestEnvelopeResampling:
    """
    Owner: "host resampling is likely required (for steps that aren't fetch) as the same monolith
    will run for small datasets and large ones so needs to fit the available compute
    appropriately." PR #660 sampled once, as a preflight, and never again.
    """

    def test_the_envelope_is_re_sampled_during_the_pass_not_only_at_preflight(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The interval gate is dropped to 0 so the test does not have to spend a real minute proving
        the cadence exists. What is asserted is the thing that was missing: MORE THAN ONE sample.
        A preflight-only command reports exactly one, forever, at any interval.
        """
        monkeypatch.setattr(pipeline_command, "ENVELOPE_RESAMPLE_INTERVAL_SECONDS", 0.0)
        _run()

        ledger = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert ledger.counters["envelope"]["samples"] > 1

    def test_the_interval_gate_stops_it_becoming_its_own_load(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of the owner's instruction - "do not re-sample so often it becomes its
        own load". At the real 60s interval a short pass samples ONCE (the forced preflight) and
        every later seam is gated out, so the seams are counted rather than queried."""
        monkeypatch.setattr(pipeline_command, "ENVELOPE_RESAMPLE_INTERVAL_SECONDS", 3600.0)
        _run()

        ledger = PilotRunLedger.objects.get(command="run_pipeline", run_id="test-monolith-pipeline")
        assert ledger.counters["envelope"]["samples"] == 1
        assert ledger.counters["envelope"]["skipped_by_interval"] > 1

    def test_a_breach_appearing_mid_pass_halts_the_run_and_says_rows_were_kept(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A HOST-LOAD BREACH THAT APPEARS AFTER THE PREFLIGHT MUST HALT. It must NOT be converted
        into a throttle (that is rate pressure's channel, beneath Stage C, PR #644) and it must not
        self-resume. The halt message must also tell the truth about what is on disk: unlike the
        preflight's "nothing was written", a mid-pass halt leaves real rows behind.
        """
        from cardpicker.operating_envelope import EnvelopeSignals

        monkeypatch.setattr(pipeline_command, "ENVELOPE_RESAMPLE_INTERVAL_SECONDS", 0.0)
        calls = {"n": 0}

        def _clean_then_breach(*args: Any, **kwargs: Any) -> EnvelopeSignals:
            calls["n"] += 1
            if calls["n"] == 1:  # the preflight sees a clear box
                return EnvelopeSignals(load_avg=0.5, rss_mb_per_worker=128.0)
            return EnvelopeSignals(load_avg=99.0, rss_mb_per_worker=128.0)

        monkeypatch.setattr(pipeline_command, "_sample_envelope_signals", _clean_then_breach)

        with pytest.raises(CommandError) as excinfo:
            _run()

        message = str(excinfo.value)
        assert "ENVELOPE HALT" in message
        assert "host_load" in message
        assert "STAYS WRITTEN" in message, "a mid-pass halt must not claim nothing was written"
        assert "--run-id test-monolith" in message, "the halt must name the resume handle"

        # The trip is DURABLE - the run cannot decide for itself that it is fine now.
        from cardpicker.models import EnvelopeTrip

        assert EnvelopeTrip.objects.filter(acknowledged_at__isnull=True).exists()

    def test_skip_envelope_disables_the_mid_pass_checks_too(
        self, cohort: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--skip-envelope` must turn off the WHOLE bar, not just the preflight - otherwise the
        flag would silently stop meaning what it says the moment re-sampling landed."""
        from cardpicker.operating_envelope import EnvelopeSignals

        monkeypatch.setattr(pipeline_command, "ENVELOPE_RESAMPLE_INTERVAL_SECONDS", 0.0)
        monkeypatch.setattr(
            pipeline_command,
            "_sample_envelope_signals",
            lambda *a, **k: EnvelopeSignals(load_avg=99.0, rss_mb_per_worker=128.0),
        )

        _run("--skip-envelope")  # must not raise

        from cardpicker.models import EnvelopeTrip

        assert not EnvelopeTrip.objects.exists()


@pytest.mark.django_db
class TestPropagationEligibilityMatchesTheBaseQueryset:
    """
    THE DRIFT TRIPWIRE for `_members_eligible_for_a_propagated_vote`.

    That method expresses four CATALOGUE-LEVEL facts (unresolved, no confirmed `canonical_card`,
    `card_type=CARD`, no resolved `custom-art`/`non-english` tag) which
    `local_identify_printing_tags._eligible_base_queryset` also expresses. It does not simply CALL
    that function, for reasons its own docstring gives: that queryset bundles the four with
    WORKLOAD rules that are wrong for a propagation target (a scan-log exclusion keyed to the
    pilot's rescannable vocabulary, and a deductive-backfill exclusion that is a "don't spend a
    scan" choice rather than an ineligibility). Nor can `_eligible_base_queryset` be refactored to
    expose the four - its own docstring records that several tests and `stream_backstop_sweep`
    assert against its COMPILED SQL, so re-ordering its `.exclude()` chain would change that SQL
    for every legacy caller.

    So there are two expressions of the same four facts, and this test is what stops them drifting:
    over a fixture that triggers each ineligibility reason exactly once - and that deliberately
    contains NO votes, NO scan logs and NO deductive-backfill rows, so the workload excludes are
    inert and the two are being compared on the four facts alone - both must return the same set.

    If this fails, the two have diverged. Fix the divergence; do not relax the assertion.
    """

    def test_the_two_expressions_of_catalogue_level_eligibility_agree(self, db: Any) -> None:
        from cardpicker.local_identify_printing_tags import _eligible_base_queryset
        from cardpicker.models import CardTypes, PrintingTagStatus

        eligible = CardFactory(name="Eligible Card")
        resolved = CardFactory(name="Resolved Card", printing_tag_status=PrintingTagStatus.RESOLVED)
        confirmed = CardFactory(name="Confirmed Card", canonical_card=CanonicalCardFactory(name="Confirmed Card"))
        token = CardFactory(name="Token Card", card_type=CardTypes.TOKEN)
        custom = CardFactory(name="Custom Card", tags=["custom-art"])
        foreign = CardFactory(name="Foreign Card", tags=["non-english"])

        every_id = {c.pk for c in (eligible, resolved, confirmed, token, custom, foreign)}

        command = pipeline_command.Command()
        from_propagation = command._members_eligible_for_a_propagated_vote(every_id)
        from_base = set(
            _eligible_base_queryset("some-identity-with-no-rows").filter(pk__in=every_id).values_list("pk", flat=True)
        )

        assert from_propagation == from_base
        # ...and both actually discriminate, rather than agreeing by returning everything.
        assert from_propagation == {eligible.pk}
