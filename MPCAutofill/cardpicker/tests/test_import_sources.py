import csv

from cardpicker.management.commands.import_sources import (
    maybe_trigger_bootstrap_scan,
    read_sources_csv,
)
from cardpicker.tests.factories import CardFactory, SourceFactory

CSV_HEADER = "name,drive_id,drive_public,description"


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "drive_id", "drive_public", "description"])
        writer.writeheader()
        for name, drive_id, drive_public, description in rows:
            writer.writerow(
                {"name": name, "drive_id": drive_id, "drive_public": drive_public, "description": description}
            )


class TestReadSourcesCsv:
    def test_absent_private_file_is_no_op(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_csv(tmp_path / "drives.csv", [("Alpha", "id_alpha", "true", "Alpha drive")])

        sources = read_sources_csv()

        assert len(sources) == 1
        assert sources[0].name == "Alpha"
        assert sources[0].ordinal == 0

    def test_private_rows_appended_with_ordinal_continuation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_csv(
            tmp_path / "drives.csv",
            [
                ("Alpha", "id_alpha", "true", "Alpha drive"),
                ("Beta", "id_beta", "false", "Beta drive"),
            ],
        )
        _write_csv(tmp_path / "drives.private.csv", [("Gamma", "id_gamma", "false", "Gamma drive")])

        sources = read_sources_csv()

        assert len(sources) == 3
        names = [s.name for s in sources]
        assert names == ["Alpha", "Beta", "Gamma"]
        assert [s.ordinal for s in sources] == [0, 1, 2]

    def test_private_wins_on_duplicate_name(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        _write_csv(
            tmp_path / "drives.csv",
            [
                ("Alpha", "id_alpha_old", "true", "Old Alpha"),
                ("Beta", "id_beta", "false", "Beta drive"),
            ],
        )
        _write_csv(tmp_path / "drives.private.csv", [("Alpha", "id_alpha_new", "false", "New Alpha")])

        sources = read_sources_csv()

        assert len(sources) == 2
        alpha = next(s for s in sources if s.name == "Alpha")
        assert alpha.identifier == "id_alpha_new"
        assert alpha.external_link is None  # drive_public=false
        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "Alpha" in captured.out

    def test_ordinal_is_sequential_after_dedup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_csv(
            tmp_path / "drives.csv",
            [
                ("Alpha", "id_alpha_old", "true", "Old Alpha"),
                ("Beta", "id_beta", "false", "Beta drive"),
            ],
        )
        _write_csv(tmp_path / "drives.private.csv", [("Alpha", "id_alpha_new", "false", "New Alpha")])

        sources = read_sources_csv()

        ordinals = [s.ordinal for s in sources]
        assert ordinals == list(range(len(sources)))


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
