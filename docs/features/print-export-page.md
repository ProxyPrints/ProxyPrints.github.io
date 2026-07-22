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

## Post-export contribution prompt (issue #166)

The `PDFGenerator.tsx` mounted inside this tab's own "PDF" sub-tab carries a
dismissible `Alert` shown once per session after a genuine "Generate
PDF"/"Save PDF to Google Drive" success, linking to `/whatsthat`. One shared
implementation (`frontend/src/features/export/ usePostExportContributionPrompt.ts` + `PostExportContributionPrompt.tsx`),
mounted from `PDFGenerator.tsx` itself so every real caller of that
component — this tab (reachable both via the classic editor's "Print!" tab
and, since issue #275, standalone at `pages/print.tsx`), `PDFGeneratorModal.tsx`,
`ProjectEditor.tsx` — gets it for free, rather than wiring it into
`FinishedMyProject.tsx` separately. (Issue #275 also retired the unified
`/display` page's OWN separate inline export pipeline and its own mount of
this same prompt — PDF generation now lives solely here, reached from
`/display`'s Finish footer via a pre-print save gate; see
`docs/proposals/proposal-h-display-layout-spec.md`'s ADDENDUM D9/D10.) See
`docs/features/printing-tags.md`'s own entry for the full detail (session-
scoped `sessionStorage` flag, success-detection mechanism, why it's a
funnel entry point rather than a parallel one) and
`docs/features/pdf-generator.md`'s "Key files" for the export-pipeline side
of the wiring.

## Key files

- `frontend/src/features/export/FinishedMyProject.tsx`
- `frontend/src/components/flags.tsx`
- `frontend/public/*.svg` (vendored flag icons)
- `frontend/src/pages/print.tsx` (issue #275, D10/F5) — thin standalone route
  wrapper mounting `FinishedMyProject` unchanged, mirroring `pages/myDecks.tsx`;
  the funnel destination `/display`'s Finish footer navigates to

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
