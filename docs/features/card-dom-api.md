# Card DOM API

Additive, generic DOM hooks for external tooling/testing/accessibility.
Deliberately has no reference to any specific external tool by name.

## What it does

`frontend/src/common/cardDom.ts` exports `getCardDataAttributes`/
`getCardSelectedEventDetail`, both sourced from the `CardDocument` object
the frontend already holds (no new fetches). Spread onto `Card.tsx`'s
`BSCard` root (covers the editor's card slots and the art-selection grid,
both of which reuse `Card`) and `CardDetailedViewModal.tsx`'s `Modal` root:
`data-card-name`, `data-card-identifier`, `data-source-key`, `data-card-dpi`,
`data-card-type` (`"card"`/`"cardback"`/`"token"`), and
`data-card-set-code`/`data-card-collector-number` (sourced from
`CardDocument.canonicalCard.{expansionCode,collectorNumber}`, only present
once a printing is actually resolved). Any field that isn't available is
omitted entirely, never emitted empty.

`CardSlot.tsx` dispatches a bubbling, composed `mpc:card-selected`
`CustomEvent` from the slot's root element whenever an art selection is
confirmed (prev/next arrows or grid selector), with the same fields
(camelCased: `setCode`/`collectorNumber`) in `event.detail`.

### Printing-candidate extension

The printing-tag candidate grids (`QuestionFeed.tsx`'s unified vote queue
and `PrintingTagPicker.tsx`'s embedded picker in
`CardDetailedViewModal.tsx`) carry a sibling helper,
`getPrintingCandidateDataAttributes(cardName, candidate)` — not a reuse of
`getCardDataAttributes`, since `PrintingCandidate` (`schema_types.ts`)
isn't a `CardDocument`. Spread onto each candidate button:
`data-card-name` (the card being tagged), `data-card-identifier`/
`data-card-set-code`/`data-card-collector-number` (the one candidate
printing that button represents). Client tooling must not assume
`data-card-name` and the candidate's set code/collector number describe the
same printing — resolving that question is the entire point of the UI.
The "No match" button intentionally carries none of these attributes.

## Key files

- `frontend/src/common/cardDom.ts`
- `frontend/src/features/card/Card.tsx`, `CardSlot.tsx`
- `frontend/src/features/cardDetailedView/CardDetailedViewModal.tsx`
- `frontend/src/features/questionFeed/QuestionFeed.tsx`,
  `frontend/src/features/printingTags/PrintingTagPicker.tsx`,
  `cardPanel.tsx`
- `frontend/docs/dom-api.md` (stability: best-effort, semver-ish,
  additive-only)

## Status

Documented in `frontend/docs/dom-api.md`. Test coverage in
`CardSlot.spec.ts`, `VotePickers.spec.ts` (formerly `PrintingTagPicker.spec.ts`), and the
`QuestionFeed*.spec.ts` suite (unified vote queue, successor to the old
standalone `PrintingTagQueue.tsx` this API originally shipped against)
— real Playwright runs against the mocked backend, not just typecheck.

**Known gap (found 2026-07-24, issue #272 parity wave 3): unimplemented on the
unified `/editor` page's sheet.** Since the Proposal H route swap, `Card.tsx`/
`CardSlot.tsx`/`CardDetailedViewModal.tsx` remain the only callers of
`getCardDataAttributes`/`getCardSelectedEventDetail`/`CardSelectedEventName`
(confirmed by grep against `cardDom.ts`'s own import list) — none of them are
reachable as the _placed_ card for a project slot on `/editor` post-swap.
`PagePreview.tsx` (the sheet's own per-slot renderer, `frontend/src/features/ pdf/PagePreview.tsx`) renders a plain, unwrapped `<img>` with no
`data-card-*` attributes and dispatches no `mpc:card-selected` event at all.
Any external tooling built against this contract (userscripts, browser
extensions) that used to read a project's placed cards off the classic grid
gets nothing on the unified page. Not ported/faked in wave 3's `CardSlot.spec.ts`
port (the one classic test that exercised this, "selecting an image in a
CardSlot via the grid selector", was dropped rather than weakened) — flagged
here and in that wave's PR body for an owner decision on priority; wiring
`PagePreview.tsx`'s slot `<img>` into `getCardDataAttributes` is a contained,
mechanical fix once scheduled, not investigated further as part of that port.
