# `/display` left rail (card surface)

The unified display page's left rail (`features/display/DisplayPage.tsx`'s
`Rail`/`RailHeader`/`PromotedZone` + `SelectVersionSection`) shows one
slot's card details, confidence signal, sources, and version picker. This
doc is the single, un-fragmented home for the round shipped 2026-07-23
(`SPEC-display-left-rail.md`, owner-approved; built into PR #352) — see
[`docs/upstreaming/readiness-audit.md`](../upstreaming/readiness-audit.md)'s
§10 for the presentation-only upstream-divergence ledger this round seeded
(not duplicated here). A corrected fidelity round (also 2026-07-23,
Yori) normalized every rail block-boundary divider to `#16202b` (O1,
below) — see that section for the one binding-table row it deliberately
did NOT apply.

Companion design artifacts (spec + mockup) live at
[`docs/proposals/mockups/proposal-h/display-left-rail-mockup.html`](../proposals/mockups/proposal-h/display-left-rail-mockup.html)
and
[`docs/proposals/mockups/proposal-h/SPEC-display-left-rail.md`](../proposals/mockups/proposal-h/SPEC-display-left-rail.md),
following the same "durable home in `docs/proposals/mockups/`" convention
[`docs/proposals/mockups/proposal-h/README.md`](../proposals/mockups/proposal-h/README.md)
already documents for this round's own predecessor mockups.

## D14 confidence element

`features/display/ConfidenceElement.tsx` — the promoted identity band
directly under the rail header's card name + `RequestedPrintingBadge`
(above the artist line; it's identity, not demoted metadata). Supersedes
the old `DeckbuilderConfirmAffordance` mount that used to co-render in
`RailHeader` — that mount is **removed** (the component itself is
untouched, still mounted in `CardSlot.tsx`'s editor grid and inside
`SelectVersionResults.tsx`'s suggested-printing confirm ribbon, both
outside this round's scope).

- **Set symbol is the confidence anchor** (`SetIcon`, a Keyrune glyph): a
  human-confirmed printing (`canonicalCard != null`) gets a green ✓
  corner badge + a "Confirmed" pill, no number (a resolved printing is a
  settled fact, not a probability). A not-yet-confirmed printing (only
  `suggestedCanonicalCard`) gets a numeric confidence score badge **if
  the backend has actually supplied one** (see "Numeric confidence
  score" below), else the qualitative "Suggested" pill.
- **Scryfall reference on hover/focus**: `OverlayTrigger`
  (`trigger={["hover","focus"]}`) + `Popover`, anchored on the set icon,
  showing the printing's Scryfall reference image via
  `buildScryfallReferenceImageUrl` (`scryfallReference.ts`) — Scryfall's
  own documented `?format=image` convenience redirect
  (`https://api.scryfall.com/cards/:code/:number?format=image`), which
  resolves straight to the image on Scryfall's own CDN from just a set
  code + collector number, no card-UUID lookup needed first. Display-only
  — nothing fetched or stored by this catalog (governing premise + #271).
- **"✗ not this printing"** — a real `btn-outline-danger btn-sm` (not the
  old disabled placeholder) that casts a genuine vote via
  `APISubmitPrintingTag(backendURL, cardIdentifier, anonymousId, undefined, /* isNoMatch */ true, "display-confidence")`. This is
  deliberately the `isNoMatch` half of the printing-tag vote schema, not
  `useTagVoting.ts`'s attribute-tag hook of the same rough shape — D14 is
  disputing the CARD'S OWN currently-attached printing (`canonicalCard`/
  `suggestedCanonicalCard`), which is exactly what `isNoMatch: true`
  models ("no known printing matches this card image"); it's a distinct
  situation from `DeckbuilderConfirmAffordance.tsx`'s own `handleNo`
  comment, which explains why disputing ONE candidate among several in a
  picker has no such vote in the schema — that constraint doesn't apply
  here, since D14 has only one printing in view, not several candidates.
  **Owner answer #2 (2026-07-23)**: stays visible — de-emphasised via
  CSS `opacity` (`data-confirmed="true"`), never hidden — on an
  already-`confirmed` printing too, so disputing settled consensus is
  always possible (D1's "explicit human dissent opens a human-vs-human
  contest" semantics). Casts the identical vote call in both states.

### Numeric confidence score — API field flag for the backend

**Owner answer #1 (2026-07-23)**: a calibrated score is arriving
backend-side "shortly." Today's API exposes no such field —
`suggestedCanonicalCard` is a machine-cast VOTE identifier, not a
percentage. The frontend reads a new, currently-always-absent seam field:

```ts
// common/schema_types.ts, on Card/CardDocument
suggestedCanonicalCardConfidence?: number | null;
```

**Expected shape**: an integer 0–100 percentage, present ONLY alongside a
non-null `suggestedCanonicalCard` (never sent for an already-`resolved`
card) — same opt-in-per-endpoint pattern
`suggestedCanonicalCard`/`suggestedFilterTagNames` already use
(`Card.serialise`'s `include_suggested_printing`/
`include_suggested_filter_tags` kwargs). Until a backend PR populates it,
every real API response omits the field, `ConfidenceElement.tsx` reads
`undefined`, and the component degrades to the qualitative "Suggested"
pill — never a fabricated number, never a crash. **When the backend
lands this, no frontend change is needed beyond confirming the field name
above matches exactly.**

## Sources accordion

`features/display/SourcesAccordion.tsx` — replaces the flat, ~247-row
per-source toggle list (previously reachable only through the Search
Settings modal, `SourceSettings.tsx`) with a disclosure in the **left**
rail. Sources gate which art is even searchable, so the owner brief puts
them with the card surface itself.

**Deviation from `proposal-h-display-layout-spec.md` §4.2** (which put
Search Settings in the RIGHT rail): honours the newer, explicit owner
brief. **Owner answer #4 (2026-07-23)**: the modal `SourceSettings.tsx`
stays, unmodified, reachable via the toolbar's own Search Settings button
— this accordion is additive, not a replacement of that surface.

**Owner answer #3 (2026-07-23)**: INLINE shape (confirmed, the mockup's
own recommendation) — the accordion's body pushes rail content down,
inside the rail's single `overflow-y:auto` scroll container, at every
breakpoint. The mockup's alternative "overlay dropdown" shape was
reviewed and rejected: on phone the left rail is itself a 72vh
bottom-sheet Offcanvas and on tablet a start-drawer, so an overlay
dropdown there would float over rail content inside ANOTHER overlay — the
exact stacking/z-index hazard the base Proposal H spec already warns
against.

**Composition**: a thin, standalone composer (not additive props on
`SourceSettings.tsx`) — it writes directly to `searchSettingsSlice`
(Redux + the same `setLocalStorageSearchSettings` persistence the modal's
own Save button uses) on every toggle/bulk action, with no staged
local-copy-then-Save step; `SourceSettings.tsx` itself is completely
untouched.

- **Collapsed summary**: `Sources · <N> of <M> enabled` (N in green) +
  chevron, plus the pinned-favourites chip strip (see below) — both live
  in `AutofillCollapse`'s `title` node, so they stay visible even
  collapsed.
- **Expanded body**: a type-to-filter `Form.Control`, three bulk-action
  buttons (`Enable all` / `Disable all` / `Invert`), a disabled `#353`
  seam button ("☆ Save these as my defaults"), and the per-source toggle
  list (`react-bootstrap-toggle`, same `Toggle` component the modal
  uses) with its own inner `max-height: 190px` scroll so it never
  dominates the rail.

### Pinned favourite sources (owner answer #5, 2026-07-23)

"Implement the pin UI + localStorage persistence now" — each source row
gets a ★ pin toggle (`aria-pressed`); pinned sources show as a chip strip
in the accordion's collapsed summary. Persistence:
`getLocalStoragePinnedSourcePks`/`setLocalStoragePinnedSourcePks`
(`common/cookies.ts`, `PinnedSourcesKey` = `"pinnedSources"` in
`common/constants.ts`) — a plain array of source pks, validated JSON with
a safe empty-array fallback, same shape as this codebase's existing
`getLocalStorageFavorites`/`setLocalStorageFavorites` pattern.

**Deliberately device-local, not account-tied** — this is the seam only.
The real "save these as my defaults" version (synced to an account,
surviving a device switch) is issue **#353**, a disabled button in the
accordion's body until that ships. **Scoped exception to this repo's
usual "no localStorage for state that should survive a clear-site-data
test" rule** (CLAUDE.md's tooling-rules note, journal-documented after
past bugs): this is a narrow, low-stakes UI preference (which sources are
starred for quick reference) with an owner-directed, explicit,
documented carve-out — not a case of critical or server-authoritative
state hiding in browser storage. A cleared/incognito browser just loses
its stars and starts fresh; nothing breaks.

## Select Version — continuous grid (addendum item 2)

`features/gridSelector/SelectVersionResults.tsx`'s stacked (funnel)
layout — owner verbatim (from a live 390px screenshot): **"the 5 cards
should be in 1 section."** The rail used to fragment candidates into
stacked single-column mini-blocks, each broken up by a `Confirm?`/Y·N
block, a `+N more of this printing` text link, and `⌇ suggested`/`More like this` text rows.

**Now**: every candidate tile packs into ONE continuous
`d-flex flex-wrap` grid (`role="list"`), with
`selectVersionGrouping.ts`'s existing canonical → non-canonical → unknown
ordering preserved as a pure **sort key**, not a sectioning key — zero
visual partitioning, per the owner's "read as ONE grid" direction. Every
per-group affordance that used to occupy its own row is now a tile-corner
annotation instead:

| Old (row, broke the grid)                                   | New (tile-corner annotation)                                                                                                                                                                                                                                                                                                                                                                    |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Group header                                                | tiny `✓` corner tag (canonical/resolved) / `Alt` (non-canonical) / `?` (unknown)                                                                                                                                                                                                                                                                                                                |
| —                                                           | `REQ` corner badge on the slot's own requested printing, sorts first                                                                                                                                                                                                                                                                                                                            |
| `+N more of this printing` text link                        | an inline **ghost tile** (`GhostTile`, same tile footprint, dashed outline) right after the cluster representative — expands the cluster IN PLACE, no full-width row. Once expanded, the ghost tile becomes a "−"/"Show fewer" collapse control instead of disappearing, so re-collapsing stays reachable without reintroducing a text row.                                                     |
| `Confirm?`/Y·N block (suggested-printing confirm, moment a) | a small **confirm ribbon** — the real, completely unmodified `DeckbuilderConfirmAffordance` (no internals touched), wrapped in a `transform: scale(0.72)` overlay positioned at the tile's bottom-right corner instead of rendered at full size in a separate block below the tile. Same hover/click/vote behavior everywhere else that component mounts; only its position/scale changed here. |
| `⌇ suggested` text row                                      | a small dashed corner marker (bottom-left)                                                                                                                                                                                                                                                                                                                                                      |
| "More like this" text link                                  | **dropped** (see below)                                                                                                                                                                                                                                                                                                                                                                         |

**Dropped, not replaced**: the old "More like this" per-tile link (seed
the filter chips from this specific card's own resolved tags) has no
tile-corner slot in the spec's own affordance table and was removed
entirely from the funnel/stacked layout when the between-group rows went
away — a flagged, deliberate capability loss, not a silent one. It's
still there, byte-for-byte unchanged, on the sidebar/modal layout
(`GridSelectorModal.tsx`'s own caller, which this whole round leaves
untouched) — Treatment chips (below) cover the same "narrow by an
attribute" need on the funnel surface instead.

**A11y**: the grid is `role="list"`; each tile is `role="listitem"` with
an `aria-label` spelling out its group + requested/suggested status (e.g.
`"XYZ 001, requested printing, canonical printing, resolved"`), so the
sort-order semantics survive for a screen reader even though the visual
separators are gone. The ghost tile is a real `button`
(`aria-label="Show N more copies of…"` / `"Show fewer copies of…"`).

Tile widths are unchanged from PR #352's own earlier density round
(dense 72px / medium 88px / hero 112px, `FUNNEL_TIER_TILE_WIDTH_REM`,
`FUNNEL_DENSE_ABOVE`/`FUNNEL_HERO_AT_OR_BELOW` thresholds) — this round
is a grid/render change, not a re-litigation of tile sizing.

## Unified Frame + Treatment filter (addendum item 1)

Owner: "i want the filters list unified, treatment and frame type can
sit in one spot to save space." Border (`ToggleButtonGroup type="radio"`,
exclusive) keeps its own row; Frame (also exclusive) and Treatment (five
independent chips) now share ONE bordered `fieldset` block, Frame's
segmented control and Treatment's chip row sitting side by side (wrapping
together at narrow widths) separated by a thin vertical divider.

**Treatment gained a real tri-state cycle it didn't have before**:
`untouched (·) → include (+) → exclude (−) → untouched`, reusing
`attributeChips.ts`'s own `nextChipState` for the cycle order (the
taxonomy's single source of truth for it — this is a pure client-side
FILTER, not a vote). Previously Treatment was rendered through the same
generic `FunnelAxisRow`/checkbox `ToggleButtonGroup` Border/Frame use,
which is binary (active or not) — a checkbox group has no notion of a
third "exclude" state. `TreatmentChipRow` is its own small component for
exactly this reason.

Implementation is fully additive to the existing filter pipeline: a new
`excludedAttributeTags: Set<string>` piece of local state, entirely
separate from the pre-existing `activeAttributeTags` (which keeps its
exact original "include" semantics, still the only thing the implicit-
vote/awareness-line logic ever reads — excluding a tag is a pure negative
filter action, never something a pick "supports"). Filtering runs the
existing positive filter first, then a new
`filterOutExcludedChipsVotesGated` pass drops any candidate that
satisfies an excluded tag; `membershipByTagName`'s own "survivors
excluding this axis" computation got the same exclude-aware extension
(excluding an axis's own exclusions when computing that axis's own
membership, mirroring the existing "exclude own axis" pattern for
positive tags) so a chip's own exclude-state never hides itself. Border/
Frame's exclusive-radio behavior is completely untouched.

**A11y**: the block is a `fieldset` with a visually-hidden legend ("Frame
and treatment filters"); Frame stays a radiogroup; each Treatment chip is
a real `button` with `aria-pressed` (true only when `positive`/included)
and an `aria-label` spelling out the actual state ("Extended Art:
excluded").

## Artist support button

`features/display/ArtistSection.tsx` — the credit line ("Art by
`<Name>`") stays plain text; the support link (`ArtistSupportLink.tsx`,
unchanged) now renders as `Support on MTG Artist Connection ↗` styled
`btn btn-outline-primary btn-sm`, visibly naming its destination, instead
of a bare orange hotlink wrapping just the artist's own name.
Zero-crawl posture is unaffected (text credit only, no fetched logo/asset
— see [`artist-support-links.md`](artist-support-links.md)); gating is
unchanged (`canonicalArtist != null` → button, `null` → plain "Unknown").

## Buttons-look-like-buttons audit

Owner rule (SPEC §8): anything clickable that performs an ACTION reads as
a real, bordered/filled Superhero `.btn`; only pure NAVIGATION stays a
link. On the dark rail surface, `btn-outline-secondary` (`$secondary` /
`#4e5d6c`) is near-invisible — corrected surfaces use `btn-outline-light`
(`$light` / `#abb6c2`) for neutral actions instead.

Corrected in this round: the Select Version **Filters** disclosure toggle
(was underlined text — briefly, mid-PR-#352, before this round; the rule
wins over that reference-mockup drift, and this also happens to AGREE
with upstream's own `GridSelectorFilters` toggle, which is already a
real `Button` — see the upstream-divergence ledger's explicit "does NOT
diverge" row), Slot Actions (`outline-light`/`outline-danger` for
Delete, replacing near-invisible `outline-secondary` — these were
already real `Button`s, just the wrong variant), the artist support link
(above), D14's "✗ not this printing" (above), and the Sources accordion's
bulk/pin/save-defaults controls (above). The empty-state "Find this card
↗" link stays a link — pure navigation out to Scryfall, the rule's own
explicit exception.

## Density (mechanical, SPEC §D.1)

Rail blocks now butt against each other separated by 1px borders —
vertical rhythm comes from each block's own compact padding
(`8px 10px` for the rail header/D14 band/artist line/Select Version
wrapper), not an inter-block `gap`. Tile-wrapping rows already use
`gap-1` (4px, from PR #352's earlier round). No layout/breakpoint
behavior changed — see `proposal-h-display-layout-spec.md` §4.1 for the
unchanged R2 shell (Offcanvas placement per tier, 380px inline width,
etc.); this round only restyles/recomposes the rail's interior.

## O1 — divider normalization (corrected fidelity round, 2026-07-23)

The rail's own block-boundary hairlines were inconsistent: `.d14` (the
confidence band) already used an explicit `#16202b`, while `.rail-head`,
`.artist-line`, and the Sources accordion's outer wrapper used the plain
Bootstrap `.border-bottom` utility — whose active `--bs-border-color` is
genuinely ambiguous in this theme's compiled CSS (both `#495057` and
`#ced4da` are present), risking a pale line on the dark rail depending on
cascade order. The unified Frame+Treatment filter's own border (and its
internal Frame↔Treatment divider) separately hardcoded the unthemed
`rgba(0,0,0,.22)`. The Select Version wrapper had no boundary divider at
all.

**Normalized (owner-approved, corrected `SPEC-display-left-rail.md` §A/
§D.1) — every one of the above now explicitly renders `#16202b`, 1px**:
`.rail-head`, `.artist-line`, and `.sources` (all three now via
`RailRoot`'s own styled-component rules in `DisplayPage.tsx`, replacing
the Bootstrap utility classes they used to carry); the Select Version
wrapper (gained a `select-version-wrapper` className plus a new
`RailRoot` rule — it never had a boundary before); the unified filter
`fieldset`'s own border and its internal `UnifiedFilterDivider` (both
inline/styled-component literals in `SelectVersionResults.tsx`). The
Sources list's own inner border and each source row's own bottom divider
were deliberately left at `rgba(0,0,0,.22)` — the spec's own binding
table marks those two specifically as unchanged (`I`, not `I (border N)`), not part of O1's scope.

**Deliberately NOT applied this round**: the same corrected spec's §A/
§D.1 also calls for every rail `.btn-sm` to return to Bootstrap's real
`sm` metrics (`14px`/`4px 8px`), reversing the smaller, already-shipped
`CompactButton`/`CompactToggleButton`/`CompactLinkButton`/`TreatmentChip`
sizing from the earlier "the buttons are too big" owner fix round. The
spec's own §A flags that specific row as needing its own owner sign-off
(distinct from O1's separately-confirmed divider normalization), and it
directly conflicts with the more specific, already-shipped directive on
the exact same controls — left as shipped pending an explicit owner call
on that one row (`funnel-filters-toggle`'s own 12px assertion in
`DisplayLeftRailFidelity.spec.ts` documents this).

## File-level summary

| File                                             | Change                                                                                                                                                                          |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `features/display/ConfidenceElement.tsx`         | rewrite: SetIcon anchor + ✓/score corner badge, `OverlayTrigger`+`Popover` Scryfall reference, live `APISubmitPrintingTag` ✗ vote                                               |
| `features/display/DisplayPage.tsx`               | `RailHeader`'s `DeckbuilderConfirmAffordance` mount removed; `PromotedZone` reordered (Confidence before Artist) + threads `backendURL`; mounts `SourcesAccordion`; density CSS |
| `features/display/ArtistSection.tsx`             | support link rendered as a named button                                                                                                                                         |
| `features/display/SlotActionsSection.tsx`        | button variants (`outline-light`/`outline-danger`), `w-100`                                                                                                                     |
| `features/display/SourcesAccordion.tsx`          | new — rail Sources accordion                                                                                                                                                    |
| `features/gridSelector/SelectVersionResults.tsx` | continuous grid + tile-corner annotations; unified Frame+Treatment block; Treatment tri-state exclude; Filters toggle reverted to a real button                                 |
| `features/display/scryfallReference.ts`          | added `buildScryfallReferenceImageUrl` (existing `buildScryfallReferenceUrl` untouched)                                                                                         |
| `common/schema_types.ts`                         | added `suggestedCanonicalCardConfidence` seam field                                                                                                                             |
| `common/constants.ts` / `common/cookies.ts`      | `PinnedSourcesKey` + `getLocalStoragePinnedSourcePks`/`setLocalStoragePinnedSourcePks`                                                                                          |
| `components/AutofillCollapse.tsx`                | additive optional `id` prop (real `aria-expanded`/`aria-controls`)                                                                                                              |

No new npm dependency. `GridSelectorModal.tsx` (editor modal),
`CardSlot.tsx`, and `DeckbuilderConfirmAffordance.tsx`'s own internals
are untouched.

## Open items (owner-decidable, not blocking)

1. **Confidence element's numeric-score field name** — flagged above;
   confirm `suggestedCanonicalCardConfidence` is the name the backend PR
   should actually use once the calibrated score work lands.
2. **Group corner-tag copy** (`✓`/`Alt`/`?`) — the spec's own open item
   6: whether a canonical/custom/unknown label should surface anywhere
   for sighted users beyond the corner tag. Current build ships the
   minimal tag only, per the owner's "zero partitioning" direction.
