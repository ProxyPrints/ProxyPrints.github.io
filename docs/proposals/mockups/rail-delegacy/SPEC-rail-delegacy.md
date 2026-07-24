# /editor LEFT RAIL — delegacy round (nine grey drop-downs folded into designed elements)

> Durable copy, recovered 2026-07-24 from session tmp storage (same
> durability convention as [`../../../reference/funnel-spec.md`](../../../reference/funnel-spec.md)) —
> this is the owner-approved BINDING spec that committed code comments
> across open PR branches (e.g. `DisplayPage.tsx`, `RequestedPrintingBadge.tsx`,
> `SelectVersionResults.tsx`) cite by filename as their authority. Content below
> is verbatim from the 2026-07-24 original, including its OWNER AMENDMENTS
> section where present.

Companion to `rail-delegacy-mockup.html` (same directory). Owner reviews the mockup in a
browser BEFORE any implementation.

**Premise (owner-approved 2026-07-24):** every grey legacy `AutofillCollapse` drop-down section
is REMOVED from the /editor left rail. Its contents fold into designed elements (or are SCRAPPED)
per the ruled disposition list. This spec is the layout + binding tokens for what replaces them.

**Inherited, not renegotiable:** `SPEC-display-left-rail-CORRECTED.md` §0 (the #302 palette) and
§2 (density: blocks butt together, one 1px `#16202b` hairline between, each block's own compact
padding carries the rhythm). Every token from that round is reproduced verbatim below and tagged
`I`. The D14 confidence element and its Y/N decisions (#271 + owner answer #2), the Sources inline
design (owner answer #3), the continuous Select-Version grid (§F), and the `Offcanvas responsive`
shell (§B) are all inherited unchanged. This round only removes the grey accordions and rehomes
their contents.

Every value below is **BINDING** (owner standing rule, 2026-07-23). `I` = inherited (reproduce
verbatim); `N` = introduced/normalized this round (flagged, and `.propose`-labelled in the mockup
where it changes the current look).

---

## A. Breakpoint behaviour (inherited from corrected-bundle §B — UNCHANGED)

The left rail is ONE node: `Offcanvas responsive="lg"`. Content composition is IDENTICAL at every
breakpoint (D2) — one `leftRail()` builder in the mockup proves it can't drift. Only the chrome
differs.

| Tier    | Width      | Bootstrap | Left-rail chrome                                                  |
| ------- | ---------- | --------- | ----------------------------------------------------------------- |
| Phone   | `<768`     | xs+sm     | `placement="bottom"` 72vh bottom-sheet; rounded top + drag handle |
| Tablet  | `768–991`  | md        | `placement="start"` drawer; "Card details" edge handle when idle  |
| Laptop  | `992–1199` | lg        | Inline sticky **380px** column                                    |
| Desktop | `≥1200`    | xl        | Inline sticky **380px** column                                    |

Inline width `380px`; `overflow-y:auto` own scroll container; sticky `top:0`. **Phone
reachability (hard requirement, verified):** the whole rail — rail-head → D14 → identify panel →
artist → Sources → Select Version + Filters panel → bottom control stack (bleed / slot actions /
Report) — lives in the one `overflow-y:auto` container and is reachable by scrolling the 72vh
sheet. Verified in the forced-phone frame scrolled to its end (`v-phone-bottom-stack.png`) and the
native 390px frame. **Implementation note (fidelity):** inside the drawer the rail must
`flex:1 1 auto; min-height:0` so `.lscroll` owns the scroll — the inline `380px` is a WIDTH, and
if it leaks into the column-flow drawer as a height the sheet can't reach its bottom (caught and
fixed in the mockup; carry the same rule into the real Offcanvas body).

---

## B. Rail composition order (this round — revised 2026-07-24)

```
┌ rail-head ─────────── SUBJECT-CARD IMAGE (rev #3) + LEAN identity (Slot · name) + "More details"
│                       disclosure holding the WHOLE Card-Details metadata block (rev #1). No
│                       printing identifier here (rev #2 — it lives once, in D14).
├ D14 confidence band ─ LOCKED (#271 + owner #2); owns the ONE canonical printing id "2X2 · 117" (rev #2)
├ identify panel ────── Printing-Tags voting surface HANGS OFF D14 (item 6), opened on demand
├ artist line ───────── ArtistSection (unchanged)
├ Sources ───────────── inline AutofillCollapse (inherited, owner answer #3) — NOT one of the nine
├ Select Version ────── header row [N versions · Sort ▾ · Filters ▾] (item 2) → Filters panel
│                       (item 3 power set + item 5 UNIFIED into the one funnel chip surface, O1;
│                       phone=in-rail expand, desktop/tablet=centred float, O3) → continuous grid (§F)
└ control stack ─────── Print Options + Slot Actions + Report (item 7), one designed stack
```

NO grey `AutofillCollapse` anywhere in the rail. `RailSection`/`AutofillCollapse` mounts for the
demoted zone (`DisplayPage.tsx` ~L1171-1264) are deleted; `GridSelectorFilters`' `AutofillCollapse`
sections (Jump/Sort/Filter) are deleted from the rail path.

---

## C. react-bootstrap primitive mapping (no new dependencies)

| Element (this round)                      | Primitive(s)                                                                                                                                                      | Source component reused                                                                            |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **Subject-card image** (rev #3)           | `Card.Img`/`<img>` of the slot's selected art at a preview footprint; dashed placeholder empty state                                                              | reuses the same thumbnail URL the selected `.vtile`/`CardImage` renders — NOT a second full render |
| "More details" disclosure (rev #1)        | `Button` (link-style) toggling a `Collapse`; body = the FULL `CardMetaTable` (`AutofillTable`) + `ClickToCopy` + `AddCardToFavorites` + Download `Button`         | `CardMetaTable` + `CardDownloadFavorite` (whole block)                                             |
| Requested≠resolved mismatch flag (rev #2) | `RequestedPrintingBadge`, rendered ONLY when the query's requested printing differs from the resolved/suggested printing                                          | `RequestedPrintingBadge` (additive `showOnlyOnMismatch`-style prop)                                |
| Sort dropdown (item 2)                    | `Form.Select size="sm"` (6 `SortByOptions`)                                                                                                                       | replaces `NullableSortByFilter` tree-select (see O5)                                               |
| Filters toggle (item 2)                   | `Button variant="outline-light" size="sm"` + chevron, `aria-expanded`                                                                                             | new toggle                                                                                         |
| Filters panel — phone (O3)                | in-rail `Collapse` wrapping `fieldset`s (in place)                                                                                                                | new container                                                                                      |
| Filters panel — desktop/tablet (O3)       | `Overlay`/floating panel centred in the viewport + backdrop; same `fieldset` body                                                                                 | new container (shared body node)                                                                   |
| Border / Frame filter chips (O1)          | `ToggleButtonGroup type="radio"` — positive-or-off (`FUNNEL_AXES`), re-tap clears to "any"                                                                        | funnel chips (`attributeChips.ts`)                                                                 |
| Treatment filter chips (O1)               | `ToggleButton`/`Button` tri-state (`TreatmentChipRow`/`nextChipState`)                                                                                            | funnel chips (`attributeChips.ts`)                                                                 |
| SUGGESTED chip state (O1)                 | dashed border + trailing `⌇` on chips carried only via `suggestedFilterTagNames`                                                                                  | ratified funnel F3 (`chipMembershipState`)                                                         |
| Implicit-vote awareness line (O1)         | plain muted text row under the chips                                                                                                                              | ratified funnel column element                                                                     |
| DPI / Size fieldsets (item 3)             | `DPIFilter` / `SizeFilter` (range sliders)                                                                                                                        | unchanged                                                                                          |
| Languages / Tags fieldsets (item 3)       | `LanguageFilter` / `TagFilter` (tree-selects)                                                                                                                     | unchanged                                                                                          |
| Mature-content (NSFW) fieldset (item 3)   | `MatureContentFilter` (`Form.Check` switch)                                                                                                                       | unchanged                                                                                          |
| Identify-printing panel (item 6)          | `Button` toggle → `Collapse` → `PrintingTagPicker` (`Form.Control`+`Row/Col` `Button` thumbnails + `OverlayTrigger`/`Popover`) + `AttributeVotingPanel` follow-up | `PrintingTagsBlock`                                                                                |
| Print-options select (item 7)             | `Form.Select size="sm"` (Auto / Force bleed / Force trimmed)                                                                                                      | `PrintOptionsSection`                                                                              |
| Slot-action buttons (item 7)              | stacked `Button size="sm" variant="outline-light\|outline-danger"`                                                                                                | `SlotActionsSection`                                                                               |
| Report button + panel (item 7)            | one `Button size="sm" variant="outline-danger"` → `ReportCardPanel` chip grid                                                                                     | `ReportCardPanel`                                                                                  |

Shared components gain only additive, optional, behaviour-preserving props (e.g. `RequestedPrintingBadge`
render-only-on-mismatch; `GridSelectorFilters` already carries `hiddenSections`; the funnel chip
components already own the SUGGESTED-state + implicit-vote wiring). No display-only fork of any
/editor component, and — per O1 — no new voting mechanic: the funnel chips behave exactly as the
ratified implicit mechanics, `AttributeVotingPanel` stays the one explicit surface.

---

## D. BINDING token table — every rail element (sizing · colouring · spacing)

Colours are the §0 #302 tokens. `I` = inherited (reproduce verbatim); `N` = introduced this round.

### D.0 Palette tokens (all inherited — `styles.scss` #302 + Superhero)

| Token            | Value              | Token              | Value                 |
| ---------------- | ------------------ | ------------------ | --------------------- |
| body bg          | `#0f2537`          | primary (hover)    | `#df6919` (`#be5915`) |
| panel/card/2ndry | `#4e5d6c`          | success            | `#5cb85c`             |
| card-header      | `#4e5d6b` (inline) | danger             | `#d9534f`             |
| raised/input bg  | `#22303f`          | warning            | `#ffc107`             |
| D14 band         | `#2b3e50`          | info               | `#5bc0de`             |
| text             | `#ebebeb`          | input border       | `#4e5d6c`             |
| muted            | `#8fa0b0`          | divider (hairline) | `#16202b`             |
| light            | `#abb6c2`          | radius / pill      | `0` / `10px`          |

### D.1 Inherited elements (verbatim from corrected-bundle §D.1 — reproduce, do not redraw)

| Element                       | Sizing                                      | Colour (bg / text / border)                                                          | Spacing                          | I/N                  |
| ----------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------- | -------------------- |
| `.rail-head`                  | —                                           | `#22303f` / `#ebebeb` / bottom `#16202b`                                             | `padding:8px 10px`               | I                    |
| `.rail-head .slot`            | `14px/700`; face `11px` uppercase `#8fa0b0` | text `#ebebeb`                                                                       | face `margin-left:6px`           | I                    |
| `.rail-head .name`            | `15px`                                      | `#ebebeb`                                                                            | `margin-top:1px`                 | I                    |
| `RequestedPrintingBadge`      | `12px` mono                                 | `#4e5d6c`/`#fff`; degraded `#ffc107`/`#111`                                          | `padding:2px 8px; mt:5px`        | I                    |
| `.d14` band                   | `12px`, wrap, `gap:8px`                     | `#2b3e50` / — / bottom `#16202b`                                                     | `padding:8px 10px`               | I                    |
| `.d14 .seticon`               | `30×30` circle                              | `#4e5d6c` / — / `#7f8fa0`; `50%`                                                     | `flex:0 0 30px`                  | I                    |
| `.seticon .check` (confirmed) | `15×15` circle                              | `#5cb85c` / `#fff` / `2px #2b3e50`                                                   | `right/bottom:-3px`              | I                    |
| `.seticon .score` (suggested) | `9px/800` tabular                           | `#df6919` / `#fff` / `2px #2b3e50`; radius `10px`                                    | `right/bottom:-7px; pad 1px 4px` | I                    |
| `.d14 .idtext`                | `12px` mono                                 | `#ebebeb`                                                                            | —                                | I                    |
| `.statepill.confirmed`        | `11px/700`                                  | — / `#a7e08a` / `#3f7a2f`; radius `10px`                                             | `padding:1px 8px`                | I                    |
| `.statepill.suggested`        | `11px/700`                                  | — / `#ffb27d` / `#df6919`; radius `10px`                                             | `padding:1px 8px`                | I                    |
| `.d14 .notthis` (`✗`)         | `btn-sm`                                    | `btn-outline-danger`; confirmed → `opacity:.6`                                       | `margin-left:auto`               | I                    |
| `.artist-line`                | `13px`                                      | `#22303f` / `#ebebeb` / bottom `#16202b`                                             | `padding:8px 10px`               | I                    |
| Artist support button         | `btn-sm`                                    | `btn-outline-primary` (`#df6919`) + `↗`                                              | `.by margin-bottom:6px`          | I                    |
| Sources header                | `12px/700` label                            | `#4e5d6b` / `#ebebeb`; count N `#5cb85c`                                             | `padding:7px 10px; gap:8px`      | I                    |
| Sources pinned chip strip     | `11px`                                      | chip `#22303f`/`#ebebeb`/`rgba(0,0,0,.22)`; ★ `#ffc107`                              | `gap:4px; pad 0 10px 7px`        | I                    |
| Sources filter input          | `14px`                                      | `#22303f` / `#ebebeb` / `#4e5d6c`; radius `0`                                        | `padding:6px 10px; mb:8px`       | I                    |
| Sources bulk buttons ×3       | `btn-sm`                                    | `btn-outline-light` (`#abb6c2`)                                                      | `gap:6px; mb:6px`                | I                    |
| Sources "Save defaults" seam  | `btn-sm block` disabled                     | `btn-outline-success` (`#5cb85c`); `title` #353                                      | `mb:8px`                         | I                    |
| Sources list container        | `max-height:150px` scroll                   | `#22303f` / — / `rgba(0,0,0,.22)`                                                    | —                                | I (height N)\*       |
| Source row                    | row ≥38px                                   | / — / bottom `rgba(0,0,0,.22)`                                                       | `padding:8px; gap:8px`           | I                    |
| Source toggle                 | **`54×38`**                                 | on `#df6919`/`#fff`; off `#4e5d6c`/`#8fa0b0`; `#6b7d8e` border                       | —                                | I                    |
| Source pin ★                  | **`38×38`** hit                             | pinned `#ffc107` / unpinned `#5b6b7b`                                                | `min 38px`                       | I                    |
| `.select-version-heading`     | `14px/600`                                  | `#ebebeb`                                                                            | `margin:0; padding:8px 0 4px`    | I                    |
| Border/Frame filter segments  | `11px`                                      | seg `#22303f`/`#ebebeb`; active `#df6919`/`#fff`; `#4e5d6c` border                   | `padding:3px 8px`                | I                    |
| Treatment tri-state chip      | `11px`                                      | neutral `#6b7d8e`; inc `#5cb85c`/`.22`; exc `#d9534f`/`.22`/strike                   | `padding:2px 7px; gap:3px`       | I                    |
| Result grid `.vgrid`          | `flex-wrap`                                 | —                                                                                    | `gap:6px`                        | I                    |
| Tile `.vtile`                 | **`72/88/112`px**                           | outline `rgba(235,235,235,.15)`; sel `2px #df6919`                                   | —                                | I                    |
| Tile REQ / ✓ / Alt / ? tags   | `8px`/`7px/800`                             | `#df6919` / `rgba(92,184,92,.92)` / `rgba(91,192,222,.92)` / `rgba(120,135,150,.92)` | corners                          | I                    |
| Tile confirm ribbon (§F-a)    | `16px` triangle                             | `#ffc107` / `#111` `?`                                                               | top-right                        | I                    |
| Ghost "+N" tile               | `72px` dashed                               | transparent / `#abb6c2` / `1px dashed #abb6c2`                                       | grid gap                         | I                    |
| `.btn-sm` (all)               | **`14px / 4px 8px`**, radius 0              | per variant (§0)                                                                     | —                                | I (was N last round) |

\*Sources list `max-height` trimmed `190px→150px` this round to buy vertical room for the folded
content; a fidelity-relevant delta, flagged. Revert to `190px` if the owner prefers the taller list.

### D.2 Introduced elements (new this round — need knowing sign-off)

| Element                                                         | Sizing                                                                          | Colour (bg / text / border)                                                                                                                           | Spacing                                                               | I/N                         |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | --------------------------- |
| **rail-head row** `.rhead-row` (rev)                            | —                                                                               | inside `.rail-head` `#22303f`                                                                                                                         | `gap:10px; align items flex-start`                                    | N                           |
| **Subject-card image** `.subject` (rev #3)                      | **`66px` wide**, aspect `63/88` (≈`92px` tall)                                  | art thumbnail / caption `rgba(0,0,0,.55)`/`#cdd6df` `7px`; border `1px rgba(235,235,235,.15)`                                                         | `flex:0 0 66px`                                                       | N                           |
| Subject empty state `.subject.empty`                            | same `66×92` footprint                                                          | transparent / `#8fa0b0` `9px` / `1px dashed #abb6c2`                                                                                                  | centred "No art selected"                                             | N                           |
| Identity column `.idcol`                                        | `slot 14/700`, `name 15px`; empty name `italic #8fa0b0`                         | text `#ebebeb`; face `#8fa0b0` `11px` uppercase                                                                                                       | `flex:1; min-width:0`                                                 | I (values)                  |
| Requested≠resolved flag `.mismatch` (rev #2)                    | `10px` mono                                                                     | `#ffc107` / `#111`                                                                                                                                    | `margin-top:5px; padding:1px 7px`; hidden in empty state              | N                           |
| **"More details" toggle** `.detmore` (rev #1)                   | `11px`                                                                          | `#8fa0b0` (hover `#ebebeb`); no border                                                                                                                | `margin-top:6px; gap:4px`                                             | N                           |
| "More details" body `.detbody`                                  | rows `11px`; key `10px` uppercase                                               | key `#8fa0b0` (flex 0 0 88px); value `#ebebeb` (mono where numeric); top border `#16202b`; id-copy `#5bc0de` dotted; tag pill `#4e5d6c`/`#ebebeb` r10 | `margin-top:8px; padding-top:8px`                                     | N                           |
| "More details" actions ×2 (Favourite/Download)                  | `btn-sm`                                                                        | `btn-outline-light`                                                                                                                                   | `gap:6px; margin-top:8px`                                             | N                           |
| **Identify panel band** `.idhang` (item 6)                      | —                                                                               | `#2b3e50` (same as D14) / — / bottom `#16202b`                                                                                                        | `padding:0 10px 8px`                                                  | N                           |
| Identify toggle `.idtoggle`                                     | `12px`                                                                          | transparent / `#abb6c2` / `1px #6b7d8e` (hover `#abb6c2`)                                                                                             | `padding:3px 8px; gap:6px`                                            | N                           |
| Identify body `.idbody`                                         | —                                                                               | `#22303f` / — / `1px #16202b`                                                                                                                         | `margin-top:8px; padding:8px`                                         | N                           |
| Identify consensus line `.cons`                                 | `11px`                                                                          | `#8fa0b0` (value `#ebebeb`)                                                                                                                           | `margin-bottom:6px`                                                   | N                           |
| Identify search input `.idsearch`                               | `12px`                                                                          | `#2b3e50` / `#ebebeb` / `1px #4e5d6c`; radius `0`                                                                                                     | `padding:5px 8px; mb:8px`                                             | N                           |
| Candidate grid `.candgrid`                                      | 4-col grid                                                                      | —                                                                                                                                                     | `gap:6px`                                                             | N                           |
| Candidate tile `.cand`                                          | aspect `63/88`                                                                  | tile gradient / — / `1px #6b7d8e`; sel `2px #5cb85c`; No-match `#1b2836`/`#8fa0b0`                                                                    | pad `2px`                                                             | N                           |
| Candidate label `.cl`                                           | `7px` mono                                                                      | `rgba(0,0,0,.65)` / `#ebebeb`                                                                                                                         | —                                                                     | N                           |
| **Sort dropdown** `.sortsel` (item 2)                           | `12px`                                                                          | `#22303f` / `#ebebeb` / `1px #4e5d6c`; radius `0`                                                                                                     | `padding:3px 6px; max-width 150px`                                    | N                           |
| **Filters toggle** `.filtersbtn` (item 2)                       | `btn-sm`                                                                        | `btn-outline-light` (`#abb6c2`) + chevron                                                                                                             | `padding:4px 8px; gap:5px`                                            | N                           |
| SV header row `.svhead`                                         | `12px`                                                                          | `#8fa0b0` (`.n` `#ebebeb/700`)                                                                                                                        | `gap:6px; mb:6px; wrap`                                               | N                           |
| **Filters panel — inline (phone)** `.fpanel.inline`             | —                                                                               | `#22303f` / — / `1px #16202b`                                                                                                                         | `padding:8px; mb:8px`                                                 | N                           |
| **Filters panel — float (desktop/tablet)** `.fpanel.float` (O3) | `width:440px`, `max-width:calc(100%-32px)`, `max-height:calc(100%-96px)` scroll | `#22303f` / — / `1px #7f8fa0`; shadow `0 12px 34px rgba(0,0,0,.6)`                                                                                    | `position:absolute; left:50%; top:64px; translateX(-50%); z-index:91` | N                           |
| Float panel title bar `.fptitle` (O3)                           | `12px/700` uppercase                                                            | `#4e5d6b` / `#ebebeb`; close btn `1px rgba(235,235,235,.2)`                                                                                           | `padding:8px 12px; sticky top:0`                                      | N                           |
| Float backdrop `.fscrim` (O3)                                   | full-frame                                                                      | `rgba(0,0,0,.45)`; `z-index:90`                                                                                                                       | shown desktop/tablet only                                             | N                           |
| Fieldset `.fset`                                                | —                                                                               | —                                                                                                                                                     | `margin-bottom:9px`                                                   | N                           |
| Fieldset legend `.lg`                                           | `10px` uppercase                                                                | `#8fa0b0`                                                                                                                                             | `margin-bottom:4px`                                                   | N                           |
| Fieldset row label `.frl`                                       | `10px` uppercase                                                                | `#8fa0b0`                                                                                                                                             | `flex:0 0 46px`                                                       | N                           |
| Fieldset separator `.fsep`                                      | `1px`                                                                           | `#16202b`                                                                                                                                             | `margin:9px -8px`                                                     | N                           |
| **SUGGESTED chip** `.tchip.suggested` / `.seg .suggested` (O1)  | `11px`                                                                          | dashed `1px #abb6c2`; trailing `⌇` glyph `#abb6c2`                                                                                                    | `.sg margin-left:2px`                                                 | N (ratified funnel F3 look) |
| **Implicit-vote awareness line** `.implicit-note` (O1)          | `10px`                                                                          | `#8fa0b0`; leading `ⓘ` `#5bc0de`                                                                                                                      | `margin-top:7px; gap:5px`                                             | N                           |
| Range fieldset `.frange/.ftrack`                                | track `4px`; knob `12px`                                                        | track `#3a4653`; fill `#df6919`; knob `#abb6c2`/`#fff` border                                                                                         | `gap:8px`                                                             | N                           |
| Range value `.fval`                                             | `10px` tabular                                                                  | `#8fa0b0`                                                                                                                                             | —                                                                     | N                           |
| Tree-select box `.ftree`                                        | `11px`                                                                          | `#2b3e50` / `#8fa0b0` / `1px #4e5d6c`; chip `#4e5d6c`/`#ebebeb` r10                                                                                   | `padding:4px 8px; gap:6px`                                            | N                           |
| NSFW switch `.swtrack`                                          | `34×18`; knob `14`                                                              | off `#3a4653`; on `#df6919`; knob `#abb6c2`→`#fff`                                                                                                    | label `13px`/gap `8px`                                                | N                           |
| **Control stack** `.cstack` (item 7)                            | —                                                                               | `#4e5d6c` (rail) — no own bg                                                                                                                          | `padding:8px 10px`                                                    | N                           |
| Control-stack legend `.cs-legend`                               | `10px` uppercase                                                                | `#8fa0b0`                                                                                                                                             | `margin-bottom:5px`                                                   | N                           |
| Bleed select `.bleedsel`                                        | `13px`                                                                          | `#22303f` / `#ebebeb` / `1px #4e5d6c`; radius `0`                                                                                                     | `padding:4px 8px; width 100%`                                         | N                           |
| Bleed hint `.cs-hint`                                           | `10px`                                                                          | `#8fa0b0`                                                                                                                                             | `margin-top:4px`                                                      | N                           |
| Slot-action buttons ×3                                          | `btn-sm block` left-aligned                                                     | Change/Duplicate `btn-outline-light`; Delete `btn-outline-danger`                                                                                     | `gap:6px`                                                             | N (composition)             |
| Control-stack foot `.cs-foot`                                   | —                                                                               | top border `#16202b`                                                                                                                                  | `padding-top:8px`                                                     | N                           |
| Report button `.reportbtn`                                      | `btn-sm block`                                                                  | `btn-outline-danger` (`#d9534f`) + `⚑`                                                                                                                | —                                                                     | N (composition)             |
| Report reason chips `.rchip` ×5                                 | `11px`                                                                          | `#22303f` / `#ebebeb` / `1px #4e5d6c` (hover danger)                                                                                                  | 3-col grid `gap:6px`                                                  | N                           |

---

## E. Owner decisions logged this round (RD = rail-delegacy; all PROPOSED, pending sign-off)

- **RD1 (owner-ruled, O1 UNIFIED, 2026-07-24).** There is exactly ONE chip surface — the existing
  funnel per-axis chips (`attributeChips.ts` `FUNNEL_AXES`): Border/Frame as positive-or-off radio
  segments, Treatment as a tri-state include/exclude cycle. The separate `.achip` "attribute vote"
  fieldset is REMOVED. Per the ratified record (`docs/features/printing-tags.md` "Frontend consumer
  (funnel round)" / "Implicit votes"; `grid-selector.md` funnel + Compliance-fix), the funnel chips
  ARE the voting surface: picking a candidate while chips are active casts CAPPED IMPLICIT support
  votes (`castImplicitVote`, weight 0.25, per-outcome cap 1.0 < quorum, never human-backed, never
  tips a contest). SUGGESTED chips (dashed + trailing `⌇`) are driven by `suggestedFilterTagNames`
  (NOT `tagVoteStatuses` — condition 6, no self-seeding), and exclude sensitive tags. An
  implicit-vote awareness line states the passive-signal behaviour. The design implies NO new voting
  mechanic. Explicit attribute voting remains ONLY where it already lives — the D14 identify
  follow-up's `AttributeVotingPanel` (item 6).
- **RD2.** Sort (item 2) is a compact `Form.Select` of the 6 `SortByOptions`, inline in the SV
  header (O5 accepted — the tree-select's inline search is dropped for now).
- **RD3.** Jump to Version is SCRAPPED (O4 ruled fully dead). The continuous grid + the Sources/
  identify searches are the funnel; the eventual power path is **search-in-the-filter-bar** (noted
  in §H Futures), not a revived numeric jump.
- **RD4 (owner-ruled, O3, 2026-07-24).** The Filters panel is tier-conditional: **phone** = in-rail
  `Collapse` expanding IN PLACE inside the one scroll container (no overlay-over-overlay in the
  bottom-sheet); **desktop inline rail + tablet drawer** = a panel that FLOATS toward the CENTRE of
  the viewport (a frame-level `Overlay` + backdrop, escaping the 380px column and the tablet
  drawer's own clipping — there's more room there and no stacking hazard). One shared fieldset body
  feeds both so they can't drift.
- **RD5.** Print Options + Slot Actions + Report collapse into one `.cstack` at the rail bottom;
  Report is a single `btn-outline-danger` that expands to the `ReportCardPanel` reason chips
  in place (ruled).
- **RD6 (owner-ruled, rev #1, 2026-07-24).** O2 answered: the WHOLE Card-Details metadata block —
  Resolution/DPI, File size, Source, Source type, Class, Identifier, Language, Tags, dates, plus
  `CardDownloadFavorite` (Download + Favourite) — lives ONLY in the "More details" `Collapse`.
  Rail-head carries no metadata rows; it stays lean (subject image + Slot · name + toggle). This
  RETIRES disposition item 4's "small muted rows under the card name".
- **RD7 (owner-ruled, rev #2, 2026-07-24).** The printing identifier appears exactly ONCE in the
  rail. Proposed & applied canonical home = the **D14 confidence band** (`.idtext`) — the
  always-visible "what printing is this" context, so identity never requires expanding a disclosure.
  Removed from rail-head and from More details. `RequestedPrintingBadge` survives only as a
  conditional mismatch flag (requested ≠ resolved), never a static second copy.
- **RD8 (owner-ruled, rev #3, 2026-07-24).** The rail TOP shows a **subject-card image** — a `66px`
  preview of the slot's selected art (aspect `63/88`), left of the identity text, with a dashed
  "No art selected" empty state. Restores the classic Card-details modal's subject preview that the
  unified rail had dropped. Sized as a preview, not a second full render (Select Version stays the
  art surface); at `66px` it does not starve the 390px grid — verified.

Honoured LOCKED decisions (unchanged): D2 (identical composition per breakpoint), D3 (promote
identity/art, demote metadata — here "demote" means fold, not a grey accordion), D14 + #271 +
owner answer #2 (confidence element & the ✗-stays-de-emphasised rule), owner answer #3 (Sources
inline), owner answer #5 (source pins + #353 seam), §F (one continuous grid).

---

## F. FEATURES ACCOUNTED FOR — every control from the nine removed grey sections

| #   | Removed grey section                | Control / content it held                                                                                               | New home (this round)                                                                                                                                                                                              |
| --- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | **Jump to Version**                 | numeric "option #" jump + identifier input                                                                              | **SCRAPPED** (RD3/O4) — grid funnel + searches replace it                                                                                                                                                          |
| 2   | **Sort**                            | `NullableSortByFilter` (6 sort orders, radioSelect)                                                                     | → `Form.Select` in SV header row (item 2 / RD2)                                                                                                                                                                    |
| 3   | **Filter** (remaining after #409)   | DPI range (`DPIFilter`)                                                                                                 | → Filters panel fieldset "Resolution (DPI)"                                                                                                                                                                        |
| 3   |                                     | Max size (`SizeFilter`)                                                                                                 | → Filters panel fieldset "Max file size"                                                                                                                                                                           |
| 3   |                                     | Languages (`LanguageFilter`)                                                                                            | → Filters panel fieldset "Languages"                                                                                                                                                                               |
| 3   |                                     | Tags (`TagFilter`)                                                                                                      | → Filters panel fieldset "Tags"                                                                                                                                                                                    |
| 3   |                                     | NSFW (`MatureContentFilter`)                                                                                            | → Filters panel fieldset "Mature content" (switch)                                                                                                                                                                 |
| 3   | _(pre-removed #409)_                | stock sources table (`SourceSettings`), `CanonicalCardFilter`, `ResolvedAttributeFilter`                                | already hidden from the rail's Filters panel (PR #409 `d8db75db`) — **accounted, not this round's drop**                                                                                                           |
| 4   | **Card Details**                    | Canonical Card set/collector (the printing id)                                                                          | → **D14 band, ONE canonical occurrence** (rev #2 / RD7)                                                                                                                                                            |
| 4   |                                     | Resolution (DPI), File Size, Source Name/Type, Class, Identifier (`ClickToCopy`), Language, Tags, Date Created/Modified | → **"More details" disclosure** (rev #1 / RD6 — O2 answered)                                                                                                                                                       |
| 4   |                                     | Download Image + Add to Favourites (`CardDownloadFavorite`)                                                             | → **"More details" body** (rev #1 / RD6)                                                                                                                                                                           |
| 4   |                                     | Canonical Artist                                                                                                        | → already the promoted Artist line (ArtistSection) — **accounted**                                                                                                                                                 |
| —   | _(rev #3 NEW, not one of the nine)_ | subject-card preview (classic modal had it)                                                                             | → **subject-card image at the rail top** (RD8)                                                                                                                                                                     |
| 5   | **Attributes**                      | attribute-lean signal on Border/Frame/Treatment                                                                         | → **UNIFIED into the ONE funnel chip surface** (O1/RD1): the funnel chips already carry the SUGGESTED (`⌇`) lean from `suggestedFilterTagNames` and cast capped implicit votes on pick. No separate vote fieldset. |
| 5   |                                     | explicit attribute voting (`AttributesSection`/`useTagVoting` deliberate taps)                                          | → lives ONLY in the D14 identify follow-up's `AttributeVotingPanel` (item 6) — the single explicit surface (O6 resolved by O1's record)                                                                            |
| 6   | **Printing Tags**                   | `PrintingTagPicker` (consensus line, search, candidate thumbnail grid, "No match", vote submit)                         | → identify panel hanging off D14 (item 6)                                                                                                                                                                          |
| 6   |                                     | `AttributeVotingPanel` follow-up (shown when printing unresolved)                                                       | → follow-up region inside the identify panel — the ONE explicit attribute-vote surface                                                                                                                             |
| 7   | **Print Options**                   | Bleed override `Form.Select` (Auto/Force bleed/Force trimmed); ineligible-card muted message                            | → `.cstack` "Print options" group (item 7)                                                                                                                                                                         |
| 7   | **Slot Actions**                    | `getCardSlotMenuActions` → Change query / Duplicate / Delete (+ Unfilter printing when filtered)                        | → `.cstack` "Slot actions" button stack (item 7)                                                                                                                                                                   |
| 7   | **Report**                          | `ReportCardPanel` flag button → 5 reason chips (NSFW/Low quality/Wrong card/Broken image/Other + free-text)             | → `.cstack` single Report button → chips (item 7)                                                                                                                                                                  |

Not among the nine, unchanged: **View** (already hidden via `hiddenSections=["view"]`), **Sources**
(designed inline element, owner answer #3), **Artist**, **D14**, **RailHeader identity**, **Select
Version grid**.

---

## G. Accessibility

Hit targets ≥38px for source toggles/pins (`ToggleButtonHeight`); D14 set icon `tabIndex=0` +
popover on focus; Sort is a labelled `Form.Select`; the Filters toggle and identify toggle are
`button`s with `aria-expanded`/`aria-controls`; each filter fieldset is a `fieldset` with a text
legend; filter chips carry `+/−/·` glyph state, vote chips carry `✓/✗/·` glyph + `aria-label`
spelling the state (colour never the only signal); the NSFW control is a `role="switch"` with
`aria-checked`; candidate tiles and report chips are focusable `button`s. Grid keeps `role=list`.
AA contrast holds on the four rail surfaces (`#0f2537/#22303f/#2b3e50/#4e5d6c`).

---

## H. Open questions — ALL RESOLVED (owner rulings 2026-07-24)

Every question from the prior pass is now closed; nothing owner-facing remains open for this design.

- ~~**O1.**~~ **RESOLVED — UNIFIED** (→ RD1): ONE chip surface (the funnel chips, which are the
  implicit-vote surface per the ratified record); the separate `.achip` vote fieldset is removed;
  explicit voting stays in the D14 follow-up only. Design implies no new voting mechanic.
- ~~**O2.**~~ **ANSWERED** (rev #1/#2 → RD6/RD7): whole metadata block + Download/Favourite in "More
  details"; printing id lives once in D14; rail-head lean.
- ~~**O3.**~~ **RESOLVED — TIER-CONDITIONAL** (→ RD4): phone = in-rail expand in place; desktop +
  tablet = float toward viewport centre.
- ~~**O4.**~~ **RESOLVED** (→ RD3): Jump to Version fully dead, no numeric-jump path preserved.
- ~~**O5.**~~ **RESOLVED — ACCEPTED**: plain 6-option `Form.Select` for Sort (for now).
- ~~**O6.**~~ **RESOLVED by O1's record**: the funnel chips carry the implicit lean; the ONE explicit
  attribute-vote surface is the D14 identify follow-up. Voting flows are unchanged from this panel
  and this page generally.

**Futures (noted, not this round):** the eventual power-user replacement for the scrapped Jump to
Version is **search-in-the-filter-bar** — typing to narrow the version grid from the same bar that
holds the funnel chips. Out of scope here; recorded so the intent isn't lost.

---

## I. Verification

Playwright (`shot.js`, chromium) at **390px**, **900px** and **1400px**; screenshots inspected.

Final-pass shots (2026-07-24, O1/O3):

- `v-1400-floatpanel-el.png` — the desktop/tablet Filters panel floated to viewport centre: ONE chip
  surface (Border/Frame radio + Treatment tri-state), the SUGGESTED "Showcase ⌇" dashed chip, the
  implicit-vote awareness line, then DPI/Size/Languages/Tags/NSFW. No separate vote fieldset.
- `v-1400-filters-float.png` — same, in the full desktop frame with centred float + backdrop over
  the sheet region.
- `v-900-tablet-drawer.png` — tablet: the Filters panel floats to viewport centre (escapes the start-
  drawer's clipping), Card-details drawer still on the left.
- `v-390-filters-inline.png` — phone: the Filters panel expands IN PLACE inside the rail scroll (no
  float; the `.fpanel.float` node isn't even rendered on the phone frame — verified `display:none-el`).

Revision-pass shots (2026-07-24, subject/dedup):

- `v-1400-railhead-lean.png` — rail-head now lean: `66px` subject-card thumbnail + Slot·name +
  conditional mismatch flag + "More details ›"; NO printing id (rev #1/#2/#3 all visible).
- `v-1400-railhead-details.png` — "More details" open: full `CardMetaTable` block (Resolution, File
  size, Source, Source type, Class, Identifier, Language, Tags, Created, Modified) + Favourite/
  Download; canonical printing id NOT repeated here (lives in D14).
- `v-1400-railhead-empty.png` — dashed "No art selected" subject placeholder + italic empty name;
  mismatch flag correctly suppressed.
- Deduped identity confirmed: the only textual "2X2 · 117" identity display in the rail is the D14
  band (grid tiles / picker candidates are their own labels, not identity copies).

Base shots (re-verified after revision):

- `v-1400-auto.png` (desktop three-region), `v-1400-rail-allopen.png` (full rail, filters +
  identify + report all open) — every folded element renders cohesively; no grey accordion remains.
- `v-1400-d14-confirmed.png` / suggested state via demo toggle — confirmed shows green ✓ + "Confirmed"
  pill + the ✗ vote de-emphasised (opacity .6); suggested shows the score badge + "92% confident"
  pill. **Locked D14/owner-#2 treatment reproduced exactly.**
- `v-390-auto-top.png`, `v-390-auto-full.png`, `v-390-filters-open.png`, `v-390-all-open.png` (native
  390 phone), `v-390-rail-bottom.png` (drawer scrolled) — full rail reachable in the bottom-sheet.
- `v-phone-bottom-stack.png` (forced-phone frame, real 72vh clip, scrolled to end) — the bottom
  control stack (bleed select, Change/Duplicate/Delete, Report-expanded reason chips) all render and
  **fit at 390px width**, proving phone reachability to the very bottom.
- `v-900-tablet-drawer.png` (forced tablet start-drawer) — identical rail interior at md.

**Bug caught + fixed:** inside the drawer the rail's inline `flex:0 0 380px` was being read as a
380px HEIGHT in the column-flow drawer, capping the bottom-sheet so the control stack couldn't be
scrolled to. Added `.drawer .lrail{flex:1 1 auto; min-height:0}` + `.drawer .lscroll{flex:1 1 auto}`;
re-verified the scrolled-to-bottom shot. This is a real fidelity note to carry into the Offcanvas
body implementation (§A). Zero page errors across all frames.
