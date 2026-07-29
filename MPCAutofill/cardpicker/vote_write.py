"""
The single purge-then-write primitive every machine calculator in this app shares.

WHY THIS MODULE EXISTS AT ALL (2026-07-28). PR #526 introduced
`local_calculate_verdicts._purge_and_write_printing_tag_votes` to fix a purge/split ordering bug
plus a cancel-safety hole at the three `CardPrintingTag`-casting Stage D call sites. The same two
defects existed, unfixed, at every OTHER `purge_stale_machine_votes(...)` +
`bulk_create(...)` pair wired up by #519/#520 - nine more sites across seven modules, casting four
different vote models (`CardPrintingTag`, `CardTagVote`, `CardArtistVote`, and the since-retired
`PrintingTagVote`) and keyed on two different target fields (`card_id`, `printing_id`). This module
is #526's primitive with those four axes parameterised; the semantics below are #526's, unchanged.
`PrintingTagVote` was retired on 2026-07-29 (migration 0101) and took the app's only
`printing_id`-keyed call site with it, so every LIVE caller today passes the default
`target_field="card_id"`. The parameter stays because it is what makes this a primitive rather
than a `CardPrintingTag` helper, and `purge_stale_machine_votes` is keyed the same way.

IT IS A SEPARATE MODULE, NOT A FUNCTION IN `local_calculate_verdicts`, BECAUSE OF AN IMPORT CYCLE:
`local_calculate_verdicts` imports from `local_identify_printing_tags` (its `CandidateNameIndex`,
`_eligible_base_queryset`, `generate_run_id`, ...), and `local_identify_printing_tags` is itself
one of the call sites that needs this primitive - so it cannot import back. `local_lands_identify`
and `local_residual_classify` sit on that same import chain, and the management commands that
write vote batches have no business importing a Stage D calculator at all just to do it (the
motivating case was `management/commands/import_external_ip_tags.py`, retired 2026-07-29 with
`PrintingTagVote`; the argument is unchanged for the ones that remain). A leaf module whose only
dependencies are `django.db.transaction`
and `cardpicker.models` is importable from all of them. It is deliberately NOT in `models.py`
alongside `purge_stale_machine_votes` itself: `models.py` is the schema, and this is write-path
policy that composes a model-layer helper with `bulk_create`.

THE THREE PROPERTIES CALLERS ARE BUYING (all three are #526's, restated here because this is now
the place they are implemented):

1. SPLIT/COUNT BEFORE PURGE. A caller that runs an already-voted split (today:
   `local_calculate_verdicts._split_new_printing_tag_votes`, `local_illustration`'s use of it, and
   `local_lands_identify._split_new_votes`) MUST run it BEFORE calling this function and pass its
   `new_votes` output. `purge_stale_machine_votes` deletes by CALCULATOR FAMILY
   (`^<family>-v\\d+$`), which necessarily includes the caller's own CURRENT anonymous_id - so a
   purge run FIRST deletes exactly the rows the split then goes looking for, making the
   `already_voted` counter structurally 0 in every deployment forever. That is not "races never
   happen": it is the guard reporting on a table it just emptied, the literal "zero forever would
   suggest the guard itself is dead code" failure
   `stage_e_dispatch.DispatchOutcome.stage_d_join_key_already_voted`'s own comment warns about.

2. THE PURGE IS SCOPED TO THE ROWS ACTUALLY BEING WRITTEN, NEVER TO THE PRE-SPLIT BATCH. This is
   the trap, and it is a silent data-destruction one: a card whose vote the split just skipped as
   already cast by a concurrent dispatch must keep that winner's row. Purging on the full batch
   would DELETE the winner and then NOT re-insert anything (the loser's vote is no longer in
   `new_votes`), destroying a committed vote with no error and no counter movement. Passing the
   rows-to-write as the single source of both the purge scope and the insert - as this function's
   signature forces - makes that mistake unexpressible at a call site.

   Note the splits check the EXACT current anonymous_id, so a STALE-VERSION row (`...-v1` when the
   calculator is now `...-v2`) is never counted as "already voted" - such a target stays in
   `rows`, gets purged, and is overwritten. The calculator-version self-overwrite behaviour
   #519/#520 added is preserved exactly.

3. CANCEL-SAFETY. The purge is a DELETE and the insert a separate statement. Without a surrounding
   transaction, a process killed between them leaves every affected target with its previous vote
   deleted and no replacement written. This project's operator kills long runs mid-flight
   deliberately and a full-catalog pass takes hours, so this is a routine event, not a disaster
   scenario. `transaction.atomic()` makes the pair all-or-nothing.
"""

import collections
from typing import Any, Optional, Sequence

from django.db import transaction

from cardpicker.models import purge_stale_machine_votes

__all__ = ["purge_and_write_votes"]


def purge_and_write_votes(
    model_class: Any,
    rows: Sequence[Any],
    *,
    anonymous_id: Optional[str] = None,
    target_field: str = "card_id",
    ignore_conflicts: bool = False,
) -> None:
    """
    Purge same-family machine votes for exactly the targets in `rows`, then insert `rows` - both
    inside one transaction. See this module's docstring for the full rationale; the short version
    is that callers must pass POST-SPLIT rows, because `rows` is simultaneously the purge scope
    and the insert payload.

    `model_class` is the vote model (`CardPrintingTag`, `CardTagVote`, `CardArtistVote`);
    `target_field` is the column `purge_stale_machine_votes` keys the purge on and the attribute
    read off each row to build that scope - `card_id` for every vote model that exists today. It
    is still a parameter because the primitive is not `CardPrintingTag`-specific: the retired
    `PrintingTagVote` passed `printing_id`, and any future non-card-keyed vote model would too.

    `anonymous_id` is the identity whose FAMILY is purged. Pass it explicitly when the caller
    purges under one fixed identity even though `rows` may carry others - `local_lands_identify`
    is the live case: its batch mixes `LANDS_ANONYMOUS_ID` and `OCR_ANONYMOUS_ID` votes but has
    only ever purged the lands family, and widening that to the OCR family would be a behaviour
    change well outside an atomicity fix. Leave it `None` to purge each row under its OWN
    `anonymous_id`, grouped into one `purge_stale_machine_votes` call per distinct identity -
    what `local_identify_printing_tags.run_pilot`'s flush already did by hand for its
    multi-engine batches.

    `ignore_conflicts` is passed straight through to `bulk_create` and must match whatever the
    call site used before: it is load-bearing crash-proofing at the sites that set it (the
    residual check-then-insert window their own comments describe), and its absence is equally
    deliberate at the sites that don't - turning it on there would silently swallow a real
    constraint violation this pipeline currently surfaces.

    Returns nothing and does nothing at all for an empty `rows` - an all-collided batch must purge
    NOTHING (property 2 above), so the early return is part of the contract, not an optimisation.

    4. THE SUPERSEDED GENERATION IS ARCHIVED, NOT DESTROYED (2026-07-29 owner ruling: "keep at
    least one prior generation of votes, whose votes are NOT counted"). That copy happens inside
    `purge_stale_machine_votes` - see its docstring for why it lives at the model layer rather
    than here - and is covered by the SAME `transaction.atomic()` below as the purge and the
    insert, so property 3 (cancel-safety) now spans three statements instead of two. All this
    function contributes is the answer to "which run overwrote it": `_superseding_run_id`, read
    off the rows being written.
    """
    if not rows:
        return

    targets_by_anonymous_id: dict[str, list[Any]] = collections.defaultdict(list)
    for row in rows:
        identity = anonymous_id if anonymous_id is not None else row.anonymous_id
        targets_by_anonymous_id[identity].append(getattr(row, target_field))

    superseded_by_run_id = _superseding_run_id(rows)
    with transaction.atomic():
        for identity, target_ids in targets_by_anonymous_id.items():
            purge_stale_machine_votes(
                model_class, identity, target_field, target_ids, superseded_by_run_id=superseded_by_run_id
            )
        model_class.objects.bulk_create(rows, ignore_conflicts=ignore_conflicts)


def _superseding_run_id(rows: Sequence[Any]) -> Optional[str]:
    """
    The `run_id` to stamp on rows this write archives, or None when the batch cannot name one.

    A batch is normally one calculator invocation's output and therefore carries exactly one
    `run_id`; that value is the honest answer to "which run overwrote the generation this write
    replaces". Anything else - a batch with no `run_id` at all (`local_lands_identify`'s pre-#570
    shape, an import command, a test fixture), or one mixing several - gets None rather than an
    arbitrary pick, because a WRONG run stamp on an archived row is worse than a missing one: the
    `--generation-diff` report and issue #575's retention janitor both select on it, and a
    plausible-looking wrong value cannot be distinguished from a right one after the fact.

    `getattr(..., None)` rather than `row.run_id` because this primitive is model-agnostic and
    `run_id` lives on `AbstractWeightedVote`, not on every model a caller could pass.
    """
    run_ids = {getattr(row, "run_id", None) for row in rows}
    if len(run_ids) != 1:
        return None
    only = next(iter(run_ids))
    return only if only else None
