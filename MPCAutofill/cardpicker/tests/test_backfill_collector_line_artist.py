"""
Tests for `cardpicker.collector_line_artist`'s BACKFILL LAYER (`backfill_eligible_evidence_
queryset`, `run_collector_line_artist_backfill`) and the `backfill_collector_line_artist`
management command wired on top of it - PR #569's own recorded open item. Real ORM, pytest-django's
ephemeral test DB (never production - see `docs/troubleshooting.md`'s "Running backend pytest on
the production box" entry). No network calls, no image fetch, no OCR: every input is an
already-persisted `ImageEvidence.collector_line_raw_text`/`legal_line_raw_text` string.

Deliberately mirrors `test_backfill_modern_artist_names.py`'s structure case for case - the two
backfills re-read different stored strings off the same table under the same currency and
never-overwrite rules, so a divergence between the two suites should be visible as a missing test,
not hidden behind a different layout.
"""

from io import StringIO

import pytest

from django.core.management import call_command

from cardpicker.collector_line_artist import (
    backfill_eligible_evidence_queryset,
    build_artist_lexicon,
    run_collector_line_artist_backfill,
)
from cardpicker.models import ImageEvidence, PilotRunLedger
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CardFactory,
    ImageEvidenceFactory,
    SourceFactory,
)

# see test_printing_consensus.py for why this capture-and-restore fixture exists
_SHARED_FACTORIES = [
    CardFactory,
    SourceFactory,
    CanonicalArtistFactory,
    CanonicalExpansionFactory,
    CanonicalCardFactory,
]

# A collector line whose artist credit is clipped by the 35%-width crop (the population this
# recovery exists for), and the untruncated full-width read of the same print row.
CLIPPED_COLLECTOR_LINE = "159/281R\nMOM ¢ EN LINDSEY L"
FULL_LEGAL_LINE = "159/281R\nMOM ¢ EN LINDSEY LOOK"


@pytest.fixture(autouse=True)
def _preserve_shared_factory_sequences():
    before = {f: f._meta.next_sequence() for f in _SHARED_FACTORIES}
    for f, n in before.items():
        f.reset_sequence(n, force=True)
    yield
    for f, n in before.items():
        f.reset_sequence(n, force=True)


def _evidence(card, **overrides):
    defaults = dict(
        content_hash=card.content_phash or 0,
        collector_line_raw_text=CLIPPED_COLLECTOR_LINE,
        legal_line_raw_text="",
        artist_ocr_name="",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestBackfillEligibleEvidenceQueryset:
    def test_both_source_strings_blank_excluded(self, db):
        card = CardFactory(content_phash=1)
        _evidence(card, collector_line_raw_text="", legal_line_raw_text="")

        assert list(backfill_eligible_evidence_queryset()) == []

    def test_only_the_legal_line_populated_is_still_eligible(self, db):
        """The full-width read alone is enough - it is the BETTER of the two sources (it carries
        the artist credit whole where the collector crop clips it), so a row with only that one
        must not be filtered out."""
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, collector_line_raw_text="", legal_line_raw_text=FULL_LEGAL_LINE)

        assert list(backfill_eligible_evidence_queryset()) == [evidence]

    def test_already_named_excluded(self, db):
        card = CardFactory(content_phash=1)
        _evidence(card, artist_ocr_name="Someone Else")

        assert list(backfill_eligible_evidence_queryset()) == []

    def test_stale_content_hash_excluded(self, db):
        card = CardFactory(content_phash=1)
        _evidence(card, content_hash=999)

        assert list(backfill_eligible_evidence_queryset()) == []

    def test_current_blank_named_row_included(self, db):
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        assert list(backfill_eligible_evidence_queryset()) == [evidence]


class TestRunCollectorLineArtistBackfill:
    LEXICON = build_artist_lexicon(["Lindsey Look", "Alessandra Pisano", "Ron Spears"])

    def test_dry_run_counts_without_writing(self, db):
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        result = run_collector_line_artist_backfill(run_id="test-run", dry_run=True, lexicon=self.LEXICON)

        assert result.considered == 1
        assert result.would_fill == 1
        assert result.filled == 0
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == ""

    def test_write_fills_the_blank_name(self, db):
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        result = run_collector_line_artist_backfill(run_id="test-run", dry_run=False, lexicon=self.LEXICON)

        assert result.filled == 1
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Lindsey Look"

    def test_reads_the_legal_line_too(self, db):
        """The full-width twin of the collector crop (PR #569): the same y band at full width, so
        it carries the credit untruncated. A row whose collector text is useless but whose legal
        text is clean must still recover."""
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, collector_line_raw_text="159/281R\nMOM", legal_line_raw_text=FULL_LEGAL_LINE)

        run_collector_line_artist_backfill(run_id="test-run", dry_run=False, lexicon=self.LEXICON)

        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Lindsey Look"

    def test_never_overwrites_a_non_blank_name(self, db):
        """PR #563's rule: the `Illus.` anchor's own reading always wins and is never
        overwritten. The row below would recover `Lindsey Look` if it were ever considered."""
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_name="Someone Else")

        result = run_collector_line_artist_backfill(run_id="test-run", dry_run=False, lexicon=self.LEXICON)

        assert result.considered == 0  # excluded by the eligibility queryset entirely
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Someone Else"

    def test_no_reading_leaves_the_name_blank(self, db):
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, collector_line_raw_text="159/281R\nMOM ¢ EN")

        result = run_collector_line_artist_backfill(run_id="test-run", dry_run=False, lexicon=self.LEXICON)

        assert result.no_reading == 1
        assert result.filled == 0
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == ""

    def test_an_ambiguous_reading_stores_nothing_and_is_counted_separately(self, db):
        """Owner ruling, 2026-07-29: fuzzy MATCHING is permitted, fuzzy STORAGE is not. `LINDSEY
        L` is compatible with both names below, so there is no single verbatim
        `CanonicalArtist.name` to write down and the row stays blank - counted as `ambiguous`,
        NOT as `no_reading`, because the two mean different things (an illegible row vs. a
        legible one the lexicon cannot disambiguate)."""
        ambiguous_lexicon = build_artist_lexicon(["Lindsey Look", "Lindsey Lopez"])
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        result = run_collector_line_artist_backfill(run_id="test-run", dry_run=False, lexicon=ambiguous_lexicon)

        assert result.ambiguous == 1
        assert result.no_reading == 0
        assert result.would_fill == 0
        assert result.filled == 0
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == ""

    def test_card_name_narrowing_resolves_an_otherwise_ambiguous_reading(self, db):
        """The same ambiguous reading as the test above, but now the card's own name is known to
        have been illustrated by exactly one of the two candidates - so the reading resolves and
        the row fills. This is the `name_artist_lookup` seam, and it is what makes the backfill's
        yield match what a live Stage C extraction of the same card would produce."""
        ambiguous_lexicon = build_artist_lexicon(["Lindsey Look", "Lindsey Lopez"])
        card = CardFactory(content_phash=1, name="Sheoldred")
        evidence = _evidence(card)

        result = run_collector_line_artist_backfill(
            run_id="test-run",
            dry_run=False,
            lexicon=ambiguous_lexicon,
            name_artist_lookup=lambda card_name: ("Lindsey Look",) if card_name == "Sheoldred" else (),
        )

        assert result.filled == 1
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Lindsey Look"

    def test_audit_sample_capped_and_populated(self, db):
        for i in range(5):
            _evidence(CardFactory(content_phash=i + 1))

        result = run_collector_line_artist_backfill(
            run_id="test-run", dry_run=True, audit_sample_size=3, lexicon=self.LEXICON
        )

        assert result.would_fill == 5
        assert len(result.audit) == 3
        assert result.audit[0]["matched_name"] == "Lindsey Look"

    def test_limit_caps_how_many_rows_are_considered(self, db):
        """The read-only measurement handle - a `--dry-run --limit N` pass reports a real yield
        on a real sample without walking the whole 207k-row population."""
        for i in range(5):
            _evidence(CardFactory(content_phash=i + 1))

        result = run_collector_line_artist_backfill(run_id="test-run", dry_run=True, limit=2, lexicon=self.LEXICON)

        assert result.considered == 2
        assert result.would_fill == 2

    def test_writes_are_batched_across_more_rows_than_one_chunk(self, db):
        """The 207k-row pass writes via `bulk_update` every `chunk_size` staged rows, plus a
        final flush for the remainder - so a population that is not a multiple of the chunk size
        must still be fully written, and `filled` must count only rows that really committed."""
        for i in range(5):
            _evidence(CardFactory(content_phash=i + 1))

        result = run_collector_line_artist_backfill(
            run_id="test-run", dry_run=False, chunk_size=2, lexicon=self.LEXICON
        )

        assert result.filled == 5
        assert ImageEvidence.objects.filter(artist_ocr_name="Lindsey Look").count() == 5

    def test_does_not_touch_run_id_or_extractor_versions(self, db):
        """A downstream re-parse of stored evidence, not a Stage C extraction pass - stamping
        either field would misrepresent the row's provenance AND (via `extractor_versions`)
        change what `run_image_evidence_cohort`'s resume filter believes about the card."""
        card = CardFactory(content_phash=1)
        evidence = _evidence(
            card, run_id="some-prior-run", extractor_versions={"collector_line_ocr": "collector-line-ocr-v2"}
        )

        run_collector_line_artist_backfill(run_id="test-run", dry_run=False, lexicon=self.LEXICON)

        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Lindsey Look"
        assert evidence.run_id == "some-prior-run"
        assert evidence.extractor_versions == {"collector_line_ocr": "collector-line-ocr-v2"}

    def test_defaults_to_the_live_canonical_artist_table(self, db):
        """No `lexicon` argument: the pass loads every `CanonicalArtist.name` itself, once."""
        CanonicalArtistFactory(name="Lindsey Look")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        run_collector_line_artist_backfill(run_id="test-run", dry_run=False)

        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Lindsey Look"


class TestBackfillCollectorLineArtistCommand:
    def test_dry_run_is_the_default_and_writes_nothing(self, db):
        CanonicalArtistFactory(name="Lindsey Look")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        out = StringIO()
        call_command("backfill_collector_line_artist", stdout=out)

        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == ""
        assert "DRY RUN" in out.getvalue()

        ledger = PilotRunLedger.objects.get(command="backfill_collector_line_artist")
        assert ledger.dry_run is True
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["would_fill"] == 1
        assert ledger.counters["filled"] == 0

    def test_write_flag_persists_and_records_ledger(self, db):
        CanonicalArtistFactory(name="Lindsey Look")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        out = StringIO()
        call_command("backfill_collector_line_artist", "--write", stdout=out)

        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Lindsey Look"
        assert "WRITE" in out.getvalue()

        ledger = PilotRunLedger.objects.get(command="backfill_collector_line_artist")
        assert ledger.dry_run is False
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.votes_written == 1
        assert ledger.counters["filled"] == 1

    def test_write_is_idempotent_on_a_second_run(self, db):
        CanonicalArtistFactory(name="Lindsey Look")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card)

        call_command("backfill_collector_line_artist", "--write", stdout=StringIO())
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Lindsey Look"

        # second run: the row is no longer eligible (its name is no longer blank) - a no-op, not
        # a crash and not a duplicate write.
        out = StringIO()
        call_command("backfill_collector_line_artist", "--write", stdout=out)
        assert "filled=0" in out.getvalue()

    def test_a_failure_mid_pass_marks_the_ledger_failed_with_a_reason(self, db, monkeypatch):
        """ "Did this ever run, and what happened?" has to be answerable from the database. A
        pass that dies must leave a FAILED row carrying the reason, never a RUNNING row that
        lies about it forever."""
        import cardpicker.management.commands.backfill_collector_line_artist as command_module

        def _boom(**kwargs):
            raise RuntimeError("boom - simulated mid-pass failure")

        monkeypatch.setattr(command_module, "run_collector_line_artist_backfill", _boom)

        with pytest.raises(RuntimeError):
            call_command("backfill_collector_line_artist", "--write", stdout=StringIO())

        ledger = PilotRunLedger.objects.get(command="backfill_collector_line_artist")
        assert ledger.status == PilotRunLedger.Status.FAILED
        assert ledger.finished_at is not None
        assert "boom - simulated mid-pass failure" in ledger.counters["failure_reason"]

    def test_every_invocation_leaves_a_ledger_row_even_with_nothing_to_do(self, db):
        """The 13-day-undetected-calculator lesson: an empty pass is still a pass, and must be
        recorded, or "it never ran" and "it ran and found nothing" are indistinguishable."""
        out = StringIO()
        call_command("backfill_collector_line_artist", stdout=out)

        ledger = PilotRunLedger.objects.get(command="backfill_collector_line_artist")
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["considered"] == 0
