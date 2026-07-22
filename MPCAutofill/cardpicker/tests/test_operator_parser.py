from cardpicker.search.operator_parser import (
    ParsedOperator,
    ParsedQuery,
    ParseError,
    parse_query,
)


class TestPlainText:
    def test_plain_query_has_no_filters_or_errors(self):
        result = parse_query("Lightning Bolt")
        assert result == ParsedQuery(residual_text="Lightning Bolt", filters=[], errors=[])

    def test_empty_string(self):
        assert parse_query("") == ParsedQuery(residual_text="", filters=[], errors=[])

    def test_whitespace_only(self):
        assert parse_query("   ") == ParsedQuery(residual_text="", filters=[], errors=[])


class TestEachOperator:
    def test_artist_operator(self):
        result = parse_query("artist:guay")
        assert result.filters == [ParsedOperator(operator="artist", value="guay", negated=False)]
        assert result.residual_text == ""

    def test_artist_alias_a(self):
        result = parse_query("a:guay")
        assert result.filters == [ParsedOperator(operator="artist", value="guay", negated=False)]

    def test_border_operator(self):
        result = parse_query("border:borderless")
        assert result.filters == [ParsedOperator(operator="border", value="borderless", negated=False)]

    def test_frame_operator(self):
        result = parse_query("frame:2015")
        assert result.filters == [ParsedOperator(operator="frame", value="2015", negated=False)]

    def test_tag_operator(self):
        result = parse_query("tag:foil")
        assert result.filters == [ParsedOperator(operator="tag", value="foil", negated=False)]

    def test_set_operator(self):
        result = parse_query("set:lea")
        assert result.filters == [ParsedOperator(operator="set", value="lea", negated=False)]

    def test_lang_operator(self):
        result = parse_query("lang:en")
        assert result.filters == [ParsedOperator(operator="lang", value="en", negated=False)]

    def test_operator_name_is_case_insensitive(self):
        result = parse_query("ARTIST:guay")
        assert result.filters == [ParsedOperator(operator="artist", value="guay", negated=False)]

        result = parse_query("BoRdEr:black")
        assert result.filters == [ParsedOperator(operator="border", value="black", negated=False)]


class TestNegation:
    def test_negated_operator(self):
        result = parse_query("-tag:foil")
        assert result.filters == [ParsedOperator(operator="tag", value="foil", negated=True)]

    def test_negated_alias(self):
        result = parse_query("-a:guay")
        assert result.filters == [ParsedOperator(operator="artist", value="guay", negated=True)]

    def test_negation_composes_with_quoting(self):
        result = parse_query('-artist:"Rebecca Guay"')
        assert result.filters == [ParsedOperator(operator="artist", value="Rebecca Guay", negated=True)]

    def test_double_dash_is_not_negation_falls_through_as_text(self):
        # pathological input: no operator name directly follows the second `-`, so the whole
        # token is opaque literal text, never crashes, never half-parses.
        result = parse_query("--tag:foil")
        assert result.filters == []
        assert result.errors == []
        assert result.residual_text == "--tag:foil"


class TestQuoting:
    def test_quoted_multi_word_value(self):
        result = parse_query('artist:"Rebecca Guay"')
        assert result.filters == [ParsedOperator(operator="artist", value="Rebecca Guay", negated=False)]

    def test_empty_quoted_value(self):
        result = parse_query('artist:""')
        assert result.filters == [ParsedOperator(operator="artist", value="", negated=False)]

    def test_unterminated_quote_degrades_gracefully(self):
        # pathological input: no crash, no exception - the quote character just becomes part of
        # a literal value/text token instead of being interpreted as a real quoted span.
        result = parse_query('artist:"Rebecca Guay')
        assert result.filters == [ParsedOperator(operator="artist", value='"Rebecca', negated=False)]
        assert result.residual_text == "Guay"


class TestUnknownOperatorErrors:
    def test_unknown_operator_produces_an_error_not_text(self):
        result = parse_query("power:4")
        assert result.filters == []
        assert result.residual_text == ""
        assert result.errors == [ParseError(operator="power", raw_token="power:4")]

    def test_unknown_operator_alongside_plain_text(self):
        result = parse_query("power:4 Lightning Bolt")
        assert result.residual_text == "Lightning Bolt"
        assert result.errors == [ParseError(operator="power", raw_token="power:4")]

    def test_unknown_operator_preserves_original_casing_in_error(self):
        result = parse_query("POWER:4")
        assert result.errors == [ParseError(operator="POWER", raw_token="POWER:4")]

    def test_multiple_unknown_operators(self):
        result = parse_query("power:4 toughness:4")
        assert result.errors == [
            ParseError(operator="power", raw_token="power:4"),
            ParseError(operator="toughness", raw_token="toughness:4"),
        ]


class TestMixedTextAndOperators:
    def test_text_before_and_after_operator(self):
        result = parse_query("Lightning Bolt artist:guay foo bar")
        assert result.residual_text == "Lightning Bolt foo bar"
        assert result.filters == [ParsedOperator(operator="artist", value="guay", negated=False)]

    def test_multiple_operators_and_negation_mixed(self):
        result = parse_query('Lightning Bolt artist:"Rebecca Guay" -tag:foil set:lea -lang:ja')
        assert result.residual_text == "Lightning Bolt"
        assert result.filters == [
            ParsedOperator(operator="artist", value="Rebecca Guay", negated=False),
            ParsedOperator(operator="tag", value="foil", negated=True),
            ParsedOperator(operator="set", value="lea", negated=False),
            ParsedOperator(operator="lang", value="ja", negated=True),
        ]

    def test_repeated_same_operator(self):
        result = parse_query("tag:foil tag:extended-art")
        assert result.filters == [
            ParsedOperator(operator="tag", value="foil", negated=False),
            ParsedOperator(operator="tag", value="extended-art", negated=False),
        ]


class TestPathologicalInput:
    def test_operator_with_no_value_falls_through_as_text(self):
        result = parse_query("artist:")
        assert result.filters == []
        assert result.errors == []
        assert result.residual_text == "artist:"

    def test_bare_colon(self):
        result = parse_query(":")
        assert result.filters == []
        assert result.errors == []
        assert result.residual_text == ":"

    def test_many_repeated_dashes(self):
        result = parse_query("-----tag:foil")
        # an operator name must directly follow a single `-` - a run of dashes never resolves
        # to one, so the whole thing is opaque text, not a crash and not a misparse.
        assert result.filters == []
        assert result.errors == []
        assert result.residual_text == "-----tag:foil"

    def test_very_long_query_does_not_crash(self):
        long_query = " ".join(f"word{i}" for i in range(2000)) + " artist:guay"
        result = parse_query(long_query)
        assert result.filters == [ParsedOperator(operator="artist", value="guay", negated=False)]
        assert result.residual_text.startswith("word0 word1")

    def test_operator_name_with_digits_is_not_recognised_as_an_operator(self):
        # operator names are `[A-Za-z]+` only - `a1:foo` never matches the operator alternative,
        # so (unlike an unknown *alphabetic* operator) it's not even an error, just plain text.
        result = parse_query("a1:foo")
        assert result.filters == []
        assert result.errors == []
        assert result.residual_text == "a1:foo"
