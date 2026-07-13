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
`data-testid="vote-queue"`; `PrintingTagQueue.tsx` needed a *different*
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

## Key files
- Backend: `cardpicker/printing_consensus.py`,
  `cardpicker/printing_metadata_import.py`,
  `cardpicker/integrations/game/mtg.py`, `cardpicker/models.py` (migration
  `0050_canonicalprintingmetadata_cardprintingtag_and_more.py`)
- Frontend: `frontend/src/features/printingTags/` (`PrintingTagQueue.tsx`,
  `PrintingTagPicker.tsx`, `starburstShape.ts`, `useStickyTop`)
- `docs/upstreaming/vote-system.md`

## Known gaps
- `CanonicalCard.image_hash` is bootstrapped to `0` for every row
  (`--skip-image-hash`); real perceptual-hash-based matching isn't
  implemented yet.
- Upstreaming this feature is deprioritized — see
  [[../infrastructure.md]]'s Upstreaming section.
