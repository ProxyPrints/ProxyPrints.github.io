"""
Deletes machine-cast votes, in exactly one of two mutually-exclusive, deliberately NARROW modes.

    --run-id <id>           every vote stamped with that one invocation's run_id
    --anonymous-id <id>     one calculator's votes, across the whole catalog, every run_id

WHY THERE IS NO `--all-machine` MODE
------------------------------------
There was an attempt at one (PR #517, "purge every machine-sourced vote across all four vote
tables regardless of run_id"). The owner closed it UNMERGED as too blunt: its blast radius was
"every non-human-backed source" - `{DEDUCTION, OCR, FEDERATED, IMPLICIT}` - across the entire
catalog in a single invocation, with a dry run as the only thing standing between an operator
and the irreversible loss of every machine verdict the pipeline has ever produced. A purge tool
whose worst-case typo destroys the whole machine corpus is the wrong shape regardless of how
carefully its per-source counts are printed.

`--anonymous-id` exists ONLY because it is targeted: ONE exact calculator identity per
invocation, named in full on the command line, printed back in the output. It is the tool for
"calculator X wrote bad rows, remove exactly what X wrote" - the case that motivated it being a
defect in which `stage-d-illustration-v1` wrote votes for several MUTUALLY EXCLUSIVE printings
per card across many run_ids, which `--run-id` cannot clean up without knowing and replaying
every run_id involved, and which no per-run purge can reach at all for rows carrying a NULL
run_id.

Do NOT relax this into a wildcard, prefix, or family-wide mode ("purge every version of
stage-d-join-key"). Each of those recreates PR #517's objection in a smaller box: the operator
stops naming what is being destroyed and starts describing it. One exact id per invocation, and
run the command again for the next one.

OPERATIONAL NOTE - A VOTE PURGE ALONE DOES NOT MAKE CARDS ELIGIBLE AGAIN
-----------------------------------------------------------------------
`local_calculate_verdicts._eligible_cards_queryset` excludes a card from a Stage D calculator's
next run for EITHER of two independent reasons: the card already has a vote from that
`anonymous_id`, OR it has a `CardScanLog` row for that `anonymous_id` whose `skip_reason` is not
in that calculator's rescannable set. `CardScanLog` is an abstention/audit table, not a vote
table, so neither this command's `--run-id` mode nor a bare `--anonymous-id` purge touches it.

A vote-only purge therefore leaves the scan-log half of the exclusion fully intact, and the
calculator skips nearly everything on the re-run - which reads exactly like a broken pipeline.
The scan-log row count is typically an ORDER OF MAGNITUDE larger than the vote count for the
same calculator; measured live, 2026-07-28:

    anonymous_id              votes    CardScanLog rows
    stage-d-join-key-v1       57,945            647,122
    stage-d-fallback-v1       30,306            131,713
    stage-d-illustration-v1        0              2,013
    stage-d-slow-path-v1           0            135,346

So: a FULL re-eligibility purge for a Stage D calculator requires `--anonymous-id X
--include-scan-log`, and the operator should expect the scan-log line of the output to dwarf the
vote lines. `--include-scan-log` is opt-in rather than the default because deleting scan logs
discards the audit trail of what that calculator previously concluded and why it abstained,
which is frequently the thing worth keeping - a vote purge WITHOUT it (drop the verdicts, keep
the record of how they were reached) is a legitimate, narrower operation in its own right. The
two are separate decisions, so they are two separate flags rather than one bundled behaviour.
"""

from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cardpicker.artist_consensus import resolve_and_persist_artist
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardArtistVote,
    CardPrintingTag,
    CardScanLog,
    CardTagVote,
    PilotRunLedger,
    PrintingTagStatus,
    TagVoteStatus,
    VoteSource,
    calculator_family,
)
from cardpicker.printing_consensus import (
    identity_groups_for_card_ids,
    resolve_and_persist_printing,
)
from cardpicker.tag_consensus import resolve_and_persist_tag_votes
from cardpicker.utils import find_stale_applied_migrations
from cardpicker.vote_consensus import is_human_backed_source

# Source not in this set means human-backed. DERIVED from `is_human_backed_source` (the single
# definition the whole app resolves human-backed-ness with) rather than hand-copied, so a future
# new machine source is added in `vote_consensus` alone and can't go stale here: the previous
# hand-maintained literal `{DEDUCTION, OCR}` had already drifted from it (FEDERATED and IMPLICIT
# were added to `vote_consensus._MACHINE_DERIVED_SOURCES` without this copy following). Only the
# `--anonymous-id` mode consults it - `--run-id` deletes by run_id alone and is unchanged.
_MACHINE_SOURCES = frozenset(source for source in VoteSource.values if not is_human_backed_source(source))


@dataclass(frozen=True)
class PurgeResult:
    dry_run: bool = False
    run_id: str = ""
    # Set instead of `run_id` by the `--anonymous-id` mode; the two are never both populated.
    anonymous_id: str = ""
    printing_votes_deleted: int = 0
    artist_votes_deleted: int = 0
    tag_votes_deleted: int = 0
    # `CardScanLog` rows removed - always 0 unless the `--anonymous-id` mode was run with
    # `--include-scan-log`. Reported as its OWN number, never folded into the vote totals: it is
    # audit-trail data, not votes, and an operator reading the output needs to see which of the
    # two things they just destroyed. See the module docstring for why the two are separate.
    scan_log_rows_deleted: int = 0
    # Whether CardScanLog was in scope at all, kept separate from the count so "the flag was
    # passed and there were zero rows" is distinguishable from "the flag was not passed" - the
    # first means the calculator's cards are now eligible again, the second means they are not.
    include_scan_log: bool = False
    affected_card_count: int = 0
    # cards that un-resolved as an EXPECTED, correct consequence of losing machine-only weight -
    # informational, not a violation. See verify_no_machine_only_resolutions' own docstring for
    # why this is the corrected invariant, not "assert status returns to pre-purge state".
    cards_unresolved_by_purge: int = 0
    gate_violations: list[int] = field(default_factory=list)


def verify_no_machine_only_resolutions(card_ids: list[int]) -> list[int]:
    """
    The corrected post-purge invariant (docs/features/catalog-completion-plan.md's Part 1):
    the task's original literal framing - "assert statuses return to pre-run state" - is WRONG
    and would false-positive on the very first real purge. With the real default weights
    (PRINTING_TAG_MIN_VOTES=2, PRINTING_TAG_MACHINE_WEIGHT=0.5, human vote weight 1.0), 1 human vote
    + 2 agreeing machine votes sums to 2.0 and resolves; purging those 2 machine votes correctly
    drops the weight below threshold and the card LEGITIMATELY un-resolves - that's correct
    consensus recalculation, not a violation.

    The invariant actually worth asserting, mirroring local_identify_printing_tags.
    verify_zero_resolutions' own "structurally impossible but verify against real data" spirit:
    any card still RESOLVED (printing, artist, or a specific tag) after re-resolution must have
    AT LEAST ONE surviving human-backed vote behind that specific outcome. A card resolved with
    only machine-sourced survivors is a real, halting violation - resolve_weighted_consensus's
    own human-backed gate should have made this structurally impossible, so if it happens here
    it means something upstream is broken, not that the purge itself did anything wrong.

    THE PRINTING CHECK IS POOLED ACROSS THE IDENTITY GROUP, THE ARTIST/TAG CHECKS ARE NOT
    -----------------------------------------------------------------------------------
    `printing_consensus.resolve_printing` does not resolve a card in isolation: it tallies
    `CardPrintingTag` votes across `card`'s combined identity group (issue #661 -
    `identity_group_card_ids`, every card sharing a byte-identical image file or a
    distance-0 artbox phash), because that group is, by that module's own ruling, ONE
    identification target - a human confirming one member resolves every member. A gate that
    inspected only `card`'s own `CardPrintingTag` rows was therefore asking a question the
    resolver does not answer in those terms: it flagged every OTHER member of a group as
    machine-only the moment a human vote landed on just one of them, even though the resolved
    outcome those members carry is, in fact, human-backed - via a twin, exactly as
    `resolve_printing` intends. This check now pools the same way, over the same group
    (`identity_groups_for_card_ids`, the batch form of `identity_group_card_ids`), so it asks its
    question at the grain the resolver actually answers it.

    `resolve_and_persist_artist`/`resolve_and_persist_tag_votes` are NOT identity-group-pooled -
    they resolve `card` alone, so the artist/tag halves below are deliberately left checking
    `card`'s own votes only. Pooling them here would be inventing a grouping the resolver itself
    does not perform.

    NOTE: this function checks Card-level resolution status only (printing_tag_status,
    artist_vote_status, tag_vote_statuses). There is no per-CanonicalCard resolution status in
    the schema to check: the one model that would have needed one, `PrintingTagVote`, was
    retired on 2026-07-29 (migration 0101) having never had a resolver or a row. If a
    per-printing resolution status field is ever added, add the analogous check then.

    Returns the list of violating card pks (empty means clean).
    """
    violations: set[int] = set()
    cards = list(Card.objects.filter(pk__in=card_ids).prefetch_related("artist_votes", "tag_votes"))

    resolved_card_ids = [card.pk for card in cards if card.printing_tag_status == PrintingTagStatus.RESOLVED]
    identity_groups = identity_groups_for_card_ids(resolved_card_ids)
    group_card_ids = {member_id for group in identity_groups.values() for member_id in group}
    printing_votes_by_card_id: dict[int, list[CardPrintingTag]] = {}
    if group_card_ids:
        for vote in CardPrintingTag.objects.filter(card_id__in=group_card_ids, is_no_match=False):
            printing_votes_by_card_id.setdefault(vote.card_id, []).append(vote)

    for card in cards:
        if card.printing_tag_status == PrintingTagStatus.RESOLVED:
            group = identity_groups.get(card.pk, [card.pk])
            printing_survivors = [
                vote
                for member_id in group
                for vote in printing_votes_by_card_id.get(member_id, [])
                if vote.printing_id == card.inferred_canonical_card_id
            ]
            if not any(is_human_backed_source(v.source) for v in printing_survivors):
                violations.add(card.pk)

        if card.artist_vote_status == ArtistVoteStatus.RESOLVED:
            artist_survivors = card.artist_votes.filter(artist=card.inferred_canonical_artist, is_unknown=False)
            if not any(is_human_backed_source(v.source) for v in artist_survivors):
                violations.add(card.pk)

        for tag_name, status in (card.tag_vote_statuses or {}).items():
            if status not in (TagVoteStatus.RESOLVED_APPLY, TagVoteStatus.RESOLVED_REJECT):
                continue
            tag_survivors = card.tag_votes.filter(tag__name=tag_name)
            if not any(is_human_backed_source(v.source) for v in tag_survivors):
                violations.add(card.pk)

    return sorted(violations)


def _re_resolve_and_count_unresolved(affected_card_ids: set[int]) -> int:
    """
    Re-resolves printing/artist/tag consensus for every affected card after a delete, returning
    how many LOST a previously-RESOLVED printing status (an expected, correct consequence of
    losing machine weight - see `verify_no_machine_only_resolutions`, not a violation).

    Extracted verbatim from `purge_run` so both modes re-resolve identically: a card must
    un-resolve the same way whether the votes behind it were removed by run_id or by
    anonymous_id. Deliberately NOT parameterised by mode - there is no correct reason for the
    two to diverge here, so there is nothing to switch on.
    """
    cards_unresolved = 0
    for card in Card.objects.filter(pk__in=affected_card_ids):
        was_resolved = card.printing_tag_status == PrintingTagStatus.RESOLVED
        resolve_and_persist_printing(card)
        resolve_and_persist_artist(card)
        resolve_and_persist_tag_votes(card)
        card.refresh_from_db()
        if was_resolved and card.printing_tag_status != PrintingTagStatus.RESOLVED:
            cards_unresolved += 1
    return cards_unresolved


def purge_by_anonymous_id(anonymous_id: str, dry_run: bool = False, include_scan_log: bool = False) -> PurgeResult:
    """
    Deletes every MACHINE-SOURCED vote carrying EXACTLY `anonymous_id`, across all four vote
    tables and across every run_id - including rows whose `run_id` is NULL, which `purge_run`
    can never reach by construction (a NULL matches no `--run-id` filter) - then re-resolves
    every affected card. With `include_scan_log=True`, also deletes that id's `CardScanLog`
    rows; see the module docstring for why that is opt-in and why a Stage D re-eligibility purge
    needs it.

    THE HUMAN-VOTE GUARD IS THIS FUNCTION'S FIRST STATEMENT, AND IT IS STRUCTURAL
    ----------------------------------------------------------------------------
    Human voters identify themselves with client-generated UUIDs
    (`frontend/src/common/anonymousId.ts`); machine calculators use a versioned
    `<family>-v<N>` string. `models.calculator_family` returns None for anything that is not the
    latter, so refusing every id it returns None for makes passing a human's UUID IMPOSSIBLE,
    not merely discouraged - the operator cannot typo, paste, or script their way into deleting
    one person's voting history, and there is no flag that turns the check off. This is enforced
    in code rather than by convention or documentation precisely because the failure is silent
    and irreversible: a UUID that reached the delete would match real rows and remove them
    without anything looking wrong.

    The `source__in=_MACHINE_SOURCES` filter is the SECOND, independent layer of the same
    guarantee: even for a well-formed calculator id, a human-backed row that somehow carried it
    is not deleted. Neither layer is redundant - the first stops a human IDENTITY being
    targeted, the second stops a human VOTE being collateral.

    Unlike `purge_run` this does NOT stamp `PilotRunLedger.purged_at`. Deliberate: this mode
    removes one calculator's rows from potentially thousands of runs, and none of those runs has
    been purged - their other calculators' votes are untouched - so marking them purged would
    record something false.

    Raises `CommandError` (not ValueError) for a rejected id so the refusal surfaces identically
    whether this is reached through `manage.py` or called directly.
    """
    if calculator_family(anonymous_id) is None:
        raise CommandError(
            f"REFUSED: {anonymous_id!r} is not a machine calculator anonymous_id - "
            "calculator_family() returns None for it, which is true of every human voter's "
            "UUID. This mode can only ever purge machine calculators (ids of the form "
            "'<family>-v<N>', e.g. 'stage-d-illustration-v1'). Human votes are never purgable "
            "by this command, and there is no flag to override this."
        )

    printing_votes = CardPrintingTag.objects.filter(anonymous_id=anonymous_id, source__in=_MACHINE_SOURCES)
    artist_votes = CardArtistVote.objects.filter(anonymous_id=anonymous_id, source__in=_MACHINE_SOURCES)
    tag_votes = CardTagVote.objects.filter(anonymous_id=anonymous_id, source__in=_MACHINE_SOURCES)
    # NOT source-filtered: CardScanLog has no `source` field at all (it is an abstention record,
    # not a vote - see the model's own docstring). The `calculator_family` guard above is what
    # keeps this exact-id filter off human territory, and only a calculator ever writes here.
    scan_log_rows = CardScanLog.objects.filter(anonymous_id=anonymous_id)

    affected_card_ids: set[int] = set()
    affected_card_ids.update(printing_votes.values_list("card_id", flat=True))
    affected_card_ids.update(artist_votes.values_list("card_id", flat=True))
    affected_card_ids.update(tag_votes.values_list("card_id", flat=True))

    printing_count = printing_votes.count()
    artist_count = artist_votes.count()
    tag_count = tag_votes.count()
    # Counted even when the flag is off, but reported as "would be left behind" rather than
    # "deleted" - see Command.handle. An operator who forgot the flag needs to see the number
    # they are leaving in place, since it is the number that will keep their cards ineligible.
    scan_log_count = scan_log_rows.count()

    if dry_run:
        return PurgeResult(
            dry_run=True,
            anonymous_id=anonymous_id,
            printing_votes_deleted=printing_count,
            artist_votes_deleted=artist_count,
            tag_votes_deleted=tag_count,
            scan_log_rows_deleted=scan_log_count if include_scan_log else 0,
            include_scan_log=include_scan_log,
            affected_card_count=len(affected_card_ids),
        )

    printing_votes.delete()
    artist_votes.delete()
    tag_votes.delete()
    if include_scan_log:
        scan_log_rows.delete()

    cards_unresolved = _re_resolve_and_count_unresolved(affected_card_ids)
    gate_violations = verify_no_machine_only_resolutions(sorted(affected_card_ids))

    return PurgeResult(
        dry_run=False,
        anonymous_id=anonymous_id,
        printing_votes_deleted=printing_count,
        artist_votes_deleted=artist_count,
        tag_votes_deleted=tag_count,
        scan_log_rows_deleted=scan_log_count if include_scan_log else 0,
        include_scan_log=include_scan_log,
        affected_card_count=len(affected_card_ids),
        cards_unresolved_by_purge=cards_unresolved,
        gate_violations=gate_violations,
    )


def purge_run(run_id: str, dry_run: bool = False) -> PurgeResult:
    """
    The actual purge logic (docs/features/catalog-completion-plan.md's Part 1) - a plain,
    testable function, matching this module's own convention of keeping Command.handle() thin
    (see run_name_frequency_elimination/run_content_phash_backfill's identical shape).

    Unchanged by the 2026-07-28 addition of `purge_by_anonymous_id`: this mode still deletes by
    run_id alone (no source filter, no anonymous_id filter) and still leaves `CardScanLog`
    entirely untouched. `--include-scan-log` is NOT offered here and must not be added - a run
    spans every calculator that participated in it, so a scan-log delete scoped to a run_id
    would discard several calculators' audit trails at once, which is the bundling the
    anonymous-id mode exists to avoid.
    """
    printing_votes = CardPrintingTag.objects.filter(run_id=run_id)
    artist_votes = CardArtistVote.objects.filter(run_id=run_id)
    tag_votes = CardTagVote.objects.filter(run_id=run_id)

    affected_card_ids: set[int] = set()
    affected_card_ids.update(printing_votes.values_list("card_id", flat=True))
    affected_card_ids.update(artist_votes.values_list("card_id", flat=True))
    affected_card_ids.update(tag_votes.values_list("card_id", flat=True))

    printing_count = printing_votes.count()
    artist_count = artist_votes.count()
    tag_count = tag_votes.count()

    if dry_run:
        return PurgeResult(
            dry_run=True,
            run_id=run_id,
            printing_votes_deleted=printing_count,
            artist_votes_deleted=artist_count,
            tag_votes_deleted=tag_count,
            affected_card_count=len(affected_card_ids),
        )

    printing_votes.delete()
    artist_votes.delete()
    tag_votes.delete()

    cards_unresolved = _re_resolve_and_count_unresolved(affected_card_ids)
    gate_violations = verify_no_machine_only_resolutions(sorted(affected_card_ids))

    PilotRunLedger.objects.filter(run_id=run_id).update(purged_at=timezone.now())

    return PurgeResult(
        dry_run=False,
        run_id=run_id,
        printing_votes_deleted=printing_count,
        artist_votes_deleted=artist_count,
        tag_votes_deleted=tag_count,
        affected_card_count=len(affected_card_ids),
        cards_unresolved_by_purge=cards_unresolved,
        gate_violations=gate_violations,
    )


class Command(BaseCommand):
    help = (
        "Deletes machine-cast votes in exactly one of two narrow modes (docs/features/"
        "catalog-completion-plan.md's Part 1), then re-resolves every affected card so stored "
        "printing/artist/tag status reflects the surviving votes. --run-id purges exactly one "
        "invocation's votes; --anonymous-id purges exactly one machine calculator's votes across "
        "every run_id (including NULL-run_id rows, which --run-id cannot reach), optionally "
        "with its CardScanLog rows via --include-scan-log. Exactly one mode is required - there "
        "is deliberately no --all-machine or wildcard mode, see the module docstring."
    )

    def add_arguments(self, parser: Any) -> None:
        # A required mutually-exclusive group: argparse enforces exactly-one for real CLI
        # invocations. `handle` re-checks anyway - see the comment there, it is NOT redundant.
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--run-id", default=None, help="Purge exactly this run_id's votes.")
        mode.add_argument(
            "--anonymous-id",
            default=None,
            help=(
                "Purge exactly this ONE machine calculator's votes across every run_id, "
                "including NULL-run_id rows. Must be a machine calculator id ('<family>-v<N>', "
                "e.g. 'stage-d-illustration-v1'); a human voter's UUID is refused. No wildcards, "
                "no prefixes, one exact id per invocation."
            ),
        )
        parser.add_argument(
            "--include-scan-log",
            action="store_true",
            default=False,
            help=(
                "--anonymous-id only: ALSO delete that id's CardScanLog rows. Required to make "
                "its cards eligible for a re-run (a vote purge alone leaves the scan-log half of "
                "the eligibility exclusion intact); expect roughly an order of magnitude more "
                "rows than votes. Off by default because it destroys the calculator's abstention "
                "audit trail."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print counts without deleting anything or re-resolving any card.",
        )

    @staticmethod
    def _report_counts(result: PurgeResult) -> None:
        """
        Per-table counts, for BOTH modes and for both dry and write runs - the dry run's version
        is the operator's confirmation step, so it must be the SAME breakdown they will see
        afterwards, not a summary of it.

        The verb changes with the run: a dry run says "WOULD DELETE", a write says "DELETED".
        There is no way to require an operator to have dry-run first, so the alternative
        safeguard is that a write's output can never be misread as a preview. The exact target
        id is echoed on its own line for the same reason - the output should be sufficient, on
        its own, to reconstruct what was destroyed.

        CardScanLog is printed separately from the vote tables (and only when it was in scope):
        it is audit data, not votes, and folding it into a total would hide the single largest
        number in the output behind a label that does not describe it.

        The per-vote-table line keeps its exact pre-2026-07-28 wording so an operator's (or a
        log scraper's) existing reading of `--run-id` output is unchanged - the new information
        is added around it, never by rewording it. ONE DELIBERATE EXCEPTION, 2026-07-29: the
        `printing tag votes: N` field is gone, along with `PurgeResult.printing_tag_votes_deleted`,
        because `PrintingTagVote` itself is gone (migration 0101). The alternative - keeping the
        field pinned at 0 forever for output-shape stability - was rejected: a purge report naming
        a table that no longer exists is a claim about work this command did not do, and this
        module's whole design premise is that its output must be sufficient on its own to
        reconstruct what was destroyed. Three vote tables are enumerated here now, not four.
        """
        verb = "WOULD DELETE" if result.dry_run else "DELETED"
        target = f"--anonymous-id={result.anonymous_id}" if result.anonymous_id else f"--run-id={result.run_id}"
        print(f"{verb} (target: {target})")
        print(
            f"printing votes: {result.printing_votes_deleted}, "
            f"artist votes: {result.artist_votes_deleted}, "
            f"tag votes: {result.tag_votes_deleted}, "
            f"affected cards: {result.affected_card_count}"
        )
        if result.include_scan_log:
            print(f"CardScanLog rows (abstention audit trail, NOT votes): {result.scan_log_rows_deleted}")

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code (see docs/features/catalog-completion-plan.md's rebuild command) before "
                "running this command."
            )

        run_id = kwargs.get("run_id")
        anonymous_id = kwargs.get("anonymous_id")
        dry_run = kwargs["dry_run"]
        include_scan_log = kwargs.get("include_scan_log", False)

        # NOT redundant with add_arguments' mutually-exclusive group. Django 4.2's
        # `call_command` does map that group onto its kwargs form (verified: `call_command(...,
        # run_id=x, anonymous_id=y)` raises argparse's own "not allowed with argument"), so the
        # parser covers both entry points TODAY - but a direct `Command().handle(**kwargs)` call
        # never touches a parser at all, and neither would a future Django that stopped
        # reconstructing the group. This check is what makes "exactly one mode" a property of
        # the code rather than of a library's kwargs handling. Do not delete it as redundant.
        if (run_id is None) == (anonymous_id is None):
            raise CommandError(
                "Pass exactly one of --run-id or --anonymous-id (got "
                f"run_id={run_id!r}, anonymous_id={anonymous_id!r}). These are two different, "
                "deliberately narrow purge scopes and combining them is not supported; there is "
                "no mode that purges everything."
            )
        if include_scan_log and anonymous_id is None:
            raise CommandError(
                "--include-scan-log is only valid with --anonymous-id. CardScanLog rows are "
                "per-calculator audit records; a run_id spans every calculator that took part in "
                "that run, so there is no correct run-scoped scan-log delete."
            )

        mode = "DRY RUN" if dry_run else "WRITE"

        if anonymous_id is not None:
            print(
                f"[{mode}] purge_machine_votes --anonymous-id={anonymous_id}"
                + (" --include-scan-log" if include_scan_log else "")
            )
            result = purge_by_anonymous_id(anonymous_id, dry_run=dry_run, include_scan_log=include_scan_log)
            self._report_counts(result)
            if not include_scan_log:
                remaining = CardScanLog.objects.filter(anonymous_id=anonymous_id).count()
                print(
                    f"CardScanLog rows for {anonymous_id}: {remaining} LEFT IN PLACE "
                    "(--include-scan-log not passed). These still exclude their cards from this "
                    "calculator's next run - re-run with --include-scan-log if the goal is to "
                    "make those cards eligible again."
                )
        else:
            assert run_id is not None
            print(f"[{mode}] purge_machine_votes --run-id={run_id}")

            ledger_entry = PilotRunLedger.objects.filter(run_id=run_id).first()
            if ledger_entry is None:
                print(
                    f"(no PilotRunLedger row found for run_id={run_id} - proceeding anyway, purge target is unaffected)"
                )
            else:
                print(
                    f"ledger context: command={ledger_entry.command} status={ledger_entry.status} "
                    f"dry_run={ledger_entry.dry_run} votes_written={ledger_entry.votes_written} "
                    f"started_at={ledger_entry.started_at}"
                )

            result = purge_run(run_id, dry_run=dry_run)
            self._report_counts(result)

        if dry_run:
            print("Dry run - nothing deleted, no card re-resolved.")
            return

        print(
            f"{result.cards_unresolved_by_purge} card(s) correctly un-resolved as a consequence "
            "of losing machine-only weight (expected, not a violation)."
        )

        if result.gate_violations:
            raise CommandError(
                f"GATE VIOLATION: {len(result.gate_violations)} card(s) are RESOLVED with only "
                f"machine-sourced surviving votes behind that outcome, which should be "
                f"structurally impossible per resolve_weighted_consensus's own human-backed gate "
                f"- STOP and investigate before continuing. Affected card pks: "
                f"{result.gate_violations[:50]}" + (" (truncated)" if len(result.gate_violations) > 50 else "")
            )

        print(f"Gate check passed: 0/{result.affected_card_count} affected cards resolved machine-only.")
