# "Print!" export page

`FinishedMyProject.tsx` — the final step of the editor where a finished
project gets sent off to be physically printed.

## What it does

- A NotMPC ordering tab mirroring the MakePlayingCards tab's 3-step
  structure. NotMPC.com flow steps have a TODO for manual verification —
  sourced from an automated site read, not a manual walkthrough.
- A PringlePrints ordering tab (started as a minimal single-line listing
  below the existing tabs, later promoted to a full tab matching the
  others).
- Three tab icons (`frontend/src/components/flags.tsx`) — plain `<img>`
  tags pointing at 3 static SVG files vendored from `lipis/flag-icons` (MIT
  licensed) in `frontend/public/`.

## Why not emoji flags

Deliberately not raw unicode emoji flags (🇨🇦🇨🇳🇺🇸): Windows' default emoji
font (Segoe UI Emoji) has no flag glyphs at all, so Windows browsers would
render plain letter pairs ("CA"/"CN"/"US") instead of a flag. The flags
were originally hand-rolled inline SVG (trig-based star generation, loop-
generated stripes, a hand-typed maple-leaf path) specifically to avoid
that — which produced two real rendering bugs of its own, fixed, then
later simplified to the vendored static SVGs above once the original
Windows-emoji reasoning was already satisfied by "not emoji" rather than
requiring hand-rolled SVG specifically.

## Key files

- `frontend/src/features/export/FinishedMyProject.tsx`
- `frontend/src/components/flags.tsx`
- `frontend/public/*.svg` (vendored flag icons)

## Status

Confirmed live. Verified end-to-end via a temporary Playwright test reusing
this repo's MSW mock infra (`tests/test-utils.ts` + `src/mocks/handlers.ts`)
reaching the Print! tab and screenshotting the tab bar — all 3 flags
rendered correctly; test file removed after verification (not a permanent
addition).

## Known gaps

- The NotMPC flow steps still carry a TODO for manual verification against
  the real site (currently based on an automated read only).
- The PringlePrints flow steps carry the identical TODO (`FinishedMyProject.tsx:347`)
  — steps/pricing/service-area were derived from a one-time read of
  pringleprints.ca, not a manual walkthrough, and may have changed since.
