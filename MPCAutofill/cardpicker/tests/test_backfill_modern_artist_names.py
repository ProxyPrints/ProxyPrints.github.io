"""
Tests for cardpicker.modern_artist_credit's DB-touching layer (`load_lexicon_index`,
`eligible_evidence_queryset`, `run_modern_artist_credit_backfill`) and the
`backfill_modern_artist_names` management command wired on top of it - issue #368. Real ORM,
pytest-django's ephemeral test DB (never production - see `docs/troubleshooting.md`'s "Running
backend pytest on the production box" entry). No network calls, no image fetch, no OCR: every
input is an already-persisted `ImageEvidence.artist_ocr_raw_text` string.
"""

from io import StringIO

import pytest

from django.core.management import call_command

from cardpicker.models import PilotRunLedger
from cardpicker.modern_artist_credit import (
    build_lexicon_index,
    eligible_evidence_queryset,
    load_lexicon_index,
    run_modern_artist_credit_backfill,
)
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
        artist_ocr_raw_text="",
        artist_ocr_name="",
    )
    defaults.update(overrides)
    return ImageEvidenceFactory(card=card, **defaults)


class TestLoadLexiconIndex:
    def test_reflects_current_canonical_artist_table(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        CanonicalArtistFactory(name="Mark Tedin")

        lexicon = load_lexicon_index()

        assert set(lexicon.entries) == {"Mike Bierek", "Mark Tedin"}


class TestEligibleEvidenceQueryset:
    def test_blank_raw_text_excluded(self, db):
        card = CardFactory(content_phash=1)
        _evidence(card, artist_ocr_raw_text="")

        assert list(eligible_evidence_queryset()) == []

    def test_already_named_excluded(self, db):
        card = CardFactory(content_phash=1)
        _evidence(card, artist_ocr_raw_text="MIKE BIEREK", artist_ocr_name="Mike Bierek")

        assert list(eligible_evidence_queryset()) == []

    def test_stale_content_hash_excluded(self, db):
        card = CardFactory(content_phash=99)
        _evidence(card, content_hash=42, artist_ocr_raw_text="MIKE BIEREK")

        assert list(eligible_evidence_queryset()) == []

    def test_current_blank_named_row_included(self, db):
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_raw_text="MIKE BIEREK")

        assert list(eligible_evidence_queryset()) == [evidence]


class TestRunModernArtistCreditBackfill:
    def test_dry_run_counts_without_writing(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n")

        result = run_modern_artist_credit_backfill(run_id="test-run", dry_run=True)

        assert result.considered == 1
        assert result.would_fill == 1
        assert result.filled == 0
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == ""

    def test_write_fills_the_blank_name(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n")

        result = run_modern_artist_credit_backfill(run_id="test-run", dry_run=False)

        assert result.filled == 1
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Mike Bierek"

    def test_never_overwrites_a_non_blank_name(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        # already has a (deliberately different) name - must never be touched, even though the
        # raw text would otherwise recognize a different artist.
        evidence = _evidence(
            card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n", artist_ocr_name="Someone Else"
        )

        result = run_modern_artist_credit_backfill(run_id="test-run", dry_run=False)

        assert result.considered == 0  # excluded by eligible_evidence_queryset entirely
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Someone Else"

    def test_no_confident_match_leaves_name_blank(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_raw_text="totally illegible noise xk9 qz\n")

        result = run_modern_artist_credit_backfill(run_id="test-run", dry_run=False)

        assert result.no_match == 1
        assert result.filled == 0
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == ""

    def test_audit_sample_capped_and_populated(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        for i in range(5):
            card = CardFactory(content_phash=i + 1)
            _evidence(card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n")

        result = run_modern_artist_credit_backfill(run_id="test-run", dry_run=True, audit_sample_size=3)

        assert result.would_fill == 5
        assert len(result.audit) == 3
        assert result.audit[0]["matched_name"] == "Mike Bierek"

    def test_does_not_touch_run_id_or_extractor_versions(self, db):
        """This is a downstream re-parse, not a Stage C extraction pass - it must not
        misrepresent itself as one (module docstring)."""
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        evidence = _evidence(
            card,
            artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n",
            run_id="some-prior-run",
            extractor_versions={"artist_ocr": "artist-ocr-v1"},
        )

        run_modern_artist_credit_backfill(run_id="test-run", dry_run=False)

        evidence.refresh_from_db()
        assert evidence.run_id == "some-prior-run"
        assert evidence.extractor_versions == {"artist_ocr": "artist-ocr-v1"}

    def test_reusable_prebuilt_lexicon_avoids_a_second_query(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        _evidence(card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n")
        prebuilt = build_lexicon_index(["Mike Bierek"])

        result = run_modern_artist_credit_backfill(run_id="test-run", dry_run=True, lexicon=prebuilt)

        assert result.would_fill == 1


class TestBackfillModernArtistNamesCommand:
    def test_dry_run_is_the_default_and_writes_nothing(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n")

        out = StringIO()
        call_command("backfill_modern_artist_names", stdout=out)

        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == ""
        assert "DRY RUN" in out.getvalue()

        ledger = PilotRunLedger.objects.get(command="backfill_modern_artist_names")
        assert ledger.dry_run is True
        assert ledger.status == PilotRunLedger.Status.COMPLETED
        assert ledger.counters["would_fill"] == 1

    def test_write_flag_persists_and_records_ledger(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n")

        out = StringIO()
        call_command("backfill_modern_artist_names", "--write", stdout=out)

        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Mike Bierek"
        assert "WRITE" in out.getvalue()

        ledger = PilotRunLedger.objects.get(command="backfill_modern_artist_names")
        assert ledger.dry_run is False
        assert ledger.votes_written == 1
        assert ledger.counters["filled"] == 1

    def test_write_is_idempotent_on_a_second_run(self, db):
        CanonicalArtistFactory(name="Mike Bierek")
        card = CardFactory(content_phash=1)
        evidence = _evidence(card, artist_ocr_raw_text="270/302 U\n2ED * EN © MIKE BIEREK\n")

        call_command("backfill_modern_artist_names", "--write", stdout=StringIO())
        evidence.refresh_from_db()
        assert evidence.artist_ocr_name == "Mike Bierek"

        # second run: the row is no longer eligible (name is no longer blank) - a no-op, not a
        # crash or a duplicate write.
        out = StringIO()
        call_command("backfill_modern_artist_names", "--write", stdout=out)
        assert "filled=0" in out.getvalue()
