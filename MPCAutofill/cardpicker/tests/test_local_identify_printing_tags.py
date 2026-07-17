"""
Tests for the local OCR/phash printing-identification pilot (docs/features/printing-tags.md's
Stage 8). No network calls and no real tesseract binary in CI - both engines' raw outputs
(local_ocr.run_tesseract, local_phash's Scryfall/image fetches) are mocked throughout via
monkeypatch/requests_mock. The one test that exercises the real tesseract binary is guarded
with a skipif so the suite stays green in an environment without it installed (see
docs/features/printing-tags.md's Stage 8 environment section - CI's django image doesn't have
it, only the host venv used for the real pilot run does).
"""

import collections
import os
import shutil

import pytest
from PIL import Image, ImageDraw

from cardpicker.local_clustering import (
    NEAR_DUPLICATE_MAX_DISTANCE,
    compute_two_threshold_clusters,
)
from cardpicker.local_fallback import FALLBACK_ANONYMOUS_ID
from cardpicker.local_identify_printing_tags import (
    DEDUCTIVE_BACKFILL_ANONYMOUS_ID,
    NAME_FREQUENCY_ANONYMOUS_ID,
    NAME_FREQUENCY_CONFIDENCE,
    OCR_ANONYMOUS_ID,
    PHASH_ANONYMOUS_ID,
    RESCANNABLE_SKIP_REASONS,
    RESOLUTION_FLOOR_DPI,
    CandidateNameIndex,
    CandidatePrinting,
    compute_covered_printing_pks,
    count_below_resolution_floor,
    get_worker_image_url,
    run_name_frequency_elimination,
    run_pilot,
    select_candidates,
    verify_zero_resolutions,
)
from cardpicker.local_ocr import (
    crop_collector_line,
    parse_collector_line,
    preprocess_variants,
    run_tesseract,
    validate_against_candidates,
)
from cardpicker.local_phash import (
    BackfillResult,
    compute_content_phash_for_card,
    find_best_match,
    run_content_phash_backfill,
)
from cardpicker.models import (
    CardPrintingTag,
    CardScanLog,
    CardTagVote,
    CardTypes,
    PilotRunLedger,
    PrintingTagStatus,
    VotePolarity,
    VoteSource,
)
from cardpicker.tests.factories import (
    CanonicalArtistFactory,
    CanonicalCardFactory,
    CanonicalExpansionFactory,
    CanonicalPrintingMetadataFactory,
    CardFactory,
    CardPrintingTagFactory,
    SourceFactory,
    TagFactory,
)

# see test_deductive_backfill.py's identical fixture for the full rationale
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


class TestSelection:
    def test_excludes_resolved_cards(self, db):
        CardFactory(name="Forest", printing_tag_status=PrintingTagStatus.RESOLVED)
        CanonicalCardFactory(name="Forest")
        assert select_candidates("ocr") == []

    def test_excludes_cards_with_confirmed_indexing_match(self, db):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", canonical_card=printing)
        assert select_candidates("ocr") == []

    def test_excludes_cards_with_no_name_candidate(self, db):
        CardFactory(name="Totally Unmatched Name")
        assert select_candidates("ocr") == []

    def test_includes_card_with_a_name_candidate(self, db):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [card.pk]

    def test_excludes_tokens(self, db):
        # 2026-07-16, diagnosed live: a token's printed collector line reads its PARENT set's
        # code, while its CanonicalCard candidates use token-specific set codes that never
        # match - structurally unmatchable, not a fixable parsing bug. Combined with item 1's
        # "descending uncovered count" ordering, generic multi-set token names were being
        # front-loaded to the very front of every real selection.
        CanonicalCardFactory(name="Beast")
        CardFactory(name="Beast", card_type=CardTypes.TOKEN)
        assert select_candidates("ocr") == []

    def test_excludes_cardbacks(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", card_type=CardTypes.CARDBACK)
        assert select_candidates("ocr") == []

    def test_excludes_card_with_existing_vote_from_this_engines_own_anonymous_id(self, db):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=OCR_ANONYMOUS_ID)
        assert select_candidates("ocr") == []
        # a different engine's own anonymous_id is unaffected by an OCR vote
        assert [s.card.pk for s in select_candidates("phash")] == [card.pk]

    def test_excludes_card_already_covered_by_deductive_backfill(self, db):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=DEDUCTIVE_BACKFILL_ANONYMOUS_ID)
        assert select_candidates("ocr") == []

    def test_excludes_resolved_custom_art_tag(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", tags=["custom-art"])
        assert select_candidates("ocr") == []

    def test_excludes_resolved_non_english_tag(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", tags=["non-english"])
        assert select_candidates("ocr") == []

    def test_more_uncovered_candidates_come_before_fewer_when_both_fully_uncovered(self, db):
        # addendum item 1 (2026-07-15): with no coverage at all, both names sit in the
        # zero-covered tier - the ORIGINAL "multi before single" ordering was actually a special
        # case of this: 2 uncovered candidates outranks 1 uncovered candidate at priority (2),
        # before "fewer candidates first" (priority 4) ever gets consulted.
        CanonicalCardFactory(name="Single Match")
        single = CardFactory(name="Single Match")
        CanonicalCardFactory(name="Multi Match", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Multi Match", expansion=CanonicalExpansionFactory(code="bbb"))
        multi = CardFactory(name="Multi Match")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [multi.pk, single.pk]


class TestExpansionHintNarrowing:
    """Fast-follow (2026-07-16): _narrow_candidates_by_expansion_hint narrows the candidate
    list an engine considers using Card.expansion_hint (already populated at import time by
    cardpicker.tags.Tags.extract - not a new field, just newly wired into the pilot)."""

    def test_no_hint_returns_selected_unchanged(self, db):
        import cardpicker.local_identify_printing_tags as module

        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        card = CardFactory(name="Forest", expansion_hint="")
        index = CandidateNameIndex()
        selected = module.SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        narrowed = module._narrow_candidates_by_expansion_hint(selected)

        assert narrowed is selected
        assert len(narrowed.candidates) == 2

    def test_hint_narrows_to_only_matching_candidates(self, db):
        import cardpicker.local_identify_printing_tags as module

        expansion_bbb = CanonicalExpansionFactory(code="bbb")
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=expansion_bbb)
        CanonicalCardFactory(name="Forest", expansion=expansion_bbb)
        card = CardFactory(name="Forest", expansion_hint="bbb")
        index = CandidateNameIndex()
        selected = module.SelectedCard(card=card, candidates=index.candidates_for("Forest"))
        assert len(selected.candidates) == 3

        narrowed = module._narrow_candidates_by_expansion_hint(selected)

        assert len(narrowed.candidates) == 2
        assert all(c.expansion_code == "bbb" for c in narrowed.candidates)
        assert narrowed.card is card

    def test_hint_matching_zero_candidates_falls_back_to_full_list(self, db):
        # a real, measured data-quality case: the hint doesn't match anything in this name's
        # actual candidate pool - narrowing to empty would make matching IMPOSSIBLE, strictly
        # worse than not narrowing at all.
        import cardpicker.local_identify_printing_tags as module

        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest", expansion_hint="zzz")
        index = CandidateNameIndex()
        selected = module.SelectedCard(card=card, candidates=index.candidates_for("Forest"))

        narrowed = module._narrow_candidates_by_expansion_hint(selected)

        assert len(narrowed.candidates) == 1

    def test_phash_unlocked_when_narrowing_crosses_under_the_candidate_cap(self, db, monkeypatch):
        # the real, measured benefit: a name with MORE than PHASH_MAX_CANDIDATES total
        # printings gets skipped entirely ("too-many-candidates") - but if this card's own
        # expansion_hint narrows it down to a small handful, phash gets a real shot instead.
        import cardpicker.local_identify_printing_tags as module

        for i in range(module.PHASH_MAX_CANDIDATES + 3):
            CanonicalCardFactory(name="Beast", expansion=CanonicalExpansionFactory(code=f"e{i:02}"))
        CanonicalCardFactory(name="Beast", expansion=CanonicalExpansionFactory(code="hnt"))
        CardFactory(name="Beast", expansion_hint="hnt")

        phash_call_candidate_counts: list[int] = []

        def recording_run_phash_for_card(selected, image, threshold, margin, max_candidates, bleed_class=None):
            phash_call_candidate_counts.append(len(selected.candidates))
            return None, "no-clear-winner"

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (750, 1050)))
        monkeypatch.setattr(module, "run_phash_for_card", recording_run_phash_for_card)

        run_pilot(engine="phash", limit=10, dry_run=True, nice=False)

        # narrowed to just the "hnt" candidate (1), not the full 13+ - phash actually ran
        # (recorded a call) instead of being skipped at selection-adjacent "too-many-candidates".
        assert phash_call_candidate_counts == [1]


class TestCoveragePriority:
    """Addendum item 1 (2026-07-15): coverage-gap + demand ordering, the full 5-key tuple
    (zero-covered first, descending uncovered count, demand rank, fewer candidates, pk)."""

    def test_zero_covered_names_come_before_partially_covered_names_even_with_fewer_uncovered(self, db):
        # a partially-covered name can have a HIGHER absolute uncovered count than a
        # zero-covered name, but priority (1) (the zero-covered boolean) still wins - this is
        # the case that distinguishes (1) from a pure "-uncovered_count" sort.
        CanonicalCardFactory(name="Zero Covered")
        zero_covered = CardFactory(name="Zero Covered")

        partially_covered_printing_a = CanonicalCardFactory(
            name="Partially Covered", expansion=CanonicalExpansionFactory(code="aaa")
        )
        for i in range(9):
            CanonicalCardFactory(name="Partially Covered", expansion=CanonicalExpansionFactory(code=f"b{i:02}"))
        # one of "Partially Covered"'s 10 printings is confirmed - 9 uncovered, more than "Zero
        # Covered"'s single uncovered printing, but it must still sort AFTER.
        CardFactory(canonical_card=partially_covered_printing_a)
        partially_covered = CardFactory(name="Partially Covered")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [zero_covered.pk, partially_covered.pk]

    def test_more_uncovered_beats_fewer_within_the_same_tier(self, db):
        CanonicalCardFactory(name="Two Uncovered", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Two Uncovered", expansion=CanonicalExpansionFactory(code="bbb"))
        two_uncovered = CardFactory(name="Two Uncovered")

        CanonicalCardFactory(name="One Uncovered")
        one_uncovered = CardFactory(name="One Uncovered")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [two_uncovered.pk, one_uncovered.pk]

    def test_fewer_candidates_is_only_a_tiebreak_after_coverage_and_demand_are_equal(self, db):
        # both names: single uncovered candidate each, no edhrec_rank (both hit the "no demand
        # signal" sentinel) - so priority (4), fewer candidates, is what actually decides here.
        CanonicalCardFactory(name="Fewer Candidates")
        fewer = CardFactory(name="Fewer Candidates")

        CanonicalCardFactory(name="More Candidates", expansion=CanonicalExpansionFactory(code="aaa"))
        more_printing = CanonicalCardFactory(name="More Candidates", expansion=CanonicalExpansionFactory(code="bbb"))
        # cover the second "More Candidates" printing so both names have exactly ONE uncovered
        # candidate - otherwise priority (2) (descending uncovered count) would decide instead.
        CardFactory(canonical_card=more_printing)
        more = CardFactory(name="More Candidates")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [fewer.pk, more.pk]

    def test_fully_covered_names_process_last_not_never(self, db):
        covered_printing = CanonicalCardFactory(name="Fully Covered")
        covered = CardFactory(name="Fully Covered")
        CardFactory(canonical_card=covered_printing)

        CanonicalCardFactory(name="Uncovered")
        uncovered = CardFactory(name="Uncovered")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [uncovered.pk, covered.pk]

    def test_inferred_canonical_card_only_counts_as_covered_when_resolved(self, db):
        # "machine votes pending confirmation do NOT count as coverage" - an UNRESOLVED
        # inferred_canonical_card (e.g. a machine vote awaiting human confirmation) must not
        # make this name outrank a genuinely zero-covered one.
        pending_printing = CanonicalCardFactory(name="Pending Inference")
        pending = CardFactory(
            name="Pending Inference",
            inferred_canonical_card=pending_printing,
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
        )

        CanonicalCardFactory(name="Zero Covered")
        zero_covered = CardFactory(name="Zero Covered")

        covered_printing_pks = compute_covered_printing_pks()
        assert pending_printing.pk not in covered_printing_pks

        selected = select_candidates("ocr")
        # both are single-candidate, zero-covered (pending's own printing isn't "covered" by the
        # spec's own definition) - tiebreak (5), pk, decides between them.
        assert {s.card.pk for s in selected} == {pending.pk, zero_covered.pk}

    def test_resolved_inferred_canonical_card_does_count_as_covered(self, db):
        resolved_printing = CanonicalCardFactory(name="Resolved Inference")
        CardFactory(
            name="Resolved Inference",
            inferred_canonical_card=resolved_printing,
            printing_tag_status=PrintingTagStatus.RESOLVED,
        )
        covered_printing_pks = compute_covered_printing_pks()
        assert resolved_printing.pk in covered_printing_pks
        # resolved's own card is excluded from selection entirely (printing_tag_status is no
        # longer UNRESOLVED), but the coverage computation itself is what's under test here.
        assert select_candidates("ocr") == []


class TestDemandRank:
    """Addendum item 3 (2026-07-15): priority (3) of the coverage-priority tuple - ascending
    edhrec_rank (lower = more popular = processed first) as a tiebreak within a coverage tier."""

    def test_lower_edhrec_rank_comes_first_within_the_same_coverage_tier(self, db):
        high_demand_printing = CanonicalCardFactory(name="High Demand")
        CanonicalPrintingMetadataFactory(canonical_card=high_demand_printing, edhrec_rank=5)
        high_demand = CardFactory(name="High Demand")

        low_demand_printing = CanonicalCardFactory(name="Low Demand")
        CanonicalPrintingMetadataFactory(canonical_card=low_demand_printing, edhrec_rank=50000)
        low_demand = CardFactory(name="Low Demand")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [high_demand.pk, low_demand.pk]

    def test_missing_edhrec_rank_sorts_last_not_first(self, db):
        ranked_printing = CanonicalCardFactory(name="Ranked")
        CanonicalPrintingMetadataFactory(canonical_card=ranked_printing, edhrec_rank=99999)
        ranked = CardFactory(name="Ranked")

        # no CanonicalPrintingMetadata at all - edhrec_rank is unknown, not literally 0.
        CanonicalCardFactory(name="Unranked")
        unranked = CardFactory(name="Unranked")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [ranked.pk, unranked.pk]

    def test_a_names_demand_rank_is_its_most_popular_printings_rank(self, db):
        # a name with one well-known printing and one obscure one should be treated as
        # high-demand overall - the MIN across its candidates, not e.g. an average.
        mixed_a = CanonicalCardFactory(name="Mixed Demand", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalPrintingMetadataFactory(canonical_card=mixed_a, edhrec_rank=3)
        mixed_b = CanonicalCardFactory(name="Mixed Demand", expansion=CanonicalExpansionFactory(code="bbb"))
        CanonicalPrintingMetadataFactory(canonical_card=mixed_b, edhrec_rank=90000)
        mixed = CardFactory(name="Mixed Demand")

        mid_printing = CanonicalCardFactory(name="Mid Demand")
        CanonicalPrintingMetadataFactory(canonical_card=mid_printing, edhrec_rank=500)
        mid = CardFactory(name="Mid Demand")

        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [mixed.pk, mid.pk]


class TestResolutionFloor:
    """Addendum item 4 (2026-07-15): RESOLUTION_FLOOR_DPI applied in the selection query itself
    - a source image already below it is never selected, so never fetched."""

    def test_below_floor_card_is_never_selected(self, db):
        CanonicalCardFactory(name="Low Res")
        CardFactory(name="Low Res", dpi=RESOLUTION_FLOOR_DPI - 1)
        assert select_candidates("ocr") == []

    def test_at_floor_card_is_selected(self, db):
        CanonicalCardFactory(name="At Floor")
        at_floor = CardFactory(name="At Floor", dpi=RESOLUTION_FLOOR_DPI)
        assert [s.card.pk for s in select_candidates("ocr")] == [at_floor.pk]

    def test_count_below_resolution_floor_matches_what_was_skipped(self, db):
        CanonicalCardFactory(name="Low Res")
        CardFactory(name="Low Res", dpi=RESOLUTION_FLOOR_DPI - 1)
        CanonicalCardFactory(name="High Res")
        CardFactory(name="High Res", dpi=RESOLUTION_FLOOR_DPI)

        assert count_below_resolution_floor(OCR_ANONYMOUS_ID) == 1
        assert len(select_candidates("ocr")) == 1

    def test_below_floor_cards_are_excluded_from_the_count_once_already_voted_on(self, db):
        # count_below_resolution_floor shares _eligible_base_queryset's other rules (idempotence
        # etc.) - a below-floor card that's already been voted on by this engine shouldn't be
        # double-counted as a "would fetch except for the floor" skip forever.
        printing = CanonicalCardFactory(name="Low Res")
        card = CardFactory(name="Low Res", dpi=RESOLUTION_FLOOR_DPI - 1)
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=OCR_ANONYMOUS_ID)
        assert count_below_resolution_floor(OCR_ANONYMOUS_ID) == 0


class TestSourceExclusion:
    def test_excludes_cards_from_a_given_source_pk(self, db):
        excluded_source = SourceFactory()
        included_source = SourceFactory()
        CanonicalCardFactory(name="Forest")
        excluded_card = CardFactory(name="Forest", source=excluded_source)
        included_card = CardFactory(name="Forest", source=included_source)

        selected = select_candidates("ocr", exclude_source_pks=[excluded_source.pk])
        assert [s.card.pk for s in selected] == [included_card.pk]
        assert excluded_card.pk not in [s.card.pk for s in selected]

    def test_no_exclusion_by_default(self, db):
        source = SourceFactory()
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest", source=source)
        assert [s.card.pk for s in select_candidates("ocr")] == [card.pk]

    def test_exclusion_is_independent_per_engine(self, db):
        source = SourceFactory()
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest", source=source)

        assert select_candidates("ocr", exclude_source_pks=[source.pk]) == []
        assert [s.card.pk for s in select_candidates("phash", exclude_source_pks=[])] == [card.pk]


class TestManagementCommandExclusionDefaults:
    """The library-level tests above always pass exclude_source_pks explicitly - none of them
    touch the CLI's own --exclude-sources-ocr/--exclude-sources-phash argparse defaults. This
    guards the actual thing Rider 2 was for: a bare invocation excludes source pk=1 from OCR
    (and only OCR) without the operator having to remember the flag."""

    def test_bare_invocation_defaults_to_excluding_source_pk_1_for_ocr_only(self, db, capsys):
        from django.core.management import call_command

        call_command("local_identify_printing_tags", "--dry-run", "--limit", "0")
        printed = capsys.readouterr().out
        assert "--exclude-sources-ocr=[1]" in printed
        assert "--exclude-sources-phash=[]" in printed

    def test_explicit_flag_overrides_the_default(self, db, capsys):
        from django.core.management import call_command

        call_command(
            "local_identify_printing_tags",
            "--dry-run",
            "--limit",
            "0",
            "--exclude-sources-ocr",
            "",
            "--exclude-sources-phash",
            "2,3",
        )
        printed = capsys.readouterr().out
        assert "--exclude-sources-ocr=[]" in printed
        assert "--exclude-sources-phash=[2, 3]" in printed

    def test_bare_invocation_defaults_fetch_dpi_to_250(self, db, capsys):
        from django.core.management import call_command

        call_command("local_identify_printing_tags", "--dry-run", "--limit", "0")
        printed = capsys.readouterr().out
        assert "--fetch-dpi=250" in printed

    def test_fetch_dpi_zero_means_native_resolution(self, db, capsys):
        from django.core.management import call_command

        call_command("local_identify_printing_tags", "--dry-run", "--limit", "0", "--fetch-dpi", "0")
        printed = capsys.readouterr().out
        assert "--fetch-dpi=None" in printed


class TestCandidateNameIndex:
    def test_groups_by_normalised_name(self, db):
        CanonicalCardFactory(name="Kusari-Gama")
        index = CandidateNameIndex()
        assert len(index.candidates_for("Kusari-Gama (Modern Tomas Giorello)")) == 1


class TestOcrParsing:
    def test_standard_modern_collector_line(self):
        parsed = parse_collector_line("158/287 R MOM EN Some Artist")
        assert parsed.set_code == "mom"
        assert parsed.collector_number == "158"

    def test_pre_m15_has_no_set_code(self):
        # older frames print just the collector number, no set code on the line at all
        parsed = parse_collector_line("158")
        assert parsed.set_code is None
        assert parsed.collector_number == "158"

    def test_letter_suffix_collector_number(self):
        parsed = parse_collector_line("123a/281 M MID EN")
        assert parsed.collector_number == "123a"

    def test_junk_input_parses_to_nothing(self):
        parsed = parse_collector_line("asdf jkl qwerty !!@#")
        assert parsed.set_code is None
        assert parsed.collector_number is None

    def test_empty_string(self):
        parsed = parse_collector_line("")
        assert parsed.set_code is None
        assert parsed.collector_number is None

    def test_leading_noise_token_before_number_is_skipped_for_real_set_code_after(self):
        # 2026-07-15 no-match autopsy finding (docs/features/printing-tags.md's Stage 8): a
        # plausible-looking 3-5 char token appearing BEFORE the collector number (a watermark,
        # a rarity-letter glyph merging with a stray digit) must not win over the real set code
        # that follows the number, per real MTG collector-line layout (number always comes
        # first). "R0O324 WilfordGriml\nLCI ¢ EN..." - "R0O" is exactly such spurious noise.
        parsed = parse_collector_line("R0O324 WilfordGriml\nLCI ¢ EN © SIDHARTH (")
        assert parsed.collector_number == "324"
        assert parsed.set_code == "lci"

    def test_falls_back_to_a_before_number_token_when_nothing_plausible_follows(self):
        # no real second line at all - the only plausible token is before the number, so it
        # must still be used rather than giving up (some old-format lines genuinely have no
        # "after" content to search).
        parsed = parse_collector_line("MOM 158")
        assert parsed.collector_number == "158"
        assert parsed.set_code == "mom"


class TestOcrValidationRail:
    CANDIDATES = [
        CandidatePrinting(pk=1, expansion_code="mom", collector_number="158"),
        CandidatePrinting(pk=2, expansion_code="vow", collector_number="158"),
    ]

    def test_no_text_extracted(self):
        parsed = parse_collector_line("")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is None
        assert reason == "no-text"

    def test_set_and_collector_match_exactly_one_candidate(self):
        parsed = parse_collector_line("158/287 R MOM EN")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is not None
        assert matched.pk == 1
        assert reason == ""

    def test_parsed_but_no_matching_candidate(self):
        parsed = parse_collector_line("999/287 R MOM EN")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is None
        assert reason == "parsed-but-no-match"

    def test_collector_only_ambiguous_across_two_candidates(self):
        # no set code parsed - collector number "158" alone matches both candidates above
        parsed = parse_collector_line("158")
        matched, reason = validate_against_candidates(parsed, self.CANDIDATES)
        assert matched is None
        assert reason == "ambiguous"

    def test_collector_only_matches_when_unambiguous(self):
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="158")]
        parsed = parse_collector_line("158")
        matched, reason = validate_against_candidates(parsed, candidates)
        assert matched is not None
        assert matched.pk == 1
        assert reason == ""

    def test_leading_zero_in_parsed_number_matches_a_candidate_without_one(self):
        # 2026-07-15 no-match autopsy finding: OCR often reads a spurious leading zero
        # ("0093" for a real "93") - this alone accounted for the majority of a 47/176 (26.7%)
        # yield-delta fix, see docs/features/printing-tags.md's Stage 8 no-match autopsy.
        candidates = [CandidatePrinting(pk=1, expansion_code="unf", collector_number="93")]
        parsed = parse_collector_line("C0093 WilfordGrim\nUNF EN ALEXANDE")
        matched, reason = validate_against_candidates(parsed, candidates)
        assert matched is not None
        assert matched.pk == 1
        assert reason == ""

    def test_leading_zero_in_stored_candidate_matches_a_plain_parsed_number(self):
        # the reverse direction - some CanonicalCard rows themselves store a zero-padded
        # collector_number (e.g. "007" for a promo) - normalization must apply symmetrically.
        candidates = [CandidatePrinting(pk=1, expansion_code="mom", collector_number="007")]
        parsed = parse_collector_line("7/287 R MOM EN")
        matched, reason = validate_against_candidates(parsed, candidates)
        assert matched is not None
        assert matched.pk == 1
        assert reason == ""


class TestPhashThresholdAndMargin:
    def test_clear_winner_within_threshold_and_margin(self):
        candidate_a = CandidatePrinting(pk=1, expansion_code="mom", collector_number="1")
        candidate_b = CandidatePrinting(pk=2, expansion_code="mom", collector_number="2")
        match, reason = find_best_match(
            card_hash=0,
            candidates_with_hashes=[(candidate_a, 0), (candidate_b, (1 << 40) - 1)],
            distance_threshold=10,
            margin=6,
        )
        assert reason == ""
        assert match is not None
        assert match.candidate.pk == 1

    def test_over_distance_threshold_is_no_clear_winner(self):
        candidate = CandidatePrinting(pk=1, expansion_code="mom", collector_number="1")
        match, reason = find_best_match(
            card_hash=0, candidates_with_hashes=[(candidate, (1 << 20) - 1)], distance_threshold=10, margin=6
        )
        assert match is None
        assert reason == "no-clear-winner"

    def test_runner_up_too_close_is_no_clear_winner(self):
        # best distance 2 (within threshold), but runner-up at distance 4 is only 2 apart -
        # below the margin of 6, so the match isn't clear enough to trust
        candidate_a = CandidatePrinting(pk=1, expansion_code="mom", collector_number="1")
        candidate_b = CandidatePrinting(pk=2, expansion_code="mom", collector_number="2")
        match, reason = find_best_match(
            card_hash=0b11,
            candidates_with_hashes=[(candidate_a, 0), (candidate_b, 0b1111)],
            distance_threshold=10,
            margin=6,
        )
        assert match is None
        assert reason == "no-clear-winner"

    def test_no_hashable_candidates(self):
        match, reason = find_best_match(card_hash=0, candidates_with_hashes=[], distance_threshold=10, margin=6)
        assert match is None
        assert reason == "no-hashable-candidates"


class TestPhashCandidateCap:
    """A name with more candidates than the cap (basic lands/staple commons - 944 candidates
    for Forest alone in the live pilot pool, confirmed 2026-07-15) must never fetch or hash
    anything - the cap is checked before any network call, not just before voting."""

    def test_over_the_cap_skips_without_fetching_anything(self, db, monkeypatch):
        import cardpicker.local_identify_printing_tags as module

        card = CardFactory(name="Forest")
        candidates = [CandidatePrinting(pk=i, expansion_code="aaa", collector_number=str(i)) for i in range(13)]
        selected = module.SelectedCard(card=card, candidates=candidates)

        # passing image=None (rather than a real fetch) doubles as proof the cap is checked
        # before any image is needed at all - if the cap check didn't short-circuit first,
        # this would instead fail differently (compute_card_art_hash on a None image)
        vote, reason = module.run_phash_for_card(selected, None, max_candidates=12)
        assert vote is None
        assert reason == "too-many-candidates"

    def test_at_or_under_the_cap_is_unaffected(self, db, monkeypatch):
        import cardpicker.local_identify_printing_tags as module

        card = CardFactory(name="Forest")
        candidates = [CandidatePrinting(pk=i, expansion_code="aaa", collector_number=str(i)) for i in range(12)]
        selected = module.SelectedCard(card=card, candidates=candidates)

        vote, reason = module.run_phash_for_card(selected, None, max_candidates=12)
        assert vote is None
        assert reason == "unfetchable-image"  # got past the cap check, failed later for an unrelated reason


class TestOcrLiveTesseractIntegration:
    """The one test that exercises the real tesseract binary (see this module's docstring) -
    everything else in this file mocks run_tesseract, since CI's django image doesn't have the
    binary installed (see docs/features/printing-tags.md's Stage 8 environment section)."""

    @pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract-ocr binary not installed")
    def test_crop_preprocess_and_ocr_a_synthetic_collector_line(self):
        # positioned within DEFAULT_CROP_BOX's band (left 45-262px, top 945-1013px of a
        # 750x1050 image) - tuned against real production card images, see DEFAULT_CROP_BOX's
        # comment
        img = Image.new("RGB", (750, 1050), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([45, 945, 262, 1013], fill="black")
        draw.text((50, 970), "158/287 R MOM EN", fill="white")

        cropped = crop_collector_line(img)
        variants = preprocess_variants(cropped)
        texts = [run_tesseract(v) for v in variants]
        parsed_results = [parse_collector_line(t) for t in texts]
        assert any(p.set_code == "mom" and p.collector_number == "158" for p in parsed_results)


class TestRunPilotAgreementAndDisagreement:
    def test_both_engines_agree_keeps_both_votes(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        card = CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            )

        def fake_phash(selected, image, threshold, margin, max_candidates, bleed_class=None):
            return module.EngineVote(engine="phash", printing_pk=printing.pk, confidence=0.8, detail="d=0"), ""

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "run_phash_for_card", fake_phash)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        results, _attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 1
        assert results["phash"].votes_written == 1
        assert results["ocr"].disagreements == []
        from cardpicker.models import CardPrintingTag

        assert CardPrintingTag.objects.filter(card=card, anonymous_id=OCR_ANONYMOUS_ID).exists()
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=PHASH_ANONYMOUS_ID).exists()

    def test_both_engines_disagree_writes_neither(self, db, monkeypatch):
        printing_a = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        printing_b = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        card = CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing_a.pk, confidence=0.85, detail="raw")
            )

        def fake_phash(selected, image, threshold, margin, max_candidates, bleed_class=None):
            return module.EngineVote(engine="phash", printing_pk=printing_b.pk, confidence=0.8, detail="d=0"), ""

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "run_phash_for_card", fake_phash)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        results, _attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 0
        assert results["phash"].votes_written == 0
        assert len(results["ocr"].disagreements) == 1
        assert results["ocr"].disagreements[0]["card_id"] == card.pk
        from cardpicker.models import CardPrintingTag

        assert not CardPrintingTag.objects.filter(card=card).exists()

    def test_dry_run_writes_nothing(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=True, nice=False)

        assert results["ocr"].votes_written == 1  # counted, even though nothing is persisted
        from cardpicker.models import CardPrintingTag

        assert not CardPrintingTag.objects.exists()

    def test_only_requested_engine_appears_in_results(self, db, monkeypatch):
        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=True, nice=False)
        # "fallback" (pass 2) always gets a result entry - it isn't a selectable --engine, it
        # fires automatically whenever pass 1 (whichever engines were requested) misses
        assert set(results.keys()) == {"ocr", "fallback"}


class TestUncoveredPrintingsClosed:
    """Addendum item 1's run-level progress metric. A pilot vote is never a direct resolve (the
    gate check - TestVerifyZeroResolutions - asserts this structurally), so a real write run
    still can't move a printing from uncovered to covered by itself; this is the documented,
    by-design behavior (AttributeReport.uncovered_printings_closed's own docstring), not
    something these tests are expected to ever observe going non-zero via a pilot vote alone."""

    def test_stays_zero_on_a_real_write_run_since_a_pilot_vote_alone_cannot_resolve_anything(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        _results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)
        assert attributes.uncovered_printings_closed == 0

    def test_stays_zero_in_dry_run(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        _results, attributes = run_pilot(engine="ocr", limit=10, dry_run=True, nice=False)
        assert attributes.uncovered_printings_closed == 0


class TestNameFrequencyElimination:
    """Fast-follow (2026-07-16): run_name_frequency_elimination's SAFE 1:1 gate - exactly one
    uncovered printing AND exactly one unresolved-eligible card for that name - not just "one
    uncovered printing" (which is unsound whenever more than one unresolved card shares a name;
    see the function's own docstring for the full rationale, backed by a live measurement)."""

    def test_votes_for_the_single_uncovered_printing_when_exactly_one_card_and_one_gap(self, db):
        covered_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        uncovered_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(canonical_card=covered_printing)  # confirms "aaa" as covered
        card = CardFactory(name="Forest")  # the single unresolved card for this name

        result = run_name_frequency_elimination(dry_run=False)

        assert result.votes_written == 1
        vote = CardPrintingTag.objects.get(card=card, anonymous_id=NAME_FREQUENCY_ANONYMOUS_ID)
        assert vote.printing_id == uncovered_printing.pk
        assert vote.confidence == NAME_FREQUENCY_CONFIDENCE
        assert vote.is_no_match is False

    def test_does_not_vote_when_multiple_unresolved_cards_share_the_name(self, db):
        # the unsafe case this gate exists specifically to exclude: TWO unresolved cards for
        # "Forest", only one uncovered printing - elimination can't tell you which card (if
        # either) is the missing one, so it must abstain for BOTH, not guess for either.
        covered_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(canonical_card=covered_printing)
        CardFactory(name="Forest")
        CardFactory(name="Forest")

        result = run_name_frequency_elimination(dry_run=False)

        assert result.votes_written == 0
        assert not CardPrintingTag.objects.filter(anonymous_id=NAME_FREQUENCY_ANONYMOUS_ID).exists()

    def test_does_not_vote_when_more_than_one_printing_is_uncovered(self, db):
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(name="Forest")  # single unresolved card, but nothing covered at all

        result = run_name_frequency_elimination(dry_run=False)

        assert result.votes_written == 0

    def test_does_not_vote_when_fully_covered(self, db):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(canonical_card=printing)
        CardFactory(name="Forest")

        result = run_name_frequency_elimination(dry_run=False)

        assert result.votes_written == 0

    def test_dry_run_writes_nothing(self, db):
        covered_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(canonical_card=covered_printing)
        CardFactory(name="Forest")

        result = run_name_frequency_elimination(dry_run=True)

        assert result.votes_written == 1  # counted, even though nothing is persisted
        assert not CardPrintingTag.objects.exists()

    def test_idempotent_on_a_second_invocation(self, db):
        covered_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(canonical_card=covered_printing)
        CardFactory(name="Forest")

        first = run_name_frequency_elimination(dry_run=False)
        second = run_name_frequency_elimination(dry_run=False)

        assert first.votes_written == 1
        assert second.votes_written == 0
        assert CardPrintingTag.objects.filter(anonymous_id=NAME_FREQUENCY_ANONYMOUS_ID).count() == 1

    def test_excludes_tokens_and_cardbacks(self, db):
        covered_printing = CanonicalCardFactory(name="Beast", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Beast", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(canonical_card=covered_printing)
        CardFactory(name="Beast", card_type=CardTypes.TOKEN)

        result = run_name_frequency_elimination(dry_run=False)

        assert result.votes_written == 0


class TestNameFrequencyEliminationCommand:
    def test_dry_run_writes_nothing(self, db, capsys):
        from django.core.management import call_command

        covered_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(canonical_card=covered_printing)
        CardFactory(name="Forest")

        call_command("local_name_frequency_elimination", "--dry-run")

        printed = capsys.readouterr().out
        assert "[DRY RUN]" in printed
        assert "votes written: 1" in printed
        assert not CardPrintingTag.objects.exists()

    def test_real_run_writes_and_passes_gate_check(self, db, capsys):
        from django.core.management import call_command

        covered_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(canonical_card=covered_printing)
        card = CardFactory(name="Forest")

        call_command("local_name_frequency_elimination")

        printed = capsys.readouterr().out
        assert "[WRITE]" in printed
        assert "Gate check passed: 0/1 affected cards resolved." in printed
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=NAME_FREQUENCY_ANONYMOUS_ID).exists()


class TestPilotRunLedger:
    """docs/features/catalog-completion-plan.md's Part 1: each real (non-dry-run) command
    invocation creates a PilotRunLedger row and keeps it in lockstep with the run's outcome -
    RUNNING at start, COMPLETED on success, FAILED on an exception or a gate violation. A
    missing/inconsistent row must never block a purge (see test_purge_machine_votes.py), but a
    real invocation should still produce a correct one."""

    def test_dry_run_creates_no_ledger_row(self, db):
        from django.core.management import call_command

        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        call_command("local_identify_printing_tags", "--dry-run", "--engine=ocr", "--limit=5")

        assert not PilotRunLedger.objects.exists()

    def test_real_run_creates_a_completed_ledger_row(self, db, monkeypatch):
        from django.core.management import call_command

        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CardFactory(name="Forest")
        TestCheckpointing._wire_fake_ocr(monkeypatch, printing.pk)

        call_command("local_identify_printing_tags", "--engine=ocr", "--limit=5")

        entry = PilotRunLedger.objects.get(command="local_identify_printing_tags")
        assert entry.status == PilotRunLedger.Status.COMPLETED
        assert entry.finished_at is not None
        assert entry.votes_written == 1
        assert entry.dry_run is False
        vote = CardPrintingTag.objects.get(anonymous_id=OCR_ANONYMOUS_ID)
        assert vote.run_id == entry.run_id

    def test_an_exception_mid_run_leaves_the_ledger_row_failed_not_dangling(self, db, monkeypatch):
        from django.core.management import call_command

        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        import cardpicker.management.commands.local_identify_printing_tags as command_module

        def raising_run_pilot(*args, **kwargs):
            raise RuntimeError("simulated mid-run crash")

        monkeypatch.setattr(command_module, "run_pilot", raising_run_pilot)

        with pytest.raises(RuntimeError):
            call_command("local_identify_printing_tags", "--engine=ocr", "--limit=5")

        entry = PilotRunLedger.objects.get(command="local_identify_printing_tags")
        assert entry.status == PilotRunLedger.Status.FAILED
        assert entry.finished_at is not None

    def test_staleness_refusal_creates_no_ledger_row(self, db, monkeypatch):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        import cardpicker.management.commands.local_identify_printing_tags as command_module

        monkeypatch.setattr(command_module, "find_stale_applied_migrations", lambda: [("cardpicker", "9999_fake")])

        with pytest.raises(CommandError):
            call_command("local_identify_printing_tags", "--engine=ocr", "--limit=5")

        assert not PilotRunLedger.objects.exists()


class TestRunPilotSourceExclusion:
    def test_excluded_sources_cards_never_reach_the_engine(self, db, monkeypatch):
        excluded_source = SourceFactory()
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        excluded_card = CardFactory(name="Forest", source=excluded_source)

        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        results, _attributes = run_pilot(
            engine="ocr",
            limit=10,
            dry_run=False,
            nice=False,
            exclude_source_pks_by_engine={"ocr": [excluded_source.pk]},
        )

        assert results["ocr"].votes_written == 0
        from cardpicker.models import CardPrintingTag

        assert not CardPrintingTag.objects.filter(card=excluded_card).exists()


class TestCheckpointing:
    """Stage 8 pre-scale program item 2: run_pilot must survive a kill mid-run without losing
    everything accumulated since the last flush, matching cardpicker.deductive_backfill's
    periodic-flush precedent (see run_pilot's checkpointing comment for the one deliberate
    deviation - the gate check runs per-flush here, not once at the end)."""

    @staticmethod
    def _wire_fake_ocr(monkeypatch, printing_pk):
        import cardpicker.local_identify_printing_tags as module

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing_pk, confidence=0.85, detail="raw")
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

    def test_flushes_periodically_not_just_once_at_the_end(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        for _ in range(5):
            CardFactory(name="Forest")
        self._wire_fake_ocr(monkeypatch, printing.pk)

        bulk_create_calls: list[int] = []
        original_bulk_create = CardPrintingTag.objects.bulk_create

        def counting_bulk_create(objs, *args, **kwargs):
            objs = list(objs)
            bulk_create_calls.append(len(objs))
            return original_bulk_create(objs, *args, **kwargs)

        monkeypatch.setattr(CardPrintingTag.objects, "bulk_create", counting_bulk_create)

        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False, batch_size=2)

        assert results["ocr"].votes_written == 5
        # 5 cards at batch_size=2: flush after card 2, after card 4, and once more for the
        # trailing single card - three separate writes, not one giant write at the very end.
        assert bulk_create_calls == [2, 2, 1]

    def test_gate_check_runs_per_flush_not_only_at_the_end(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        for _ in range(4):
            CardFactory(name="Forest")
        self._wire_fake_ocr(monkeypatch, printing.pk)

        import cardpicker.local_identify_printing_tags as module

        verify_calls: list[list[int]] = []
        original_verify = module.verify_zero_resolutions

        def counting_verify(card_ids, *args, **kwargs):
            verify_calls.append(list(card_ids))
            return original_verify(card_ids, *args, **kwargs)

        monkeypatch.setattr(module, "verify_zero_resolutions", counting_verify)

        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False, batch_size=2)

        # 4 cards at batch_size=2: two flushes, each with its own gate check - not one call at
        # the very end covering all 4.
        assert len(verify_calls) == 2
        assert all(len(c) == 2 for c in verify_calls)

    def test_resume_after_a_simulated_kill_completes_the_remaining_cards(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        cards = [CardFactory(name="Forest") for _ in range(6)]
        self._wire_fake_ocr(monkeypatch, printing.pk)

        class SimulatedKill(Exception):
            pass

        original_bulk_create = CardPrintingTag.objects.bulk_create
        call_count = {"n": 0}

        def killing_bulk_create(objs, *args, **kwargs):
            call_count["n"] += 1
            result = original_bulk_create(objs, *args, **kwargs)
            if call_count["n"] == 1:
                raise SimulatedKill("process died immediately after the first flush committed")
            return result

        monkeypatch.setattr(CardPrintingTag.objects, "bulk_create", killing_bulk_create)

        with pytest.raises(SimulatedKill):
            run_pilot(engine="ocr", limit=10, dry_run=False, nice=False, batch_size=2)

        # the first flush's 2 cards are durably committed despite the "crash" on the next batch
        assert CardPrintingTag.objects.filter(anonymous_id=OCR_ANONYMOUS_ID).count() == 2

        monkeypatch.setattr(CardPrintingTag.objects, "bulk_create", original_bulk_create)
        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False, batch_size=2)

        assert results["ocr"].votes_written == 4  # the 4 cards the killed run never reached
        final_votes = CardPrintingTag.objects.filter(anonymous_id=OCR_ANONYMOUS_ID)
        assert final_votes.count() == 6
        assert {v.card_id for v in final_votes} == {c.pk for c in cards}


class TestRunIdStamping:
    """docs/features/catalog-completion-plan.md's Part 1: every MACHINE-cast vote from one
    invocation shares a single run_id, and different invocations get different run_ids -
    anonymous_id's own exact-match reuse across invocations is completely untouched (see
    generate_run_id's docstring for why this is a separate field, not a suffix)."""

    def test_every_vote_from_one_run_shares_one_run_id(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        for _ in range(3):
            CardFactory(name="Forest")
        TestCheckpointing._wire_fake_ocr(monkeypatch, printing.pk)

        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 3
        assert results["ocr"].run_id  # non-empty
        votes = list(CardPrintingTag.objects.filter(anonymous_id=OCR_ANONYMOUS_ID))
        assert len(votes) == 3
        run_ids = {v.run_id for v in votes}
        assert run_ids == {results["ocr"].run_id}

    def test_two_invocations_get_distinct_run_ids(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card_a = CardFactory(name="Forest")
        TestCheckpointing._wire_fake_ocr(monkeypatch, printing.pk)

        results_1, _ = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)
        assert results_1["ocr"].votes_written == 1

        # a second card so the second invocation has something new to vote on (the first card
        # is already excluded by this run's own anonymous_id-based idempotence).
        card_b = CardFactory(name="Forest")
        results_2, _ = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)
        assert results_2["ocr"].votes_written == 1

        assert results_1["ocr"].run_id != results_2["ocr"].run_id
        vote_a = CardPrintingTag.objects.get(card=card_a, anonymous_id=OCR_ANONYMOUS_ID)
        vote_b = CardPrintingTag.objects.get(card=card_b, anonymous_id=OCR_ANONYMOUS_ID)
        assert vote_a.run_id == results_1["ocr"].run_id
        assert vote_b.run_id == results_2["ocr"].run_id

    def test_an_explicit_run_id_is_respected_not_regenerated(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CardFactory(name="Forest")
        TestCheckpointing._wire_fake_ocr(monkeypatch, printing.pk)

        results, _ = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False, run_id="explicit-test-run-id")

        assert results["ocr"].run_id == "explicit-test-run-id"
        vote = CardPrintingTag.objects.get(anonymous_id=OCR_ANONYMOUS_ID)
        assert vote.run_id == "explicit-test-run-id"

    def test_name_frequency_elimination_gets_its_own_run_id(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        CardFactory(name="Forest")

        result = run_name_frequency_elimination()

        assert result.votes_written == 1
        assert result.run_id
        vote = CardPrintingTag.objects.get(anonymous_id=NAME_FREQUENCY_ANONYMOUS_ID)
        assert vote.printing_id == printing.pk
        assert vote.run_id == result.run_id

    def test_human_submitted_votes_are_never_stamped(self, db):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")
        human_vote = CardPrintingTagFactory(card=card, printing=printing, source=VoteSource.USER)

        assert human_vote.run_id is None


class TestFetchDpi:
    """Item 6/3c's empirically-validated resolution floor - see local_identify_printing_tags'
    DEFAULT_FETCH_DPI comment for the measured yield numbers behind the default."""

    def test_default_dpi_is_included_in_the_url(self, db):
        card = CardFactory()
        url = get_worker_image_url(card)
        assert url is not None
        assert "dpi=250" in url

    def test_explicit_dpi_overrides_the_default(self, db):
        card = CardFactory()
        url = get_worker_image_url(card, dpi=200)
        assert url is not None
        assert "dpi=200" in url

    def test_none_dpi_omits_the_param_for_native_resolution(self, db):
        card = CardFactory()
        url = get_worker_image_url(card, dpi=None)
        assert url is not None
        assert "dpi=" not in url


class TestFetchBudget:
    """Stage 8 pre-scale program item 3b: every image fetch is one request against the shared
    image CDN Worker quota - an unattended run must be boundable. Cards past the budget must be
    left completely untouched (no vote/outcome), not skipped-and-recorded, so the next
    invocation's ordinary idempotent selection just picks them up."""

    def test_stops_after_the_budget_and_leaves_the_rest_untouched(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        cards = [CardFactory(name="Forest") for _ in range(5)]
        TestCheckpointing._wire_fake_ocr(monkeypatch, printing.pk)

        # batch_size=3 matches fetch_budget=3 deliberately (pre-scale program item 3d): the
        # budget is now checked BETWEEN chunks, not per-card - a chunk already in flight always
        # completes (see run_pilot's own comment on this), so the real bound on overshoot is one
        # chunk's worth. Aligning the two here keeps this test's exact-count assertions valid;
        # a batch_size that DIDN'T divide evenly would still stop correctly, just with the
        # (already-documented, already-accepted) chunk-sized overshoot instead of an exact cut.
        results, _attributes = run_pilot(
            engine="ocr", limit=10, dry_run=False, nice=False, fetch_budget=3, batch_size=3, workers=1
        )

        assert results["ocr"].votes_written == 3
        assert results["ocr"].fetch_budget_exhausted is True
        assert results["ocr"].cards_not_attempted_this_invocation == 2

        # the 2 untouched cards have no vote at all - a follow-up invocation with no budget
        # limit picks them up via the ordinary idempotent selection, no special handling needed
        remaining = select_candidates("ocr")
        assert len(remaining) == 2
        results_2, _ = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)
        assert results_2["ocr"].votes_written == 2
        assert CardPrintingTag.objects.filter(anonymous_id=OCR_ANONYMOUS_ID).count() == 5
        assert {c.pk for c in cards} == {
            t.card_id for t in CardPrintingTag.objects.filter(anonymous_id=OCR_ANONYMOUS_ID)
        }

    def test_no_budget_means_no_limit(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        for _ in range(4):
            CardFactory(name="Forest")
        TestCheckpointing._wire_fake_ocr(monkeypatch, printing.pk)

        results, _attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False, fetch_budget=None)

        assert results["ocr"].votes_written == 4
        assert results["ocr"].fetch_budget_exhausted is False
        assert results["ocr"].cards_not_attempted_this_invocation == 0


class TestIdempotence:
    def test_a_card_voted_on_is_excluded_from_the_next_selection(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module

        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            ),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)
        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        # re-running the exact same selection now excludes this card - it already has a vote
        # under OCR_ANONYMOUS_ID
        assert select_candidates("ocr") == []


class TestScanLog:
    """Part 3 addendum item 3 (docs/features/catalog-completion-plan.md, upgraded from
    propose-to-hold to build 2026-07-16): abstention evidence persists exactly like assent
    evidence - a CardScanLog row per (card, anonymous_id) an engine looked at and abstained on,
    consumed by the same exclusion pattern votes already use."""

    def test_a_skipped_card_gets_a_scan_log_row_and_is_excluded_next_time(self, db, monkeypatch):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        import cardpicker.local_identify_printing_tags as module

        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult(skip_reason="no-text"),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        assert select_candidates("ocr") != []  # eligible before this run
        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        rows = list(CardScanLog.objects.filter(card=card))
        assert len(rows) == 1
        assert rows[0].anonymous_id == OCR_ANONYMOUS_ID
        assert rows[0].skip_reason == "no-text"
        assert select_candidates("ocr") == []  # excluded now, same as a vote would exclude it

    def test_a_voted_card_gets_no_scan_log_row(self, db, monkeypatch):
        # "voted cards need no row (the vote IS the record)" - CardPrintingTag alone must be
        # sufficient for exclusion; a scan-log row would be redundant bookkeeping.
        printing = CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest")
        import cardpicker.local_identify_printing_tags as module

        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            ),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)
        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert CardScanLog.objects.count() == 0

    def test_rescannable_skip_reasons_stay_eligible_next_time(self, db, monkeypatch):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        import cardpicker.local_identify_printing_tags as module

        assert "unfetchable-image" in RESCANNABLE_SKIP_REASONS
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)  # -> unfetchable-image
        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        row = CardScanLog.objects.get(card=card)
        assert row.skip_reason == "unfetchable-image"
        # still eligible - a transient fetch failure isn't a conclusion about the card
        selected = select_candidates("ocr")
        assert [s.card.pk for s in selected] == [card.pk]

    def test_a_later_non_rescannable_reason_overrides_an_earlier_rescannable_one(self, db, monkeypatch):
        # the resume query re-evaluates ALL of a card's scan-log rows for this anonymous_id
        # every time, not just the first - a card that abstained transiently once and then
        # abstained for a REAL reason later must end up excluded, regardless of which happened
        # first. This is the "order doesn't matter, latest conclusive state wins" property.
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        import cardpicker.local_identify_printing_tags as module

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)
        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)  # -> unfetchable-image, rescannable
        assert select_candidates("ocr") != []

        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult(skip_reason="no-text"),
        )
        # image now "fetches" (a real tiny image - classify_bleed_edge needs .size, not a bare
        # object) - this also makes fallback newly eligible to run (it requires image is not
        # None), so it gets its OWN scan-log row too; scoping the assertion to OCR_ANONYMOUS_ID
        # is what this test is actually about, not fallback's independent behavior.
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (10, 10)))
        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)  # -> no-text, NOT rescannable

        ocr_rows = CardScanLog.objects.filter(card=card, anonymous_id=OCR_ANONYMOUS_ID)
        assert ocr_rows.count() == 2
        assert {r.skip_reason for r in ocr_rows} == {"unfetchable-image", "no-text"}
        assert select_candidates("ocr") == []

    def test_kill_mid_run_then_restart_only_rescans_the_rescannable_set(self, db, monkeypatch):
        # the explicit restart-resume proof: a run processes several cards with a mix of
        # outcomes (vote, non-rescannable skip, rescannable skip), a restart happens, and only
        # the rescannable-skip card is genuinely re-fetched - zero re-fetches for everything else.
        printing = CanonicalCardFactory(name="Forest")
        voted_card = CardFactory(name="Forest")
        skipped_card = CardFactory(name="Forest")
        rescannable_card = CardFactory(name="Forest")
        import cardpicker.local_identify_printing_tags as module

        fetch_calls: dict[int, int] = collections.defaultdict(int)

        def counting_fetch(card: object, dpi: object = None) -> object:
            fetch_calls[card.pk] += 1  # type: ignore[attr-defined]
            if card.pk == rescannable_card.pk:  # type: ignore[attr-defined]
                return None  # unfetchable-image every time - genuinely transient
            return Image.new("RGB", (10, 10))  # real image - run_ocr_for_card below is also monkeypatched

        def per_card_ocr_result(selected: object, image: object, crop_box: object, bleed_class: object = None):
            card_id = selected.card.pk  # type: ignore[attr-defined]
            if card_id == voted_card.pk:
                return module.OcrCardResult(
                    vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
                )
            if card_id == skipped_card.pk:
                return module.OcrCardResult(skip_reason="no-text")
            return module.OcrCardResult(skip_reason="unfetchable-image")  # unreached for rescannable_card

        monkeypatch.setattr(module, "fetch_card_image", counting_fetch)
        monkeypatch.setattr(module, "run_ocr_for_card", per_card_ocr_result)

        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)  # "kill" = just one invocation

        assert fetch_calls[voted_card.pk] == 1
        assert fetch_calls[skipped_card.pk] == 1
        assert fetch_calls[rescannable_card.pk] == 1

        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)  # "restart"

        # zero re-fetches for the voted and non-rescannable-skipped cards - still exactly 1 each
        assert fetch_calls[voted_card.pk] == 1
        assert fetch_calls[skipped_card.pk] == 1
        # the rescannable card is genuinely re-fetched - this is the point of leaving it eligible
        assert fetch_calls[rescannable_card.pk] == 2


class TestAbstentionAwareOrdering:
    """Part 3 addendum, abstention-aware ordering (2026-07-17): task #109's coverage-gap-ordering
    finding upgraded from a static heuristic to an evidence-based one - demote (not exclude)
    names with a proven all-time abstention record to the back of the queue."""

    @staticmethod
    def _scan_log_row(card: object, anonymous_id: str) -> None:
        from cardpicker.models import CardScanLog

        CardScanLog.objects.create(card=card, anonymous_id=anonymous_id, skip_reason="no-text")

    def test_qualification_boundary_four_attempts_not_hard(self, db):
        from cardpicker.local_identify_printing_tags import (
            HARD_NAME_MIN_ATTEMPTS,
            _compute_hard_names,
        )

        assert HARD_NAME_MIN_ATTEMPTS == 5
        for _ in range(4):
            self._scan_log_row(CardFactory(name="Forest"), OCR_ANONYMOUS_ID)
        assert "Forest" not in _compute_hard_names(OCR_ANONYMOUS_ID)

    def test_qualification_boundary_five_attempts_is_hard(self, db):
        from cardpicker.local_identify_printing_tags import _compute_hard_names

        for _ in range(5):
            self._scan_log_row(CardFactory(name="Forest"), OCR_ANONYMOUS_ID)
        assert "Forest" in _compute_hard_names(OCR_ANONYMOUS_ID)

    def test_one_vote_disqualifies_regardless_of_attempt_count(self, db):
        from cardpicker.local_identify_printing_tags import _compute_hard_names

        printing = CanonicalCardFactory(name="Forest")
        for _ in range(9):
            self._scan_log_row(CardFactory(name="Forest"), OCR_ANONYMOUS_ID)
        voted_card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=voted_card, anonymous_id=OCR_ANONYMOUS_ID, printing=printing, source=VoteSource.OCR)

        assert "Forest" not in _compute_hard_names(OCR_ANONYMOUS_ID)

    def test_internal_sort_stability_among_demoted_names(self, db):
        # demoted entries must still respect the REST of the ordering key among themselves
        # (uncovered count, demand rank, candidate count, pk) - being demoted to the back is a
        # leading tuple dimension prepended to the existing key, not a replacement for it.
        # Computed directly against _coverage_priority_key with controlled inputs (equal
        # uncovered/demand-rank tiers so candidate-count is the actual deciding element) rather
        # than through a real DB-backed queue, which would let element (2) - uncovered count -
        # dominate before candidate count ever gets consulted, and prove nothing about (4).
        from cardpicker.local_identify_printing_tags import (
            CandidatePrinting,
            SelectedCard,
            _coverage_priority_key,
        )

        forest_card = CardFactory(name="Forest")
        island_card = CardFactory(name="Island")
        # both hard; both single-candidate, same demand rank (None) - only pk would differ, so
        # sort by (fewer-candidates-first) is already tied; add a second Forest candidate to make
        # candidate count the actual deciding element, with an equal uncovered count via covered=0
        # for both (nothing covered - simplest way to keep element (2) tied at "-1" for both).
        forest_selected = SelectedCard(
            card=forest_card, candidates=[CandidatePrinting(pk=1, expansion_code="a", collector_number="1")]
        )
        island_selected = SelectedCard(
            card=island_card, candidates=[CandidatePrinting(pk=2, expansion_code="a", collector_number="1")]
        )
        hard_names = frozenset({"Forest", "Island"})
        key_forest = _coverage_priority_key(forest_selected, covered_printing_pks=set(), hard_names=hard_names)
        key_island = _coverage_priority_key(island_selected, covered_printing_pks=set(), hard_names=hard_names)

        assert key_forest[0] == key_island[0] == 1  # both demoted (tier 1)
        # with everything else tied, pk (element 5) breaks the tie - proves the demoted tier's
        # OWN internal ordering still falls through to the rest of the key correctly, not just
        # "some order, who cares" - a genuinely scrambled implementation could return either
        # order regardless of pk, which this pins down.
        ordered = sorted([key_forest, key_island])
        assert ordered == [key_forest, key_island] if forest_card.pk < island_card.pk else [key_island, key_forest]

    def test_reactivation_on_first_vote(self, db):
        from cardpicker.local_identify_printing_tags import _compute_hard_names

        printing = CanonicalCardFactory(name="Forest")
        for _ in range(6):
            self._scan_log_row(CardFactory(name="Forest"), OCR_ANONYMOUS_ID)
        assert "Forest" in _compute_hard_names(OCR_ANONYMOUS_ID)

        voted_card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=voted_card, anonymous_id=OCR_ANONYMOUS_ID, printing=printing, source=VoteSource.OCR)

        # immediately re-qualified on the very next computation - no restart, no delay
        assert "Forest" not in _compute_hard_names(OCR_ANONYMOUS_ID)

    def test_demotion_counts_logged_at_queue_build(self, db, capsys):
        from cardpicker.local_identify_printing_tags import select_candidates

        CanonicalCardFactory(name="Forest")
        for _ in range(5):
            self._scan_log_row(CardFactory(name="Forest"), OCR_ANONYMOUS_ID)
        CardFactory(name="Forest")

        select_candidates("ocr")

        captured = capsys.readouterr()
        assert "abstention-aware ordering" in captured.out
        assert "1 names / 1 candidates demoted" in captured.out


class TestVerifyZeroResolutions:
    def test_no_violations_when_nothing_resolves(self, db):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest", printing_tag_status=PrintingTagStatus.UNRESOLVED)
        CardPrintingTagFactory(card=card, anonymous_id=OCR_ANONYMOUS_ID, printing=printing, source=VoteSource.OCR)
        assert verify_zero_resolutions([card.pk]) == []

    def test_detects_a_violation(self, db, monkeypatch):
        card = CardFactory(printing_tag_status=PrintingTagStatus.UNRESOLVED)

        # verify_zero_resolutions imports resolve_printing locally inside the function body,
        # so patching cardpicker.printing_consensus.resolve_printing (the module it imports
        # from) before calling it is what a fresh local import picks up.
        import cardpicker.printing_consensus as consensus_module

        monkeypatch.setattr(consensus_module, "resolve_printing", lambda c: "NO_MATCH")
        assert verify_zero_resolutions([card.pk]) == [card.pk]


def _black_bordered_image_with_artist_text(artist_name: str) -> Image:
    # 750x1020 (ratio ~0.7353) is deliberately a clean "bleed" shape (BLEED_ASPECT_RATIO
    # ~0.7350, distance 0.0003) rather than the original 750x1050 (ratio 0.7143), which landed
    # just inside classify_bleed_edge's "trimmed" bucket by accident - that silently triggered
    # local_fallback.normalize_crop_box's trimmed-image remap on ARTIST_CROP_BOX/
    # _BORDER_SAMPLE_BANDS, shifting them away from where this synthetic image actually draws
    # its content. This test is about fallback wiring, not bleed-remap correctness (that's
    # covered separately in test_local_fallback.py) - matching the real-world majority shape
    # keeps normalize_crop_box a no-op here, same as it is for ~97.5% of real images.
    img = Image.new("RGB", (750, 1020), (5, 5, 5))
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, 690, 960], fill=(120, 80, 200))
    draw.text((150, 960), f"Illus. {artist_name}", fill=(255, 255, 255))
    return img


class TestPass2Wiring:
    """Integration coverage for the pass-2 fallback wiring inside run_pilot itself (not just
    local_fallback's own unit tests) - pass 1 mocked to always miss, local_fallback's real
    logic runs against a real (synthetic) image."""

    def test_fallback_fires_and_votes_when_pass_1_misses_entirely(self, db, monkeypatch):
        printing = CanonicalCardFactory(
            name="Forest",
            expansion=CanonicalExpansionFactory(code="aaa"),
            artist=CanonicalArtistFactory(name="Marie Magny"),
        )
        # frame="1993" (old-border class) - the fake image below carries an "Illus. <artist>"
        # credit, which the frame classifier reads as old-border; the printing's own frame must
        # agree, or the CONSISTENCY CHECK correctly withholds the vote as a frame-mismatch (see
        # TestPass2Wiring::test_frame_mismatch_withholds_the_printing_vote below for that path).
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="black", frame="1993")
        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        card = CardFactory(name="Forest")
        TagFactory(name="Black Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - the fake image below has "Illus. Marie Magny" drawn
        # on it, but the crop/OCR fallback inside detect_illus_anchor() must not depend on the
        # real binary reading it accurately; this mirrors what it would extract.
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "Illus. Marie Magny")
        monkeypatch.setattr(
            module, "run_ocr_for_card", lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult()
        )
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "no-clear-winner"),
        )
        monkeypatch.setattr(
            module, "fetch_card_image", lambda card, dpi=None: _black_bordered_image_with_artist_text("Marie Magny")
        )

        # workers=1: this test exercises REAL (unmocked) run_fallback_for_card, which queries
        # CanonicalCard/CanonicalPrintingMetadata/CanonicalArtist - under workers>1 those queries
        # run on a worker thread's own DB connection, which can't see this test's fixture data
        # under pytest-django's default (non-transactional) `db` fixture (only the original
        # connection sees an uncommitted test transaction). Concurrency correctness itself is
        # covered separately (TestConcurrency, using transactional_db) - this test is about
        # fallback wiring, not concurrency, so it stays on the simple single-threaded path.
        results, attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False, workers=1)

        assert results["fallback"].votes_written == 1
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=FALLBACK_ANONYMOUS_ID, printing=printing).exists()
        assert attributes.border_votes_by_class["black"] == 1
        assert CardTagVote.objects.filter(
            card=card, anonymous_id=FALLBACK_ANONYMOUS_ID, tag__name="Black Border"
        ).exists()

    def test_frame_mismatch_withholds_the_printing_vote(self, db, monkeypatch):
        # OCR "succeeds" (a modern-frame signal: a collector number was parsed), but the
        # matched printing's own frame is old-border (1993) - contradiction, so the vote must
        # be withheld even though pass 1 nominally produced one.
        printing = CanonicalCardFactory(name="Forest")
        CanonicalPrintingMetadataFactory(canonical_card=printing, frame="1993")
        card = CardFactory(name="Forest")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - the fetched image is blank (no text at all), so a
        # real tesseract read would also find nothing, but the frame classifier's unconditional
        # detect_illus_anchor() call must not depend on the real binary being present to do so.
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(
                    engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="158/281 R MOM EN"
                ),
                parsed_a_collector_number=True,
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 0
        assert results["ocr"].skip_counts["frame-mismatch"] == 1
        assert not CardPrintingTag.objects.filter(card=card).exists()
        assert len(attributes.frame_mismatches) == 1
        assert attributes.frame_mismatches[0]["card_id"] == card.pk

    def test_already_fallback_covered_card_is_not_reattempted(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        CardPrintingTagFactory(card=card, printing=printing, anonymous_id=FALLBACK_ANONYMOUS_ID)

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - see the identical note on the sibling test above
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fail_if_called(selected, image, ocr_raw_texts):
            raise AssertionError("run_fallback_for_card must not run again for an already-covered card")

        monkeypatch.setattr(module.local_fallback, "run_fallback_for_card", fail_if_called)
        monkeypatch.setattr(
            module, "run_ocr_for_card", lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult()
        )
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "no-clear-winner"),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (750, 1050), (5, 5, 5)))

        # if the assertion inside fail_if_called had fired, this call itself would raise
        run_pilot(engine="both", limit=10, dry_run=False, nice=False)


class TestGroundTruthAttributeVotes:
    """When a printing is confirmed for a card this run, border/frame attribute votes prefer
    ground truth from that printing's own CanonicalPrintingMetadata over the pixel/OCR
    heuristic estimate - see run_pilot's ground-truth-preferred wiring, docs/features/
    printing-tags.md's Stage 8 section."""

    def test_ground_truth_overrides_heuristic_when_printing_confirmed(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest")
        CanonicalPrintingMetadataFactory(canonical_card=printing, border_color="white", frame="2015")
        card = CardFactory(name="Forest")
        TagFactory(name="White Border")
        TagFactory(name="Black Border")
        TagFactory(name="Modern Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - the fetched image is blank, so this matches what a
        # real read would find anyway; see the identical note on TestPass2Wiring above.
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(
                    engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="158/281 R MOM EN"
                ),
                parsed_a_collector_number=True,
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        # a uniform near-black image - the pixel-sample heuristic would read "black" here, but
        # the matched printing's own metadata says "white" and must win instead.
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 1
        assert attributes.border_votes_by_class == {"white": 1}
        assert attributes.border_ground_truth_count == 1
        assert CardTagVote.objects.filter(card=card, tag__name="White Border").exists()
        assert not CardTagVote.objects.filter(card=card, tag__name="Black Border").exists()

        # frame: the heuristic (parsed_a_collector_number=True) already reads "modern", which
        # happens to agree with the printing's own frame="2015" -> "modern" - still sourced
        # from (and counted as) ground truth, since that's genuinely where the cast value came
        # from this run.
        assert attributes.frame_votes_by_class == {"modern": 1}
        assert attributes.frame_ground_truth_count == 1
        assert CardTagVote.objects.filter(card=card, tag__name="Modern Border").exists()

    def test_heuristic_used_when_no_printing_confirmed_this_run(self, db, monkeypatch):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        TagFactory(name="Black Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - see the identical note on the sibling test above
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        monkeypatch.setattr(
            module, "run_ocr_for_card", lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult()
        )
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "no-clear-winner"),
        )
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert attributes.border_votes_by_class == {"black": 1}
        assert attributes.border_ground_truth_count == 0
        assert CardTagVote.objects.filter(card=card, tag__name="Black Border").exists()

    def test_heuristic_used_when_confirmed_printing_has_no_usable_metadata(self, db, monkeypatch):
        # a printing that matches but has no CanonicalPrintingMetadata row at all (predates the
        # metadata import - see cardpicker.local_identify_printing_tags module docstring's
        # sibling deductive_backfill's identical nullable-metadata handling)
        printing = CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        TagFactory(name="Black Border")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        # no real tesseract binary in CI - see the identical note on the sibling test above
        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")

        def fake_ocr(selected, image, crop_box, bleed_class=None):
            return module.OcrCardResult(
                vote=module.EngineVote(
                    engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="158/281 R MOM EN"
                ),
                parsed_a_collector_number=True,
            )

        monkeypatch.setattr(module, "run_ocr_for_card", fake_ocr)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (750, 1050), (5, 5, 5)))

        results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 1
        assert attributes.border_votes_by_class == {"black": 1}
        assert attributes.border_ground_truth_count == 0
        assert CardTagVote.objects.filter(card=card, tag__name="Black Border").exists()


class TestBleedEdgeVotesEndToEnd:
    """Addendum item 7 + consolidated respec item 4b (2026-07-16, negative-only): run_pilot casts
    a vote on the pre-existing appropriate-bleed tag ONLY for a 'trimmed' reading. A 'bleed'
    reading (the ~97.5% common case) still counts toward the census (bleed_votes_by_class) but
    writes NO vote at all - absence of any vote is the documented convention for "presumed
    normal bleed", per sensitive_tags.py's SENSITIVE_TAGS comment."""

    def test_bleed_shaped_image_is_censused_but_casts_no_vote(self, db, monkeypatch):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        TagFactory(name="appropriate-bleed")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")
        monkeypatch.setattr(
            module, "run_ocr_for_card", lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult()
        )
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "too-many-candidates"),
        )
        # 735/1000 ~= BLEED_ASPECT_RATIO
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (735, 1000), (5, 5, 5)))

        _results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        # census still reflects the classification...
        assert attributes.bleed_votes_by_class == {"bleed": 1}
        # ...but no vote was actually written - absence IS the signal for this case.
        assert not CardTagVote.objects.filter(card=card, tag__name="appropriate-bleed").exists()

    def test_trimmed_shaped_image_casts_a_negative_vote(self, db, monkeypatch):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        TagFactory(name="appropriate-bleed")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")
        monkeypatch.setattr(
            module, "run_ocr_for_card", lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult()
        )
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "too-many-candidates"),
        )
        # 716/1000 ~= TRIM_ASPECT_RATIO
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (716, 1000), (5, 5, 5)))

        _results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert attributes.bleed_votes_by_class == {"trimmed": 1}
        vote = CardTagVote.objects.get(card=card, tag__name="appropriate-bleed")
        assert vote.polarity == VotePolarity.NOT_APPLICABLE

    def test_ambiguous_ratio_abstains_without_writing_anything(self, db, monkeypatch):
        CanonicalCardFactory(name="Forest")
        card = CardFactory(name="Forest")
        TagFactory(name="appropriate-bleed")

        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_ocr as local_ocr_module

        monkeypatch.setattr(local_ocr_module, "run_tesseract", lambda image: "")
        monkeypatch.setattr(
            module, "run_ocr_for_card", lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult()
        )
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "too-many-candidates"),
        )
        monkeypatch.setattr(
            module, "fetch_card_image", lambda card, dpi=None: Image.new("RGB", (1000, 1000), (5, 5, 5))
        )

        _results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert attributes.bleed_votes_by_class == {}
        assert attributes.bleed_abstain_count == 1
        assert not CardTagVote.objects.filter(card=card, tag__name="appropriate-bleed").exists()


class TestConcurrency:
    """Pre-scale program item 3d (2026-07-15): the per-card fetch+OCR+phash+fallback compute
    work now runs across `workers` concurrent threads, feeding the same single-threaded
    DB-write loop as before. `transactional_db` (real commits, TRUNCATE-based cleanup), not the
    default rollback-wrapped `db` fixture - a real regression was caught writing these tests:
    `run_phash_for_card`'s own `CanonicalCard.objects.filter(...)` query, running on a worker
    thread's own DB connection, silently found nothing under `db` because that connection can't
    see `db`'s uncommitted wrapping transaction - exact same rationale as
    test_sources.py's `test_all_sources_scanned_concurrently_local_file` for
    `update_database()`'s own worker threads."""

    def test_workers_greater_than_one_still_finds_a_real_phash_match(self, transactional_db, monkeypatch):
        # deliberately does NOT mock run_phash_for_card itself - the whole point is exercising
        # its real CanonicalCard query from inside a worker thread. Only the network-dependent
        # half (Scryfall art_crop fetch/hash) is mocked, pinned to exactly what the real
        # compute_card_art_hash(card_image) will produce, guaranteeing a distance=0 match.
        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_phash as phash_module

        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card = CardFactory(name="Forest")

        card_image = Image.new("RGB", (750, 1050), (5, 5, 5))
        pinned_hash = phash_module.compute_card_art_hash(card_image)

        monkeypatch.setattr(phash_module, "get_or_compute_canonical_hash", lambda canonical: pinned_hash)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: card_image)

        results, _attributes = run_pilot(engine="phash", limit=10, dry_run=False, nice=False, workers=2)

        assert results["phash"].votes_written == 1
        assert CardPrintingTag.objects.filter(card=card, anonymous_id=PHASH_ANONYMOUS_ID, printing=printing).exists()

    def test_workers_one_and_workers_two_agree_on_the_same_real_input(self, transactional_db, monkeypatch):
        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_phash as phash_module

        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        cards = [CardFactory(name="Forest") for _ in range(6)]

        card_image = Image.new("RGB", (750, 1050), (5, 5, 5))
        pinned_hash = phash_module.compute_card_art_hash(card_image)
        monkeypatch.setattr(phash_module, "get_or_compute_canonical_hash", lambda canonical: pinned_hash)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: card_image)

        results_seq, _ = run_pilot(engine="phash", limit=10, dry_run=True, nice=False, workers=1)

        for c in cards:
            c.refresh_from_db()
        results_conc, _ = run_pilot(engine="phash", limit=10, dry_run=True, nice=False, workers=4, batch_size=2)

        assert results_seq["phash"].votes_written == results_conc["phash"].votes_written == 6

    def test_thread_pool_is_created_once_for_the_whole_run_not_per_chunk(self, transactional_db, monkeypatch):
        # bug fix (2026-07-16): the pool used to be created fresh inside the chunk loop, which -
        # because Django DB connections are thread-local and nothing closes a connection when
        # its owning thread is torn down - leaked one Postgres connection per worker per chunk
        # and crashed a live full-catalog run with "sorry, too many clients already" within
        # minutes. Reusing one pool for the whole run means each worker thread (and its DB
        # connection) is created at most once, regardless of chunk count.
        import cardpicker.local_identify_printing_tags as module
        import cardpicker.local_phash as phash_module

        CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        for _ in range(9):
            CardFactory(name="Forest")

        card_image = Image.new("RGB", (750, 1050), (5, 5, 5))
        pinned_hash = phash_module.compute_card_art_hash(card_image)
        monkeypatch.setattr(phash_module, "get_or_compute_canonical_hash", lambda canonical: pinned_hash)
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: card_image)

        construction_count = 0
        real_executor_cls = module.ThreadPoolExecutor

        class CountingThreadPoolExecutor(real_executor_cls):
            def __init__(self, *args, **kwargs):
                nonlocal construction_count
                construction_count += 1
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(module, "ThreadPoolExecutor", CountingThreadPoolExecutor)

        # 9 cards / batch_size=3 = 3 chunks - a pre-fix run would construct the pool 3 times.
        results, _ = run_pilot(engine="phash", limit=10, dry_run=True, nice=False, workers=3, batch_size=3)

        assert results["phash"].votes_written == 9  # sanity: real work actually flowed through all 3 chunks
        assert construction_count == 1

    def test_omp_thread_limit_is_set_when_running_concurrently(self, db, monkeypatch):
        monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
        import cardpicker.local_identify_printing_tags as module

        monkeypatch.setattr(module, "select_candidates", lambda *args, **kwargs: [])

        run_pilot(engine="ocr", limit=10, dry_run=True, nice=False, workers=3)

        assert os.environ.get("OMP_THREAD_LIMIT") == "1"

    def test_workers_one_does_not_set_omp_thread_limit(self, db, monkeypatch):
        monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
        import cardpicker.local_identify_printing_tags as module

        monkeypatch.setattr(module, "select_candidates", lambda *args, **kwargs: [])

        run_pilot(engine="ocr", limit=10, dry_run=True, nice=False, workers=1)

        assert "OMP_THREAD_LIMIT" not in os.environ


class TestClusterDedup:
    """Addendum item 2a (2026-07-15) -> superseded 2026-07-16 (docs/features/printing-tags.md's
    hash-at-ingest architecture): distance-0/distance<=2 clustering over Card.content_phash - a
    stored-hash DB read, not a live fetch. See cardpicker.local_clustering's module docstring
    for the full d=0 (vote propagation) / d<=2 (narrowing prior, never wired below - out of
    scope this pass, see docs) semantics. Cards without content_phash set cluster as
    singletons - CardFactory defaults content_phash to None, so most tests below set it
    explicitly via CardFactory(content_phash=...) to opt into clustering."""

    def test_two_cards_with_identical_hash_cluster_with_lower_pk_as_representative(self, db):
        CanonicalCardFactory(name="Forest")
        card_a = CardFactory(name="Forest", content_phash=123)
        card_b = CardFactory(name="Forest", content_phash=123)
        assert card_a.pk < card_b.pk

        selected = select_candidates("ocr")
        assert {s.card.pk for s in selected} == {card_a.pk, card_b.pk}

        cluster_result = compute_two_threshold_clusters(selected)

        assert cluster_result.members_by_representative == {card_a.pk: [card_b.pk]}

    def test_different_hashes_do_not_cluster(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", content_phash=123)
        CardFactory(name="Forest", content_phash=456)

        cluster_result = compute_two_threshold_clusters(select_candidates("ocr"))

        assert cluster_result.members_by_representative == {}

    def test_unhashed_card_stays_a_singleton(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", content_phash=None)

        cluster_result = compute_two_threshold_clusters(select_candidates("ocr"))

        assert cluster_result.members_by_representative == {}
        assert cluster_result.near_duplicate_ids_by_card_id == {}

    def test_near_duplicate_within_threshold_is_hinted_but_not_clustered_for_propagation(self, db):
        # distance 1 (one bit flipped) - within NEAR_DUPLICATE_MAX_DISTANCE, but NOT distance 0,
        # so it must show up as a narrowing hint, never as a vote-propagation cluster member.
        CanonicalCardFactory(name="Forest")
        card_a = CardFactory(name="Forest", content_phash=0b0000)
        card_b = CardFactory(name="Forest", content_phash=0b0001)
        assert bin(card_a.content_phash ^ card_b.content_phash).count("1") == 1
        assert 1 <= NEAR_DUPLICATE_MAX_DISTANCE

        cluster_result = compute_two_threshold_clusters(select_candidates("ocr"))

        assert cluster_result.members_by_representative == {}
        assert cluster_result.near_duplicate_ids_by_card_id == {
            card_a.pk: {card_b.pk},
            card_b.pk: {card_a.pk},
        }

    def test_beyond_threshold_hash_produces_no_hint_either(self, db):
        CanonicalCardFactory(name="Forest")
        CardFactory(name="Forest", content_phash=0b0000)
        # 3 bits flipped - beyond NEAR_DUPLICATE_MAX_DISTANCE (2).
        CardFactory(name="Forest", content_phash=0b0111)

        cluster_result = compute_two_threshold_clusters(select_candidates("ocr"))

        assert cluster_result.members_by_representative == {}
        assert cluster_result.near_duplicate_ids_by_card_id == {}

    def test_accepted_vote_on_representative_propagates_to_absorbed_member(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card_a = CardFactory(name="Forest", content_phash=123)
        card_b = CardFactory(name="Forest", content_phash=123)

        import cardpicker.local_identify_printing_tags as module

        identical_image = Image.new("RGB", (750, 1050), (5, 5, 5))
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: identical_image)
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            ),
        )

        results, attributes = run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        # one real OCR call, one propagated vote - both cards end up with an identical vote.
        assert results["ocr"].votes_written == 2
        assert attributes.cluster_count == 1
        assert attributes.cards_absorbed_into_clusters == 1
        vote_a = CardPrintingTag.objects.get(card=card_a, anonymous_id=OCR_ANONYMOUS_ID)
        vote_b = CardPrintingTag.objects.get(card=card_b, anonymous_id=OCR_ANONYMOUS_ID)
        # not just "some vote exists" - the propagated vote is a genuine copy: same printing,
        # same anonymous_id, same confidence, same source as the representative's real vote.
        assert vote_a.printing_id == vote_b.printing_id == printing.pk
        assert vote_a.anonymous_id == vote_b.anonymous_id == OCR_ANONYMOUS_ID
        assert vote_a.confidence == vote_b.confidence == 0.85
        assert vote_a.source == vote_b.source == VoteSource.OCR
        assert vote_a.is_no_match == vote_b.is_no_match is False

    def test_member_with_an_existing_vote_from_a_prior_run_is_not_double_voted_or_overwritten(self, db, monkeypatch):
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        other_printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="bbb"))
        CardFactory(name="Forest", content_phash=123)
        card_b = CardFactory(name="Forest", content_phash=123)
        # card_b already has its OWN OCR vote from a prior run, on a DIFFERENT printing than
        # what card_a (the representative) is about to vote for this run - simulates the exact
        # scenario that would violate the (card, printing, anonymous_id) uniqueness constraint
        # (or silently create a second conflicting OCR vote) if propagation didn't guard it.
        existing_vote = CardPrintingTagFactory(
            card=card_b, printing=other_printing, anonymous_id=OCR_ANONYMOUS_ID, source=VoteSource.OCR
        )

        import cardpicker.local_identify_printing_tags as module

        identical_image = Image.new("RGB", (750, 1050), (5, 5, 5))
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: identical_image)
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            ),
        )
        # card_b is already excluded from OCR selection (existing vote), so it only reaches
        # all_selected_by_card_id (and thus clustering) via an independent phash eligibility.
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "no-clear-winner"),
        )

        results, _attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        # exactly one OCR vote written this run (card_a's real vote) - propagation to card_b was
        # correctly skipped, not attempted and silently failed.
        assert results["ocr"].votes_written == 1
        assert CardPrintingTag.objects.filter(card=card_b, anonymous_id=OCR_ANONYMOUS_ID).count() == 1
        untouched_vote = CardPrintingTag.objects.get(card=card_b, anonymous_id=OCR_ANONYMOUS_ID)
        assert untouched_vote.pk == existing_vote.pk
        assert untouched_vote.printing_id == other_printing.pk  # unchanged, not overwritten

    def test_absorbed_member_never_reaches_ocr_or_phash_processing(self, db, monkeypatch):
        # the whole point of dedup is not re-running the expensive engines on cluster members -
        # this is the test that actually proves the efficiency win, not just vote correctness.
        CanonicalCardFactory(name="Forest")
        card_a = CardFactory(name="Forest", content_phash=123)
        card_b = CardFactory(name="Forest", content_phash=123)
        assert card_a.pk < card_b.pk

        import cardpicker.local_identify_printing_tags as module

        identical_image = Image.new("RGB", (750, 1050), (5, 5, 5))
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: identical_image)

        ocr_called_for_card_ids: list[int] = []

        def recording_run_ocr_for_card(selected, image, crop_box, bleed_class=None):
            ocr_called_for_card_ids.append(selected.card.pk)
            return module.OcrCardResult()

        monkeypatch.setattr(module, "run_ocr_for_card", recording_run_ocr_for_card)

        run_pilot(engine="ocr", limit=10, dry_run=False, nice=False)

        assert ocr_called_for_card_ids == [card_a.pk]
        assert card_b.pk not in ocr_called_for_card_ids

    def test_absorbed_members_own_engine_eligibility_still_runs_via_the_representative(self, db, monkeypatch):
        # card_a (the lower-pk representative) is only phash-eligible; card_b (absorbed member)
        # is only ocr-eligible - the representative must still run OCR on card_a's behalf, or
        # card_b's OCR opportunity is silently lost when it gets absorbed.
        printing = CanonicalCardFactory(name="Forest", expansion=CanonicalExpansionFactory(code="aaa"))
        card_a = CardFactory(name="Forest", content_phash=123)
        card_b = CardFactory(name="Forest", content_phash=123)

        import cardpicker.local_identify_printing_tags as module

        identical_image = Image.new("RGB", (750, 1050), (5, 5, 5))
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: identical_image)

        def fake_select_candidates(engine, index=None, exclude_source_pks=None, covered_printing_pks=None):
            real = select_candidates(engine, index, exclude_source_pks, covered_printing_pks)
            if engine == "ocr":
                return [s for s in real if s.card.pk == card_b.pk]
            return [s for s in real if s.card.pk == card_a.pk]

        monkeypatch.setattr(module, "select_candidates", fake_select_candidates)
        monkeypatch.setattr(
            module,
            "run_ocr_for_card",
            lambda selected, image, crop_box, bleed_class=None: module.OcrCardResult(
                vote=module.EngineVote(engine="ocr", printing_pk=printing.pk, confidence=0.85, detail="raw")
            ),
        )
        monkeypatch.setattr(
            module,
            "run_phash_for_card",
            lambda selected, image, threshold, margin, max_candidates, bleed_class=None: (None, "no-clear-winner"),
        )

        results, _attributes = run_pilot(engine="both", limit=10, dry_run=False, nice=False)

        assert results["ocr"].votes_written == 2
        assert CardPrintingTag.objects.filter(card=card_a, anonymous_id=OCR_ANONYMOUS_ID).exists()
        assert CardPrintingTag.objects.filter(card=card_b, anonymous_id=OCR_ANONYMOUS_ID).exists()


class TestComputeContentPhashForCard:
    """docs/features/printing-tags.md's hash-at-ingest architecture (2026-07-16): the shared
    fetch+hash primitive used by both the ingest hook (update_database) and the backfill
    command."""

    def test_returns_a_hash_for_a_fetchable_image(self, db, monkeypatch):
        card = CardFactory(name="Forest")
        import cardpicker.local_phash as module

        image = Image.new("RGB", (750, 1050), (5, 5, 5))
        ImageDraw.Draw(image).rectangle([100, 100, 300, 300], fill=(200, 30, 30))
        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: image)

        result = compute_content_phash_for_card(card)

        assert result is not None
        assert isinstance(result, int)

    def test_returns_none_when_the_fetch_fails(self, db, monkeypatch):
        card = CardFactory(name="Forest")
        import cardpicker.local_phash as module

        monkeypatch.setattr(module, "fetch_card_image", lambda card, dpi=None: None)

        assert compute_content_phash_for_card(card) is None

    def test_uses_the_small_ingest_dpi_by_default(self, db, monkeypatch):
        card = CardFactory(name="Forest")
        import cardpicker.local_phash as module

        seen_dpi = []

        def recording_fetch(card, dpi=None):
            seen_dpi.append(dpi)
            return Image.new("RGB", (750, 1050), (5, 5, 5))

        monkeypatch.setattr(module, "fetch_card_image", recording_fetch)

        compute_content_phash_for_card(card)

        assert seen_dpi == [module.INGEST_HASH_FETCH_DPI]


class TestContentPhashBackfill:
    """docs/features/printing-tags.md's hash-at-ingest architecture (2026-07-16): the one-time
    backfill command for existing NULL-content_phash cards."""

    def test_hashes_every_null_card_and_persists_the_result(self, db, monkeypatch):
        card_a = CardFactory(name="Forest", content_phash=None)
        card_b = CardFactory(name="Island", content_phash=None)
        import cardpicker.local_phash as module

        monkeypatch.setattr(module, "compute_content_phash_for_card", lambda card, dpi=module.INGEST_HASH_FETCH_DPI: 42)

        result = run_content_phash_backfill(nice=False)

        assert result == BackfillResult(dry_run=False, total_candidates=2, hashed=2, failed=0)
        card_a.refresh_from_db()
        card_b.refresh_from_db()
        assert card_a.content_phash == 42
        assert card_b.content_phash == 42

    def test_already_hashed_cards_are_not_touched(self, db, monkeypatch):
        already_hashed = CardFactory(name="Forest", content_phash=99)
        import cardpicker.local_phash as module

        called = []
        monkeypatch.setattr(
            module,
            "compute_content_phash_for_card",
            lambda card, dpi=module.INGEST_HASH_FETCH_DPI: called.append(card.pk) or 42,
        )

        result = run_content_phash_backfill(nice=False)

        assert result.total_candidates == 0
        assert called == []
        already_hashed.refresh_from_db()
        assert already_hashed.content_phash == 99

    def test_a_failed_hash_stays_null_and_is_counted_as_failed(self, db, monkeypatch):
        card = CardFactory(name="Forest", content_phash=None)
        import cardpicker.local_phash as module

        monkeypatch.setattr(
            module, "compute_content_phash_for_card", lambda card, dpi=module.INGEST_HASH_FETCH_DPI: None
        )

        result = run_content_phash_backfill(nice=False)

        assert result.hashed == 0
        assert result.failed == 1
        card.refresh_from_db()
        assert card.content_phash is None

    def test_dry_run_writes_nothing(self, db, monkeypatch):
        card = CardFactory(name="Forest", content_phash=None)
        import cardpicker.local_phash as module

        monkeypatch.setattr(module, "compute_content_phash_for_card", lambda card, dpi=module.INGEST_HASH_FETCH_DPI: 42)

        result = run_content_phash_backfill(dry_run=True, nice=False)

        assert result.hashed == 1
        card.refresh_from_db()
        assert card.content_phash is None

    def test_a_second_invocation_only_processes_what_the_first_missed(self, db, monkeypatch):
        # simulates a kill mid-backfill and a plain re-invocation - the NULL filter is the
        # checkpoint, no separate --resume flag needed.
        already_hashed = CardFactory(name="Forest", content_phash=42)
        still_null = CardFactory(name="Island", content_phash=None)
        import cardpicker.local_phash as module

        monkeypatch.setattr(module, "compute_content_phash_for_card", lambda card, dpi=module.INGEST_HASH_FETCH_DPI: 7)

        result = run_content_phash_backfill(nice=False)

        assert result.total_candidates == 1
        already_hashed.refresh_from_db()
        still_null.refresh_from_db()
        assert already_hashed.content_phash == 42  # untouched
        assert still_null.content_phash == 7  # newly hashed


class TestBackfillCommandCLI:
    """Closes a real gap: every other test in this file (and TestContentPhashBackfill above)
    calls run_content_phash_backfill() directly as a function, never through the actual CLI
    parser - so a real bug (local_backfill_content_phash.py redefining --skip-checks, which
    Django's BaseCommand already provides natively, an argparse.ArgumentError: conflicting
    option string) shipped silently and only surfaced live, on the real invocation, after the
    full-catalog pilot completed and this command was actually run for the first time
    (2026-07-17). call_command() exercises the real add_arguments()/parser path these other
    tests never touch."""

    def test_skip_checks_flag_does_not_conflict_with_djangos_own(self, db, monkeypatch):
        from django.core.management import call_command

        import cardpicker.local_phash as module

        monkeypatch.setattr(module, "compute_content_phash_for_card", lambda card, dpi=module.INGEST_HASH_FETCH_DPI: 1)
        # would raise argparse.ArgumentError before this fix - reaching here at all is the test.
        call_command("local_backfill_content_phash", "--skip-checks", "--limit=0")

    def test_real_cli_invocation_with_no_flags_at_all(self, db, monkeypatch):
        from django.core.management import call_command

        import cardpicker.local_phash as module

        monkeypatch.setattr(module, "compute_content_phash_for_card", lambda card, dpi=module.INGEST_HASH_FETCH_DPI: 1)
        call_command("local_backfill_content_phash", "--limit=0")


class TestPipelinedBackfillOutOfOrder:
    """Part 2 (docs/features/catalog-completion-plan.md): the pipelined backfill's sliding
    fetch window means completion order isn't submission order once more than one worker
    thread is in flight - this proves persistence is correct regardless of which order fetches
    actually finish in, unlike run_pilot's ThreadPoolExecutor.map() which gets ordering for
    free."""

    def test_persists_correctly_when_completion_order_differs_from_submission_order(self, db, monkeypatch):
        # card_a is submitted first (lower pk, since the queryset orders by pk) but its fetch
        # is made to finish LAST - proves the persisted result is keyed by which card the
        # future belongs to, not by submission/completion position.
        card_a = CardFactory(name="Forest", content_phash=None)
        card_b = CardFactory(name="Island", content_phash=None)
        card_c = CardFactory(name="Mountain", content_phash=None)
        import time

        import cardpicker.local_phash as module

        delays = {card_a.pk: 0.3, card_b.pk: 0.05, card_c.pk: 0.15}
        hashes = {card_a.pk: 111, card_b.pk: 222, card_c.pk: 333}

        def slow_variable_hash(card: object, dpi: int = module.INGEST_HASH_FETCH_DPI) -> int:
            time.sleep(delays[card.pk])  # type: ignore[attr-defined]
            return hashes[card.pk]  # type: ignore[attr-defined]

        monkeypatch.setattr(module, "compute_content_phash_for_card", slow_variable_hash)

        # workers=3 keeps all three in flight simultaneously (window_size = max(batch_size *
        # queue_depth_batches, workers) = max(2, 3) = 3), so completion order is purely
        # determined by the delays above (b, then c, then a) - the reverse of submission order.
        result = run_content_phash_backfill(nice=False, batch_size=1, workers=3, queue_depth_batches=1)

        assert result == BackfillResult(dry_run=False, total_candidates=3, hashed=3, failed=0)
        card_a.refresh_from_db()
        card_b.refresh_from_db()
        card_c.refresh_from_db()
        assert card_a.content_phash == 111
        assert card_b.content_phash == 222
        assert card_c.content_phash == 333

    def test_checkpoint_flushes_progressively_not_all_at_once(self, db, monkeypatch):
        # proves the pipeline actually flushes as it goes (the "kill loses at most one batch"
        # safety property) rather than accumulating every result and writing once at the end,
        # which would silently defeat that property while still passing every other test here.
        cards = [CardFactory(name=f"Card {i}", content_phash=None) for i in range(6)]
        import cardpicker.local_phash as module

        monkeypatch.setattr(
            module, "compute_content_phash_for_card", lambda card, dpi=module.INGEST_HASH_FETCH_DPI: card.pk
        )

        bulk_update_calls: list[int] = []
        original_bulk_update = module.Card.objects.bulk_update

        def counting_bulk_update(objs: object, fields: object, **kwargs: object) -> object:
            bulk_update_calls.append(len(list(objs)))  # type: ignore[arg-type]
            return original_bulk_update(objs, fields, **kwargs)

        monkeypatch.setattr(module.Card.objects, "bulk_update", counting_bulk_update)

        result = run_content_phash_backfill(nice=False, batch_size=2, workers=2, queue_depth_batches=1)

        assert result.hashed == 6
        # 6 cards at batch_size=2 must flush at least 3 times (could be more if timing splits a
        # window awkwardly, but never fewer) - the key assertion is "more than one," proving
        # this isn't a single end-of-run write.
        assert len(bulk_update_calls) >= 3
        assert sum(bulk_update_calls) == 6
        for card in cards:
            card.refresh_from_db()
            assert card.content_phash == card.pk
