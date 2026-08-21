# "Print!" export page — RETIRED

> **Retired 2026-08-14.** The `/print` page (`pages/print.tsx`) and its "Print!" tab
> (`FinishedMyProject.tsx`) were deleted along with the rest of the print-only chain
> (`Export.tsx`, `ExportPDF.tsx`, `PDFGenerator.tsx`, `PDFCanvasPreview.tsx`,
> `PDFWaitPanel.tsx`, `PDFGeneratorModal.tsx`). The three printshop ordering guides
> (PringlePrints / MakePlayingCards / NotMPC) moved into `/editor`'s Export ▾ menu as a
> "Printshops" item opening a modal — see `docs/features/pdf-generator.md`'s
> [Printshop ordering guides](pdf-generator.md#printshop-ordering-guides-the-retired-print-print-tab)
> section for the new home, the flags rationale, and the home-printing guidance. This file is
> kept as a stub (rather than deleted) so the wiki-publish map's `Print-Export-Page` entry
> keeps resolving; the history below is preserved for reference.

## What it used to do

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
requiring hand-rolled SVG specifically. The same vendored SVGs still title
the printshop tabs in the modal that replaced this page.

## Known gaps (carried into the new home)

- The NotMPC flow steps still carry a TODO for manual verification against
  the real site (currently based on an automated read only).
- The PringlePrints flow steps carry the identical TODO — steps/pricing/
  service-area were derived from a one-time read of pringleprints.ca, not a
  manual walkthrough, and may have changed since.

Both TODOs and the "steps current as of July 2026 — confirm before ordering"
caveats were ported verbatim into `DisplayExportPrintshops.tsx`.
