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
    build_artist_lexicon,
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
