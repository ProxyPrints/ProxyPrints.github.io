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
another's, both landing on the SAME row within one Stage C pass) triggers several dispatch calls
that mostly resolve to fast, cheap no-ops rather than repeated real work. This is the SAME
"evidence-change event re-opens a card to re-scan, never an elapsed-time trigger" contract issue
#278's own selector already specifies (docs/proposals/stage-e-streaming.md §4 item 4) - deliberately
generic here (every evidence-change fires an attempt, not just #278's own specific detector), since
this module only decides WHETHER to attempt a dispatch, never what any downstream engine does with
it.
"""

from typing import Any

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from cardpicker.models import Card, ImageEvidence


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
    from django_q.tasks import async_task

    async_task("cardpicker.stage_e_dispatch.dispatch_for_card", instance.card_id, "evidence-change")
