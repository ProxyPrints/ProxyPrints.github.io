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

### CDN fetching + Worker quota (2026-07-15, pre-scale program item 3b)

**The premise "CDN-first fetching" was built on turned out to be wrong,
checked against the actual Worker source (`image-cdn/src/handler/image.ts`,
`R2Service.ts`) before implementing anything.** The pilot's
`get_worker_image_url` requests the `full` tier (matching the PDF export
path, for print-quality output) - and the `full` tier is a **pure
passthrough**: `fetch(url)` straight to Google Drive, every single
request, with zero R2 involvement. Only the `small`/`large` tiers go
through `R2Service.getThumbnail`'s cache-check-then-populate-on-miss
logic. There is no bucket to be "first" about in the pilot's current flow

- it was never touching one.

**Checked whether switching tiers would help anyway - real measurement,
not assumption.** If the pilot switched to the `large` tier (800px,
R2-cacheable), would it benefit from a warm cache? Fetched 20 real
pilot-candidate images through both `full` and `large` Worker endpoints:
**0/20 `large`-tier requests showed a cache hit** (`cf-cache-status: DYNAMIC` on every one; `large` mean 0.881s vs. `full` mean 0.983s -
within noise, both dominated by Google Drive origin latency, not R2 read
time). This isn't surprising in hindsight: the pilot's candidate pool is
specifically the tail of the catalog needing backfill - by definition
these are exactly the cards NOT recently popular enough to have been
browsed (and thus cached) by real users. **Verdict: switching tiers would
not reduce fetch latency or add caching benefit for this workload - stay
on `full` tier, already in use, gives the best-quality image for OCR.**
This also makes addendum item 6's original framing ("OCR resolution floor
re-measured at the CDN's delivered pixel size") moot - the delivered
pixel size doesn't change, since no tier switch is happening.

**Checked a real cache-key gap while in the Worker source, cleared it -
not applicable today.** `R2Service.getImageKey` doesn't include
`jpgQuality` in the cache key (`${imageIdentifier}-${imageSize}-${imageType}`)

- whichever quality first populated an entry is what every later request
  gets, silently. Checked every call site across `frontend/src/` that
  requests `small`/`large`: all either omit `jpgQuality` (defaulting to

100. or pass 100 explicitly - no call site requests a different quality
     today, so this can't currently produce a mismatched-quality cache hit.
     Worth remembering if a quality-tunable thumbnail path is ever added, but
     not an active risk to the pilot (or anything else) as the code stands.

**What the real constraint actually is, and what got built for it**: every
image fetch is one request against the Worker's daily request quota,
which is **shared with live site traffic** regardless of which tier is
requested (a cache hit still counts as a Worker request, just a cheaper
one to serve) - this part of the original concern was correct, just not
for the "bucket-first" reason originally assumed. Implemented
`--fetch-budget` (`run_pilot(fetch_budget=...)`): caps the number of
image fetches a single invocation will make; on exhaustion the run stops
cleanly mid-selection, whatever was already flushed stays committed, and
every card not yet reached is left completely untouched (no vote, no
skip-reason recorded) so the next invocation's ordinary idempotent
selection just picks them up - no special resume handling needed, same
mechanism `--resume`/checkpointing already relies on. Verified in tests
(`TestFetchBudget`): stops exactly at the budget, and a follow-up
invocation with no budget completes the untouched remainder with no
duplicates.

**Quota math**: ~171,800 eligible cards remain, each fetched at most once
(idempotent selection - no repeat fetches across invocations). Spread
across the ~13-day naive full-catalog projection (see wall-clock section
below), that's roughly 13,000/day if evenly sliced - well under the
Worker's 100,000/day shared limit on its own. The real risk isn't the
pilot in isolation, it's concentration: heavy parallelization (item 3d)
compressing the same total fetch count into fewer, busier days, stacked
on top of live traffic's own share of the same quota on those days.
`--fetch-budget` is the safety valve for that scenario - a conservative
per-invocation cap (a specific number is a scaling-proposal decision, not
fixed here) leaves headroom for live traffic regardless of how
aggressively a given slice is scheduled.

**Amendment (same day, owner review): the "shared Worker request quota"
framing above was the wrong quota.** The real question is whether
`lh4.googleusercontent.com` itself (the domain the `full` tier's
passthrough actually fetches from - the Worker's own 100k/day request
quota was never the binding constraint) can take sustained pilot-scale
load without degrading for live traffic. That domain is genuinely shared

- `frontend/src/features/pdf/pdfImage.ts` (PDF export) and
  `frontend/src/features/download/downloadImages.ts` (bulk image download)
  both request the `full` tier already - but had **no rate limiting of any
  kind**, unlike the real Drive API (`GoogleDriveService.executeCall`,
  guarded by the existing `GOOGLE_DRIVE_RATE_LIMITER` binding - a
  DIFFERENT Google domain the `full`-tier image fetch never touches).
  Fixed with a real enforced limiter (`image-cdn`, separate PR ahead of
  this one): a new `IMAGE_FULL_TIER_RATE_LIMITER` Cloudflare rate-limiting
  binding (3 req/s sustained, `wrangler.toml`), wired into `image.ts`'s
  `full`-tier handler via a new `fetchWithRateLimit` helper
  (`src/utils.ts`) that mirrors `GoogleDriveService.executeCall`'s
  check-then-backoff-then-retry pattern - checked-in-limit, delay-and-retry
  on denial, plus a defensive retry on an upstream 429. This is now the
  **primary** protection, shared by all three callers (pilot, PDF export,
  bulk download); `--fetch-budget` is defense-in-depth on the pilot's own
  pacing, not the main safeguard the earlier paragraphs implied. Lands and
  deploys independently of this pilot's own branch, ahead of any
  full-catalog run.

### Resolution floor + payload reduction (2026-07-15, same review)

**`lh4.googleusercontent.com`'s size-suffix parameter genuinely
re-encodes a smaller image - verified directly, not assumed**: fetched
one real card at `=h200`/`=h400`/`=h800`/native and confirmed real,
progressively smaller dimensions and byte counts each time (native
1146x1600 @ 3.29MB → `=h800` 573x800 @ 892KB → `=h400` 287x400 @ 218KB).
The image CDN Worker already exposes this via the `full` tier's existing
`dpi` query param (`height = dpi * 1110 / 300`, `image-cdn/src/url.ts`)

- the pilot just never passed one, so every fetch requested the
  uncapped native original.

**Empirical resolution floor**, a real 6-way sweep (dpi 100/150/200/250/
300/native) against the same 30-card sample used to validate the
tightened crop box, applying that same tightened box and the production
OCR pipeline at each size:

| dpi           | matched/30 | mean payload |
| ------------- | ---------: | -----------: |
| 100           |          3 |        144KB |
| 150           |          7 |        298KB |
| 200           |         12 |        495KB |
| 250           |         10 |        728KB |
| 300           |          9 |        997KB |
| native (none) |          8 |       1.84MB |

dpi≤150 clearly degrades yield below the native baseline; dpi≥200
matches or **exceeds** it despite a 2-4x smaller payload (plausibly a
smaller re-encoded JPEG rendering small text more cleanly than a full-res
original in some cases - 30 cards is too small a sample to fully explain
the exact ranking, but the floor itself - "150 is unsafe, 200+ is safe" -
is a clear, robust signal). Adopted `DEFAULT_FETCH_DPI = 250` in
`local_identify_printing_tags.py` (a `--fetch-dpi` CLI flag, `0` for
uncapped) - a margin above the empirically-best 200, hedging against
small-sample noise while keeping most of the win (728KB vs. 1.84MB
native, 2.5x smaller). **Pilot-only**: `pdfImage.ts`/`downloadImages.ts`
are untouched and still request full print-quality resolution by design.

### Crop tightening (2026-07-15, pre-scale program item 3c / addendum item 6b)

Tesseract's TSV bbox output, sampled across the same 30-card sample
(both preprocessing polarities), showed every observed collector-number-
shaped text line landing within the top 41.2% / right-hand 74.4% of the
existing crop's own area - meaning the bottom ~59% and left ~26% were
dead space. Tightened `local_ocr.DEFAULT_CROP_BOX` from
`(0.0, 0.90, 0.35, 1.0)` to `(0.06, 0.90, 0.35, 0.965)`, applying a
safety margin over the observed range (not cutting exactly to it, per
the addendum's explicit bleed-variance caution) and leaving the right
edge untouched (text was observed touching that boundary already -
trimming it would risk clipping, not save anything). **Validated, not
just derived**: re-ran OCR with both the old and new box against the
same 30 cards - identical match count (8/30 both) AND identical card-
level match set (same 8 card pks matched both ways) - zero yield
regression on this sample. See `local_ocr.py`'s `DEFAULT_CROP_BOX`
comment for the full derivation.

### Bleed-edge tagging (2026-07-15, addendum item 7)

**Checked whether a bleed tag already existed before proposing anything
new, per the addendum's explicit gate**: `appropriate-bleed` already
exists (`sensitive_tags.py`, 0 cards tagged) - but as a
`TagModerationClass.SENSITIVE` tag, the same category as `low-res`/NSFW,
with its own code comment: _"Sensitive because that verification is
exactly a moderator's co-sign."_ It was designed for human-only
verification. Surfaced this to the owner before building anything -
decision: proceed, cast machine votes on the existing tag anyway (a
SENSITIVE tag still requires a moderator co-sign to resolve either way,
so a vote alone can't misuse it - it's one more signal moderators see,
not an override).

**Detection design, owner-directed**: measure the image's own aspect
ratio against chilli_axe's two known reference card sizes
(`frontend/src/common/constants.ts`'s `CardWidthMM`/`CardHeightMM` =
63x88mm trim; +1/8" bleed per edge = 69.35x94.35mm) rather than any
pixel-color heuristic - purely geometric, so it's inherently
DPI/resolution-independent (verified: 0/15 mismatches between native and
`--fetch-dpi=250`-scaled classification of the same real cards - Google's
resize preserves aspect ratio) and unaffected by whether the card's own
border is visually a normal frame or a borderless full-art printing
(both follow the same file-dimension convention regardless of what's
visible).

- `TRIM_ASPECT_RATIO = 63/88 ≈ 0.7159`
- `BLEED_ASPECT_RATIO = 69.35/94.35 ≈ 0.7350`

**Validated against a real, source-diverse sample** (one card per
distinct source, 40 sources, not the earlier 30-card OCR-selection
sample - this needed source diversity, not OCR-selection-order
diversity): a clean, well-separated bimodal signal. Every source but one
clustered tightly at ratio 0.7325-0.7393 (bleed present); the one
exception measured 0.7163, matching the theoretical trim ratio almost
exactly. Nothing observed in the gap between clusters. Classification:
nearest-reference-ratio, abstaining (no vote) when the ratio is more
than 0.03 from BOTH references (`classify_bleed_edge`,
`local_fallback.py`) - comfortably covers the observed real spread on
either side while still abstaining on a genuinely non-standard image
(a DFC composite scan, a token, a corrupted fetch).

**Wired into `run_pilot`**: fires for every card with a fetched image,
independent of printing-vote success (same "double duty" convention as
border/frame attribute votes) - classification is censused
(`AttributeReport.bleed_votes_by_class`) for every card regardless, but
see the negative-only voting change below for what actually gets
written. `VoteSource.OCR`, confidence 0.7 (`BLEED_EDGE_VOTE_CONFIDENCE`).
No ground-truth counterpart to prefer - unlike border/frame, Scryfall
doesn't encode this at all.

**Negative-only voting (2026-07-16, consolidated respec item 4b -
supersedes the original both-directions design above)**: a vote is now
cast ONLY for a `trimmed` reading (`NOT_APPLICABLE`) - a `bleed` reading
(the ~97.5% common case per the 40-source validation) still counts
toward the census but writes NO `CardTagVote` at all. **Absence of any
vote is the documented convention for "presumed normal bleed"** -
updated in `sensitive_tags.py`'s `SENSITIVE_TAGS` comment alongside this
doc, since the tag's _original_ design comment said the opposite
("absence just means not yet verified") from before this pilot existed.
Rationale: `appropriate-bleed` is `SENSITIVE` and needs a moderator
co-sign regardless of machine votes - voting `APPLY` on the routine 97.5%
case would flood moderation with confirmations of normalcy instead of
surfacing the rare real exception, which is what a SENSITIVE tag is for.
Confidence unchanged (0.7). No new tag seeded - the existing-tag check
(`Tag.objects.filter(name=...).first()`, degrades to no vote if absent)
was already in place before this change.

### DPI-tag audit (2026-07-15, addendum item 8 - report only)

Live, read-only cross-reference of `Card.dpi` (computed once at import
time, `update_database.py`) against both places tag state lives -
`Card.tags` (resolved/baked) and `CardTagVote` (raw votes, including
anything pending a moderator co-sign) - for the `low-res` SENSITIVE tag
specifically. No votes cast, no code changed; report only, per the
addendum's own scope, and `low-res` itself stays untouched by this item
(distinct from `appropriate-bleed` above - see the "Future work" note
below for a follow-up idea that WOULD vote on it, deliberately deferred).

**Findings (218,152 cards, live 2026-07-15):**

| dpi bucket |  count | resolved `low-res` | pending vote | neither |
| ---------- | -----: | -----------------: | -----------: | ------: |
| 0 (unset)  |      4 |                  0 |            0 |       4 |
| 1-99       |      7 |                  0 |            0 |       7 |
| 100-149    |      9 |                  0 |            0 |       9 |
| 150-199    |      3 |                  0 |            0 |       3 |
| 200-299    |     40 |                  0 |            0 |      40 |
| 300+       | 218089 |                  0 |            0 |  218089 |

**Query mechanics sanity-checked before trusting an all-zero result**:
the same `resolved`/`pending` query pattern run against tags known to
have real production data - `NSFW` (339 resolved, via filename-bracket
import tagging, not the vote flow), and `custom-art`/`AI-Generated`/
`Borderless` (1, 1, 13 genuinely pending via the exact same
`tag_votes__tag__name=...` pattern used above) - all returned correct
nonzero counts. The `low-res` all-zero result is a real finding, not a
broken query.

Two things worth flagging, neither actionable within this item's scope:

- **99.97% of cards already report full 300dpi** - `Card.dpi` isn't a
  useful prioritization signal on its own; the sub-300 tail is 63 cards
  total across the whole catalog.
- **The `low-res` tag has never been used, anywhere, by anyone** - 0
  resolved, 0 pending, independent of dpi bucket. The report-flow
  (`CardReportReason.LOW_QUALITY` -> `low-res` `CardTagVote`,
  `sensitive_tags.REPORT_REASON_TO_TAG_NAME`) exists in code and has
  never actually been exercised in production. Not a bug - just means
  there's no existing signal to reconcile against yet, and any future
  automated low-res detection (see below) would be establishing this
  tag's first real usage, not correcting drift from manual reports.

**Future work: art-crop-specific DPI check + Scryfall comparison
(2026-07-15, flagged by owner during this item, deliberately deferred -
not built).** `Card.dpi` measures the FULL card image's resolution, which
this audit shows is essentially always fine (99.97% at 300dpi) - but a
proxy can have a perfectly fine full-image dpi while still having a
genuinely blurry/undersized ART specifically (upscaled source, a bad
crop-and-stretch, etc.), which `Card.dpi` can't see. Sketched design,
explicitly NOT built this pass:

- Reuse `local_phash.ART_CROP_BOX` (already the art-region fraction used
  for phash matching - one definition, not a second one) to crop the art
  region out of the pilot's own fetched image.
- Reuse the just-built `classify_bleed_edge` result to pick the correct
  physical reference height per card (trim 88mm vs. bleed-inclusive
  94.35mm - see the bleed-edge section above) before converting the
  crop's pixel height to a real DPI number, rather than assuming one.
- Cross-check against Scryfall's own official `art_crop` image for the
  same printing (`local_phash._fetch_scryfall_art_crop_url` already
  fetches this, reused not reinvented) as a second, comparative signal -
  independent of the absolute-DPI estimate, catches "much smaller than
  the official art for this exact card" even if the physical-mm math has
  slack in it.
- **This is additive, not a replacement for `Card.dpi`** - `Card.dpi`
  stays as the whole-image import-time measurement it already is; this
  would be a second, art-specific signal alongside it, for a different
  failure mode `Card.dpi` structurally can't catch.
- **Goes straight to the moderation pipeline when built** - `low-res` is
  `TagModerationClass.SENSITIVE` (same property established for
  `appropriate-bleed` above: a moderator co-sign is required to resolve
  either way, so a machine vote alone can't misuse it), so this would
  cast real `CardTagVote`s, not just report - unlike this item's
  DB-audit scope, which deliberately doesn't.
- Deferred rather than built now because it needs its own validation
  pass (a real sample, Scryfall-vs-source comparison, a derived
  threshold with a safety margin - the same discipline every other
  detector in this pilot got) before casting anything real, and this
  item's own scope was report-only.

### Bleed-first crop normalization (2026-07-15, owner-directed, folded into item 3d)

**Owner's question mid-item-8**: since bleed classification is cheap and
purely geometric, should it run FIRST, ahead of everything else, so its
result can normalize every OTHER fixed-fraction crop box in the pipeline?
Investigated rather than assumed: `local_ocr.DEFAULT_CROP_BOX`,
`local_phash.ART_CROP_BOX`, `local_fallback.ARTIST_CROP_BOX`,
`local_fallback.SYMBOL_STRIP_BOX`, and `local_fallback._BORDER_SAMPLE_BANDS`
are all fixed-fraction boxes empirically tuned against real fetched images -
which are ~97.5% bleed-inclusive (the 40-source bleed sample above). That
means they're already correctly calibrated for the bleed-inclusive
majority; the ~2.5% TRIMMED minority is the one case where a box tuned
against a bleed-inclusive image lands in the wrong place, since removing
the bleed margin shifts where the same physical card position falls as a
fraction of the (now smaller) full image.

**`local_fallback.normalize_crop_box(box, bleed_class)`**: a no-op for
`'bleed'` or `None` (abstain); for `'trimmed'`, rescales each fraction by
the same margin-fraction math derived from the bleed-edge section's own
reference geometry (`_WIDTH_MARGIN_FRACTION = 3.175 / 69.35 ≈ 4.58%`,
`_HEIGHT_MARGIN_FRACTION = 3.175 / 94.35 ≈ 3.37%` per edge). Threaded
through all five crop sites via a new `bleed_class` parameter on
`classify_border_color`, `detect_illus_anchor`, `find_symbol_matches`,
`run_ocr_for_card`, and `local_phash.compute_card_art_hash`.

**The border-sample bands got a real empirical check, not just the
derivation, before being included** - their sample position sits close to
where the bleed margin lives (0.03-0.05 fraction from each edge, inside
the ~3.4-4.6% margin), which could in principle mean the EXISTING
(unmodified) bands were already misreading bleed-inclusive images, not
just needing a trimmed-image fix. Sampled 15 real bleed-classified cards
with and without the remap applied: solid-color borders (the common case,
most sources) read IDENTICAL RGB regardless of exact sample position -
border color extends uniformly through the bleed margin in real print
prep. Confirms the existing bands are correct for the majority as-is, and
normalizing is safe to apply unconditionally (a no-op there anyway, since
it only activates for `'trimmed'`).

`run_pilot`'s per-card processing now classifies bleed FIRST (before
OCR/phash/border/frame/symbol/artist), immediately after image fetch -
see `_compute_card`'s docstring.

### Pipeline concurrency (2026-07-15, pre-scale program item 3d)

**Measured the real constraint before designing anything**: this box has
2 CPU cores total, shared with 5 live production containers (Django,
worker, nginx, Postgres, Elasticsearch) - not an abstract "how many
threads" question, a genuine resource-contention one. Also found (while
setting up the measurement) that `mpcautofill_django` doesn't have
tesseract installed at all - confirms the real pilot run's host-venv
execution path is the ONLY one that currently works, not just how it
happened to be run (relevant to item 4's install-path decision).

**Live-contention test, not a synthetic benchmark**: 10 real candidate
cards, dry, fetch+OCR+phash only, run against the live production DB
while a separate probe hit the live API's `2/languages/` endpoint
locally (bypassing Cloudflare) every ~0.3s, comparing latency across
three conditions:

| condition                     | mean latency | p95 latency | wall clock (10 cards) |
| ----------------------------- | -----------: | ----------: | --------------------: |
| idle (no pilot load)          |       79.8ms |      94.7ms |                     - |
| sequential (today's behavior) |       88.7ms |     126.1ms |                13.42s |
| 2-worker concurrent           |       93.9ms |     135.7ms |                 6.34s |

Only ~5ms extra mean latency for 2 workers over the ALREADY-EXISTING
single-threaded impact, for a near-ideal ~2.1x wall-clock speedup
matching the core count exactly - tesseract's subprocess-based OCR
genuinely parallelizes here (the GIL releases during the subprocess
wait). `DEFAULT_WORKERS = 2` adopted as the new default.

**Design: split compute from writes, not a full concurrent rewrite.**
`_compute_card` (new) does the parallelizable half - fetch, bleed
classification (first), OCR, phash, border/frame classification, pass-2
fallback - as a pure function with no DB writes and no shared/nonlocal
state, safe to run via `ThreadPoolExecutor.map()` (which preserves
submission order in its results regardless of completion order).
`run_pilot`'s own loop - votes_batch/tag_votes_batch staging,
disagreement bookkeeping, the ground-truth-preferred attribute override,
the frame-mismatch consistency check, flush/gate-check - stays
single-threaded and in selection order, completely UNCHANGED from
before this split; only where its input comes from changed. Chunked at
`batch_size` granularity (reusing checkpointing's existing boundary,
item 2) rather than a second batching concept - each chunk's compute
pool completes before that chunk's writes are staged and flushed.

`OMP_THREAD_LIMIT=1` set (via `os.environ.setdefault`, respects an
operator's own override) whenever `workers > 1` - without it, N
concurrent tesseract subprocesses could each ALSO try to multi-thread
themselves internally, oversubscribing this box's 2 real cores well
beyond `workers`.

**Fetch budget is now checked between chunks, not per-card** - a chunk
already in flight always completes once started, so the real bound on
an overshoot is one chunk's worth of fetches (`<= batch_size`), not
zero. Consistent with the belt-and-suspenders framing already
established for `--fetch-budget` (item 3b) - the real enforcement is the
Worker's own `IMAGE_FULL_TIER_RATE_LIMITER`, not this counter.

**A real threading bug found and fixed while writing the tests, not
just a design risk avoided in the abstract**: `run_fallback_for_card`'s
own `CanonicalCard.objects.filter(...)` query, executed from a worker
thread, silently returned empty under pytest-django's default
(non-transactional) `db` fixture - a worker thread opens its own DB
connection, which can't see an uncommitted test transaction only the
original connection is inside. Exact same root cause and fix
(`transactional_db`, real commits, TRUNCATE-based cleanup) as
`test_sources.py`'s pre-existing `test_all_sources_scanned_concurrently_local_file`
for `update_database()`'s own worker threads - this is a known, already-
established pattern in this codebase, not a new problem. Not a
production concern (committed data is visible across connections/threads
fine); a test-fixture-only issue, but a real one - the failing assertion
caught it, not a code review guess. New `TestConcurrency` test class
(`transactional_db`-based) validates workers>1 finds a real cross-thread
DB match, workers=1 and workers=4 agree on the same input, and
`OMP_THREAD_LIMIT` is set/unset correctly.

`--workers` CLI flag added (default `DEFAULT_WORKERS = 2`, `--workers=1`
disables concurrency entirely).

### Re-projected full-catalog wall-clock (2026-07-15, pre-scale program item 3e)

**Explicit correction from the owner, applied here**: the original
projection couldn't reuse item 3a's phase-timing numbers unmodified -
those were measured against NATIVE-resolution fetches, and `--fetch-dpi`
didn't exist yet. Re-measured directly rather than assumed:

- **Fetch latency at the real default (`dpi=250`)**: 20 real direct
  fetches against the live CDN Worker, mean **0.509s** (vs. item 3a's
  native-resolution mean of 1.187s - a real, not assumed, 57% reduction).
- **Full per-card compute cost** (fetch + bleed-first + OCR + phash +
  border/frame + pass-2 fallback, everything `_compute_card` does) on 15
  real candidate cards: **2.520s/card sequential, 1.568s/card at
  2 workers (1.61x speedup)** - notably LOWER than the 2.1x seen in item
  3d's own narrower fetch+OCR+phash-only benchmark, because
  `detect_illus_anchor` and pass-2 fallback (item 3a's two LARGEST cost
  components, 33% and 23.2% respectively) also make their own DB queries
  and tesseract calls, which don't parallelize quite as cleanly as pure
  fetch+OCR+phash did. **1.61x, not 2.1x, is the correct real figure for
  a full-catalog projection** - flagging this discrepancy explicitly
  rather than letting the earlier item-3d number stand uncorrected.
- **A real 300-card (`--limit 300`, 392 candidates processed - both
  engines' selections union) dry-run** at the CURRENT code (dpi=250,
  bleed-first, crop-tightened, 2 workers), timed end-to-end via the
  actual management command: **12m10s / 392 = 1.863s/card** for
  compute + the frame-mismatch consistency check + ground-truth-metadata
  lookup (dry-run skips `bulk_create`/the gate check entirely - can't
  measure that component this way). A genuine write-enabled run was
  attempted first and correctly blocked by the auto-mode classifier -
  HOLD #2 gates scaled DB-writing runs, and a fresh 300-card write wasn't
  pre-cleared for this specific measurement; pivoted to `--dry-run`
  instead, which still exercises real fetch/compute/consistency-check
  cost.

**Reconciling the three measurements**: `1.863 - 1.568 = 0.295s/card` is
the consistency-check + ground-truth-lookup overhead alone, at 2 workers

- and since that portion runs single-threaded in the main loop
  regardless of `workers` (only the compute half is parallelized), it's a
  `workers`-invariant constant. The one component with NO fresh
  measurement is `bulk_create`/`verify_zero_resolutions`'s gate-check cost
  (write-path code, untouched by items 3b/3c/3d) - reusing item 3a's own
  residual (old real total 6.42s/card minus old compute-only 4.46s/card
  minus this same 0.295s/card consistency-check estimate = **~1.665s/card**
  inferred write-path cost). Two independently-derived estimates cross-
  validate within 0.1%:

| projection            | compute | consistency-check | write-path (inferred) |  total |
| --------------------- | ------: | ----------------: | --------------------: | -----: |
| single-threaded (now) |  2.520s |            0.295s |                1.665s | 4.480s |
| 2 workers (now)       |  1.568s |            0.295s |                1.665s | 3.528s |
| single-threaded (OLD) |      -- |                -- |                    -- |  6.42s |

**Full-catalog projection** (171,853 cards - the live union of both
engines' eligible pools, fresh count 2026-07-15, up from the ~171,878
figure quoted earlier in this doc - natural drift as votes accumulate):

| scenario                                  |    s/card |    wall clock |
| ----------------------------------------- | --------: | ------------: |
| OLD (native fetch, single-threaded)       |     6.42s |    ~12.8 days |
| NEW (dpi=250+bleed+crop, single-threaded) |     4.48s |     ~8.9 days |
| **NEW (dpi=250+bleed+crop, 2 workers)**   | **3.53s** | **~7.0 days** |

**~45% wall-clock reduction from items 3b/3c/3d combined** (12.8 → 7.0
days) - real, substantial, and cross-validated by two independent
derivations. **Still a full week of continuous host-process runtime** -
this is the single most consequential number for item 4's scheduling
decision (chunked scheduler slices vs. one continuous screen'd process):
a naive one-shot week-long run on a box that also serves live production
traffic is a real operational risk regardless of `--nice` throttling
(no natural checkpoint against an OS update, a reboot, a multi-hour
network blip - though item 2's checkpointing does bound how much work
any single interruption loses). The one inferred (not freshly
re-measured) component - write-path cost - should be validated with a
real, HOLD #2-cleared write run before this projection is treated as
final; the write-path code itself is unchanged by any of this session's
work, so reusing the old measurement is a reasonable but not yet
re-confirmed assumption.

### Phash yield investigation (2026-07-15, pre-scale program item 4)

**A wrong hypothesis, tested and rejected before it reached this doc.**
The item 3e dry-run showed phash yield collapse to 0/300 (0%), down from
the baseline run's 13/300 (4.3%) - and the skip-count redistribution
looked suspiciously exact (13 fewer votes, +8 `no-clear-winner`,
+5 `too-many-candidates`, exactly 13). The obvious suspect: `--fetch-dpi =250` was only ever validated against OCR yield (item 6/3c's sweep
explicitly used "the production OCR pipeline" at each dpi) - never
against phash, which hashes the SAME fetched image. **Tested directly
rather than trusted the correlation**: computed phash match outcomes at
native vs. `dpi=250` resolution for 12 real current-pool multi-candidate
cards - **zero difference in outcome on any of them**. The dpi
hypothesis is rejected.

More likely explanation: the candidate POOL itself shifted between the
two runs - the baseline run wrote 94 real votes (including 13 phash
matches), which are now excluded from selection (idempotence), so the
"next 300" cards by the selection ordering are a genuinely different
set than the original 300. Phash's yield is small enough (4.3% at best)
that which specific 300 cards happen to be sampled plausibly explains
more of the swing than any code change does. Not fully resolved - flagged
honestly as unexplained sample volatility, not asserted as a solved
mystery.

**Verdict: keep phash as-is, no further tuning.** Real but small
contribution (13/300 in the one sample with a nonzero count), zero
false-positive risk (the distance+margin gate is strict - a wrong-but-
confident vote has never been observed), and negligible cost (item 3a:
0.011s/card, 0.2% of total time) - there's no strong case for either
investing more tuning effort or dropping it. Its abstention rate is
simply the honest floor for this signal at pilot scale.

### Scaling proposal + install path (2026-07-15, pre-scale program item 4)

**The real constraint driving this decision**: item 3e's ~7.0-day
(2 workers) / ~8.9-day (single-threaded) full-catalog projection is a
multi-day-to-week continuous workload on a box that also serves live
production traffic. Two scheduling shapes were compared, not assumed -
checked against what actually exists in this codebase before proposing
anything new.

**A real, load-bearing tension found while checking, not assumed away**:
django-q2 infrastructure already exists here (`Q_CLUSTER` in
`settings.py`, an already-running `mpcautofill_worker` container whose
entire job is `python3 manage.py qcluster`, an existing daily
`update_database` schedule seeded via migrations `0043`/`0048`). Its
`Q_CLUSTER` config sets `cpu_affinity: 1` - a deliberate reservation
(alongside `timeout: 12 hours, "extreme upper limit"`) that reads as
intentionally protecting this box's OTHER core for live traffic, not an
arbitrary default. **That directly conflicts with item 3d's validated
`--workers=2` default** - scheduling the pilot through the EXISTING
cluster would effectively cap it at 1 core, meaning the real achievable
rate under that path is the ~8.9-day single-threaded projection, not the
~7.0-day one, unless a second, dedicated cluster/queue with different
affinity is stood up specifically for this workload (more infrastructure
complexity, not evaluated further here - the addendum's own scope is
"a decision," not a second scheduler).

**Option A - screen'd host process, `--workers=2` (recommended)**:

- Works TODAY with zero infrastructure changes - tesseract is already
  installed on the host (`/usr/bin/tesseract`, confirmed while measuring
  item 3d), and the host venv used for every real run in this session
  already proves the path works against the live DB.
- Gets the full validated ~7.0-day projection - the only option that
  does, since it isn't constrained by the existing cluster's
  `cpu_affinity=1`.
- No new Dockerfile/image rebuild, no new `Schedule`/queue
  infrastructure to build and validate.
- **Real gap, not glossed over**: the live-latency-contention
  measurement (item 3d) that justified `--workers=2` as safe was a
  10-card, ~20-second burst test - it validates "briefly safe," not
  "safe sustained for a full week." A longer soak measurement (a few
  hours, not 20 seconds) against live traffic latency is a reasonable
  ask before actually launching a multi-day run, and is flagged here as
  a residual open item for the HOLD #2 package, not resolved by this
  proposal.
- Lifecycle is manual (`screen`, not django-q's built-in retry/crash
  handling) - partially mitigated by item 2's checkpointing (a kill
  loses at most one `--batch-size` worth of unflushed work and resumes
  cleanly on restart), but still needs a human or a `cron` re-invocation
  after a real crash, not automatic retry.

**Option B - chunked django-q nightly slices, existing cluster**:

- Reuses established, already-working infrastructure - the exact
  `Schedule.objects.create(func="django.core.management.call_command", args="'local_identify_printing_tags', '--limit', 'N', ...", schedule_type="D")` pattern already seeds `update_database`/
  `import_canonical_card_data` today (migrations `0043`/`0048`) - a new
  migration doing the same for this command is a small, low-risk,
  precedented change.
- Gets django-q's existing retry/crash-recovery machinery for free.
- **Requires a Dockerfile change**: `mpcautofill_worker` builds from the
  same `docker/django/Dockerfile` `builder` stage as `mpcautofill_django`
  (confirmed by reading it) - neither has tesseract; adding
  `tesseract-ocr` to that stage's `apt-get install` line and rebuilding
  both images is a real, concrete requirement, not a formality.
- Bound by `cpu_affinity=1` unless a second cluster is built (see
  above) - realistically the ~8.9-day single-threaded rate, spread
  across many nights at whatever `--limit` fits comfortably inside a
  night's window (well under the cluster's 12-hour task timeout, to
  leave real margin - a nightly `--limit` sized for ~2-4 hours, not 12,
  is the safer target).

**Recommendation: Option A for the eventual full-catalog run** - it's
faster, needs no new infrastructure, and the pilot's own checkpointing
already covers most of what django-q's retry machinery would otherwise
buy. Revisit Option B only if the longer soak-test flagged above turns
up a real sustained-load problem Option A can't tolerate.

**Host-venv disposition - a real, currently-open gap**: every real run
in this session used
`/home/ubuntu/.claude/jobs/4495614d/tmp/venv` - a job-scoped path that
is cleaned up when this Claude Code job ends. Whichever option is
eventually chosen, a permanent venv needs to live somewhere stable and
documented (`docs/infrastructure.md`) before an unattended host-process
run is launched for real - this doesn't block anything in this pre-scale
program itself (every measurement in this doc was already real, run
against the live DB), but it's a genuine loose end for whoever actually
launches the full-catalog run.

### Dockerized execution, host-venv retired (2026-07-15, closes the item 4 gap above)

Closes the "host-venv disposition" gap flagged in the scaling proposal
above: `docker/django/Dockerfile`'s shared `builder` stage now installs
`tesseract-ocr tesseract-ocr-eng` alongside the existing
`dos2unix gcc netcat-traditional curl libpq-dev` line - both the
`webserver` and `worker` targets inherit it since they both `FROM builder`. Verified end-to-end, not just "image builds": rebuilt the
`worker` image and ran
`python3 manage.py local_identify_printing_tags --dry-run --limit 3 --skip-checks`
inside a one-off `docker compose run --rm worker ...` container against
the real live DB - tesseract resolved (`/usr/bin/tesseract`, v5.5.0),
OCR/phash/fallback/attribute voting all executed and reported real
(dry-run) output. The job-scoped host venv
(`~/.claude/jobs/4495614d/tmp/venv`) used for every prior measurement in
this doc is now retired - no job dependency for this recurring task
lives outside the image anymore.

Build-context note: `docker/django/check_client_secrets.sh` and
`check_drives.sh` require `MPCAutofill/client_secrets.json` and
`MPCAutofill/drives.csv` to exist in the build context (both gitignored,
real content only on-disk per `CLAUDE.md`) - a fresh worktree doesn't
have them by default, since worktrees share git history but not
untracked files. Verifying this Dockerfile change from a worktree
required temporarily copying those two files plus `docker/.env` (needed
at container-run time for `SECRET_KEY`/DB config) in from the main
checkout, with explicit user go-ahead for each, and deleting all three
immediately after the verification container run completed. This is a
one-time verification cost, not a recurring one - normal builds/deploys
happen from the main checkout, where these files already live natively.

This does not change the Option A vs. B scheduling recommendation above
(still Option A, screen'd host process) - it only changes _how_ the
command executes (containerized instead of a host venv) once a
scheduling shape is chosen, and removes one of Option B's stated
requirements ("Dockerfile change...adding `tesseract-ocr`") since that
part is now already done regardless of which scheduling path is picked.

### Coverage-gap + demand ordering, skip-before-fetch (2026-07-15, addendum items 1/3/4)

Full respecification from the owner, superseding the earlier AskUserQuestion-confirmed
interpretations - implemented verbatim, not re-derived.

**Item 1 - coverage-gap prioritization**: `select_candidates`'s ordering is now a full 5-key
tuple, REPLACING the old "multi-candidate names first" primary split entirely (that split is now
only tiebreak #4, "fewer candidates"): (1) names with zero covered printings first, (2)
descending count of uncovered printings, (3) demand rank (item 3), (4) fewer candidates, (5) pk.
"Covered" (`compute_covered_printing_pks`): a printing has >=1 `Card` with `canonical_card`
pointing at it (a confirmed indexing match, no RESOLVED gate needed - already a direct,
non-vote-based signal) OR `inferred_canonical_card` pointing at it with
`printing_tag_status=RESOLVED` - gated on RESOLVED specifically so a machine vote pending human
confirmation does NOT count as coverage, per the owner's explicit clarification. Computed fresh
on every `run_pilot` call (never cached across invocations), so a nightly slice's ordering
reflects human confirmations made in the queue since the previous slice. Fully-covered names
still process, just LAST - redundant identifications add real value (image choice per printing,
coverage-independent border/frame attribute votes). New report metric,
`AttributeReport.uncovered_printings_closed`: of the printings in scope this run that were
uncovered at the start, how many are covered by the end - the run's real progress metric per the
owner ("that number, not raw votes"). Almost always 0 for a machine-only run BY DESIGN, not a
bug: a pilot vote is never a direct resolve (the gate check asserts this structurally), and
"covered" explicitly excludes unresolved machine votes - a printing only counts as closed once a
human confirms it in the queue, which is what item 5 (follow-up) is for.

**Item 3 - demand order via `edhrec_rank`**: already existed as a schema field
(`CanonicalPrintingMetadata.edhrec_rank`, populated by the existing `printing_metadata_import`
Scryfall bulk-data import) - checked live before assuming it needed adding: 101,133/113,224 rows
(89.3%) genuinely populated. `CandidatePrinting` now carries `edhrec_rank` (fetched via
`CandidateNameIndex`'s existing single query, `select_related("printing_metadata")` - zero extra
queries). A name's demand rank is the MINIMUM `edhrec_rank` across its candidates (its most
popular printing, not an average) - missing ranks (~10.7% of rows) sort LAST via a large
sentinel, not first, so "no demand signal" never masquerades as highest-priority. Public Scryfall
data, zero user tracking - explicitly the zero-telemetry-policy-clean substitute for a previously
-parked export-popularity-ordering idea.

**Item 4 - skip-before-fetch**: `RESOLUTION_FLOOR_DPI = 200` (the actual empirical floor from the
6-way dpi sweep above - NOT `DEFAULT_FETCH_DPI = 250`, which is a safety margin above it) applied
against `Card.dpi` (computed once at catalog-import time from the source image's own pixel
height) directly in `select_candidates`' selection query (`.exclude(dpi__lt=...)`) - a source
image already below the floor is never fetched at all, not just never OCR'd. `Card.size` (raw
file bytes) is deliberately NOT used as a second condition despite the addendum's "dpi/size"
phrasing: it's a compression-dependent proxy with no empirical calibration behind it, unlike
dpi's direct, validated sweep - an unvalidated byte threshold would violate this pilot's own
"measure, don't assume" discipline. New `PilotResult.skipped_below_resolution_floor` counter
(`count_below_resolution_floor`, a separate COUNT query, cheap at full-catalog scale) - its own
report line, not folded into the existing `skip_counts` dict (which is populated downstream of a
fetch attempt; a selection-time skip never reaches that loop).

Sequencing note (owner-directed): items 3/4/1 ship together with item 2a (cluster dedup, no
schema change) as one PR. Item 2b (persisting `content_hash` for federation) and item 5
(questionFeed ordering mirror) are deferred, logged as follow-ups, not built here.

Verified: 82/82 pilot tests pass (15 new: `TestCoveragePriority`, `TestDemandRank`,
`TestResolutionFloor`, `TestUncoveredPrintingsClosed`), including a coverage-tier test that
specifically distinguishes "zero-covered" from "most uncovered" (a partially-covered name with
MORE absolute uncovered printings than a zero-covered name must still sort after it) and an
`inferred_canonical_card`-without-`RESOLVED` test (confirms an unconfirmed machine vote doesn't
count as coverage). mypy clean (`MPCAutofill/`, whole-package invocation). `black`/`prettier`
clean.

### Cluster dedup, run-scoped (2026-07-15, addendum item 2a)

Before slicing, `compute_own_image_clusters` phashes OUR OWN eligible images (local only - no
candidate/Scryfall downloads) via the same `local_phash.compute_card_art_hash` the phash engine
already uses, and collapses distance-0 (EXACT 64-bit hash match) groups to one representative
(lowest pk, for determinism) - only representatives reach `_compute_card`; absorbed members never
run their own OCR/phash/border/frame/fallback at all. "One read answers N cards": an accepted
vote on the representative propagates as an identical `CardPrintingTag` (same anonymous*id,
printing, confidence, source) to every absorbed member. Sound by construction: a distance-0 match
among OUR OWN uploaded images most plausibly means a duplicate/shared-source image, not
independent depictions that coincidentally look alike (that's the \_candidate* art-crop clustering
problem the phash engine already handles separately via `DEFAULT_DISTANCE_THRESHOLD=20`, a much
looser bar than 0) - identical image genuinely entails identical printing. Costs one extra fetch
per selected card (the clustering pass itself) to save the far more expensive per-card compute
pipeline on every absorbed duplicate.

Scoped to the printing-identification vote only, not border/frame/bleed attribute votes -
absorbed members never get their own image classified, so there's nothing of theirs to
propagate for those; a documented limitation, not a silent gap. Run-scoped only, no schema
change: no `content_hash` persisted anywhere (that's item 2b, deferred as a standalone future
task for federation-v1's content_hash groundwork). New `AttributeReport.cluster_count`/
`cards_absorbed_into_clusters` report fields.

**A real idempotence gap found and fixed before landing, not just anticipated**: a cluster
member can reach clustering via one engine's independent eligibility (e.g. phash) while already
carrying a vote from a DIFFERENT engine's `anonymous_id` from a prior invocation (the exact
reason it was excluded from that OTHER engine's selection this run). Propagating a same-
`anonymous_id` vote to it anyway would violate `CardPrintingTag`'s own
`(card, printing, anonymous_id)` uniqueness constraint - checked once per run (a single query
across all cluster members, not re-queried per propagation call) and skipped, not attempted.
`ocr_selected_ids`/`phash_selected_ids` also get absorbed into the representative's own
eligibility (a representative must run an engine if EITHER it or any absorbed member was
independently selected for that engine), so clustering can't silently drop an engine's
eligibility just because the specific card that became the representative wasn't itself
originally selected for it.

Verified: 96/96 pilot tests pass (7 new: `TestClusterDedup`), including a test that caught a
genuine test-fixture bug during development (two different solid-color images accidentally
hashed identically - imagehash's DCT-based `phash` has zero frequency content on any uniform
fill regardless of color, so distinguishable synthetic fixtures need actual drawn shapes, not
just a different fill color; the production clustering logic was working correctly the whole
time), a test proving the double-vote/overwrite gap above is actually fixed (not just that some
vote exists), and a test proving the efficiency win itself (an absorbed member's card id is
never passed to `run_ocr_for_card`, not just that it ends up with a vote). mypy clean.
`black`/`prettier` clean.

### Bottleneck split, current pipeline state (2026-07-16, throughput track item 2a)

Re-measured phase timing against the CURRENT code (post items 1/2a/3/4/4b) rather than trusting
item 3a's original breakdown, which predates dpi=250, crop tightening, bleed-first
classification, and clustering entirely. Real instrumented run, 50 selected candidates
(representative-only, post-clustering), against the live DB/API - not simulated:

| phase                                 | mean/card | share (uncorrected) |
| ------------------------------------- | --------: | ------------------: |
| `fetch_card_image`                    |    0.450s |               13.4% |
| `classify_bleed_edge`                 |   ~0.000s |               ~0.0% |
| OCR (crop+preprocess+tesseract)       |    0.478s |               14.3% |
| phash (hash+compare)                  |   ~0.000s |               ~0.0% |
| border/frame (`detect_illus_anchor`+) |    1.206s |               36.0% |
| pass-2 fallback                       |    1.218s |               36.3% |

**Measurement caveat, stated plainly**: this run called fallback unconditionally for every
representative (not gated on pass-1's real accept/reject outcome), so its 36.3% share is
inflated relative to real `run_pilot` behavior (item 3a's original sample: fallback fires
~70% of the time). Corrected estimate using that same 70% rate:
`0.450 + 0.478 + 1.206 + (1.218 × 0.7) ≈ 2.99s/card` sequential, for cards that reach full
compute (clustering representatives only).

**Bonus real data point from the same sample**: 13/50 selected cards (26%) were absorbed into
10 clusters by item 2a's dedup - a materially higher rate than assumed, though from one
50-card sample, not a claim about the full-catalog rate.

**The clear finding: this is CPU-bound, not I/O-bound.** `fetch_card_image` is ~13% of
per-card cost; `detect_illus_anchor`-plus-border-classification and pass-2 fallback together
are ~72% (uncorrected) / ~65% (corrected). This directly answers throughput track item 2a's own
question: **the "6-8 fetch threads, I/O-bound, no core needed" idea does not currently exist as
a mechanism** - `_compute_card`'s single `ThreadPoolExecutor(max_workers=workers)` runs fetch
AND OCR AND phash AND fallback all in the SAME worker, sized for CPU-bound work
(`DEFAULT_WORKERS=2`, matching this box's core count). Decoupling fetch into its own larger pool
would only ever attack the ~13% fetch share - a real potential improvement, but not the
dominant cost, and not built in this pass. This bottleneck split is the evidence that makes
manifest mode (item 2c) and a core-count resize (item 2b) the higher-leverage levers, not a
larger fetch pool.

**Current instance shape** (checked via the cloud provider's own instance-metadata endpoint,
no auth needed - exact shape/region kept out of this public doc, see CLAUDE.local.md/journal
for the specific values): core count matches `DEFAULT_WORKERS=2`'s own derivation (item 3d)
exactly - this box has never had spare cores for a bigger pool without a resize.

### Soak test at the current box, PRE-RESIZE baseline (2026-07-16, throughput track item 2d)

**This measurement is at the box's PRE-RESIZE core count (`--workers 2`) - it is the pre-resize
baseline, NOT the workers=3 post-resize number the resize decision is waiting on.** A separate
post-resize soak test (same 250-card window, same selection/dedup) at a higher `--workers` count
on the resized shape is required before comparing - see the entry below once that lands. Do not
conflate the two numbers. (Exact shape/OCPU/RAM values kept out of this public doc - see
CLAUDE.local.md/journal.)

Real 250-card `--dry-run --workers 2` run (not a burst - the prior `--workers=2` safety
validation was only ~20 seconds/10 cards) against the live DB/API with live services running
normally. Clustering (item 2a) absorbed 70/250 selected candidates (28%) into 59 clusters before
the main loop even started, leaving 180 representatives actually processed - closely matching
the bottleneck-split sample's independently-observed 26% (13/50) absorption rate, two samples
now agreeing rather than one small anecdote. Total wall-clock ~400s (00:16:10 start to 00:22:50
log-file mtime), including container startup/migrate/collectstatic overhead (~45-60s fixed cost,
not pilot processing) - effective throughput **≈1.94s/card** across the 180 processed
representatives, consistent with the previously-established top-down 1.863s/card figure from
the original 392-candidate real run. **Caveat, stated plainly**: this run's progress markers
(50/100/150-candidate checkpoints) weren't individually timestamped, so this confirms
AGGREGATE throughput held up over a real multi-hundred-card window (not just a burst) but
doesn't give intra-run stability granularity (e.g. whether the first 50 cards processed at a
different rate than the last 50) - a finer-grained timing pass would be needed for that
specific claim, not done here.

### Token exclusion + post-resize soak comparison (2026-07-16)

**A real correctness gap found and fixed before trusting any throughput number from this
window**: the first several 250-card soak-test runs at both pre- and post-resize core counts
showed 0/250 OCR votes - a stark regression from the original 94/300 baseline. Diagnosed live
by sampling real OCR output against real candidates for the first 8 selected cards: all 8 were
generic "Beast" tokens (source-uploaded images with `card_type=TOKEN`) with ~90 candidate
printings each across token-only sets. A token's printed collector line reads its PARENT set's
code (e.g. "MM3"), while its `CanonicalCard` candidates use token-specific set codes (e.g.
"tm3c") that never match - structural, not a parsing bug. Item 1's "descending uncovered count"
ordering was front-loading this near-0%-matchable cohort (huge candidate counts, near-zero
coverage) to the very front of every real selection. Fixed: `_eligible_base_queryset` now
filters to `card_type=CARD` only (excludes tokens and cardbacks) - confirmed via a fresh
eligible-pool count, 172,494 cards (the pilot's own real filtered count, not a naive
unfiltered query). Future work (not built): a token-aware matching path using Scryfall's own
token detection to search collector info or the set icon instead of the parent-set text tokens
don't reliably print.

**Corrected before/after comparison**, same 250-card window, re-run after the fix - OCR yield
now healthy and consistent at both core counts (56/198 votes, 28.3%, matching the original
94/300 baseline):

| config (pre-resize vs. post-resize core count) | wall-clock | processing-only rate |
| ---------------------------------------------- | ---------: | -------------------: |
| lower core count (`--workers 2`)               |       456s |          2.051s/card |
| higher core count (`--workers 7`)              |       230s |          0.914s/card |

**Speedup: 2.24x** (up from an earlier token-contaminated measurement's 2.03x - the sequential
clustering pre-pass, still unparallelized, see below, is a smaller share of a longer, more
representative run). Full-catalog re-projection (172,494 eligible pool):

|                   |   raw (naive) | cluster-dedup-adjusted (incl. ~21.6h sequential clustering pre-pass) |
| ----------------- | ------------: | -------------------------------------------------------------------: |
| lower core count  |     4.09 days |                                                            4.14 days |
| higher core count | **1.82 days** |                                                        **2.34 days** |

The sequential clustering pre-pass (`compute_own_image_clusters`, confirmed via code inspection
AND a live `docker stats` capture showing a single-core-only ~100% CPU plateau during that
phase) is ~21.6h fixed regardless of core count - ~38% of total time at the higher core count.
Parallelizing that one loop (flagged as a follow-up, not built) remains the highest-leverage
lever to push below ~2.3 days. Verified via direct `docker stats` sampling (not just aggregate
system `top`) that the compute phase itself DOES achieve real multi-core parallelism (a peak of
~625% CPU observed, consistent with most of a 7-worker pool active simultaneously) once past the
pre-pass - an earlier read of aggregate `top` data alone had incorrectly suggested a GIL-bound
compute phase; the direct per-process measurement corrected that.

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

## HOLD #2: full package report (2026-07-16)

Synthesizing deliverable gating full-catalog run authorization. Everything below is either
already-linked from earlier in this doc or newly summarized here; nothing in this section is a
new claim not otherwise sourced above.

**Infrastructure prerequisites - all landed:**

- Rate limiter (PR #25): merged to master. Deploy confirmed live via direct requests against
  `cdn.proxyprints.ca`'s full tier (4 real requests, all HTTP 200, 0.46-1.67s latency, no 429s)
  - the underlying fetch path PDF export and bulk download both depend on is healthy
    post-merge. (CI's "Publish image CDN" job shows red on every run, before and after this
    merge - a separate, pre-existing, unrelated failure in a `thumbnail-refresh` Cloudflare
    Workflow trigger, not the image-serving route itself; logged as its own follow-up, task
    #111, not a gate.)
- Tesseract dockerized (`docker/django/Dockerfile`'s shared `builder` stage) - verified
  end-to-end via a real `--dry-run --limit 3` inside the rebuilt container. Host venv retired.
- Container boot-recovery hardened: `restart: unless-stopped` on all 5 services plus a
  `mpcautofill-docker-compose.service` systemd unit as belt-and-suspenders - verified with a
  real `sudo reboot`, not simulated (all containers back up unattended within minutes, site
  returned 200 on both domains).
- Batch-flush checkpointing (item 2): a kill loses at most one `--batch-size` (default 25)
  worth of unflushed work; a plain re-invocation resumes cleanly via the existing idempotent
  selection query. Verified with a simulated-kill test.

**Throughput, real and corrected:**

A real correctness gap was found and fixed before trusting any number from this window: the
first several soak-test runs showed 0/250 OCR votes (vs. an original 94/300 baseline) - traced
to generic multi-set token names (e.g. "Beast", ~90 candidates each, essentially 0% coverage)
being front-loaded by item 1's coverage-gap ordering into a cohort that's structurally
unmatchable by OCR (a token's printed collector line reads its parent set's code; its DB
candidates use token-specific codes that never match). Fixed by excluding `card_type=TOKEN`/
`CARDBACK` from selection. Post-fix, OCR yield is healthy and consistent (56/198 votes, 28.3%,
matching the original baseline) at every core count tested.

Corrected same-window (250-card) before/after comparison, real `docker stats`-verified multi-core
parallelism (not just inferred from noisy aggregate `top`):

| core count | wall-clock | processing-only rate |
| ---------- | ---------: | -------------------: |
| lower      |       456s |          2.051s/card |
| higher     |       230s |          0.914s/card |

**Speedup: 2.24x.** Full-catalog re-projection (172,494 eligible pool, freshly counted with the
token/cardback fix applied):

|                   |   raw (naive) | cluster-dedup-adjusted |
| ----------------- | ------------: | ---------------------: |
| lower core count  |     4.09 days |              4.14 days |
| higher core count | **1.82 days** |          **2.34 days** |

The instance is now running at its higher core count as the standing configuration (not a
temporary state for this measurement alone) - not reverting to the lower count, though not
treated as permanently fixed either; revisit whenever convenient, no urgency either way.

**Cluster + coverage census:** clustering (item 2a) absorbed ~21% of selected candidates into
representatives in the corrected (token-excluded) sample - down from an earlier ~26-28% observed
in the token-contaminated sample, consistent with tokens/generic images being more prone to
visual duplication. The sequential clustering pre-pass (`compute_own_image_clusters`, confirmed
via code inspection and a live `docker stats` capture showing a single-core ~100% CPU plateau
during that phase specifically) is ~21.6h fixed regardless of core count - ~38% of total time at
the higher core count. Logged as task #108, held as an available future optimization, not built
now - the current projection is already a good number for a background job.

**Track 4 (pilot-quality items):**

- Bleed tag: negative-only voting shipped (item 4b) - votes only on a detected `trimmed`
  reading, absence of any vote is the documented convention for "presumed normal bleed" (updated
  in both this doc and `sensitive_tags.py`'s own comment, which previously documented the
  opposite pre-pilot convention). The existing-tag check (`Tag.objects.filter(...).first()`,
  degrades to no vote if the tag isn't seeded) was already in place before this change - no new
  tag seeded, matching the "wait for owner ok" instruction by construction. The underlying
  aspect-ratio classification itself was validated against a real 40-source diverse sample
  (Bleed-edge tagging section above) - the negative-only voting change is a polarity/gating
  change on top of that already-validated classification, not a new detection algorithm needing
  its own separate validation pass.
- DPI-tag audit (item 8, report only): 99.97% of the catalog already at 300+dpi - not a useful
  prioritization signal on its own. `low-res` SENSITIVE tag has never been used in production
  (0 resolved, 0 pending) - stays untouched, human-judgment/moderation-gated as designed. Both
  tag stores checked (`Card.tags` resolved/baked array and `CardTagVote` raw votes).

**Git/branch audit:** clean. This session's branch (`worktree-pilot-prescale`, PR #24) is
in sync with origin, mergeable. PR #25 merged (rate limiter). PR #20 (unrelated frontend fix)
merged at the owner's request, reviewed and confirmed by the owner before merging. PR #19
(unrelated docs-only Playwright-flake note) remains open with a trivial, keep-both `docs/lessons.md`
conflict against master - not a dependency of anything in this program, disposition left to the
owner's convenience. Several other worktree branches exist but are either already merged or have
zero unique diff against master (content already landed via a different commit path) - no lost
work found anywhere in the audit.

**Scaling recommendation, updated for the shorter true runtime:** the original Option A
(screen'd process) vs. Option B (django-q nightly slices) decision assumed a ~7-day run,
where crash-recovery and unattended multi-night scheduling mattered enough to weigh a full
scheduler infrastructure investment. At the now-real ~1.8-2.3 day full-catalog runtime, **a
single continuous run is the right shape - chunked nightly slicing is not needed.** Item 2's
own batch-flush checkpointing already provides crash-resilience within that single run (a kill
loses at most one batch, a plain re-invocation resumes cleanly), which is the main protection
django-q's scheduler infrastructure would otherwise buy - not worth the added complexity for a
run this short. Execution is via the now-dockerized image (`docker compose run`, matching every
verification run this session), not a host venv - a `screen`/`tmux`-wrapped single invocation is
sufficient; no new infrastructure to build.

**Open, non-blocking items** (logged, not gates): item 2b (persist `content_hash` for
federation, deferred), item 5 (questionFeed ordering mirror, separate follow-up PR), task #108
(parallelize the clustering pre-pass), task #109's future-work note (token-aware matching via
Scryfall's own token detection), task #111 (unrelated CI noise in the thumbnail-refresh
trigger), PR #19's disposition (owner's convenience).

**Full-catalog run: not yet fired.** This report is the synthesizing deliverable requested
before that authorization - awaiting explicit owner go-ahead.

## Two fast-follows, built after HOLD #2 (2026-07-16)

Both researched and sized before building (see the HOLD #2 section above and this doc's earlier
feasibility notes) - neither required schema changes, both reuse already-existing, already-
populated data.

### `expansion_hint` candidate narrowing

`_narrow_candidates_by_expansion_hint` (`local_identify_printing_tags.py`) narrows the
candidate list every engine considers, using `Card.expansion_hint` - a field that already
existed and is already populated at import time by `cardpicker.tags.Tags.extract` (a lone
set-code bracket token in the filename that didn't resolve a direct match, e.g. `[UNF]` with no
collector number). Not a new signal - just newly wired into the pilot; `deductive_backfill`'s
own D2 tier already trusts this same field for direct resolution when it narrows to exactly
one candidate.

A confidence PRIOR, not an entailment: narrows the list passed to `run_ocr_for_card`/
`run_phash_for_card`/`run_fallback_for_card` inside `_compute_card` only - never touches
`select_candidates`'s ordering, `compute_covered_printing_pks`, or the
`uncovered_printings_closed` metric, all of which need the true, unnarrowed candidate set to
stay correct. Never narrows to empty: if the hint matches zero of the name's real candidates (a
real, measured ~9% data-quality case - the hint may be stale or mismatched), the full list is
used instead.

**Real yield, measured live**: of 2,466 pilot-eligible cards with a real `expansion_hint`, 645
currently get skipped by phash outright (`too-many-candidates`) - narrowing brings 407 of those
back under `PHASH_MAX_CANDIDATES`, giving phash a real shot where it currently never runs.
OCR's own exact-match logic doesn't benefit (a smaller candidate list doesn't change whether a
parsed code+number is in it) - this is a phash-only unlock in practice.

### Name-frequency elimination

`run_name_frequency_elimination` (new function, new management command
`local_name_frequency_elimination`) - for a NAME where exactly one printing remains uncovered
AND exactly one pilot-eligible card is unresolved for that name, the match is deducible by
elimination alone: no image fetch, no OCR/phash, no visual disambiguation at all.

**The safety gate is the whole point, not a refinement.** A name can have exactly one uncovered
printing while SEVERAL unresolved cards share that name - in that case elimination does NOT
tell you WHICH card is the missing one (any of the others could just as easily be a redundant
depiction of an already-covered printing uploaded by a different source). The naive version
(gate on "one uncovered printing" alone) was the original researched number; adding "and
exactly one unresolved card too" is what makes the deduction airtight. Measured live against
the full catalog (not a sample), 2026-07-16: 2,076 names have exactly one uncovered printing;
only 1,678 of those also have exactly one unresolved eligible card - the naive version would
have voted incorrectly, on average, for the other ~400 names' multiple candidate cards.

Confidence deliberately modest (0.6, vs. OCR/phash's 0.85/0.75/0.8) - a purely structural
deduction is weaker evidence than an engine that actually looked at the image, even with the
1:1 gate making it sound. Still just a vote (`NAME_FREQUENCY_ANONYMOUS_ID`), never a direct
resolve - same consensus/gate-check discipline as every other engine in this module, same
batch-flush checkpointing pattern as `run_pilot`.

## Incident: per-chunk thread pool leaked Postgres connections, crashed the live run (2026-07-16)

The second full-catalog relaunch (post cluster-dedup removal) died ~3 minutes in with
`psycopg2.OperationalError: FATAL: sorry, too many clients already`. Root cause: pipeline
concurrency's `ThreadPoolExecutor` (item 3d above) was constructed **inside** the chunk `while`
loop, once per chunk, instead of once for the whole run. Django DB connections are thread-local
and nothing closes a connection when its owning thread is torn down, so every chunk's disposable
`ThreadPoolExecutor` leaked up to `workers` Postgres connections that were never coming back.
At `DEFAULT_BATCH_SIZE=25` and `workers=7`, against `max_connections=100` with ~10 already in
use by live traffic, the math works out to roughly a dozen chunks (~300 cards) before
exhaustion - consistent with the observed crash timing at workers=7's measured throughput.

Production site itself was never affected (confirmed 200s on both domains, and Postgres
recovered to its normal ~8 connections once the crashed process released its leaked slots) -
this was a background management-command process, not user-facing traffic.

**Fix**: hoist the `with ThreadPoolExecutor(...)` (falling back to `contextlib.nullcontext()`
for `workers==1`) to wrap the entire chunk loop, so the same pool - and therefore the same
`workers` threads, and therefore each thread's single DB connection - is reused across every
chunk instead of recreated. Zero behavior change to write ordering or chunking semantics (see
the code comment at the fix site); regression test
`TestConcurrency::test_thread_pool_is_created_once_for_the_whole_run_not_per_chunk` asserts
pool construction count stays at 1 across multiple real chunks of work, not just that votes
still get written.
