"""
Tests for cardpicker.modern_artist_credit (issue #368) - the from-scratch modern (bare-name)
artist-credit recognizer. Pure-function tests only here, against a small in-memory
`LexiconIndex` built from `build_lexicon_index` - no DB access, matching the module's own "no
DB/network in `recognize_artist_credit` itself" design. See test_backfill_modern_artist_names.py
for the DB-touching management-command tests (real ORM, pytest-django's ephemeral test DB).
"""

from cardpicker.modern_artist_credit import (
    MIN_MATCH_MARGIN,
    MIN_RATIO_MULTI_WORD,
    MIN_RATIO_SINGLE_WORD,
    MIN_SINGLE_WORD_CANDIDATE_LENGTH,
    build_lexicon_index,
    recognize_artist_credit,
)

# A small, deliberately-realistic lexicon fixture - real CanonicalArtist.name strings sampled
# from production (module docstring), plus a couple of short/tricky mononyms specifically
# exercising the false-positive guards below.
LEXICON_NAMES = [
    "Karl Kopinski",
    "Hideaki Takamura & Karl Kopinski",
    "Mike Bierek",
    "Mark Tedin",
    "Howard Lyon",
    "Jesper Ejsing",
    "Daarken",
    "Daarken & Jared Blando",
    "Rien.",
    "SETTA",
    "Zoltan Boros",
    "Zoltan Boros & Gabor Szikszai",
    "Julian Kok Joon Wen",
]
LEXICON = build_lexicon_index(LEXICON_NAMES)


class TestRecognizeArtistCredit:
    def test_kopinski_garble_edit_distance_two(self):
        # The flagship real-world case (card evidence id 83867, module docstring):
        # "Kalk Kopinski" for the real "Karl Kopinski", inside a noisy multi-line OCR read with
        # an unrelated glyph-garble prefix ("Te ") and trailing junk.
        raw = ':| battlefield, then shuffle your library.\nTe Kalk Kopinski* "AEE a! Ce gee\n'
        result = recognize_artist_credit(raw, LEXICON)
        assert result is not None
        assert result.matched_name == "Karl Kopinski"
        assert result.candidate == "Kalk Kopinski"

    def test_clean_modern_collector_line_shape(self):
        raw = "RIX *EN %® DANIEL LIUNGGREN\n"
        result = recognize_artist_credit(raw, LEXICON)
        # DANIEL LIUNGGREN isn't in this small fixture lexicon - expect no false match manufactured.
        assert result is None

    def test_exact_multi_word_match_all_caps(self):
        raw = "270/302 U\n2ED * EN © MIKE BIEREK\n"
        result = recognize_artist_credit(raw, LEXICON)
        assert result is not None
        assert result.matched_name == "Mike Bierek"
        assert result.ratio == 1.0

    def test_squished_no_space_single_token_still_matches(self):
        # A real observed shape: OCR drops the space between first/last name entirely.
        raw = "2ED * EN © MARKTEDIN & POLITE FROG PROXIES\n"
        result = recognize_artist_credit(raw, LEXICON)
        assert result is not None
        assert result.matched_name == "Mark Tedin"

    def test_garbled_first_name_still_matches(self):
        # "Howarp" for "Howard" - single-character OCR misread (p/d confusion).
        raw = "EXP* EN > Howarp LYON\n"
        result = recognize_artist_credit(raw, LEXICON)
        assert result is not None
        assert result.matched_name == "Howard Lyon"

    def test_running_prose_neighbour_rejected_not_a_false_positive(self):
        # The exact false positive found and fixed during tuning (module docstring, evidence id
        # 517): "rien." is real French flavor-text prose ("...then, nothing more.") sitting
        # right next to the REAL credit line on the next line down. Must resolve to the real
        # credit, never to the coincidental "Rien." lexicon collision.
        raw = "ensuite, plus rien.\nU 0663\nCMM . FR > JESPER EISING Proxy CARD ~ NOT FOR SALE\n"
        result = recognize_artist_credit(raw, LEXICON)
        assert result is not None
        assert result.matched_name == "Jesper Ejsing"

    def test_standalone_mononym_line_matches(self):
        # A real credit-line-shaped standalone mononym (glyph prefix + name, no surrounding
        # sentence structure) - contrast with the prose-neighbour case above.
        raw = "2020 Custom Proxy » NOT FOR SALE\nBCP ¢ EN %® DAARKEN\n"
        result = recognize_artist_credit(raw, LEXICON)
        assert result is not None
        assert result.matched_name == "Daarken"

    def test_short_single_token_below_length_floor_rejected(self):
        # "Seta" (4 chars) is below MIN_SINGLE_WORD_CANDIDATE_LENGTH (5) even though it fuzzy-
        # matches "SETTA" at a high ratio - the exact false-positive class this floor guards
        # against (found during tuning against evidence id 101's real raw text).
        raw = 'eA NS A eter Mike Bierey "Seta\n'
        result = recognize_artist_credit(raw, LEXICON)
        # "Mike Bierey" -> "Mike Bierek" (a real 2-word garble) should win instead of "Seta".
        assert result is not None
        assert result.matched_name == "Mike Bierek"

    def test_ampersand_collaboration_not_guessed_at(self):
        # OCR drops the "&" - the module deliberately does not try to reconstruct a
        # collaboration credit from a half-visible name (module docstring).
        raw = "KHM «+ FR %© ZOLTAN BOROS Tg\n"
        result = recognize_artist_credit(raw, LEXICON)
        # Falls back to the distinct SOLO lexicon entry "Zoltan Boros", which is correct (not a
        # guess at the collaboration) - not None, but also not manufacturing "& Gabor Szikszai".
        assert result is not None
        assert result.matched_name == "Zoltan Boros"

    def test_four_word_name_matches(self):
        raw = "JULIAN KOK JOON WEN\n"
        result = recognize_artist_credit(raw, LEXICON)
        assert result is not None
        assert result.matched_name == "Julian Kok Joon Wen"

    def test_empty_raw_text_returns_none(self):
        assert recognize_artist_credit("", LEXICON) is None

    def test_pure_noise_returns_none(self):
        raw = "aa fl\n5 . ~ ? Wea ADL - ky L-... ,. i\n"
        assert recognize_artist_credit(raw, LEXICON) is None

    def test_illegible_name_below_ratio_floor_returns_none(self):
        # Too mangled to trust - well below MIN_RATIO_MULTI_WORD against anything in the lexicon.
        raw = "Xz Qw Vv Fj\n"
        assert recognize_artist_credit(raw, LEXICON) is None


class TestThresholdConstantsAreConservative:
    """The literal threshold VALUES matter for the "wrong name worse than none" directive - a
    silent tightening/loosening of one of these should fail a test, not pass unnoticed."""

    def test_single_word_ratio_stricter_than_multi_word(self):
        assert MIN_RATIO_SINGLE_WORD > MIN_RATIO_MULTI_WORD

    def test_margin_is_a_real_gap_not_a_rounding_slop(self):
        assert MIN_MATCH_MARGIN >= 0.05

    def test_single_word_length_floor_excludes_four_letter_tokens(self):
        assert MIN_SINGLE_WORD_CANDIDATE_LENGTH >= 5
