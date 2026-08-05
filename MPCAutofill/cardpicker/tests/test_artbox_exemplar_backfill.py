"""
Tests for cardpicker.artbox_exemplar_backfill (issue #508 phase 1) and the model/management
commands it backs: ArtboxPhashExemplar's own constraints, the two seed passes (human-backed
resolution, join-key machine), the confidence floor, staleness exclusion, idempotent resume,
retraction, and the coverage measurement's Hamming-distance matching.
"""

import uuid
from typing import Any

import pytest

from django.core.management import call_command
from django.db import IntegrityError, transaction

from cardpicker.artbox_exemplar_backfill import (
    JOIN_KEY_ANONYMOUS_ID,
    JOIN_KEY_SEED_CONFIDENCE_FLOOR,
    dry_run_candidate_exemplar_hashes,
    human_resolution_seed_group_key,
    join_key_seed_group_key,
    measure_unresolved_coverage,
    run_artbox_exemplar_backfill,
)
from cardpicker.models import (
    ArtboxPhashExemplar,
    ArtboxPhashExemplarSeedKind,
    PrintingTagStatus,
)
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
    ImageEvidenceFactory,
)


def _resolved_card_with_evidence(illustration_id: Any = None, artbox_phash: int = 111, content_phash: int = 111):
    """A card whose printing_tag_status is RESOLVED, resolved to a printing carrying
    `illustration_id` (a fresh uuid4 if not given), with a CURRENT ImageEvidence row carrying
    `artbox_phash`."""
    printing = CanonicalCardFactory()
    CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id or uuid.uuid4())
    card = CardFactory(
        content_phash=content_phash,
        printing_tag_status=PrintingTagStatus.RESOLVED,
        inferred_canonical_card=printing,
    )
    ImageEvidenceFactory(card=card, content_hash=content_phash, artbox_phash=artbox_phash)
    return card, printing


def _join_key_vote_with_evidence(
    confidence: float, artbox_phash: int = 222, content_phash: int = 222, is_no_match: bool = False
):
    printing = CanonicalCardFactory()
    CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
    card = CardFactory(content_phash=content_phash)
    ImageEvidenceFactory(card=card, content_hash=content_phash, artbox_phash=artbox_phash)
    vote = CardPrintingTagFactory(
        card=card,
        printing=None if is_no_match else printing,
        is_no_match=is_no_match,
        anonymous_id=JOIN_KEY_ANONYMOUS_ID,
        confidence=confidence,
    )
    return card, printing, vote


class TestModelConstraints:
    def test_one_exemplar_per_card_enforced(self, db: Any) -> None:
        card, printing = _resolved_card_with_evidence()
        ArtboxPhashExemplar.objects.create(
            illustration_id=printing.printing_metadata.illustration_id,
            artbox_phash=111,
            card=card,
            printing=printing,
            seed_kind=ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION,
            is_human_backed=True,
            seed_group_key=human_resolution_seed_group_key(card),
            content_hash=111,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ArtboxPhashExemplar.objects.create(
                    illustration_id=uuid.uuid4(),
                    artbox_phash=222,
                    card=card,
                    printing=printing,
                    seed_kind=ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION,
                    is_human_backed=True,
                    seed_group_key=human_resolution_seed_group_key(card),
                    content_hash=111,
                )

    def test_seed_kind_must_match_is_human_backed(self, db: Any) -> None:
        card, printing = _resolved_card_with_evidence()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ArtboxPhashExemplar.objects.create(
                    illustration_id=printing.printing_metadata.illustration_id,
                    artbox_phash=111,
                    card=card,
                    printing=printing,
                    seed_kind=ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION,
                    is_human_backed=False,  # mismatched - must be True for HUMAN_RESOLUTION
                    seed_group_key=human_resolution_seed_group_key(card),
                    content_hash=111,
                )


class TestSeedGroupKey:
    def test_human_resolution_key_shares_across_md5_group(self, db: Any) -> None:
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        card_a = CardFactory(md5_checksum="same-md5", content_phash=1, printing_tag_status=PrintingTagStatus.RESOLVED)
        card_b = CardFactory(md5_checksum="same-md5", content_phash=2, printing_tag_status=PrintingTagStatus.RESOLVED)

        assert human_resolution_seed_group_key(card_a) == human_resolution_seed_group_key(card_b)

    def test_human_resolution_key_differs_for_checksum_less_cards(self, db: Any) -> None:
        card_a = CardFactory(md5_checksum=None)
        card_b = CardFactory(md5_checksum=None)

        assert human_resolution_seed_group_key(card_a) != human_resolution_seed_group_key(card_b)

    def test_join_key_group_key_is_per_vote(self, db: Any) -> None:
        assert join_key_seed_group_key(1) != join_key_seed_group_key(2)
        assert join_key_seed_group_key(1) == join_key_seed_group_key(1)


class TestHumanResolutionSeeding:
    def test_resolved_card_with_current_evidence_is_seeded(self, db: Any) -> None:
        illustration_id = uuid.uuid4()
        card, printing = _resolved_card_with_evidence(illustration_id=illustration_id, artbox_phash=333)

        result = run_artbox_exemplar_backfill()

        assert result.human_backed_seeded == 1
        assert result.machine_seeded == 0
        exemplar = ArtboxPhashExemplar.objects.get(card=card)
        assert exemplar.illustration_id == illustration_id
        assert exemplar.artbox_phash == 333
        assert exemplar.seed_kind == ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION
        assert exemplar.is_human_backed is True
        assert exemplar.confidence is None
        assert exemplar.source_vote_id is None

    def test_printing_with_no_illustration_id_is_not_seeded(self, db: Any) -> None:
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=None)
        card = CardFactory(
            content_phash=444, printing_tag_status=PrintingTagStatus.RESOLVED, inferred_canonical_card=printing
        )
        ImageEvidenceFactory(card=card, content_hash=444, artbox_phash=444)

        result = run_artbox_exemplar_backfill()

        assert result.human_backed_seeded == 0
        assert not ArtboxPhashExemplar.objects.filter(card=card).exists()

    def test_unresolved_card_is_not_seeded(self, db: Any) -> None:
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        card = CardFactory(content_phash=555, printing_tag_status=PrintingTagStatus.UNRESOLVED)
        ImageEvidenceFactory(card=card, content_hash=555, artbox_phash=555)

        result = run_artbox_exemplar_backfill()

        assert result.human_backed_seeded == 0
        assert not ArtboxPhashExemplar.objects.filter(card=card).exists()

    def test_stale_evidence_cannot_seed(self, db: Any) -> None:
        """content_hash on the ImageEvidence row disagrees with the card's LIVE content_phash -
        the row is stale (an old image's evidence) and must never seed an exemplar."""
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        card = CardFactory(
            content_phash=999, printing_tag_status=PrintingTagStatus.RESOLVED, inferred_canonical_card=printing
        )
        ImageEvidenceFactory(card=card, content_hash=111, artbox_phash=111)  # stale: != card.content_phash

        result = run_artbox_exemplar_backfill()

        assert result.human_backed_seeded == 0
        assert not ArtboxPhashExemplar.objects.filter(card=card).exists()

    def test_no_artbox_phash_is_not_seeded(self, db: Any) -> None:
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        card = CardFactory(
            content_phash=222, printing_tag_status=PrintingTagStatus.RESOLVED, inferred_canonical_card=printing
        )
        ImageEvidenceFactory(card=card, content_hash=222, artbox_phash=None)

        result = run_artbox_exemplar_backfill()

        assert result.human_backed_seeded == 0

    def test_second_invocation_only_seeds_what_the_first_missed(self, db: Any) -> None:
        _resolved_card_with_evidence(artbox_phash=1)
        card_b, _ = _resolved_card_with_evidence(artbox_phash=2, content_phash=2)

        first = run_artbox_exemplar_backfill()
        assert first.human_backed_seeded == 2

        second = run_artbox_exemplar_backfill()
        assert second.human_backed_seeded == 0
        assert ArtboxPhashExemplar.objects.count() == 2

    def test_dry_run_writes_nothing(self, db: Any) -> None:
        _resolved_card_with_evidence()

        result = run_artbox_exemplar_backfill(dry_run=True)

        assert result.human_backed_seeded == 1
        assert ArtboxPhashExemplar.objects.count() == 0


class TestJoinKeyMachineSeeding:
    def test_vote_at_both_confidence_is_seeded(self, db: Any) -> None:
        card, printing, vote = _join_key_vote_with_evidence(confidence=0.85, artbox_phash=1)

        result = run_artbox_exemplar_backfill()

        assert result.machine_seeded == 1
        exemplar = ArtboxPhashExemplar.objects.get(card=card)
        assert exemplar.seed_kind == ArtboxPhashExemplarSeedKind.JOIN_KEY_MACHINE
        assert exemplar.is_human_backed is False
        assert exemplar.confidence == 0.85
        assert exemplar.source_vote_id == vote.pk

    def test_vote_at_collector_only_confidence_is_seeded(self, db: Any) -> None:
        _join_key_vote_with_evidence(confidence=JOIN_KEY_SEED_CONFIDENCE_FLOOR, artbox_phash=2)

        result = run_artbox_exemplar_backfill()

        assert result.machine_seeded == 1

    def test_vote_below_floor_is_not_seeded(self, db: Any) -> None:
        card, _, _ = _join_key_vote_with_evidence(confidence=0.65, artbox_phash=3)

        result = run_artbox_exemplar_backfill()

        assert result.machine_seeded == 0
        assert not ArtboxPhashExemplar.objects.filter(card=card).exists()

    def test_no_match_vote_never_seeds_regardless_of_confidence(self, db: Any) -> None:
        card, _, _ = _join_key_vote_with_evidence(confidence=0.6, artbox_phash=4, is_no_match=True)

        result = run_artbox_exemplar_backfill()

        assert result.machine_seeded == 0
        assert not ArtboxPhashExemplar.objects.filter(card=card).exists()

    def test_stale_evidence_is_skipped_and_counted(self, db: Any) -> None:
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        card = CardFactory(content_phash=777)
        ImageEvidenceFactory(card=card, content_hash=111, artbox_phash=111)  # stale
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=JOIN_KEY_ANONYMOUS_ID, confidence=0.85)

        result = run_artbox_exemplar_backfill()

        assert result.machine_seeded == 0
        assert result.machine_skipped_stale_or_missing_evidence == 1

    def test_card_already_human_resolved_is_not_double_seeded_by_machine_pass(self, db: Any) -> None:
        illustration_id = uuid.uuid4()
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
        card = CardFactory(
            content_phash=555, printing_tag_status=PrintingTagStatus.RESOLVED, inferred_canonical_card=printing
        )
        ImageEvidenceFactory(card=card, content_hash=555, artbox_phash=555)
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=JOIN_KEY_ANONYMOUS_ID, confidence=0.85)

        result = run_artbox_exemplar_backfill()

        assert result.human_backed_seeded == 1
        assert result.machine_seeded == 0
        exemplar = ArtboxPhashExemplar.objects.get(card=card)
        assert exemplar.seed_kind == ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION

    def test_dry_run_does_not_double_count_human_and_machine_for_same_card(self, db: Any) -> None:
        illustration_id = uuid.uuid4()
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
        card = CardFactory(
            content_phash=666, printing_tag_status=PrintingTagStatus.RESOLVED, inferred_canonical_card=printing
        )
        ImageEvidenceFactory(card=card, content_hash=666, artbox_phash=666)
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=JOIN_KEY_ANONYMOUS_ID, confidence=0.85)

        result = run_artbox_exemplar_backfill(dry_run=True)

        assert result.human_backed_seeded == 1
        assert result.machine_seeded == 0

    def test_second_invocation_only_seeds_what_the_first_missed(self, db: Any) -> None:
        _join_key_vote_with_evidence(confidence=0.85, artbox_phash=1)
        card_b, printing_b, vote_b = _join_key_vote_with_evidence(confidence=0.85, artbox_phash=2, content_phash=2)

        first = run_artbox_exemplar_backfill()
        assert first.machine_seeded == 2

        second = run_artbox_exemplar_backfill()
        assert second.machine_seeded == 0


class TestDistinguishability:
    def test_human_and_machine_exemplars_are_queryable_separately(self, db: Any) -> None:
        _resolved_card_with_evidence(artbox_phash=1)
        _join_key_vote_with_evidence(confidence=0.85, artbox_phash=2)

        run_artbox_exemplar_backfill()

        assert ArtboxPhashExemplar.objects.filter(is_human_backed=True).count() == 1
        assert ArtboxPhashExemplar.objects.filter(is_human_backed=False).count() == 1
        assert ArtboxPhashExemplar.objects.filter(seed_kind=ArtboxPhashExemplarSeedKind.HUMAN_RESOLUTION).count() == 1
        assert ArtboxPhashExemplar.objects.filter(seed_kind=ArtboxPhashExemplarSeedKind.JOIN_KEY_MACHINE).count() == 1


class TestRunIdStamping:
    def test_run_id_is_stamped_on_created_rows(self, db: Any) -> None:
        _resolved_card_with_evidence()
        _join_key_vote_with_evidence(confidence=0.85, artbox_phash=2)

        run_artbox_exemplar_backfill(run_id="run-abc")

        assert ArtboxPhashExemplar.objects.filter(run_id="run-abc").count() == 2


class TestRetraction:
    def test_retract_by_seed_group_key_removes_every_group_member(self, db: Any) -> None:
        illustration_id = uuid.uuid4()
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=illustration_id)
        card_a = CardFactory(
            md5_checksum="grp-1",
            content_phash=1,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=printing,
        )
        card_b = CardFactory(
            md5_checksum="grp-1",
            content_phash=2,
            printing_tag_status=PrintingTagStatus.RESOLVED,
            inferred_canonical_card=printing,
        )
        ImageEvidenceFactory(card=card_a, content_hash=1, artbox_phash=1)
        ImageEvidenceFactory(card=card_b, content_hash=2, artbox_phash=2)

        run_artbox_exemplar_backfill()
        assert ArtboxPhashExemplar.objects.count() == 2
        seed_group_key = ArtboxPhashExemplar.objects.get(card=card_a).seed_group_key
        assert seed_group_key == ArtboxPhashExemplar.objects.get(card=card_b).seed_group_key

        call_command("retract_artbox_phash_exemplars", f"--seed-group-key={seed_group_key}", "--write")

        assert ArtboxPhashExemplar.objects.count() == 0

    def test_retract_by_source_vote_id_removes_only_that_exemplar(self, db: Any) -> None:
        card_a, _, vote_a = _join_key_vote_with_evidence(confidence=0.85, artbox_phash=1)
        card_b, _, vote_b = _join_key_vote_with_evidence(confidence=0.85, artbox_phash=2, content_phash=2)

        run_artbox_exemplar_backfill()
        assert ArtboxPhashExemplar.objects.count() == 2

        call_command("retract_artbox_phash_exemplars", f"--source-vote-id={vote_a.pk}", "--write")

        assert ArtboxPhashExemplar.objects.count() == 1
        assert ArtboxPhashExemplar.objects.filter(card=card_b).exists()
        assert not ArtboxPhashExemplar.objects.filter(card=card_a).exists()

    def test_dry_run_deletes_nothing(self, db: Any) -> None:
        card, printing = _resolved_card_with_evidence()
        run_artbox_exemplar_backfill()
        seed_group_key = ArtboxPhashExemplar.objects.get(card=card).seed_group_key

        call_command("retract_artbox_phash_exemplars", f"--seed-group-key={seed_group_key}")

        assert ArtboxPhashExemplar.objects.count() == 1

    def test_requires_exactly_one_selector(self, db: Any) -> None:
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("retract_artbox_phash_exemplars", "--write")

        with pytest.raises(CommandError):
            call_command(
                "retract_artbox_phash_exemplars", "--card-id=1", "--illustration-id=" + str(uuid.uuid4()), "--write"
            )


class TestCoverageMeasurement:
    def test_exact_match_counts_as_both_d0_and_d_le_2(self, db: Any) -> None:
        printing = CanonicalCardFactory()
        CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
        card = CardFactory(content_phash=42, printing_tag_status=PrintingTagStatus.UNRESOLVED)
        ImageEvidenceFactory(card=card, content_hash=42, artbox_phash=42)

        result = measure_unresolved_coverage([42])

        assert result.unresolved_candidates_considered == 1
        assert result.matches_at_d0 == 1
        assert result.matches_at_d_le_2 == 1

    def test_distance_one_and_two_count_only_toward_d_le_2(self, db: Any) -> None:
        base = 0
        distance_one = base ^ (1 << 3)
        distance_two = base ^ (1 << 3) ^ (1 << 7)
        distance_three = base ^ (1 << 3) ^ (1 << 7) ^ (1 << 11)

        for offset, value in enumerate([distance_one, distance_two, distance_three]):
            printing = CanonicalCardFactory()
            CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
            card = CardFactory(content_phash=100 + offset, printing_tag_status=PrintingTagStatus.UNRESOLVED)
            ImageEvidenceFactory(card=card, content_hash=100 + offset, artbox_phash=value)

        result = measure_unresolved_coverage([base])

        assert result.unresolved_candidates_considered == 3
        assert result.matches_at_d0 == 0
        assert result.matches_at_d_le_2 == 2  # distance_one and distance_two, not distance_three

    def test_resolved_and_no_match_cards_are_excluded_from_candidates(self, db: Any) -> None:
        for status, offset in [(PrintingTagStatus.RESOLVED, 0), (PrintingTagStatus.NO_MATCH, 1)]:
            printing = CanonicalCardFactory()
            CanonicalPrintingMetadataFactory(canonical_card=printing, illustration_id=uuid.uuid4())
            card = CardFactory(content_phash=200 + offset, printing_tag_status=status)
            ImageEvidenceFactory(card=card, content_hash=200 + offset, artbox_phash=200 + offset)

        result = measure_unresolved_coverage([200, 201])

        assert result.unresolved_candidates_considered == 0
        assert result.matches_at_d0 == 0

    def test_dry_run_candidate_exemplar_hashes_matches_what_a_real_run_would_seed(self, db: Any) -> None:
        _resolved_card_with_evidence(artbox_phash=1)
        _join_key_vote_with_evidence(confidence=0.85, artbox_phash=2)

        dry_run_hashes = sorted(dry_run_candidate_exemplar_hashes())

        assert dry_run_hashes == [1, 2]


class TestBackfillCommandCLI:
    def test_real_cli_invocation_with_no_flags(self, db: Any) -> None:
        _resolved_card_with_evidence()

        call_command("backfill_artbox_phash_exemplars", "--skip-checks", "--skip-coverage")

        assert ArtboxPhashExemplar.objects.count() == 1

    def test_dry_run_flag_reports_without_writing(self, db: Any, capsys: Any) -> None:
        _resolved_card_with_evidence()

        call_command("backfill_artbox_phash_exemplars", "--skip-checks", "--dry-run", "--skip-coverage")
        captured = capsys.readouterr()

        assert "Dry run - nothing written." in captured.out
        assert ArtboxPhashExemplar.objects.count() == 0

    def test_coverage_measurement_runs_by_default(self, db: Any, capsys: Any) -> None:
        _resolved_card_with_evidence()

        call_command("backfill_artbox_phash_exemplars", "--skip-checks")
        captured = capsys.readouterr()

        assert "COVERAGE (phase-2 estimate)" in captured.out
