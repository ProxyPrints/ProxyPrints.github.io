"""
Tests for `cardpicker.collector_line_artist` (2026-07-29) - recovering the artist credit from
`ImageEvidence.collector_line_raw_text`.

Every class here except `TestPrintingArtistLookup` is a pure-function test against a small
in-memory `ArtistLexicon` built by `build_artist_lexicon` - no DB access, matching the module's own
"no DB/network in `recover_artist_from_collector_line` itself" design. `TestPrintingArtistLookup`
at the bottom exercises the one stateful, DB-touching helper against the real ORM (pytest-django's
ephemeral test DB, never production); `load_artist_lexicon`'s own real-ORM coverage lives with its
consumer, in `test_local_calculate_verdicts.py`.

Every `raw` string in `TestTruncationAndOcrNoise` below is VERBATIM production text, pulled
read-only from `cardpicker_imageevidence.collector_line_raw_text` on 2026-07-29 - not invented,
not cleaned up.
"""

from cardpicker.collector_line_artist import (
    MAX_COMPATIBLE,
    MIN_CANDIDATE_LETTERS,
    MIN_TRUNCATED_LETTERS,
    PrintingArtistLookup,
    _joint_credit_components,
    build_artist_lexicon,
    build_name_artist_lookup,
    recover_artist_from_card_text,
    recover_artist_from_collector_line,
)
from cardpicker.tests.factories import CanonicalCardFactory, CanonicalExpansionFactory

# A deliberately-realistic fixture lexicon: every entry is a real `CanonicalArtist.name` sampled
# from production, chosen to exercise a specific behaviour -
#   - the three flagship truncation cases from the dispatching brief (Alessandra Pisano / Lindsey
#     Look / Ron Spears), plus "Ron Spencer" as the near-collision that makes "RON SPEA" genuinely
#     ambiguous rather than trivially unique;
#   - "Ryo Kamei", the owner's canonical-resolution case (cards print "RIYOU KAMEI");
#   - "Mike Bierek", the lost-space case ("MIKEBIE");
#   - "Daarken"/"Daarken & Jared Blando" and "Cliff Childs"/"Cliff Chiang", two shapes of
#     irreducible truncation ambiguity;
#   - "Daniel Lieske"/"Daniel Ljunggren", the near-miss pair that COMPATIBLE_BAND exists for;
#   - the eight "Richard ..." entries, the MAX_COMPATIBLE case;
#   - the four "Vincent ..." entries, the truncation-guard case (a production row whose card name
#     ends in "... Vincent");
#   - "Ray", a real 3-character mononym - the MIN_CANDIDATE_LETTERS case.
LEXICON_NAMES = [
    "Alessandra Pisano",
    "Lindsey Look",
    "Ron Spears",
    "Ron Spencer",
    "Ryo Kamei",
    "Mike Bierek",
    "Mark Tedin",
    "Daarken",
    "Daarken & Jared Blando",
    "Cliff Childs",
    "Cliff Chiang",
    "Daniel Lieske",
    "Daniel Ljunggren",
    "Ray",
    "Vincent Proce",
    "Vincent Evans",
    "Vincent Coviello",
    "Vincent Christiaens",
    "Richard Kane Ferguson",
    "Richard Luong",
    "Richard Sardinha",
    "Richard Suwono",
    "Richard Thomas",
    "Richard Whitters",
    "Richard Wright",
    "Rebecca Guay",
    # JOINT / COLLABORATIVE CREDITS (2026-07-29). Every entry below is a verbatim live
    # `CanonicalArtist.name` - both the joint rows and the standalone rows for their components -
    # chosen to cover each shape the separator census turned up:
    #   - "Greg Hildebrandt & Tim Hildebrandt", the reported production defect (card 679), with
    #     BOTH standalone components also on record, and its own reversed-order twin
    #     "Tim Hildebrandt & Greg Hildebrandt", which the live lexicon really does carry as a
    #     separate row;
    #   - "Paolo Parente & Brian Snõddy", the ORDER-REVERSED case - the recovered name is the
    #     SECOND component, so a first-component-only rule would miss it;
    #   - "M. W. Kaluta & DiTerlizzi", whose components are both standalone entries and whose
    #     first one carries the initials/periods `_normalize` has to erase;
    #   - "Anthony S. Waters & Edward P. Beard, Jr.", a joint credit with a COMMA inside its
    #     second component - the reason comma is not a separator;
    #   - "Wesley Burt & コーヘー", whose second component normalizes to the EMPTY string - the
    #     reason the degenerate-split guard tests the raw part, not the normalized one;
    #   - "Daarken & Jared Blando" was already here, and "Jared Blando" is deliberately NOT added:
    #     a component with no standalone lexicon row of its own must still decompose.
    "Greg Hildebrandt",
    "Tim Hildebrandt",
    "Greg Hildebrandt & Tim Hildebrandt",
    "Tim Hildebrandt & Greg Hildebrandt",
    "Paolo Parente",
    "Brian Snõddy",
    "Paolo Parente & Brian Snõddy",
    "M. W. Kaluta",
    "DiTerlizzi",
    "M. W. Kaluta & DiTerlizzi",
    "Anthony S. Waters",
    "Edward P. Beard, Jr.",
    "Anthony S. Waters & Edward P. Beard, Jr.",
    "Wesley Burt",
    "Wesley Burt & コーヘー",
]
LEXICON = build_artist_lexicon(LEXICON_NAMES)


class TestTruncationAndOcrNoise:
    """The core capability: the artist is present but the crop clipped its right edge, and the
    surviving characters arrive wrapped in tesseract's rendering of the brush glyph / set-symbol
    (`«`, `¢`, `%®`, `>`, `te`, `be`)."""

    def test_truncated_alessandra_pisano_with_glyph_noise(self):
        # Verbatim production row. 'ALESSAND' is 9 characters short of the real name.
        raw = "124/281R\nAFR « EN %®ALESSAND"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.candidate == "ALESSAND"
        assert result.canonical_name == "Alessandra Pisano"

    def test_truncated_lindsey_look_keeping_a_lone_surviving_initial(self):
        # 'LINDSEY L' - the trailing single character is real evidence, and TOKEN_RE deliberately
        # admits a one-character token (unlike modern_artist_credit's own WORD_RE) to keep it.
        raw = "204/361R\nCLB ¢ EN LINDSEY L"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.canonical_name == "Lindsey Look"

    def test_truncated_ron_spears_is_ambiguous_against_ron_spencer(self):
        # 'RON SPEA' fits "Ron Spears" exactly (1.0) but "Ron Spencer" scores 0.857 on the same
        # prefix - inside COMPATIBLE_BAND. Both are plausible, so the reading is usable for the
        # contradiction test and NOT storable. This is the design working, not a regression.
        raw = "059/274R\nDMR ¢ EN RON SPEA"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert set(result.compatible_names) == {"Ron Spears", "Ron Spencer"}
        assert result.canonical_name is None
        assert result.is_compatible_with("Ron Spears")
        assert result.is_compatible_with("Ron Spencer")
        assert not result.is_compatible_with("Mark Tedin")

    def test_lost_space_between_first_and_last_name(self):
        # Real production row: tesseract dropped the space entirely. Normalizing both sides to
        # letters/digits is what makes 'MIKEBIE' a clean prefix of 'mikebierek'.
        raw = "283/325 M\nVMA~+EN > MIKEBIE"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.canonical_name == "Mike Bierek"

    def test_brush_glyph_garble_prefix_is_dropped(self):
        # 'he' is tesseract's reading of the brush glyph - short enough to be droppable under
        # MAX_DROPPABLE_PREFIX_LEN, so 'MARK TED' is still the whole name-shaped tail.
        raw = "001/001 P Command\nPRM «EN he MARK TED"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.canonical_name == "Mark Tedin"

    def test_untruncated_name_matches_anywhere_in_the_text(self):
        # No collector line structure at all, artist on its own line - the FULL match path, which
        # (unlike the truncated path) is not restricted to the line-final tail.
        raw = "2021 Darkpingouin « PRO)\n———» Mark Tedin"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.canonical_name == "Mark Tedin"


class TestCanonicalResolution:
    """Owner ruling, 2026-07-29: fuzzy MATCHING is permitted, fuzzy STORAGE is not."""

    def test_riyou_kamei_resolves_to_the_canonical_ryo_kamei(self):
        # The card prints "RIYOU KAMEI"; the lexicon (Scryfall-derived) holds only "Ryo Kamei".
        # They are one person and must resolve to one canonical artist - which falls straight out
        # of normalized fuzzy matching (0.889), with no alias table.
        raw = "119/281 R\nAFR ¢ EN © RIYOU KAMEI"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.canonical_name == "Ryo Kamei"
        assert result.is_compatible_with("Ryo Kamei")

    def test_riyou_kamei_in_mixed_case_resolves_identically(self):
        raw = "119/281 R\nAFR ¢ EN © Riyou Kamei"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.canonical_name == "Ryo Kamei"

    def test_every_returned_name_is_a_verbatim_lexicon_entry_never_the_ocr_string(self):
        raw = "124/281R\nAFR « EN %®ALESSAND"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert all(name in LEXICON_NAMES for name in result.compatible_names)
        assert result.candidate not in result.compatible_names  # the OCR span is never the value

    def test_storage_is_withheld_whenever_more_than_one_canonical_artist_fits(self):
        # 'DAARKEN' is an exact prefix of BOTH the solo credit and the collaboration credit.
        raw = "661 R\nCMR °EN %® DAARKEN"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert set(result.compatible_names) == {"Daarken", "Daarken & Jared Blando"}
        assert result.canonical_name is None


class TestCompatibilityBand:
    def test_near_miss_alternative_stays_compatible_so_it_cannot_manufacture_a_contradiction(self):
        # 'DANIEL Li' scores 1.00 against "Daniel Lieske" and 0.875 against "Daniel Ljunggren".
        # Collapsing to the winner would confidently contradict a correct Ljunggren printing -
        # the exact production false positive COMPATIBLE_BAND was set (0.15) to prevent.
        raw = "240/269 R\nDOM «EN DANIEL LI"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert set(result.compatible_names) == {"Daniel Lieske", "Daniel Ljunggren"}
        assert result.is_compatible_with("Daniel Ljunggren")
        assert result.canonical_name is None

    def test_a_genuinely_incompatible_artist_is_reported_as_such(self):
        raw = "204/361R\nCLB ¢ EN LINDSEY L"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert not result.is_compatible_with("Rebecca Guay")

    def test_missing_artist_name_is_never_a_contradiction(self):
        # "absent data is not evidence" - the same rule every agreement check in
        # local_calculate_verdicts._apply_agreement_checks applies.
        raw = "204/361R\nCLB ¢ EN LINDSEY L"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.is_compatible_with("")


class TestFalsePositiveGuards:
    def test_hopelessly_ambiguous_prefix_abstains_entirely(self):
        # 'RICHARD' alone prefix-matches eight real artists at 1.0 - past MAX_COMPATIBLE, so the
        # reading carries no information and the module returns nothing at all.
        assert MAX_COMPATIBLE < 8
        raw = "269/307 U\nC18 ° EN RICHARD"
        assert recover_artist_from_collector_line(raw, LEXICON) is None

    def test_longer_exact_read_wins_over_the_bare_first_name_it_contains(self):
        # Same eight-way 'RICHARD' tie as above, but the full name IS legible - the
        # (ratio, length) ranking must let the exact read through rather than being drowned out.
        raw = "> RICHARD WRIGHT"
        result = recover_artist_from_collector_line(raw, LEXICON)
        assert result is not None
        assert result.canonical_name == "Richard Wright"

    def test_truncation_is_refused_when_a_real_word_sits_to_the_left(self):
        # Verbatim production row. 'Vincent' is line-final and prefix-matches four real artists at
        # 1.0, but the whole name-shaped tail of that line is 'Kelton Vincent' - nothing was
        # clipped off 'Vincent', so a prefix match on it is not legitimate. The TRUNCATION GUARD
        # is grounded in the physical cause (the crop cuts the RIGHT EDGE), not in taste.
        raw = "Kelton Vincent\nbe DIVINE REVOCATIO!"
        assert recover_artist_from_collector_line(raw, LEXICON) is None

    def test_short_mononym_is_never_recovered_from_noise(self):
        # Verbatim production row that matched the real 3-character lexicon entry "Ray" before
        # MIN_CANDIDATE_LETTERS existed.
        assert MIN_CANDIDATE_LETTERS > len("Ray")
        raw = "ae 2a. se rd Oe all\n\\ ate ER C7 ed Ra y\noop ete bee “(89 4 4 )"
        assert recover_artist_from_collector_line(raw, LEXICON) is None

    def test_too_few_surviving_characters_to_claim_a_truncated_match(self):
        # 'ALESS' is a genuine prefix of "Alessandra Pisano" but is under MIN_TRUNCATED_LETTERS -
        # not enough evidence for anybody, so this abstains rather than guessing right by luck.
        assert MIN_TRUNCATED_LETTERS == 7
        raw = "124/281R\nAFR « EN %®ALESS"
        assert recover_artist_from_collector_line(raw, LEXICON) is None

    def test_language_marker_is_never_itself_a_candidate(self):
        raw = "124/281R\nAFR « EN"
        assert recover_artist_from_collector_line(raw, LEXICON) is None

    def test_pure_noise_recovers_nothing(self):
        raw = "oat : . a ae ee se ew FE te\nPeat lre’ ee wh ts ee cs hr hd ae Se"
        assert recover_artist_from_collector_line(raw, LEXICON) is None

    def test_empty_text_recovers_nothing(self):
        assert recover_artist_from_collector_line("", LEXICON) is None


class TestLexiconConstruction:
    def test_empty_lexicon_never_matches(self):
        empty = build_artist_lexicon([])
        assert recover_artist_from_collector_line("124/281R\nAFR « EN %®ALESSAND", empty) is None

    def test_blank_names_are_dropped_rather_than_bucketed(self):
        lexicon = build_artist_lexicon(["", "   ", "Lindsey Look"])
        result = recover_artist_from_collector_line("204/361R\nCLB ¢ EN LINDSEY L", lexicon)
        assert result is not None
        assert result.canonical_name == "Lindsey Look"


class TestPrintingArtistLookup:
    """The Stage C resolver (real ORM). Stage C has no `CandidatePrinting` list and no
    already-fetched `CanonicalCard` row to read an artist off, so it resolves a parsed
    (set_code, collector_number) pair directly."""

    def test_resolves_a_real_printing_to_its_artist(self, db):
        CanonicalCardFactory(expansion__code="mom", collector_number="158", artist__name="Ron Spears")

        assert PrintingArtistLookup()("mom", "158") == "Ron Spears"

    def test_leading_zeros_and_case_do_not_change_the_answer(self, db):
        """Same `_normalize_collector_number` treatment `local_ocr.find_matching_candidates`
        already applies, so this resolver and Stage D's candidate matching can never disagree
        about which printing a parse denotes."""
        CanonicalCardFactory(expansion__code="mom", collector_number="0158a", artist__name="Ron Spears")

        lookup = PrintingArtistLookup()
        assert lookup("MOM", "158A") == "Ron Spears"
        assert lookup("mom", "00158a") == "Ron Spears"

    def test_unknown_pair_and_missing_set_code_both_resolve_to_none(self, db):
        lookup = PrintingArtistLookup()
        assert lookup("mom", "999") is None
        assert lookup(None, "158") is None  # the pre-M15 collector-number-only carve-out
        assert lookup("mom", None) is None

    def test_an_expansion_is_loaded_once_and_reused(self, db):
        """One query per EXPANSION, not per card - Stage C batches hammer the same few sets."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        expansion = CanonicalExpansionFactory(code="mom")
        CanonicalCardFactory(expansion=expansion, collector_number="158", artist__name="Ron Spears")
        CanonicalCardFactory(expansion=expansion, collector_number="159", artist__name="Lindsey Look")
        lookup = PrintingArtistLookup()

        with CaptureQueriesContext(connection) as captured:
            assert lookup("mom", "158") == "Ron Spears"
            assert lookup("mom", "159") == "Lindsey Look"
            assert lookup("mom", "160") is None

        assert len(captured) == 1


class TestWideningTheRead:
    """`recover_artist_from_card_text` (2026-07-29) - reading the artist out of BOTH stored reads
    of the card's own bottom print row, not just the clipped one.

    `legal_line_raw_text` crops the IDENTICAL y band as `collector_line_raw_text`
    (`local_ocr.LEGAL_LINE_CROP_BOX` (0.0, 0.90, 1.0, 0.965) vs `DEFAULT_CROP_BOX`
    (0.06, 0.90, 0.35, 0.965)) at the FULL card width, so it carries the artist credit whole where
    the collector crop clips it. Every pair below is VERBATIM production text pulled read-only on
    2026-07-29 - the same row's two stored strings, not two hand-written variants of one."""

    def test_the_untruncated_legal_line_read_wins_over_the_clipped_collector_read(self):
        # 'LINDSEY L' truncates; the full-width read of the same print row does not. Both score
        # ratio 1.0, and the shared `(ratio, normalized length)` key is what makes the longer,
        # unclipped read win - no new precedence rule was needed.
        result = recover_artist_from_card_text(
            "204/361R\nCLB ¢ EN LINDSEY L", "204/361R\nCLB ¢ EN LINDSEY LOOK\n", LEXICON
        )
        assert result is not None
        assert result.candidate == "LINDSEY LOOK"
        assert result.canonical_name == "Lindsey Look"

    def test_a_read_ambiguous_when_clipped_becomes_decisive_when_whole(self):
        """The flagship case. 'RON SPEA' is irreducibly compatible with two real artists; the
        full-width read of the SAME print row is compatible with exactly one, so it becomes
        storable - with no threshold moved and no lexicon change."""
        clipped = recover_artist_from_collector_line("059/274R\nDMR ¢ EN RON SPEA", LEXICON)
        assert clipped is not None
        assert clipped.compatible_names == ("Ron Spears", "Ron Spencer")
        assert clipped.canonical_name is None  # ambiguous - deliberately unstorable

        whole = recover_artist_from_card_text("059/274R\nDMR ¢ EN RON SPEA", "059/274R\nDMR ¢ EN RON SPEARS\n", LEXICON)
        assert whole is not None
        assert whole.canonical_name == "Ron Spears"

    def test_truncated_matching_is_disabled_for_the_legal_line_text(self):
        """A prefix match is only ever legitimate against a crop that CLIPS the name's right edge,
        and the legal-line crop runs to the full card width. So a legal-line-only prefix read must
        produce NOTHING, even though the identical string in the collector line reads fine."""
        clipped_text = "124/281R\nAFR « EN %®ALESSAND"
        assert recover_artist_from_collector_line(clipped_text, LEXICON) is not None
        assert recover_artist_from_card_text("", clipped_text, LEXICON) is None

    def test_either_text_may_be_empty(self):
        """A fetch failure or a legal-line extractor that found nothing leaves one side blank -
        the other decides alone, and two blanks are simply no reading."""
        assert recover_artist_from_card_text("", "", LEXICON) is None
        collector_only = recover_artist_from_card_text("124/281R\nAFR « EN %®ALESSAND", "", LEXICON)
        assert collector_only is not None and collector_only.canonical_name == "Alessandra Pisano"
        legal_only = recover_artist_from_card_text("", "2022 Custom Proxy\nMMQ: EN > MARK TEDIN\n", LEXICON)
        assert legal_only is not None and legal_only.canonical_name == "Mark Tedin"

    def test_the_legal_lines_watermark_tail_does_not_derail_the_read(self):
        """Verbatim production legal line. The full-width crop picks up the proxy/watermark prose
        the narrow collector crop never reached - `CANDIDATE_STOPWORDS` already covers it, which is
        why widening the read costs no new vocabulary."""
        result = recover_artist_from_card_text(
            "003/030 M\nZNE «FR % DAARKEN", "003/030 M\nZNE «FR > DAARKEN PROXY CARD - NOT FOR SALE\n", LEXICON
        )
        assert result is not None
        assert "Daarken" in result.compatible_names


class TestCardNameNarrowing:
    """`allowed_artist_names` (2026-07-29) - narrowing the compatible set to the artists who
    actually illustrated a printing of this card's own name.

    Applied as a strict INTERSECTION of the already-computed compatible set, and only when that
    intersection is non-empty. The tests below pin all three consequences of that shape."""

    def test_narrowing_collapses_an_ambiguous_read_to_one_storable_name(self):
        """'RON SPEA' against the full lexicon fits both "Ron Spears" and "Ron Spencer"; against
        the one artist who illustrated this card's name it is decisive."""
        result = recover_artist_from_collector_line(
            "059/274R\nDMR ¢ EN RON SPEA", LEXICON, allowed_artist_names=["Ron Spears"]
        )
        assert result is not None
        assert result.compatible_names == ("Ron Spears",)
        assert result.canonical_name == "Ron Spears"

    def test_narrowing_can_only_shrink_the_set_never_change_which_read_won(self):
        unnarrowed = recover_artist_from_collector_line("059/274R\nDMR ¢ EN RON SPEA", LEXICON)
        narrowed = recover_artist_from_collector_line(
            "059/274R\nDMR ¢ EN RON SPEA", LEXICON, allowed_artist_names=["Ron Spencer"]
        )
        assert unnarrowed is not None and narrowed is not None
        assert narrowed.candidate == unnarrowed.candidate
        assert narrowed.ratio == unnarrowed.ratio
        assert set(narrowed.compatible_names) < set(unnarrowed.compatible_names)

    def test_an_empty_intersection_falls_back_to_the_unnarrowed_set(self):
        """A decorated or genuinely custom card name resolves to artists that have nothing to do
        with the read (only 48% of uploaded names match a canonical name exactly). That must never
        cost the recovery - it falls back, it does not abstain and it does not force a wrong name."""
        unnarrowed = recover_artist_from_collector_line("059/274R\nDMR ¢ EN RON SPEA", LEXICON)
        fallen_back = recover_artist_from_collector_line(
            "059/274R\nDMR ¢ EN RON SPEA", LEXICON, allowed_artist_names=["Rebecca Guay"]
        )
        assert unnarrowed is not None and fallen_back is not None
        assert fallen_back.compatible_names == unnarrowed.compatible_names
        assert fallen_back.canonical_name is None

    def test_no_allowed_names_at_all_is_byte_identical_to_not_narrowing(self):
        baseline = recover_artist_from_collector_line("059/274R\nDMR ¢ EN RON SPEA", LEXICON)
        for empty in (None, (), [], ["", "   "]):
            assert recover_artist_from_collector_line("059/274R\nDMR ¢ EN RON SPEA", LEXICON, empty) == baseline

    def test_narrowing_rescues_a_read_that_fits_too_many_artists_to_mean_anything(self):
        """A bare 'RICHARD' fits eight real artists, so the unnarrowed module abstains entirely
        (`MAX_COMPATIBLE`). Scoped to the one Richard who illustrated this card's name, the same
        read is decisive - which is why the narrowing is applied BEFORE that cap, not after."""
        raw = "> RICHARD"
        assert recover_artist_from_collector_line(raw, LEXICON) is None
        result = recover_artist_from_collector_line(raw, LEXICON, allowed_artist_names=["Richard Luong"])
        assert result is not None
        assert result.canonical_name == "Richard Luong"

    def test_narrowing_never_makes_a_compatible_artist_incompatible_if_it_is_allowed(self):
        """THE STAGE D SAFETY INVARIANT. `_apply_agreement_checks` compares the reading against the
        artist of the MATCHED candidate, and that candidate came out of the very list the allowed
        set is derived from - so the printing's artist is always IN the allowed set, and narrowing
        (a pure intersection) can therefore never turn a non-contradiction into a contradiction
        there. Measured confirmation, read-only production 2026-07-29: the false-contradiction rate
        on independently-corroborated rows is byte-identical with and without narrowing (2.83%)."""
        unnarrowed = recover_artist_from_collector_line("059/274R\nDMR ¢ EN RON SPEA", LEXICON)
        assert unnarrowed is not None
        for allowed_member in unnarrowed.compatible_names:
            narrowed = recover_artist_from_collector_line(
                "059/274R\nDMR ¢ EN RON SPEA", LEXICON, allowed_artist_names=[allowed_member]
            )
            assert narrowed is not None
            assert narrowed.is_compatible_with(allowed_member)

    def test_narrowing_is_compared_on_the_normalized_form(self):
        """Same normalisation both sides, so a lexicon that ever drifts in casing/punctuation
        can't silently switch the narrowing off - the identical rule `is_compatible_with` uses."""
        result = recover_artist_from_collector_line(
            "059/274R\nDMR ¢ EN RON SPEA", LEXICON, allowed_artist_names=["  ron   spears!  "]
        )
        assert result is not None
        assert result.canonical_name == "Ron Spears"

    def test_narrowing_composes_with_the_widened_read(self):
        result = recover_artist_from_card_text(
            "204/361R\nCLB ¢ EN LINDSEY L",
            "204/361R\nCLB ¢ EN LINDSEY LOOK\n",
            LEXICON,
            allowed_artist_names=["Lindsey Look", "Mark Tedin"],
        )
        assert result is not None
        assert result.canonical_name == "Lindsey Look"


class TestJointArtistCredits:
    """JOINT / COLLABORATIVE CREDITS (2026-07-29) - a recovered artist that is a COMPONENT of a
    joint credit must not contradict that credit.

    The production defect, verbatim (card 679, "Weathered Wayfarer (NormalPlus Greg Hildebrandt &
    Tim Hildebrandt)"): the legal line reads `... GREG HILDEBRANDT & TIM HILDEBRAMBT2022 ...` with
    tesseract garbling the second surname. `GREG HILDEBRANDT` matches the STANDALONE entry at ratio
    1.0; the card's real printing is credited to the JOINT entry, which is longer than the
    candidate and so reachable only in TRUNCATED mode - which is off for the legal line. So the
    joint entry never entered the compatible set and a correct vote was judged contradicted, and
    the live Stage D veto (`skip_reason="artist-mismatch"`) withheld it.

    Separator vocabulary is MEASURED, not assumed - a read-only census of all 2,523 live
    `CanonicalArtist` rows on 2026-07-29 found `' & '` on 219 rows and NO other joint form at all
    (`' and '`, `' + '`, `';'`, `' x '`, `'|'`, dashes: zero rows each). Its 20 comma rows are name
    suffixes and Unfinity age gags, never collaborations, and its one `'/'` row is a single
    person's name in two scripts. All 219 joint rows have exactly two components.

    Every string below is a real production artist name or a real production OCR line."""

    def test_the_reported_production_defect_card_679(self):
        """Verbatim legal line from production card 679, with tesseract's own garbling of the
        second surname. Before this fix `is_compatible_with` returned False here and Stage D
        vetoed a CORRECT vote."""
        raw_legal = "034/577 R ,\n2X2 « EN © GREG HILDEBRANDT & TIM HILDEBRAMBT2022 Proxy * Not for Sale\n"
        result = recover_artist_from_card_text("", raw_legal, LEXICON)
        assert result is not None
        assert result.compatible_names == ("Greg Hildebrandt",)
        assert result.is_compatible_with("Greg Hildebrandt & Tim Hildebrandt")

    def test_the_second_component_is_just_as_compatible_as_the_first(self):
        """`Brian Snõddy` is the SECOND component of "Paolo Parente & Brian Snõddy" - a
        first-component-only (prefix) rule would miss the entire order-reversed population. The
        `õ` also proves the comparison runs through `_normalize` on both sides."""
        result = recover_artist_from_card_text("", "233/281 R\nMH2 « EN BRIAN SNODDY\n", LEXICON)
        assert result is not None
        assert result.compatible_names == ("Brian Snõddy",)
        assert result.is_compatible_with("Paolo Parente & Brian Snõddy")

    def test_it_works_when_only_the_first_component_survives_truncation(self):
        """THE COMMON CASE. The crop clips the RIGHT edge, so the second component of a joint
        credit is exactly what gets lost. Here the collector line is clipped mid-surname and there
        is no legal-line text at all, so only a truncated prefix of the first component exists -
        and the joint printing still must not be contradicted."""
        result = recover_artist_from_collector_line("034/577 R\n2X2 « EN GREG HILDEBRAN", LEXICON)
        assert result is not None
        assert result.is_compatible_with("Greg Hildebrandt & Tim Hildebrandt")
        assert result.is_compatible_with("Tim Hildebrandt & Greg Hildebrandt")

    def test_a_component_that_has_no_standalone_lexicon_row_still_decomposes(self):
        """ "Jared Blando" is deliberately absent from the fixture lexicon, exactly as ~34% of the
        live joint credits' components are absent from the real one. Decomposition is a property
        of the ARGUMENT STRING, not a lexicon lookup, so it does not depend on that."""
        result = recover_artist_from_card_text("", "003/030 M\nZNE «FR > DAARKEN\n", LEXICON)
        assert result is not None
        assert "Daarken" in result.compatible_names
        assert result.is_compatible_with("Daarken & Jared Blando")

    def test_initials_and_an_internal_comma_do_not_break_decomposition(self):
        """Two live shapes at once: "M. W. Kaluta" carries initials and periods `_normalize` has
        to erase, and "Anthony S. Waters & Edward P. Beard, Jr." carries a COMMA inside its second
        component - which is why the split is on `&` alone and components are never re-split."""
        kaluta = recover_artist_from_card_text("", "038/249 U\nSTA « EN M. W. KALUTA\n", LEXICON)
        assert kaluta is not None
        assert kaluta.compatible_names == ("M. W. Kaluta",)
        assert kaluta.is_compatible_with("M. W. Kaluta & DiTerlizzi")

        waters = recover_artist_from_card_text("", "092/281 R\nMH3 « EN ANTHONY S. WATERS\n", LEXICON)
        assert waters is not None
        assert waters.compatible_names == ("Anthony S. Waters",)
        assert waters.is_compatible_with("Anthony S. Waters & Edward P. Beard, Jr.")
        # The second component is itself a whole real artist, comma and all - not "Jr.".
        assert not waters.is_compatible_with("Edward P. Beard, Jr.")

    def test_a_component_that_normalizes_to_nothing_still_decomposes(self):
        """ "Wesley Burt & コーヘー" is a real lexicon row whose second component survives
        `_normalize` as the EMPTY string (it keeps only `[a-z0-9]`). The degenerate-split guard
        therefore has to test the RAW stripped part - testing the normalized one would classify
        this row as non-joint.

        Asserted at `_joint_credit_components`, because through `is_compatible_with` this row
        cannot distinguish the two: `_normalize("Wesley Burt & コーヘー")` is exactly
        `"wesleyburt"`, so the DIRECT membership test already answers True either way. That is
        worth knowing rather than papering over - it is why the compatibility assertion below is
        not by itself evidence the guard works."""
        assert _joint_credit_components("Wesley Burt & コーヘー") == ("Wesley Burt", "コーヘー")
        result = recover_artist_from_card_text("", "0055 R\nSLD « EN WESLEY BURT\n", LEXICON)
        assert result is not None
        assert "Wesley Burt" in result.compatible_names
        assert result.is_compatible_with("Wesley Burt & コーヘー")

    def test_two_unrelated_artists_do_not_become_compatible_with_each_other(self):
        """THE ASYMMETRY THAT MAKES THIS SAFE. Only the joint STRING is ever explained by one of
        its own components; the components are never made compatible with each other, and an
        artist who merely shares a joint entry with the recovered one is still a contradiction."""
        result = recover_artist_from_card_text("", "034/577 R\n2X2 « EN GREG HILDEBRANDT\n", LEXICON)
        assert result is not None
        assert result.compatible_names == ("Greg Hildebrandt",)
        # Both are components of one live joint credit. That must not make them each other's
        # equal - this is a real disagreement about which printing the card is.
        assert not result.is_compatible_with("Tim Hildebrandt")
        # Nor does sharing a joint entry with somebody make an unrelated joint credit compatible.
        assert not result.is_compatible_with("Paolo Parente & Brian Snõddy")

    def test_a_genuine_contradiction_against_a_joint_printing_is_still_detected(self):
        """The fix must not buy its number by making everything compatible. A reading of a real
        artist who appears NOWHERE in the printing's joint credit still contradicts it - this is
        the shape of all 8 joint-credit contradictions that survive the fix in the full production
        census (e.g. "Dermot Power" vs "Greg Hildebrandt & Tim Hildebrandt")."""
        result = recover_artist_from_card_text("", "204/361R\nCLB ¢ EN LINDSEY LOOK\n", LEXICON)
        assert result is not None
        assert result.compatible_names == ("Lindsey Look",)
        assert not result.is_compatible_with("Greg Hildebrandt & Tim Hildebrandt")
        assert not result.is_compatible_with("Paolo Parente & Brian Snõddy")
        assert not result.is_compatible_with("Rebecca Guay")

    def test_the_reverse_direction_is_deliberately_still_a_contradiction(self):
        """A reading of the WHOLE joint credit against a printing credited to one component alone
        is NOT truncation - the pixels named a collaborator the printing does not credit, which is
        a real disagreement. Measured cost of holding this line over the full 41,129-vote census:
        zero restored votes, so the extra false-agreement surface buys nothing."""
        result = recover_artist_from_card_text("", "017/016 M\nSLD « EN WESLEY BURT & コーヘー\n", LEXICON)
        assert result is not None
        assert "Wesley Burt & コーヘー" in result.compatible_names
        assert not result.is_compatible_with("コーヘー")

    def test_a_degenerate_split_is_not_reported_as_a_joint_credit(self):
        """A leading or trailing ampersand leaves only one side carrying a name, and that is not a
        collaboration - decomposition must report NOTHING rather than a one-sided credit, so that
        "& Foo" can never make everything compatible with "Foo".

        Asserted at `_joint_credit_components` rather than through `is_compatible_with`, and
        deliberately so: `_normalize` erases a stray ampersand along with every other non-
        alphanumeric character, so "& Greg Hildebrandt" and "Greg Hildebrandt" are the SAME string
        by the time the direct membership test sees them and that test already answers both
        identically. The guard is therefore unobservable from outside - it exists to keep the
        decomposition itself honest for any future consumer, which is what this asserts."""
        assert _joint_credit_components("& Greg Hildebrandt") == ()
        assert _joint_credit_components("Greg Hildebrandt &") == ()
        assert _joint_credit_components("&") == ()
        assert _joint_credit_components(" & ") == ()

    def test_a_non_joint_printing_artist_is_compared_exactly_as_before(self):
        """Nothing about the ordinary path moves: an artist with no separator in it is still a
        plain normalized set-membership test, both ways."""
        result = recover_artist_from_card_text("", "204/361R\nCLB ¢ EN LINDSEY LOOK\n", LEXICON)
        assert result is not None
        assert result.is_compatible_with("Lindsey Look")
        assert result.is_compatible_with("lindsey look")  # normalized comparison, unchanged
        assert not result.is_compatible_with("Mark Tedin")
        assert result.is_compatible_with("")  # absent data is never a contradiction, unchanged

    def test_storage_is_untouched_by_the_widening(self):
        """`compatible_names` is NOT widened - only the contradiction test is - so the value the
        module is willing to STORE cannot change. Card 679 still resolves to exactly one canonical
        name, and the honesty property (store only when exactly one artist fits) is intact."""
        result = recover_artist_from_card_text(
            "", "034/577 R ,\n2X2 « EN © GREG HILDEBRANDT & TIM HILDEBRAMBT2022 Proxy * Not for Sale\n", LEXICON
        )
        assert result is not None
        assert result.canonical_name == "Greg Hildebrandt"
        assert len(result.compatible_names) == 1
        # An ambiguous read is still unstorable - widening compatibility did not force a choice.
        ambiguous = recover_artist_from_collector_line("059/274R\nDMR ¢ EN RON SPEA", LEXICON)
        assert ambiguous is not None and ambiguous.canonical_name is None

    def test_the_separator_vocabulary_is_ampersand_and_nothing_else(self):
        """Guards the census's own finding (module docstring): comma is a name suffix, `/` is a
        transliteration, and no other joint form exists in the live lexicon. Splitting on any of
        them would manufacture "Jr." as an artist."""
        assert _joint_credit_components("Greg Hildebrandt & Tim Hildebrandt") == (
            "Greg Hildebrandt",
            "Tim Hildebrandt",
        )
        assert _joint_credit_components("A&B") == ("A", "B")  # whitespace around `&` is optional
        assert _joint_credit_components("Edward P. Beard, Jr.") == ()
        assert _joint_credit_components("宋其金/Song Qijin") == ()
        assert _joint_credit_components("Tyler Jacobson, age 39") == ()
        assert _joint_credit_components("Rebecca “Don't Mess with Me” Guay") == ()
        assert _joint_credit_components("Lindsey Look") == ()
        assert _joint_credit_components("") == ()


class TestNameArtistLookup:
    """The Stage C resolver for the narrowing (real ORM). Owns NO name normaliser of its own - it
    delegates entirely to `local_identify_printing_tags.CandidateNameIndex.candidates_for`, which
    is what keeps both halves of the predicate in one name space."""

    def test_resolves_a_card_name_to_the_artists_who_illustrated_it(self, db):
        CanonicalCardFactory(name="Mystic Remora", artist__name="Ron Spears")
        CanonicalCardFactory(name="Mystic Remora", artist__name="Ron Spencer")
        CanonicalCardFactory(name="Counterspell", artist__name="Mark Tedin")

        lookup = build_name_artist_lookup()
        assert lookup("Mystic Remora") == ("Ron Spears", "Ron Spencer")
        assert lookup("Counterspell") == ("Mark Tedin",)

    def test_it_uses_the_shared_normaliser_rather_than_the_raw_name(self, db):
        """`to_searchable` (via `candidates_for`) is what makes punctuation/case/bracket
        differences between an uploaded filename and the catalog name a non-event."""
        CanonicalCardFactory(name="Vazal, the Compleat", artist__name="Mark Tedin")

        lookup = build_name_artist_lookup()
        assert lookup("vazal the compleat") == ("Mark Tedin",)
        assert lookup("Vazal, the Compleat (1)") == ("Mark Tedin",)

    def test_an_unresolvable_name_reports_an_honest_empty_tuple(self, db):
        """A genuinely custom upload has no canonical printing, which every consumer reads as
        "don't narrow" - never as "no artist is allowed"."""
        CanonicalCardFactory(name="Counterspell", artist__name="Mark Tedin")

        lookup = build_name_artist_lookup()
        assert lookup("TreacheryGame_04") == ()
        assert lookup("") == ()
