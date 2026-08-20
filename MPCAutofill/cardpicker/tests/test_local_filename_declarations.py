"""
Tests for `cardpicker.local_filename_declarations` - the filename-declaration caster. Covers the
pure parser (every keyword, the negation guard, the two measured false-positive fixes, the
border-colour exclusivity abstention) and the batch runner's dry-run/write/idempotence behavior.
No network calls, no image fetch, no `ImageEvidence` at all - this module consumes `Card.name`
only, same "host venv, no network" precedent every sibling caster's own test module establishes.
"""

import pytest

from cardpicker.attribute_tags import ATTRIBUTE_CHIP_TAG_NAMES, seed_attribute_tags
from cardpicker.default_tags import seed_default_tags
from cardpicker.local_filename_declarations import (
    BORDER_AXIS_CONTRADICTION_SKIP_REASON,
    BORDER_COLOR_AXIS_TAG_NAMES,
    FILENAME_DECLARATION_CAST_ANONYMOUS_ID,
    FILENAME_DECLARATION_PATTERNS,
    FILENAME_DECLARATION_VOTE_CONFIDENCE,
    NO_DECLARATION_SKIP_REASON,
    calculate_filename_declaration_verdict,
    run_filename_declaration_cast,
)
from cardpicker.models import CardScanLog, CardTagVote, VotePolarity, VoteSource
from cardpicker.sensitive_tags import seed_sensitive_tags
from cardpicker.tests.factories import CardFactory


def _seed_tags() -> None:
    seed_default_tags()
    seed_attribute_tags()
    seed_sensitive_tags()


class TestKeywordVocabularyCoverage:
    def test_every_attribute_chip_tag_has_an_explicit_entry(self) -> None:
        """A new chip added to ATTRIBUTE_CHIP_TAG_NAMES without a matching entry here (even an
        explicit `None`, like Modern Border) must fail loudly rather than silently go
        unsupported - the task's own requirement."""
        assert set(FILENAME_DECLARATION_PATTERNS) == set(ATTRIBUTE_CHIP_TAG_NAMES)

    def test_modern_border_is_deliberately_unsupported(self) -> None:
        assert FILENAME_DECLARATION_PATTERNS["Modern Border"] is None


class TestCalculateFilenameDeclarationVerdict:
    @pytest.mark.parametrize(
        "name,expected_tag",
        [
            ("Snapcaster Mage Extended.png", "Extended"),
            ("Selvala, Explorer Returned extended 2", "Extended"),
            ("Island (Showcase Mark Poole)", "Showcase"),
            ("Forest (OTJ 276 Full Art)", "Full Art"),
            ("Plateau (Full-Art Stained Glass)", "Full Art"),
            ("Urza, Lord High Artificer Fullart", "Full Art"),
            ("Forest (Borderless Kozyndan)", "Borderless"),
            ("Colossus Hammer [M20] (White Border Crop) (v3)", "White Border"),
            ("Goblin Bookie (Classic - Silver Bordered)", "Silver Border"),
            ("Cityscape Leveler (Classic Black Bordered)", "Black Border"),
            ("Seize the Spoils [Retro Frame]", "Old Border"),
            ("Sol Ring (old frame, JP)", "Old Border"),
            ("Sliver Queen (Futureshifted)", "Future Frame"),
            ("Providence of Night [YECL] (Futureshifted)", "Future Frame"),
        ],
    )
    def test_positive_declarations_are_read(self, db, name, expected_tag):
        card = CardFactory(name=name)
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert expected_tag in verdict.cast_tag_names

    def test_absence_of_a_keyword_is_not_read_as_a_negative(self, db):
        """Silence is not a claim - a plain name with no treatment word casts nothing at all,
        never a NOT_APPLICABLE-style vote."""
        card = CardFactory(name="Snapcaster Mage")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert verdict.cast_tag_names == frozenset()
        assert verdict.axis_contradiction is False

    def test_a_card_can_genuinely_match_several_non_exclusive_chips(self, db):
        card = CardFactory(name="Forest (Extended Showcase Borderless).png")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert verdict.cast_tag_names == frozenset({"Extended", "Showcase", "Borderless"})

    @pytest.mark.parametrize("name", ["Etched Champion", "Etched Oracle", "Etched Monstrosity", "etched champion"])
    def test_the_three_scars_of_mirrodin_card_names_do_not_false_positive_etched(self, db, name):
        """Real Scars-of-Mirrodin card names beginning with the word "Etched" - a filename that
        is JUST the card name must not manufacture an Etched-treatment vote (measured 2026-08-19,
        module docstring's KEYWORD VOCABULARY section)."""
        card = CardFactory(name=name)
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert "Etched" not in verdict.cast_tag_names

    def test_a_genuine_etched_declaration_on_one_of_those_same_cards_is_still_read(self, db):
        """The negative lookahead only excludes "Etched" immediately followed by one of the three
        collision words - a SECOND, later "Etched" in the same name (an actual treatment
        annotation) must still be read."""
        card = CardFactory(name="Etched Champion (Etched Foil)")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert "Etched" in verdict.cast_tag_names

    def test_wretched_does_not_false_positive_etched(self, db):
        """ "Wretched" embeds the substring "etched" with no preceding word boundary - the
        plain-substring trap the word-boundary regex exists to avoid."""
        card = CardFactory(name="Wretched Gryff")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert verdict.cast_tag_names == frozenset()

    @pytest.mark.parametrize(
        "name",
        [
            "Future Sight",
            "Future Sight [SLD]",
            "Nacatl War-Pride (Future Sight)",
            "Command Tower (Future Sight CMM Art)",
            "Exotic Orchard [Future]",
        ],
    )
    def test_the_future_sight_set_name_does_not_false_positive_future_frame(self, db, name):
        """ "future sight" was dropped as a keyword entirely (module docstring's KEYWORD
        VOCABULARY section) - it names the SET far more often than the timeshifted treatment."""
        card = CardFactory(name=name)
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert "Future Frame" not in verdict.cast_tag_names

    def test_alt_extended_does_not_false_positive_extended(self, db):
        """A concatenated identifier with no word boundary before "Extended" - measured in
        production ("Slip Through Space (AltExtended)")."""
        card = CardFactory(name="Slip Through Space (AltExtended)")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert "Extended" not in verdict.cast_tag_names

    def test_retrofitter_foundry_does_not_false_positive_old_border(self, db):
        card = CardFactory(name="Retrofitter Foundry")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert "Old Border" not in verdict.cast_tag_names

    def test_an_explicit_negation_casts_nothing_for_that_keyword(self, db):
        """Measured once in production: "No Black Border" is a negative CLAIM, not silence, and
        must not be read as a positive declaration."""
        card = CardFactory(name="Pantlaza, Sun-Favored [No Black Border, Stonecutter]")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert "Black Border" not in verdict.cast_tag_names

    @pytest.mark.parametrize("phrase", ["not extended", "without showcase"])
    def test_negation_applies_to_every_keyword_not_just_border_colour(self, db, phrase):
        keyword = phrase.split()[-1]
        expected_tag = {"extended": "Extended", "showcase": "Showcase"}[keyword]
        card = CardFactory(name=f"Some Card ({phrase})")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert expected_tag not in verdict.cast_tag_names

    @pytest.mark.parametrize(
        "name",
        [
            "Some Card (White Border) (Black Border)",
            "Some Card (Borderless) (Silver Border)",
        ],
    )
    def test_two_border_colour_declarations_abstain_on_the_whole_axis(self, db, name):
        card = CardFactory(name=name)
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert verdict.axis_contradiction is True
        assert verdict.cast_tag_names.isdisjoint(BORDER_COLOR_AXIS_TAG_NAMES)

    def test_an_axis_contradiction_does_not_suppress_an_unrelated_treatment_chip(self, db):
        card = CardFactory(name="Some Card (White Border) (Black Border) (Extended)")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert verdict.axis_contradiction is True
        assert verdict.cast_tag_names == frozenset({"Extended"})

    def test_a_single_border_colour_declaration_is_not_a_contradiction(self, db):
        card = CardFactory(name="Some Card (White Border)")
        verdict = calculate_filename_declaration_verdict(card.pk, card.name)
        assert verdict.axis_contradiction is False
        assert "White Border" in verdict.cast_tag_names


class TestRunFilenameDeclarationCast:
    def test_a_write_run_casts_every_matched_tag_with_the_deduction_source(self, db):
        _seed_tags()
        card = CardFactory(name="Forest (Extended Showcase Borderless).png")

        result = run_filename_declaration_cast(run_id="r1", dry_run=False)

        assert result.votes_written == 3
        assert result.cards_with_declarations == 1
        votes = CardTagVote.objects.filter(anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID, card=card)
        assert {v.tag.name for v in votes} == {"Extended", "Showcase", "Borderless"}
        for vote in votes:
            assert vote.polarity == VotePolarity.APPLY
            assert vote.source == VoteSource.DEDUCTION
            assert vote.confidence == FILENAME_DECLARATION_VOTE_CONFIDENCE
            assert vote.run_id == "r1"

    def test_a_dry_run_writes_nothing_at_all(self, db):
        _seed_tags()
        CardFactory(name="Snapcaster Mage Extended.png")

        result = run_filename_declaration_cast(run_id="r1", dry_run=True)

        assert result.votes_would_cast == 1
        assert CardTagVote.objects.count() == 0
        assert CardScanLog.objects.count() == 0

    def test_a_card_with_no_declaration_is_a_named_skip_not_a_crash(self, db):
        _seed_tags()
        card = CardFactory(name="Snapcaster Mage")

        result = run_filename_declaration_cast(run_id="r1", dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {NO_DECLARATION_SKIP_REASON: 1}
        assert CardScanLog.objects.get(card=card, anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID).skip_reason == (
            NO_DECLARATION_SKIP_REASON
        )

    def test_an_axis_contradiction_writes_a_scan_log_row_even_though_no_axis_vote_is_cast(self, db):
        _seed_tags()
        card = CardFactory(name="Some Card (White Border) (Black Border)")

        result = run_filename_declaration_cast(run_id="r1", dry_run=False)

        assert result.votes_written == 0
        assert result.skip_counts == {BORDER_AXIS_CONTRADICTION_SKIP_REASON: 1}
        assert CardTagVote.objects.filter(card=card, anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID).count() == 0
        assert CardScanLog.objects.get(card=card, anonymous_id=FILENAME_DECLARATION_CAST_ANONYMOUS_ID).skip_reason == (
            BORDER_AXIS_CONTRADICTION_SKIP_REASON
        )

    def test_a_second_run_is_idempotent(self, db):
        _seed_tags()
        CardFactory(name="Forest (Extended Showcase).png")

        run_filename_declaration_cast(run_id="r1", dry_run=False)
        second = run_filename_declaration_cast(run_id="r2", dry_run=False)

        assert second.votes_written == 0
        assert CardTagVote.objects.count() == 2

    def test_a_card_already_carrying_a_scan_log_row_is_not_reconsidered(self, db):
        """Card.name never changes, so a card that produced no-declaration once must never be
        re-selected - unlike the evidence-backed siblings, nothing here is rescannable."""
        _seed_tags()
        card = CardFactory(name="Snapcaster Mage")
        run_filename_declaration_cast(run_id="r1", dry_run=False)
        assert CardScanLog.objects.filter(card=card).count() == 1

        second = run_filename_declaration_cast(run_id="r2", dry_run=False)

        assert second.cards_considered == 0
        assert CardScanLog.objects.filter(card=card).count() == 1

    def test_missing_tag_seed_raises(self, db):
        CardFactory(name="Snapcaster Mage Extended.png")
        with pytest.raises(RuntimeError):
            run_filename_declaration_cast(run_id="r1", dry_run=False)

    def test_card_ids_scopes_the_batch(self, db):
        _seed_tags()
        in_scope = CardFactory(name="Snapcaster Mage Extended.png")
        out_of_scope = CardFactory(name="Forest (Showcase).png")

        result = run_filename_declaration_cast(run_id="r1", dry_run=False, card_ids=[in_scope.pk])

        assert result.cards_considered == 1
        assert CardTagVote.objects.filter(card=in_scope).count() == 1
        assert CardTagVote.objects.filter(card=out_of_scope).count() == 0
