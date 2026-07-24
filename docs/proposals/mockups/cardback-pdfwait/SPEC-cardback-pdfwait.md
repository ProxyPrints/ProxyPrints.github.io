# /editor flow — cardback flow (PKG 1) + PDF-generation wait experience (PKG 2)

> Durable copy, recovered 2026-07-24 from session tmp storage (same
> durability convention as [`../../../reference/funnel-spec.md`](../../../reference/funnel-spec.md)) —
> this is the owner-approved BINDING spec that committed code comments
> across open PR branches (e.g. `CardbackApplyPrompt.tsx`, `CommonCardback.tsx`,
> `PrePrintSaveGate.tsx`, `SlotCardbackControl.tsx`, `useCardbackReminderGate.tsx`)
> cite by filename as their authority. Content below is verbatim from the
> 2026-07-24 original, including its OWNER AMENDMENTS section.

Companion to `cardback-pdfwait-mockup.html` (same directory). Owner reviews the mockup in a browser
BEFORE any implementation. Verified with Playwright at **390px (native + forced)** and **1400px**;
zero page errors (see §H).

**Inherited base (unchanged unless a row says REVISES):** `SPEC-editor-polish.md` +
`SPEC-rail-delegacy.md` + the corrected-bundle #302 palette. Every token tagged `I` there is still
binding; this round reads as the SAME design language (dark `#0f2537/#22303f/#2b3e50/#4e5d6c` chrome,
`$primary #df6919`, radius `0`, pill `10px`, Lato). All values below are **BINDING** (owner standing
rule 2026-07-23: a visual regression against an approved mockup is a defect).

**Grounded in shipped code (read, not assumed):**
`PrePrintSaveGate.tsx` (flush → optional Save/Skip → `router.push("/print")`; dismiss = cancel the
whole attempt); `CommonCardback.tsx` (`CommonCardback` / `CardbackToolbarButton` /
`CommonCardbackGridSelector`; a pick dispatches `bulkReplaceSelectedImage({currentImage, selectedImage, face:Back})` **and** `setSelectedCardback` — so the toolbar entry is already project-wide canonical);
`cardbackSlice.ts` (`selectCardbacks` list); `PDFGenerator.tsx` (`imageFetchProgress {completed,total}`
from `pdfRenderService.onImageProgress`; `usePostExportContributionPrompt().notifyExportSucceeded()`);
`PostExportContributionPrompt.tsx` (`<Alert variant="info">` → `/whatsthat`, once-per-session);
`QuestionFeed.tsx` (Level-1 YES / NOT SURE / NO / SKIP, `ThumbButton` min-height floor,
`QuestionFeedCounts`); `docs/features/pdf-generator.md` (eager-WASM history);
`docs/features/printing-tags.md` (the vote-queue funnel + capped-implicit mechanics — LOCKED, no new
mechanic this round).

Legend: `I` = inherited verbatim; `N` = introduced this round; `REV` = revises a named prior decision.

---

## A. Where each surface lands, at a glance

| #   | Item                                      | Surface it touches                                                            | Kind                                 |
| --- | ----------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| 1a  | No-cardback reminder                      | a NEW gate step inside `usePrePrintSaveGate.startPrintFlow` (before nav)      | N (gate step)                        |
| 1b  | Apply-all + set-default prompt (toolbar)  | inline footer of `CommonCardbackGridSelector`'s `GridSelectorModal`           | N (inline, no stacked modal)         |
| 1b  | Apply-all + set-default prompt (rail)     | inline block under the per-slot cardback control on the left rail             | N (inline, no modal)                 |
| 1c  | Site-default cardback                     | assumed to exist; UI only. Config/seed = Annex A-1                            | seam only                            |
| 2a  | Generation progress bar                   | `PDFGenerator.tsx` left column, replaces the bare "Fetching images: N/M" text | N (`ProgressBar`)                    |
| 2b  | Embedded What's That Card? game           | `PDFGenerator.tsx` right column, shown while `isDownloading`                  | N (embeds `<QuestionFeed>` verbatim) |
| 2b  | Game outro = PostExportContributionPrompt | replaces the game on finish (one nudge, not two)                              | REV #166 placement                   |
| 2c  | Memory-safety constraint                  | implementer note (lazy-load on start, tear down on finish)                    | N (constraint)                       |

---

## B. react-bootstrap primitive mapping (no new dependencies)

| Element (this round)                | Primitive(s)                                                                                                      | Component reused / additive prop                                                                                                                                                                                                 |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cardback reminder gate (1a)         | `Modal` (md) — Header/Body/Footer, `Button variant="primary"` + `Button variant="outline-light"`                  | a new step composed INTO `usePrePrintSaveGate` (same hook that owns the Save/Skip `Modal`); the cardback picker it opens is the existing `CommonCardbackGridSelector`                                                            |
| Cardback grid (both entries)        | `GridSelectorModal` (toolbar) / inline grid (rail)                                                                | `CommonCardbackGridSelector` verbatim — same `selectCardbacks`, same `bulkReplaceSelectedImage`+`setSelectedCardback` on pick                                                                                                    |
| Apply-all + set-default prompt (1b) | `Alert`-shaped inline panel with two `Button size="sm"` (distinct variants) + a "Not now" `Button variant="link"` | NEW presentational panel; additive callback surfaced from `CommonCardback`/`CommonCardbackGridSelector` `onClick` (after the existing dispatch), plus a new `applyCardbackToAll` thunk + a `setDefaultCardback` preference write |
| Per-slot cardback control (rail)    | `Card.Img`/`<img>` swatch + `Button size="sm" variant="outline-light"` ("Choose a different back…")               | reuses the rail subject-image idiom (§D SPEC-rail-delegacy `.subject`) at the back-face                                                                                                                                          |
| Progress bar (2a)                   | `ProgressBar` (`now`=determinate; `animated striped`=indeterminate; `variant="success"`=done)                     | `progress` SCSS already imported (`styles.scss`); driven by the existing `imageFetchProgress` state                                                                                                                              |
| Game embed frame (2b)               | `Card`/`div` frame + `next/dynamic(() => import("QuestionFeed"), {ssr:false})`                                    | `QuestionFeed` rendered verbatim; NO new voting mechanic                                                                                                                                                                         |
| Game outro (2b)                     | `PostExportContributionPrompt` (`<Alert variant="info">`)                                                         | the SHIPPED component, unchanged — repositioned as the embed's outro                                                                                                                                                             |
| Generate/Save buttons (context)     | `Button` + `Spinner`                                                                                              | unchanged `PDFGenerator` buttons                                                                                                                                                                                                 |

Shared components gain only additive, optional, behaviour-preserving props. No display-only fork.

---

## C. PACKAGE 1 — cardback flow

### C.1 (1a) Export-time reminder — a GATE STEP, not a nag loop

Placement is inside `usePrePrintSaveGate.startPrintFlow()`, ordered so it is a deck-completeness
decision that runs BEFORE the persistence decision and BEFORE navigation:

```
startPrintFlow():
  flushDraftNow(); notifyPromoteDraftPrePrint();          // unchanged (D9(3)a)
  ── NEW gate step ────────────────────────────────────────────────────────────
  if ( ridingUntouchedDefault  &&  !suppressedThisSession(projectId) )
      show CardbackReminder:
        • "Choose a cardback"      → opens CommonCardbackGridSelector; on pick → continue ↓
        • "Use current & continue" → suppressThisSession(projectId); continue ↓
        • dismiss (✕ / Esc / backdrop) → CANCEL the whole print attempt (no nav, nothing saved)
  ── existing branch (unchanged) ──────────────────────────────────────────────
  if (isAuthenticated && isProjectDirty) show Save/Skip Modal → proceedToPrint()
  else proceedToPrint()                                    // router.push("/print")
```

- **Fire condition — `ridingUntouchedDefault`.** The reminder appears ONLY when the project cardback
  is still the site/user default and the user has never explicitly set one this project. A deck with a
  chosen cardback never sees it. (Implementer seam: a boolean derived from projectSlice — "cardback was
  explicitly set" — since a default always resolves a non-null `projectCardback`, null-ness alone can't
  distinguish "chose the default" from "never chose". → Annex A-1.)
- **Not a nag loop.** It fires at most once per print attempt, and "Use current & continue" sets a
  per-project **session** suppress (mirroring the post-export prompt's `sessionStorage` once-rule), so a
  second export in the same session is silent. `CB1`.
- **Dismissal semantics (`CB2`).** ✕ / Esc / backdrop = **cancel the print attempt** — deliberately
  identical to the sibling Save gate's own rule (`PrePrintSaveGate` module comment). It is not a trap:
  "Use current & continue" is a first-class footer button right beside the primary, so escaping via the
  X is never the only way to proceed. (This is the one genuine dismissal fork; the safer-consistency
  choice is taken — see `OQ-A` only if the owner prefers dismiss = "use current".)
- **Copy** names the risk plainly ("most printers put a back on every card") and reassures ("keep the
  default and continue — this only asks once per print"). Primary CTA = "Choose a cardback".

### C.2 (1b) Apply-all + set-default prompt — two distinct, skippable choices, from both entries

On selecting a cardback, a prompt offers **two independent, clearly-distinct, individually-skippable**
actions. It is rendered INLINE, never as a second modal stacked over the picker (honours
`CommonCardback.tsx` §4.4′'s modal-stacking ban):

- **Toolbar entry (`CardbackToolbarButton` / `CommonCardback`) = project-wide canonical.** The pick
  already runs `bulkReplaceSelectedImage({currentImage: projectCardback, …, face:Back})` +
  `setSelectedCardback`, so every slot that FOLLOWS the project cardback updates automatically. The
  prompt's "Apply to all" therefore means **also override the M slots that carry a deliberately-custom
  back** — counted explicitly ("also overrides the 1 card with a custom back"), and never pre-applied.
  The prompt renders as the inline footer of the `GridSelectorModal` body (same modal, no new one).
- **Rail entry (per-slot) = per-slot.** A pick sets ONLY that slot's back. The prompt renders inline
  in the rail directly under the slot's cardback control (no modal at all — the rail per-slot picker is
  already the "no modal, ever" surface). "Apply to all card backs in this deck" is an explicit,
  **never-pre-checked** opt-in with a visible trap-guard line: _"Per-slot pick stays per-slot. 'Apply
  to all' is never pre-checked — a single-slot choice can't silently rewrite the deck."_ (owner-ratified
  no-trap rule).

Both entries share the SAME prompt body (one component, can't drift). The two choices are made visually
distinct by **colour + label + separate action button** (not two look-alike checkboxes):

- **"Apply to all card backs"** → `.applybtn` (primary-tinted `#df6919` border / `#ffb27d` text).
- **"Set as my default cardback"** → `.defbtn` (info-tinted `#5bc0de` border / `#8fd7ea` text).

Each button, once tapped, flips to a green "…✓" done state; either can be skipped ("Not now" link, or
simply leaving — the base selection already stands). Neither action is required to have selected a
cardback. `CB3`.

### C.3 (1c) Site default cardback — UI assumes it exists; the seed is a backend/config seam

The reminder and "Set as my default" both presuppose a resolvable default. Design treats it as present.
**Two seams, noted not designed (Annex A-1/A-2):** (1) which source's cardback DOCUMENT ships as the
site fallback (the owner-drive cardback) is a backend/config seed; (2) where a user's "my default"
persists (localStorage for anonymous, account for authenticated) is an app-state seam. No backend
designed here.

---

## D. PACKAGE 2 — PDF-generation wait experience

### D.1 (2a) Progress bar — determinate where the signal exists, honest indeterminate where it doesn't

Two phases, driven by what the pipeline actually exposes:

1. **Fetching images (determinate).** Real signal = `imageFetchProgress {completed,total}` already
   surfaced by `pdfRenderService.onImageProgress`. `ProgressBar now={min(completed/total,1)*100}`, label
   "Fetching images: N of ~M". `total` is **approximate** (it undercounts duplicate cards, so `completed`
   can exceed it — `pdf.worker.ts` comment) → it is shown as "~M" and the bar is **capped at 99% / never
   shows a false 100%** until the phase actually ends. This replaces today's bare
   `pdf-image-fetch-progress` text line, not adds to it.
2. **Assembling PDF (indeterminate).** After fetch, `@react-pdf/renderer` lays out + encodes with **no
   progress callback exposed** (only `onImageProgress` exists). → `ProgressBar animated striped` with an
   honest "Assembling PDF…" label. Seam noted in the box itself. `PB1` (Annex A-3): if a future render
   seam exposes assemble progress, swap this leg to determinate; until then, indeterminate is the honest
   presentation, not a placeholder to fill with a fake number.
3. **Done.** `ProgressBar variant="success" now={100}` + "✓ PDF ready — saved to your device."

The box carries both `isDownloading` and `isSavingToDrive` (the Save-to-Drive path has the same fetch
phase). It never blocks the buttons above it.

### D.2 (2b) Embedded What's That Card? game — reuse the real funnel, verbatim

While generation runs, the right column (today: the stale live preview) is replaced by an embed frame
that renders **`<QuestionFeed>` verbatim** — the exact vote-queue funnel from `/whatsthat`
(`docs/features/printing-tags.md`). **No new voting mechanic, no forked component**: Level-1
YES / NOT SURE / NO / SKIP, Level-2 candidate grid, Level-3 exclusion chips, `QuestionFeedCounts`, and
the capped-implicit / weighted-consensus rules are all unchanged. The embed adds only chrome:

- **Embed frame** (`.gameembed`): header "While your PDF builds — help identify a card?" + a `lazy-loaded on generate · torn down on finish` note, and a **persistent build-status ribbon** (`.geband`) that
  keeps the PDF's progress visible so the two coexist (the user always sees the build state while
  playing).
- **Entry.** The embed (and thus `QuestionFeed`) is **lazy-loaded only when generation starts**
  (`isDownloading` true) via `next/dynamic({ssr:false})` — an idle user configuring the PDF never
  carries the game's weight. (2c.)
- **Generation finishes mid-round.** The build ribbon flips to green "✓ Your PDF is ready — saved to
  your device," and the game is **torn down** (unmount → memory reclaimed) and **replaced by the
  outro** (D.3). Nothing is lost: `QuestionFeed` POSTs each answer the instant it's tapped
  (`castVote`/`castImplicitVote`), so an already-submitted answer survives the unmount; an
  un-submitted, half-considered card is simply dropped (never a partial vote). Copy in the embed foot
  states this ("leaving mid-card never loses a vote").
- **Exit.** Dismissing the outro, or navigating away, is the terminal teardown.

### D.3 (2b) Relationship with PostExportContributionPrompt — the outro IS the prompt (one nudge)

Owner note: they reinforce. Proposed relationship — **the existing `PostExportContributionPrompt`
becomes the game embed's outro**, not a second, separate nudge:

- When the game embed was shown for this export, on finish the embed's game unmounts and the
  **`PostExportContributionPrompt` (`<Alert variant="info">` → `/whatsthat`)** renders in its place, with
  the CTA reading "Keep going on What's That Card? →" (context-aware, since the user was just playing).
- The standalone bottom-of-settings mount of `PostExportContributionPrompt` is **suppressed when the
  embed handled this export** — so there is exactly one nudge, governed by the unchanged
  once-per-session rule (`usePostExportContributionPrompt`). When the embed did NOT run (reduced-motion
  opt-out, game unavailable, or a generation too short to have shown it), the standalone prompt fires as
  today. `PE1`.

### D.4 (2c) Memory-safety — binding constraint for the implementer

Generation is WASM/memory-heavy (`docs/features/pdf-generator.md`: `@react-pdf/renderer` instantiates a
Yoga WASM binary; a large export peaks memory). The game embed MUST NOT compound that peak:

1. **Lazy-load only after generation starts.** The `QuestionFeed` module is `next/dynamic({ssr:false})`
   and imported only when `isDownloading` becomes true — never eagerly bundled/instantiated on the print
   page. (Mirrors the bug-1 lazy-WASM fix's own posture.)
2. **Do not contend for the full-resolution fetch budget.** `QuestionFeed`'s own hero images use the
   small/large thumbnail tiers, NOT the semaphore-capped full-resolution path the PDF export saturates
   (`pdfImage.ts` `FULL_RESOLUTION_FETCH_CONCURRENCY=3`) — so the game's image loads do not steal the
   PDF's paced CDN budget. Verify this holds at wiring time; if any game image would hit the
   full-resolution path, gate it. `MS1`.
3. **Tear down on finish.** The moment `isDownloading` goes false, unmount `<QuestionFeed>` (revoking
   any object URLs it holds) so a SECOND generation's peak isn't inflated by a lingering game — the
   lightweight outro `Alert` is all that remains. Governing-premise clean throughout: transient display
   only, nothing stored.

---

## E. BINDING token table (`I`/`N`; every element of the affected surfaces)

Palette tokens (all `I`, #302): `--body #0f2537`, `--panel #4e5d6c`, `--raised #22303f`,
`--conf #2b3e50`, `--text #ebebeb`, `--muted #8fa0b0`, `--light #abb6c2`, `--primary #df6919`
(hover `#be5915`), `--success #5cb85c`, `--danger #d9534f`, `--warning #ffc107`, `--info #5bc0de`,
`--input-border #4e5d6c`, `--divider #16202b`, radius `0`, pill `10px`.

### E.1 Cardback reminder gate (1a) — real Modal on Superhero

| Element                      | Sizing                                           | Colour (bg / text / border)                                                       | Spacing                                                     | I/N                             |
| ---------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------- |
| `.mdialog` (Modal content)   | `width:500px`, `max-width:calc(100%-24px)`; r`0` | `#4e5d6c` (real `$modal-content-bg`) / `#ebebeb` / `1px rgba(0,0,0,.2)`           | shadow `0 12px 40px rgba(0,0,0,.6)`                         | I (framework) / N (composition) |
| `.mhead .mtitle`             | `18px/700`                                       | `#ebebeb`                                                                         | `padding:14px 16px`; border-bottom `rgba(0,0,0,.2)`         | I                               |
| `.mhead .mx` close           | `20px`                                           | `#ebebeb` @ `opacity:.7`                                                          | —                                                           | I                               |
| `.mbody`                     | `14px`                                           | text `#ebebeb`; sub `#8fa0b0 13px`                                                | `padding:16px`; p `mb:12px`                                 | I                               |
| **`.cbremind .curback`**     | **`88px`** wide, aspect `63/88`                  | cardback art; cap `rgba(0,0,0,.6)`/`#a99 9px`; border `1px rgba(235,235,235,.15)` | `flex:0 0 88px; gap:14px`                                   | **N**                           |
| **`.dfnote` (1c seam note)** | `12px`                                           | `#8fa0b0`; seam phrase `#ffd76a`                                                  | `mt:10px; pt:8px`; top border `#16202b`                     | **N**                           |
| `.mfoot` buttons             | `.btn`=`14px / 6px 14px` r`0`                    | primary `#df6919`/`#fff`; "Use current" `outline-light` `#abb6c2`                 | `padding:12px 16px`; gap `8px`; top border `rgba(0,0,0,.2)` | I                               |

### E.2 Cardback grid + apply/default prompt (1b)

| Element                               | Sizing                                                          | Colour (bg / text / border)                                                                           | Spacing                      | I/N                                    |
| ------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------- | -------------------------------------- |
| `.mdialog.wide` (grid modal)          | `width:640px`                                                   | as `.mdialog`                                                                                         | —                            | I                                      |
| **`.cbgrid`**                         | `repeat(auto-fill,minmax(78px,1fr))`; `max-height:230px` scroll | `#22303f` / — / `1px #16202b`                                                                         | `gap:8px; padding:4px`       | **N**                                  |
| **`.cbtile`**                         | aspect `63/88`                                                  | cardback art; sel `2px #df6919`; `.lab` `rgba(0,0,0,.55)`/`#cdd6df 8px`; ★ default `#ffc107`          | —                            | **N** (reuses GridSelector tile idiom) |
| **`.cbprompt`** panel                 | —                                                               | `#22303f` / — / `1px #16202b` + left `3px #df6919`                                                    | `padding:10px 12px; mt:12px` | **N**                                  |
| `.cbprompt .ct` title                 | `13px/700`                                                      | `#ebebeb`                                                                                             | `mb:2px`                     | N                                      |
| `.cbprompt .cintro`                   | `12px`                                                          | `#8fa0b0`                                                                                             | `mb:10px`                    | N                                      |
| **`.choice`** row                     | —                                                               | top border `#16202b` (none on first)                                                                  | `gap:10px; padding:8px 0`    | **N**                                  |
| `.choice .cl .h` / `.s`               | `13px` / `11px`                                                 | `#ebebeb` / `#8fa0b0`                                                                                 | —                            | N                                      |
| **`.applybtn`** (apply-all)           | `13px / 4px 10px` r`0`                                          | transparent / `#ffb27d` / `1px #df6919`; hover fill `#df6919`/`#fff`; done `#8fe08f`/`1px #5cb85c`    | —                            | **N**                                  |
| **`.defbtn`** (set default)           | `13px / 4px 10px` r`0`                                          | transparent / `#8fd7ea` / `1px #5bc0de`; hover fill `#5bc0de`/`#062430`; done `#8fe08f`/`1px #5cb85c` | —                            | **N**                                  |
| `.cbprompt .skip a`                   | `12px` underline                                                | `#8fa0b0`                                                                                             | `mt:8px`; right-aligned      | N                                      |
| **`.cbprompt .trapnote`** (rail only) | `11px`                                                          | `#ffd76a`; leading `⚠`                                                                                | `mt:8px; gap:5px`            | **N**                                  |
| **rail `.slotback .bthumb`**          | `54px` wide, aspect `63/88`                                     | back-face art; cap `#a99 8px`; border `1px rgba(235,235,235,.15)`                                     | `flex:0 0 54px; gap:9px`     | **N**                                  |
| rail `.slotback .bchoose`             | `btn-sm` `13px / 4px 8px`                                       | `outline-light` `#abb6c2`                                                                             | `mt:6px`                     | N                                      |

### E.3 Generation progress bar (2a)

| Element                     | Sizing                                  | Colour (bg / text / border)                                       | Spacing                      | I/N                             |
| --------------------------- | --------------------------------------- | ----------------------------------------------------------------- | ---------------------------- | ------------------------------- |
| **`.progressbox`**          | —                                       | `#22303f` / — / `1px #16202b`                                     | `padding:10px 12px; mt:12px` | **N**                           |
| `.plabel`                   | `12px`; frac tabular                    | `#ebebeb`; frac `#8fa0b0`                                         | `mb:6px`                     | N                               |
| **`.progress`** track       | `height:10px`; r`0`                     | `#16202b`                                                         | —                            | **N** (Bootstrap `ProgressBar`) |
| **`.bar` determinate**      | `width:min(completed/total,1)`, cap 99% | `#df6919`                                                         | transition `.3s`             | **N**                           |
| **`.bar.indet` (assemble)** | `width:100%`                            | `#df6919` + `rgba(255,255,255,.18)` stripe; `barstripe 1s linear` | —                            | **N**                           |
| **`.bar.done`**             | `width:100%`                            | `#5cb85c`                                                         | —                            | **N**                           |
| `.psub` / `.psub.donec`     | `11px`                                  | `#8fa0b0` / `#8fe08f`                                             | `mt:6px`                     | N                               |
| **`.seamtag`**              | `11px`                                  | `#ffd76a`                                                         | `mt:6px`                     | **N** (2a seam label)           |

### E.4 Game embed + outro (2b)

| Element                                     | Sizing                                                  | Colour (bg / text / border)                                                                                      | Spacing                                              | I/N                                                |
| ------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| **`.gameembed`** frame                      | fills right col; `min-height:420px` (phone `520`)       | `#22303f` / — / `1px #16202b`                                                                                    | column flex                                          | **N**                                              |
| `.gehead`                                   | `12px/700` uppercase; dot `8px`                         | `#2b3e50` / `#8fa0b0`; dot `#df6919`; `.lz` `#8fa0b0 10px` mono                                                  | `padding:8px 12px; gap:8px`; bottom border `#16202b` | N                                                  |
| **`.geband`** build ribbon                  | `11px`; mini bar `6px`                                  | `#0b1520` / `#ebebeb`; mini `#16202b`→`#df6919`; done `#8fe08f` + `#5cb85c` fill                                 | `padding:6px 12px; gap:8px`                          | **N**                                              |
| `.gecard` hero                              | `132px`, aspect `63/88`                                 | art; name `rgba(0,0,0,.6)`/`#ebebeb 9px`; border `1px rgba(235,235,235,.15)`                                     | —                                                    | I (QuestionFeed hero idiom)                        |
| `.gecount` / `.geq`                         | `11px` / `14px` (qn `12px`)                             | `#8fa0b0` / `#ebebeb`                                                                                            | —                                                    | I                                                  |
| **`.tbtn`** (ThumbButton)                   | full-width ≤`340px`; `min-height:44px`; `15px/600` r`0` | yes `#5cb85c`; notsure `#ffc107`; no `#d9534f`; skip `link`/`#ffc107` `min-height:36px` (all outline→hover fill) | `gap:8px`                                            | I (QuestionFeed `ThumbButton` floor — reproduced)  |
| `.gefoot`                                   | `10px`                                                  | `#8fa0b0`                                                                                                        | `padding:6px 12px`; top border `#16202b`             | N                                                  |
| **`.outro`** (PostExportContributionPrompt) | —                                                       | **`#cff4fc` / `#055160` / `1px #b6effb`** (REAL BS5 `alert-info`); link `#04414d`/700                            | `margin:14px; padding:14px 16px`                     | **I** (shipped `<Alert variant="info">`, verbatim) |
| `.spinner` (Generate btn)                   | `1.15em`, `.18em` ring                                  | `rgba(255,255,255,.4)` / right transparent; `spin .75s`                                                          | —                                                    | I (`Spinner.tsx`)                                  |

### E.5 Print-page + editor context (reaffirmed, unchanged)

Appbar (`.abtn`/`.cbtoolbtn`/`.pill`/`.gear`), three-region rail language (left rail `#4e5d6c`, center
sheet `#0f2537`, right project rail `#4e5d6c`), `.finishbtn`/`.genbtn` primary `#df6919`, `.genbtn2`
outline-primary, `.setrow` `12px #8fa0b0`/`#ebebeb`, and the phone stacking rule (all three regions
stack full-width in one scroll container so every surface is reachable) are `I` from the inherited
rounds / shipped `PDFGenerator` two-column layout. No value changes.

---

## F. FEATURES ACCOUNTED FOR

| Ref | Requirement (dispatch)                                                | Accounted where                                                     | Demoed in mockup                    |
| --- | --------------------------------------------------------------------- | ------------------------------------------------------------------- | ----------------------------------- |
| 1a  | Reminder when heading to save/export/print w/o a cardback             | §C.1; gate step in `usePrePrintSaveGate`                            | Scene "1a · no-cardback reminder"   |
| 1a  | Dismissal semantics — gate step, not a nag loop                       | `CB1`/`CB2` (once-per-attempt, session suppress, dismiss=cancel)    | gate footer buttons + ✕             |
| 1b  | Prompt: apply-to-all + separate set-default; distinct + skippable     | §C.2; `.applybtn` vs `.defbtn` + "Not now"                          | both apply scenes                   |
| 1b  | Toolbar = project-wide canonical                                      | §C.2 (bulkReplace already runs; prompt overrides customs)           | "1b · apply — toolbar"              |
| 1b  | Rail = per-slot; apply-to-all must not be a trap                      | §C.2 + `.trapnote`, never-pre-checked                               | "1b · apply — rail"                 |
| 1c  | Site default = owner-drive cardback; assume it exists, note seam      | §C.3; Annex A-1/A-2; `.dfnote` seam chip                            | gate + prompt seam notes            |
| 2a  | Progress bar; determinate if signal exists, honest indeterminate else | §D.1; `.bar` / `.bar.indet` / `.bar.done`; `.seamtag`               | Fetching / Assembling / Done phases |
| 2b  | Embedded WTC game, reuse real funnel mechanics/components             | §D.2; `<QuestionFeed>` verbatim, no new mechanic                    | "2 · PDF wait + game"               |
| 2b  | Embed frame, entry/exit, finish-mid-round                             | §D.2 (lazy-load entry, ribbon flip, unmount+outro, per-answer POST) | fetch → done transition             |
| 2b  | Coexist with PostExportContributionPrompt (prompt as outro)           | §D.3; `PE1` (one nudge)                                             | Done → outro scene                  |
| 2c  | Memory-safety: lazy-load on start, tear down on finish                | §D.4; `MS1` (no full-res contention) + teardown                     | embed header note                   |

---

## G. Accessibility

Reminder gate is a `Modal role="dialog" aria-modal` with focus on the primary; ✕/Esc/backdrop cancel
(consistent). Apply-all / set-default are two labelled `button`s (colour is never the only signal —
each has a distinct text label and a "✓" done text). The prompt's "Not now" is a real link/button. The
`ProgressBar` carries `role="progressbar"` with `aria-valuenow` in the determinate phase and
`aria-busy`/text label in the indeterminate phase (no false numeric). `QuestionFeed` keeps its shipped
a11y verbatim (the `ThumbButton` min-height floor, per-option glyph/text). The outro `Alert` keeps its
`Alert.Link`. Phone: all three regions stack in one scroll container; the modal becomes a bottom-sheet;
every control reachable (§H).

---

## H. Verification

Playwright (`shot.js`, chromium), screenshots inspected at **1400px** and **390px (native + forced)**.
**Zero page errors across all frames.**

- `v-1400-gate.png` — 1a reminder gate over the editor; current-cardback preview, "Choose a cardback"
  primary + "Use current & continue", 1c seam note.
- `v-1400-apply-toolbar.png` — 1b toolbar: `GridSelectorModal` grid + inline apply/default prompt
  (project-wide copy, "also overrides custom").
- `v-1400-apply-rail.png` — 1b rail: per-slot control + inline prompt with the never-pre-checked
  trap-guard line; no stacked modal.
- `v-1400-pdf-fetch.png` / `v-1400-pdf-assemble.png` / `v-1400-pdf-done.png` — 2a determinate fetch
  bar → indeterminate assemble stripe → green done; 2b game embed (ThumbButton stack + build ribbon) →
  on done, game replaced by the real info-alert outro; Generate button re-enables on done.
- `v-390-native-gate.png` — phone: reminder as a bottom-sheet Modal over the stacked editor.
- `v-390-native-apply-rail.png` — phone: rail (with slot cardback + inline prompt), center sheet, and
  right project rail + Print/Export all reachable in one scroll.
- `v-390-native-pdf-fetch.png` / `v-390-native-pdf-done.png` — phone print page stacks: settings →
  progress → game embed (then outro), fully reachable.
- `v-phone-forced-*.png` — forced-phone frames at a wide window (transform-scaled), same reachability.

**Bug caught + fixed in review:** (1) the phone frame first HID the left rail, hiding the 1b-rail
prompt — fixed by stacking all three regions full-width in one scroll container (every surface reachable
on the phone). (2) the "done" phase left the Generate button reading "Generating…" — fixed so it
re-enables once the download resolves (`generating = fetch||assemble`).

---

## I. Annex — the seams (noted, NOT designed here)

- **A-1 (1a/1c) Default-cardback config + "was cardback explicitly chosen".** Which source's cardback
  DOCUMENT ships as the site fallback (the owner-drive cardback) is a backend/config seed. Separately,
  the reminder's fire condition needs a projectSlice boolean distinguishing "chose the default" from
  "never chose" (null-ness alone can't, since a default always resolves non-null). Both are
  backend/state seams; the UI assumes a resolved default + a derivable "explicit" flag.
- **A-2 (1b) "My default" persistence.** "Set as my default cardback" writes a user preference:
  localStorage for anonymous, account-persisted for authenticated (mirroring how favourites/projects
  already split). Not designed here.
- **A-3 (2a) Assemble-phase progress signal.** `pdfRenderService` exposes only `onImageProgress`; the
  `@react-pdf/renderer` layout/encode phase has no progress callback. The spec's indeterminate assemble
  bar is the honest presentation; if a render seam later exposes assemble progress, swap that leg to
  determinate (`PB1`).

---

## J. Open questions — ONLY the genuine owner forks

- **OQ-A (1a dismissal).** Ruled `CB2` = dismiss (✕/Esc/backdrop) cancels the whole print attempt, to
  match the sibling Save gate exactly. The alternative — dismiss = "use current & continue" (a valid
  default exists, so proceeding is safe) — is defensible too. Confirm the safer-consistency default, or
  flip it? (Recommendation: keep cancel-on-dismiss; "Use current & continue" is a first-class button, so
  it isn't a trap.)
- **OQ-B (1b toolbar apply-all scope).** For the project-wide toolbar entry, should "Apply to all" also
  overwrite the M slots a user **deliberately** gave a custom back, or leave those custom slots alone?
  Ruled here: it DOES override them, but the count names it ("also overrides the 1 custom back") and it
  is never pre-applied. Confirm, or should custom slots be excluded from "apply to all"?
  (Recommendation: override-with-count — one predictable meaning of "all"; the per-slot rail entry
  remains the way to keep a slot different.)
- **OQ-C (2b game persistence after finish).** Ruled `PE1`/`D.2` = on finish the game is torn down and
  the `/whatsthat` outro replaces it (memory-safety + one-nudge). The alternative is keeping the game
  alive inline post-finish so a user can keep playing without leaving the page (heavier: the embed lingers
  into any second generation's memory peak). Confirm teardown-to-outro, or keep-playing-inline?
  (Recommendation: teardown-to-outro; the outro's link carries anyone who wants to keep going to
  `/whatsthat`, where the funnel already lives.)

## OWNER AMENDMENTS — 2026-07-24 post-review (BINDING, supersede conflicting rows above)

1. OQ-A RULED (overrules the spec's recommendation): dismissing the no-cardback reminder
   (✕/Esc/backdrop) means "use current default & continue" — the print attempt PROCEEDS.
   The explicit "Use current & continue" button stays; dismiss is its shorthand, not a cancel.
2. OQ-B RULED: apply-to-all uses override-with-count AND shows the affected cards — the
   prompt renders thumbnails (front + current custom back) of every slot whose custom back
   would be overwritten, above the count line. Never pre-checked, unchanged.
3. NEW ELEMENT (owner addition): the sheet cell's corner flip icon (⟲, from EP6) carries a
   small non-default-back indicator (dot/badge within the existing icon footprint) whenever
   that slot's cardback differs from the deck default — passive awareness before any
   warning. Same gating as the flip icon itself (card-holding cells only); tooltip/aria
   "Custom cardback". Token-conformant; no new color roles (reuse warning or info token).
4. OQ-C RULED: teardown-to-outro as recommended (game unmounts on finish; the existing
   /whatsthat outro prompt is the single post-export nudge).
