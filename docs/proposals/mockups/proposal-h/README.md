# Proposal H mockups

Static HTML/CSS mockups for
[`docs/proposals/proposal-h-unified-display-page.md`](../../proposal-h-unified-display-page.md)
— the unified print-sheet-preview + card-details-rail page. These are
design artifacts, not application code: plain HTML with hand-written CSS
(`shared.css`), no build step, no framework. Card art is a gray 63:88
placeholder rectangle throughout; real measurements and behavior notes
are inline in each page as small annotated captions.

**HOLD — nothing here is a build target yet.** See the design doc for
scope, sequencing, and open decisions.

## How to view

Open any file directly in a browser — `file:///path/to/this/directory/desktop.html`
— or serve the directory locally (`python3 -m http.server`, then visit
`http://localhost:8000/desktop.html`) if your browser restricts local
`file://` stylesheet loading. All five pages load the same
`shared.css`; keep it alongside them.

| File                                             | Breakpoint                | What it shows                                                                                                                                    |
| ------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| [`desktop.html`](desktop.html)                   | 1920×1080                 | Sheet + persistent 400px rail, both fully inline; slot 18 selected, rail showing all 7 instruments                                               |
| [`laptop.html`](laptop.html)                     | 1366×768                  | Rail narrowed to 350px; toolbar's paper/bleed/guides controls collapsed into one "Print Settings" popover trigger                                |
| [`tablet.html`](tablet.html)                     | 768–992 (rendered at 900) | Two states in one file: default (rail closed, edge handle only) and open (rail as a 340px right-side off-canvas drawer)                          |
| [`mobile.html`](mobile.html)                     | <768 (rendered at 390)    | Default view — sheet only, single column, compact toolbar                                                                                        |
| [`mobile-rail-open.html`](mobile-rail-open.html) | <768 (rendered at 390)    | Slot selected — rail as a full bottom-sheet/overlay in plain document flow (no `position: fixed`/`sticky`), all 7 instruments stacked vertically |

## Palette

Values are hand-copied from the Superhero theme already live on this
site (`frontend/`), not invented for these mockups: body `#2B3E50`,
panel `#4E5D6C`, text `#EBEBEB`, accent `#DF691A`, success `#5cb85c`,
danger `#d9534f`, `border-radius: 0` throughout, Lato at a 15px base.
