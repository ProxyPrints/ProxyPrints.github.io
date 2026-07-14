# Printing-aware card tagging ("What's That Card?" vote queue)

Additive, upstream-pitchable feature letting users/admins tag which
Scryfall printing a `Card` (a catalog image) depicts, with a
weighted-consensus mechanism to auto-resolve uncontested cases. Stage 1
(schema + consensus + import command) shipped; a generalized
artist/tag-taxonomy layer and a federation-readiness stub have since
merged on top (PR #7).

## Backend design

**Key recon finding that shaped the design**: `CanonicalCard`
(`cardpicker/models.py`) already IS a per-printing model —
`identifier` = Scryfall's printing UUID, `canonical_id` = Scryfall's
`oracle_id`, unique on `(expansion, collector_number)`, own
`artist`/`image_hash`/thumbnails — populated weekly by
`import_canonical_card_data`, which already downloads+caches Scryfall's
`default_cards` bulk file. A fully separate `CanonicalPrinting` model would
have duplicated ~90% of this via a second, independently-scheduled Scryfall
sync that could drift out of agreement. Decision instead:
**`CardPrintingTag.printing` FKs directly to the existing `CanonicalCard`**;
a new `CanonicalPrintingMetadata` model (OneToOne to `CanonicalCard`) holds
only the Scryfall fields `CanonicalCard` doesn't already store (full_art,
border_color, frame, frame_effects, promo_types, edhrec_rank,
printings_count, released_at, lang).

`cardpicker/printing_consensus.py` (`resolve_printing(card)`) — weighted-
vote formula: user weight 1, admin weight `PRINTING_TAG_ADMIN_WEIGHT`
(default 5), ai weight `PRINTING_TAG_AI_WEIGHT` (default 0.5).
`PRINTING_TAG_MIN_VOTES` is compared against **summed weight**, not raw row
count — that's what makes a single admin vote alone clear the default
threshold of 2, with no special-cased branch, just the one unified formula.
A winning group additionally needs `PRINTING_TAG_MIN_SHARE` (default 0.6)
of total weight AND at least one non-AI vote, so no volume of AI-only votes
can resolve consensus alone. Settings live in `MPCAutofill/settings.py`.

`cardpicker/printing_metadata_import.py` + management command
`import_scryfall_printing_metadata` reuses the same
`scryfall_cache/default_cards.json` cache path as `import_canonical_card_data`
(within the same 7-day window, only one of the two commands actually
downloads); skips rows whose Scryfall id has no matching `CanonicalCard`
rather than doing its own lang/paper filtering (that boundary already lives
in `MTGIntegration`).

## CanonicalCard population fix (data pipeline)

`CanonicalCard` had 0 rows despite `CanonicalExpansion` having 1000+,
because `import_canonical_card_data` was silently hanging for its full
12-hour django-q timeout. Root-caused and fixed in
`cardpicker/integrations/game/mtg.py`:

- No `requests.get(...)` call had a `timeout=`, so one stalled Scryfall
  connection could hang a worker thread forever.
- The `ThreadPoolExecutor` was submitted-and-immediately-`.result()`'d one
  row at a time inside the loop — effectively fully serial despite
  `max_workers=10`. Fixed to submit all rows up front, gather at the end.
- Scryfall's bulk file can legitimately contain more than one printing for
  the same `(expansion, collector_number)` slot (a language-exclusive
  variant alongside the English one), which violated `CanonicalCard`'s
  uniqueness constraint and crashed the import. Fixed with a slot-ownership
  mechanism that keeps the English printing and skips/displaces non-English
  duplicates for the same slot.
- Added `--skip-image-hash`: the per-card perceptual-hash step dominates a
  full import's runtime, and nothing in the codebase reads
  `CanonicalCard.image_hash` yet — bootstraps metadata from the bulk JSON
  alone (`image_hash=0`), deferring real hash computation until hash-based
  matching actually exists. A full import (~113k rows post-dedup) now takes
  about a minute instead of hanging.
- Verified end-to-end against real Scryfall data:
  `CanonicalCard.objects.count() == 113224`,
  `CanonicalArtist.objects.count() == 2505`, and
  `import_scryfall_printing_metadata` produced 113,224
  `CanonicalPrintingMetadata` rows against that real data.

## Frontend: vote-queue UI ("What's That Card?")

`PrintingTagQueue.tsx` (standalone queue page) and `PrintingTagPicker.tsx`
(embedded picker in `CardDetailedViewModal.tsx`) present candidate
printings for a card with a themed starburst background, animated flicker,
and hover-zoomed candidate thumbnails. Current state (after several rounds
of visual iteration):

- `starburstShape.ts` — a seeded PRNG (mulberry32) generates alternating
  spike-tip/valley polygon vertices per layer, precomputing 5 frames per
  layer (deterministic) so the shape flickers rather than holding static.
- The card panel is `position: sticky` (measured offset via
  `useStickyTop`, not a hardcoded navbar constant, so it pins at wherever
  it actually rendered rather than jumping to a fixed position on first
  scroll) and full-bleeds to the viewport edges.
- Every candidate thumbnail (including "No match") shows a blue
  `ArtPlaceholder` ("?" background) while loading, hover-zooms uncropped on
  hover, and has no border (a border previously clipped the hover-zoomed
  art against a stationary frame).
- Consensus-resolved candidates get a solid blue `CandidateButton`
  highlight instead of Bootstrap's default green `success` variant.
- Animation is skipped under `prefers-reduced-motion` (checked once via
  `matchMedia`, not a live listener).
- See [[../lessons.md]] for the sticky/overflow CSS gotchas, debug-color
  verification trick, and cyclic-animation sampling gotcha found while
  building this.

## Printing-candidate DOM wiring

Candidate buttons in both `PrintingTagQueue.tsx` and `PrintingTagPicker.tsx`
carry the card DOM API's data attributes — see [[card-dom-api.md]].

## Genericized theming identifiers

Every identifier/comment/copy referencing a specific third-party media
franchise (the original visual inspiration for the starburst/quiz-show
theming) was renamed to neutral terms — zero such references anywhere in
code, comments, copy, or docs. Page title/headers: **"What's That Card?"**.
`GenericVoteQueue.tsx` (artist/tag vote modes) already used
`data-testid="vote-queue"`; `PrintingTagQueue.tsx` needed a _different_
testid (`printing-tag-queue*`) rather than reusing that string, because its
`Tab.Pane` stays mounted (hidden, no `unmountOnExit`) after switching tabs —
reusing the same testid would produce two simultaneously-mounted elements
sharing it. Caught via review before shipping — see
[[../lessons.md]] (testid collision check).

## Multi-worker coordination fallout

A cross-session push conflict on this page's file (two sessions pushed to
`master` unaware of each other, landing overlapping edits within a few
lines of each other in `PrintingTagQueue.tsx`) is what motivated adding
`WORKERS.md` as a coordination file — see CLAUDE.md's tooling rules and
`WORKERS.md` itself for the protocol this produced.

## Upstream extraction status

`docs/upstreaming/vote-system.md` is a companion document: a commit-by-
commit cherry-pick classification for the whole vote system (Stage 1
through the federation stub and contested-review generalization, PR #7),
for whoever eventually cuts an upstream extraction branch. It flags that
`PrintingTagQueue.tsx`/`printingQueue.tsx` interleave real vote-queue logic
with the fork-only starburst theming across many commits and should not be
cherry-picked commit-by-commit as a result.

## Stage 3: consumption (search re-rank, attribute filters, match indicator)

Resolved printing-tag consensus previously did nothing outside the vote
queue itself. Stage 3 makes `printing_tag_status == RESOLVED` actually
affect search — gated so unresolved/no-match cards behave exactly as
before.

**Shared hard-gate helper**: `cardpicker/printing_consensus.py::get_resolved_printings(identifiers)`
— batch DB lookup returning `ResolvedPrinting` (expansion_code,
collector_number, full_art, border_color) only for identifiers with
`printing_tag_status == RESOLVED`. Both the re-rank and the attribute
filters call this one function, so they can't drift on what counts as
"resolved."

**Search re-rank** (`cardpicker/search/search_functions.py::retrieve_card_identifiers`):
a narrow post-fetch stable-sort boost, applied _after_ the pre-existing
(unrelated, untouched) ES hard filter on `expansion_code`/
`collector_number` — never a new query path. Tiers: exact set+collector
match > set-only match > everything else (today's order, unchanged).
**Real gap found and closed along the way**: that pre-existing hard filter
is fed by `Card.get_expansion_code`/`get_collector_number`
(models.py:481-497), which historically only read `canonical_card` — a
field set at _ingestion time_ from source-file tags (`cardpicker/tags.py`),
entirely unrelated to voting. Verified empirically (grepped for every
`canonical_card` assignment in application code) that cards which actually
need community printing-tag votes almost always have `canonical_card = None` — meaning the re-rank boost would have been nearly inert for its
own target population, since those cards would never survive the hard
filter to reach the boost step at all. Fixed by widening
`get_expansion_code`/`get_collector_number` to fall back to
`inferred_canonical_card` when `printing_tag_status == RESOLVED` (mirrors
the same fallback chain `Card.serialise()` already uses for
`canonicalCard`), plus widening `documents.py`'s `select_related` to eager-
load it. Same hard match-or-exclude semantics as before — only the data
the filter can see got wider, not the exclude logic itself.

**Attribute filters** (Full art / Borderless, opt-in, default off):
`FilterSettings.fullArtOnly`/`borderlessOnly` (new JSON-schema fields,
regenerated via `schemas/` quicktype build — see below). Applied as a
post-fetch filter in the same function, same `get_resolved_printings`
call reused for both re-rank and filter when both are active (not two
separate lookups). Hard requirement: a card absent from
`get_resolved_printings` (UNRESOLVED/NO_MATCH) always passes the filter —
unresolved cards are unknowns, not mismatches. UI:
`frontend/src/features/filters/ResolvedAttributeFilter.tsx`, states the
"unresolved cards still show" semantic explicitly in the toggle copy.

**Match indicator**: `Card.printingTagStatus` (new field, `Card.serialise()`

- regenerated schema) lets the frontend know a slot's selected card is
  community-resolved. `frontend/src/common/processing.ts::getPrintingMatchLabel`
  (pure function) compares the slot's originating `SearchQuery` (parsed from
  the decklist line) against the selected `CardDocument`'s `canonicalCard`,
  returning a tooltip string or `null`. Rendered in
  `frontend/src/features/card/Card.tsx`'s `CardImage`, reusing the existing
  small-overlay-icon mechanism (`isFavorite`'s `CardIcon`) via a new sibling
  `MatchIndicatorIcon` in the opposite corner (so favorite + match indicator
  never overlap on the same card).

**Bug caught only by the Playwright test, not unit tests**: the shared
`Icon` component (`frontend/src/components/icon.tsx`) didn't forward
`data-testid`/other rest props to the underlying `<i>` element — the
indicator rendered correctly in the DOM but was unfindable by any
testid-based selector. Fixed by spreading `...rest` onto the `<i>`; this
also benefits any other future consumer of `Icon` needing a testid/
aria-label.

**Schema changes require the quicktype regeneration step**, not hand-
editing `schema_types.py`/`schema_types.ts` (both say "Generated by
quicktype. Do not manually modify this file." at the top): edit the
source JSON Schema files in `schemas/schemas/`, then `cd schemas && npm run build`. The raw quicktype output isn't black/isort/prettier-
formatted — run those afterward, or the diff is mostly reformatting noise
unrelated to the actual schema change.

**Known deferred gap**: client-side (local-folder/Google Drive,
Orama-indexed) search gets no re-rank/filter/indicator parity — that path
has no ES/DB access to consult `printing_tag_status`. Flagged explicitly,
not silently built.

## Stage 3.5: immediate reindex on vote transition

Stage 3's re-rank/filters read `printing_tag_status` and the indexed
`expansion_code`/`collector_number` (see the fallback widening above) —
but nothing pushed a changed card into ES until the next scheduled
`update_database` re-scan. A vote that just resolved (or un-resolved) a
printing was invisible to search until that next scan ran.

`cardpicker/documents.py::reindex_card_safely(card)` — the shared,
failure-isolated push (`CardSearch().update([card], action="index")`,
exception caught and logged, never raised: Postgres is truth, ES is a
projection, so an ES hiccup must never break vote submission or roll back
a write that already committed).

`printing_consensus.py::resolve_and_persist_printing` calls it, but only
when the _effective indexed_ printing id actually changes
(`_effective_indexed_printing_id` — the same RESOLVED-gated fallback
`get_expansion_code`/`get_collector_number` use). Covers both directions:
entering RESOLVED, leaving RESOLVED (contested/unresolved again), and the
resolved printing itself changing while staying RESOLVED. A re-resolve
landing on the same outcome (the common case for an already-settled card)
touches the DB but not the index.

`tag_consensus.py::resolve_and_persist_tag_votes` already had an
ES push for `tags` (an ES-indexed field, unlike the printing/artist
denormalised columns) gated on its own `tags_changed` flag — switched to
`reindex_card_safely` for the same failure isolation, no change to when
it fires.

Artist resolution (`artist_consensus.py`) never touches an ES-indexed
field (`inferred_canonical_artist`/`artist_vote_status` only,
serialise-time-only) — confirmed against `documents.py`'s field list, no
hook needed.

## Stage 4: deductive backfill (AI-weight votes for logically-entailed printings)

Casts `source=ai` `CardPrintingTag` votes (`cardpicker/deductive_backfill.py`,
management command `deductive_backfill_printing_tags`) for cards whose
printing is entailed by data already in the catalog, rather than waiting
for a human to vote from scratch on every one of the ~207k untagged
cards. **PRINCIPLE**: a deduction is only valid conditional on the image
actually being an authentic depiction of the named card - this catalog
allows custom art - so a deduction is always a _vote_
(`PRINTING_TAG_AI_WEIGHT`, default 0.5), never a direct
`printing_tag_status`/`inferred_canonical_card` write. The hard
"at least one human-backed vote" gate in
`vote_consensus.resolve_weighted_consensus` means an AI-only vote can
never resolve a card by itself, at any volume - a human still confirms.

**Two confidence tiers**, both keyed on `to_searchable`-normalized name
(the same normalizer `printing_candidates.py`'s queue lookup uses,
post-#460 - no mid-string "the" stripping):

- **D1** (confidence 0.95): the name matches exactly one `CanonicalCard`
  row. Cross-verified against Scryfall's own `printings_count`
  (`CanonicalPrintingMetadata`, not derived from our import) so "exactly
  one row in our table" can't be mistaken for "Scryfall says this card
  only has one printing" when the two disagree - a card is only D1 if
  both agree. A `CanonicalCard` with no `CanonicalPrintingMetadata`
  sidecar at all is treated as unverifiable, never as count-1.
- **D2** (confidence 0.90): the name matches more than one `CanonicalCard`
  row, but `Card.expansion_hint` (already parsed at upload time from a
  lone set-code bracket token in the source filename -
  `cardpicker/tags.py::Tags.extract()`, no new parsing built for this)
  narrows `(name, expansion)` to exactly one row.

**Eligibility, beyond the two tiers above**: `printing_tag_status == UNRESOLVED`, no `canonical_card` (a confirmed ingestion-time match already
settles it), **no existing vote of any kind** - not just no prior
deductive vote. A card with a pre-existing human vote is exactly the
scenario where adding a same-outcome AI vote could push an _already_
human-backed group's weight over the resolution threshold; excluding
these outright removes the scenario rather than relying on the live gate
check below to catch it. Also excludes a card with the `"Custom"` tag
already resolved (`Card.tags` - the PRINCIPLE's precondition is already
known false) and a non-English card (`Card.language` - name-matching
compares against Scryfall's English oracle name, so a coincidental match
against a foreign-language name isn't trustworthy).

**Idempotent / resumable**: the "no existing vote" exclusion above is
also the checkpoint mechanism - an interrupted run leaves whatever it
already committed, and simply re-invoking the command later picks up
exactly where it left off with no separate checkpoint file. `--limit`
caps a single invocation; `--dry-run` selects and counts without writing.

**Live gate check**: after writing (unless `--dry-run`), every affected
card is re-fetched fresh and run through the _pure_ `resolve_printing`
(never `resolve_and_persist_printing` - the check itself must never be
able to cause a write) to confirm none of them actually resolved. Should
be structurally impossible per the paragraph above; verified live against
the real data anyway rather than only trusted in theory. Any violation
raises `CommandError` and stops rather than continuing past it.

**Census** (2026-07-14, `printing_tag_status=UNRESOLVED`,
`canonical_card` null pool of 207,123 / 218,128 total cards): D1 =
26,962, D2 = 1,202 after the Custom-tag/non-English exclusions (27,424 /
1,204 before them). Every D1 candidate's Scryfall `printings_count`
cross-check passed (0 false positives out of 27,424). D2's `(name, expansion)` narrowing occasionally collides across distinct oracle
objects sharing a display name (generic tokens - Treasure, Zombie, Beast,
etc. - and one real card, Llanowar Elves, colliding with an unrelated
same-named token in a token-only set); doesn't affect any individual
vote's correctness since each vote's own `(name, expansion_hint)` pair is
independently verified to narrow to one row.

**Out of scope for this stage**: vision/AI image classification calls
(this is pure logical deduction from existing structured data, zero new
dependencies), `is_no_match` votes, fuzzy/lower-confidence signals beyond
D1/D2, a "suggested" badge in the queue UI, and artist/tag deduction
(printing only).

## Key files

- Backend: `cardpicker/printing_consensus.py`,
  `cardpicker/printing_metadata_import.py`,
  `cardpicker/integrations/game/mtg.py`, `cardpicker/models.py` (migration
  `0050_canonicalprintingmetadata_cardprintingtag_and_more.py`),
  `cardpicker/search/search_functions.py` (Stage 3 re-rank/filter),
  `cardpicker/documents.py` (Stage 3 widened indexing; Stage 3.5
  `reindex_card_safely`), `cardpicker/tag_consensus.py` (Stage 3.5),
  `cardpicker/deductive_backfill.py` + management command
  `deductive_backfill_printing_tags` (Stage 4)
- Frontend: `frontend/src/features/printingTags/` (`PrintingTagQueue.tsx`,
  `PrintingTagPicker.tsx`, `starburstShape.ts`, `useStickyTop`),
  `frontend/src/features/filters/ResolvedAttributeFilter.tsx` (Stage 3),
  `frontend/src/common/processing.ts::getPrintingMatchLabel` (Stage 3)
- `docs/upstreaming/vote-system.md`

## Known gaps

- `CanonicalCard.image_hash` is bootstrapped to `0` for every row
  (`--skip-image-hash`); real perceptual-hash-based matching isn't
  implemented yet.
- Client-side (Orama) search has no Stage 3 parity — see above.
- Upstreaming this feature is deprioritized — see
  [[../infrastructure.md]]'s Upstreaming section.
