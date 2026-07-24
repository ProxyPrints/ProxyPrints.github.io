# /display LEFT RAIL — CORRECTED fidelity round (breakpoint spec + binding token table)

Companion to `display-left-rail-mockup.html` (same directory). Owner reviews the
mockup in a browser BEFORE any implementation. This document supersedes the prior
mockup round (2026-07-23 implementation round), which was rejected for two
defects (both fixed here — see §A). This corrected round is itself
owner-approved; every value below is BINDING (see the note under §D).

Scope = the LEFT rail / card surface of the Proposal H unified page (served at
`/editor`; `/display` redirects). Center sheet + RIGHT rail are shown in the
mockup for three-region context only. Every primitive is the installed
react-bootstrap 2.10.10 / Bootstrap 5.3.8 family — **no new dependencies**;
shared components gain only additive, optional, behaviour-preserving props.

All CSS values below are **BINDING** (owner standing rule, 2026-07-23: approved
mockup/spec values are binding; a visual regression against the approved mockup
is a defect). Every value is either **inherited** (already shipped on master via
PR #352's fidelity pass — reproduce verbatim) or **introduced** (new/normalized
this round — flagged, and labelled `.propose` in the mockup where it changes the
current look). §A is the full inherited-vs-introduced ledger.

---

## A. What the two rejection defects were, and the fix

**Defect (a) — element sizing/colouring regressed vs the binding spec.** The
prior mockup carried at least these drifts from the shipped/#302 values:

| Element                   | Prior mockup (wrong)                                                | Corrected (grounded source)                                                                             |
| ------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Source toggle height      | `24px`                                                              | **`38px`** = `ToggleButtonHeight` (`common/constants.ts`); shipped SourcesAccordion passes exactly this |
| Source pin ★ hit target   | ~18px, no min size                                                  | **`38×38`** min (`ToggleButtonHeight`) — a11y ≥ touch min                                               |
| `.btn-sm` metrics         | `12px / 3px 8px`                                                    | **`14px / 4px 8px`** = Bootstrap `$font-size-sm` / `$input-btn-padding-*-sm`                            |
| `.d14` bottom hairline    | `rgba(0,0,0,.22)`                                                   | **`#16202b`** = shipped `RailRoot .d14` border-bottom                                                   |
| `.select-version-heading` | `margin:0 0 6px`                                                    | **`padding:8px 0 4px; margin:0`** = shipped `.select-version-heading`                                   |
| Block dividers (mixed)    | mix of `rgba(0,0,0,.22)` / `rgba(235,235,235,.15)` / Bootstrap util | **`#16202b` uniform** (normalized — see below), `.propose`                                              |

**Defect (b) — the "is this matching Y/N" consensus prompt didn't follow the
owner's decision.** Fixed per the unambiguous record (see §C). The standalone
Confirm?/Y·N block is gone (superseded, #271); the `✗ not this printing` vote
**stays visible on a confirmed printing, de-emphasised (opacity 0.6)** per owner
answer #2, and this is framed in the mockup as a **settled decision**, not an
open question.

**Inherited (reproduced verbatim from shipped `RailRoot` / `AutofillCollapse` /
`ArtistSection` / `SourcesAccordion` / `ConfidenceElement`):** the whole §D.0
#302 palette; `.rail-head`/`.artist-line` bg `#22303f`, padding `8px 10px`;
AutofillCollapse header bg `#4E5D6B` + padding `7px 10px`; `.d14` bg `#2b3e50`
padding `8px 10px`; `.seticon` 30px circular bg `#4e5d6c` border `#7f8fa0`;
`.check` 15px `#5cb85c`; `.score` `#df6919` radius 10px; `.statepill` radius
10px, confirmed `#3f7a2f`/`#a7e08a`, suggested `#df6919`/`#ffb27d`; src-list
border `rgba(0,0,0,.22)` bg `#22303f`; toggle onstyle=primary/offstyle=secondary
width 54px; tile densities 72/88/112.

**Owner ruling, 2026-07-23 — `#4E5D6B` vs `#4e5d6c` is deliberate, not a
typo.** PR #400's own predecessor round "corrected" the `AutofillCollapse`
header background from `#4E5D6B` to `#4e5d6c` (`$secondary`), treating the one
hex-digit gap as a hand-typed literal error. The corrected mockup's own live
DOM is the actual binding reference here (not an approximation of it), and it
renders the card-header token as `#4E5D6B` — one hex digit off `$secondary`
BY DESIGN, distinguishing the AutofillCollapse header surface from the panel/
seticon/Card-body token elsewhere in the rail. **Do not "fix" this back to
`#4e5d6c` again** — `AutofillCollapse.tsx`'s own inline-style comment at this
exact line carries the same note.

**Introduced this round (needs owner sign-off, labelled in the mockup):**

1. **Divider normalization to `#16202b`, 1px, on every rail block boundary.**
   Shipped code was inconsistent — `.d14` used an explicit `#16202b`, while
   `.rail-head`/`.artist-line`/`.sources` used Bootstrap's `.border-bottom`
   utility whose active `--bs-border-color` is ambiguous in the compiled CSS
   (`#495057` vs `#ced4da` both present; the light value would render a pale
   line on the dark rail). Normalizing all boundaries to the one explicit
   shipped dark value removes the fidelity hazard and suits the flat dark
   theme. **Open item O1 — CONFIRMED (owner-approved 2026-07-23) and
   implemented** (`.rail-head`/`.artist-line`/`.sources`/the Select Version
   wrapper/the unified filter fieldset/the fieldset's internal Frame↔Treatment
   divider all now carry the explicit `#16202b` value — see §J for exactly
   where each one resolves from).
2. `.btn-sm` set to Bootstrap's real `sm` metrics (14px / 4px 8px) rather than
   the prior mockup's smaller invented values. This is a _return_ to the
   framework default, not a new look, but it is larger than what the prior
   mockup showed — flagged so the owner sees the denser-vs-standard tradeoff.
   **RESOLVED (owner ruling, 2026-07-23): the corrected mockup is the binding
   reference for this row too, superseding the earlier "the buttons are too
   big" shrink for the rail's Filters disclosure toggle specifically**
   (`SelectVersionResults.tsx`'s `CompactButton`, 14px/4px 8px now — its one
   call site is that button, so the fix is component-scoped by construction).
   `CompactToggleButton` (Frame/Border segmented chips) and `TreatmentChip`
   (Treatment tri-state chips) are UNCHANGED — they bind to their own
   distinct, still-in-force D.1 rows ("Filter segment group `.seg`" 11px,
   "Treatment tri-state chip" 11px), never the generic `.btn-sm (all)` row,
   so the ruling doesn't touch them. See `DisplayLeftRailFidelity.spec.ts`'s
   own comment at the `funnel-filters-toggle` assertion.
3. **Source toggle restyled from the shared `react-bootstrap-toggle`
   library's stock sliding single-label switch into the corrected mockup's
   static two-cell segmented control** (both "On"/"Off" labels always
   visible side by side, never sliding/clipped). **RESOLVED (owner ruling,
   2026-07-23): the mockup's rendered look is binding; the library CAN be
   styled to match it** — its real DOM already renders both `.toggle-on`/
   `.toggle-off` spans, each already carrying the requested
   `btn-primary`/`btn-secondary` colour classes unconditionally (confirmed
   by reading `node_modules/react-bootstrap-toggle/dist/react-bootstrap-toggle.js`);
   only the library's own `overflow:hidden`/`.toggle-group{width:200%}`
   sliding-and-clipping CSS needed overriding to reveal both cells at once.
   Scoped to a `rail-source-toggle` className (`SourcesAccordion.tsx`'s own
   Toggle passes it) so every OTHER `react-bootstrap-toggle` mount sitewide
   (`FinishSettings`/`PDFGenerator`/`SearchTypeSettings`/the filter Toggles/
   etc — same library, ~10 other call sites) is completely unaffected.

---

## B. Breakpoint behaviour — left-rail placement (react-bootstrap primitives)

The left rail is ONE node: `Offcanvas responsive="lg"` (shipped R2 shell,
unchanged). Content composition is IDENTICAL at every breakpoint (D2) — only the
chrome differs. The mockup's single `leftRail()` builder proves it can't drift.

| Tier    | Width      | Bootstrap | Left-rail chrome                                                                     |
| ------- | ---------- | --------- | ------------------------------------------------------------------------------------ |
| Phone   | `<768`     | xs+sm     | `placement="bottom"` 72vh bottom-sheet, opens on slot tap; rounded top + drag handle |
| Tablet  | `768–991`  | md        | `placement="start"` drawer, opens on slot tap; "Card details" edge handle when idle  |
| Laptop  | `992–1199` | lg        | Inline sticky **380px** column                                                       |
| Desktop | `≥1200`    | xl        | Inline sticky **380px** column                                                       |

Inline width `380px`; `overflow-y:auto` own scroll container; sticky `top:0`
(action-bar height via CSS var, #250). Unchanged from the shipped shell — this
round restyles/recomposes the rail INTERIOR only.

**Phone reachability (hard requirement, verified):** every surface below lives in
the one `overflow-y:auto` rail container, so all of it is reachable in the 72vh
phone bottom-sheet by scrolling — verified in the mockup's native 390px phone
frame (top → D14 → Sources → Select Version → demoted sections → Slot Actions
button stack all reached) and in the scaled forced-Desktop-on-phone frame.

---

## C. The Y/N consensus-prompt decision applied (rejection cause b)

**Record found (unambiguous):** `proxyprints-orchestration/DECISIONS.md`,
`2026-07-23`: _"OWNER APPROVED Quorra's unified-page design ('go on that design')
with six answers"_ — of which **answer #2** governs the Y/N prompt: _"keep ✗ on
confirmed (verified sound: explicit human dissent = D1 human-vs-human contest per
ratified matrix)."_ This resolves the prior spec's Open Item 2 (which had been
left as "owner call: keep visible vs hide once resolved"). The D14 rewrite that
removes the standalone Confirm?/Y·N block is the separately-locked owner decision
#271 (c.2026-07-21). Both are reflected in the shipped `ConfidenceElement.tsx`
(`.notthis[data-confirmed="true"]{opacity:0.6}`) and `RailHeader` removal note.

**Applied treatment (exactly as decided, shipped):**

1. **No standalone "matching? Y/N" block anywhere in the rail.** Removed
   (superseded by D14, #271). It appears ONLY in the mockup's "Before (live)"
   recreation of the owner's screenshot `8f5b65ce`, labelled as the superseded
   element.
2. **Human-confirmed printing** (`canonicalCard != null`): green ✓ badge on the
   set icon + green **"Confirmed"** pill. No number, no Y/N.
3. **Machine-suggested printing** (only `suggestedCanonicalCard`): numeric score
   badge + amber **"N% confident"** pill; positive confirmation is a **corner
   ribbon** on the suggested tile in the Select Version grid (§F moment-a), which
   fires the existing `DeckbuilderConfirmAffordance` action — never a separate
   block.
4. **Negative half — `✗ not this printing`** (a real `useTagVoting` vote):
   present in both states, and per **owner answer #2 STAYS VISIBLE on a confirmed
   printing, de-emphasised via `opacity:0.6` (not hidden)** — explicit human
   dissent opens a D1 human-vs-human contest. Framed as settled.

The mockup demo strip toggles "D14 state → Suggested / Confirmed" so the owner
sees both, and toggles "Select Version → Before (live) / After (new)" so the
superseded Y/N block is visible side-by-side with its replacement.

---

## D. BINDING token table — every rail element (sizing · colouring · spacing)

Every value below is **BINDING** (owner standing rule, 2026-07-23): approved
mockup/spec CSS values are binding for the full token table (sizing, colouring,
spacing) of every element on the affected page — a fidelity regression vs. an
approved mockup is a defect, and `DisplayLeftRailFidelity.spec.ts` enforces the
rows marked `Source: local` in §J via real `getComputedStyle` reads. `I` =
inherited (shipped, reproduce verbatim). `N` = introduced/normalized this round.
Colours are the §D.0 #302 tokens.

### D.0 Palette tokens (all inherited — `styles.scss` #302 + Superhero)

> **SUPERSEDED (2026-07-24, owner ruling — "Tokyo-11" re-theme).** The
> table below is the #302 palette this section originally shipped with; it
> is kept verbatim here as a historical record of what shipped at the time
> this spec's other rows (sizing/spacing/I-N markers) were written and
> verified against. It no longer reflects the site's actual colours. The
> live, binding palette is [`docs/features/theming.md`](../../../features/theming.md)
> — edit `_theme-tokens.scss` there, not this table, for any future
> retheme.

| Token            | Value              | Token              | Value                 |
| ---------------- | ------------------ | ------------------ | --------------------- |
| body bg          | `#0f2537`          | primary (hover)    | `#df6919` (`#be5915`) |
| panel/card/2ndry | `#4e5d6c`          | success            | `#5cb85c`             |
| card-header      | `#4e5d6b` (inline) | danger             | `#d9534f`             |
| raised/input bg  | `#22303f`          | warning            | `#ffc107`             |
| D14 band         | `#2b3e50`          | info               | `#5bc0de`             |
| text             | `#ebebeb`          | input border       | `#4e5d6c`             |
| muted            | `#8fa0b0`          | radius             | `0` (flat)            |
| light            | `#abb6c2`          | status-pill radius | `10px`                |

### D.1 Element table

| Element                                         | Sizing                         | Colour (bg / text / border)                                              | Spacing                                | I/N                                                        |
| ----------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------ | -------------------------------------- | ---------------------------------------------------------- |
| `.rail-head`                                    | —                              | `#22303f` / `#ebebeb` / bottom `#16202b`                                 | `padding:8px 10px`                     | I (border N)                                               |
| `.rail-head .slot`                              | `14px/700`                     | text `#ebebeb`; face `#8fa0b0` `11px` uppercase                          | face `margin-left:6px`                 | I                                                          |
| `.rail-head .name`                              | `15px`                         | `#ebebeb`                                                                | `margin-top:1px`                       | I                                                          |
| `RequestedPrintingBadge`                        | `12px` mono                    | `#4e5d6c`/`#fff`; degraded `#ffc107`/`#111`                              | `padding:2px 8px; mt:5px`              | I                                                          |
| `.d14` band                                     | `12px`, `flex-wrap`, `gap:8px` | `#2b3e50` / — / bottom `#16202b`                                         | `margin:0; padding:8px 10px`           | I (border N)                                               |
| `.d14 .seticon`                                 | `30×30` circle                 | `#4e5d6c` / — / `#7f8fa0`; radius `50%`                                  | `flex:0 0 30px`                        | I                                                          |
| `.d14 .seticon .check`                          | `15×15` circle                 | `#5cb85c` / `#fff` / `2px #2b3e50`                                       | `right/bottom:-3px`                    | I                                                          |
| `.d14 .seticon .score`                          | `9px/800` tabular              | `#df6919` / `#fff` / `2px #2b3e50`; radius `10px`                        | `right/bottom:-7px; pad 1px 4px`       | I                                                          |
| `.d14 .idtext`                                  | `12px` mono                    | `#ebebeb`                                                                | —                                      | I                                                          |
| `.d14 .statepill.confirmed`                     | `11px/700`                     | — / `#a7e08a` / `#3f7a2f`; radius `10px`                                 | `padding:1px 8px`                      | I                                                          |
| `.d14 .statepill.suggested`                     | `11px/700`                     | — / `#ffb27d` / `#df6919`; radius `10px`                                 | `padding:1px 8px`                      | I                                                          |
| `.d14 .notthis` (`✗`)                           | `btn-sm`                       | `btn-outline-danger` (`#d9534f`); confirmed → `opacity:.6`               | `margin-left:auto`                     | I                                                          |
| `.artist-line`                                  | `13px`                         | `#22303f` / `#ebebeb` / bottom `#16202b`                                 | `padding:8px 10px`                     | I (border N)                                               |
| Artist support button                           | `btn-sm`                       | `btn-outline-primary` (`#df6919`) + `↗` icon                             | `.by margin-bottom:6px`                | I                                                          |
| Sources header (`AutofillCollapse`)             | `12px/700` label               | `#4e5d6b` / `#ebebeb`; count N `#5cb85c`                                 | `padding:7px 10px; gap:8px`            | I                                                          |
| Sources pinned chip strip                       | `11px`                         | chip `#22303f` / `#ebebeb` / `rgba(0,0,0,.22)`; ★ `#ffc107`              | `gap:4px; pad 0 10px 7px`              | I                                                          |
| Sources filter input                            | `14px`                         | `#22303f` / `#ebebeb` / `#4e5d6c`; radius `0`                            | `padding:6px 10px; mb:8px`             | I                                                          |
| Sources bulk buttons ×3                         | `btn-sm`                       | `btn-outline-light` (`#abb6c2`)                                          | `gap:6px; mb:6px`                      | I                                                          |
| Sources "Save defaults" seam                    | `btn-sm block` disabled        | `btn-outline-success` (`#5cb85c`); `title` #353                          | `mb:8px`                               | I                                                          |
| Sources list container                          | `max-height:190px; scroll`     | `#22303f` / — / `rgba(0,0,0,.22)`                                        | —                                      | I                                                          |
| Source row                                      | — (row ≥38px)                  | / — / bottom `rgba(0,0,0,.22)`                                           | `padding:8px; gap:8px`                 | I                                                          |
| Sources outer wrapper `.sources`                | —                              | / — / bottom `#16202b`                                                   | —                                      | I (border N)                                               |
| Source toggle                                   | **`54×38`**                    | on `#df6919`/`#fff`; off `#4e5d6c`/`#8fa0b0`; `#6b7d8e` border           | —                                      | I                                                          |
| Source pin ★                                    | **`38×38`** hit                | pinned `#ffc107` / unpinned `#5b6b7b`; transparent                       | `min 38px`                             | I                                                          |
| Select Version wrapper                          | —                              | / — / bottom `#16202b`                                                   | `padding:8px 10px`                     | I (border N)                                               |
| `.select-version-heading`                       | `14px/600`                     | `#ebebeb`                                                                | `margin:0; padding:8px 0 4px`          | I                                                          |
| Filters toggle button                           | `btn-sm` + ▾ chevron           | `btn-outline-light` (`#abb6c2`)                                          | `margin-left:auto`                     | I                                                          |
| Unified filter block `.ufilter`                 | —                              | `#22303f` / — / `#16202b`                                                | `padding:6px 8px; mb:6px; row gap 6px` | I (border N)                                               |
| Unified filter internal Frame↔Treatment divider | `1px` wide                     | `#16202b` / — / —                                                        | `margin:0 2px`                         | I (border N)                                               |
| Filter segment group `.seg`                     | `11px`                         | seg `#22303f`/`#ebebeb`; active `#df6919`/`#fff`; `#4e5d6c` border       | `padding:3px 8px`                      | I                                                          |
| Treatment tri-state chip                        | `11px`                         | neutral `#6b7d8e`; inc `#5cb85c`/`.22 bg`; exc `#d9534f`/`.22 bg`/strike | `padding:2px 7px; gap:3px`             | I                                                          |
| Result grid `.vgrid`                            | `flex-wrap`                    | —                                                                        | `gap:6px`                              | I                                                          |
| Tile `.vtile`                                   | **`72` / `88` / `112`px**      | outline `rgba(235,235,235,.15)`; sel `2px #df6919`                       | —                                      | I                                                          |
| Tile REQ badge                                  | `8px/800`                      | `#df6919` / `#fff`                                                       | top-right                              | I                                                          |
| Tile ✓ canonical tag                            | `7px/800`                      | `rgba(92,184,92,.92)` / `#fff`                                           | top-left                               | I                                                          |
| Tile Alt tag                                    | `7px/800`                      | `rgba(91,192,222,.92)` / `#fff`                                          | top-left                               | I                                                          |
| Tile ? unknown tag                              | `7px/800`                      | `rgba(120,135,150,.92)` / `#fff`                                         | top-left                               | I                                                          |
| Tile confirm ribbon (§F-a)                      | `16px` triangle                | `#ffc107` / `#111` `?`                                                   | top-right                              | I                                                          |
| Ghost "+N" tile                                 | `72px` dashed                  | transparent / `#abb6c2` / `1px dashed #abb6c2`                           | grid gap                               | I                                                          |
| Demoted `AutofillCollapse` header               | `13px/600`                     | `#4e5d6b` / `#ebebeb`                                                    | `padding:7px 10px`                     | I                                                          |
| Demoted body                                    | `13px`                         | `#4e5d6c` / `#ebebeb`                                                    | `padding:8px 10px`                     | I — **known gap, not yet fixed** (see note below)          |
| Slot Actions buttons                            | `btn-sm block` stack           | Change/Duplicate `btn-outline-light`; Delete `btn-outline-danger`        | `gap:6px`                              | I                                                          |
| `.btn-sm` (all)                                 | **`14px / 4px 8px`**, radius 0 | per variant (§D.0)                                                       | —                                      | N — **RESOLVED (owner ruling, 2026-07-23)**; see §A item 2 |

**"Demoted body" 13px — known, deliberately deferred gap.** The machine-diff
fix round's own delta flagged this (measured via "Slot Actions buttons stack"
font-size, 13px mockup vs 16px built — the mockup's demoted body inherits
13px from `.acc-b{font-size:13px}`, the built page's demoted `AutofillCollapse`
bodies have no equivalent rule). The mechanical fix (an additive
`bodyFontSize?: string` prop on `AutofillCollapse.tsx`, mirroring the existing
`headerPadding` precedent, applied only at rail call sites) is well
precedented, but its blast radius wasn't verified this round: applying it to
EVERY demoted `RailSection` (not just Slot Actions, the only one the delta
script actually expanded and measured) would shrink the ambient font-size for
Card Details/Attributes/Printing Tags/Print Options/Report too, none of which
were measured — a real risk of shrinking some nested `.small`/badge element
further than intended in a section nobody's looked at. Left unfixed rather
than guessed; a follow-up pass should measure each demoted section
individually before applying the prop broadly.

---

## E. Bundle items → react-bootstrap mapping (unchanged design intent)

1. **Sources collapse (item 1):** `AutofillCollapse` shell (summary count in its
   `title`, pinned strip in the header region so it shows while collapsed) +
   `Form.Control` filter + `Button` bulk row + `react-bootstrap-toggle` `Toggle`
   rows + `button` pin star. **Inline** (owner answer #3); overlay shape is
   demo-only, rejected. Shipped `SourcesAccordion.tsx`.
2. **Unified Frame + Treatment filter (item 2):** one bordered `fieldset`
   (`.ufilter`) — Border stays its own exclusive `ToggleButtonGroup` row above;
   Frame = `ToggleButtonGroup type="radio"`; Treatment = five tri-state
   `Button`/`ToggleButton`s preserving `attributeChips.ts` `nextChipState`. No
   change to membership/filter math. Additive `SelectVersionResults` /
   `attributeChips` render change.
3. **Preferred-sources persistence (item 3):** pin ★ per row (device-local
   `localStorage` now, owner answer #5) + a disabled `btn-outline-success` "Save
   these as my defaults" **seam** (account-tie under #353). Signed-in vs anon:
   the pin/persist affordance is always present; the account-tied "defaults"
   button is the disabled seam until #353 lands a backend. **Backend annex:** a
   `POST /2/preferences/sources` (enabled-set + pinned-set, keyed to the Discord
   OAuth session) — out of scope for this round; frontend contract is the
   localStorage shape `getLocalStoragePinnedSourcePks`/`setLocalStorageSearchSettings`.
4. **Artist support crediting (item 4):** `ArtistSupportLink` (unchanged)
   rendered as `btn btn-outline-primary btn-sm`, children "Support on MTG Artist
   Connection", `↗` icon. Text credit only, zero-crawl. Shipped `ArtistSection.tsx`.
5. **Buttons-look-like-buttons (item 5):** artist link, D14 `✗`, Filters toggle,
   Slot Actions stack, Sources bulk + pin + save-defaults, ghost "+N", confirm
   ribbon — all real `.btn`/`button`. Empty-state "Find this card ↗" stays a link
   (pure navigation, the rule's explicit exception).

---

## F. Continuous Select Version grid (item 2, verbatim owner: "the 5 cards

should be in 1 section")

ALL candidate tiles pack into ONE `d-flex flex-wrap gap-2` (6px) grid;
canonical → non-canonical → unknown is **sort order only, zero visual
partitioning**. Per-group affordances annotate the tile:

| Affordance                 | New form                                                                                                                                           |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Requested printing         | `REQ` corner badge (`#df6919`), sorts first                                                                                                        |
| Canonical / resolved       | `✓` corner tag (`#5cb85c`)                                                                                                                         |
| Non-canonical / custom     | `Alt` corner tag (`#5bc0de`)                                                                                                                       |
| Unknown                    | `?` corner tag (muted)                                                                                                                             |
| "+N more of this printing" | inline ghost tile (dashed, `+N`), expands cluster in place                                                                                         |
| Suggested confirm (a)      | corner **ribbon** (`#ffc107`, `?`) on the suggested rep; fires existing `DeckbuilderConfirmAffordance` — **the only surviving confirm affordance** |

`role="list"` / `role="listitem"` carry the group + requested/suggested status in
`aria-label` so the sort semantics survive for AT even with no visual separators.

---

## G. Accessibility (consolidated)

Hit targets ≥38px for toggles/pins (`ToggleButtonHeight`); D14 set icon
`tabIndex=0` + popover on `focus`; Sources summary is a `button` with
`aria-expanded`/`aria-controls`; unified filter is a `fieldset`/`radiogroup`,
each treatment chip a `button` with state-spelling `aria-label`; grid
`role=list`; every corrected action is a focusable Enter/Space `button` with a
visible focus ring. All text/borders use the #302 tokens (AA on the four rail
surfaces). Colour is never the only signal (pill text + `aria-label` spell
confirmed/suggested; `+/−/·` glyphs carry chip state alongside colour).

---

## H. Open items / owner decisions

- **O1 (introduced).** ~~Divider normalization to `#16202b` on every rail block
  boundary~~ — **CONFIRMED (owner-approved 2026-07-23) and implemented.**
- **O2.** D14 numeric score — wire `suggestedCanonicalCardConfidence`; graceful
  "Suggested" fallback until the calibrated number is live (owner answer #1,
  already accepted; implemented — `ConfidenceElement.tsx` reads that field and
  falls back today since the backend doesn't populate it yet).
- **O3.** Preferred-sources backend (#353) contract sign-off (annex, §E.3) —
  scope of the account-tied "defaults" persist when it lands. Still open.
- **O4.** Group corner-tag copy (`✓` / `Alt` / `?`) — owner answer #6 accepted;
  implemented as shown in the mockup.
- **O5.** ~~`.btn-sm (all)` 14px/4px 8px (§A item 2 / §D.1's final row)~~ —
  **RESOLVED (owner ruling, 2026-07-23): the corrected mockup is binding for
  this row too.** Applied to the Filters disclosure toggle (`CompactButton`,
  its only rail control still overriding this away from Bootstrap's real
  `sm` metrics); every other `.btn-sm`-class rail control (Sources bulk/
  save-defaults, Slot Actions, Artist support, D14 `✗`) was already at
  14px/4px 8px via plain `<Button size="sm">` with no override at all.
- **O6 (new, this round — resolved same-round).** Source toggle
  pill-vs-switch shape (§A item 3) — **RESOLVED (owner ruling, 2026-07-23):
  the corrected mockup's rendered look is binding; the shared
  `react-bootstrap-toggle` library was restyled (scoped to a
  `rail-source-toggle` className) to match it** rather than replaced. See §A
  item 3.
- **O7 (new, this round — resolved same-round).** `AutofillCollapse` header
  background hex, `#4E5D6B` vs `#4e5d6c` (§A item 1 of the "What the two
  rejection defects were" table / §D.0) — **RESOLVED (owner ruling,
  2026-07-23): `#4E5D6B` is deliberate, distinct from the `#4e5d6c`
  `$secondary` token used elsewhere.** This REVERTS PR #400's own
  "correction" of the same value — see §D.0's own note.
- **O8 (new, this round — still open).** "Demoted body" 13px (§D.1) — a
  known gap surfaced by the machine-diff round's own measurement (Slot
  Actions' body font-size), deliberately NOT fixed this round pending a
  section-by-section measurement pass (see the note under §D.1's "Demoted
  body" row for the full reasoning — the mechanical fix would touch every
  demoted `RailSection`, most of which weren't measured).

---

## I. Verification

Playwright (`shot.js`, chromium) at **390px** and **1400px**; screenshots
inspected: `v-1400-auto-suggested` (desktop three-region), `v-1400-d14-confirmed`
/ `v-1400-d14-suggested` (both D14 states), `v-1400-sources`,
`v-1400-selectversion`, `v-1400-forced-phone`, `v-390-auto-top/-selectversion/ -bottom` (full phone-rail scroll), `v-390-confirmed-top`, `v-390-forced-desktop`.
One real bug caught + fixed (a backtick in an annotation broke the JS template
literal — the rail failed to render; now clean, zero page errors). One layout
fix (demo bar overlapped the appbar at narrow widths — stage top-padding now
tracks the bar's measured height). Verified: 38px toggles, one continuous grid
with corner tags + ribbon, unified filter block wraps at 390px, ✗-on-confirmed
de-emphasis, full phone reachability to the Slot Actions button stack.

Implementation round (Yori, 2026-07-23): `frontend/tests/DisplayLeftRailFidelity.spec.ts`
asserts the §J `Source: local` rows below via real `getComputedStyle` reads
(`toHaveCSS`); `frontend/tests/DisplayPage.spec.ts` covers the Sources
disclosure (collapsed summary count, expand/filter/bulk/invert/pin/#353 seam,
pin-chip-stays-visible-while-collapsed) and both D14 states (confirmed/
suggested, `✗` casting a real vote in both, including on an already-confirmed
printing). Screenshots for this round: see the task's own report for paths
under `frontend/test-results/`.

Machine-diff fix round (Yori, 2026-07-23): a throwaway Playwright/computed-style
diff (session tmp dir, not committed) measured the corrected mockup against the
O1-round build and found 63 property mismatches. Every unambiguous one (a
literal §D.1 value with no design judgment involved) is fixed and newly
asserted in `DisplayLeftRailFidelity.spec.ts`; the diff's own caveats section
identified several rows as fixture/measurement artifacts (not real defects —
e.g. the `RequestedPrintingBadge` wrapper-vs-badge mismeasurement, the
suggested-variant Frame chip, the tile/ghost-tile density-tier size
difference) and those were left alone. The three rows initially held back for
an owner call (`AutofillCollapse` header hex, Source toggle shape, `.btn-sm`
12px/14px) are now resolved per the owner's ruling — see §H O5–O7.

---

## J. Source map addendum (CSS-fidelity pass, originally 2026-07-23; O1 + machine-diff rounds)

Why this exists: PR #352 shipped several rows as "done" in the spec's own prose
while the actual CSS still fell through to a Bootstrap/theme default — then had
to separately fix its own regression in a follow-up commit ("Fix left-rail CSS
fidelity regressions vs SPEC-display-left-rail.md"). This table traces where
every §D.0/§D.1 binding value actually resolves from today, so a future edit
knows which values are safe to touch locally and which ones are quietly relying
on cascade order. `frontend/tests/DisplayLeftRailFidelity.spec.ts` asserts the
`Source: local` rows below via real `getComputedStyle` reads (`toHaveCSS`) —
keep this table and that spec in lockstep.

| Spec value (§/row)                                                                                                                                                                                         | Current source                                                                                                                                                                                                                                                                                                                                                                                                                            | Risk                                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.rail-head` padding `8px 10px` (§D.1)                                                                                                                                                                     | Inline style, `RailHeader` (`DisplayPage.tsx`)                                                                                                                                                                                                                                                                                                                                                                                            | Local — safe                                                                                                                                                                                                                                                                                                                        |
| `.rail-head` border-bottom `#16202b` (§A item 1/§D.1, O1)                                                                                                                                                  | **O1 fix (this round).** Was the plain Bootstrap `.border-bottom` utility (ambiguous `--bs-border-color`) on `RailHeader`'s own className; now `RailRoot`'s own `.rail-head{border-bottom:1px solid #16202b}` rule (`DisplayPage.tsx`)                                                                                                                                                                                                    | Was global/ambiguous, now local explicit — fixed                                                                                                                                                                                                                                                                                    |
| `.artist-line` padding `8px 10px` (§D.1)                                                                                                                                                                   | Inline style, `PromotedZone` (`DisplayPage.tsx`)                                                                                                                                                                                                                                                                                                                                                                                          | Local — safe                                                                                                                                                                                                                                                                                                                        |
| `.artist-line` background (§D.0 `$dark`/`$input-bg`)                                                                                                                                                       | `RailRoot` styled-component rule (Emotion-scoped, component-local CSS-in-JS)                                                                                                                                                                                                                                                                                                                                                              | Local — safe (scoped selector, not a global rule)                                                                                                                                                                                                                                                                                   |
| `.artist-line` border-bottom `#16202b` (§A item 1/§D.1, O1)                                                                                                                                                | **O1 fix (this round).** Same pattern as `.rail-head` above; `RailRoot`'s own `.artist-line{border-bottom:1px solid #16202b}` rule                                                                                                                                                                                                                                                                                                        | Was global/ambiguous, now local explicit — fixed                                                                                                                                                                                                                                                                                    |
| D14 `.d14` band margin/padding/background/border-bottom (§D.1)                                                                                                                                             | `RailRoot` styled-component rules, consumed by `ConfidenceElement.tsx`'s own markup                                                                                                                                                                                                                                                                                                                                                       | Local — safe, BUT literal hex (`#2b3e50`/`#16202b`), not var-linked — see "accepted trade-off" note below                                                                                                                                                                                                                           |
| `.sources` (accordion outer wrapper) border-bottom `#16202b` (§A item 1/§D.1, O1)                                                                                                                          | **O1 fix (this round).** Was the plain Bootstrap `.border-bottom` utility on `SourcesAccordion.tsx`'s own outer `<div className="sources">`; now `RailRoot`'s own `.sources{border-bottom:1px solid #16202b}` rule (a descendant selector — `SourcesAccordion` is rendered inside `RailRoot`'s subtree even though it's defined in a different file)                                                                                      | Was global/ambiguous, now local explicit — fixed                                                                                                                                                                                                                                                                                    |
| Select Version wrapper padding `8px 10px` (§D.1)                                                                                                                                                           | Inline style, `Rail()` (`DisplayPage.tsx`)                                                                                                                                                                                                                                                                                                                                                                                                | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Select Version wrapper border-bottom `#16202b` (§A item 1/§D.1, O1)                                                                                                                                        | **O1 fix (this round) — new, no prior boundary existed.** `RailRoot`'s own `.select-version-wrapper{border-bottom:1px solid #16202b}` rule, keyed off a new `select-version-wrapper` className added to the wrapper `<div>` (`Rail()`, `DisplayPage.tsx`)                                                                                                                                                                                 | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Unified filter fieldset padding `6px 8px` / `margin-bottom:6px` (§D.1)                                                                                                                                     | Inline style, `SelectVersionResults.tsx` fieldset                                                                                                                                                                                                                                                                                                                                                                                         | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Unified filter fieldset border `#16202b` (§A item 1/§D.1, O1)                                                                                                                                              | **O1 fix (this round).** Was inline `rgba(0,0,0,.22)`; now inline `1px solid #16202b`, `SelectVersionResults.tsx`'s `.ufilter` fieldset style                                                                                                                                                                                                                                                                                             | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Unified filter internal Frame↔Treatment divider `#16202b` (§D.1, O1)                                                                                                                                       | **O1 fix (this round).** Was `styled.span` with `background: rgba(0,0,0,.22)`; now `background: #16202b` (`UnifiedFilterDivider`, `SelectVersionResults.tsx`)                                                                                                                                                                                                                                                                             | Local — safe                                                                                                                                                                                                                                                                                                                        |
| `.vgrid` continuous grid `gap:6px` (§D.1/§F)                                                                                                                                                               | Inline style, `SelectVersionResults.tsx`                                                                                                                                                                                                                                                                                                                                                                                                  | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Frame+Treatment shared row `gap:6px` (§D)                                                                                                                                                                  | Inline style, `SelectVersionResults.tsx`                                                                                                                                                                                                                                                                                                                                                                                                  | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Filters toggle font-size `14px`/padding `4px 8px` (§D.1's `.btn-sm` row — §A item 2/§H O5)                                                                                                                 | `styled(Button)` (`CompactButton`, `SelectVersionResults.tsx`) — its ONE call site, so component-scoped by construction                                                                                                                                                                                                                                                                                                                   | **Machine-diff fix round.** Was `0.75rem`/`0.2rem 0.5rem`; now the spec's own literal `.btn-sm (all)` value, resolved per owner ruling (§H O5) — local, safe                                                                                                                                                                        |
| Slot Actions button stack `gap:6px` (§D.1)                                                                                                                                                                 | Inline style, `SlotActionsSection.tsx`                                                                                                                                                                                                                                                                                                                                                                                                    | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Sources bulk-action row `gap:6px`/`margin-bottom:6px` (§D.1/§E)                                                                                                                                            | Inline style, `SourcesAccordion.tsx`                                                                                                                                                                                                                                                                                                                                                                                                      | Local — safe                                                                                                                                                                                                                                                                                                                        |
| Sources list surface border/background (§D.1/§D.0 raised token)                                                                                                                                            | Inline style, `SourcesAccordion.tsx`                                                                                                                                                                                                                                                                                                                                                                                                      | Local — safe                                                                                                                                                                                                                                                                                                                        |
| **AutofillCollapse header padding `7px 10px` (§D.1)**                                                                                                                                                      | Additive, optional `headerPadding?: string` prop on `AutofillCollapse.tsx` itself, passed at each rail call site (`RailSection`, `SourcesAccordion`) — the value travels with the component invocation instead of being injected from an ancestor. Every other `AutofillCollapse` caller (`CardDetailedViewBody`, `PDFGenerator`, `JumpToVersion`, `CardResultSet`, `GridSelectorFilters`) omits the prop and is byte-for-byte unchanged. | Local — safe                                                                                                                                                                                                                                                                                                                        |
| AutofillCollapse header background `#4E5D6B` (§D.0 — deliberate, distinct from `$secondary`)                                                                                                               | `AutofillCollapse.tsx` inline style — its own comment at this line carries the "do not fix this back" note                                                                                                                                                                                                                                                                                                                                | **REVERTED (owner ruling, 2026-07-23; §H O7).** PR #400 "corrected" this to `#4e5d6c` (`$secondary`), treating the 1-hex-digit gap as a typo; the corrected mockup's own live DOM proves `#4E5D6B` is the deliberate, binding value for this token specifically — local literal, correct, still not var-linked (see trade-off note) |
| `.rail-head .slot` font-size `14px` / `.rail-head .name` font-size `15px`+`margin-top:1px` (§D.1)                                                                                                          | Inline styles on the exact two nodes, `RailHeader` (`DisplayPage.tsx`)                                                                                                                                                                                                                                                                                                                                                                    | **Machine-diff fix round.** Neither had a font-size rule at all before, so both fell through to the Bootstrap body default (16px) — component-scoped, not a `.rail-head .slot`/`.rail-head .name` RailRoot selector (#400 rule: `.slot`/`.name` are bare, reusable classnames)                                                      |
| `.artist-line` font-size `13px` (§D.1)                                                                                                                                                                     | Inline style, `PromotedZone` (`DisplayPage.tsx`)                                                                                                                                                                                                                                                                                                                                                                                          | **Machine-diff fix round.** Was the Bootstrap `small` utility (0.875em -> 14px off a 16px parent) — close but not the spec's own exact literal; replaced with an explicit inline value                                                                                                                                              |
| `.select-version-heading` font-size `14px` (§D.1)                                                                                                                                                          | `RailRoot` styled-component rule, extending the existing selector (`DisplayPage.tsx`)                                                                                                                                                                                                                                                                                                                                                     | **Machine-diff fix round.** Had margin/padding/font-weight already but no font-size rule; this bespoke, single-use classname isn't the kind of sitewide-clobber risk the #400 rule targets                                                                                                                                          |
| Sources filter input font-size `14px`/padding `6px 10px` (§D.1)                                                                                                                                            | Inline style on the exact `Form.Control`, `SourcesAccordion.tsx`                                                                                                                                                                                                                                                                                                                                                                          | **Machine-diff fix round.** Was Bootstrap's stock `.form-control` (16px/`.375rem .75rem`=6px 12px) — fixed inline (component-scoped) rather than a `.form-control` RailRoot selector, which WOULD be the sitewide-clobber pattern #400 retired for `.card-header`                                                                   |
| Source row border-bottom `rgba(0,0,0,.22)` (§D.1)                                                                                                                                                          | Inline style on each row, `SourcesAccordion.tsx`                                                                                                                                                                                                                                                                                                                                                                                          | **Machine-diff fix round.** Was the plain Bootstrap `.border-bottom` utility, resolving to the theme's ambiguous `--bs-border-color` (`#ced4da`) — not previously caught by O1's own named list (`.rail-head`/`.artist-line`/`.sources` only)                                                                                       |
| Source toggle restyle — two-cell segmented look, on `#df6919`/`#fff`, off `#4e5d6c`/`#8fa0b0`, `#6b7d8e` frame border (§D.1, §A item 3, §H O6)                                                             | `RailRoot`'s own `.rail-source-toggle`/`.toggle-on`/`.toggle-off`/`.toggle-group`/`.toggle-handle` rules (`DisplayPage.tsx`), scoped via a `className="rail-source-toggle"` passed only by `SourcesAccordion.tsx`'s Toggle                                                                                                                                                                                                                | **Machine-diff fix round + owner ruling.** Overrides `react-bootstrap-toggle`'s own stock sliding/`overflow:hidden` CSS to a static flex layout — scoped so every other mount of the shared library (≈10 other call sites sitewide) is unaffected                                                                                   |
| Tile corner tag font-size `7px`, alpha `.92` (§D.1)                                                                                                                                                        | `styled.span` (`CornerTag`) + its colour map (`CORNER_TAG_COLORS`), `SelectVersionResults.tsx`                                                                                                                                                                                                                                                                                                                                            | **Machine-diff fix round.** Was `0.5rem`(8px)/alpha `.9` — literal value correction, no design judgment                                                                                                                                                                                                                             |
| Ghost "+N" tile padding `0` (§D.1)                                                                                                                                                                         | `styled.button` (`GhostTile`), `SelectVersionResults.tsx`                                                                                                                                                                                                                                                                                                                                                                                 | **Machine-diff fix round.** A real `<button>` (buttons-look-like-buttons audit) carries the browser's own UA-stylesheet button padding unless reset — the mockup's own demo used a plain span with no such default                                                                                                                  |
| `AutofillCollapse` header `border-light` Bootstrap utility (no spec anywhere)                                                                                                                              | Removed entirely from `AutofillCollapse.tsx`'s `Card.Header` className                                                                                                                                                                                                                                                                                                                                                                    | **Machine-diff fix round.** Was tinting the header's own border `$light`/`#abb6c2` (pale line on the dark rail) — a stray utility, not a deliberate token anywhere; removed at the shared component itself. What remains is Bootstrap Card's own stock themed border, not independently pinned to a literal value here              |
| AutofillCollapse body gutter (`pad={2}` inside react-bootstrap `Container`)                                                                                                                                | `Container`'s `--bs-gutter-x` (Bootstrap global grid variable) + Bootstrap's `p-2` utility class                                                                                                                                                                                                                                                                                                                                          | **Judgment item, not re-verified this pass** — still resolves through Bootstrap's global gutter variable, so a future `--bs-gutter-x` theme edit could reintroduce a double-gutter without any local override to catch it                                                                                                           |
| `$body-bg`, card/offcanvas bg, `$dark`/`$input-bg`, `$body-color`, `$light`, `$primary`, `$success`, `$danger`, `$warning`, `$info`, `$input-border-color`, `border-radius:0`, font family (§D.0, general) | bootswatch/superhero SCSS variables + `styles.scss`'s #302 overrides, consumed via Bootstrap variant classes (`btn-outline-light`, `text-success`, etc.) or component defaults (Card bg, global border-radius)                                                                                                                                                                                                                            | **Intentionally global — correct.** These are meant to track the sitewide theme; consuming them through Bootstrap's own variant/class system is the right pattern, not a bug.                                                                                                                                                       |

**Accepted trade-off (not fixed this pass):** the D14 band's own CSS
(`.d14`/`.seticon`/`.score`/`.statepill` in `RailRoot`) hardcodes theme colors
as literal hex rather than CSS custom properties or SCSS variables — this is
the spec's own §D.0 instruction ("extracted, not approximated" — literal
values, not variables). It's immune to Bootstrap override (nothing in
Bootstrap/bootswatch targets `.d14`/`.seticon`), but it won't auto-track a
future edit to the underlying `styles.scss`/bootswatch tokens the way a
`btn-outline-*` class would — a different risk axis (manual literal drift
over time) than the Bootstrap-clobber pattern the O1 fixes above address.
Threading real CSS custom properties through the Emotion template is a larger
refactor, out of scope for this source-map/trivial-fix pass. The same
trade-off now also covers the O1-normalized `#16202b` literals themselves —
they're deliberately hardcoded, not var-linked, same rationale.
