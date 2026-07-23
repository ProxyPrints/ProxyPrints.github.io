"""
JestaProxy ticket (2026-07-23) - retroactive re-derivation half: `local_ocr.parse_legal_line`'s
`_PROXY_MARKER_RE` gained an unbounded substring match for "proxy"/"proxies"/"proxied" (catches a
maker brand name glued directly onto the word with no space, e.g. "JestaProxy", "ValarProxy")
plus a bounded "original design" maker-attribution heuristic (see that regex's own comment for
the full false-positive analysis this change is built on). This command re-applies the CURRENT
parser to every `ImageEvidence` row's already-stored `legal_line_raw_text` and persists any
resulting flip of `legal_line_proxy_marker_detected` from False to True.

PARSE-ONLY, ZERO FETCHES: the only input is `ImageEvidence.legal_line_raw_text`, already on disk
- no image fetch, no re-crop, no re-OCR. Matches `reparse_collector_evidence`'s own "zero image
fetches" contract, and this command is simpler than that one for a structural reason: this field
carries no candidate-matching step (see `local_calculate_verdicts.py`'s own "moderator-flag
SIGNAL, not veto" 2026-07-21 correction - `legal_line_proxy_marker_detected` does not gate or
retract any Stage-D join-key vote, it is packaged into `SlowPathVerdict.raw_signals` for human
review only), so there is no `CardPrintingTag`/`CardScanLog` retraction, no
`printing_consensus.resolve_and_persist_printing` call, and no resolved-consensus safety gate
here - unlike `reparse_collector_evidence`/`retract_stage_d_by_run_id`, this is a pure field-level
correction on `ImageEvidence` itself.

SCOPE: every `ImageEvidence` row (not scoped to the CURRENT row per card the way
`reparse_collector_evidence._current_evidence_for_card` is - there is no per-card candidate-
matching step here to scope to a single "live" row; every stored `legal_line_raw_text` is equally
correctable regardless of whether it belongs to a card's current or a superseded
`content_phash`) with `legal_line_proxy_marker_detected=False` (explicitly False, never NULL - a
NULL row means the extractor never reached a conclusion at all, e.g. a "fetch_failed"/"no-text"
skip, and carries no `legal_line_raw_text` to re-derive from either) and a non-empty
`legal_line_raw_text`.

ADDITIVE-ONLY INVARIANT: this command only ever flips False -> True, never the reverse. This
follows by construction from `local_ocr.py`'s own regex change being a strict superset of the old
pattern (every prior alternative - "not for sale", the old \\b-bounded proxy/proxies/proxied,
playtest - is still present verbatim, only the proxy family lost its boundary anchors and one new
alternative was added) - a row already True under the OLD parser is provably still True under the
NEW one, so this command's own selector (`legal_line_proxy_marker_detected=False`) never even
considers a True row for re-evaluation. Not just argued: `reparse_legal_line_proxy_marker`
verifies this on every row it touches, structurally (only a False-or-unconsidered row is ever
written), and the command's own `--write` path never issues an `UPDATE` that could set the field
back to False.

PHASE 0 RAILS (`cardpicker.pilot_run_lifecycle`, issues #362/#153, PR #373): the forced-dry-run
guard (a `--write` invocation refuses to proceed without a matching COMPLETED dry-run
`PilotRunLedger` row for this command within the recency window, `--skip-dryrun-check` to
override) and the counters-before-output/resilient-terminal-output hardening are both wired in
here, matching `consensus_recompute`/`local_calculate_verdicts`'s own usage. `scope=None`
throughout (module docstring's own SCOPE paragraph) - this command always operates over the WHOLE
`legal_line_proxy_marker_detected=False` population, no caller-chosen cohort narrower than "the
whole command" the way `reparse_collector_evidence`'s `--selector`/`--card-ids-file` is, matching
`consensus_recompute`/`local_calculate_verdicts`'s own identical reasoning for `scope=None`.

Dry-run by default (matches every other pilot command's own convention); `--write` required to
persist anything.
"""

from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from cardpicker.local_identify_printing_tags import generate_run_id
from cardpicker.local_ocr import parse_legal_line
from cardpicker.models import ImageEvidence, PilotRunLedger
from cardpicker.pilot_run_lifecycle import (
    add_dry_run_guard_arguments,
    enforce_dry_run_precondition,
    initial_counters,
    merge_counters,
    resilient_terminal_output,
)
from cardpicker.utils import find_stale_applied_migrations, get_baked_git_sha

# matches Card.objects...iterator(chunk_size=500)/ImageEvidence bulk_update batch_size precedent
# used elsewhere in this codebase's own management commands (reparse_collector_evidence.py).
_BATCH_SIZE = 500


@dataclass
class LegalLineProxyMarkerReparseResult:
    dry_run: bool = False
    run_id: str = ""
    considered: int = 0
    # defensive-only counter (module docstring's ADDITIVE-ONLY INVARIANT) - should always be 0
    # given select_evidence_ids' own filter already excludes True rows; kept so a future caller
    # of reparse_legal_line_proxy_marker with a hand-built id list still gets a correct report
    # rather than a silent no-op.
    already_true: int = 0
    still_false: int = 0
    flipped_false_to_true: int = 0
    # capped audit sample of newly-True rows, matching this codebase's own "up to N, for the
    # report" convention (ReparseResult.audit / JoinKeyCalculatorResult.audit, etc.)
    audit: list[dict[str, Any]] = field(default_factory=list)


def select_evidence_ids() -> list[int]:
    """Every `ImageEvidence` row that's a live candidate for a False -> True flip: currently
    explicitly False (never NULL - module docstring) and carrying a non-empty
    `legal_line_raw_text` (an empty string can never match `_PROXY_MARKER_RE`, so excluding it
    here is a pure cost optimization over the full considered set, not a correctness filter -
    `reparse_legal_line_proxy_marker` would reach the identical `still_false` conclusion for an
    empty-text row on its own)."""
    return list(
        ImageEvidence.objects.filter(legal_line_proxy_marker_detected=False)
        .exclude(legal_line_raw_text="")
        .values_list("pk", flat=True)
    )


def reparse_legal_line_proxy_marker(
    evidence_ids: list[int], run_id: str, dry_run: bool = True, audit_sample_size: int = 20
) -> LegalLineProxyMarkerReparseResult:
    """
    The actual re-derivation (module docstring) - a plain, testable function, matching this
    codebase's own "keep Command.handle() thin" convention (`reparse_collector_evidence.
    reparse_and_retract` / `retract_stage_d_by_run_id.retract_run_id`).
    """
    result = LegalLineProxyMarkerReparseResult(dry_run=dry_run, run_id=run_id)
    to_update: list[ImageEvidence] = []

    for evidence in ImageEvidence.objects.filter(pk__in=evidence_ids).iterator(chunk_size=_BATCH_SIZE):
        result.considered += 1

        if evidence.legal_line_proxy_marker_detected is True:
            # ADDITIVE-ONLY INVARIANT (module docstring) - structurally unreachable given
            # select_evidence_ids' own filter, but this function is also called directly by
            # tests/future callers with a hand-built id list, so this guard is real, not
            # decorative: a True row is left alone unconditionally, never re-written.
            result.already_true += 1
            continue

        fresh = parse_legal_line(evidence.legal_line_raw_text)
        if not fresh.proxy_marker_detected:
            result.still_false += 1
            continue

        result.flipped_false_to_true += 1
        if len(result.audit) < audit_sample_size:
            result.audit.append(
                {
                    "evidence_id": evidence.pk,
                    "card_id": evidence.card_id,
                    "legal_line_raw_text": evidence.legal_line_raw_text,
                }
            )

        evidence.legal_line_proxy_marker_detected = True
        to_update.append(evidence)

    if not dry_run and to_update:
        for start in range(0, len(to_update), _BATCH_SIZE):
            ImageEvidence.objects.bulk_update(
                to_update[start : start + _BATCH_SIZE], ["legal_line_proxy_marker_detected"]
            )

    return result


class Command(BaseCommand):
    help = (
        "JestaProxy ticket: re-applies the CURRENT local_ocr.parse_legal_line proxy-marker "
        "regex (unbounded proxy/proxies/proxied substring + 'original design' heuristic) to "
        "every ImageEvidence row's stored legal_line_raw_text and flips "
        "legal_line_proxy_marker_detected from False to True wherever the fresh parse now "
        "detects a marker. Parse-only - zero image fetches, zero OCR re-run. Additive-only: "
        "never flips True to False. Dry-run by default; --write required to persist anything. "
        "--write also requires a matching COMPLETED dry-run within --dry-run-window-hours "
        "(forced-dry-run guard, issue #362) - see --skip-dryrun-check to override."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually persist the legal_line_proxy_marker_detected flips. Default is "
            "dry-run: compute and report every counter below without writing anything. "
            "Requires a matching recent COMPLETED dry-run ledger row (forced-dry-run guard) "
            "unless --skip-dryrun-check is passed.",
        )
        parser.add_argument(
            "--audit-sample-size",
            type=int,
            default=20,
            help="How many newly-True rows to include in the printed audit sample (default 20).",
        )
        parser.add_argument("--run-id", default=None, help="Reuse a specific run_id. Default: freshly generated.")
        # Forced-dry-run guard (issue #362, Phase 0 rails): this command always operates over the
        # WHOLE legal_line_proxy_marker_detected=False population - no caller-chosen cohort
        # narrower than "the whole command" (module docstring's own SCOPE paragraph), matching
        # consensus_recompute/local_calculate_verdicts's own identical reasoning - so the guard
        # below always passes scope=None.
        add_dry_run_guard_arguments(parser, write_flag="--write")

    def handle(self, *args: Any, **kwargs: Any) -> None:
        stale = find_stale_applied_migrations()
        if stale:
            raise CommandError(
                f"STALE IMAGE: the DB has {len(stale)} migration(s) applied that this image's "
                f"own code doesn't know about ({stale[:10]}{'...' if len(stale) > 10 else ''}) - "
                "this image is older than a previously-deployed one. Rebuild with the current "
                "code before running this command."
            )

        write = kwargs["write"]
        skip_used = enforce_dry_run_precondition(
            command="reparse_legal_line_proxy_marker",
            write_mode=write,
            skip_check=kwargs["skip_dryrun_check"],
            window_hours=kwargs["dry_run_window_hours"],
            scope=None,
        )

        evidence_ids = select_evidence_ids()
        dry_run = not write
        mode = "WRITE" if write else "DRY RUN"
        self.stdout.write(f"[{mode}] reparse_legal_line_proxy_marker candidates={len(evidence_ids)}")

        if not evidence_ids:
            self.stdout.write("No candidate ImageEvidence rows found - nothing to do.")
            return

        run_id = kwargs["run_id"] or generate_run_id()
        ledger = PilotRunLedger.objects.create(
            run_id=run_id,
            command="reparse_legal_line_proxy_marker",
            dry_run=dry_run,
            status=PilotRunLedger.Status.RUNNING,
            git_sha=get_baked_git_sha(),
            counters=initial_counters(skip_dryrun_check_used=skip_used),
        )
        try:
            result = reparse_legal_line_proxy_marker(
                evidence_ids, run_id=run_id, dry_run=dry_run, audit_sample_size=kwargs["audit_sample_size"]
            )

            # Counters-before-output (production incident 2026-07-23, see
            # cardpicker.pilot_run_lifecycle's own module docstring point 1): the ledger row is
            # saved COMPLETED here, BEFORE the terminal summary prints below - a BrokenPipeError
            # on a severed stdout while printing that summary must never look like this run failed.
            ledger.status = PilotRunLedger.Status.COMPLETED
            ledger.finished_at = timezone.now()
            # repurposed for this command, same convention reparse_collector_evidence's own
            # ledger.votes_written comment gives: rows this run's own write actually touched, not
            # "votes cast" (this command casts no votes at all).
            ledger.votes_written = result.flipped_false_to_true
            ledger.counters = merge_counters(
                ledger.counters,
                {
                    "considered": result.considered,
                    "already_true": result.already_true,
                    "still_false": result.still_false,
                    "flipped_false_to_true": result.flipped_false_to_true,
                },
            )
            ledger.save(update_fields=["status", "finished_at", "votes_written", "counters"])

            with resilient_terminal_output():
                self.stdout.write(
                    f"considered={result.considered} already_true={result.already_true} "
                    f"still_false={result.still_false}"
                )
                if dry_run:
                    self.stdout.write(f"(dry-run) would_flip_false_to_true={result.flipped_false_to_true}")
                else:
                    self.stdout.write(f"flipped_false_to_true={result.flipped_false_to_true}")
                for entry in result.audit:
                    self.stdout.write(f"  sample: {entry}")
        except Exception:
            # Only a still-RUNNING row gets marked FAILED here - a run this invocation already
            # marked COMPLETED above must never be overwritten by a later exception (e.g. from the
            # terminal print, if resilient_terminal_output didn't already swallow it).
            if ledger.status == PilotRunLedger.Status.RUNNING:
                ledger.status = PilotRunLedger.Status.FAILED
                ledger.finished_at = timezone.now()
                ledger.save(update_fields=["status", "finished_at"])
            raise
