# Search-operator syntax

Scryfall-style `operator:value` tokens typed directly into the free-text
`/editor` search box (2026-07-22), owner-approved. Supported operators:
`artist:`/`a:`, `border:`, `frame:`, `tag:`, `set:`, `lang:` — any of them
can be negated with a `-` prefix (`-tag:foil`), and a multi-word value can
be quoted (`artist:"Rebecca Guay"`). Operator names are case-insensitive;
an unrecognised operator (e.g. `power:4`) is never silently treated as
literal search text — it's dropped from the query and surfaced as a
structured error instead.

## How it works

- **Parsing** (`cardpicker/search/operator_parser.py`, `parse_query`) is a
  pure string-in/structure-out module — stdlib `re`/`dataclasses` only,
  zero Django/model imports — deliberately liftable into upstream
  mpc-autofill unchanged. It returns `ParsedQuery(residual_text, filters, errors)`: `residual_text` is whatever's left after every recognised
  `operator:value` token is stripped out (still destined for the existing
  fuzzy/precise free-text search), `filters` is a list of
  `ParsedOperator(operator, value, negated)`, and `errors` is a list of
  `ParseError(operator, raw_token)` for any unrecognised operator name. An
  operator with no value (`artist:`) or an operator name containing digits
  (`a1:foo`) both fall through as plain residual text, not an error — only
  a real `letters:value` token with an unrecognised operator name counts as
  an error.
- **Wiring** (`cardpicker/search/search_functions.py`) is where the
  fork-specific decisions live: `get_search`/`retrieve_card_identifiers`
  take an additional optional `operator_filters: list[ParsedOperator]`
  parameter (threaded through from `views.post_editor_search`, which calls
  `parse_query` on each `SearchQuery.query` before searching). Each parsed
  filter becomes its own additional `.filter()`/must-not `Bool` call on the
  Elasticsearch query — deliberately never merged into
  `search_settings.filterSettings`'s own request-global `includesTags`/
  `excludesTags`/`languages` lists, since those are shared across every
  query in one `/editorSearch` batch and mutating them would leak one
  query line's typed operator into every other line in the same request.
  Because every `.filter()` call already ANDs with every other one, two
  operators in one query (`tag:common set:ice`) narrow the result set
  together rather than each independently loosening it — see
  `test_search_operator_syntax.py::TestTagSetLangOperators::test_combining_two_operators_ands_them_together`.
  `tag:`/`set:`/`lang:` land on the exact same ES fields
  (`tags`/`expansion_code`/`language`) the pre-existing structured filters
  already use; `artist:`/`border:`/`frame:` are new fields entirely.
- **Response contract**: `EditorSearchResponse` gained an additive,
  optional `operatorErrors: Dict[str, List[str]]` field (hash-key ->
  human-readable messages, e.g. `["unsupported operator: power"]`) —
  absent/empty means every query in the batch parsed cleanly. Older
  clients that don't read this field are unaffected.

## The artist fallback chain

`Card.get_indexed_artist_name()` (models.py) mirrors `Card.serialise()`'s
existing artist-resolution precedence exactly — four rungs, not the two a
simplified read might suggest, because the search index must never
disagree with what a viewer already sees for the same card:

1. `canonical_artist` (an explicit override)
2. `canonical_card.artist` (a confirmed indexing match)
3. `inferred_canonical_card.artist`, **only** when `printing_tag_status == RESOLVED` (a community-vote-confirmed printing)
4. `inferred_canonical_artist` (artist-vote consensus only, no printing)

`border_color`/`frame`/`frame_effects`/`full_art` follow the same
`canonical_card` → RESOLVED-gated `inferred_canonical_card` precedence
`get_expansion_code`/`get_collector_number` already established (see
`Card._get_indexed_printing_metadata()`), reading from
`CanonicalPrintingMetadata`.

## Case-insensitivity

- `artist:` matches via a dedicated `artist_text` `TextField` using the
  same `fuzzy_analyser` (standard tokenizer + lowercase + asciifolding)
  the main card-name search already uses — `artist:guay` matches a token
  inside "Rebecca Guay". A separate `artist` `KeywordField` (exact/raw
  casing) also exists, mirroring this Document's own pre-existing
  `searchq_fuzzy`/`searchq_precise`/`searchq_keyword` three-fields-one-attr
  pattern, but no operator reads it directly today.
- `border:`/`frame:` are lowercased at the source
  (`Card.get_border_color`/`get_frame`) rather than via an ES normalizer,
  and the query-side wiring lowercases the typed value the same way — the
  same "handle casing in Python, not the mapping" choice
  `get_expansion_code` already made with its own `.upper()`.
- `lang:` reuses the pre-existing `language` field's own
  `precise_analyser` (which already lowercases) and lowercases the typed
  query value the same way `get_enabled_languages` already produces
  lowercase codes for the existing language filter.
- `tag:`/`set:` values are NOT case-folded beyond `set:`'s existing
  `.upper()` convention (mirroring `expansion_code`'s pre-existing term
  filter) — `tag:` matches a `Tag.name` exactly as stored, same as the
  pre-existing `includesTags`/`excludesTags` checkbox mechanism.

## Indexed but not yet wired to an operator

`frame_effects` (array) and `full_art` (boolean) are indexed per the
mapping spec but have no `showcase:`/`extendedart:`/`fullart:`-style
operator yet — reserved for future work. The pre-existing
`fullArtOnly`/`borderlessOnly` `/editor` filters are untouched; they still
read from `cardpicker.printing_consensus.get_resolved_printings`'s
hard-gated (RESOLVED-only, no `canonical_card` fallback) live lookup, a
deliberately different and stricter mechanism than this feature's own
`canonical_card`-first fallback — see that function's own docstring.

## Deploy step

New ES mapping fields (`artist`, `artist_text`, `border_color`, `frame`,
`frame_effects`, `full_art`) only take effect for already-indexed cards
after an owner-gated `python manage.py search_index --rebuild -f` runs —
until then, `artist:`/`border:`/`frame:` return empty results while
`tag:`/`set:`/`lang:` (which reuse pre-existing indexed fields) work
immediately on deploy.

## Known gap (not fixed in this change)

`cardpicker.artist_consensus.resolve_and_persist_artist` does not call
`documents.reindex_card_safely` (unlike
`printing_consensus.resolve_and_persist_printing`, which does) — both
`artist_consensus.py` and the artist-vote submission endpoint were
explicitly out of scope for this change (PROTECTED CORE + a concurrent
PR touching that same endpoint). Practical impact: a printing-tag
resolution already reindexes the whole card (picking up whatever artist
state exists at that moment as a side effect), but a _pure_ artist-vote
resolution with no accompanying printing-tag change currently reindexes
nothing, so the ES `artist`/`artist_text` fields can go stale until the
next full rebuild or an unrelated printing-tag reindex touches the same
card. Fix: add a `reindex_card_safely(card)` call to
`resolve_and_persist_artist` — left for the artist-vote-endpoint work.

## Key files

- `MPCAutofill/cardpicker/search/operator_parser.py` — the pure parser.
- `MPCAutofill/cardpicker/search/search_functions.py` — operator-filter
  wiring (`_apply_operator_filter`, `get_search`'s `operator_filters` arg).
- `MPCAutofill/cardpicker/documents.py` — the new ES mapping fields.
- `MPCAutofill/cardpicker/models.py` — `Card.get_indexed_artist_name`,
  `Card._get_indexed_printing_metadata`, `get_border_color`, `get_frame`,
  `get_frame_effects`, `get_full_art`.
- `MPCAutofill/cardpicker/views.py` — `post_editor_search`'s parse/wire/
  surface-errors call site.
- `schemas/schemas/endpoints/EditorSearchResponse.json` — the additive
  `operatorErrors` field (regenerate via `schemas/`'s quicktype build).
- `MPCAutofill/cardpicker/tests/test_operator_parser.py` — parser unit
  tests.
- `MPCAutofill/cardpicker/tests/test_search_operator_syntax.py` —
  real-Elasticsearch integration tests (each operator, negation, quoting,
  case-insensitivity, artist fallback precedence, unknown-operator
  response shape, plain-text regression).
