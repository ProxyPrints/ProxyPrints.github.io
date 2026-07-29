import pytest

import cardpicker.deductive_backfill as module
from cardpicker.deductive_backfill import (
    DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
    DeductiveVote,
    generate_run_id,
    run_backfill,
    select_d1_candidates,
    select_d2_candidates,
    verify_zero_resolutions,
)
from cardpicker.models import CardPrintingTag, PrintingTagStatus, VoteSource
from cardpicker.printing_consensus import resolve_printing
from cardpicker.tests.factories import (
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
)
from cardpicker.vote_consensus import (
    _SOURCE_WEIGHTS,
    DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID,
    resolve_vote_weight,
)


def _unique_printing(name: str, catalogued_printings_count: int = 1, **kwargs) -> "CanonicalCardFactory":
    printing = CanonicalCardFactory(name=name, **kwargs)
    CanonicalPrintingMetadataFactory(canonical_card=printing, catalogued_printings_count=catalogued_printings_count)
    return printing


class TestD1Selection:
    def test_unique_name_match_is_d1(self, db):
        printing = _unique_printing("Plumecreed Mentor")
        card = CardFactory(name="Plumecreed Mentor")
        votes = list(select_d1_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == printing.pk
        assert votes[0].tier == "d1"

    def test_parenthetical_suffix_is_stripped_by_normalization(self, db):
        # mirrors real corpus data: many cards carry an "(Style Artist Name)" suffix that
        # to_searchable strips (bracketed content removal) but CanonicalCard.name never has.
        printing = _unique_printing("Kusari-Gama")
        card = CardFactory(name="Kusari-Gama (Modern Tomas Giorello)")
        votes = list(select_d1_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == printing.pk

    def test_mid_string_the_is_preserved_post_460(self, db):
        # if to_searchable still stripped mid-string "the" (the pre-#460 bug), both of these
        # would normalize to the same string and the match would be ambiguous (2 matches, not
        # D1) instead of each resolving independently.
        printing_with_the = _unique_printing("Adanto, the First Fort")
        _unique_printing("Adanto First Fort")  # deliberately similar but distinct name
        card = CardFactory(name="Adanto, the First Fort")
        votes = list(select_d1_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == printing_with_the.pk

    def test_ambiguous_name_is_not_d1(self, db):
        _unique_printing("Forest", expansion=CanonicalExpansionFactory(code="ust"))
        _unique_printing("Forest", expansion=CanonicalExpansionFactory(code="csp"))
        CardFactory(name="Forest")
        assert list(select_d1_candidates()) == []

    def test_catalogued_printings_count_greater_than_one_excludes_from_d1(self, db):
        # THIS TEST ASSERTS OVER A STATE THE IMPORTER CANNOT PRODUCE (labelled 2026-07-29).
        # It builds, via the factory, one CanonicalCard row whose catalogued_printings_count is
        # 2 - and `import_scryfall_printing_metadata` computes that column as the number of
        # CanonicalCard rows sharing an oracle id, so one row can only ever score 1. The test
        # passes, and proves nothing about production: measured on the live catalogue
        # 2026-07-29, all 14,893 uniquely-named rows carry a count of exactly 1, and the
        # condition under test excluded 0 of 137 D1 candidates.
        #
        # It used to be commented as proving a "Scryfall cross-check" catches printings we
        # haven't imported. It does not - see `select_d1_candidates`' docstring and issue #600.
        # Kept, deliberately: it pins the branch's behaviour so that whatever real check
        # replaces the condition has a failing-first test to grow from.
        _unique_printing("Gilded Drake", catalogued_printings_count=2)
        CardFactory(name="Gilded Drake")
        assert list(select_d1_candidates()) == []

    def test_missing_printing_metadata_is_treated_as_unverifiable(self, db):
        # a CanonicalCard with no CanonicalPrintingMetadata sidecar at all (predates that
        # import) must never be silently treated as catalogued_printings_count == 1.
        # Also unreachable in production as of 2026-07-29: all 113,224 CanonicalCard rows
        # carry a metadata sidecar. Kept as a guard on the -1 sentinel, not as evidence.
        CanonicalCardFactory(name="No Metadata Card")
        CardFactory(name="No Metadata Card")
        assert list(select_d1_candidates()) == []

    def test_resolved_card_is_excluded(self, db):
        _unique_printing("Already Resolved")
        card = CardFactory(name="Already Resolved")
        card.printing_tag_status = PrintingTagStatus.RESOLVED
        card.inferred_canonical_card = CanonicalCardFactory()
        card.save()
        assert list(select_d1_candidates()) == []

    def test_card_with_confirmed_canonical_card_is_excluded(self, db):
        printing = _unique_printing("Already Tagged")
        CardFactory(name="Already Tagged", canonical_card=printing)
        assert list(select_d1_candidates()) == []

    def test_card_with_any_existing_vote_is_excluded(self, db):
        # not just an existing deductive-backfill vote - ANY existing vote, since that's
        # exactly the scenario where an added machine vote could tip an already-human-backed
        # group over the resolution threshold (see deductive_backfill.py's docstring).
        _unique_printing("Has A Vote Already")
        card = CardFactory(name="Has A Vote Already")
        CardPrintingTagFactory(card=card, printing=CanonicalCardFactory(), source=VoteSource.USER)
        assert list(select_d1_candidates()) == []

    def test_card_with_existing_deductive_vote_is_excluded(self, db):
        _unique_printing("Already Backfilled")
        card = CardFactory(name="Already Backfilled")
        CardPrintingTagFactory(
            card=card,
            printing=CanonicalCardFactory(),
            source=VoteSource.DEDUCTION,
            anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
        )
        assert list(select_d1_candidates()) == []

    def test_card_with_resolved_custom_tag_is_excluded(self, db):
        # the catalog deliberately allows custom/fan art - once tag-vote consensus has
        # already confirmed "Custom", a name-based printing deduction is meaningless.
        _unique_printing("Custom Art Card")
        CardFactory(name="Custom Art Card", tags=["Custom"])
        assert list(select_d1_candidates()) == []

    def test_non_english_card_is_excluded(self, db):
        # name-matching compares against CanonicalCard.name (Scryfall's English oracle name);
        # a foreign-language card's name isn't a trustworthy signal for it.
        _unique_printing("Foreign Language Card")
        CardFactory(name="Foreign Language Card", language="FR")
        assert list(select_d1_candidates()) == []


class TestD2Selection:
    def test_expansion_hint_narrows_ambiguous_name_to_one(self, db):
        _unique_printing("Snow-Covered Forest", expansion=CanonicalExpansionFactory(code="csp"))
        matching = _unique_printing("Snow-Covered Forest", expansion=CanonicalExpansionFactory(code="wwk"))
        card = CardFactory(name="Snow-Covered Forest", expansion_hint="wwk")
        votes = list(select_d2_candidates())
        assert len(votes) == 1
        assert votes[0].card_id == card.pk
        assert votes[0].printing_id == matching.pk
        assert votes[0].tier == "d2"

    def test_no_expansion_hint_is_not_d2(self, db):
        _unique_printing("No Hint Card", expansion=CanonicalExpansionFactory(code="csp"))
        _unique_printing("No Hint Card", expansion=CanonicalExpansionFactory(code="wwk"))
        CardFactory(name="No Hint Card", expansion_hint="")
        assert list(select_d2_candidates()) == []

    def test_hint_that_still_does_not_narrow_to_one_is_excluded(self, db):
        # hint present, but that (name, expansion) pair matches zero printings (stale/wrong
        # hint) - must not guess.
        _unique_printing("Wrong Hint Card", expansion=CanonicalExpansionFactory(code="csp"))
        CardFactory(name="Wrong Hint Card", expansion_hint="wwk")
        assert list(select_d2_candidates()) == []

    def test_unambiguous_name_is_not_d2(self, db):
        # D1's territory - a name matching exactly one printing is never D2, hint or not.
        _unique_printing("Solo Printing", expansion=CanonicalExpansionFactory(code="csp"))
        CardFactory(name="Solo Printing", expansion_hint="csp")
        assert list(select_d2_candidates()) == []


class TestRunBackfillWriteShape:
    def test_d1_vote_row_shape(self, db):
        printing = _unique_printing("Shape Test D1")
        card = CardFactory(name="Shape Test D1")
        result = run_backfill(tier="d1")
        assert result.d1_written == 1
        assert result.d2_written == 0
        assert result.gate_violations == []

        vote = card.printing_tags.get()
        assert vote.printing_id == printing.pk
        assert vote.is_no_match is False
        assert vote.anonymous_id == DEDUCTIVE_BACKFILL_ANONYMOUS_ID
        assert vote.source == VoteSource.DEDUCTION
        assert vote.confidence == 0.95
        # 2026-07-29: every run stamps a run_id, and it is never the frozen 2026-07-14 cohort's
        # (which is what a zero-weight vote would look like) - see generate_run_id's docstring.
        assert vote.run_id is not None
        assert vote.run_id.startswith(f"{DEDUCTIVE_BACKFILL_ANONYMOUS_ID}/")
        assert vote.run_id != DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID

    def test_d2_vote_row_shape(self, db):
        matching = _unique_printing("Shape Test D2", expansion=CanonicalExpansionFactory(code="csp"))
        _unique_printing("Shape Test D2", expansion=CanonicalExpansionFactory(code="wwk"))
        card = CardFactory(name="Shape Test D2", expansion_hint="csp")
        result = run_backfill(tier="d2")
        assert result.d2_written == 1

        vote = card.printing_tags.get()
        assert vote.printing_id == matching.pk
        assert vote.source == VoteSource.DEDUCTION
        assert vote.confidence == 0.90

    def test_dry_run_writes_nothing(self, db):
        _unique_printing("Dry Run Card")
        card = CardFactory(name="Dry Run Card")
        result = run_backfill(tier="d1", dry_run=True)
        assert result.d1_written == 1  # counted, but not persisted
        assert result.gate_violations == []
        assert card.printing_tags.count() == 0

    def test_limit_caps_total_written(self, db):
        # distinct alphabetic suffixes, not digits - to_searchable strips all digits, so
        # "Limit Card 0"/"Limit Card 1" would collide into the same normalized name and
        # make every one of them ambiguous (not D1) rather than exercising the --limit path.
        for suffix in ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]:
            _unique_printing(f"Limit Card {suffix}")
            CardFactory(name=f"Limit Card {suffix}")
        result = run_backfill(tier="d1", limit=2)
        assert result.total_written == 2

    def test_one_run_id_is_shared_by_every_vote_the_invocation_writes(self, db):
        # one run_id generated once per invocation and threaded through the whole run - that is
        # what makes `purge_machine_votes --run-id <id>` able to retract exactly one bad run.
        # Two chunks (batch_size=2 over 5 cards) so this also proves it is not re-generated
        # per flush.
        for suffix in ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]:
            _unique_printing(f"Run Id Card {suffix}")
            CardFactory(name=f"Run Id Card {suffix}")
        run_backfill(tier="d1", batch_size=2)
        run_ids = set(
            CardPrintingTag.objects.filter(anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID).values_list(
                "run_id", flat=True
            )
        )
        assert len(run_ids) == 1

    def test_idempotent_on_rerun(self, db):
        _unique_printing("Idempotence Card")
        card = CardFactory(name="Idempotence Card")

        first = run_backfill(tier="d1")
        assert first.d1_written == 1
        assert card.printing_tags.count() == 1

        second = run_backfill(tier="d1")
        assert second.d1_written == 0
        assert card.printing_tags.count() == 1  # no duplicate vote


class TestFreshRunVotesCarryWeight:
    """
    2026-07-29 owner clarification, at this module's own level. The 2026-07-23 ruling zeroed the
    2026-07-14 COHORT as a measurement control; it did not disqualify name-matching deductive
    inference as a method. So the votes THIS module writes today carry the ordinary machine
    weight, and the frozen cohort is identified by its stamped run_id rather than by this
    module's identity.

    Named plainly because it is a live behavioural consequence, not a refactor: re-running
    `deductive_backfill_printing_tags --tier d1` now casts votes that COUNT in consensus. They
    still cannot resolve anything on their own - the human-backed gate is untouched, and
    `TestZeroResolutionsGate` below verifies that against real data on every run.
    """

    def test_a_vote_this_module_writes_now_resolves_to_ordinary_machine_weight(self, db):
        _unique_printing("Weighted Vote Card")
        card = CardFactory(name="Weighted Vote Card")
        run_backfill(tier="d1")

        vote = card.printing_tags.get()
        assert resolve_vote_weight(vote.source, vote.anonymous_id, vote.run_id) == _SOURCE_WEIGHTS[VoteSource.DEDUCTION]

    def test_generate_run_id_never_mints_the_frozen_cohort_stamp(self):
        # if it could, a future run's votes would silently join a ratified zero-weight control
        # cohort - re-creating by collision the over-broad reading this clarification removed
        assert all(generate_run_id() != DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID for _ in range(50))

    def test_the_frozen_cohort_is_still_zero_weight(self, db):
        # the other half of the pair: a row carrying the 2026-07-14 stamp, as the 28,112
        # production rows do after migration 0095, still weighs nothing
        card = CardFactory()
        vote = CardPrintingTagFactory(
            card=card,
            printing=CanonicalCardFactory(),
            source=VoteSource.DEDUCTION,
            anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
            run_id=DEDUCTIVE_BACKFILL_ZERO_WEIGHT_RUN_ID,
        )
        assert resolve_vote_weight(vote.source, vote.anonymous_id, vote.run_id) == 0.0


class TestZeroResolutionsGate:
    def test_backfill_never_resolves_an_ai_only_card(self, db):
        _unique_printing("Gate Test Card")
        card = CardFactory(name="Gate Test Card")
        result = run_backfill(tier="d1")
        assert result.gate_violations == []
        card.refresh_from_db()
        assert card.printing_tag_status == PrintingTagStatus.UNRESOLVED
        assert resolve_printing(card) is None

    def test_verify_zero_resolutions_detects_a_real_violation(self, db):
        # constructs the scenario _eligible_base_queryset is designed to prevent from ever
        # reaching run_backfill - a card with a pre-existing human vote, plus (bypassing
        # selection entirely) a same-outcome machine vote added directly - to prove the detector
        # itself actually catches a resolved card rather than trivially always passing.
        printing = CanonicalCardFactory()
        card = CardFactory()
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)
        # two USER votes alone already clear consensus here - assert the fixture itself
        # actually resolves before layering the machine vote on top, so the test is meaningful.
        assert resolve_printing(card) == printing

        violations = verify_zero_resolutions([card.pk])
        assert violations == [card.pk]


class TestPurgeWriteAtomicity:
    """Cancel-safety at this module's chunked flush (2026-07-28, generalising PR #526's fix for
    the Stage D calculators). The chunking already means an interrupted run keeps whatever it
    committed, but the purge and the insert WITHIN a chunk were two untransacted statements - a
    kill between them deleted that chunk's cards' previous same-family votes and wrote no
    replacement, which is worse than simply losing the chunk. Both now run inside one
    `transaction.atomic()`.

    `select_candidates` is stubbed rather than driven by a fixture because `_eligible_base_queryset`
    excludes any card that already has ANY `CardPrintingTag` row - so the only way this site's
    purge ever has something to delete is the selection-to-write race window, which is exactly
    what the stub reproduces."""

    def test_a_failed_insert_rolls_the_purge_back(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Race Window Card")
        card = CardFactory(name="Race Window Card")
        stale = CardPrintingTagFactory(
            card=card,
            printing=printing,
            source=VoteSource.DEDUCTION,
            anonymous_id="deductive-backfill-v0",
        )

        monkeypatch.setattr(
            module,
            "select_candidates",
            lambda tier: iter([DeductiveVote(card_id=card.pk, printing_id=printing.pk, tier="d1")]),
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated mid-flight kill between DELETE and INSERT")

        monkeypatch.setattr(CardPrintingTag.objects, "bulk_create", _boom)

        with pytest.raises(RuntimeError):
            run_backfill(tier="d1")

        assert CardPrintingTag.objects.filter(pk=stale.pk).exists()
