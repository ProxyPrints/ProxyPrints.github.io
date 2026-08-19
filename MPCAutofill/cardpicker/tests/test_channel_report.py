"""
Tests for the per-channel run report (`cardpicker.channel_roster` +
`cardpicker.channel_report` + `manage.py channel_report`).

THE INSTRUMENT MUST BE ABLE TO REPORT A FAILURE. That is the whole point of
this file, and the three demonstrations the brief for issue #628 asked for
are named as such:

  * `test_DEMO_silent_channel_is_reported_and_gates` - a run where a channel
    produces nothing and the report flags it.
  * `test_DEMO_fully_producing_roster_passes` - a run where everything fires
    and it passes.
  * `test_DEMO_empty_roster_is_itself_a_finding` - a MUTATED derivation whose
    roster comes back empty, proving the empty roster fails rather than
    reporting all clear.

The third is the one that matters most. A report that derives nothing and
prints PASS is worse than no report, and it is the exact defect class this
repo has spent a week removing. The other tests here would all still pass
against an instrument that measured nothing; that one would not.
"""

import pytest

from django.core.management import call_command

from cardpicker.channel_report import (
    ZERO_DECLARATIONS,
    DidState,
    WhyState,
    ZeroDeclaration,
    ZeroDeclarationError,
    build_channel_report,
)
from cardpicker.channel_roster import (
    Channel,
    Reachability,
    Roster,
    derive_extractor_channels,
    derive_roster,
    derive_vote_channels,
    roster_source_files,
)
from cardpicker.models import CardScanLog, ImageEvidence, PilotRunLedger, VotePolarity
from cardpicker.tests import factories

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers - synthetic rosters, so a report-behaviour test is not hostage to
# whatever the real tree happens to contain today.
# ---------------------------------------------------------------------------


def _roster(*channels: Channel, reachable: tuple[str, ...] = ("writer",)) -> Roster:
    return Roster(
        vote=tuple(c for c in channels if c.family == "vote"),
        extractor=tuple(c for c in channels if c.family == "extractor"),
        abstention=tuple(c for c in channels if c.family == "abstention"),
        skip_reason=(),
        reachability=Reachability(
            reachable=frozenset(reachable),
            entrypoints_by_function={w: frozenset({"management/commands/pretend_command.py"}) for w in reachable},
        ),
        findings=(),
    )


def _vote_channel(identity: str, model: str = "CardPrintingTag", tag: str | None = None) -> Channel:
    key = f"vote:{model}:{identity}" + (f":{tag}" if tag else "")
    return Channel(
        family="vote",
        key=key,
        identity=identity,
        model=model,
        tag=tag,
        sites=(f"cardpicker/pretend.py:1 ({identity})",),
        writers=("writer",),
    )


# ---------------------------------------------------------------------------
# Derivation: the roster comes from CODE
# ---------------------------------------------------------------------------


def test_roster_scan_is_recursive_and_sees_management_commands(tmp_path):
    """PR #588's hole, kept closed.

    A non-recursive `*.py` glob never scanned `management/commands/`, so a
    real vote-casting identity declared one directory down was invisible to
    the derivation - absent from the roster, dormant in production, with
    nothing anywhere that would say so. This asserts the recursion directly
    AND asserts what the non-recursive scan would have missed, so the test
    fails if anyone narrows it back.
    """
    (tmp_path / "top.py").write_text('TOP_ANONYMOUS_ID = "top-v1"\n')
    nested = tmp_path / "management" / "commands"
    nested.mkdir(parents=True)
    (nested / "buried.py").write_text('BURIED_ANONYMOUS_ID = "buried-v1"\n')

    scanned = {p.name for p in roster_source_files(tmp_path)}
    assert scanned == {"top.py", "buried.py"}
    assert scanned - {p.name for p in tmp_path.glob("*.py")} == {"buried.py"}


def test_roster_scan_excludes_tests_but_includes_migrations(tmp_path):
    """`tests/` is excluded DELIBERATELY (fixture modules declare
    identity-shaped literals that are not production roster members);
    `migrations/` is included deliberately (a migration that pins an identity
    operates on real rows keyed by it)."""
    for rel in ("tests/fixture.py", "migrations/0001_x.py", "__pycache__/junk.py"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('X_ANONYMOUS_ID = "x-v1"\n')

    scanned = {str(p.relative_to(tmp_path)) for p in roster_source_files(tmp_path)}
    assert scanned == {"migrations/0001_x.py"}


def test_declared_identities_are_not_hardcoded_anywhere():
    """The roster must move when the code moves.

    A new `*_ANONYMOUS_ID` in a new file appears in the derived roster with no
    edit to any list - which is the difference between a derivation and a
    hand-maintained list that has merely been moved into the checker.
    """
    real = {c.identity for c in derive_vote_channels()[0]}
    assert "stage-d-join-key-v1" in real
    assert "layout-class-cast-v1" in real
    # PR #615 retired PrintingTagVote and its writer; nothing may resurrect it.
    assert "scryfall-tagger-v1" not in real


# ---------------------------------------------------------------------------
# THE SINGLE MOST IMPORTANT REQUIREMENT: chips counted BY TAG
# ---------------------------------------------------------------------------


def test_chip_channels_are_split_by_tag_not_by_identity():
    """`local-fallback-v1` is SEVEN channels, not one.

    The composition audit found border chips healthy while frame-style and
    bleed-edge sat at ZERO under this same `anonymous_id`. An identity-level
    roster reports that identity as fine while two thirds of it is dead, so
    the roster has to carry the tag.
    """
    by_key = {c.key: c for c in derive_vote_channels()[0]}
    fallback_tags = {c.tag for c in by_key.values() if c.identity == "local-fallback-v1"}

    assert {"Old Border", "Modern Border"} <= fallback_tags, "frame-style chips must be their own channels"
    assert "appropriate-bleed" in fallback_tags, "bleed-edge chips must be their own channel"
    assert {"Black Border", "White Border", "Silver Border"} <= fallback_tags
    # ...and they must be DISTINCT channels, not one merged entry.
    assert len({c.key for c in by_key.values() if c.identity == "local-fallback-v1"}) == len(fallback_tags)


def test_a_dead_chip_tag_is_reported_even_when_its_identity_is_healthy():
    """The audit's exact scenario, reproduced end to end.

    Border chips have rows; frame chips under the SAME identity have none.
    An identity-level count passes this pipeline. This report must fail it.
    """
    border = _vote_channel("local-fallback-v1", "CardTagVote", "Black Border")
    frame = _vote_channel("local-fallback-v1", "CardTagVote", "Old Border")
    black = factories.TagFactory(name="Black Border")
    factories.TagFactory(name="Old Border")
    factories.CardTagVoteFactory(tag=black, anonymous_id="local-fallback-v1")

    report = build_channel_report(roster=_roster(border, frame))
    by_key = {o.channel.key: o for o in report.outcomes}

    assert by_key[border.key].did == DidState.PRODUCED
    assert by_key[frame.key].did == DidState.SILENT
    assert any("Old Border" in f for f in report.findings)


def test_identity_abstentions_do_not_rescue_a_dead_tag_channel():
    """`CardScanLog` has no tag column, so an abstention is identity-scoped.

    If border-work abstentions counted as evidence for the FRAME channel, the
    report would call frame chips alive on the strength of other work -
    reinstating the identity-level merge this instrument exists to prevent.
    """
    frame = _vote_channel("local-fallback-v1", "CardTagVote", "Old Border")
    factories.TagFactory(name="Old Border")
    card = factories.CardFactory()
    CardScanLog.objects.create(card=card, anonymous_id="local-fallback-v1", skip_reason="no-evidence")

    report = build_channel_report(roster=_roster(frame))
    outcome = report.outcomes[0]

    assert outcome.abstentions == 1, "the abstention is still REPORTED as context"
    assert outcome.evidence() == 0, "but it is not evidence for this tag"
    assert outcome.did == DidState.SILENT
    assert any("identity-scoped context" in note for note in outcome.notes)


# ---------------------------------------------------------------------------
# Reachability - the derivation reproduces the hand audit
# ---------------------------------------------------------------------------


def _commands_reaching(channel, roster):
    modules: set[str] = set()
    for writer in channel.writers:
        modules |= set(roster.reachability.entrypoints_by_function.get(writer, ()))
    return {m.rsplit("/", 1)[-1][:-3] for m in modules if m.startswith("management/commands/")}


def test_reachability_reproduces_the_audit_per_channel_command_column():
    """The static call graph must agree with the hand audit it automates.

    These are the audit's own CMD entries. If the graph drifts from them, the
    reachability column is decoration rather than evidence, and the "wire it
    first" vs "run it again" split it exists to make becomes unreliable.
    """
    roster = derive_roster()
    by_key = {c.key: c for c in roster.vote}

    expected = {
        "vote:CardTagVote:layout-class-cast-v1:Black Border": "local_layout_class_cast",
        "vote:CardTagVote:local-fallback-v1:Old Border": "local_identify_printing_tags",
        "vote:CardTagVote:ai-art-detector-v1:AI-Generated": "local_detect_ai_art",
        "vote:CardPrintingTag:deductive-backfill-v1": "deductive_backfill_printing_tags",
        "vote:CardPrintingTag:lands-artist-decomp-v1": "local_lands_identify",
        "vote:CardPrintingTag:local-name-frequency-v1": "local_name_frequency_elimination",
        "vote:CardPrintingTag:stage-d-join-key-v1": "local_calculate_verdicts",
        "vote:CardArtistVote:art-hash-artist-v1": "local_residual_classify",
        "vote:CardTagVote:art-edge-continuity-v1:Extended": "local_art_edge_cast",
    }
    for key, command in expected.items():
        assert command in _commands_reaching(by_key[key], roster), key


def test_reachability_closed_the_audits_previously_unreachable_channel():
    """The audit's central wiring finding, now closed, derived rather than remembered.

    `local_art_edge.cast_art_edge_continuity_vote` used to be reachable from NO management
    command - the same shape `image_evidence.extract_card_evidence` still is, whose only
    non-test callers are a docstring and a comment. This asserts the fix directly: the new
    `local_art_edge_cast` command and `stage_e_dispatch._run_evidence_only_calculators` both
    reach it now.
    """
    roster = derive_roster()
    art_edge = next(c for c in roster.vote if c.identity == "art-edge-continuity-v1")
    assert "local_art_edge_cast" in _commands_reaching(art_edge, roster)


def test_the_pooled_runner_reaches_no_vote_channel():
    """The audit's headline, independently reproduced.

    Only one channel is reachable from `run_image_evidence_cohort` and it
    writes no votes - so a "full run" built on the pooled engine is a Stage C
    run, and every Stage D identity has to be invoked separately.
    """
    roster = derive_roster()
    assert all("run_image_evidence_cohort" not in _commands_reaching(c, roster) for c in roster.vote)
    reached = {c.identity for c in roster.abstention if "run_image_evidence_cohort" in _commands_reaching(c, roster)}
    assert reached == {"evidence-transfer-v1"}


# ---------------------------------------------------------------------------
# The five outcomes - only one of them is a failure
# ---------------------------------------------------------------------------


def test_negative_votes_are_a_conclusion_not_an_absence():
    """A channel whose every row is `is_no_match=True` is WORKING.

    It looked at the whole candidate set and ruled all of it out. Counting
    that as "produced nothing" reports the most decisive thing a printing
    calculator can say as a failure.
    """
    channel = _vote_channel("negative-only-v1")
    factories.CardPrintingTagFactory(anonymous_id="negative-only-v1", printing=None, is_no_match=True)

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert (outcome.positive, outcome.negative) == (0, 1)
    assert outcome.did == DidState.PRODUCED


def test_negative_tag_votes_are_counted_by_polarity():
    channel = _vote_channel("polarity-v1", "CardTagVote", "appropriate-bleed")
    tag = factories.TagFactory(name="appropriate-bleed")
    factories.CardTagVoteFactory(tag=tag, anonymous_id="polarity-v1", polarity=VotePolarity.NOT_APPLICABLE)

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert (outcome.positive, outcome.negative) == (0, 1)
    assert outcome.did == DidState.PRODUCED


def test_abstentions_are_reported_by_reason_not_as_a_total():
    """ "Abstained 500 times for `no-evidence`" and "abstained 500 times for
    `artist-mismatch`" are completely different findings."""
    channel = Channel(
        family="abstention",
        key="abstention:router-v1",
        identity="router-v1",
        sites=("cardpicker/pretend.py:1",),
        writers=("writer",),
    )
    card = factories.CardFactory()
    for reason, count in (("no-evidence", 2), ("artist-mismatch", 3)):
        for _ in range(count):
            CardScanLog.objects.create(card=card, anonymous_id="router-v1", skip_reason=reason)

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert outcome.abstained_by_reason == {"no-evidence": 2, "artist-mismatch": 3}
    assert outcome.did == DidState.PRODUCED, "a router that abstained with named reasons is working"


def test_a_router_that_casts_no_votes_says_so_rather_than_showing_zeros():
    channel = Channel(
        family="abstention",
        key="abstention:stage-d-slow-path-v1",
        identity="stage-d-slow-path-v1",
        sites=("cardpicker/pretend.py:1",),
        writers=("writer",),
    )
    card = factories.CardFactory()
    CardScanLog.objects.create(card=card, anonymous_id="stage-d-slow-path-v1", skip_reason="to-review")

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert any("casts no votes by design" in note for note in outcome.notes)


def test_extractor_success_is_a_populated_field_not_a_manifest_key():
    """Where the manifest lies.

    All eleven extractors report 100% key presence in `extractor_versions`
    while `bleed_diff_mm` is NULL on 97.9% of rows. A key-presence count says
    "gap 0" for every one of them, so this counts FIELDS.
    """
    channel = Channel(
        family="extractor",
        key="extractor:geometry_bleed",
        identity="geometry_bleed",
        version="geometry-bleed-v1",
        fields=("bleed_diff_mm",),
        sites=("cardpicker/image_evidence.py:1",),
    )
    card = factories.CardFactory(content_phash=123)
    # The key is present - the manifest would call this extractor complete.
    ImageEvidence.objects.create(
        card=card, content_hash=123, extractor_versions={"geometry_bleed": "geometry-bleed-v1"}, bleed_diff_mm=None
    )

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert outcome.values_written == 0
    assert outcome.did == DidState.SILENT, "manifest key present, no value written - that is the failure"


def test_extractor_with_a_written_value_passes():
    channel = Channel(
        family="extractor",
        key="extractor:geometry_bleed",
        identity="geometry_bleed",
        fields=("bleed_diff_mm",),
        sites=("cardpicker/image_evidence.py:1",),
    )
    card = factories.CardFactory(content_phash=123)
    ImageEvidence.objects.create(card=card, content_hash=123, extractor_versions={}, bleed_diff_mm=1.5)

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert outcome.values_by_field == {"bleed_diff_mm": 1}
    assert outcome.did == DidState.PRODUCED


def test_empty_string_is_not_a_written_value():
    """`compute_card_evidence` writes `""` for "ran, found nothing"
    (`fields["layout_class"] = layout_class or ""`). Counting those as values
    written would restate the manifest's own lie in a second place."""
    channel = Channel(
        family="extractor", key="extractor:layout_class", identity="layout_class", fields=("layout_class",)
    )
    card = factories.CardFactory(content_phash=7)
    ImageEvidence.objects.create(card=card, content_hash=7, extractor_versions={}, layout_class="")

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert outcome.values_by_field == {"layout_class": 0}


def test_extractor_channels_that_share_a_field_block_say_so():
    """The OCR group closes with three manifest stores over ONE block of field
    writes. Splitting it between them would be an invention; crediting one and
    showing the other two at zero fields would read like two dead
    extractors."""
    by_key = {c.identity: c for c in derive_extractor_channels()[0]}
    ocr = by_key["collector_line_ocr"]
    assert set(ocr.shares_fields_with) == {"artist_ocr", "collector_line_tsv"}
    assert ocr.fields and by_key["artist_ocr"].fields == ocr.fields


# ---------------------------------------------------------------------------
# The zero declaration cannot be added without a reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reason": "", "ratified_by": "owner"},
        {"reason": "   ", "ratified_by": "owner"},
        {"reason": "n/a", "ratified_by": "owner"},
        {"reason": "not needed right now, will revisit", "ratified_by": "owner"},
        {"reason": "a" * 60, "ratified_by": ""},
    ],
)
def test_zero_declaration_cannot_be_added_without_a_real_reason(kwargs):
    """A zero nobody signed is an assumption, and assuming a zero is the
    defect OPS-CORR-0008 records. Enforced at construction, not requested in
    a comment."""
    with pytest.raises(ZeroDeclarationError):
        ZeroDeclaration(**kwargs)


def test_ships_with_no_zero_declarations():
    """EMPTY TODAY, DELIBERATELY.

    The audit found real, undeclared zeros and this instrument was built to
    report them. Pre-declaring them would be building the instrument and
    silencing its first reading in the same change.
    """
    assert ZERO_DECLARATIONS == {}


def test_declared_silent_channel_that_starts_producing_is_flagged(monkeypatch):
    """A stated expectation just became false. That is a real event and gets
    exactly as much attention as the reverse."""
    channel = _vote_channel("declared-v1")
    declaration = ZeroDeclaration(
        reason=(
            "pretend channel used only by this test to prove the declared-silent transition is "
            "noticed rather than swallowed"
        ),
        ratified_by="test",
    )
    monkeypatch.setitem(ZERO_DECLARATIONS, channel.key, declaration)

    empty = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert empty.did == DidState.DECLARED_SILENT

    factories.CardPrintingTagFactory(anonymous_id="declared-v1")
    report = build_channel_report(roster=_roster(channel))
    assert report.outcomes[0].did == DidState.DECLARED_SILENT_NOW_PRODUCING
    assert any("NOW PRODUCING" in f for f in report.findings)


# ---------------------------------------------------------------------------
# The four states - WHY a channel is silent
# ---------------------------------------------------------------------------


def test_never_wired_is_distinguished_from_never_run():
    """ "Run it again" and "wire it first" are not the same instruction, and
    one of them can never work."""
    unwired = Channel(
        family="vote",
        key="vote:CardTagVote:unwired-v1:Extended",
        identity="unwired-v1",
        model="CardTagVote",
        tag="Extended",
        sites=("cardpicker/pretend.py:1",),
        writers=("nobody_calls_this",),
    )
    wired = _vote_channel("wired-v1")

    report = build_channel_report(roster=_roster(unwired, wired))
    by_key = {o.channel.key: o for o in report.outcomes}
    assert by_key[unwired.key].why == WhyState.NEVER_WIRED
    assert by_key[wired.key].why == WhyState.WIRED_NEVER_RUN


def test_wired_and_run_is_distinguished_from_wired_and_never_run():
    channel = _vote_channel("ran-v1")
    PilotRunLedger.objects.create(run_id="r1", command="pretend_command")
    factories.CardPrintingTagFactory(anonymous_id="ran-v1")

    outcome = build_channel_report(roster=_roster(channel)).outcomes[0]
    assert outcome.why == WhyState.RAN
    assert outcome.commands == ("pretend_command",)


def test_ran_and_purged_is_distinguished_from_ran_and_produced_nothing():
    from django.utils import timezone

    purged = _vote_channel("purged-v1")
    PilotRunLedger.objects.create(run_id="r1", command="pretend_command", purged_at=timezone.now())

    outcome = build_channel_report(roster=_roster(purged)).outcomes[0]
    assert outcome.why == WhyState.RAN_AND_PURGED
    assert outcome.did == DidState.SILENT, "purged is an explanation, not an excuse"


# ---------------------------------------------------------------------------
# THE THREE DEMONSTRATIONS
# ---------------------------------------------------------------------------


def test_DEMO_silent_channel_is_reported_and_gates():
    """DEMONSTRATION 1: a run where a channel produces nothing, and the report
    flags it and fails the exit code."""
    producing = _vote_channel("producing-v1")
    silent = _vote_channel("silent-v1")
    factories.CardPrintingTagFactory(anonymous_id="producing-v1")

    report = build_channel_report(roster=_roster(producing, silent))
    by_key = {o.channel.key: o for o in report.outcomes}

    assert by_key[producing.key].did == DidState.PRODUCED
    assert by_key[silent.key].did == DidState.SILENT
    assert len(report.findings) == 1
    assert "SILENT CHANNEL" in report.findings[0] and "silent-v1" in report.findings[0]
    assert report.failures() == [by_key[silent.key]]


def test_DEMO_fully_producing_roster_passes():
    """DEMONSTRATION 2: a run where everything fires, across all five outcome
    types, and the report passes."""
    positive = _vote_channel("positive-v1")
    negative = _vote_channel("negative-v1")
    chip = _vote_channel("chip-v1", "CardTagVote", "Black Border")
    router = Channel(family="abstention", key="abstention:router-v1", identity="router-v1", writers=("writer",))
    extractor = Channel(
        family="extractor", key="extractor:geometry_bleed", identity="geometry_bleed", fields=("bleed_diff_mm",)
    )

    factories.CardPrintingTagFactory(anonymous_id="positive-v1")
    factories.CardPrintingTagFactory(anonymous_id="negative-v1", printing=None, is_no_match=True)
    factories.CardTagVoteFactory(tag=factories.TagFactory(name="Black Border"), anonymous_id="chip-v1")
    CardScanLog.objects.create(card=factories.CardFactory(), anonymous_id="router-v1", skip_reason="to-review")
    card = factories.CardFactory(content_phash=99)
    ImageEvidence.objects.create(card=card, content_hash=99, extractor_versions={}, bleed_diff_mm=2.0)

    report = build_channel_report(roster=_roster(positive, negative, chip, router, extractor))

    assert report.findings == [], f"expected a clean report, got {report.findings}"
    assert all(o.did == DidState.PRODUCED for o in report.outcomes)
    assert report.measurable


def test_DEMO_empty_roster_is_itself_a_finding(tmp_path):
    """DEMONSTRATION 3, AND THE ONE THAT MATTERS MOST.

    The derivation is MUTATED so the roster comes back empty - here by
    pointing the scan at a tree with no declarations in it, which is exactly
    what a broken regex, a renamed constant convention, or a reintroduced
    non-recursive glob would do silently.

    An instrument that measures nothing must never report "all clear". This
    asserts the empty roster is a hard finding, that the report declares
    itself UNMEASURABLE, and that the command exits with the distinct
    INSUFFICIENT-DATA code rather than PASS.
    """
    (tmp_path / "nothing_here.py").write_text("VALUE = 1\n")

    roster = derive_roster(src_dir=tmp_path)
    assert roster.is_empty()
    assert roster.findings, "an empty derivation must produce findings, not silence"
    assert any("empty derivation is the finding" in f.lower() or "FAILED" in f for f in roster.findings)

    report = build_channel_report(roster=roster)
    assert not report.measurable
    assert report.derivation_findings
    assert report.outcomes == [], "nothing may be reported as healthy when nothing was measured"


def test_DEMO_empty_roster_makes_the_command_exit_insufficient_data(tmp_path, monkeypatch):
    """The same mutation, through the command, proving the exit code."""
    import cardpicker.channel_roster as roster_module

    (tmp_path / "nothing_here.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(roster_module, "CARDPICKER_DIR", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        call_command("channel_report")
    assert excinfo.value.code == 2, "an unmeasurable roster is INSUFFICIENT-DATA, never PASS"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_command_runs_with_no_flags_at_all():
    """Owner directive: "default the default things, disable them with
    flags". A bare invocation must produce a useful report."""
    PilotRunLedger.objects.create(run_id="r1", command="local_layout_class_cast")
    with pytest.raises(SystemExit) as excinfo:
        call_command("channel_report")
    # The real tree HAS silent channels (the audit found three), so a bare run
    # against an empty test database is expected to FAIL, not to error out.
    assert excinfo.value.code == 1


def test_command_no_gate_reports_without_failing():
    PilotRunLedger.objects.create(run_id="r1", command="local_layout_class_cast")
    call_command("channel_report", "--no-gate")


def test_command_json_output_is_machine_readable(capsys):
    import json

    PilotRunLedger.objects.create(run_id="r1", command="local_layout_class_cast")
    call_command("channel_report", "--json", "--no-gate")
    payload = json.loads(capsys.readouterr().out)

    assert payload["measurable"] is True
    assert payload["roster_sizes"]["vote"] > 0
    assert any(c["tag"] == "Old Border" for c in payload["channels"]), "chips must be reported at tag grain"


def test_report_never_reads_a_consensus_outcome():
    """Owner, 2026-07-30: "we don't expect full resolutions just machine votes
    cast". `resolve_weighted_consensus` enforces a human-backed gate, so a
    report keyed on resolutions would show ~100% failure across a fully
    healthy pipeline. This asserts the module does not import or touch one.
    """
    import inspect

    from cardpicker import channel_report as module

    source = inspect.getsource(module)
    for forbidden in (
        "printing_tag_status",
        "inferred_canonical_card",
        "resolve_weighted_consensus",
        "resolve_printing",
        "printing_consensus",
        "tag_consensus",
        "artist_consensus",
    ):
        assert f"{forbidden}(" not in source and f"import {forbidden}" not in source
