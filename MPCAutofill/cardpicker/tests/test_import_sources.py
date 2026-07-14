from cardpicker.management.commands.import_sources import maybe_trigger_bootstrap_scan
from cardpicker.tests.factories import CardFactory, SourceFactory


class TestMaybeTriggerBootstrapScan:
    def test_no_sources_does_not_trigger(self, db, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "cardpicker.management.commands.import_sources.async_task", lambda *a, **kw: calls.append((a, kw))
        )

        maybe_trigger_bootstrap_scan()

        assert calls == []

    def test_sources_but_no_cards_triggers_once(self, db, monkeypatch):
        SourceFactory()
        calls = []
        monkeypatch.setattr(
            "cardpicker.management.commands.import_sources.async_task", lambda *a, **kw: calls.append((a, kw))
        )

        maybe_trigger_bootstrap_scan()

        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args == ("django.core.management.call_command", "update_database")
        assert kwargs == {}

    def test_sources_and_cards_already_exist_does_not_trigger(self, db, monkeypatch):
        source = SourceFactory()
        CardFactory(source=source)
        calls = []
        monkeypatch.setattr(
            "cardpicker.management.commands.import_sources.async_task", lambda *a, **kw: calls.append((a, kw))
        )

        maybe_trigger_bootstrap_scan()

        assert calls == []
