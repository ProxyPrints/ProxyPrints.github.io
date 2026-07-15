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

**Superseded by Stage 7 (unified question feed) below** — `PrintingTagQueue.tsx`,
`GenericVoteQueue.tsx`, `PrintingConfirmStrip.tsx`, and `ModerationQueue.tsx`
(the tab switcher and its four tab bodies) were deleted as part of that
change; their mechanics (starburst, sticky panel, reveal animation,
candidate grid) live on, extracted into `cardPanel.tsx` and reused by the
new `QuestionFeed.tsx`. This section is kept as the historical record of
how those mechanics were originally built — still accurate for that, just
not for "what renders today."

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

## Stage 4: no-match reason tags + post-vote follow-up strips

A resolved printing vote and an explicit "No match" vote both used to
advance the queue with zero follow-up (or, for no-match, the general
`AttributeVotingPanel`) — no fast way to capture _why_ a card had no
match, and no prompt to confirm full-art/borderless while the card was
still on screen. Two new, narrowly-scoped strips render in
`PrintingTagQueue.tsx` between a vote submitting and the queue
auto-advancing, both a brief, skippable dwell that never blocks
advancing:

- `PrintingConfirmStrip` (after a vote resolves a printing) — two chips,
  "Full art"/"Borderless", pre-filled (highlighted) from the resolved
  candidate's own `fullArt`/`isBorderless` flags. A tap casts one
  `CardTagVote` for the existing `Full Art`/`Borderless` tags (seeded by
  `cardpicker.default_tags`, not new) with polarity matching the
  preview. No new tags, no new endpoint.
- `NoMatchReasonStrip` (after an explicit "No match" vote) — six chips
  for a new reason-code taxonomy (below). One tap casts one positive
  `CardTagVote` and advances. Replaces `AttributeVotingPanel` only in
  this specific branch — a card that's still contested from a candidate
  pick (not an explicit no-match) keeps showing `AttributeVotingPanel`
  unchanged.

Both strips reuse the existing `CardTagVote`/`submitTagVote` machinery
end to end — no new backend endpoints or vote types, just narrower UI
over what Stage "attribute voting" already shipped.

**`isBorderless` added to `PrintingCandidate`**: the schema had
`fullArt` but no border-color-derived field, so `PrintingConfirmStrip`
couldn't pre-fill a borderless preview from data "already in the
payload" as originally assumed — it wasn't. Added via the quicktype
regeneration step (`schemas/schemas/PrintingCandidate.json` →
`cd schemas && npm run build`), wired in
`CanonicalCard.serialise_as_printing_candidate()` as
`metadata.border_color == "borderless"`. Verified against live data
first (read-only `CanonicalPrintingMetadata.objects.values("border_color").annotate(...)`
query) rather than assumed from general Scryfall knowledge: the stored
values are exactly `black`/`borderless`/`white`/`gold`/`silver`/`yellow`.

**Reason-code taxonomy — six new `Tag` rows, seeded by a management
command, not a migration**: `custom-art`, `altered-frame`, `upscaled`,
`ai-art`, `no-collector-line`, `non-english`
(`cardpicker/reason_tags.py`, `manage.py seed_no_match_reason_tags`,
mirroring the existing `cardpicker/default_tags.py`/
`seed_default_tags` pattern exactly). **These names are a federation
interchange contract** — other instances consuming our vote export
expect these exact strings; renaming any of them is a breaking change,
not a refactor.

A first pass seeded these via a data migration instead, per the
original task spec. That broke 5 unrelated tests
(`test_views.py::TestGetTags::*`, `test_tag_votes.py:: TestPostTagConsensus::test_returns_an_entry_for_every_seeded_tag`) —
they assert the _complete_ set of `Tag` rows, and document that a fresh
DB has zero real `Tag` rows besides the synthetic, never-persisted
`"NSFW"` pseudo-tag (`cardpicker/tags.py`). `seed_default_tags` is
deliberately **not** wired into any migration for the same reason: a
migration runs unconditionally at DB-setup time (including the test
DB), permanently seeding rows nothing asked for. Switched to a command
to match that established convention; suite back to the known 4-failure
baseline (2 unrelated `moxfield` network tests, 2 unrelated
`test_sources.py` path issues) afterward.

**Deliberately a separate taxonomy from `DEFAULT_TAGS`**, not a reuse:
`upscaled`/`custom-art`/`ai-art` cover near-identical concepts to the
existing `Upscaled`/`Custom`/`AI-Generated` (which parse filename
bracket content at _upload_ time), but these are cast by a _human_ as
the reason they picked "no match" in the queue — kept as distinct rows
(exact-string-distinct, case included) so the two vote populations
don't silently merge into one consensus.

`Tag` has no `description` field — the descriptions given in the task
spec live as documentation only (`reason_tags.py`'s module comment,
mirrored as frontend display copy in `NoMatchReasonStrip.tsx`), not a
new DB column or serializer field.

**Activation note**: `manage.py seed_no_match_reason_tags` must be run
once after this deploys, or `NoMatchReasonStrip` votes 400
(`post_submit_tag_vote` does `Tag.objects.get(name=...)`, not
`get_or_create` — a miss raises `BadRequestException`, not a silent
no-op). Confirmed live: `Full Art`/`Borderless` (used by
`PrintingConfirmStrip`) already exist in production — `seed_default_tags`
has been run there before — so that strip needs no activation step.

**Graceful degradation for the un-activated case**: `NoMatchReasonStrip`
filters its six chips against `useGetTagsQuery` (the existing, already-
cached `2/tags/` query — no new endpoint/fetch) and hides any chip whose
tag doesn't exist yet, rather than rendering a chip that will only ever 400. While that query is still loading it shows all six optimistically.

**Status: live** (merged as PR #12, 2026-07-14). Activation sequence
completed: django/worker rebuilt and restarted,
`seed_no_match_reason_tags` run (created all 6, none pre-existing — no
prior partial-seed to reconcile), both follow-up strips proven end to
end against the real production API (`api.proxyprints.ca`, not a local
mock): a real no-match vote + `custom-art` reason chip landed as
expected `CardPrintingTag`/`CardTagVote` rows on "Llanowar Elves [FDN]",
and a real resolving printing vote + `Borderless` confirm chip (correctly
polarity `NOT_APPLICABLE`, matching that printing's real
`isBorderless: false`) landed as expected on "Loki, Lord of Misrule
[MSC]". Both cards' test votes were then deleted and the cards
re-resolved to restore their real prior state (the same "cast, verify,
reverse" discipline as Stage 3.5's live proof) — confirmed one genuine
pre-existing `Borderless` vote on the Loki card survived the cleanup
untouched, proving the deletion was scoped correctly to only the test
rows.

**Operational gotcha hit during this activation**: recreating the
`django` container left `nginx` proxying to a stale internal IP (full
502 on every API request) until `nginx` itself was restarted — see
[[../infrastructure.md]]'s Docker/backend deploy section for the
mechanism and the now-standard extra restart step.

## Stage 5: decouple tag identity (`name`) from presentation (`display_name`)

`Tag.name` is both the machine key (votes, `Card.tags`, filename-bracket
matching, federation — see `docs/federation-v1.md`) and, until now, the
only text ever shown to a human. That coupling meant a purely cosmetic
relabel (fixing a typo, adding nicer casing) was indistinguishable from
a breaking rename — both touched the same field. `Tag.display_name`
(nullable `CharField`, additive migration) splits them: `name` stays
forever immutable post-creation, `display_name` is freely editable
presentation text, admin-editable via the already-registered `Tag`
admin (now also in `list_display`/`search_fields`).

**Serialization**: `Tag.serialise()` includes `displayName`;
`schemas/schemas/Tag.json` gained the field (quicktype-regenerated, not
hand-edited — see the note above). Nullable/optional, so it doesn't
disturb any response that doesn't set it.

**Frontend**: one shared lookup, `frontend/src/common/tagDisplayNames.ts`'s
`useTagDisplayName()` — built off the same already-cached
`useGetTagsQuery()` other consumers (e.g. `TagFilter`) already use, so
adding a lookup call site never triggers a new fetch. Flattens the tag
tree (children included) into a `name -> displayName` map and returns a
`(name) => displayName ?? name` function. Wired into every render site
that showed a raw tag name: `TagFilter.tsx` (filter dropdown labels),
`CardDetailedViewModal.tsx` (a card's resolved tag badges),
`TagVotePicker.tsx`, `QueueTagQuestion.tsx`, `NoMatchReasonStrip.tsx`,
`PrintingConfirmStrip.tsx`. API submissions/filters (`includesTags`,
`excludesTags`, `APISubmitTagVote`'s `tagName`, ...) are untouched —
they always send `name`.

`NoMatchReasonStrip`/`PrintingConfirmStrip` previously hardcoded their
own chip label strings, duplicating what `display_name` now owns -
refactored both to look the label up dynamically instead, so editing a
`display_name` in admin changes what's shown without a frontend deploy.
One visible, intentional side effect: `PrintingConfirmStrip`'s "Full
art" chip (a hand-picked lowercase label) now reads "Full Art" (the
seeded `display_name`, matching `Tag.name`'s own casing exactly).

**Seeding**: `seed_no_match_reason_tags` sets `display_name` for its six
tags at creation, and backfills it on an already-existing tag only when
still null (never clobbers a manual admin edit). `seed_default_tags`
gained the identical idempotent pattern, but only for `Full Art`/
`Borderless` — `display_name = name` verbatim for those two (not
renamed, just given an explicit row so no actively-displayed tag
silently relies on fallback); the other eleven `DEFAULT_TAGS` entries
are left with no `display_name` (already nice Title Case `name`s, the
`displayName ?? name` fallback covers them for free).

**Filename tag-extraction pipeline is unaffected, and here's why that
matters**: `cardpicker/tags.py`'s `Tags.get_tags()` builds its raw-token
lookup as `{tag.name.lower(): tag for tag in [...]}`, matched against
`Tag.name`/`aliases` only (`match_tag_fuzzy`, `extract()`) — never reads
`display_name`. `Card.tags` (the persisted, denormalised ArrayField)
stores `tag_object.name`, again never `display_name`. So adding
`display_name` changes nothing about indexing today. The reverse case -
what a future _rename_ of `name` (not what this stage does) would break

- is exactly why `name` needed protecting in the first place: an exact
  `.lower()` match against old filenames would silently stop firing
  unless the old name were preserved as an alias, and every already-
  persisted `Card.tags` array containing the old string would go stale
  relative to the renamed row, with no migration path to reconcile them
  (it's a snapshot array, not a live FK). `display_name` exists precisely
  so that presentation changes never need to risk this at all.

## Stage 6: deductive backfill (AI-weight votes for logically-entailed printings)

Casts `source=deduction` `CardPrintingTag` votes (`cardpicker/deductive_backfill.py`,
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

> **2026-07-15 vocabulary split**: the single `VoteSource.AI` value this
> stage originally wrote (`source=ai`) was split into `VoteSource.DEDUCTION`
> (this stage - pure logical inference, zero image inspection) and
> `VoteSource.OCR` (Stage 8 below - anything that actually looks at the
> card image). Same weight (`PRINTING_TAG_AI_WEIGHT`, setting name
> unchanged) and gate treatment for both - a label split, not a policy
> change; see `cardpicker/models.py`'s `VoteSource` docstring and migration
> `0060_votesource_deduction_ocr_split.py` (schema choices + one-time data
> backfill of every existing `source='ai'` row to `source='deduction'`,
> since every pre-split row came from this stage's own production run).
> `is_human_backed_source()` (`vote_consensus.py`) is the one place that
> now knows which `VoteSource` values are machine-derived, replacing the
> scattered `!= VoteSource.AI` comparisons this doc's examples used to show.

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

**Status: live** (merged as PR #11, 2026-07-14; real production run same
day). `manage.py deductive_backfill_printing_tags --tier all` executed
against production: **D1 = 26,931, D2 = 1,181, total = 28,112** votes
written (a `bulk_create` of `CardPrintingTag` rows directly - never routed
through `resolve_and_persist_printing`, so this write path cannot trigger
`reindex_card_safely`; ES reindex firings from this run are zero by
construction, not merely by observed log silence). Slightly below the
same-day census (D1 26,962 / D2 1,202 / total 28,164, taken hours
earlier) - the ~52-vote gap matches cards resolved or voted on for other
reasons in the interim, consistent with real production traffic between
the census and the run; the command's own `--dry-run` immediately
beforehand reproduced the identical 28,112 figure deterministically.
Post-write live gate check (`verify_zero_resolutions`, the pure
`resolve_printing` path, never persisting): **0/28,112 affected cards
resolved** - the human-backed gate held at scale exactly as designed, no
AI-only vote pushed a card into `RESOLVED` on its own.

5-card spot check (random sample) confirmed every vote as
`source=ai` (since migrated to `source=deduction` by the vocabulary split
above - the underlying rows are unchanged, only the label), `anonymous_id=deductive-backfill-v1`, `confidence` 0.95/0.90
matching its tier, `is_no_match=False`, printing name matching the card
name, and the card's `printing_tag_status` still `unresolved`.
**Confirmed via code path, not just this sample: the queue's candidate
grid highlight is keyed strictly on
`consensus?.resolvedPrinting?.identifier === candidate.identifier`**
(`PrintingTagQueue.tsx`), which only ever populates for a truly
`RESOLVED` card - so the "suggested" printing from a deductive-backfill
vote does **not** surface as a pre-filled highlight in the queue today.
This is the documented, deliberate scope decision above (no "suggested"
badge this stage), not a bug; a UX follow-up to surface AI-only
suggestions visually is a separate, future proposal.

## Moderation layer (stage 1)

The sensitive-tag moderation layer ([[moderation.md]]) builds directly on
this system: a third seeded taxonomy (`seed_sensitive_tags` — NSFW/low-res/
incorrect-info/appropriate-bleed, same command-not-migration convention as
the two above), a privileged-approval gate in `resolve_weighted_consensus`,
and a moderator-only review surface. Briefly folded into the unified
question feed's `moderation` question type when Stage 7 shipped (below),
then split back out into its own Moderation tab (Reports + Drives sub-tabs
— see [[moderation.md]]) once live use showed that made any pending report
displace a moderator's ordinary tagging work for as long as it stayed
pending - `question_feed.py` never serves a pending-approval pair now, for
any role.

## Stage 7: unified question feed (queue redesign)

Replaces the printing/artist/tag/moderation tab switcher with a single
`GET 2/questionFeed/`-driven stream: one question at a time, typed
(`confirm_suggestion` | `identify_printing` | `artist` | `tag` |
`moderation`), each with a `payload` shaped per type. A "dumb ranked
union" v1 — four fixed-priority tiers, first non-empty tier wins, no
cross-tier scoring. Full design rationale (chip taxonomy data grounding,
layout tradeoffs, exact tier queries) lives in
`journal/2026-07-14-queue-question-feed-design.md` (gitignored, local
only) — this section captures the durable facts a future reader needs
without that file.

**Priority tiers**: (1) `confirm_suggestion` — cards with an unresolved
AI-sourced printing vote and no human printing vote yet (28,112 cards at
last count — the full deductive-backfill set from Stage 6); (2) contested
printing/artist/tag pairs, existing per-kind ordering reused verbatim; (3)
`moderation` — pending-approval sensitive tags
(`get_pending_approval_queue_pairs`, unchanged from the moderation layer),
gated on `is_moderator(request.user)` and simply never queried for a
non-moderator request; (4) fresh unresolved. **Own-vote exclusion**: every
tier excludes cards/pairs this exact `anonymous_id` has already voted on
(scoped to `(card, tag)`, not just `card` — a card can carry ~11
independent attribute-chip votes), so a single vote that doesn't itself
resolve consensus doesn't re-serve the same question forever.

**Starvation risk, not silently accepted**: at current volume, a voter
working only this feed will not see a single contested/moderation item
until all 28,112 tier-1 questions are exhausted. Flagged as a known v1
property; an interleaved/weighted union is the likely v2 fix, out of scope
here (matches the "ML/scoring schedulers beyond the ranked union"
exclusion from this stage's own brief).

**Attribute chips** (`frontend/src/features/attributeChips/`): tri-state
per chip (untouched → positive → negative → untouched, cycling on tap),
fill color/intensity renders the tag's weighted net polarity (a new
`netPolarity` field on `TagConsensusEntry`, computed by
`tag_consensus.get_tag_net_polarity` — the same weighted-sum math
`get_tag_review_queue_pairs` already computed inline for its own ordering,
now exposed as its own function). Chip taxonomy (11 tags total,
`cardpicker/attribute_tags.py` + `frontend/.../attributeChips.ts`,
kept in lockstep by tag name): standalone toggles Full Art / Borderless /
Showcase / Extended (Art) / Etched, plus two **exclusion groups** — Border
Color (Black/White/Silver) and Frame Style (Old/Modern/Future, bucketing
Scryfall's four raw frame years into three) — encoded as one frontend
constant (`EXCLUSION_GROUPS`) with a comment, per spec. A positive tap on
one exclusion-group chip renders siblings implied-negative (dimmed) and
drives live candidate filtering, but casts no vote on those siblings —
only the frontend styling/filtering is group-aware, the vote write path
never is. Chip set is deliberately narrower than "every value
`CanonicalPrintingMetadata` stores" — `promo_types` is excluded entirely
(mostly production/marketing provenance, not visually identifiable from a
card image) and `frame_effects` is limited to the three values common
enough (849–4165 occurrences at census time) to read as a distinct visual
treatment to a non-expert; `legendary`/`inverted` had higher raw counts
but were excluded as a judgment call (card-type marker and one narrow
product line, respectively, not general printing-identification signal).

**Retraction**: `CardTagVote` previously only supported apply/not-
applicable (`update_or_create`, no delete path) — the tri-state chip's
untouched-cycle-back needed a real "un-vote." Minimal addition:
`post_submit_tag_vote` now also accepts `polarity=0` as a retract
sentinel (never persisted — `VotePolarity`'s two real choices are
unchanged), which deletes the existing `CardTagVote` row instead of
upserting.

**Auto-tag on selection**: picking a printing candidate casts the
existing printing vote plus one positive `CardTagVote` per _standalone_
attribute the candidate itself carries true (not the exclusion groups —
border/frame aren't auto-derivable from a boolean flag the same way).
`PrintingConfirmStrip` (Stage 4) is fully redundant under this — both
attributes it used to manually confirm (Full Art, Borderless) are now
auto-cast — and was deleted rather than kept as dead code.

**No-match gating**: the "No match" candidate is disabled (visually and
functionally) until at least one chip has an explicit (non-untouched)
state, per spec — "describe what you see first."

**Layout**: the starburst/sticky subject-card panel (with its surrounding
chips) renders LEFT and the candidate grid RIGHT on desktop, in plain
JSX/DOM order — the spec's original brief called for the opposite
(candidates left, card right, via a CSS `order` flip so mobile stacking
still worked); changed to this arrangement per direct follow-up
instruction. Mobile stacks in the same DOM order (card+chips first/top,
grid second/below) with no extra CSS needed.

**A latent bug this stage's chips exposed, not introduced**: `CardPanel`
has always used `z-index: -1` (see `cardPanel.tsx`, unchanged since the
original `PrintingTagQueue.tsx`) so the starburst bleeding out from
behind it doesn't paint over the page heading above. That negative
z-index was never actually _contained_ to CardPanel's own column — with
no positioned ancestor between it and the page root, it escapes all the
way up, which happens to be harmless as long as nothing _inside_
CardPanel needs to be clicked (the original component only ever showed a
static image there). This stage is the first time CardPanel hosts real
interactive content (the attribute chips), and the escape turned out to
make CardPanel's entire subtree - chips included - unclickable at the
browser's hit-testing layer: `elementFromPoint` at a chip's own screen
coordinates resolved to its grandparent `Col`, not the chip, even though
the chip visually renders exactly there. Caught via a real
intercepted-click failure in Playwright (multiple false leads chased
first - CSS `order`, dev-server staleness, duplicate mounts - before
isolating it with `elementFromPoint` diagnostics and a bisection between
`z-index: -1` and a throwaway positive value). Fixed by giving the `Col`
wrapping `CardPanel` its own local stacking context: `position: relative`
_and_ an explicit non-`auto` `z-index` (`0`) together - `position: relative` alone does not establish one, a distinction that cost a full
extra round of "fixed, then still broken" before landing on the working
combination.

**Server deployment step**: `manage.py seed_attribute_tags` must run once
before this feature is live (idempotent, same pattern as
`seed_sensitive_tags` — see [[moderation.md]]'s checklist). Without it,
the six non-default-taxonomy chips (Etched, Black/White/Silver Border,
Old/Modern Border, Future Frame) 400 on tap; `Full Art`/`Borderless`/
`Showcase`/`Extended` already work since they're seeded by the existing
`seed_default_tags`.

## Stage 8: local (zero-API-cost) printing-identification backfill pilot

**Status: built and pilot-run against live production** (2026-07-15,
`worktree-local-printing-id-pilot`, PR #22). Code + tests merged; a real
`--limit 300 --engine both --nice` invocation ran against the live DB and
its full results are summarized below. **Full-catalog run explicitly NOT
executed** - see "Real pilot run results" below for why (a ~13-day
single-process projection). See
`journal/2026-07-15-local-printing-id-pilot.md` (machine-local, not
committed) for the complete data dump this summary is drawn from.

Sibling to Stage 6's deductive backfill, same non-negotiable principle
(a vote is always just a vote, never a direct resolve - the human-backed
gate in `vote_consensus.resolve_weighted_consensus` still applies), but
sourced from actually looking at the card image instead of pure logical
deduction from existing structured data - two independent local (no paid
API calls) pass-1 engines, plus a pass-2 fallback for cards pass 1 can't
reach at all:

- **L1, OCR**: Tesseract on a cropped, preprocessed collector-line region
  (bottom-left corner, grayscale/upscaled/thresholded). Parses candidate
  (set code, collector number) pairs from the raw text and only casts a
  vote when the parse matches **exactly one** of the card's own
  name-candidates - weak OCR is made safe by this validation rail, not by
  trusting the OCR output itself. Never writes `is_no_match`.
- **L2, perceptual hash**: art-region phash comparison against each
  name-candidate's Scryfall art crop, voting only when there's a clear
  single best match (distance threshold + margin over the second-best,
  recalibrated from real production data - see the journal for the
  calibration history). `CanonicalCard.image_hash` (`models.py`) already
  exists as a `BigIntegerField` for exactly this - added when
  `import_canonical_card_data` first shipped ("CanonicalCard population
  fix" above) but never computed in production (`--skip-image-hash` was
  used for the real import) - so this pilot is the first thing to
  actually populate it, lazily, only for candidates it needs. Capped at
  12 candidates per name (basic lands/staples can have hundreds - see
  "Real pilot run results" for how often this cap fires).
- **Pass 2, fallback** (`local_fallback.py`, `local-fallback-v1`): fires
  only when pass 1 (either engine) produced no accepted vote for a card -
  the old-border-frame case (no collector line printed on the card face
  at all, just an "Illus. `<artist>`" credit). Evidence-combination model
  across border-color sample, artist-name OCR fuzzy match, and set-symbol
  phash (found unreliable in practice, kept but effectively disabled via
  a strict threshold - see `local_fallback.py`'s module docstring for the
  full negative finding): a vote is cast only when the intersection of
  every sub-check that produced a reading narrows to exactly one
  candidate.
- Border-color sampling and frame-style classification (OCR-collector-
  line-present vs. Illus.-anchor-present) run for **every** processed
  card regardless of printing-vote success, casting standalone
  attribute-chip votes (Black/White/Silver Border, Borderless, Old/Modern
  Border) - and, when a printing vote **is** confirmed for that card this
  run, preferring ground truth from that printing's own
  `CanonicalPrintingMetadata` (Scryfall `border_color`/`frame`) over the
  heuristic estimate. The same heuristic reading also feeds a
  **consistency check**: if a card's observed frame class contradicts its
  matched printing's real frame value, the printing vote itself is
  withheld (kept as a frame-vote-only outcome) rather than trusting an
  art/OCR match that likely landed on the wrong printing.
- All engines vote under `VoteSource.OCR` (the 2026-07-15 split of the
  old single `VoteSource.AI` value into `DEDUCTION`/`OCR` - see
  `models.py`'s `VoteSource` docstring; same weight/gate treatment as
  before, individual technique still distinguishable via `anonymous_id`)
  - when OCR and phash both vote on the same card and agree, both votes
    stand as independent evidence; on disagreement, **neither** is written
    (logged instead - see the journal's disagreement examples).

**Environment**: resolved via a host-side venv pointed at the
already-`127.0.0.1`-exposed Postgres/Elasticsearch ports (zero
Docker/container change) - `tesseract-ocr` installed via host apt,
`pytesseract`/`ImageHash`/`Pillow` via the venv's `requirements.txt`
install. No Dockerfile change made. (A future full-catalog run, if one
ever happens, should revisit baking `tesseract-ocr` into
`docker/django/Dockerfile` instead, per the original tradeoff writeup.)

### Real pilot run results (2026-07-15, `--limit 300 --engine both --nice`)

**32m4.6s wall-clock, 19m36s user + 4m37s sys CPU (≈76% avg utilization of
one core on this 2-CPU box), exit 0.** `--nice` confirmed actually
throttling (process niceness observed alternating 5↔19 during the run).

| Engine    | Attempted | Votes written | Yield |
| --------- | --------- | ------------- | ----- |
| OCR       | 300       | 77            | 25.7% |
| Phash     | 300       | 13            | 4.3%  |
| Fallback  | 210       | 4             | 1.9%  |
| **Total** | —         | **94**        | —     |

**Gate check: 0/94 affected cards resolved** - the human-backed gate held
perfectly at this scale, same result as Stage 6's 0/28,112.

Largest skip bucket by far: OCR's "parsed-but-no-match" at 176/300
(58.7%) - a syntactically valid collector line that didn't match any of
the card's own candidates. Not investigated further in this pilot (out of
scope), but the single most promising lead for improving yield before any
larger run - see the journal for the plausible-causes breakdown.

Attribute votes: border `{black: 280, borderless: 17, white: 3}` (91 from
ground truth, 209 from the pixel heuristic); frame `{modern: 258, old: 14}`, 28 abstains (91 from ground truth, 181 from the OCR/Illus.-anchor
heuristic); **6 frame-mismatches** (printing vote withheld by the
consistency check) - see the journal for all 10 sampled examples and the
per-case reasoning.

**Full-catalog projection: ~171,800 eligible cards remain (of 179,002 raw
eligible pool) → naive linear projection ≈ 306 hours ≈ 12.8 days of
continuous single-process runtime.** This is the key number for any
future decision to scale up - not attempted in this pilot, and not
practical as a single uninterrupted process. Before attempting it:
parallelizing across multiple processes/pk-range partitions (raised, not
yet implemented - see the pre-scale program's scaling proposal below).

### Checkpointing (2026-07-15, pre-scale program item 2)

`run_pilot` no longer does one giant `bulk_create` at the very end -
matches `deductive_backfill.py`'s periodic-flush precedent (`--batch-size`,
default 25 cards - much smaller than `deductive_backfill`'s 2000, since
each card here costs a real image fetch plus OCR/phash CPU work, not just
a DB write). A killed/interrupted run keeps whatever it already flushed;
a plain re-invocation resumes cleanly with no separate checkpoint file,
via the same `select_candidates` idempotence mechanism `--resume` already
relied on. Verified live in tests (`TestCheckpointing`, not just
plausible): flushes happen every `--batch-size` cards, a simulated kill
mid-run leaves the already-flushed cards durably committed and a
follow-up invocation completes exactly the remainder with no duplicates.

**One deliberate deviation from `deductive_backfill`'s pattern**: the gate
check (`verify_zero_resolutions`) now runs after every flush, not once at
the end. `deductive_backfill`'s votes are provably exact by construction
(a violation there is structurally impossible, so one end-of-run check is
belt-and-suspenders); this pilot's OCR/phash/fallback votes are explicitly
weaker, lower-confidence signal where a real violation is more plausible,
and a kill is now an _expected_ event for a multi-day run - a violation in
an already-flushed batch must not sit undetected in the DB indefinitely
just because the process died before reaching a final check that may
never come.

5-vote spot check, 20-vote random admin-link sample, 3 disagreement
examples, and the filename tag-gap census (1,097 unresolved cards with an
unmatchable `expansion_hint`) are all in the journal, not duplicated here.

**Pilot discipline honored**: `--limit 300`, no full-catalog run attempted
per the original hold.

### Phase timing (2026-07-15, pre-scale program item 3a)

Measured against real production data (read-only, no writes) via two
instrumented 30-card samples run through the actual pipeline functions,
not simulated. First sample (OCR + phash only) undercounted real cost -
`run_pilot` also runs border/frame classification and pass-2 fallback for
every card with an image, regardless of pass-1 outcome. Second sample
matched `run_pilot`'s real per-card call sequence exactly:

| phase                           | mean/card | share of measured total |
| ------------------------------- | --------: | ----------------------: |
| `detect_illus_anchor`           |    1.466s |                   33.0% |
| pass-2 fallback (fires ~70%)    |  1.474s\* |                   23.2% |
| `fetch_card_image`              |    1.187s |                   26.6% |
| OCR (crop+preprocess+tesseract) |    0.602s |                   13.5% |
| `classify_border_color`         |    0.159s |                    3.6% |
| phash (hash+compare)            |    0.011s |                    0.2% |

\*mean over the 21/30 cards it actually fired on; contributes 0 for the
other 9.

**Measured total: 4.46s/card** (sum of the above), against the real
300-card pilot run's **observed 6.42s/card** (32m4.6s / 300) - a ~2s/card
gap not fully attributed by this instrumented sample, plausibly per-card
DB queries this sample didn't isolate (the frame-mismatch consistency
check and ground-truth-metadata lookup each re-query `CanonicalCard` once
per confirmed vote) and/or run-to-run network/cache variance (different
selection window, different Scryfall/CDN load). Treat 6.42s/card as the
trustworthy full-pipeline number and the phase breakdown above as
directional (which phases dominate), not a component-by-component
reconciliation.

**`detect_illus_anchor` is the single largest cost, and it's partly
redundant with the main OCR pass**: when pass 1's OCR text doesn't
already contain the "Illus." artist credit, it runs its OWN
crop+preprocess+tesseract pass (a second full OCR call per card, on a
different crop) purely to extract the artist name for pass-2 evidence
and the frame-style classifier's illus-anchor signal. This is a real
optimization target flagged for a future pass, not fixed here - the
addendum ledger closed on ideas beyond items 1-8, and this wasn't one of
them.

### No-match autopsy (2026-07-15, post-merge Hold #1 of the pre-scale program)

Classified all 176 OCR "parsed-but-no-match" cases from the pilot run
(reconstructed via selection-order stability, since the CLI doesn't
persist per-card raw text - a real gap, see the journal). Two real,
contained parser bugs found, both now fixed in `local_ocr.py`:

- **Set-code token position**: `parse_collector_line`'s set-code search
  took the FIRST plausible 3-5 char token in the line, which is virtually
  always leading noise (a watermark, a rarity-letter glyph merging with a
  stray digit into something code-shaped) rather than the real set code
  that always follows the collector number in a genuine card layout. Fixed
  to search the text AFTER the number first, falling back to before only
  if nothing plausible follows.
- **Collector-number leading zeros**: OCR frequently reads a spurious
  leading zero ("0093" for a real "93") that literal string comparison
  silently rejected. Fixed via `_normalize_collector_number` (strip
  leading zeros, keep any trailing variant letter) applied symmetrically
  to both the parsed reading and every candidate's stored value.

**Yield delta, precisely measured** (re-parsing the exact same 176 raw
texts with both the old and new logic, isolating exactly this cohort from
the 3 cards that already matched under the old parser): **47/176 (26.7%)
now match.** Projected full-engine impact: OCR yield 77/300 (25.7%) →
~124/300 (41.3%), a ~60% relative improvement, from a small parser fix.
Confirmed live via a real (non-simulated) `--dry-run` afterward: 62/250
votes on a fresh selection window, consistent with the isolated measurement.

**Yield reconciliation, old logic vs. new logic on that same 250-card
window** (no new OCR work run for this - reusing already-known numbers):
selection-order stability means the 250-card window is the 223-card
reconstructed cohort above (still eligible - no vote was ever cast on a
skip) plus 27 cards never seen in the original 300-card pilot run at all.
Old-logic yield on the 223 known cards is **measured, not estimated**: 3
(the "already-matching" cards, unaffected by the fix) out of 223 - the
other 220 are old-logic non-matches by definition of how they were
classified as skips. Old-logic yield on the 27 unseen cards is **not
measured** - no new work was done to classify them - and is instead
estimated by applying the original pilot's overall old-logic OCR base
rate (77/300, 25.7%) to that count: 27 × 0.257 ≈ 7. Combined old-logic
estimate: (3 + ~7)/250 ≈ 10/250 ≈ **4.0%**, against the confirmed
new-logic **24.8%** (62/250) on the identical window - roughly a 6x
relative lift here, well above the pilot-set's ~1.6x (60% relative)
projection, because this window is disproportionately drawn from cards
that were old-logic failures by construction (the 223-card skip cohort),
not a representative sample of the full catalog. Treat the 24.8%-vs-4.0%
comparison as the honest floor-to-floor number on hard cases, and the
41.3%-vs-25.7% pilot-set figures as the representative full-run
projection - they are not the same statistic and should not be quoted
interchangeably.

Of the 129 cases still unfixed: only 2/176 (1.1%) are genuinely-missing
printings (the parsed set code is real, but no `CanonicalCard` row exists
for that (set, number) at all); the remaining 127/176 (72.2%) are true
OCR garbage with no salvageable signal - a meaningful fraction of which
traces to one specific custom-frame Drive source
(`Source pk=1, "WilfordGrimley"`, "Custom Cardbacks and alternate frames
with Upscaled images") whose non-standard branding text sits inside the
collector-line crop region and defeats OCR outright; not something a
parsing fix can address.

**Cross-check against the filename tag-gap census (1,097 unresolved cards
with an unmatchable `expansion_hint`, from the pre-pilot addendum): NOT
the same root cause.** All 1,097 have a fully _recognized_
`CanonicalExpansion` code (0 unknown) - the gap is a name-matching problem
(many are `(Front)`/`(Back)` filename-parsing artifacts on basic lands),
unrelated to the OCR token-position bug above. Two separate fixes, not
one parser fix arriving twice - the D2.5 deterministic tier is **not**
implied by this OCR fix and was not built.

## Key files

- Backend: `cardpicker/printing_consensus.py`,
  `cardpicker/printing_metadata_import.py`,
  `cardpicker/integrations/game/mtg.py`, `cardpicker/models.py` (migration
  `0050_canonicalprintingmetadata_cardprintingtag_and_more.py`;
  `display_name` — migration `0056_tag_display_name.py`, Stage 5),
  `cardpicker/search/search_functions.py` (Stage 3 re-rank/filter),
  `cardpicker/documents.py` (Stage 3 widened indexing; Stage 3.5
  `reindex_card_safely`), `cardpicker/tag_consensus.py` (Stage 3.5),
  `cardpicker/reason_tags.py`, `cardpicker/default_tags.py`,
  `cardpicker/management/commands/seed_no_match_reason_tags.py` (Stage 4,
  display_name seeding Stage 5),
  `cardpicker/deductive_backfill.py` + management command
  `deductive_backfill_printing_tags` (Stage 6),
  `cardpicker/question_feed.py`, `cardpicker/attribute_tags.py` +
  management command `seed_attribute_tags` (Stage 7)
- Frontend: `frontend/src/features/printingTags/` (`PrintingTagPicker.tsx`,
  `starburstShape.ts`, `cardPanel.tsx` — the extracted sticky/starburst/
  reveal/candidate-grid mechanics, Stage 7),
  `frontend/src/features/filters/ResolvedAttributeFilter.tsx` (Stage 3),
  `frontend/src/common/processing.ts::getPrintingMatchLabel` (Stage 3),
  `frontend/src/features/attributeVoting/` (`ChipCard.tsx`,
  `NoMatchReasonStrip.tsx` — Stage 4; `QueueTagQuestion.tsx`,
  `ArtistVotePicker.tsx` — reused directly by Stage 7),
  `frontend/src/common/tagDisplayNames.ts` (Stage 5),
  `frontend/src/features/attributeChips/`, `frontend/src/features/ questionFeed/QuestionFeed.tsx`, `frontend/src/pages/whatsthat.tsx`
  (renamed from `printingQueue.tsx` — Stage 7)
- `docs/upstreaming/vote-system.md`, `docs/federation-v1.md` (`name` vs.
  `display_name` interchange-key note, Stage 5)

## Known gaps

- The Stage 7 layout (starburst/card/chip-ring composition) was hand-tuned
  via iterative screenshot review, not built against a real design system -
  owner has flagged that this needs a proper pass with the `/dataviz` skill
  in the future rather than further ad hoc CSS tuning.
- `CanonicalCard.image_hash` was bootstrapped to `0` for every row
  (`--skip-image-hash`) at import time; Stage 8's phash engine is the
  first thing to actually populate it, lazily and only for rows it
  needs - most of the table (any candidate no pilot run has hashed yet)
  is still at the placeholder `0`.
- Client-side (Orama) search has no Stage 3 parity — see above.
- Upstreaming this feature is deprioritized — see
  [[../infrastructure.md]]'s Upstreaming section.
- Tier-1 `confirm_suggestion` volume (28,112) is confirmed via a direct
  live query, not the _live-usage_ starvation impact - whether it actually
  swamps tiers 2-4 in practice (vs. just in raw candidate-set size) is a
  server follow-up.
- `netPolarity`'s optimistic client-side update (set to the tapped
  direction's extreme immediately, reconciled with the server's real
  value once the response lands) isn't linear in vote count once AI/admin
  weights are involved - can't fully verify the two never visibly diverge
  against MSW mocks alone.
- Border Color's v1 chip set omits gold/yellow `border_color` values, and
  the frame_effects chip set omits `legendary`/`inverted` despite higher
  raw counts than the chips that made the cut - both flagged as judgment
  calls in Stage 7 above, worth revisiting with real moderator/voter
  feedback.
- Stage numbering: Stage 4 (no-match reason tags, merged as PR #12),
  Stage 5 (tag identity/presentation decoupling via `Tag.display_name`,
  merged as PR #14), and Stage 6 (this document's current stage —
  deductive printing-tag backfill) reflect three concurrently-developed
  branches sharing this one doc file, numbered in landing order to avoid
  collisions.
- **Future work: anonymous_id trust scoring via honeypot questions**
  (2026-07-15, raised during Stage 8's pilot run). Idea: periodically
  serve a voter a card whose printing is already known with very high
  confidence — ideally an already-`RESOLVED` card (real human-backed
  consensus), Stage 6's D1 tier as a fallback pool (0 false positives
  across 27,424 live cards, but still AI-derived, not independently
  human-verified, so using it as "trusted" ground truth to police other
  submissions has a circularity worth being honest about) — without
  telling the voter it's a check, and score their `anonymous_id` based on
  whether they answer correctly. Deprioritize/downweight low-scoring
  anonymous_ids to make data poisoning more costly. Same crowdsourcing
  pattern as reCAPTCHA/Mechanical-Turk gold-standard questions. Known
  limitation before this is worth building: `anonymous_id` is a
  client-generated, trivially rotatable value
  (`frontend/src/common/anonymousId.ts`) with no persisted identity —
  a trust score raises the cost of poisoning (a fresh ID needed per
  abuse attempt) but doesn't stop a determined actor, so it's a speed
  bump, not a hard Sybil defense. Also a genuinely new subsystem, not a
  small addition: a honeypot-injection point in `question_feed.py`
  (nothing currently interrupts the three-tier ranked union with a
  planted question), somewhere to persist per-`anonymous_id` trust state
  (no such model exists today), and a way to feed that score back into
  `vote_consensus`'s per-source weighting — worth its own design pass
  rather than bolting onto an existing stage.
- **Future work: `(Front)`/`(Back)` name-matching fix for the
  `expansion_hint` census gap** (2026-07-15, deferred out of the pre-scale
  program by owner decision — deterministic parser fix, not part of
  Stage 8's OCR/phash engines). The 1,097-card filename tag-gap census
  (cards with an unmatchable `expansion_hint`, all with a fully
  _recognized_ `CanonicalExpansion` code) was cross-checked against the
  Stage 8 no-match autopsy above and confirmed to be a **different root
  cause** — a name-matching problem, not the OCR set-code-position/
  leading-zero bugs the autopsy fixed. Many of the 1,097 are
  `(Front)`/`(Back)` filename-parsing artifacts on basic lands (a
  double-faced-card naming convention this catalog's name-matching
  doesn't strip before comparing against `CanonicalCard.name`). Belongs
  with `cardpicker.deductive_backfill`'s deterministic tiers (D1/D2), not
  Stage 8's visual-disambiguation engines — explicitly not the "D2.5
  arriving for free" the autopsy's cross-check ruled out.
