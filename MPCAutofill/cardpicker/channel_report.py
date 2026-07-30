"""
The per-channel run report: what did every channel in this pipeline
actually produce?

WHAT THIS IS FOR
-----------------
`docs/reports/2026-07-29-pipeline-coverage-composition-audit.md` is the
hand-built version of this: a per-channel table across the vote channels,
the Stage C extractors and the skip reasons, assembled by querying
production one channel at a time and sorting the zeros by hand. It found
three channels down, one of them for a reason nobody had recorded. This
module makes that table a command, so a failed run produces a LIST rather
than another hand audit.

THE DOCTRINE IT INHERITS
-------------------------
`image_evidence.build_reconciliation_report` states the rule this module
follows and reuses verbatim:

    "Queries ImageEvidence + CardScanLog directly rather than a
    separately-maintained counter, so the report can never drift from what
    was actually persisted."

That is why it is trustworthy, and nothing here keeps a counter either.
Every number below is a `COUNT(*)` over the rows a channel wrote. This
module GENERALISES that function rather than duplicating it: the Stage C
side literally calls it, once per derived extractor key, instead of
re-implementing the attempted/ran/skipped split. What it adds is the three
things that function does not do - the whole roster instead of one named
extractor, the four vote tables it never looks at, and the per-TAG chip
grain.

Its deliberate asymmetry is preserved because it is correct: the
`CardScanLog` side is scoped by `run_id`, the `ImageEvidence` side is not,
because a card's evidence may have been written by an earlier run and
merely skipped in this one.

FIVE OUTCOMES, AND ONLY ONE OF THEM IS A FAILURE
--------------------------------------------------
Owner, 2026-07-30: "not just votes cast, abstentions are also worth
tracking as well as negative votes or writing a value". Every unit of work
a channel does ends in exactly one of these, and collapsing them into a
single count is how a working channel reads as dead:

  1. POSITIVE VOTE - a row asserting a claim.
  2. NEGATIVE VOTE - a row asserting the claim is FALSE
     (`CardPrintingTag.is_no_match`, `CardTagVote.polarity=NOT_APPLICABLE`,
     `CardArtistVote.is_unknown`, `CardIllustrationVote.is_unknown`). A
     conclusion, not an absence: the channel looked and decided "not this".
  3. ABSTENTION - a `CardScanLog` row with a NAMED skip reason. Also a
     conclusion: it looked, could not decide, and said why. Reported BY
     REASON, never as a total, because "abstained 500 times for
     `no-evidence`" and "abstained 500 times for `artist-mismatch`" are
     completely different findings.
  4. VALUE WRITTEN - for a Stage C extractor, success is a POPULATED
     FIELD. This is where the manifest lies: all eleven extractors report
     100% key presence in `extractor_versions` while `bleed_diff_mm` is
     NULL on 97.9% of rows and `artist_ocr_name` blank on 206,629. A
     key-presence count says "gap 0" for every one of them, so this
     counts fields, not keys.
  5. NOTHING AT ALL - no vote, no negative, no abstention, no value.
     THE ONLY TRUE FAILURE, and what the gate fires on.

A channel that abstained 200,000 times with a named reason is working and
telling us something. A channel that produced silence is broken or
unwired. Today those are indistinguishable, which is exactly how
frame-style and bleed-edge sat at zero unnoticed.

WHAT THIS DOES NOT MEASURE, DELIBERATELY
------------------------------------------
RESOLUTIONS. Owner, 2026-07-30: "we don't expect full resolutions just
machine votes cast ... a machine vote is as good as a confirmation".
`vote_consensus.resolve_weighted_consensus` enforces a hard human-backed
gate, so no volume of machine votes resolves anything on its own - the
catalogue has 4 resolved cards out of 230,770 and that is the system
working as designed. A report keyed on `printing_tag_status`,
`inferred_canonical_card` or any consensus outcome would show ~100%
failure across a fully healthy pipeline. Nothing here reads them.

WHY ZERO GATES
---------------
`OPS-CORR-0008`, ratified: chip channels must be VERIFIED to produce rows,
not assumed - "treat zero as a run failure rather than a quiet outcome". A
silent channel therefore fails the report unless it carries an explicit
`ZeroDeclaration` with a written reason, and a channel that is declared
silent and then STARTS producing rows fails too, because that is a real
event nobody predicted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from django.db.models import Count, Q

from cardpicker.channel_roster import Channel, Roster, derive_roster
from cardpicker.image_evidence import ReconciliationReport, build_reconciliation_report
from cardpicker.models import (
    CardArtistVote,
    CardIllustrationVote,
    CardPrintingTag,
    CardScanLog,
    CardTagVote,
    ImageEvidence,
    PilotRunLedger,
    VotePolarity,
)

#: model name -> (model class, Q() matching a NEGATIVE vote)
#:
#: A negative vote is a CONCLUSION. `CardPrintingTag.is_no_match=True` means
#: "this image depicts no known printing" - the channel looked at the whole
#: candidate set and ruled all of it out. Counting that as "produced nothing"
#: would report the single most decisive thing a printing calculator can say
#: as a failure.
VOTE_MODELS: dict[str, tuple[Any, Q]] = {
    "CardPrintingTag": (CardPrintingTag, Q(is_no_match=True)),
    "CardArtistVote": (CardArtistVote, Q(is_unknown=True)),
    "CardIllustrationVote": (CardIllustrationVote, Q(is_unknown=True)),
    "CardTagVote": (CardTagVote, Q(polarity=VotePolarity.NOT_APPLICABLE)),
}


# ---------------------------------------------------------------------------
# The zero declaration
# ---------------------------------------------------------------------------


class ZeroDeclarationError(ValueError):
    """Raised when a zero declaration is added without a usable reason."""


@dataclass(frozen=True)
class ZeroDeclaration:
    """
    An explicit, per-entry statement that a channel is EXPECTED to produce
    nothing, and why.

    IT CANNOT BE ADDED WITHOUT A REASON. `__post_init__` rejects an empty,
    whitespace, or token reason, so the declaration table cannot be used as a
    silencer - the same discipline docs_lint.py's
    `CALCULATOR_ROSTER_ALLOWLIST` and `SKIP_REASON_ROSTER_ALLOWLIST` apply
    ("an exclusion has to be a visible decision, not a silent gap"), enforced
    here at construction rather than requested in a comment, because a
    comment is exactly what gets ignored at 2am.

    `ratified_by` is required for the same reason: a zero that nobody signed
    is an assumption, and assuming a zero is what OPS-CORR-0008 was written
    about.
    """

    reason: str
    ratified_by: str

    #: A reason shorter than this is a label, not an explanation.
    MIN_REASON_CHARS = 40

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ZeroDeclarationError(
                "a zero declaration needs a written reason - a channel producing nothing is a "
                "run failure unless somebody states why it is not (OPS-CORR-0008)."
            )
        if len(self.reason.strip()) < self.MIN_REASON_CHARS:
            raise ZeroDeclarationError(
                f"zero-declaration reason {self.reason!r} is too short to be an explanation "
                f"(minimum {self.MIN_REASON_CHARS} characters). State what the channel is, why "
                f"it legitimately produces no rows, and what would have to change for it to "
                f"start."
            )
        if not self.ratified_by or not self.ratified_by.strip():
            raise ZeroDeclarationError(
                "a zero declaration needs `ratified_by` - a zero nobody signed is an "
                "assumption, and assuming a zero is the defect OPS-CORR-0008 records."
            )


#: Channels that legitimately produce nothing, keyed by `Channel.key`.
#:
#: EMPTY TODAY, DELIBERATELY - the same posture
#: `SKIP_REASON_ROSTER_ALLOWLIST` and `UNMANIFESTED_CONSTANT_ALLOWLIST` ship
#: in. The composition audit found real, undeclared zeros (frame-style chips,
#: bleed-edge chips, `local-name-frequency-v1`), and this instrument was built
#: to report them. Pre-declaring them here would be building the instrument
#: and silencing its first reading in the same change - the report would come
#: back clean on a pipeline with three channels down, which is precisely the
#: failure this exists to end. They are meant to show up RED on the first run.
#:
#: Nothing goes here because it currently fails. Something goes here when the
#: owner rules that a channel is not supposed to produce rows at all.
ZERO_DECLARATIONS: dict[str, ZeroDeclaration] = {}


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


class WhyState:
    """WHY a channel is silent. Four problems, four fixes.

    The audit had to sort these by hand, and collapsing them is how a dormant
    channel reads as healthy: "run it again" and "wire it first" are not the
    same instruction, and one of them can never work.
    """

    NEVER_WIRED = "NEVER-WIRED"
    WIRED_NEVER_RUN = "WIRED-NEVER-RUN"
    RAN = "RAN"
    RAN_AND_PURGED = "RAN-AND-PURGED"
    UNKNOWN = "UNKNOWN"


class DidState:
    """WHAT a channel did when it ran. Orthogonal to `WhyState`."""

    PRODUCED = "PRODUCED"
    SILENT = "SILENT"
    DECLARED_SILENT = "DECLARED-SILENT"
    DECLARED_SILENT_NOW_PRODUCING = "DECLARED-SILENT-BUT-PRODUCING"


@dataclass
class ChannelOutcome:
    channel: Channel
    positive: int = 0
    negative: int = 0
    abstained_by_reason: dict[str, int] = field(default_factory=dict)
    #: extractor channels only: field name -> rows with a populated value
    values_by_field: dict[str, int] = field(default_factory=dict)
    #: extractor channels only, straight from `build_reconciliation_report`
    reconciliation: Optional[ReconciliationReport] = None
    #: run-scoped equivalents of the above three totals
    run_positive: int = 0
    run_negative: int = 0
    run_abstentions: int = 0
    why: str = WhyState.UNKNOWN
    did: str = DidState.SILENT
    #: commands that statically reach this channel's writer functions
    commands: tuple[str, ...] = ()
    declaration: Optional[ZeroDeclaration] = None
    notes: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    @property
    def abstentions(self) -> int:
        return sum(self.abstained_by_reason.values())

    @property
    def values_written(self) -> int:
        return sum(self.values_by_field.values())

    def evidence(self) -> int:
        """Total evidence that this channel did ANYTHING - outcome 5's inverse.

        WHY ABSTENTIONS DO NOT COUNT FOR A TAG-GRAINED CHANNEL. `CardScanLog`
        has no tag column, so an abstention is only ever identity-scoped. If
        `local-fallback-v1`'s border abstentions counted as evidence for its
        FRAME-style channel, the report would call frame chips alive on the
        strength of border work - reinstating exactly the identity-level merge
        this whole instrument exists to prevent. So for a tag-grained channel
        the evidence is that TAG's own rows, and its identity's abstentions
        are carried in `notes` as context only.
        """
        total = self.positive + self.negative + self.values_written
        if not (self.channel.family == "vote" and self.channel.tag):
            total += self.abstentions
        return total


@dataclass
class ChannelReport:
    run_id: Optional[str]
    ledger: Optional[PilotRunLedger]
    roster: Roster
    outcomes: list[ChannelOutcome]
    findings: list[str]
    #: derivation failures - the instrument could not be built
    derivation_findings: list[str]

    @property
    def measurable(self) -> bool:
        return not self.derivation_findings and not self.roster.is_empty()

    def failures(self) -> list[ChannelOutcome]:
        return [o for o in self.outcomes if o.did in (DidState.SILENT, DidState.DECLARED_SILENT_NOW_PRODUCING)]


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def _vote_counts(channel: Channel, run_id: Optional[str]) -> tuple[int, int, int, int]:
    """(positive, negative, run positive, run negative) for one vote channel."""
    model, negative_q = VOTE_MODELS[channel.model or ""]
    qs = model.objects.filter(anonymous_id=channel.identity)
    if channel.tag:
        qs = qs.filter(tag__name=channel.tag)
    negative = qs.filter(negative_q).count()
    positive = qs.count() - negative
    run_positive = run_negative = 0
    if run_id:
        run_qs = qs.filter(run_id=run_id)
        run_negative = run_qs.filter(negative_q).count()
        run_positive = run_qs.count() - run_negative
    return positive, negative, run_positive, run_negative


def _abstention_counts(identity: str, run_id: Optional[str]) -> tuple[dict[str, int], int]:
    """({skip reason: count}, run-scoped total) for one identity.

    BY REASON, never as a total - see the module docstring on why
    "abstained 500 times for `no-evidence`" and "abstained 500 times for
    `artist-mismatch`" are different findings.
    """
    by_reason: dict[str, int] = {}
    for row in CardScanLog.objects.filter(anonymous_id=identity).values("skip_reason").annotate(n=Count("id")):
        by_reason[row["skip_reason"]] = row["n"]
    run_total = CardScanLog.objects.filter(anonymous_id=identity, run_id=run_id).count() if run_id else 0
    return by_reason, run_total


def _populated_field_counts(fields: tuple[str, ...]) -> tuple[dict[str, int], list[str]]:
    """{field: rows carrying a real value}, plus any name that is not a model field.

    "Populated" excludes NULL and excludes the empty string/list, because
    `compute_card_evidence` writes `""` for "ran, found nothing"
    (`fields["layout_class"] = layout_class or ""`). Counting those as values
    written would restate the manifest's own lie in a second place.
    """
    model_fields = {f.name: f for f in ImageEvidence._meta.get_fields() if hasattr(f, "get_internal_type")}
    counts: dict[str, int] = {}
    unknown: list[str] = []
    for name in fields:
        if name not in model_fields:
            unknown.append(name)
            continue
        qs = ImageEvidence.objects.exclude(**{f"{name}__isnull": True})
        internal = model_fields[name].get_internal_type()
        if internal in {"CharField", "TextField"}:
            qs = qs.exclude(**{name: ""})
        elif internal == "JSONField":
            qs = qs.exclude(**{name: []}).exclude(**{name: {}})
        counts[name] = qs.count()
    return counts, unknown


def _run_card_ids(run_id: str) -> list[int]:
    """The cards a run touched, derived from the run itself rather than a flag.

    Union of "this run wrote evidence for it" and "this run logged a skip for
    it" - the attempted set `build_reconciliation_report` needs, without an
    operator having to supply a card list (owner: "default the default
    things, disable them with flags").
    """
    evidence_ids = ImageEvidence.objects.filter(run_id=run_id).values_list("card_id", flat=True)
    scan_ids = CardScanLog.objects.filter(run_id=run_id).values_list("card_id", flat=True)
    return sorted(set(evidence_ids) | set(scan_ids))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _commands_for(channel: Channel, roster: Roster) -> tuple[str, ...]:
    """Management commands that statically reach this channel's writers."""
    modules: set[str] = set()
    for writer in channel.writers:
        modules |= set(roster.reachability.entrypoints_by_function.get(writer, ()))
    commands = {
        module.rsplit("/", 1)[-1][:-3]
        for module in modules
        if module.startswith("management/commands/") and module.endswith(".py")
    }
    return tuple(sorted(commands))


def _classify_why(outcome: ChannelOutcome, roster: Roster) -> str:
    channel = outcome.channel
    if channel.family == "extractor":
        # Extractors do not have their own writer functions in the vote sense -
        # they are inline blocks of `compute_card_evidence`, which both engines
        # call directly. Their "ran" evidence is the manifest itself.
        return WhyState.RAN if outcome.reconciliation and outcome.reconciliation.attempted else WhyState.WIRED_NEVER_RUN

    reachable = any(w in roster.reachability.reachable for w in channel.writers)
    if channel.writers and not reachable:
        return WhyState.NEVER_WIRED

    if not outcome.commands:
        # Reachable from somewhere, but from no management command - either a
        # view-only surface or a function only other library code calls.
        return WhyState.NEVER_WIRED if not reachable else WhyState.UNKNOWN

    ledger = PilotRunLedger.objects.filter(command__in=outcome.commands)
    if not ledger.exists():
        return WhyState.WIRED_NEVER_RUN
    if outcome.evidence() == 0 and ledger.filter(purged_at__isnull=False).exists():
        return WhyState.RAN_AND_PURGED
    return WhyState.RAN


def _classify_did(outcome: ChannelOutcome) -> str:
    declaration = ZERO_DECLARATIONS.get(outcome.channel.key)
    produced = outcome.evidence() > 0
    if declaration is not None:
        # A declared-silent channel that STARTS producing is a real event -
        # somebody's stated expectation just became false, and that is worth
        # exactly as much attention as the reverse.
        return DidState.DECLARED_SILENT_NOW_PRODUCING if produced else DidState.DECLARED_SILENT
    return DidState.PRODUCED if produced else DidState.SILENT


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def latest_run_id() -> Optional[str]:
    """The most recently STARTED ledger run - the no-flag default."""
    row = PilotRunLedger.objects.order_by("-started_at").first()
    return row.run_id if row else None


def build_channel_report(run_id: Optional[str] = None, roster: Optional[Roster] = None) -> ChannelReport:
    """
    Assemble the per-channel report for one run.

    `run_id=None` picks the most recent ledger run. Lifetime counts are
    reported alongside run-scoped ones and are what the gate fires on: a
    channel is a failure when it has NEVER produced anything, which is the
    OPS-CORR-0008 reading ("chip channels must be verified to produce rows")
    and does not swing on whether the last run happened to touch it.
    """
    roster = roster or derive_roster()
    if roster.findings or roster.is_empty():
        return ChannelReport(
            run_id=run_id,
            ledger=None,
            roster=roster,
            outcomes=[],
            findings=[],
            derivation_findings=list(roster.findings)
            or [
                "channel roster derivation FAILED: the derived roster is EMPTY. An instrument "
                "that measures nothing must never report all clear."
            ],
        )

    run_id = run_id or latest_run_id()
    ledger = PilotRunLedger.objects.filter(run_id=run_id).first() if run_id else None
    run_cards = _run_card_ids(run_id) if run_id else []

    outcomes: list[ChannelOutcome] = []

    for channel in roster.vote:
        positive, negative, run_positive, run_negative = _vote_counts(channel, run_id)
        by_reason, run_abstentions = _abstention_counts(channel.identity, run_id)
        outcome = ChannelOutcome(
            channel=channel,
            positive=positive,
            negative=negative,
            abstained_by_reason=by_reason,
            run_positive=run_positive,
            run_negative=run_negative,
            run_abstentions=run_abstentions,
        )
        notes: list[str] = []
        if channel.tag and by_reason:
            notes.append(
                f"{sum(by_reason.values())} abstentions exist under `{channel.identity}` but "
                f"CardScanLog has no tag column, so they are identity-scoped context and do "
                f"NOT count as evidence for this tag's channel"
            )
        if channel.tag_unresolved:
            notes.append(
                "tag could not be resolved statically from the cast site - counts are "
                "identity-wide and this channel's true grain is unmeasured"
            )
        outcome.notes = tuple(notes)
        outcomes.append(outcome)

    for channel in roster.extractor:
        counts, unknown = _populated_field_counts(channel.fields)
        by_reason, run_abstentions = _abstention_counts(channel.identity, run_id)
        reconciliation = (
            build_reconciliation_report(channel.identity, run_cards, run_id) if run_cards and run_id else None
        )
        notes = []
        if channel.shares_fields_with:
            notes.append(
                "shares one block of field writes with "
                + ", ".join(f"`{k}`" for k in channel.shares_fields_with)
                + " - these cannot be told apart by field, so the same field counts are "
                "reported for each"
            )
        if unknown:
            notes.append(f"derived field name(s) not on ImageEvidence: {', '.join(unknown)}")
        if not channel.fields:
            notes.append("no ImageEvidence fields attributed - success cannot be measured by value for this extractor")
        outcomes.append(
            ChannelOutcome(
                channel=channel,
                abstained_by_reason=by_reason,
                values_by_field=counts,
                reconciliation=reconciliation,
                run_abstentions=run_abstentions,
                notes=tuple(notes),
            )
        )

    vote_identities = {c.identity for c in roster.vote}
    for channel in roster.abstention:
        by_reason, run_abstentions = _abstention_counts(channel.identity, run_id)
        notes = []
        if channel.identity not in vote_identities:
            notes.append(
                "writes CardScanLog only and casts no votes by design - a zero vote count for "
                "this identity is its intended shape, not a failure"
            )
        outcomes.append(
            ChannelOutcome(
                channel=channel,
                abstained_by_reason=by_reason,
                run_abstentions=run_abstentions,
                notes=tuple(notes),
            )
        )

    findings: list[str] = []
    for outcome in outcomes:
        outcome.commands = _commands_for(outcome.channel, roster)
        outcome.why = _classify_why(outcome, roster)
        outcome.did = _classify_did(outcome)
        outcome.declaration = ZERO_DECLARATIONS.get(outcome.channel.key)

        if outcome.did == DidState.SILENT:
            findings.append(
                f"SILENT CHANNEL: `{outcome.channel.key}` has produced NOTHING - no positive "
                f"vote, no negative vote, no abstention, no value written - and carries no "
                f"ZeroDeclaration. Why: {outcome.why}"
                + (f" (commands: {', '.join(outcome.commands)})" if outcome.commands else "")
                + f". Declared sites: {'; '.join(outcome.channel.sites[:3]) or 'none'}."
            )
        elif outcome.did == DidState.DECLARED_SILENT_NOW_PRODUCING:
            findings.append(
                f"DECLARED-SILENT CHANNEL IS NOW PRODUCING: `{outcome.channel.key}` was "
                f"declared to produce nothing ({outcome.declaration.reason if outcome.declaration else ''}) "
                f"but now carries {outcome.evidence()} rows. Remove the declaration or explain "
                f"the change - a stated expectation just became false."
            )

    # A run that INVOKED a channel's command and still wrote nothing in that
    # run is a failure of the run, distinct from a channel that has never
    # produced anything at all.
    if ledger is not None:
        for outcome in outcomes:
            if ledger.command not in outcome.commands:
                continue
            if outcome.run_positive + outcome.run_negative + outcome.run_abstentions > 0:
                continue
            if outcome.did in (DidState.DECLARED_SILENT,):
                continue
            findings.append(
                f"RUN PRODUCED NOTHING FOR CHANNEL: run `{run_id}` invoked `{ledger.command}`, "
                f"which reaches `{outcome.channel.key}`, but that channel wrote no rows in this "
                f"run (lifetime rows: {outcome.evidence()})."
            )

    return ChannelReport(
        run_id=run_id,
        ledger=ledger,
        roster=roster,
        outcomes=outcomes,
        findings=findings,
        derivation_findings=[],
    )


__all__ = [
    "ChannelReport",
    "ChannelOutcome",
    "ZeroDeclaration",
    "ZeroDeclarationError",
    "ZERO_DECLARATIONS",
    "WhyState",
    "DidState",
    "build_channel_report",
    "latest_run_id",
]
