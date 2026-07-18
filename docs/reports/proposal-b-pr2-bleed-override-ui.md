As of: 2026-07-18
Task: Proposal B deferred PR-2 — manual-override UI + persistence
Branch: `claude/e3-bleed-override-ui` (stacked on `claude/e2-bleed-prior-batch-resolution`, PR #69)

## What shipped

Per-card manual override of the export-time bleed measurement (Auto / Force bleed / Force
trimmed), with persistence per decision 4 ("it must survive reload"). This populates
`PDFProps.bleedOverrides`, which `PDF.tsx`'s `PDFCardImage` (built in PR #66) already reads and
defaults safely to `"auto"` when absent — this PR is what actually lets a user set it to something
else.

### UI

A new "Bleed Overrides" collapsible section in the PDF export panel (`PDFGenerator.tsx`,
`BleedOverrideSettings`), following the same `AutofillCollapse` pattern as every other settings
section in that file (Page Size, Card Quality, Card Edges, etc.). It lists every card in the
project that bleed normalization can actually apply to — full-resolution Google Drive or
local-file sources, matching `PDF.tsx`'s own `isBleedNormalizationEligible` exactly — each with a
`Form.Select` (Auto / Force bleed / Force trimmed). Cards on other sources (SCM-only, thumbnail
tiers) are intentionally left off the list so the control never sits next to a card it would
silently do nothing for. Unlike this file's other settings sub-components, it reads/writes
`projectSlice` directly rather than taking `value`/`setValue` props — a deliberate difference,
since decision 4 requires this state to live in project state, not local component state.

### Persistence (decision 4)

No persistence mechanism previously existed anywhere in `projectSlice` — its existing fields
(`members`, `cardback`, etc.) are session-only, lost on reload. `favoritesSlice`'s own localStorage
pattern was the only existing per-identifier-map precedent in the codebase, and PR-2 mirrors it
exactly, three pieces:

- **State**: a new `manualOverrides: {[identifier: string]: ManualOverride}` field on
  `projectSlice`'s `Project` state (`common/types.ts`). A missing entry means `"auto"`; an entry
  is only ever stored for a non-`"auto"` choice — `setManualOverride` deletes the key when set
  back to `"auto"`, mirroring `favoritesSlice`'s delete-when-empty convention. New reducers
  `setManualOverride({identifier, override})` and `setAllManualOverrides(map)` (the latter for
  bulk-loading from localStorage); new selectors `selectManualOverrides` and
  `selectManualOverride(state, identifier)`.
- **Storage**: `getLocalStorageManualOverrides`/`setLocalStorageManualOverrides` in
  `common/cookies.ts`, structurally identical to `getLocalStorageFavorites`/
  `setLocalStorageFavorites` — same malformed-JSON/wrong-shape tolerance (falls back to `{}`),
  plus an extra check that every stored value is one of the three real `ManualOverride` strings.
  New `ManualOverridesKey` constant.
- **Wiring**: a `listenerMiddleware.ts` listener persists to localStorage on
  `setManualOverride`/`setAllManualOverrides`, matching the existing favorites listener exactly.
  `Layout.tsx`'s app-mount `useEffect` loads `getLocalStorageManualOverrides()` and dispatches
  `setAllManualOverrides` if non-empty, in the same effect that already does this for favorites.

The override is keyed by card **identifier**, not by project slot/member — it lives in its own
localStorage entry, independent of which cards happen to be in the currently-open project. This
matters because `projectSlice`'s `members` field (which cards are actually in the deck) still has
no persistence of its own — a pre-existing, unrelated gap this PR doesn't touch. The practical
effect: an override survives reload even though the rest of the open project doesn't, and it will
correctly re-apply the moment that same card identifier re-enters a project (e.g. after a fresh
search or an XML re-import) — which is the "ride through saved decks... where applicable" half of
decision 4's phrasing.

### Wired into export

`PDFGenerator.tsx`'s main component now selects `manualOverrides` via `selectManualOverrides` and
includes it as `bleedOverrides` directly in the `pdfProps` object (both the fast-preview and
full-resolution variants inherit it via the existing spread), so it flows into the real render the
same way `bleedEdgeMM`/`roundCorners`/every other export setting already does — no special-casing
needed, unlike `bleedPriors` (PR-1), which has to be resolved asynchronously right before the
render call. `bleedOverrides` is synchronous, already-in-Redux data, so it just goes in with
everything else.

### XML — flagged, not built

Per the owner's explicit instruction ("flag rather than build any XML field it wants"): the
override does not currently round-trip through `ExportXML.tsx`/`ImportXML.tsx`. Flagged in
`docs/proposals/proposal-b-bleed-normalization.md`'s "Tracked, not building" section — would need
a new optional field (e.g. `<bleedOverride>`) in the XML 2.0 schema plus read/write logic in both
files. Not required for decision 4's actual "must survive reload" requirement, which localStorage
already satisfies on the same browser/profile.

## Verification

- `npx tsc --noEmit`: clean. (Required adding `manualOverrides: {}` to 3 project fixtures in
  `test-constants.ts` and 7 partial-state objects in `projectSlice.test.ts`, since `Project` picked
  up a new required field.)
- `npx eslint` on all new/changed files: 0 errors. One pre-existing warning
  (`react-hooks/exhaustive-deps` on `Layout.tsx`'s mount effect) confirmed unrelated by diffing
  against the pre-change file directly — it already fired before this PR touched that effect.
- `npx prettier@2.7.1 --write`: applied.
- Full `npx jest --runInBand`: **295/295 passing** (282 from PR #66+PR-1's build + 13 new this
  pass: 7 reducer/selector tests, 6 localStorage round-trip tests), zero regressions.
- Full `npx playwright test tests/PDFGenerator.spec.ts`: **5/5 passing**. The 4 pre-existing tests
  pass at the same timing as before (no regression from adding a Redux-connected settings section
  to the panel). The new 5th test is a genuine end-to-end confirmation of decision 4: it sets an
  override via the real UI, confirms the write round-trips through actual `localStorage`, then
  performs a **fresh page navigation** (not just a unit-test assertion) and confirms the override
  is still selected — proving the full write→persist→reload→read cycle works in a real browser,
  not just that the reducer logic is individually correct.

### A real environment quirk found only by running the actual test, not assumed

The first version of the reload test used `page.reload()` directly, which hung past the 30s test
timeout waiting for the `"load"` event — this app's webworkers (client-search, PDF-render) appear
not to settle a second `"load"` event cleanly within one Playwright page lifecycle. Grepped the
rest of this test suite first: **no existing test anywhere reloads or renavigates a page mid-test**,
so there was no established pattern to fall back to. A plain `page.goto()` to the same URL hit the
identical hang. Fixed by navigating with `waitUntil: "domcontentloaded"` instead of the default
`"load"` — the DOM (and this app's React tree) is fully interactive well before whatever is
keeping `"load"` from firing a second time resolves, and the test's own subsequent
`page.getByText("Choose Art").click()` already waits for the actual UI to be ready. This is an
environment/framework quirk unrelated to anything this PR changed — flagging here in case a future
task wants a real multi-navigation Playwright test and hits the same wall.

## Deviations

None from the authorized scope. Two implementation choices worth flagging:

1. **Where the UI lives**: the approved spec only says "per-card manual override in the export
   panel" with no mockup. Considered embedding the control directly into `PagePreview.tsx`'s
   scaled-down WYSIWYG card tiles (Proposal A's existing per-card visual surface) but rejected it —
   that component is CSS-`transform: scale()`-shrunk to fit a preview panel, and overlaying a
   real, clickable `<select>` per tiny scaled tile would need transform-aware hit-testing/sizing
   work with no clear payoff over a plain settings-panel list. Went with a new collapsible
   settings section instead, following this file's own existing convention exactly (same
   `AutofillCollapse` pattern as every other export setting).
2. **Eligibility filtering**: the panel only lists cards `isBleedNormalizationEligible` would
   actually apply to (Google Drive/local-file, full-resolution), rather than every card in the
   project. Not explicitly specified either way — chosen so the control is never shown next to a
   card an override would silently do nothing for.

## Open items

None blocking. PR-3 (preview badge), Proposal C part (b), E-3, and Proposal F remain queued
behind this, per the standing order — not started this pass per the standing pacing rule (all are
new-feature items, not follow-ups to PR-2).
