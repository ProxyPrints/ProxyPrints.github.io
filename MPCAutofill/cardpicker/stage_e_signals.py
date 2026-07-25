"""
Stage E Phase 2 - the event-driven trigger half of docs/proposals/stage-e-streaming.md §3
decision (1) ("event-driven ... dispatched on card-create and on evidence-change, with a
low-frequency cron sweep as a correctness backstop, not the primary path"). Two `post_save`
receivers, wired unconditionally in `cardpicker.apps.CardpickerConfig.ready()` (connecting a
Django signal receiver is cheap and side-effect-free by itself) but each a no-op whenever
`settings.STAGE_E_STREAMING_ENABLED` is False (`MPCAutofill/settings.py`'s own docstring) - so this
module ships DEFAULT-OFF exactly like the rest of Phase 2, with no redeploy needed to turn it on.

Both receivers dispatch via `django_q.tasks.async_task`, never inline - a `post_save` handler
running Stage C/D synchronously inside the same request/transaction that just created the
`Card`/`ImageEvidence` row would (a) block whatever view/command triggered the save on a
network-fetch-plus-OCR-cost pipeline stage, and (b) risk seeing the just-committed row before its
own transaction has actually committed if the save happened inside a wider atomic block (a real
risk `local_calculate_verdicts.py`'s own commands avoid by never running inline off a signal at
all). `async_task` queues the work onto django-q2's existing worker pool (`Q_CLUSTER`, already
provisioned in this project - see `settings.py`) instead.

CARD-CREATE: fires once, only on `created=True` - never on an ordinary field-update save (matches
decision (1)'s own "card-create" framing exactly; a re-save of an existing card is not a new-card
event).

EVIDENCE-CHANGE: fires on every `ImageEvidence` save, created or updated - `dispatch_for_card`'s own
downstream Stage C step is naturally idempotent (its own resume filter skips a card whose evidence
is already current, see `stage_e_dispatch._run_stage_c`), and Stage D's own eligibility queries
already exclude a card once it's carrying a vote from a given calculator's own `anonymous_id` - so
a burst of `ImageEvidence` saves for the same card (e.g. one extractor group's write, then
another's, both landing on the SAME row within one Stage C pass) triggers several dispatch calls.

**CORRECTED 2026-07-25 (issue #472, the same §8 Tron pass that corrected the identical
overstated line in `stage_e_shakedown.py`'s own "EVIDENCE-CHANGE ECHO" section and
docs/features/stage-e-operations.md's "Evidence-change echo" section)**: an earlier version of
this paragraph characterized that burst as "mostly resolv[ing] to fast, cheap no-ops rather than
repeated real work." That is WRONG in general - an echo dispatch calls `dispatch_micro_batch` with
NO `batch_size`, so `_select_micro_batch` backfills the echo's own seed card up to the FULL
`STAGE_E_MICRO_BATCH_SIZE` from the Stage C backlog cursor walk. An echo is a COMPLETE micro-batch,
never just the one already-current seed card - cheap (~3.5s fixed overhead, no extraction) ONLY
while the Stage C backlog is genuinely zero at echo time; a non-zero backlog turns an echo into a
real ~25-card extraction batch that itself persists ~25 more `ImageEvidence` rows, queuing ~24
FURTHER echoes - a cascade, not a fixed cost (see `stage_e_shakedown.py`'s own section for the full
measured numbers).

ECHO SUPPRESSION (2026-07-25, issue #472's own build, closing the gap the paragraph above
describes for the ONE caller that can trigger the cascade repeatedly - `stage_e_dispatch.
_run_stage_c`'s own `persist_evidence`/`evidence_transfer.transfer_evidence` writes): every
`ImageEvidence` write performed FROM INSIDE the streaming/shakedown dispatch path is wrapped in
`suppress_evidence_change_echo()` below - the write-side already knows it's running inside a
dispatch (Stage D, over the SAME micro-batch, already covers whatever this write would otherwise
re-trigger a fresh dispatch call to reach), so it flags itself via a `contextvars.ContextVar`
rather than requiring this receiver to infer intent from the write. `_dispatch_on_evidence_change`
below checks that flag first and returns immediately if set - no `async_task` is queued at all for
a write made inside that context. BULK-mode writes (`run_image_evidence_cohort.py`'s own
`persist_evidence` calls, a genuinely independent command that never runs inside a dispatch) are
UNFLAGGED and keep firing this receiver's `async_task` exactly as before this change - only writes
performed BY the dispatch loop itself are suppressed. This is the "documented (not built) fallback"
docs/features/stage-e-operations.md's own "Evidence-change echo" section flagged as becoming
REQUIRED before scaling beyond a bounded pilot - now built.

This is the SAME "evidence-change event re-opens a card to re-scan, never an elapsed-time trigger"
contract issue #278's own selector already specifies (docs/proposals/stage-e-streaming.md §4 item
4) - deliberately generic here (every evidence-change fires an attempt, not just #278's own
specific detector), since this module only decides WHETHER to attempt a dispatch, never what any
downstream engine does with it.
"""

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from cardpicker.models import Card, ImageEvidence

# ECHO SUPPRESSION (module docstring, issue #472) - `True` for the duration of an `ImageEvidence`
# write issued FROM INSIDE `stage_e_dispatch._run_stage_c` (the ONLY caller of
# `suppress_evidence_change_echo` below), `False` otherwise (including every BULK-mode write, which
# never enters this context at all). A `contextvars.ContextVar` rather than a plain module global
# or `threading.local`: correct under both the synchronous per-thread execution this module's own
# django-q worker actually uses today AND any future asyncio-based caller, with no extra code
# needed either way - contextvars propagate correctly across `await` points where a bare
# `threading.local` would not, and behave identically to a `threading.local` for the synchronous
# case this module has today.
_dispatch_persist_in_progress: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "_dispatch_persist_in_progress", default=False
)


@contextmanager
def suppress_evidence_change_echo() -> Iterator[None]:
    """
    Context manager wrapping an `ImageEvidence` write made FROM INSIDE the streaming/shakedown
    dispatch path (`stage_e_dispatch._run_stage_c`'s own `persist_evidence`/
    `evidence_transfer.transfer_evidence` calls - the ONLY caller) - see module docstring's "ECHO
    SUPPRESSION" section for the full rationale. Re-entrant-safe (nested `with` blocks all see
    `True` until the OUTERMOST one exits, via `ContextVar.set`/`.reset`'s own token mechanism) even
    though `_run_stage_c` never actually nests these calls today - defensive, not load-bearing.
    """
    token = _dispatch_persist_in_progress.set(True)
    try:
        yield
    finally:
        _dispatch_persist_in_progress.reset(token)


@receiver(post_save, sender=Card)
def _dispatch_on_card_create(sender: Any, instance: Card, created: bool, **kwargs: Any) -> None:
    if not created:
        return
    if not getattr(settings, "STAGE_E_STREAMING_ENABLED", False):
        return
    from django_q.tasks import async_task

    async_task("cardpicker.stage_e_dispatch.dispatch_for_card", instance.pk, "card-create")


@receiver(post_save, sender=ImageEvidence)
def _dispatch_on_evidence_change(sender: Any, instance: ImageEvidence, **kwargs: Any) -> None:
    if not getattr(settings, "STAGE_E_STREAMING_ENABLED", False):
        return
    if _dispatch_persist_in_progress.get():
        # ECHO SUPPRESSION (module docstring, issue #472) - this write was made FROM INSIDE the
        # dispatch path itself; queuing another dispatch for it would be exactly the cascade risk
        # the module docstring's "CORRECTED 2026-07-25" section describes. BULK-mode writes never
        # set this flag, so they always reach the async_task call below, unchanged.
        return
    from django_q.tasks import async_task

    async_task("cardpicker.stage_e_dispatch.dispatch_for_card", instance.card_id, "evidence-change")
