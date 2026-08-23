"""
Re-sources the `CardPrintingTag` rows mislabelled `source=VoteSource.USER` by the pre-#900
`illustration_vote.cast_illustration_vote` bug to `source=VoteSource.DEDUCTION` (the command's
name predates this fix and still says "retract" - see this module's "RE-SOURCE, DO NOT DELETE"
section below for why the rows are rewritten in place, never dropped). That endpoint derives a
`CardPrintingTag`
whenever a tapped artwork resolves 1:1 to a live candidate printing - the voter only answered a
question about ARTWORK, never printing - but before #900 it cast that derivation at
`source=VoteSource.USER` with the caller's own `vote_surface`: full human weight, able to satisfy
`vote_consensus.resolve_weighted_consensus`'s human-backed gate alone, and indistinguishable in
the database from a genuine printing-confirmation answer. #900 fixed the caster going forward
(`source=VoteSource.DEDUCTION`, its own `illustration_vote.DERIVED_PRINTING_VOTE_SURFACE`) and
explicitly left existing rows alone - re-sourcing those rows to DEDUCTION is this command's
entire job.

IDENTIFICATION - THERE IS NO STORED MARKER (none existed before #900, and the pre-#900 row's own
`vote_surface` is whatever the caller's illustration-vote submission carried, not a distinct
constant - so `vote_surface` alone cannot separate a derived row from a genuine one). The forensic
handle is the sibling `CardArtistVote` written in the SAME transaction from the SAME click:
`cast_illustration_vote`'s artist channel already stamped its own derivation with
`illustration_vote.DERIVED_ARTIST_VOTE_SURFACE` before #900 existed (that discipline predates the
printing-channel fix). A `CardPrintingTag` at `source=USER` sharing a `(card_id, anonymous_id)`
pair with such a `CardArtistVote` is therefore a derived printing tag - strengthened by the
pre-#900 code path itself, which ran an UNCONDITIONAL
`CardPrintingTag.objects.filter(card=, anonymous_id=).delete()` before writing its own row, so an
explicit answer and a derivation could never coexist for the same pair AT THE MOMENT OF THE CLICK.

WHY (card_id, anonymous_id) ALONE IS NOT ENOUGH, AND THE CORRELATION WINDOW THIS ADDS: the
"could never coexist at click time" guarantee above says nothing about what happens AFTER that
click. `views.post_submit_printing_tag` (the SEPARATE, always-explicit printing-vote endpoint)
also does an unconditional delete-then-create for `(card, anonymous_id)`, so a voter who later
submits a genuine explicit printing answer for a card they were once derived-voted on OVERWRITES
that row - same `source=USER`, but now a real answer - while the original, unrelated
`CardArtistVote` sibling (a different table, never touched by that endpoint) is left standing.
Matching on `(card_id, anonymous_id)` alone would misidentify that later, genuine row as derived.
Guarded against here by additionally requiring the `CardPrintingTag.created_at` to fall within
`SIBLING_CORRELATION_WINDOW` of the sibling `CardArtistVote.created_at` - both rows are written by
two back-to-back `.create()` calls inside ONE `transaction.atomic()` block with no external I/O
between them, so a genuine same-click pair is always sub-second apart, while an unrelated later
resubmission is realistically minutes/days apart. A pair sharing `(card_id, anonymous_id)` but
OUTSIDE the window is not re-sourced - it is reported separately as skipped/ambiguous (see
`IdentificationResult.skipped_ambiguous_ids`) rather than guessed at either way.

A SECOND, WITHIN-WINDOW FALSE POSITIVE THE CORRELATION WINDOW ALONE CANNOT CATCH, AND WHY
`is_no_match=False` CLOSES IT: `question_feed._voter_answered_printing_card_ids`'s own docstring
records that before issue #713's fix (`d3dc43de`, 2026-08-06 - predating this endpoint's own
derivation bug fix in #900), a voter whose illustration vote derived ONLY the artist channel (the
N>1-matching-printings case, where the printing channel never fires at all - see point 2 of
`cast_illustration_vote`'s own docstring) was NOT excluded from re-serve, so the SAME card was
served again immediately; "production evidence: both of the only two human illustration votes on
record were each followed within seconds by an `is_no_match` escape vote on the same card." That
`is_no_match=True` row IS a genuine explicit answer (a real "no match" click through
`post_submit_printing_tag`), sharing `(card_id, anonymous_id)` with the artist-vote sibling and
landing well inside `SIBLING_CORRELATION_WINDOW` of it - a within-window false positive the
correlation window cannot distinguish from a real derivation by timing alone. `is_no_match=False`
closes it precisely: the derivation (`illustration_vote.py`, both pre- and post-#900) always
constructs its `CardPrintingTag` with `is_no_match=False` and a live `printing` FK - `is_no_match`
and `printing` are XOR by the model's own `cardprintingtag_printing_xor_no_match` CheckConstraint,
so a derived row can never carry `is_no_match=True` - making this filter strictly narrowing: it can
only ever exclude rows the derivation could not have produced, never a genuine derived one.

RE-SOURCE, DO NOT DELETE. The identification is strong but not airtight - see PR discussion for
the two remaining gaps (the shipped frontend's client-level, not structural, guarantee that a
voter cannot answer a printing question twice for the same card; and the data-side test that
would have settled it outright cannot run today, since the candidate population has drifted).
Deleting the identified rows is irreversible; re-sourcing them to `VoteSource.DEDUCTION` (with
`vote_surface=illustration_vote.DERIVED_PRINTING_VOTE_SURFACE`, matching exactly what #900 itself
now writes for a genuine derivation) achieves the same correction on the consensus gate below
while keeping every row on record, auditable, and restorable if the identification is later shown
wrong. `user`/`anonymous_id` are left untouched by the rewrite, so provenance of who triggered the
original click stays recorded, exactly as #900 already does for new derivations.

NO CONSENSUS RECOMPUTE HAPPENS HERE. This command only re-sources rows in place (or, in a dry run,
reports what it would re-source) - it never calls `printing_consensus.resolve_and_persist_printing`
or any other `_and_persist_*` function. `consensus_recompute` is a separate, separately-authorised
command and MUST be run afterwards for any affected card to actually leave
`PrintingTagStatus.RESOLVED`; until that happens, an affected card's persisted
`printing_tag_status` stays stale (still RESOLVED) even though the vote that earned it no longer
carries human weight. The dry run reports, per affected card currently RESOLVED, whether every one
of its OTHER printing votes (i.e. excluding the rows this command would re-source) is
machine-sourced - if so, that card's resolution would not survive a subsequent
`consensus_recompute`: `VoteSource.DEDUCTION` is itself machine-derived
(`vote_consensus._MACHINE_DERIVED_SOURCES`), so a re-sourced row can no longer satisfy
`resolve_weighted_consensus`'s `has_human_backed` gate either, regardless of any remaining machine
vote's weight or share (`vote_consensus.py`).

DRY-RUN BY DEFAULT (matches `retract_artbox_phash_exemplars`/`retract_stage_d_by_run_id`'s own
convention) - `--write` is required to actually re-source anything.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.illustration_vote import (
    DERIVED_ARTIST_VOTE_SURFACE,
    DERIVED_PRINTING_VOTE_SURFACE,
)
from cardpicker.models import (
    Card,
    CardArtistVote,
    CardPrintingTag,
    PrintingTagStatus,
    VoteSource,
)
from cardpicker.vote_consensus import is_human_backed_source

# See this module's own docstring's "WHY (card_id, anonymous_id) ALONE IS NOT ENOUGH" section -
# a genuine same-transaction pair is always written by two back-to-back `.create()` calls inside
# one `transaction.atomic()` block, with a single DB call (`resolve_and_persist_illustration`)
# between them and no external I/O. Per that same docstring's "WHY THE CORRELATION WINDOW THIS
# ADDS" reasoning plus `question_feed._voter_answered_printing_card_ids`'s unconditional
# CardIllustrationVote exclusion (issue #713/#738, live since 2026-08-06), a voter can never be
# re-served a genuine printing question for this card - or its identity group - once they've cast
# an illustration vote on it, so this window's only remaining job is separating same-transaction
# latency from an unrelated LATER resubmission, and those two populations sit at wholly different
# scales: one transaction's round trip vs. the minutes-to-days gap a real resubmission requires
# (the later endpoint is a separate HTTP request the voter has to consciously make). 60 seconds
# gives generous headroom to absorb request queueing, lock contention, or a GC pause stretching
# that single DB call well past its typical sub-second cost under load, while staying roughly two
# orders of magnitude below the minimum gap a genuine resubmission would show.
SIBLING_CORRELATION_WINDOW = timedelta(seconds=60)


@dataclass
class DerivedPrintingTagRow:
    tag_id: int
    card_id: int
    anonymous_id: str
    # Only meaningful once populated by `annotate_would_leave_resolved` below - True when this
    # row's card is currently PrintingTagStatus.RESOLVED and every one of its OTHER printing
    # votes (excluding every row identified in this same run) is machine-sourced, i.e. the
    # resolution would not survive a subsequent consensus_recompute once this row is re-sourced
    # to VoteSource.DEDUCTION (itself machine-derived, so it can no longer supply the
    # has_human_backed gate either).
    card_would_leave_resolved: bool = False


@dataclass
class IdentificationResult:
    derived: list[DerivedPrintingTagRow] = field(default_factory=list)
    # tag pks sharing a (card_id, anonymous_id) pair with a DERIVED_ARTIST_VOTE_SURFACE sibling,
    # but whose created_at falls outside SIBLING_CORRELATION_WINDOW of it - not retracted, listed
    # separately for human review (module docstring's "WHY (card_id, anonymous_id) ALONE IS NOT
    # ENOUGH" section).
    skipped_ambiguous_ids: list[int] = field(default_factory=list)


def find_derived_printing_tags(window: timedelta = SIBLING_CORRELATION_WINDOW) -> IdentificationResult:
    """
    The identification logic (module docstring) - a plain, testable function, matching this
    codebase's own "keep Command.handle() thin" convention.
    """
    result = IdentificationResult()

    sibling_created_at: dict[tuple[int, str], Any] = {
        (card_id, anonymous_id): created_at
        for card_id, anonymous_id, created_at in CardArtistVote.objects.filter(
            vote_surface=DERIVED_ARTIST_VOTE_SURFACE
        ).values_list("card_id", "anonymous_id", "created_at")
    }
    if not sibling_created_at:
        return result

    candidate_card_ids = {card_id for card_id, _ in sibling_created_at}
    candidate_anonymous_ids = {anonymous_id for _, anonymous_id in sibling_created_at}

    tags = CardPrintingTag.objects.filter(
        source=VoteSource.USER,
        # See module docstring's "A SECOND, WITHIN-WINDOW FALSE POSITIVE" section - the
        # derivation can never produce is_no_match=True (CheckConstraint XOR with printing), so
        # this excludes only rows the derivation could not have written, e.g. a genuine
        # is_no_match escape vote landing inside the correlation window by pre-#713 re-serve.
        is_no_match=False,
        card_id__in=candidate_card_ids,
        anonymous_id__in=candidate_anonymous_ids,
    ).values_list("id", "card_id", "anonymous_id", "created_at")

    for tag_id, card_id, anonymous_id, created_at in tags:
        sibling_at = sibling_created_at.get((card_id, anonymous_id))
        if sibling_at is None:
            # shares neither card_id nor anonymous_id with any derived-artist-vote sibling on its
            # own - the card_id__in/anonymous_id__in prefilter can still admit a row whose
            # (card_id, anonymous_id) PAIR isn't actually a key in the dict (e.g. this card_id
            # paired with a different anonymous_id that does have a sibling elsewhere).
            continue
        if abs(created_at - sibling_at) <= window:
            result.derived.append(DerivedPrintingTagRow(tag_id=tag_id, card_id=card_id, anonymous_id=anonymous_id))
        else:
            result.skipped_ambiguous_ids.append(tag_id)

    return result


def annotate_would_leave_resolved(result: IdentificationResult) -> None:
    """
    Populates `DerivedPrintingTagRow.card_would_leave_resolved` for every row in
    `result.derived`, in place (module docstring's "NO CONSENSUS RECOMPUTE HAPPENS HERE" section -
    this is a READ-ONLY prediction, never a call to `resolve_printing`/
    `resolve_and_persist_printing`).
    """
    if not result.derived:
        return

    card_ids = {row.card_id for row in result.derived}
    derived_tag_ids = {row.tag_id for row in result.derived}

    resolved_card_ids = set(
        Card.objects.filter(pk__in=card_ids, printing_tag_status=PrintingTagStatus.RESOLVED).values_list(
            "pk", flat=True
        )
    )
    if not resolved_card_ids:
        return

    remaining_sources_by_card: dict[int, list[str]] = {card_id: [] for card_id in resolved_card_ids}
    for card_id, source in (
        CardPrintingTag.objects.filter(card_id__in=resolved_card_ids)
        .exclude(pk__in=derived_tag_ids)
        .values_list("card_id", "source")
    ):
        remaining_sources_by_card[card_id].append(source)

    for row in result.derived:
        if row.card_id not in resolved_card_ids:
            continue
        remaining_sources = remaining_sources_by_card[row.card_id]
        row.card_would_leave_resolved = not any(is_human_backed_source(source) for source in remaining_sources)


class Command(BaseCommand):
    help = (
        "Re-sources CardPrintingTag rows mislabelled source=USER by the pre-#900 "
        "illustration-vote printing-derivation bug to source=DEDUCTION - identified as a "
        "USER-sourced, is_no_match=False CardPrintingTag sharing (card, anonymous_id) with a "
        "CardArtistVote at illustration_vote.DERIVED_ARTIST_VOTE_SURFACE, created within "
        f"{SIBLING_CORRELATION_WINDOW.total_seconds():.0f}s of it (same cast_illustration_vote "
        "transaction). Despite the command name, this does NOT delete the identified rows: it "
        "rewrites source=DEDUCTION and vote_surface=DERIVED_PRINTING_VOTE_SURFACE in place, "
        "deliberately reversible, preserving user/anonymous_id. Performs NO consensus recompute: "
        "run consensus_recompute for the affected cards AFTERWARDS for any of them to actually "
        "leave a stale RESOLVED status, since DEDUCTION cannot satisfy the has_human_backed gate "
        "either. Dry-run by default - --write required to actually re-source anything."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--write",
            action="store_true",
            default=False,
            help="Actually re-source the identified rows to DEDUCTION. Default is dry-run: "
            "report every counter below without writing anything.",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        write = kwargs["write"]
        mode = "WRITE" if write else "DRY RUN"

        result = find_derived_printing_tags()
        annotate_would_leave_resolved(result)

        affected_card_ids = sorted({row.card_id for row in result.derived})
        would_leave_resolved_card_ids = sorted({row.card_id for row in result.derived if row.card_would_leave_resolved})

        self.stdout.write(f"[{mode}] retract_derived_illustration_printing_tags")
        self.stdout.write(
            f"  sibling correlation window: {SIBLING_CORRELATION_WINDOW.total_seconds():.0f}s "
            "(rows sharing (card, anonymous_id) with a derived-artist-vote sibling are re-sourced "
            "to DEDUCTION if created within this window of it, else reported as skipped/ambiguous below)"
        )
        self.stdout.write(
            f"Identified {len(result.derived)} derived CardPrintingTag row(s) across "
            f"{len(affected_card_ids)} distinct card(s)."
        )
        self.stdout.write(
            f"  affected card pks: {affected_card_ids[:50]}" + (" (truncated)" if len(affected_card_ids) > 50 else "")
        )
        self.stdout.write(
            f"  {len(would_leave_resolved_card_ids)} of those card(s) are currently RESOLVED and would not "
            "survive a subsequent consensus_recompute once re-sourced to DEDUCTION (no other human-backed "
            f"printing vote remains) - run consensus_recompute for these afterwards. card pks: "
            f"{would_leave_resolved_card_ids[:50]}"
            + (" (truncated)" if len(would_leave_resolved_card_ids) > 50 else "")
        )
        if result.skipped_ambiguous_ids:
            skipped = sorted(result.skipped_ambiguous_ids)
            self.stdout.write(
                f"  SKIPPED (ambiguous) {len(skipped)} row(s): share a (card, anonymous_id) pair with a "
                "derived-artist-vote sibling, but created outside the same-transaction correlation window - "
                f"left untouched for human review. tag pks: {skipped[:50]}"
                + (" (truncated)" if len(skipped) > 50 else "")
            )

        if not write:
            self.stdout.write("Dry run - nothing written.")
            return

        updated_count = CardPrintingTag.objects.filter(pk__in=[row.tag_id for row in result.derived]).update(
            source=VoteSource.DEDUCTION,
            vote_surface=DERIVED_PRINTING_VOTE_SURFACE,
        )
        self.stdout.write(
            f"Re-sourced {updated_count} row(s) to source=DEDUCTION, "
            f"vote_surface={DERIVED_PRINTING_VOTE_SURFACE}. Run consensus_recompute for the affected cards next."
        )
