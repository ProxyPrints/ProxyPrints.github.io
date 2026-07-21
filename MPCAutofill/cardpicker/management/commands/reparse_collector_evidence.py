"""
Supersede/re-vote tooling (issue #259 follow-up, "Stage D no-text bucket: OCR preprocessing/crop
recovery"): re-parses `ImageEvidence.collector_line_raw_text` with the CURRENT
`local_ocr.parse_collector_line`, then re-derives the join-key calculator's own conclusion for
each card via `local_calculate_verdicts.calculate_join_key_verdict` - the EXISTING, unmodified
verdict function, not a re-derivation of its candidate-matching/agreement-check logic - and
compares that fresh conclusion against what's actually RECORDED (the card's current
`stage-d-join-key-v1` `CardPrintingTag` vote or `CardScanLog` skip row). Retracts (deletes) the
recorded vote/scan-log for exactly the cards where the conclusion changed, so the card becomes
eligible again for `local_calculate_verdicts`'s own eligibility query on its next invocation.

ZERO IMAGE FETCHES: every input here (`ImageEvidence`'s own stored fields, `CandidateNameIndex`,
`CanonicalCard` metadata) is already in the database or an on-disk Scryfall cache - no network
call, no `fetch_card_image`, anywhere in this command.

WHY COMPARE AGAINST THE RECORDED VERDICT, NOT AGAINST ImageEvidence's OWN STORED PARSE: an
earlier design compared the fresh re-parse of `collector_line_raw_text` against what
`ImageEvidence` already had stored for `collector_line_set_code`/`collector_line_collector_number`
- that comparison is a SILENT NO-OP for the "no-text" selector's whole intended use case. Once a
card has genuinely been RE-EXTRACTED (issue #259's improved `image_evidence.py` preprocessing,
via `run_image_evidence_cohort`'s own `--card-ids-file` targeting), `compute_card_evidence`
itself already writes the FRESH, correct parse straight onto `ImageEvidence` - there is no drift
left for a stored-field comparison to detect, even though the join-key calculator's own past
CONCLUSION (a stale `CardScanLog(skip_reason="no-text")` row from BEFORE the re-extraction) is
exactly what still needs retracting. Comparing against the RECORDED verdict instead - what the
join-key calculator actually concluded and wrote - catches this correctly for both selectors:
the "parser-bug" selector (where the raw text never changed, only the parser did) and the
"no-text" selector (where the raw text and stored parse fields already changed via re-extraction,
but the recorded verdict has not yet been re-derived from them).

TWO-STEP RUNBOOK (this command's own --help repeats this - read it before running either step):

  1. THIS COMMAND - re-parse + retract.
     - `--selector parser-bug`: the #260 parser fix alone is enough here - this command
       re-applies the FIXED `parse_collector_line` to `ImageEvidence` rows already carrying the
       OLD bug's misparsed `collector_line_set_code` shape (a bare print-run-denominator+rarity
       token, e.g. "361r" - see `local_ocr.py`'s `_DENOMINATOR_RARITY_TOKEN_RE` and PR #260's own
       fix). No re-extraction needed - the stored `collector_line_raw_text` was always fine, only
       the OLD parser code misread it.
     - `--selector no-text --stage-d-run-id RUN_ID`: THIS COMMAND ALONE recovers nothing new for
       this selector on a first pass - a no-text card's stored raw text/parsed fields are exactly
       what the extractor already concluded, and re-parsing unchanged text with an unchanged
       parser reproduces the same "no-text" outcome (`unchanged`, not `changed`, in this
       command's own counts). Real OCR-recovery gains require RE-EXTRACTION FIRST: run
       `run_image_evidence_cohort --card-ids-file <same cohort's card ids>` to re-fetch/re-crop/
       re-OCR exactly these cards with issue #259's improved multi-tier preprocessing (this
       refreshes `ImageEvidence.collector_line_raw_text`/`collector_line_set_code`/
       `collector_line_collector_number` directly, via the SAME `compute_card_evidence` this
       command never calls) - THEN run this command again against the same `--stage-d-run-id`:
       it will now detect the join-key calculator's own now-different conclusion and retract the
       stale no-text scan-log row.
  2. `local_calculate_verdicts` (UNCHANGED by this PR) - once step 1 retracts a card's stale
     vote/scan-log, it is eligible again for that command's own `_eligible_cards_queryset` and
     gets a fresh join-key verdict the next time it runs.

SAFETY GATE: never retracts a card whose `printing_consensus.resolve_printing(card)` is not
`None` - this covers BOTH a resolved printing AND a resolved `NO_MATCH` consensus (verified
against that function's own return contract, not assumed - it returns the `NO_MATCH` sentinel,
not `None`, for that case). This is the MORE CONSERVATIVE of two possible readings (card-level
vs. vote-level survivorship), matching `local_identify_printing_tags.verify_zero_resolutions`'s
own card-level check rather than the narrower "does this specific vote still survive within the
resolution" reading - chosen deliberately: a stale machine vote sitting inside an
already-settled community decision is safer left for a human to look at than silently retracted,
even when retracting it is provably harmless to the resolution itself. Gated cards are listed
for human review, never silently skipped or force-retracted. The `ImageEvidence` PARSED-FIELD
update (`collector_line_set_code`/`collector_line_collector_number`) still happens for a gated
card - it is not vote/consensus state, so refreshing it is harmless even when the vote/scan-log
retraction itself is withheld.

Dry-run by default; `--write` required to persist anything (matches `local_calculate_verdicts`/
`purge_machine_votes`'s own convention).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.local_calculate_verdicts import (
    JOIN_KEY_ANONYMOUS_ID,
    JoinKeyVerdict,
    _resolve_candidates_for_card,
    calculate_join_key_verdict,
)
from cardpicker.local_identify_printing_tags import CandidateNameIndex, generate_run_id
from cardpicker.local_ocr import parse_collector_line
from cardpicker.models import (
    Card,
    CardPrintingTag,
    CardScanLog,
    ImageEvidence,
    PilotRunLedger,
)
from cardpicker.printing_consensus import resolve_and_persist_printing, resolve_printing
from cardpicker.utils import (
    find_stale_applied_migrations,
    get_baked_git_sha,
    read_card_ids_file,
)

# The #260 bug shape stored in collector_line_set_code (a bare print-run-denominator+rarity
# token, e.g. "361r") - duplicated as a literal rather than importing local_ocr.py's own private
# `_DENOMINATOR_RARITY_TOKEN_RE`, matching this codebase's established "avoid a hard cross-
# module coupling to a sibling engine's private regex/constant" convention (see e.g.
# local_calculate_verdicts.py's own JOIN_KEY_CONFIDENCE_BOTH comment for the identical reasoning
# it gives for duplicating rather than importing its own sibling-module constants).
_PARSER_BUG_SET_CODE_SHAPE = r"^\d{1,4}[a-z]?$"


@dataclass
class ReparseResult:
    dry_run: bool = False
    run_id: str = ""
    considered: int = 0
    no_evidence: int = 0
    no_prior_join_key_state: int = 0
    unchanged: int = 0
    changed: int = 0
    retracted: int = 0
    gate_refused_card_ids: list[int] = field(default_factory=list)
    # capped audit sample, matching JoinKeyCalculatorResult/PurgeResult's own "up to N, for the
    # report" convention elsewhere in this codebase.
    audit: list[dict[str, Any]] = field(default_factory=list)


def select_card_ids_parser_bug() -> list[int]:
    """Every card carrying an `ImageEvidence` row whose CURRENTLY STORED
    `collector_line_set_code` matches the old #260 bug's own misparse shape - the exact cohort
    that fix is for. A card can carry more than one `ImageEvidence` row (a prior content_hash) -
    deduplicated to distinct card ids here; whether a given card's CURRENT (matching
    `content_phash`) evidence row is the one carrying the bug shape is decided per-card by
    `reparse_and_retract`'s own `_current_evidence_for_card` lookup, same as every other
    selector."""
    return sorted(
        set(
            ImageEvidence.objects.filter(collector_line_set_code__regex=_PARSER_BUG_SET_CODE_SHAPE).values_list(
                "card_id", flat=True
            )
        )
    )


def select_card_ids_no_text(stage_d_run_id: str) -> list[int]:
    """Every card carrying a `CardScanLog(anonymous_id=JOIN_KEY_ANONYMOUS_ID,
    skip_reason="no-text")` row from exactly `stage_d_run_id` - one specific past
    `local_calculate_verdicts` invocation's own no-text cohort."""
    return sorted(
        set(
            CardScanLog.objects.filter(
                anonymous_id=JOIN_KEY_ANONYMOUS_ID, skip_reason="no-text", run_id=stage_d_run_id
            ).values_list("card_id", flat=True)
        )
    )


def _current_evidence_for_card(card: Card) -> Optional[ImageEvidence]:
    """The CURRENT `ImageEvidence` row for `card` - same convention
    `local_calculate_verdicts.run_join_key_calculator`'s own eligibility query uses:
    `content_hash` must match the card's LIVE `content_phash` (a stale evidence row from a prior
    image version is never re-parsed), most-recently-updated row first."""
    if card.content_phash is None:
        return None
    return (
        ImageEvidence.objects.filter(card_id=card.pk, content_hash=card.content_phash)
        .filter(extractor_versions__has_key="collector_line_ocr")
        .order_by("-updated_at")
        .first()
    )


def _recorded_join_key_state(card: Card) -> Optional[tuple[Any, ...]]:
    """The join-key calculator's own LAST RECORDED conclusion for `card` - a `CardPrintingTag`
    vote (at most one can exist for this anonymous_id, per that model's own unique constraints)
    or a `CardScanLog` skip row (possibly more than one across separate runs - most recent by
    `scanned_at` wins, matching `_eligible_cards_queryset`'s own "any non-rescannable row"
    exclusion, which doesn't care which run wrote it, only that one exists). `None` means the
    join-key calculator has never reached a conclusion for this card at all (e.g. a pending
    "no-evidence" resume-filter target, or a card never scanned) - nothing recorded to compare a
    fresh verdict against, so nothing to retract either."""
    vote = CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).first()
    if vote is not None:
        return ("vote", vote.printing_id, vote.is_no_match)
    scan = CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).order_by("-scanned_at").first()
    if scan is not None:
        return ("skip", scan.skip_reason)
    return None


def _verdict_state(verdict: JoinKeyVerdict) -> tuple[Any, ...]:
    """The comparable shape of a freshly-computed `JoinKeyVerdict` - same (kind, ...) tuple shape
    `_recorded_join_key_state` returns, so the two are directly comparable."""
    if verdict.skip_reason:
        return ("skip", verdict.skip_reason)
    return ("vote", verdict.printing_pk, verdict.is_no_match)


def reparse_and_retract(
    card_ids: list[int],
    run_id: str,
    dry_run: bool = True,
    audit_sample_size: int = 20,
    default_cards_path: Optional[Path] = None,
) -> ReparseResult:
    """
    The actual re-parse + retract logic (module docstring) - a plain, testable function,
    matching this codebase's own "keep Command.handle() thin" convention
    (`purge_machine_votes.purge_run` / `local_calculate_verdicts.run_join_key_calculator`).
    """
    result = ReparseResult(dry_run=dry_run, run_id=run_id)
    index = CandidateNameIndex()  # built once, reused across the whole cohort - matches
    # run_join_key_calculator's own "one query over CanonicalCard, not one per card" precedent.

    for card in Card.objects.filter(pk__in=card_ids).iterator(chunk_size=500):
        evidence = _current_evidence_for_card(card)
        if evidence is None:
            result.no_evidence += 1
            continue
        result.considered += 1

        fresh = parse_collector_line(evidence.collector_line_raw_text)
        fresh_set_code = fresh.set_code or ""
        fresh_collector_number = fresh.collector_number or ""
        fields_changed = (
            fresh_set_code != evidence.collector_line_set_code
            or fresh_collector_number != evidence.collector_line_collector_number
        )
        # Refresh the IN-MEMORY evidence object regardless of dry_run - calculate_join_key_verdict
        # below must see the FRESH parse either way (a dry-run's whole point is computing what
        # WOULD happen); only the .save() a few lines down is gated on --write.
        evidence.collector_line_set_code = fresh_set_code
        evidence.collector_line_collector_number = fresh_collector_number

        recorded_state = _recorded_join_key_state(card)
        if recorded_state is None:
            result.no_prior_join_key_state += 1
            continue

        candidates = _resolve_candidates_for_card(card.name, index, default_cards_path=default_cards_path)
        fresh_verdict = calculate_join_key_verdict(card.pk, evidence, candidates)
        fresh_state = _verdict_state(fresh_verdict)

        if fresh_state == recorded_state:
            result.unchanged += 1
            continue

        result.changed += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append({"card_id": card.pk, "recorded": recorded_state, "fresh": fresh_state})

        if dry_run:
            continue

        if fields_changed:
            evidence.save(update_fields=["collector_line_set_code", "collector_line_collector_number"])

        # SAFETY GATE (module docstring) - card-level, re-checked LIVE (resolve_printing, not the
        # cached printing_tag_status field) - covers BOTH a resolved printing and a resolved
        # NO_MATCH consensus.
        if resolve_printing(card) is not None:
            result.gate_refused_card_ids.append(card.pk)
            continue

        CardPrintingTag.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).delete()
        CardScanLog.objects.filter(card=card, anonymous_id=JOIN_KEY_ANONYMOUS_ID).delete()
        resolve_and_persist_printing(card)
        result.retracted += 1

    return result


class Command(BaseCommand):
    help = (
        "Supersede/re-vote tooling (issue #259 follow-up): re-parses ImageEvidence.collector_"
        "line_raw_text with the CURRENT local_ocr parser and retracts the stale stage-d-join-"
        "key-v1 vote/scan-log for any card whose join-key CONCLUSION changed as a result - zero "
        "image fetches. See this command's own module docstring for the full two-step runbook "
        "(re-extraction via run_image_evidence_cohort --card-ids-file is a SEPARATE, "
        "prerequisite step for the --selector no-text case). Dry-run by default; --write "
        "required to persist anything."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--card-ids-file",
            type=str,
            default=None,
            help="Path to a newline-separated file of explicit card pks to target. Mutually "
            "exclusive with --selector.",
        )
        parser.add_argument(
            "--selector",
            choices=["parser-bug", "no-text"],
            default=None,
            help="parser-bug: cards whose CURRENT ImageEvidence.collector_line_set_code matches "
            "the old #260 bug's misparse shape. no-text: cards carrying a CardScanLog"
            "(anonymous_id=stage-d-join-key-v1, skip_reason='no-text') from --stage-d-run-id. "
            "Mutually exclusive with --card-ids-file.",
        )
        parser.add_argument(
            "--stage-d-run-id",
            type=str,
            default=None,
            help="Required with --selector no-text - the run_id of the local_calculate_verdicts "
            "invocation whose no-text scan-log rows to target.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually persist ImageEvidence field updates and retract stale votes/scan-"
            "logs. Default is dry-run: compute and count everything without writing.",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code before running this command."
            )

        card_ids_file = kwargs["card_ids_file"]
        selector = kwargs["selector"]
        if bool(card_ids_file) == bool(selector):
            raise CommandError("Exactly one of --card-ids-file or --selector is required.")

        if card_ids_file:
            card_ids = read_card_ids_file(card_ids_file)
        elif selector == "parser-bug":
            card_ids = select_card_ids_parser_bug()
        else:
            stage_d_run_id = kwargs["stage_d_run_id"]
            if not stage_d_run_id:
                raise CommandError("--selector no-text requires --stage-d-run-id.")
            card_ids = select_card_ids_no_text(stage_d_run_id)

        if not card_ids:
            self.stdout.write("No candidate cards found for this selector - nothing to do.")
            return

        run_id = kwargs["run_id"] or generate_run_id()
        dry_run = not kwargs["write"]
        mode = "WRITE" if kwargs["write"] else "DRY RUN"
        self.stdout.write(f"[{mode}] reparse_collector_evidence run_id={run_id} candidates={len(card_ids)}")

        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="reparse_collector_evidence",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
        )
        try:
            result = reparse_and_retract(card_ids, run_id=run_id, dry_run=dry_run)

            self.stdout.write(
                f"considered={result.considered} no_evidence={result.no_evidence} "
                f"no_prior_join_key_state={result.no_prior_join_key_state} "
                f"unchanged={result.unchanged} changed={result.changed}"
            )
            if dry_run:
                self.stdout.write(f"(dry-run) would_retract={result.changed - len(result.gate_refused_card_ids)}")
            else:
                self.stdout.write(f"retracted={result.retracted} gate_refused={len(result.gate_refused_card_ids)}")
            if result.gate_refused_card_ids:
                self.stdout.write(
                    f"HUMAN REVIEW NEEDED - {len(result.gate_refused_card_ids)} card(s) refused "
                    "retraction (currently a RESOLVED consensus - printing or NO_MATCH). Affected "
                    f"card pks: {result.gate_refused_card_ids[:50]}"
                    + (" (truncated)" if len(result.gate_refused_card_ids) > 50 else "")
                )
            for entry in result.audit[:10]:
                self.stdout.write(f"  sample: {entry}")

            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            # repurposed for this command: rows this run's own write actually touched (retracted),
            # not "votes cast" (this command casts none) - matches votes_written's own doc-level
            # framing as "best-effort visibility", not a hard cross-command contract.
            ledger.votes_written = result.retracted
            ledger.save(update_fields=["status", "finished_at", "votes_written"])
        except Exception:
            ledger.status = PilotRunLedger.Status.FAILED
            ledger.finished_at = timezone.now()
            ledger.save(update_fields=["status", "finished_at"])
            raise
