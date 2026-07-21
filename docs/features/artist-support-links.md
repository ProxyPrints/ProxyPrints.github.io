# Artist Support Links

## What this is

A small, deliberately narrow link-out feature: wherever a card's artist is
confirmed/known, show a link to that artist's page on [MTG Artist
Connection](https://www.mtgartistconnection.com) - a community-maintained
directory of Magic: the Gathering artists, not affiliated with this project
or its operator.

## v1 design: zero-crawl, deterministic link-out only

The core constraint, decided up front: **v1 does no verification of any
kind**. No per-artist database, no crawling MTG Artist Connection to build
a mapping, no existence check before rendering a link. The href is built
directly from the artist's display name string alone, via
`buildArtistSupportURL` (`frontend/src/components/ArtistSupportLink.tsx`):

```
https://www.mtgartistconnection.com/artist/<encodeURIComponent(artistName)>
```

e.g. `"Harold McNeill"` -> `.../artist/Harold%20McNeill`.

**Why no existence check, specifically**: MTG Artist Connection is a
client-rendered SPA where every route - including one for an artist it
doesn't actually have a page for - returns HTTP `200`. A status-code-based
"does this resolve to something real?" check is therefore not just
skipped for convenience, it's structurally meaningless against this site;
confirmed during this feature's own recon, don't re-attempt it. An artist
who isn't in their directory lands on MTG Artist Connection's own graceful
"No artist found" in-app page - accepted v1 behaviour, not treated as a
broken link from this project's side. A richer, verified integration
(e.g. an actual per-artist mapping, blessed by MTG Artist Connection's own
operator) is a plausible v2, tracked as pending owner outreach - not
started.

## Component

`frontend/src/components/ArtistSupportLink.tsx` exports:

- `buildArtistSupportURL(artistName: string): string` - the pure URL
  builder above, unit-tested directly (`ArtistSupportLink.test.tsx`) for
  the encoding behaviour (spaces -> `%20`, `&` -> `%26`, etc.) since that's
  the one thing this feature can silently get wrong with no visual symptom.
- `ArtistSupportLink({ artistName, className?, children })` - a plain
  `<a>` wrapping whatever `children` the caller wants as the link text,
  with the link-etiquette attributes fixed regardless of caller:
  `target="_blank"`, `rel="noopener noreferrer"` (opening an
  attacker-controllable-by-nobody but still third-party page shouldn't
  hand it a `window.opener` reference), `title="via MTG Artist Connection"` (a hover disclosure of where the link goes, since the
  domain itself doesn't appear in the link text on either surface below),
  and a trailing `box-arrow-up-right` Bootstrap Icon so it reads as
  external at a glance. `data-testid="artist-support-link"` on the anchor
  itself.

**Gating is the caller's job, not the component's**: `ArtistSupportLink`
takes an `artistName: string` (not optional/nullable) - it has no opinion
on when an artist is "confirmed enough" to link. Every caller below only
renders it once the artist is confirmed/known via the same precedence
chain the backend's `Card.serialise` exposes (i.e. `canonicalArtist` is
non-null) or a vote the user just cast themselves - never for a vote-
pending or unknown artist, since there'd be no name to build a URL from.

## Surfaces (three, as of the Proposal H pane migration)

1. **Card Detail Modal** (`CardDetailedViewModal.tsx`'s attribute table,
   the `"Canonical Aritst"` row - yes, that's a pre-existing typo in the
   row label, left as-is since fixing it is out of scope for this change).
   `cardDocument.canonicalArtist != null` renders
   `<ArtistSupportLink artistName={...}>{...}</ArtistSupportLink>` in
   place of the plain name text; `null` still renders `"Unknown"` as
   before, unchanged.
2. **`/whatsthat`'s post-answer moment** (`QuestionFeed.tsx`'s `"artist"`
   item type). `ArtistVotePicker` gained an optional `onArtistConfirmed?: (artistName: string) => void` prop, called from inside its own
   `submit()`'s success handler only when a real named artist was voted
   for (`!isUnknown && artistName != null` - "Unknown artist" never
   calls it, there's nothing to link). `QuestionFeed.tsx` wires this to
   local state (`confirmedArtistName`, reset every new item alongside the
   rest of the per-question state - see the fetch effect's own comment on
   why that reset has to be unconditional, not dependency-array-keyed)
   and renders `"Art by <Name> - support them"` with the link right below
   the picker once set. `ArtistVotePicker`'s _other_ caller
   (`AttributeVotingPanel`, the Card Detail Modal's own voting surface)
   doesn't pass this prop, so its behaviour is unchanged - the confirm
   banner is specific to the `/whatsthat` funnel's own post-answer moment,
   not a general property of casting an artist vote anywhere.
3. **Proposal H's `/display` rail Artist section**
   (`frontend/src/features/display/ArtistSection.tsx`, left-panel
   unification, issue #164) - the follow-on this doc originally
   anticipated. Same precedence chain/gating as surface 1:
   `cardDocument.canonicalArtist != null` renders the link (`"Art by <Name>"`), `null` renders plain `"Unknown"` text, never a link with
   nothing to point at. Reads the rail's currently-selected slot's own
   `CardDocument` (already resident in `cardDocumentsByIdentifier`) - no
   new fetch.

**Not built** (explicitly out of scope, noted so a future session doesn't
have to re-derive why): the confidently-known-artist collapsed display
inside `ArtistVotePicker` itself (the `"<name> wrong?"` span, shared by
both its callers) does not get a link - only the three surfaces above.

## Credits

`frontend/src/pages/about.tsx` credits MTG Artist Connection by name,
right after the existing contributors section, explaining the link-out-
only nature of the integration (traffic flows _to_ their directory, not
the other way) and inviting the actual site operator to reach out for a
richer, blessed integration later.

## Tests

- `ArtistSupportLink.test.tsx` (Jest/RTL) - the URL-encoding behaviour of
  `buildArtistSupportURL` directly, plus the component's fixed link-
  etiquette attributes.
- `tests/ArtistSupportLink.spec.ts` (Playwright) - surface 1: a known
  canonical artist renders the link with the correct href/attributes; no
  canonical artist renders plain `"Unknown"` text with no link at all.
- `tests/QuestionFeed.spec.ts` (formerly `QuestionFeedArtistAndTag.spec.ts`,
  Playwright) - surface 2: the
  post-answer banner appears (with the correct href) after voting for a
  named artist; voting "Unknown artist" never shows it.
- `tests/DisplayPage.spec.ts` (Playwright) - surface 3: the rail's Artist
  section shows the support link for a slot with a known canonical artist
  (Print Options and Slot Actions' own new-section coverage lives in the
  same file, alongside this).
