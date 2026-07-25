"""
Tests for cardpicker.stage_e_signals - the card-create/evidence-change event triggers
(docs/proposals/stage-e-streaming.md §3 decision (1)) and, since 2026-07-25 (issue #472), the
`suppress_evidence_change_echo` ECHO SUPPRESSION mechanism (see that module's own docstring).
`django_q.tasks.async_task` is monkeypatched at `cardpicker.stage_e_signals` itself (both
receivers import it inline, at call time, inside the function body - a patch applied to the name
INSIDE that module before the save is what a fresh `from django_q.tasks import async_task` call
actually observes).
"""

from typing import Any

from django.test import override_settings

from cardpicker import stage_e_signals
from cardpicker.stage_e_signals import suppress_evidence_change_echo
from cardpicker.tests.factories import CardFactory, ImageEvidenceFactory

STREAMING_ON = override_settings(STAGE_E_STREAMING_ENABLED=True)


def _install_async_task_spy(monkeypatch: Any) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def _fake_async_task(*args: Any, **kwargs: Any) -> None:
        calls.append(args)

    # Both receivers do `from django_q.tasks import async_task` INSIDE the function body - patch
    # the real source module so that fresh import observes the fake.
    import django_q.tasks as django_q_tasks_module

    monkeypatch.setattr(django_q_tasks_module, "async_task", _fake_async_task)
    return calls


class TestEvidenceChangeEchoSuppression:
    @STREAMING_ON
    def test_a_write_outside_the_dispatch_context_fires_async_task(self, db: Any, monkeypatch: Any) -> None:
        card = CardFactory(content_phash=42)  # before the spy - isolates this to the EVIDENCE save
        calls = _install_async_task_spy(monkeypatch)

        ImageEvidenceFactory(card=card)  # an ordinary BULK-mode-shaped save, no context wrapper

        assert len(calls) == 1
        assert calls[0] == ("cardpicker.stage_e_dispatch.dispatch_for_card", card.pk, "evidence-change")

    @STREAMING_ON
    def test_a_write_inside_the_dispatch_context_fires_no_async_task(self, db: Any, monkeypatch: Any) -> None:
        card = CardFactory(content_phash=42)
        calls = _install_async_task_spy(monkeypatch)

        with suppress_evidence_change_echo():
            ImageEvidenceFactory(card=card)

        assert calls == []

    @STREAMING_ON
    def test_the_flag_resets_after_the_context_exits(self, db: Any, monkeypatch: Any) -> None:
        card_a = CardFactory(content_phash=1)
        card_b = CardFactory(content_phash=2)
        calls = _install_async_task_spy(monkeypatch)

        with suppress_evidence_change_echo():
            ImageEvidenceFactory(card=card_a)
        ImageEvidenceFactory(card=card_b)  # outside the context again

        assert len(calls) == 1
        assert calls[0] == ("cardpicker.stage_e_dispatch.dispatch_for_card", card_b.pk, "evidence-change")

    def test_disabled_by_default_fires_no_async_task_regardless_of_context(self, db: Any, monkeypatch: Any) -> None:
        """STAGE_E_STREAMING_ENABLED's own gate is checked FIRST, before the suppression flag -
        confirms the two gates are independent (this test runs WITHOUT @STREAMING_ON)."""
        calls = _install_async_task_spy(monkeypatch)
        card = CardFactory(content_phash=42)

        ImageEvidenceFactory(card=card)

        assert calls == []

    def test_the_context_manager_itself_is_reentrant_safe(self) -> None:
        """Nested `with` blocks (never actually exercised by production code today - `_run_stage_c`
        never nests these calls - but the mechanism itself must not misbehave if it ever did)."""
        assert stage_e_signals._dispatch_persist_in_progress.get() is False
        with suppress_evidence_change_echo():
            assert stage_e_signals._dispatch_persist_in_progress.get() is True
            with suppress_evidence_change_echo():
                assert stage_e_signals._dispatch_persist_in_progress.get() is True
            # the OUTER context is still active after the inner one exits.
            assert stage_e_signals._dispatch_persist_in_progress.get() is True
        assert stage_e_signals._dispatch_persist_in_progress.get() is False


class TestCardCreateSignalUnaffectedByEvidenceSuppression:
    @STREAMING_ON
    def test_card_create_still_fires_inside_an_evidence_suppression_context(self, db: Any, monkeypatch: Any) -> None:
        """The suppression flag is scoped to the EVIDENCE-CHANGE receiver only - a Card creation
        inside the same context is a different signal entirely and must be unaffected."""
        calls = _install_async_task_spy(monkeypatch)

        with suppress_evidence_change_echo():
            card = CardFactory(content_phash=42)

        assert len(calls) == 1
        assert calls[0] == ("cardpicker.stage_e_dispatch.dispatch_for_card", card.pk, "card-create")
