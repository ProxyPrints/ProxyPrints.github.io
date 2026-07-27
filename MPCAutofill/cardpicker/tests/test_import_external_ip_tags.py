"""
Tests for cardpicker.management.commands.import_external_ip_tags — the Scryfall Tagger
art:external-ip community tag import (fix-batch plan 2026-07-27, work item W9).

Covers:
  - JSONL parsing: find_external_ip_subtree (BFS from root tag slug),
    collect_illustration_ids (second-pass over subtree only),
    build_illustration_index (illustration_id → card id, including card_faces)
  - run_external_ip_tag_import: dry-run/write, idempotent re-run,
    illustration-to-card join, unmatched illustration/canonical-card skip
  - Gate pattern: verify_no_machine_only_resolutions on the write path

No network calls, no live DB writes — uses hand-built fixture JSONL files in
tests/fixtures/ and the Django test DB.
"""

import uuid
from pathlib import Path

from django.core.management import call_command

from cardpicker.management.commands.import_external_ip_tags import (
    SCRYFALL_TAGGER_ANONYMOUS_ID,
    ExternalIpImportResult,
    build_illustration_index,
    collect_illustration_ids,
    find_external_ip_subtree,
    run_external_ip_tag_import,
)
from cardpicker.models import CanonicalCard, CardTagVote, VotePolarity, VoteSource
from cardpicker.tests.factories import CanonicalCardFactory, CardFactory

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ART_TAGS_FIXTURE = _FIXTURES / "art_tags.jsonl"
_DEFAULT_CARDS_FIXTURE = _FIXTURES / "default_cards.jsonl"

# CanonicalCard identifiers matching the default_cards fixture.
_RING_ID = uuid.UUID("11111111-8888-8888-8888-888888888888")
_GANDALF_ID = uuid.UUID("22222222-9999-9999-9999-999999999999")
_MARINE_ID = uuid.UUID("33333333-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_UNMATCHED_PRINTING_ID = uuid.UUID("44444444-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_DFC_ID = uuid.UUID("55555555-dddd-dddd-dddd-dddddddddddd")


# ---------------------------------------------------------------------------
# Parsing unit tests (only the module-level functions, no DB)
# ---------------------------------------------------------------------------


class TestFindExternalIpSubtree:
    def test_finds_root_by_slug_and_bfs_subtree(self):
        subtree, tags_seen = find_external_ip_subtree(_ART_TAGS_FIXTURE)

        # root + lotr + the-one-ring + warhammer = 4 tags in subtree
        assert len(subtree) == 4
        assert subtree == {
            uuid.UUID("aaaaaaaa-1111-1111-1111-111111111111"),  # external-ip
            uuid.UUID("bbbbbbbb-2222-2222-2222-222222222222"),  # lotr
            uuid.UUID("dddddddd-4444-4444-4444-444444444444"),  # the-one-ring
            uuid.UUID("cccccccc-3333-3333-3333-333333333333"),  # warhammer
        }
        assert tags_seen == 5  # all five rows parsed

    def test_nonexistent_slug_raises_runtime_error(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text('{"id":"00000000-0000-0000-0000-000000000000","slug":"other","child_ids":[],"taggings":[]}\n')
        try:
            find_external_ip_subtree(empty)
        except RuntimeError as e:
            assert "external-ip" in str(e)
        else:
            raise AssertionError("expected RuntimeError")


class TestCollectIllustrationIds:
    def test_collects_only_from_subtree_tags(self):
        subtree = {
            uuid.UUID("aaaaaaaa-1111-1111-1111-111111111111"),  # external-ip (no direct taggings)
            uuid.UUID("bbbbbbbb-2222-2222-2222-222222222222"),  # lotr (no direct taggings)
            uuid.UUID("dddddddd-4444-4444-4444-444444444444"),  # the-one-ring (2 taggings)
            uuid.UUID("cccccccc-3333-3333-3333-333333333333"),  # warhammer (1 tagging)
        }

        result = collect_illustration_ids(_ART_TAGS_FIXTURE, subtree)

        assert len(result) == 3
        assert uuid.UUID("eeeee111-5555-5555-5555-555555555555") in result  # from the-one-ring
        assert uuid.UUID("fffff222-6666-6666-6666-666666666666") in result  # from the-one-ring
        assert uuid.UUID("99999aaa-7777-7777-7777-777777777777") in result  # from warhammer
        # unrelated tag not in subtree → not collected
        assert uuid.UUID("00000000-0000-0000-0000-000000000000") not in result


class TestBuildIllustrationIndex:
    def test_maps_illustration_ids_to_card_ids(self):
        index = build_illustration_index(_DEFAULT_CARDS_FIXTURE)

        # single-faced cards
        assert index[uuid.UUID("eeeee111-5555-5555-5555-555555555555")] == {_RING_ID}
        assert index[uuid.UUID("fffff222-6666-6666-6666-666666666666")] == {_GANDALF_ID}
        assert index[uuid.UUID("99999aaa-7777-7777-7777-777777777777")] == {_MARINE_ID}
        # unmatched illustration
        assert index[uuid.UUID("55555555-cccc-cccc-cccc-cccccccccccc")] == {_UNMATCHED_PRINTING_ID}
        # DFC: one entry per face illustration_id
        assert index[uuid.UUID("66666666-eeee-eeee-eeee-eeeeeeeeeeee")] == {_DFC_ID}
        assert index[uuid.UUID("77777777-ffff-ffff-ffff-ffffffffffff")] == {_DFC_ID}

    def test_empty_file_returns_empty_index(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert build_illustration_index(empty) == {}


# ---------------------------------------------------------------------------
# Integration tests (DB-backed, via the real run_external_ip_tag_import)
# ---------------------------------------------------------------------------


def _make_canonical(identifier: uuid.UUID) -> CanonicalCard:
    return CanonicalCardFactory(identifier=identifier, is_default=True)


class TestRunExternalIpTagImport:
    def test_dry_run_counts_without_writing(self, db):
        _make_canonical(_RING_ID)
        _make_canonical(_GANDALF_ID)
        _make_canonical(_MARINE_ID)
        # Cards linked to those canonical cards
        CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))
        CardFactory(name="Gandalf the Grey", canonical_card=CanonicalCard.objects.get(identifier=_GANDALF_ID))
        CardFactory(name="Space Marine", canonical_card=CanonicalCard.objects.get(identifier=_MARINE_ID))

        result = run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=True,
        )

        assert isinstance(result, ExternalIpImportResult)
        assert result.dry_run is True
        assert result.tags_seen == 5
        assert result.subtree_tag_count == 4
        assert result.illustrations_tagged == 3
        assert result.canonical_cards_matched == 3
        assert result.cards_eligible == 3
        assert result.votes_would_cast == 3
        assert CardTagVote.objects.count() == 0  # nothing persisted

    def test_write_casts_votes_and_persists(self, db):
        _make_canonical(_RING_ID)
        _make_canonical(_GANDALF_ID)
        _make_canonical(_MARINE_ID)
        ring = CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))
        gandalf = CardFactory(name="Gandalf the Grey", canonical_card=CanonicalCard.objects.get(identifier=_GANDALF_ID))
        marine = CardFactory(name="Space Marine", canonical_card=CanonicalCard.objects.get(identifier=_MARINE_ID))

        result = run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=False,
        )

        assert result.votes_written == 3
        assert CardTagVote.objects.count() == 3

        for card, name in [(ring, "The One Ring"), (gandalf, "Gandalf"), (marine, "Space Marine")]:
            vote = CardTagVote.objects.get(card=card)
            assert vote.tag.name == "external-ip"
            assert vote.polarity == VotePolarity.APPLY
            assert vote.anonymous_id == SCRYFALL_TAGGER_ANONYMOUS_ID
            assert vote.source == VoteSource.DEDUCTION
            assert vote.run_id == result.run_id

        # verify_no_machine_only_resolutions — a single machine vote alone can never resolve
        from cardpicker.management.commands.purge_machine_votes import (
            verify_no_machine_only_resolutions,
        )

        card_ids = [ring.pk, gandalf.pk, marine.pk]
        assert verify_no_machine_only_resolutions(card_ids) == []

    def test_idempotent_rerun_skips_already_voted_cards(self, db):
        _make_canonical(_RING_ID)
        _make_canonical(_GANDALF_ID)
        CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))
        CardFactory(name="Gandalf the Grey", canonical_card=CanonicalCard.objects.get(identifier=_GANDALF_ID))

        first = run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=False,
        )
        assert first.votes_written == 2

        second = run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=False,
        )
        # both cards already voted by this identity → eligibility excludes them
        assert second.cards_eligible == 0
        assert second.votes_written == 0
        assert CardTagVote.objects.count() == 2  # unchanged

    def test_skips_printing_without_canonical_card_match(self, db):
        # Only one of the three tagged printings has a CanonicalCard row
        _make_canonical(_RING_ID)
        CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))

        result = run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=True,
        )

        assert result.canonical_cards_matched == 1
        assert result.cards_eligible == 1
        assert result.skip_counts.get("printing-not-canonical") == 2

    def test_card_matching_resolved_inferred_printing_is_eligible(self, db):
        """A card linked via inferred_canonical_card (community-RESOLVED, not
        ingestion-time canonical_card) is also eligible — the same
        effective-printing logic the module docstring describes."""
        from cardpicker.models import PrintingTagStatus

        _make_canonical(_RING_ID)
        card = CardFactory(
            name="The One Ring (resolved)",
            canonical_card=None,
            inferred_canonical_card=CanonicalCard.objects.get(identifier=_RING_ID),
            printing_tag_status=PrintingTagStatus.RESOLVED,
        )

        result = run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=False,
        )

        assert result.votes_written == 1
        assert CardTagVote.objects.filter(card=card).exists()

    def test_unresolved_inferred_printing_is_not_eligible(self, db):
        """A card with an inferred_canonical_card that isn't yet community-RESOLVED
        is withheld — same withhold-never-manufacture rule the module docstring
        states."""
        from cardpicker.models import PrintingTagStatus

        _make_canonical(_RING_ID)
        CardFactory(
            name="The One Ring (unresolved)",
            canonical_card=None,
            inferred_canonical_card=CanonicalCard.objects.get(identifier=_RING_ID),
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
        )

        result = run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=True,
        )

        assert result.cards_eligible == 0

    def test_source_and_anonymous_id(self, db):
        """Each vote is cast as (source=DEDUCTION, anonymous_id=scryfall-tagger-v1)
        so weight resolves to PRINTING_TAG_MACHINE_WEIGHT (0.5) through the
        normal _SOURCE_WEIGHTS path, and the 2026-07-23 zero-weight override
        scoped to deductive-backfill-v1 is never triggered."""
        _make_canonical(_RING_ID)
        CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))

        run_external_ip_tag_import(
            tags_path=_ART_TAGS_FIXTURE,
            default_cards_path=_DEFAULT_CARDS_FIXTURE,
            dry_run=False,
        )

        vote = CardTagVote.objects.get()
        assert vote.source == VoteSource.DEDUCTION
        assert vote.anonymous_id == "scryfall-tagger-v1"


class TestManagementCommand:
    """Exercise the Django management-command entry point (thin wrapper around
    run_external_ip_tag_import) via call_command."""

    def test_dry_run_default_without_write_flag(self, db):
        _make_canonical(_RING_ID)
        CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))

        call_command(
            "import_external_ip_tags",
            file=str(_ART_TAGS_FIXTURE),
            default_cards=str(_DEFAULT_CARDS_FIXTURE),
        )

        assert CardTagVote.objects.count() == 0  # default is dry-run

    def test_write_flag_persists(self, db):
        _make_canonical(_RING_ID)
        CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))

        call_command(
            "import_external_ip_tags",
            file=str(_ART_TAGS_FIXTURE),
            default_cards=str(_DEFAULT_CARDS_FIXTURE),
            write=True,
        )

        assert CardTagVote.objects.count() == 1

    def test_dry_run_explicit(self, db):
        _make_canonical(_RING_ID)
        CardFactory(name="The One Ring", canonical_card=CanonicalCard.objects.get(identifier=_RING_ID))

        call_command(
            "import_external_ip_tags",
            file=str(_ART_TAGS_FIXTURE),
            default_cards=str(_DEFAULT_CARDS_FIXTURE),
            dry_run=True,
        )

        assert CardTagVote.objects.count() == 0

    def test_mutually_exclusive_flags_raises(self, db):
        from django.core.management import CommandError

        try:
            call_command(
                "import_external_ip_tags",
                file=str(_ART_TAGS_FIXTURE),
                default_cards=str(_DEFAULT_CARDS_FIXTURE),
                write=True,
                dry_run=True,
            )
        except CommandError as e:
            assert "only one" in str(e).lower()
        else:
            raise AssertionError("expected CommandError for mutually exclusive flags")
