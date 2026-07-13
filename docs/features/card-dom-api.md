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
The printing-tag candidate grids (`PrintingTagQueue.tsx`'s standalone
queue and `PrintingTagPicker.tsx`'s embedded picker in
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
- `frontend/src/components/Card.tsx`, `CardSlot.tsx`,
  `CardDetailedViewModal.tsx`
- `frontend/src/features/printingTags/PrintingTagQueue.tsx`,
  `PrintingTagPicker.tsx`
- `frontend/docs/dom-api.md` (stability: best-effort, semver-ish,
  additive-only)

## Status
Documented in `frontend/docs/dom-api.md`. Test coverage in
`CardSlot.spec.ts`, `PrintingTagQueue.spec.ts`, `PrintingTagPicker.spec.ts`
— real Playwright runs against the mocked backend, not just typecheck.
