# Unified /editor — consolidated polish round (eleven owner-settled items + the ⋯ slot-menu cue)

> Durable copy, recovered 2026-07-24 from session tmp storage (same
> durability convention as [`../../../reference/funnel-spec.md`](../../../reference/funnel-spec.md)) —
> this is the owner-approved BINDING spec that committed code comments
> across open PR branches (e.g. `AutofillCollapse.tsx`, `ConfidenceElement.tsx`,
> `DisplayPage.tsx`, `SelectVersionResults.tsx`, `SlotActionsSection.tsx`,
> `SourcesAccordion.tsx`) cite by filename as their authority. Content below
> is verbatim from the 2026-07-24 original, including its OWNER AMENDMENTS
> section.

Companion to `editor-polish-mockup.html` (same directory). Owner reviews the mockup in a browser
BEFORE any implementation. Verified with Playwright at **390 / 900 / 1400px** (see §H).

**Inherited base (unchanged unless a row below says REVISES):** `SPEC-rail-delegacy.md` (the nine-grey-
accordion delegacy round) and its corrected-bundle #302 palette. Every token there tagged `I` is
still binding; this round supplies only the DELTA — the rows this round revises and the rows it
introduces — plus reaffirms the surrounding inherited rows so §D is a complete page table (owner
standing rule 2026-07-23: approved token values are binding; a visual regression against an approved
mockup is a defect).

**LOCKED, not reopened:** RD7 (mismatch-only rail badge). D14's confirmed-`✓` / "N% confident" pill
treatment (owner likes it — untouched by items 8/9). The ratified implicit-vote chip mechanics
(`printing-tags.md` "Implicit votes" + `grid-selector.md` compliance-fix): funnel chips ARE the
implicit vote (`castImplicitVote`, weight 0.25, per-outcome cap 1.0 < quorum, never human-backed,
SENSITIVE-excluded; SUGGESTED chips from `suggestedFilterTagNames`, dashed + `⌇`). No new voting
mechanic anywhere this round.

Legend per token row: `I` = inherited verbatim; `N` = introduced this round; `REV RDx` = revises a
named rail-delegacy decision. All values are **BINDING**.

---

## A. What changes, at a glance (the eleven items + cue → where they land)

| #   | Item                                            | Surface it touches                  | Kind                           |
| --- | ----------------------------------------------- | ----------------------------------- | ------------------------------ |
| 1   | Ghost tile gains a thumbnail + `+N`             | Select Version grid                 | REV inherited ghost tile       |
| 2   | Whole-page contrast pass (absorb #413 residual) | app chrome + Filters panel controls | N tokens + reaffirm            |
| 3   | Sources de-grey + densify                       | Sources block                       | REV sources rows               |
| 4   | Slot Actions relocate to the top                | rail head (was bottom stack)        | REV RD5                        |
| 5   | Subject image much larger                       | rail head                           | REV RD8                        |
| 6   | Per-slot Front/Back toggle (E24)                | rail head + sheet cell corner       | N (never built)                |
| 7   | Data-driven Sort                                | Select Version header               | REV RD2 / O5                   |
| 8   | Wrong-printing affordance restored/improved     | D14 `.idtoggle` + `.notthis`        | REV (post-#413 look)           |
| 9   | Scryfall compare-on-hover, beside the subject   | D14 pill → rail-head reveal         | N (relocates existing popover) |
| 10  | Round spinner instead of loading bar            | Select Version loading state        | N (reuse `Spinner.tsx`)        |
| 11  | Foreign-order consent / disclaimer UI           | consent toast + sheet cells         | N (built on `useConsentToast`) |
| cue | ⋯ slot-menu cue bigger/contrast + gated         | sheet cell (`PagePreview.tsx`)      | REV `SlotMenuCue`              |

---

## B. react-bootstrap primitive mapping (no new dependencies)

| Element (this round)                    | Primitive(s)                                                                                                                                                                                                                       | Component reused / additive prop                                                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Ghost tile thumbnail + `+N` (1)         | `<img>` (first hidden copy's `smallThumbnailUrl`) + absolute `+N` overlay                                                                                                                                                          | the same tile renderer in `SelectVersionResults.tsx`; additive: a `hiddenCopies` group + count                                    |
| App-chrome action buttons contrast (2)  | `Button variant="outline-*"` with explicit border/text token                                                                                                                                                                       | existing editor toolbar buttons — colour tokens only, no structural change                                                        |
| Filters panel controls fully themed (2) | `DPIFilter`/`SizeFilter`/`LanguageFilter`/`TagFilter`/`MatureContentFilter`                                                                                                                                                        | unchanged components; the residual is CSS-token coverage on the dark rail, not new markup                                         |
| Sources block de-grey + dense (3)       | `AutofillCollapse`? **NO** — the shipped inline `SourcesAccordion` (already inline, owner answer #3); `react-bootstrap-toggle` restyled via `.rail-source-toggle` (shipped) at 31px; `Form.Control` filter input; virtualized list | `SourcesAccordion.tsx` (tokens only + a height/virtualization prop)                                                               |
| Front/Back toggle (6)                   | `ToggleButtonGroup type="radio"` (2 segments) near the subject; sheet-cell `Button` at the reserved E24 corner                                                                                                                     | new toggle; sheet corner is the reserved `PagePreview.tsx:618` slot (additive `onSlotFlip` prop, render-gated like `SlotMenuCue`) |
| Compact top Slot Actions (4)            | 3 × `Button size="sm"` icon buttons (Change/Duplicate/Delete) in a row                                                                                                                                                             | `SlotActionsSection` — same actions (`getCardSlotMenuActions`), icon-compact layout instead of full-width stack                   |
| Larger subject image (5)                | `Card.Img`/`<img>` at a bigger preview footprint                                                                                                                                                                                   | reuses the selected tile's thumbnail URL (not a second full render)                                                               |
| Data-driven Sort (7)                    | `Form.Select size="sm"` over a NEW ordering list; client-side comparator over already-carried fields                                                                                                                               | replaces the 6-option `SortByOptions` select on this surface (see §F annex)                                                       |
| Wrong-printing affordance (8)           | `Button` toggling a `Collapse` (identify panel) restyled to the pre-#413 pill idiom; `Button variant="outline-danger"` (`.notthis`) restyled to a pill                                                                             | `IdentifyPanel` toggle (DisplayPage) + `ConfidenceElement`'s `.notthis` — CSS only, behaviour preserved                           |
| Compare-on-hover / -tap (9)             | `OverlayTrigger`/custom reveal anchored beside the subject image; trigger moved to the D14 pill; `(pointer:coarse)` → tap-toggle                                                                                                   | `ConfidenceElement` — reuses `buildScryfallReferenceImageUrl` (already client-side; §F annex)                                     |
| Round spinner (10)                      | `<Spinner>` (`components/Spinner.tsx`, `.spinner-border`)                                                                                                                                                                          | the site's canonical spinner, reused verbatim                                                                                     |
| Consent toast + disclaimer (11)         | `useConsentToast()` / `ConsentToast` (react-bootstrap `Alert` `role="alertdialog"`, `bottom-end`); denied-state cell placeholder + deck banner                                                                                     | `consent/*` infra reused; new call site + hidden-state render                                                                     |
| ⋯ cue bigger/gated (cue)                | the existing `SlotMenuCue` styled button                                                                                                                                                                                           | `PagePreview.tsx` — size/contrast tokens + render gate on "slot holds a card"                                                     |

Shared components gain only additive, optional, behaviour-preserving props. No display-only fork.

---

## C. Rail-head composition after items 4/5/6 (the one structural change this round)

```
┌ rail-head (#22303f) ───────────────────────────────────────────────┐
│  [ SUBJECT IMAGE ]   Slot 3 · Front            (item 5: 116px, was 66)│
│  [   116px wide  ]   Lightning Bolt                                   │
│  [  aspect 63/88 ]   requested ≠ shown: 2ED 161   (RD7 mismatch only) │
│  [ front|back art]   [ Front | Back ]             (item 6 toggle)     │
│                      [⇄] [⧉] [🗑]                 (item 4: compact,   │
│                      More details ›                 was full-width RD5)│
│      └ item 9 Scryfall compare reveal floats HERE, beside the subject │
├ More details ▸ ── full CardMetaTable + Download/Favourite (rev #1, unchanged)
├ D14 band ─────── LOCKED; ONE canonical id "2X2 · 117"; pills are the item-9 compare trigger
├ identify panel ─ item 8 pill "🔍 Wrong printing? Search the right one" → PrintingTagPicker
├ artist line ──── unchanged
├ Sources ──────── item 3: de-greyed + densified
├ Select Version ─ header [N · Sort▾(item 7) · Filters▾] → filters panel → grid (item 1 ghost) / spinner (item 10)
└ control stack ── item 4 REV: Print Options + Report ONLY (Slot Actions moved up)
```

The bottom control stack loses its Slot-Actions group (moved to the head). It keeps Print Options
(bleed) + Report — neither is a per-slot identity action.

---

## D. BINDING token table (every element on the affected page; `I`/`N`/`REV`)

Palette tokens are the inherited §0 #302 set (`--body #0f2537`, `--panel #4e5d6c`, `--raised #22303f`,
`--conf #2b3e50`, `--card-header #4e5d6b`, `--text #ebebeb`, `--muted #8fa0b0`, `--light #abb6c2`,
`--primary #df6919`/hover `#be5915`, `--success #5cb85c`, `--danger #d9534f`, `--warning #ffc107`,
`--info #5bc0de`, `--divider #16202b`, radius `0`, pill `10px`). All `I`.

### D.1 Rail-head (items 4/5/6/9)

| Element                       | Sizing                                                                                                                                   | Colour (bg / text / border)                                                                         | Spacing                                                         | I/N/REV                                            |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------- |
| `.rhead`                      | —                                                                                                                                        | `#22303f` / `#ebebeb` / bottom `#16202b`                                                            | `padding:8px 10px`                                              | I                                                  |
| `.rhead-row`                  | `position:relative`                                                                                                                      | —                                                                                                   | `gap:10px; align-items:flex-start`                              | I                                                  |
| **`.subject` (5)**            | **`116px` wide**, aspect `63/88` (≈`162px` tall)                                                                                         | art thumbnail; caption `rgba(0,0,0,.6)`/`#cdd6df` `8px`; border `1px rgba(235,235,235,.15)`         | `flex:0 0 116px`                                                | **REV RD8** (was 66px)                             |
| `.subject .backart` (6)       | fills subject                                                                                                                            | dark `#2a2320`↔`#1f1a17` stripe / `#a99` `9px`                                                      | shown when `data-face=back`                                     | N                                                  |
| `.subject.empty`              | same `116×162`                                                                                                                           | transparent / `#8fa0b0` `10px` / `1px dashed #abb6c2`                                               | centred                                                         | REV RD8 (footprint)                                |
| `.idcol`                      | slot `14/700`, name `15px`, empty name italic `#8fa0b0`                                                                                  | `#ebebeb`; face `#8fa0b0` `11px` uppercase                                                          | `flex:1; min-width:0`                                           | I                                                  |
| `.mismatch` (RD7)             | `10px` mono                                                                                                                              | `#ffc107` / `#111`                                                                                  | `mt:5px; padding:1px 7px`; hidden in empty state                | I                                                  |
| **`.fbtoggle` (6)**           | segment `11px/700`, `padding:2px 12px`                                                                                                   | seg `#22303f`/`#8fa0b0`; active `#5bc0de`(info)/`#062430`; border `#6b7d8e`                         | `margin-top:7px`; divider `1px #6b7d8e`                         | **N**                                              |
| **`.slotacts-top .iact` (4)** | **`32×30`** icon button, `14px` glyph                                                                                                    | transparent / `#abb6c2` / `1px #abb6c2`; danger `#f0a6a3`/`1px #d9534f`; hover fills                | `gap:6px; margin-top:8px; flex-wrap`                            | **REV RD5** (was full-width block stack at bottom) |
| `.detmore` (rev #1)           | `11px`                                                                                                                                   | `#8fa0b0` (hover `#ebebeb`)                                                                         | `margin-top:8px; gap:4px`                                       | I                                                  |
| `.detbody` block (rev #1)     | rows `11px`; key `10px` uppercase `#8fa0b0` flex `0 0 88px`; value `#ebebeb`; id-copy `#5bc0de` dotted; tag pill `#4e5d6c`/`#ebebeb` r10 | top border `#16202b`                                                                                | `mt:8px; pt:8px`                                                | I                                                  |
| More-details actions ×2       | `btn-sm`                                                                                                                                 | `btn-outline-light`                                                                                 | `gap:6px; mt:8px`                                               | I                                                  |
| **`.compare` reveal (9)**     | `width:150px`, aspect `63/88` inner img                                                                                                  | `#0b1520` / — / `1px #5bc0de`; shadow `0 8px 22px rgba(0,0,0,.6)`; cap `9px #8fa0b0`, `b`→`#5bc0de` | `position:absolute; left:126px; top:0; z-index:40; padding:5px` | **N**                                              |

### D.2 D14 band + identify (items 8/9 — pills LOCKED, affordances restyled)

| Element                                                                   | Sizing                                         | Colour (bg / text / border)                                                                                                      | Spacing                           | I/N/REV                                                                                        |
| ------------------------------------------------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------- |
| `.d14` band                                                               | `12px`, wrap, `gap:8px`                        | `#2b3e50` / — / bottom `#16202b`                                                                                                 | `padding:8px 10px`                | I                                                                                              |
| `.seticon` + `.check`/`.score`                                            | `30×30` circle; check `15×15`; score `9px/800` | as inherited (`#4e5d6c`/`#7f8fa0`; check `#5cb85c`; score `#df6919`)                                                             | inherited                         | I                                                                                              |
| `.idtext`                                                                 | `12px` mono                                    | `#ebebeb`                                                                                                                        | —                                 | I                                                                                              |
| **`.statepill.confirmed`**                                                | `11px/700`                                     | — / `#a7e08a` / `#3f7a2f`; r10                                                                                                   | `padding:1px 8px`                 | **I — LOCKED**                                                                                 |
| **`.statepill.suggested`**                                                | `11px/700`                                     | — / `#ffb27d` / `#df6919`; r10                                                                                                   | `padding:1px 8px`                 | **I — LOCKED**                                                                                 |
| `.statepill.cmp` trigger (9)                                              | —                                              | (look unchanged) `cursor:zoom-in`; hover/focus or tap toggles the compare reveal                                                 | —                                 | N (behaviour only; pill look untouched)                                                        |
| **`.notthis` ✗ (8)**                                                      | `11px/600`, `padding:2px 10px`                 | `rgba(217,83,79,.12)` / `#f0b3b1` / `1px rgba(217,83,79,.55)`; **radius `10px`**; hover → solid `#d9534f`/`#fff`                 | `margin-left:auto`                | **REV** (was flat `btn-outline-danger` bar; owner answer #2 opacity-.6-on-confirmed preserved) |
| **`.idtoggle` (8)**                                                       | `12px/600`, `padding:3px 12px`                 | `rgba(223,105,25,.12)` / `#ffb27d` / `1px rgba(223,105,25,.55)`; **radius `10px`**; leading `🔍`; hover → solid `#df6919`/`#fff` | in `.idhang` `padding:0 10px 8px` | **REV** (was bland full-width `1px #6b7d8e` grey bar, post-#413)                               |
| `.idbody` / `.cons` / `.idsearch` / `.candgrid` / `.cand` / `.attrfollow` | as inherited                                   | as inherited                                                                                                                     | as inherited                      | I                                                                                              |

### D.3 Sources (item 3 — de-grey + densify; REVISES the inherited inline Sources rows)

| Element                                     | Sizing                                     | Colour (bg / text / border)                                                | Spacing                       | I/N/REV                                               |
| ------------------------------------------- | ------------------------------------------ | -------------------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------- |
| **`.src-summary`**                          | `12px/700` label; count `12px`             | **`#22303f`** / `#ebebeb`; count `#8fa0b0`, N `#5cb85c`                    | `padding:7px 10px; gap:8px`   | **REV** (was `#4e5d6b` grey band)                     |
| **`.src-pins`**                             | pinchip `11px`                             | **`#22303f`**; chip `#2b3e50`/`#ebebeb`/`rgba(0,0,0,.22)`; ★ `#ffc107`     | `gap:4px; padding:0 10px 7px` | **REV** (was grey)                                    |
| **`.src-body`**                             | —                                          | **`#22303f`**                                                              | `padding:8px 10px`            | **REV** (de-greyed)                                   |
| **`.src-body .filter`** (primary find path) | `14px`                                     | `#2b3e50` / `#ebebeb` / **`1px #abb6c2`** (emphasised)                     | `padding:7px 10px; mb:8px`    | **REV** (border brightened; is now the primary path)  |
| Bulk buttons ×3 / Save-defaults seam        | `btn-sm`                                   | `btn-outline-light` / `btn-outline-success` disabled (#353)                | `gap:6px; mb:6/8px`           | I                                                     |
| **`.src-cap`** count/cap caption            | `10px`                                     | `#8fa0b0`, N `#ebebeb`                                                     | `mb:5px`                      | **N** (states "Showing 10 of 254 — filter to narrow") |
| **`.src-list`**                             | `max-height:186px` scroll; **virtualized** | `#2b3e50` / — / `rgba(0,0,0,.22)`                                          | —                             | REV (virtualization added)                            |
| **`.src-row`**                              | **`height:34px`**                          | / — / bottom `rgba(0,0,0,.22)`                                             | `padding:2px 8px; gap:8px`    | **REV** (was ~70px screenshot / ≥38px spec)           |
| **`.tgl` source toggle**                    | **`52×31`** (`--src-toggle-h`)             | on `#df6919`/`#fff`; off `#4e5d6c`/`#8fa0b0`; `#6b7d8e` border; `10px/700` | —                             | **REV** (was `54×38`; see a11y note §G)               |
| **`.src-row .pin` ★**                       | **`30×30`**                                | pinned `#ffc107` / unpinned `#5b6b7b`; `15px`                              | —                             | **REV** (was 38×38)                                   |
| `.src-row .snm`                             | `12px` ellipsis                            | `#ebebeb`                                                                  | `flex:1`                      | REV (13→12px)                                         |

### D.4 Select Version — Sort (7), grid (1), loading (10)

| Element                                                                | Sizing                               | Colour (bg / text / border)                                                                                                                                                    | Spacing                        | I/N/REV                                                  |
| ---------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------ | -------------------------------------------------------- |
| `.svtitle` / `.svhead` / `.filtersbtn`                                 | as inherited                         | as inherited                                                                                                                                                                   | as inherited                   | I                                                        |
| **`.sortsel` (7)**                                                     | `12px`, `max-width:172px`            | `#22303f` / `#ebebeb` / `1px #4e5d6c`; r0                                                                                                                                      | `padding:3px 6px`              | REV RD2 (option list is data-driven; see §F)             |
| `.vgrid` / `.vtile` (`72/88/112`) / corner tags / REQ / confirm ribbon | as inherited                         | as inherited                                                                                                                                                                   | `gap:6px`                      | I                                                        |
| **`.vtile.ghost` (1)**                                                 | `72px`, aspect `63/88`               | **thumbnail** stripe + `.gdim rgba(11,21,32,.62)` overlay; `.gplus` `16px/800 #fff` text-shadow; `.gcap` `7px` `rgba(0,0,0,.6)`/`#cdd6df`; outline `1px rgba(235,235,235,.15)` | grid gap                       | **REV** (was transparent `1px dashed #abb6c2` empty box) |
| **`.vloading` (10)**                                                   | min-height `140px`, gap `10px`       | `#8fa0b0` `12px`                                                                                                                                                               | replaces `.vgrid` when loading | **N**                                                    |
| **`.spinner-border` (10)**                                             | **`2.6em` ×`2.6em`**, border `.25em` | `#df6919` ring, right-transparent; `spin .75s linear infinite`                                                                                                                 | —                              | **N (reuse `Spinner.tsx`)**                              |

### D.5 Filters panel (item 2 — residual absorbed; otherwise inherited)

Every filter fieldset (`.fset` legend `10px` uppercase `#8fa0b0`; DPI/Size `.frange` track `4px`
`#3a4653`, fill `#df6919`, knob `12px #abb6c2`/`#fff`; `.ftree` `#2b3e50`/`1px #4e5d6c`; `.swtrack`
NSFW `34×18` off `#3a4653`/on `#df6919`), the funnel `.seg`/`.tchip`/`.tchip.suggested`(dashed +`⌇`)/
`.implicit-note`, and the phone-inline vs desktop/tablet-float behaviour (RD4) are all **I** (inherited
verbatim). Item 2's contribution here is **coverage, not new tokens**: these controls must inherit
the dark-rail theme rather than fall through to bare browser widgets (the #413 residual). Reaffirmed
binding; no value changes.

### D.6 App chrome contrast (item 2)

| Element                           | Sizing                     | Colour (bg / text / border)                                                                             | Spacing    | I/N/REV                                                           |
| --------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------- |
| **`.abtn`** editor toolbar action | `13px`, `padding:5px 12px` | `#22303f` / `#ebebeb` / `1px #46586a` (hover border `#abb6c2`)                                          | `gap:10px` | **N** (fixes near-invisible grey-on-dark "Add"/"Add card" ghosts) |
| **`.abtn.primary`**               | `13px`                     | transparent / `#8fe08f` / `1px #5cb85c`                                                                 | —          | **N**                                                             |
| Rail/right-rail buttons page-wide | `btn-sm`                   | outline variants carry text at ≥ `--light #abb6c2` on dark; solid `--primary` fills for primary actions | —          | N (contrast floor, no structural change)                          |

### D.7 Control stack (item 4 revision)

| Element                                                  | Sizing                  | Colour                                                                  | Spacing                        | I/N/REV                                         |
| -------------------------------------------------------- | ----------------------- | ----------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------- |
| `.cstack` Print Options group + `.bleedsel` + `.cs-hint` | as inherited            | as inherited                                                            | `padding:8px 10px`             | I                                               |
| Slot-Actions group in `.cstack`                          | —                       | —                                                                       | —                              | **REMOVED (REV RD5 → moved to rail head, D.1)** |
| Report button `.reportbtn` → `.reportpanel` chips        | `btn-sm` / `11px` chips | `btn-outline-danger` / `#22303f`/`#ebebeb`/`1px #4e5d6c` (hover danger) | `cs-foot` top border `#16202b` | I                                               |

### D.8 Sheet cell (the ⋯ cue + E24 flip + item-11 hidden state)

| Element                           | Sizing                        | Colour (bg / text / border)                                                                                     | Spacing                                                | I/N/REV                                                                                        |
| --------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| **`.slot-cue` ⋯ (cue)**           | **`26×26`**, glyph **`17px`** | **`rgba(11,21,32,.92)`** / `#fff` / **`1.5px #abb6c2`**; r4; shadow `0 1px 3px rgba(0,0,0,.5)`; hover `#df6919` | `bottom:3px; right:3px; z-index:3`                     | **REV** (`PagePreview` `SlotMenuCue` was `20×20`, `rgba(22,32,43,.85)`, `13px`, `1px #7f8fa0`) |
| **cue render gate**               | —                             | rendered ONLY when the slot holds a card **and** a context menu is wired                                        | —                                                      | **REV** (was gated on `onSlotContextMenu != null` alone)                                       |
| **`.slot-flip` ⟲ (E24, item 6)**  | `26×26`, glyph `14px`         | `rgba(11,21,32,.92)` / `#fff` / `1.5px #abb6c2`; r4; hover `#5bc0de`/`#062430`                                  | `top:3px; right:3px; z-index:3`; gated to filled cells | **N** (ships the reserved `PagePreview.tsx:618` corner)                                        |
| **`.cell.ext` hidden state (11)** | fills cell                    | `#141f2b` / `#8fa0b0` `8px` / `1px dashed #46586a`; lock `🔒 15px`                                              | shown when `data-shared=hidden`; cue/flip suppressed   | **N**                                                                                          |
| **`.extbanner` (11)**             | `11px`                        | `rgba(11,21,32,.95)` / `#ebebeb` / `1px #5bc0de`; link `#5bc0de`                                                | `position:absolute; top:10px; centred; z-index:20`     | **N**                                                                                          |

### D.9 Consent toast (item 11)

| Element                                                                    | Sizing                                     | Colour (bg / text / border)                                                                     | Spacing                                                                   | I/N/REV |
| -------------------------------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------- |
| **`.consent`** (react-bootstrap `Alert`, `role=alertdialog`, `bottom-end`) | `width:300px`, `max-width:calc(100%-28px)` | `#0b1520` / `#ebebeb` / `1px #5bc0de` + left `4px #5bc0de`; shadow `0 10px 30px rgba(0,0,0,.6)` | `position:fixed; right:14px; bottom:14px; z-index:120; padding:12px 14px` | **N**   |
| `.consent .ct` title / `.cx` close                                         | `13px/700` / `15px` `#8fa0b0`              | —                                                                                               | `mb:6px`                                                                  | N       |
| `.consent .cm` disclaimer                                                  | `11px`                                     | `#abb6c2`; risk phrase `#ffc107`                                                                | `mb:10px; line-height:1.45`                                               | N       |
| `.consent .cbtns`                                                          | `btn-sm`                                   | Show → `btn-outline-info`; Keep hidden → `btn-outline-light`                                    | `gap:8px`                                                                 | N       |

---

## E. Owner decisions logged this round (EP = editor-polish; all PROPOSED, pending sign-off)

- **EP1 (item 1).** The ghost tile renders the first hidden copy's thumbnail, dimmed
  (`rgba(11,21,32,.62)`), with a centred `+N` and a "more copies" caption. What it compresses:
  additional copies of the **same identified printing** (not distinct printings).
- **EP2 (item 2).** A page-wide button-contrast floor: outline buttons carry text at ≥ `--light`
  (`#abb6c2`) on every dark surface; the editor toolbar's near-invisible grey ghosts get an explicit
  `1px #46586a` border + `#ebebeb` text (`.abtn`). The #413 unstyled residual — the Filters float's
  DPI/Size/Language/Tags/NSFW controls — is absorbed: all inherit the dark-rail theme (no bare
  browser widgets). No token in the funnel/filter body changes value; this is coverage.
- **EP3 (item 3, REVISES the inherited Sources rows).** The grey `#4E5D6B` header/pins/body band is
  killed → dark `#22303f` throughout. Rows densify to `34px` (toggle `52×31`, pin `30×30`, name
  `12px`). The filter input becomes the primary find path (brighter `1px #abb6c2` border) and the
  list is **virtualized** with a "Showing N of 254 — filter to narrow" cap caption.
- **EP4 (item 4, REVISES RD5).** Slot Actions (Change / Duplicate / Delete) relocate from the
  full-width bottom stack to a **compact icon row** (`32×30` buttons) in the rail head, beside the
  subject image. The bottom control stack keeps only Print Options + Report. No full-width slot-action
  buttons anywhere.
- **EP5 (item 5, REVISES RD8).** The subject image grows from `66px` to **`116px`** wide (aspect
  `63/88`), anchoring the relocated actions row and the Front/Back toggle. Still a preview, not a
  second full render — Select Version stays the art surface. Verified it does not starve the 390px
  grid (phone reachability holds, §H).
- **EP6 (item 6).** A per-slot **Front/Back** segmented toggle (`ToggleButtonGroup`, info-blue active)
  sits beside the subject image; flipping it shows the back-face art in the subject preview. The same
  action ships at the sheet cell's reserved E24 top-right corner (`PagePreview.tsx:618`) as a `⟲`
  flip button, render-gated to filled cells.
- **EP7 (item 7, REVISES RD2/O5).** Sort is replaced by data-driven orderings: **Confirmation status ·
  Community vote weight · Resolution (DPI) high→low · File size low→high · Pinned sources first · Name
  (A→Z) · Date added**. Five are client-side over already-carried fields today; "Community vote
  weight" needs a backend numeric that does not exist yet (§F annex, Q1).
- **EP8 (item 8, REVISES the post-#413 look).** The wrong-printing affordance is restyled from the
  bland full-width grey bar to the **pre-#413 DeckbuilderConfirmAffordance pill idiom**: a tinted,
  rounded (`radius:10px`), higher-contrast control (`.idtoggle` primary-tinted; `.notthis`
  danger-tinted). Behaviour unchanged (`.idtoggle` opens the picker; `.notthis` casts the `isNoMatch`
  vote and stays de-emphasised at `opacity:.6` on a confirmed printing per owner answer #2). The D14
  Confirmed/`% confident` pills are **not** touched.
- **EP9 (item 9).** The Scryfall compare reveal moves its trigger from the set-icon to the D14
  Confirmed/`% confident` **pill** (owner ask), and its anchor to **beside the subject image**. Touch
  equivalent: the pill is a `tap-toggle` under `(pointer:coarse)` (no hover). Display-only, nothing
  stored (governing premise + #271). **No backend seam is required** — the URL is already derived
  client-side (§F annex).
- **EP10 (item 10).** The unified page's loading bar is replaced with the site's canonical round
  spinner, `components/Spinner.tsx` (`.spinner-border`), tinted `--primary`, in the Select Version
  loading state.
- **EP11 (item 11).** The deferred-half foreign-order consent UI ships as: a bottom-right
  `ConsentToast` (`useConsentToast`, `Alert role=alertdialog`) shown to a recipient of a shared deck
  containing orphan Drive IDs — **deny-by-default** (dismiss/Escape = decline, per the shipped
  contract); a denied resting state where orphan cells show a `🔒 External image hidden` placeholder
  with cue/flip suppressed; and a deck-level "N external images hidden — Review" banner (the
  reversible "Show/Hide" the deferred spec calls for). Owner's self-import/own-decks surfaces are
  unaffected (already allowed by default). Backend half tracked by issue #414. See Q2.
- **EPcue (cue).** The `⋯` `SlotMenuCue` grows to `26×26`, glyph `17px`, higher-contrast
  (`rgba(11,21,32,.92)` bg, `1.5px #abb6c2` border, `#fff` glyph, drop-shadow) so it reads over card
  art, and its render gate tightens from "context menu wired" to "**slot holds a card** AND context
  menu wired" (empty slots show no cue).

Honoured LOCKED decisions (unchanged): RD7 (mismatch-only badge), D14 + #271 + owner answer #2 (pill
treatment, ✗-stays-de-emphasised), RD4 (tier-conditional Filters float), RD6 (metadata in More
details only), the ratified implicit-vote chip mechanics, §F one continuous grid.

---

## F. FEATURES ACCOUNTED FOR — the eleven items + cue

| #   | Item                                | Accounted where                                      | State demoed in mockup                                         |
| --- | ----------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------- |
| 1   | Ghost tile thumbnail + `+N`         | §D.4 `.vtile.ghost`; EP1                             | always-on ("+9 · more copies")                                 |
| 2   | Whole-page contrast + #413 residual | §D.5, §D.6; EP2                                      | app-chrome `.abtn`; themed filter controls (tablet float shot) |
| 3   | Sources de-grey + densify           | §D.3; EP3                                            | Sources block (all frames)                                     |
| 4   | Slot Actions → top                  | §D.1 `.slotacts-top`, §D.7 (removed) ; EP4           | rail head icon row                                             |
| 5   | Subject image larger                | §D.1 `.subject`; EP5                                 | rail head 116px                                                |
| 6   | Front/Back toggle (E24)             | §D.1 `.fbtoggle`, §D.8 `.slot-flip`; EP6             | `Face` demo toggle (front/back) + sheet `⟲`                    |
| 7   | Data-driven Sort                    | §D.4 `.sortsel`; EP7                                 | Sort dropdown option list                                      |
| 8   | Wrong-printing affordance           | §D.2 `.idtoggle`/`.notthis`; EP8                     | D14 band + identify pill                                       |
| 9   | Scryfall compare-on-hover/-tap      | §D.1 `.compare`, §D.2 `.statepill.cmp`; EP9          | `Compare` demo toggle (beside subject)                         |
| 10  | Round spinner                       | §D.4 `.vloading`/`.spinner-border`; EP10             | `Grid` demo toggle (loading)                                   |
| 11  | Foreign-order consent/disclaimer    | §D.8 `.cell.ext`/`.extbanner`, §D.9 `.consent`; EP11 | `Shared deck` demo toggle (owner/consent/denied)               |
| cue | ⋯ cue bigger/contrast + gated       | §D.8 `.slot-cue`; EPcue                              | sheet cells (filled show cue, empty don't)                     |

### Annex — backend fields (item 7 sort, item 9 compare): what the response ALREADY carries

Read from `schema_types.ts` `Card`/`CardDocument` and `ConfidenceElement.tsx`/`scryfallReference.ts`.

**Item 7 sort — already carried (client-side comparator, no backend work):**

- `dpi: number` → "Resolution (DPI) high→low" ✓
- `size: number` → "File size low→high" ✓
- `printingTagStatus: PrintingTagStatus` + `canonicalCard` / `suggestedCanonicalCard` →
  "Confirmation status" (resolved → suggested → unknown) ✓
- `sourceName`/`sourceId`/`priority: number` → "Pinned sources first" (joined with the rail's own
  pinned-sources set, already client-side) ✓
- `name`, `dateCreated`, `dateModified` → Name / Date added ✓ (the current `SortByOptions`)

**Item 7 sort — NOT carried (needs a backend seam):**

- A numeric **community vote weight / net polarity per card**. The response carries a _status_ enum
  (`printingTagStatus`) and the resolved/suggested printing, but no per-card numeric weight.
  `suggestedCanonicalCardConfidence` exists as a **currently-always-`undefined` seam field** — the
  same one D14's "N% confident" reads. "Community vote weight" as a sort ordering depends on that (or
  a sibling) numeric landing. → **Q1.**

**Item 9 compare — DEVIATION from the dispatch's annex (reported honestly):**

- The dispatch says "frontend needs the canonical printing's Scryfall image URI in the payload (small
  backend seam)." **This is not accurate against the shipped code.** `buildScryfallReferenceImageUrl(expansionCode, collectorNumber)`
  (`features/display/scryfallReference.ts`) already derives the image URL client-side via Scryfall's
  documented `?format=image` redirect — no Scryfall UUID lookup, no payload field, no backend change.
  `ConfidenceElement.tsx` already uses it for the set-icon popover today. **Item 9 is pure frontend**:
  move the trigger to the pill, anchor the reveal beside the subject, add the touch tap-toggle. The
  payload already carries `canonicalCard`/`suggestedCanonicalCard` (`expansionCode`+`collectorNumber`),
  which is all the URL builder needs. (Posture-clean either way: transient display, nothing stored.)

---

## G. Accessibility

Cue/flip are focusable `button`s with `aria-label` (`26×26` ≥ the practical touch floor).
`ToggleButtonGroup` Front/Back carries `aria-pressed`; the D14 pill compare-trigger is a
`role=button tabindex=0` with an `aria-label` naming the compare action (colour never the only
signal). The consent toast is `role="alertdialog"` with focus moved to "Show images" on appear
(matches the shipped `ConsentToast`). The spinner keeps `role="status"` + visually-hidden "Loading…".
Sort is a labelled `Form.Select`. Filter fieldsets keep text legends; funnel chips keep `+/−/·` glyph
state; NSFW stays `role="switch"`.

**Flagged a11y tension (owner-ruled, item 3/EP3):** the densified source **toggle drops to `31px`**
and the pin to `30px`, below the inherited §G `≥38px` (`ToggleButtonHeight`) guideline. The owner
explicitly ruled "31px-toggle class or plain switch," so this is binding, not an open question — but
it is a real regression against that guideline and is recorded here. Mitigation carried in the
mockup: the **row itself is `34px` and the whole row is the toggle's hit surface**, so the effective
tap target exceeds the visible toggle. If the owner later wants the 38px floor back, revert
`--src-toggle-h` to `38px` and row height to `≥40px` (costs the vertical density EP3 buys).

---

## H. Verification

Playwright (`shot.js`, chromium), screenshots inspected at **390px (native phone)**, **900px (forced
tablet)**, **1400px (desktop + forced-phone-on-wide)**. **Zero page errors across all frames.**

- `v-1400-auto.png` — three-region desktop: big subject + Front/Back + compact slot-action icons +
  restyled wrong-printing pills + de-greyed dense Sources + data-driven Sort + ghost "+9" tile;
  sheet cells carry `⟲` flip + `⋯` cue, empty cell 7 carries neither.
- `v-1400-railhead.png` / `-details.png` / `-back.png` / `-empty.png` — rail-head states: lean head,
  metadata disclosure, back-face subject + "Slot 3 · Back", dashed empty state (mismatch suppressed).
- `v-1400-compare.png` — item 9: Scryfall reference revealed **beside** the 116px subject image.
- `v-1400-d14-confirmed.png` — LOCKED D14 confirmed: green `✓` + "Confirmed" pill + `✗` at opacity .6.
- `v-1400-loading.png` — item 10: round `.spinner-border` (orange) replacing the bar.
- `v-1400-consent.png` / `v-1400-shared-hidden.png` — item 11: bottom-right consent alertdialog;
  denied resting state (locked cells + deck "N hidden — Review" banner).
- `v-1400-sheet-cue.png` — EPcue: enlarged high-contrast `⋯`/`⟲` on filled cells; empty cell gated off.
- `v-1400-rail-allopen.png` / `v-1400-filters-float.png` — full rail with filters+identify+report
  open; RD4 desktop Filters float centred with backdrop.
- `v-390-auto-full.png` / `v-390-all-open.png` / `v-390-rail-bottom.png` — native phone bottom-sheet:
  the whole rail (head → D14 → identify → artist → Sources → Select Version → control stack) reachable
  by scrolling; the 116px subject does not starve the grid.
- `v-390-compare.png` — item 9 touch reveal (tap-toggle) at 390px.
- `v-390-consent.png` — phone consent (real `ConsentToast` is `position:fixed bottom-end`; in the tall
  native auto frame it anchors at frame-bottom, best seen in the desktop shot; behaviour is identical).
- `v-900-tablet.png` / `v-900-tablet-filters.png` — tablet start-drawer + Filters floated to viewport
  centre with the fully-themed DPI/Size/Language/Tags/NSFW controls (item 2 residual absorbed).
- `v-1400-forced-phone.png` / `v-phone-bottom-stack.png` — forced-phone frame at 1400px, scrolled to
  the bottom control stack (Print Options + Report), proving phone reachability to the very end.

---

## I. Open questions — ONLY the two that are genuinely the owner's

Everything in the dispatch is ruled; these two are real forks the dispatch does not settle:

- **Q1 (item 7).** "Community vote weight" as a sort ordering needs a per-card numeric weight the
  response does not carry today (the `suggestedCanonicalCardConfidence` seam is always `undefined`
  until a backend PR populates it). **Show the option now, disabled/greyed until the seam lands, or
  omit it until then?** The other five orderings are client-side-ready and ship immediately either
  way. (Recommendation: ship the five now; add "vote weight" when the numeric exists.)
- **Q2 (item 11).** The shipped `useConsentToast` stores one accept/decline **per key, in
  sessionStorage** (survives reloads, not "clear site data"; dismiss = terminal decline — no
  "ask again" state). The deferred-half spec asks for a **per-deck recipient opt-in** with a
  **reversible Hide**. Two sub-questions the base mechanism doesn't answer natively: **(a)** scope the
  consent key per shared-deck id (so different shared decks ask independently) — yes/no? **(b)** the
  reversible "Show/Hide after an initial decline" is beyond the base toast's `Promise<boolean>`
  contract (the consent-toast doc itself flags this needs a small mechanism extension, not a variant)
  — is the deck-level banner's "Review/Show" toggle (mockup's approach) the intended reversibility, or
  do you want the toast itself re-openable? (Recommendation: per-deck key (a=yes); reversibility lives
  in the persistent deck banner, leaving the base toast's contract untouched.)

## OWNER AMENDMENTS — 2026-07-24 post-review (BINDING, supersede conflicting rows above)

1. "More details" disclosure RELOCATES: it renders directly UNDER the D14 confidence band
   (the printing-accuracy banner: confirmed/%confidence pills + canonical printing id), not
   in the rail-head block. Rail-head keeps: subject image (116px), identity text, actions
   icon row, Front/Back toggle. Ruled without a design re-pass; implementer places it with
   the band's existing spacing rhythm (§D.2 divider tokens apply at the new boundary).
2. §I Q1 RULED (recommended option): ship the five client-side sort orderings now
   (Confirmation status, DPI, File size, Pinned-first, Name/Date); "Community vote weight"
   waits for the numeric seam — render nothing for it (no disabled placeholder).
3. §I Q2 RULED (recommended option): consent key scoped per shared-deck id; reversibility
   lives in the deck-level "N external images hidden — Review" banner; the base
   useConsentToast Promise<boolean> contract stays untouched.
