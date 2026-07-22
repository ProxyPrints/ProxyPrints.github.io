"""
Scryfall-style search operator syntax: pure string-in, structure-out parsing of a raw query
string typed into the free-text search box (e.g. `Lightning Bolt artist:"Rebecca Guay" -tag:foil`)
into residual free text (still destined for the existing fuzzy/precise search path) plus a list
of structured operator filters, plus a list of unknown-operator errors.

UPSTREAM-READINESS (owner's explicit condition, 2026-07-22): this module must stay liftable
into upstream mpc-autofill unchanged. It imports nothing beyond the standard library - no
Django, no `cardpicker.models`, no vote/consensus/auth module of any kind - and knows nothing
about what an "artist" or a "tag" IS in this catalog, only that the token `artist:foo` or
`-tag:bar` was present in the string. Every fork-specific decision (which ES field an operator
maps to, how `canonical_artist`/`inferred_canonical_artist` resolve to a name, whether a tag
name exists) lives downstream in `cardpicker.search.search_functions`/`cardpicker.documents` -
see docs/upstreaming/extractable-primitives.md's row for this file.
"""

import re
from dataclasses import dataclass, field

# Canonical operator name -> itself, plus any aliases -> canonical name. Lookup is
# case-insensitive (the raw token is lowercased before this dict is consulted) - "ARTIST:",
# "Artist:", and "a:" all resolve to the same canonical key "artist".
_OPERATOR_ALIASES: dict[str, str] = {
    "artist": "artist",
    "a": "artist",
    "border": "border",
    "frame": "frame",
    "tag": "tag",
    "set": "set",
    "lang": "lang",
}

# Matches one whitespace-delimited "word" that is EITHER a `-?operator:value` operator token
# (value either a `"quoted phrase"` or a bare non-whitespace run) OR, failing that, a plain
# run of non-whitespace characters that becomes residual free text. Operator names are
# `[A-Za-z]+` only (no digits/underscores) - deliberately narrow, so something like a decklist
# quantity prefix or a URL-ish token never accidentally parses as an operator.
_TOKEN_RE = re.compile(
    r"""
    (?P<neg>-)?(?P<op>[A-Za-z]+):(?:"(?P<qval>[^"]*)"|(?P<val>\S+))
    |
    (?P<text>\S+)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedOperator:
    """
    One recognised `operator:value` (or `-operator:value`) token. `operator` is always the
    canonical (alias-resolved, lowercased) name - e.g. both `a:guay` and `artist:guay` produce
    `operator="artist"`.
    """

    operator: str
    value: str
    negated: bool = False


@dataclass(frozen=True)
class ParseError:
    """
    One unrecognised `operator:value` token - e.g. `power:4`. `operator` is the raw operator
    name exactly as typed (NOT lowercased/alias-resolved - there's no canonical form for an
    operator we don't recognise), so a caller can echo it back verbatim in an error message
    ("unsupported operator: power"). `raw_token` is the full original token (including any `-`
    prefix and the value) for callers that want more context than the operator name alone.
    """

    operator: str
    raw_token: str


@dataclass(frozen=True)
class ParsedQuery:
    residual_text: str
    filters: list[ParsedOperator] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)


def parse_query(raw_query: str) -> ParsedQuery:
    """
    Parses `raw_query` into (residual free text, structured operator filters, unknown-operator
    errors). An unknown operator's token is consumed entirely - it contributes to neither the
    residual text nor `filters` - so it can never be silently treated as a literal search term;
    it's surfaced only via `errors`. Everything else (plain words, and any `word:value` whose
    operator name isn't in `_OPERATOR_ALIASES`) that fails to match a known operator falls
    through to residual text unchanged, in its original order and casing - downstream sanitising
    (`cardpicker.search.sanitisation.to_searchable`) handles lowercasing/punctuation itself.
    """
    text_tokens: list[str] = []
    filters: list[ParsedOperator] = []
    errors: list[ParseError] = []

    for match in _TOKEN_RE.finditer(raw_query or ""):
        op = match.group("op")
        if op is None:
            # plain free-text token (the `text` alternative matched)
            text_tokens.append(match.group("text"))
            continue

        canonical = _OPERATOR_ALIASES.get(op.lower())
        value = match.group("qval") if match.group("qval") is not None else match.group("val")
        negated = match.group("neg") is not None

        if canonical is None:
            errors.append(ParseError(operator=op, raw_token=match.group(0)))
            continue

        filters.append(ParsedOperator(operator=canonical, value=value, negated=negated))

    return ParsedQuery(residual_text=" ".join(text_tokens), filters=filters, errors=errors)


__all__ = ["ParsedOperator", "ParseError", "ParsedQuery", "parse_query"]
