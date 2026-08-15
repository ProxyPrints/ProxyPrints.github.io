# docs/proposals/mockups/

Design-artifact bundles: a spec (`SPEC-*.md`) plus its companion static-HTML
mockup, one directory per round. Most are BINDING owner-approved specs; a
bundle that has not been ratified says so in its own header and in its entry
below (`editor-repass/` is currently the only one). These are
design artifacts, not application code — see each bundle's own header for
its "how to view" instructions. Like the rest of `proposals/`, never
published to the wiki (per
[`../../documentation-process.md`](../../documentation-process.md)) — a
spec here isn't necessarily shipped yet, and some (see below) are
durability copies of work that landed only on an open PR branch, not
`master`.

- [`proposal-h/`](proposal-h/README.md) — mockups for
  [`../proposal-h-display-layout-spec.md`](../proposal-h-display-layout-spec.md)
  (the living `/display` spec) and its historical predecessor
  [`../proposal-h-unified-display-page.md`](../proposal-h-unified-display-page.md).
  See that directory's own `README.md` for the file-by-file breakdown.
- [`rail-delegacy/SPEC-rail-delegacy.md`](rail-delegacy/SPEC-rail-delegacy.md)
  — the `/editor` left rail delegacy round: the nine grey legacy
  `AutofillCollapse` drop-downs removed, their contents folded into
  designed elements. Companion mockup:
  [`rail-delegacy-mockup.html`](rail-delegacy/rail-delegacy-mockup.html).
- [`editor-polish/SPEC-editor-polish.md`](editor-polish/SPEC-editor-polish.md)
  — the unified `/editor` consolidated polish round (eleven owner-settled
  items + the slot-menu cue), inherited on top of the rail-delegacy round
  above. Companion mockup:
  [`editor-polish-mockup.html`](editor-polish/editor-polish-mockup.html).
- [`cardback-pdfwait/SPEC-cardback-pdfwait.md`](cardback-pdfwait/SPEC-cardback-pdfwait.md)
  — the `/editor` cardback flow (PKG 1) + PDF-generation wait experience
  (PKG 2), inherited on top of both rounds above. Companion mockup:
  [`cardback-pdfwait-mockup.html`](cardback-pdfwait/cardback-pdfwait-mockup.html).
- [`editor-repass/SPEC-editor-repass.md`](editor-repass/SPEC-editor-repass.md)
  — the `/editor` design repass: eleven numbered items (R1–R11) diagnosing why
  the left rail reads as a metadata surface rather than an image one, and why
  settings ended up in dialogs the rails were meant to carry. Covers art-tile
  sizing and the asset tier behind it, survivor-grid windowing, rail reordering,
  the three search-settings homes, the export-settings modal, the finish
  footer's button weights, the requery glyph, the four cardback surfaces, one
  visual vocabulary, and density. **PROPOSAL — not ratified**; it contradicts
  several shipped decisions and says which, per item. Companion mockup:
  [`editor-repass-mockup.html`](editor-repass/editor-repass-mockup.html).
- [`wtc-rebuild/SPEC-wtc-rebuild.md`](wtc-rebuild/SPEC-wtc-rebuild.md) —
  the "What's That Card?" (`/whatsthat`) rebuild spec: Tokyo-11 theme
  adoption for the page's own prior bespoke identity. Companion mockup:
  [`wtc-mockup.html`](wtc-rebuild/wtc-mockup.html).

## Why these four are here (durability, not a new proposal)

`rail-delegacy/`, `editor-polish/`, `cardback-pdfwait/`, and
`wtc-rebuild/` were brought into the repo as verbatim durability copies
(2026-07-24) of specs that previously lived only in a session's tmp
directory — which does not survive past that session — while committed
code comments on several open PR branches already cite each spec by
filename as its binding authority. Same gap
[`../../reference/funnel-spec.md`](../../reference/funnel-spec.md) closed
when it was recovered during the 2026-07-23 D-lettering sweep (it had
been cited from `docs/features/grid-selector.md` but never itself
committed). Each file's own header names which committed comments cite
it. These are reference copies of specs authored for their respective
(still-open, not-yet-merged) PRs, not a statement that the surfaces they
describe have shipped to `master`.
