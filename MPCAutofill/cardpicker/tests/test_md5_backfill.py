import datetime as dt
from typing import Optional

import pytest

from django.core.management import CommandError, call_command

from cardpicker import md5_backfill
from cardpicker.models import Card, PilotRunLedger
from cardpicker.sources.api import Folder, Image
from cardpicker.sources.source_types import GoogleDrive, SourceTypeChoices
from cardpicker.tests import factories

DEFAULT_DATE = dt.datetime(2023, 1, 1)


def _image(identifier: str, md5_checksum: Optional[str] = None) -> Image:
    return Image(
        id=identifier,
        name=f"{identifier}.png",
        size=1,
        created_time=DEFAULT_DATE,
        modified_time=DEFAULT_DATE,
        height=1110,
        folder=Folder(id="root", name="root", parent=None),
        md5_checksum=md5_checksum,
    )


def _stub_reachable_folders(monkeypatch, unreachable_keys=frozenset()):
    """Every source resolves to a root Folder, except any key in `unreachable_keys` (which
    resolves to None, matching `SourceType.get_all_folders`'s own "dead source" contract) - a
    plain, real Drive API call would otherwise be required here."""

    def fake_get_all_folders(sources):
        return {
            source.key: (None if source.key in unreachable_keys else Folder(id="root", name="root", parent=None))
            for source in sources
        }

    monkeypatch.setattr(GoogleDrive, "get_all_folders", staticmethod(fake_get_all_folders))


def _stub_listing(monkeypatch, listings_by_source_key: dict):
    """`explore_folder` is the one Drive-facing call `walk_source_checksums` makes after
    resolving a root folder - stubbing it here (rather than the underlying
    `GoogleDrive.get_all_images_inside_folder`/`execute_google_drive_api_call`) matches this
    codebase's own established pattern for isolating one source's scan without a live Drive
    connection (see `test_sources.TestUpdateDatabase.test_one_source_failure_does_not_abort_the_others`,
    which stubs `transform_images_into_objects` the same way)."""

    def fake_explore_folder(source, source_type, root_folder):
        return listings_by_source_key.get(source.key, [])

    monkeypatch.setattr(md5_backfill, "explore_folder", fake_explore_folder)


class TestWalkSourceChecksums:
    def test_unreachable_source_reports_unreachable(self, db, monkeypatch):
        source = factories.SourceFactory()
        _stub_reachable_folders(monkeypatch, unreachable_keys={source.key})

        result = md5_backfill.walk_source_checksums(source)

        assert result.reachable is False
        assert result.checksums_by_identifier == {}

    def test_reachable_source_collects_checksums_and_skips_checksum_less_entries(self, db, monkeypatch):
        source = factories.SourceFactory()
        _stub_reachable_folders(monkeypatch)
        _stub_listing(
            monkeypatch,
            {
                source.key: [
                    _image("a", md5_checksum="checksum_a"),
                    _image("b", md5_checksum=None),  # e.g. a listing entry with no md5Checksum at all
                ]
            },
        )

        result = md5_backfill.walk_source_checksums(source)

        assert result.reachable is True
        assert result.checksums_by_identifier == {"a": "checksum_a"}


class TestRunMd5Backfill:
    def test_local_file_source_is_skipped_not_walked(self, db, monkeypatch):
        source = factories.SourceFactory(source_type=SourceTypeChoices.LOCAL_FILE)
        factories.CardFactory(source=source, identifier="a", md5_checksum=None)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("explore_folder must never be called for a checksum-less source")

        monkeypatch.setattr(md5_backfill, "explore_folder", fail_if_called)

        result = md5_backfill.run_md5_backfill(dry_run=True)

        assert result.sources_scanned == 0
        assert result.sources_skipped_no_checksum_support == [source.key]
        assert Card.objects.get(identifier="a").md5_checksum is None

    def test_unreachable_source_is_reported_and_untouched(self, db, monkeypatch):
        source = factories.SourceFactory()
        factories.CardFactory(source=source, identifier="a", md5_checksum=None)
        _stub_reachable_folders(monkeypatch, unreachable_keys={source.key})

        result = md5_backfill.run_md5_backfill(dry_run=True)

        assert result.sources_scanned == 1
        assert result.sources_unreachable == [source.key]
        assert result.matched_files == 0
        assert Card.objects.get(identifier="a").md5_checksum is None

    def test_dry_run_computes_but_never_writes(self, db, monkeypatch):
        source = factories.SourceFactory()
        card = factories.CardFactory(source=source, identifier="a", md5_checksum=None)
        _stub_reachable_folders(monkeypatch)
        _stub_listing(monkeypatch, {source.key: [_image("a", md5_checksum="freshsum")]})

        result = md5_backfill.run_md5_backfill(dry_run=True)

        assert result.matched_files == 1
        assert result.planned_writes == 1
        assert result.written == 0
        card.refresh_from_db()
        assert card.md5_checksum is None  # untouched - dry run

    def test_write_persists_reconciled_checksums(self, db, monkeypatch):
        source = factories.SourceFactory()
        card = factories.CardFactory(source=source, identifier="a", md5_checksum=None)
        _stub_reachable_folders(monkeypatch)
        _stub_listing(monkeypatch, {source.key: [_image("a", md5_checksum="freshsum")]})

        result = md5_backfill.run_md5_backfill(dry_run=False)

        assert result.written == 1
        card.refresh_from_db()
        assert card.md5_checksum == "freshsum"

    def test_already_correct_checksum_is_not_a_planned_write(self, db, monkeypatch):
        source = factories.SourceFactory()
        factories.CardFactory(source=source, identifier="a", md5_checksum="freshsum")
        _stub_reachable_folders(monkeypatch)
        _stub_listing(monkeypatch, {source.key: [_image("a", md5_checksum="freshsum")]})

        result = md5_backfill.run_md5_backfill(dry_run=True)

        assert result.matched_files == 1
        assert result.planned_writes == 0

    def test_listing_entry_with_no_matching_card_is_not_invented(self, db, monkeypatch):
        source = factories.SourceFactory()  # no Card rows created at all
        _stub_reachable_folders(monkeypatch)
        _stub_listing(monkeypatch, {source.key: [_image("not_yet_indexed", md5_checksum="freshsum")]})

        result = md5_backfill.run_md5_backfill(dry_run=True)

        assert result.matched_files == 0
        assert result.planned_writes == 0
        assert Card.objects.count() == 0

    def test_dupe_group_stats_are_global_across_sources(self, db, monkeypatch):
        source_1 = factories.SourceFactory()
        source_2 = factories.SourceFactory()
        factories.CardFactory(source=source_1, identifier="a", md5_checksum=None)
        factories.CardFactory(source=source_2, identifier="b", md5_checksum=None)
        factories.CardFactory(source=source_2, identifier="c", md5_checksum=None)  # unique, no dupe
        _stub_reachable_folders(monkeypatch)
        _stub_listing(
            monkeypatch,
            {
                source_1.key: [_image("a", md5_checksum="shared")],
                source_2.key: [
                    _image("b", md5_checksum="shared"),  # cross-source dupe of "a"
                    _image("c", md5_checksum="unique"),
                ],
            },
        )

        result = md5_backfill.run_md5_backfill(dry_run=True)

        assert result.matched_files == 3
        assert result.dupe_groups == 1
        assert result.dupe_files == 2
        assert result.dupe_factor == pytest.approx(2 / 3)

    def test_source_keys_filter_restricts_the_walk(self, db, monkeypatch):
        source_1 = factories.SourceFactory()
        source_2 = factories.SourceFactory()
        factories.CardFactory(source=source_1, identifier="a", md5_checksum=None)
        factories.CardFactory(source=source_2, identifier="b", md5_checksum=None)
        _stub_reachable_folders(monkeypatch)
        _stub_listing(
            monkeypatch,
            {
                source_1.key: [_image("a", md5_checksum="sum_a")],
                source_2.key: [_image("b", md5_checksum="sum_b")],
            },
        )

        result = md5_backfill.run_md5_backfill(dry_run=True, source_keys=[source_1.key])

        assert result.sources_scanned == 1
        assert result.matched_files == 1


class TestBackfillMd5ChecksumsCommand:
    def test_write_refused_without_a_prior_matching_dry_run(self, db, monkeypatch):
        source = factories.SourceFactory()
        factories.CardFactory(source=source, identifier="a", md5_checksum=None)
        _stub_reachable_folders(monkeypatch)
        _stub_listing(monkeypatch, {source.key: [_image("a", md5_checksum="freshsum")]})

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("backfill_md5_checksums", write=True)

    def test_write_succeeds_after_a_matching_dry_run(self, db, monkeypatch):
        source = factories.SourceFactory()
        card = factories.CardFactory(source=source, identifier="a", md5_checksum=None)
        _stub_reachable_folders(monkeypatch)
        _stub_listing(monkeypatch, {source.key: [_image("a", md5_checksum="freshsum")]})

        call_command("backfill_md5_checksums")  # dry-run (default)
        call_command("backfill_md5_checksums", write=True)

        card.refresh_from_db()
        assert card.md5_checksum == "freshsum"
        ledgers = list(PilotRunLedger.objects.filter(command="backfill_md5_checksums").order_by("started_at"))
        assert len(ledgers) == 2
        assert ledgers[0].dry_run is True and ledgers[0].status == PilotRunLedger.Status.COMPLETED
        assert ledgers[1].dry_run is False and ledgers[1].status == PilotRunLedger.Status.COMPLETED
        assert ledgers[0].counters["matched_files"] == 1
        assert ledgers[1].counters["written"] == 1

    def test_write_refused_when_scope_differs_from_the_dry_run(self, db, monkeypatch):
        source_1 = factories.SourceFactory()
        source_2 = factories.SourceFactory()
        factories.CardFactory(source=source_1, identifier="a", md5_checksum=None)
        factories.CardFactory(source=source_2, identifier="b", md5_checksum=None)
        _stub_reachable_folders(monkeypatch)
        _stub_listing(
            monkeypatch,
            {
                source_1.key: [_image("a", md5_checksum="sum_a")],
                source_2.key: [_image("b", md5_checksum="sum_b")],
            },
        )

        call_command("backfill_md5_checksums", source_keys=[source_1.key])  # dry-run of source_1 only

        with pytest.raises(CommandError, match="FORCED DRY-RUN GUARD"):
            call_command("backfill_md5_checksums", source_keys=[source_2.key], write=True)

    def test_skip_dryrun_check_bypasses_the_guard_and_is_recorded(self, db, monkeypatch, capsys):
        source = factories.SourceFactory()
        card = factories.CardFactory(source=source, identifier="a", md5_checksum=None)
        _stub_reachable_folders(monkeypatch)
        _stub_listing(monkeypatch, {source.key: [_image("a", md5_checksum="freshsum")]})

        call_command("backfill_md5_checksums", write=True, skip_dryrun_check=True)

        printed = capsys.readouterr().out
        assert "SKIP-DRYRUN-CHECK" in printed
        card.refresh_from_db()
        assert card.md5_checksum == "freshsum"
        ledger = PilotRunLedger.objects.get(command="backfill_md5_checksums")
        assert ledger.counters["skip_dryrun_check_used"] is True
