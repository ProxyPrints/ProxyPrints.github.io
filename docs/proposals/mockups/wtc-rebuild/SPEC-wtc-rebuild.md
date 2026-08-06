# What's That Card? (/whatsthat) — rebuild spec (BINDING)

> Durable copy, recovered 2026-07-24 from session tmp storage (same
> durability convention as [`../../../reference/funnel-spec.md`](../../../reference/funnel-spec.md)) —
> this is the owner-approved BINDING spec that committed code comments
> (`ChipCard.tsx`, `WhatsThatWords.tsx`, `cardPanel.tsx`) cite by filename
> as their authority. Content below is verbatim from the 2026-07-24
> original; the per-viewport screenshot PNGs the original mentions were
> not carried over in this durability pass (bulk verification artifacts —
> the spec and its self-contained mockup HTML stand alone).

Designer: Quorra · 2026-07-24 · read-only vs repo
Companion mockup: `wtc-mockup.html` (self-contained) + PNGs (this dir)
Grounding: implementation brief (`a4c9c7035834dad69`) + data brief (`a42091a50f00d5417`)

Binding status (owner standing, 2026-07-23): the CSS token values below are
BINDING. A visual regression against `wtc-mockup.html` is a defect, not a nuance.
Every element on the affected page carries a sizing/coloring/spacing row.

**AMENDMENTS — owner rulings closing the three "Owner questions" at the bottom
of this spec (2026-07-24, relayed via the orchestrator ahead of implementation,
PR #446):**

1. **Owner Q1 (starburst burst)** — RETIRED. `BurstSvg`'s explosion animation is
   dropped entirely; the calmer `--wtc-field` + `--wtc-reveal-glow` treatment
   (WD5's own default) carries the reveal moment instead. The reveal reads
   through the mystery-card flip only — no separate burst animation.
2. **Owner Q2 (reward surface)** — KEPT, quiet. The "N tagged this session"
   count stays (WD6's own default) — volume-rewarding, direction-neutral (see
   ANNEX A's soundness note); no streak/score/confetti added on top of it.
3. **Owner Q3 (subject prominence on phone)** — ACCEPTED as specified (WD3).
   The subject compacts to ~132px horizontal below the hero's own 560px
   `@container` fold point so the answer stays reachable near the top on a
   phone; the open-ended shape (d) is the one shape that visually expands
   (dashed "tricky one" framing) rather than compacting further, since it
   needs more room for its own hint copy.

These three rulings resolve every open item this spec's "OWNER QUESTIONS"
section (bottom of this file) raised; nothing in this spec is still pending an
owner call as of this amendment. See PR #446's own body for the
section-by-section implementation mapping.

---

**AMENDMENTS — 2026-08-05, closing live-state issues found three days after
PR #446 shipped:**

1. **A1: Container-first policy reaffirmed (WD1).** The policy stated at §3 lines
   185–190 — components style against their CONTAINER (`@container`), layout folds
   continuously, no viewport sizing — remains binding and is WTC's first consumer.
   No amendment to the policy itself. It is recorded as binding rather than proposed
   because it already governs shipped code: describing a rule the implementation
   follows as a proposal misstates what the code does.

2. **A2: WD4 amended — reference image pinned within container, not viewport
   (§3 "Page scroll model").** WD4 currently retires sticky/bounded-height positioning
   in favour of "an ordinary scrolling document," relying on WD3's subject-compaction
   to keep the confirm hero reachable (lines 213–219). That is not sufficient: the
   reference image must remain visible at all times, at every viewport, because it is
   the subject the question is about — a reader who has scrolled it out of view cannot
   answer without scrolling back. The reconciliation:
   the reference image is PINNED WITHIN ITS CONTAINER, not viewport-sticky. The
   page remains an ordinary scrolling document (WD4's rejection of viewport-coupled
   positioning stands), but the image is held fixed within its own `@container hero`
   ancestor by `position: sticky` applied to SubjectCardBox or Subject, scoped to
   that container only — not the page viewport. This satisfies persistent visibility
   while keeping the container-first policy (A1) intact. Future readers: viewport-sticky
   was and remains rejected because it couples component layout to page-level scroll state,
   violating the container-first principle; container-pinning achieves the same UX goal
   without that coupling.

3. **A3: §1c binding table confirmed — no amendment needed.** Issue #708 reported the
   reference image's title overlay (SubjectArtTitle, gradient + text) as blocking the
   bottom corner, which appeared to conflict with the binding table. On re-examination
   the gradient is not the defect. The actual symptom is #705's hover-grow clipping
   (cards render in boxes with `overflow: hidden`, and the image scales up 1.6× on hover,
   so the clipping crops the edges). The binding table stands. A future note on the
   interaction between hover-scale transforms and container overflow may be useful; the
   table itself needs no amendment.

4. **A4: WD6 amended — AttributeChipPanel shown automatically by question type (§6
   "Features-accounted checklist").** WD6 currently carries AttributeChipPanel as
   Level-2 disclosure, opt-in behind a toggle (line 281, checkbox item). That is
   superseded: the chip panel is SHOWN AUTOMATICALLY based on the TYPE OF QUESTION being
   asked, not behind a manual toggle. A panel that must be opened before it can help is
   one most people never open, and which chips are relevant is already determined by the
   question being asked — so the disclosure step costs reach without adding information. Hard constraint couples to A2: the chip panel must
   NEVER occlude or hide the reference image — the pinning mechanism (A2) and the panel's
   visibility/placement must be co-designed to respect this.

5. **A5: Annex A amended — served-mix logging seam retired (§7).** Annex A (lines 315–334)
   calls for logging served-mix composition per session so a future audit could correlate
   click-latency / agreement-rate against easy-question exposure. The seam is RETIRED.
   Difficulty is derived from stored vote state under A6, so the logging would record
   nothing the data does not already carry, and user behaviour is not tracked beyond what
   a feature strictly requires. The Annex A text is retained rather than deleted so a
   future reader sees the reasoning rather than a gap.

6. **A6: Difficulty-lane model recorded (new § before Annex A).** Question difficulty
   is derived from DATA STATE, never from user profiling or behavioural tracking:

   - **easy**: an uncontested machine vote exists; the user confirms it.
   - **medium**: competing votes exist; the user breaks the tie.
   - **hard**: no data exists; the user answers cold.
     Lanes ramp per session by default, with user override available. Note explicitly:
     this model was chosen partly BECAUSE it requires no telemetry (A5) — it reads entirely
     off existing vote state. Supporting fact: machine votes structurally CANNOT resolve a
     field alone (`vote_consensus.py`'s gate requires `has_human_backed`, and DEDUCTION/OCR/
     FEDERATED/IMPLICIT are all machine-derived), so every derived machine vote MANUFACTURES
     a confirmable question rather than removing the need to ask one. That is the premise
     the easy lane runs on. NOTE on consensus thresholds: the gate is 60% share
     (`PRINTING_TAG_MIN_SHARE = 0.6`) plus a 2-vote minimum — NOT 51%. The "51%" figure
     belongs to `question_feed.py`'s separate "≥51%-likely-resolve" SERVING policy. These
     are separate mechanisms with different thresholds.

7. **A7: Implementation state recorded (new note at end of §6).** This spec shipped
   via PR #446 (2026-07-24). PR #687 subsequently shipped direct-access Yes/No chips on
   the question feed. Epic #704 with children #705–#716 now tracks the open work against
   this surface (spacing, hover-zoom clipping, title overlay, MTGAC applet size, confirm
   button size, and reference-card visibility). Refer to the epic for current status
   rather than duplicating its contents here.

---

**AMENDMENTS — 2026-08-06, closing #705/#707/#710/#711 as one layout pass (implements A1/A2/A4
above rather than proposing anything new):**

8. **A8: A2's sticky mechanism, concretely.** `Subject` (QuestionFeed.tsx) carries
   `position: sticky; top: 16px` unconditionally — including inside the WD3-compacted
   horizontal strip below the hero's 560px fold, so "visible at every viewport" is genuinely
   universal, not a wide-container-only affordance. No `useViewportTier`/media-query gate: the
   rule is never conditional on viewport width, satisfying A1's container-first policy. The
   actual scrolling ancestor sticky resolves against is Layout.tsx's `ContentContainer`
   (`position: fixed; overflow-y: scroll`, top-offset by the real navbar height already) — not
   `document` — so no additional navbar-height accounting was needed in QuestionFeed.tsx itself.

9. **A9: Desktop horizontal space — the actual constraint was one level up.** WtcHero/WtcHead's
   own `max-width` (1180px, §1c) was never the binding constraint on desktop: the sitewide
   `ContentMaxWidth` (1200px, `Layout.tsx`) wraps every route in a `MaxWidthContainer` that
   capped this page just as tightly regardless of WtcHero's own value. `whatsthat.tsx` now
   passes `fullWidth` to `ProjectContainer` — the same escape hatch `/display` already uses for
   an identical problem (`Layout.tsx`'s own comment on `MaxWidthContainer`) — and WtcHero/WtcHead's
   `max-width` moves from 1180px to 1600px (superseding that one §1c row; every other binding
   value in the table is unchanged). This is a static value, not a viewport breakpoint or `vw`
   unit, so A1 stands: the hero still doesn't size itself against the viewport, it simply has
   more room to fold its existing `clamp()`/`auto-fill` primitives into on a wide screen.

10. **A10: WD6's ring-around-card composition retired for this page (supersedes the
    §4/§5 "shortlist container" and "AttributeChipPanel" rows' original composition, not
    listed as a change row there).** A4 makes the panel auto-visible far more often than its
    old opt-in toggle ever did, and `AttributeChipPanel`'s `ChipRing` reflows via `@media (min-width: 576px)` — a viewport query, not a container query — which inside the narrow
    (`clamp(240px,30cqi,340px)`) Subject column it used to render in would squeeze three chip
    groups into a box that never has room for them, at exactly the widths A4 now shows it by
    default. Resolution: the panel no longer shares a box with the card at all. It renders in
    QPanel instead (its own `cardSlot` prop is now optional; omitting it swaps `ChipRing` for a
    plain `FlatChipStack` — three stacked `ChipRow`s, no ring), which trivially satisfies A4's
    "never occlude the reference card" hard constraint by construction (different flex column
    from the now-pinned Subject, A2) rather than by geometry that has to keep working as chip
    counts change.

11. **A11: Chip collapse (#707b).** An implied-negative chip (§ "chip (tri-state)" row,
    `attributeChipRender.tsx`) collapses its label away instead of only dimming — the reserved
    "dead space" the owner reported. Its two state buttons (and their full 44px tap targets,
    including the existing tap-to-override-the-implied-state affordance) are unchanged; only
    the label text's box is removed.

12. **A12: Hover-zoom clipping (#705) — root cause was one level higher than the binding
    table's own rows.** `ZoomableThumbnail`/`ArtPlaceholder` (both unchanged) were never the
    defect; their two immediate ancestors on this page (`SuggestedThumb`, `CandidateButton`)
    each clip with `overflow: hidden` for the resting state's own rounded-corner look, which
    also clips the hover-scale. Both now add `&:hover { overflow: visible; }` — clipping stays
    for the resting state, releases for exactly the hover duration the zoom needs it to. No
    §1c row changes (radius/size/colour are untouched).

13. **A13: Yes button (#711).** Drops `.big` (17px/800-weight/oversized padding) from the
    Level 1 Yes button; keeps `.block` (full width). Reads at the same 15px/600-weight text as
    its ActionGrid siblings now — hierarchy comes from position (its own row, above the grid)
    and colour (`.primary`, orange) rather than from being a larger control.

---

**AMENDMENTS — 2026-08-06, closing #740/#741/#746 (subject-card presentation defects live on
this page after the 2026-08-06 layout pass above):**

14. **A14: A3 corrected — the title overlay was a real, separate defect (#741).** A3 concluded
    the gradient overlay was not the defect and attributed the reported symptom entirely to
    #705's hover-grow clipping. That conclusion doesn't hold: `SubjectArtTitle` was
    `position: absolute; left: 0; right: 0; bottom: 0` inside `SubjectArt`'s own box — its
    containing block is the art's own box, so it sat over the art's bottom edge unconditionally,
    with no hover state involved and no dependency on the clipping/overflow mechanism #705
    fixed. Live measurement confirmed the overlap directly (title top at the art box's own
    interior, not below it). `SubjectArtTitle` is now a normal-flow sibling below the art
    (`SubjectArtImage`, a new box that owns the art's own sizing/aspect-ratio so the title can
    never share its space) rather than an absolutely-positioned child of it — the "subject art
    title" row's colour cell changes from a gradient overlay to a solid bar (below, not on top
    of, the art) for the same reason a gradient fade only reads correctly against content it's
    laid over: `#fff` on `rgba(0, 0, 0, 0.72)` (previously `linear-gradient(transparent, rgba(0, 0, 0, .72))`) — the darkest stop of the old gradient, kept as a flat colour since
    there's no longer art underneath it to fade over. Size/spacing (font-size clamp, weight)
    is unchanged.

15. **A15: A13 superseded — `.block` dropped too (#740).** A13 kept `.block` on the Level 1 Yes
    button on the reasoning that font-size parity plus position/colour was enough for
    hierarchy. Live measurement after A13 shipped showed the button still ~2x its "Not sure"
    sibling's width (494px vs 243px at an 800px viewport) — `.block`'s `width: 100%` was still
    forcing it to span the full row. `.block` is now dropped; `.primary` (colour) is kept, since
    it's legitimate affordance for the primary action and the complaint was about size, not
    about the button being identifiable. Dropping the class alone wasn't sufficient either: the
    button's parent (`ActionStack`) is a `flex-direction: column` container, whose default
    `align-items: stretch` was independently forcing the button to the row's full width
    regardless of `.block`. `ActionStack` now opts its first child (the Yes button) out of that
    stretch via `align-self: flex-start`, while its second child (`ActionGrid`, needing the full
    row width to lay out its own three siblings) keeps the default. The button now sizes to its
    label like its siblings; hierarchy is position (its own row, above the grid) and colour only.

16. **A16: Candidate grid size + a second, non-card art frame (#746).** Two coupled changes to
    the "candidate grid"/"candidate tile" §1c rows, both scoped to Level 2's candidate tiles
    (not the subject art, which was already sized to the `.subject` column's own `clamp(240px, 30cqi, 340px)`):
    - **Size.** `CandidateGrid`'s `grid-template-columns` minmax floor/ceiling moves from
      `clamp(78px, 15cqi, 116px)` to `clamp(120px, 24cqi, 190px)` — the artwork is the subject
      of the question being asked, and a 78-116px tile didn't read that way. Fewer columns per
      row at a given container width is the accepted trade for legible art.
    - **Frame.** `ArtPlaceholder` (63/88, i.e. the full card's own ratio) was the one shared
      frame for every candidate tile, including illustration-group representative tiles, whose
      image is a Scryfall art crop — not card-shaped. A new `IllustrationArtPlaceholder`
      (identical in every other respect: same `MysteryCard`/`ZoomableThumbnail` composition,
      same `object-fit: cover` contract) uses a landscape ratio instead, measured from the
      actual crop region rather than assumed: MPCAutofill's `local_phash.ART_CROP_BOX` (the
      fractional box every art crop is harvested from) resolves to pixel regions of
      width:height ~= 584:444 across the golden-set fixtures
      (`MPCAutofill/cardpicker/golden_set.py`'s `art_crop_px` entries). Illustration-group
      tiles (`QuestionFeed.tsx`'s `renderCandidateTile`, called from the illustration-cluster
      branch) use this frame when the representative candidate carries an `artCropUrl`; every
      other candidate tile (ungrouped, or a cluster representative with no crop, falling back to
      its full scan) keeps `ArtPlaceholder`.
    - **Root cause note (applies to both frames, not just the new one).** Neither frame's own
      `aspect-ratio` was actually reaching the screen: `ZoomableThumbnail`, the `img`'s
      immediate wrapper, sized itself from its content (`position: relative`, no explicit
      size), and the `img` inside used `height: 100%` — a percentage height against an
      indeterminate ancestor computes to `auto` per the CSS box model, and an `auto`-sized
      replaced element with a known width falls back to its own intrinsic ratio. That
      intrinsic-ratio height then became `ZoomableThumbnail`'s own content height, which grew
      the frame past whatever `aspect-ratio` it declared, since the frame is deliberately
      `overflow: visible` (needed so `ZoomableThumbnail`'s hover-zoom, A12, isn't clipped).
      In effect, every candidate tile's rendered shape always followed whatever the loaded
      image's own ratio happened to be, silently overriding both frames' declared ratios — a
      real full-card scan already being close to 63/88 is why this was never visible for
      `ArtPlaceholder`. `ZoomableThumbnail` is now `position: absolute; inset: 0` instead, which
      removes it from the frame's in-flow content entirely, so the frame's own `aspect-ratio` is
      what actually renders regardless of the loaded image's own ratio.

D-number scope note: D-numbers are per-proposal in this repo (proposal-h owns
its own D1–D19; the old WTC round used W4–W7). The decisions below are the
**WTC-rebuild round's** ledger, numbered WD1.. to avoid collision with either.

---

## 0. Theme foundation — Tokyo-11 (palette 11 = "tokyoorange")

The page renders **native** on the ruled Tokyo-11 token layer (owner-ratified in
the theme-options round). Orange **#ff9e64** is the ACTION colour; purple
**#bb9af7** is the ACCENT / identity colour; Semi radius; strict-AAA policy
(Tokyo-11 clears 7:1 on body text 7.54 and on the primary button 8.40 as-is).

The page's prior bespoke identity is **killed**: gold `#f8d42b`/navy `#124063`
buttons (QuestionFeed styled overrides L133–248), starburst blue `#4d8ddf`
(starburstShape.ts / cardPanel MysteryCardFace), deep-blue field `#123a6b`
(whatsthat.tsx `HERO_FIELD_BLUE_DEEP`). The WTC personality is re-expressed
through the ruled accent (WD1).

---

## 1. TOKEN TABLE — I (inherited from Tokyo-11) / N (new, WTC-identity, derived)

### 1a. Core swap-surface (inherited verbatim — do not redefine on this page)

| token                   | value     | I/N |
| ----------------------- | --------- | --- |
| `--body`                | `#1a1b26` | I   |
| `--conf`                | `#222234` | I   |
| `--raised`              | `#24283b` | I   |
| `--panel`               | `#2f3549` | I   |
| `--divider`             | `#16161e` | I   |
| `--text`                | `#c0caf5` | I   |
| `--muted`               | `#8c94bf` | I   |
| `--primary` (action)    | `#ff9e64` | I   |
| `--accent` (identity)   | `#bb9af7` | I   |
| `--success`             | `#9ece6a` | I   |
| `--warning`             | `#e0af68` | I   |
| `--danger`              | `#f7768e` | I   |
| `--btn-ink` (derived)   | `#1a1b26` | I   |
| `--r-btn` / `--r-input` | `6px`     | I   |
| `--r-card`              | `8px`     | I   |
| `--r-pill`              | `10px`    | I   |

### 1b. WTC-identity tokens (N — token-DERIVED from --accent/--body/--conf)

These are the ONLY page-private tokens; each carries WTC identity deliberately
and derives from a ruled token (no invented colour). They re-express the three
retired bespoke elements.

| token                 | value                                                                                                                        | replaces                         | I/N |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | --- |
| `--wtc-field`         | `radial-gradient(125% 115% at 30% 34%, color-mix(in srgb, var(--accent) 15%, var(--body)) 0%, var(--body) 58%)`              | deep-blue field `#123a6b` radial | N   |
| `--wtc-mystery-face`  | `linear-gradient(158deg, color-mix(in srgb,var(--accent) 26%,var(--conf)), color-mix(in srgb,var(--accent) 8%,var(--conf)))` | MysteryCardFace `#4d8ddf`        | N   |
| `--wtc-mystery-glyph` | `var(--accent)`                                                                                                              | gold `?` mascot fill             | N   |
| `--wtc-reveal-glow`   | `color-mix(in srgb, var(--accent) 55%, transparent)`                                                                         | starburst blue/white burst       | N   |
| `--wtc-wordmark`      | `var(--accent)`                                                                                                              | gold/navy wordmark               | N   |

### 1c. Per-element binding table (sizing / coloring / spacing)

Every visible element on the affected page. Values are binding.

| element              | color                                                                                                                                   | size / spacing                                                                                                                                                | radius      |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| page field wrapper   | bg `--wtc-field`                                                                                                                        | pad `14px 16px 22px`                                                                                                                                          | —           |
| wordmark `h1`        | `--wtc-wordmark`; `?` span = `--primary`                                                                                                | `font-size:clamp(26px,4.4cqi,44px)`; weight 900; text-shadow `0 0 22px color-mix(accent 26%)`                                                                 | —           |
| wordmark sub         | `--muted`                                                                                                                               | `.34em` of wordmark; weight 600; mt 3px                                                                                                                       | —           |
| solved pill          | text `--muted`, count `--success`                                                                                                       | pad `5px 12px`; font 12px                                                                                                                                     | `--r-pill`  |
| solved dots          | filled `--success`, empty `--divider`                                                                                                   | 6px circles, gap 3px                                                                                                                                          | 50%         |
| hero container       | —                                                                                                                                       | `max-width:1180px`; flex-wrap; gap `clamp(12px,2.2cqi,22px)`                                                                                                  | —           |
| subject `.subject`   | —                                                                                                                                       | `flex:1 1 300px; max-width:clamp(240px,30cqi,340px)`                                                                                                          | —           |
| subject card         | bg `--raised`, border `--divider`                                                                                                       | —                                                                                                                                                             | `--r-card`  |
| subject art          | bright card-art (real image in app)                                                                                                     | `aspect-ratio:63/88`                                                                                                                                          | —           |
| subject art title    | `#fff` on `rgba(0,0,0,.72)` (A14 — flat bar below the art, superseding the overlay gradient)                                            | `font-size:clamp(13px,3.4cqi,17px)`; weight 700                                                                                                               | —           |
| subject caption      | `--muted` on `--conf`; glyph `--accent`                                                                                                 | pad `8px 11px`; font 12px                                                                                                                                     | —           |
| qhead prompt         | `--text`                                                                                                                                | `font-size:clamp(17px,3.4cqi,22px)`; weight 800                                                                                                               | —           |
| shapepill.easy       | ink `--btn-ink` on `--success`                                                                                                          | pad `3px 10px`; 11px; upper                                                                                                                                   | `--r-pill`  |
| shapepill.pick       | ink `--btn-ink` on `--accent`                                                                                                           | "                                                                                                                                                             | `--r-pill`  |
| shapepill.neg        | ink `--btn-ink` on `--danger`                                                                                                           | "                                                                                                                                                             | `--r-pill`  |
| shapepill.hard       | `--accent` on transparent, 1px dashed `--accent`                                                                                        | "                                                                                                                                                             | `--r-pill`  |
| qhint                | `--muted`                                                                                                                               | 13px                                                                                                                                                          | —           |
| `.btn` (base)        | —                                                                                                                                       | `min-height:44px`; font 15px/600; pad `6px 16px`; 1px border                                                                                                  | `--r-btn`   |
| `.btn.big`           | —                                                                                                                                       | font 17px/800; pad `10px 20px`                                                                                                                                | `--r-btn`   |
| `.btn-primary`       | `--btn-ink` on `--primary`                                                                                                              | —                                                                                                                                                             | `--r-btn`   |
| `.btn-secondary`     | `--text` on `--raised`, border `--divider`                                                                                              | —                                                                                                                                                             | `--r-btn`   |
| `.btn-accent`        | `--btn-ink` on `--accent`; 800                                                                                                          | —                                                                                                                                                             | `--r-btn`   |
| `.btn-ghost` (Skip)  | `--muted`, transparent                                                                                                                  | —                                                                                                                                                             | `--r-btn`   |
| `.btn-danger`        | `--danger`, 1px `--danger`, transparent                                                                                                 | —                                                                                                                                                             | `--r-btn`   |
| action stack/grid    | —                                                                                                                                       | stack gap 9px; grid `repeat(auto-fit,minmax(clamp(120px,34cqi,180px),1fr))` gap 9px                                                                           | —           |
| suggested card       | bg `--conf`, border `--divider`                                                                                                         | pad 11px; gap 13px                                                                                                                                            | `--r-card`  |
| suggested thumb      | card-art                                                                                                                                | `flex:0 0 clamp(70px,20cqi,104px)`; `aspect 63/88`                                                                                                            | 6px         |
| suggested name       | `--text`                                                                                                                                | `clamp(16px,3.2cqi,19px)`; 800                                                                                                                                | —           |
| suggested set        | `--muted` monospace                                                                                                                     | 13px                                                                                                                                                          | —           |
| confidence pill      | `--accent`, 1px `--accent`                                                                                                              | pad `2px 9px`; 11px/700; dot 7px                                                                                                                              | `--r-pill`  |
| landed feedback      | `--success` on `color-mix(success 12%)`, 1px `color-mix(success 45%)`                                                                   | pad `5px 12px`; 13px; mt 12px                                                                                                                                 | `--r-pill`  |
| candidate grid       | —                                                                                                                                       | `grid; gap clamp(7px,1.6cqi,11px); grid-template-columns:repeat(auto-fill,minmax(clamp(120px,24cqi,190px),1fr))` (A16, superseding `clamp(78px,15cqi,116px)`) | —           |
| candidate tile       | bg `--raised`, border `--divider`; `.sel` outline `2px --accent`                                                                        | art `aspect 63/88`; illustration-group representative tile (has an `artCropUrl`) uses `aspect 584/444` instead (A16)                                          | `--r-card`  |
| candidate caption    | name `--text` 700, set `--muted` monospace 10px                                                                                         | pad `5px 7px 6px`; 11px                                                                                                                                       | —           |
| negative wrapper     | 1px `--danger` on `color-mix(danger 8%,--conf)`                                                                                         | pad 13px                                                                                                                                                      | `--r-card`  |
| negative header      | `--danger`                                                                                                                              | `clamp(15px,3cqi,18px)`; 800                                                                                                                                  | —           |
| reason chip          | `--text`, 1px `--danger`; `×` mark `--danger`                                                                                           | `min-height:44px`; pad `6px 12px`; 14px                                                                                                                       | `--r-btn`   |
| reason-chip grid     | —                                                                                                                                       | `repeat(auto-fill,minmax(clamp(130px,40cqi,190px),1fr))` gap 8px                                                                                              | —           |
| open wrapper         | 1px dashed `--accent` on `color-mix(accent 6%,--conf)`                                                                                  | pad 14px                                                                                                                                                      | `--r-card`  |
| search field         | bg `--raised`, 1px `--divider`; input `--text`                                                                                          | height 46px; pad `0 12px`; gap 9px; font 15px                                                                                                                 | `--r-input` |
| open help links      | `--accent`, underline `color-mix(accent 45%)`                                                                                           | 13px; mt 11px                                                                                                                                                 | —           |
| picker button        | `--text` on `--raised`, 1px `--divider`; `.unknown` `--muted`                                                                           | `min-height:44px`; 14px                                                                                                                                       | `--r-btn`   |
| picker grid          | —                                                                                                                                       | `repeat(auto-fill,minmax(clamp(120px,34cqi,180px),1fr))` gap 8px                                                                                              | —           |
| tag `h6`             | `--text`, `<em>` = `--accent`                                                                                                           | `clamp(17px,3.4cqi,21px)`; 800                                                                                                                                | —           |
| group label          | `--muted` upper                                                                                                                         | 10px/700; mt 12px mb 5px                                                                                                                                      | —           |
| chip (tri-state)     | default `--text` 1px `--muted`; `.pos` `--accent` on `color-mix(accent 20%)`; `.neg` `--danger` on `color-mix(danger 16%)` line-through | `min-height:38px`; pad `4px 12px`; 13px                                                                                                                       | `--r-btn`   |
| toggle (independent) | default `--text` 1px `--muted`; `.on` `--accent` on `color-mix(accent 20%)`                                                             | `min-height:38px`; box 14px                                                                                                                                   | `--r-btn`   |
| mystery-mini face    | glyph `--wtc-mystery-glyph` on `--wtc-mystery-face`; glow `--wtc-reveal-glow`                                                           | 44×61px                                                                                                                                                       | 6px         |

---

## 2. QUESTION-SHAPE INVENTORY → interaction contract

All shapes live in ONE component tree (QuestionFeed.tsx); the served
`QuestionFeedItem.type` selects which renders. The contract is preserved EXACTLY.

| shape                        | serves (data brief supply)                         | question `type`                                          | preserved flow (file:line)                                                                                                                                                                                                                 | distinct-shape rationale                                                                                               |
| ---------------------------- | -------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| **a · Confirm** (1-tap hero) | 45,154 single-candidate                            | `confirm_suggestion` w/ `suggestedPrinting`              | Level 1 (QuestionFeed L12–13, L811): YES casts + `getAutoTagChips` auto-tags + advances; NOT SURE/NO → Level 2 (no vote); **singleton NO → isNoMatch + custom-art** (impl brief); SKIP → advance                                           | one big card + ONE orange primary; only shape with a reflexive path, paired with equal-weight "No, different printing" |
| **b · Shortlist** (pick one) | 1,156 multi + 54,797 ambiguous (serve-time narrow) | `identify_printing`                                      | Level 2 (L14–20): tap candidate → `APISubmitPrintingTag` + `getAutoTagChips`; None-of-these → `NoMatchReasonStrip`; no-re-presentation (`rejectedCandidateIds`)                                                                            | grid of neutral tiles, **NO primary** — a real pick required                                                           |
| **c · Quick-negative**       | 45,500 unknown-set/eliminated                      | `identify_printing` / `confirm_suggestion` negative exit | one-tap classified negative: `isNoMatch` + one of the 6 seeded reason tags (`NoMatchReasonStrip` L44–50: custom-art, altered-frame, upscaled, ai-art, no-collector-line, non-english)                                                      | danger-red framed, negative verb — visibly not a confirm                                                               |
| **d · Open-ended**           | smallest slice: cold-start / no-evidence 32,838    | `identify_printing` (no shortlist)                       | search/typeahead identify; "Mark unidentifiable" = `isNoMatch`; Skip                                                                                                                                                                       | dashed accent "tricky one", search field, **no button to reflex-tap**                                                  |
| **e1 · Artist**              | artist family (13 near, byproduct)                 | `artist_vote`                                            | `ArtistVotePicker` unforked (L183 `Form.Control` + candidate `Button` grid + "Unknown artist")                                                                                                                                             | autocomplete idiom, not a discrete pick set                                                                            |
| **e2 · Tag**                 | 51,163 Borderless (mostly byproduct)               | `tag_vote`                                               | `QueueTagQuestion` unforked (L88–110: Apply / Not applicable / Skip)                                                                                                                                                                       | single yes/no attribute question                                                                                       |
| **L3 · Follow-up**           | open exclusion groups only                         | any candidate-type post-pick                             | Level 3 (L22–29): tri-state chips (`level3ChipStates`) cast immediately; Confirm & continue / Skip; groups = `BORDER_COLOR_GROUP`/`FRAME_STYLE_GROUP` + independent toggles (Full Art/Borderless/Showcase/Extended) from attributeChips.ts | appears only after a pick; "one more thing" framing                                                                    |

Per-item state reset (preserved, L907–942): `chipStates`, `revealed`,
`filterExpanded`, `rejectedCandidateIds`, `followUp`, `rateLimited`,
`level3ChipStates` reset inside the fetch `.then()` (NOT a keyed useEffect) —
the stale-filter fix stays.

Rate-limit banner (preserved, L884, L1017): honest pause condition, re-themed to
`Alert` on tokens; unchanged behavior.

---

## 3. LAYOUT SPEC — container-first, one tree (retires the 768px dual layout)

**Policy (owner-ratified 2026-07-24, WTC = first consumer):** components style
against their CONTAINER (`@container`), not the viewport; the layout folds
continuously (flex-wrap + `clamp()` + auto-fill/minmax); viewport breakpoints are
reserved for STRUCTURAL reordering only. The three retired horizontal-scrollers
(`MobileButtonRow`, `MobileCandidateScroller`, `MobileChipRow`) and `HeroGrid`'s
768px `grid-template-areas` swap are the anti-pattern being deleted.

### The one hero container

`.wtc-hero { container-type: inline-size; container-name: hero; display:flex; flex-wrap:wrap; gap:clamp(12px,2.2cqi,22px) }` — `.subject` (`flex:1 1 300px`)
and `.qpanel` (`flex:2.2 1 440px`) wrap intrinsically. No media query drives the
subject↔question column split; flex-basis does.

### Continuous fold points (all container-query, no viewport sizing)

| trigger                             | change                                                                                   | why it's allowed                                                         |
| ----------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| hero wraps (basis math)             | subject column moves above qpanel                                                        | intrinsic flex-wrap, not a breakpoint                                    |
| `@container hero (max-width:560px)` | subject → **compact-horizontal** (132px art + caption beside), full width                | structural reorder of the subject card only; sizes stay `clamp()`-driven |
| `@container hero (max-width:380px)` | `.actgrid` → single column                                                               | container-driven, not viewport                                           |
| candidate grid                      | `repeat(auto-fill, minmax(clamp(78px,15cqi,116px),1fr))` folds 6→4→3→2 cols continuously | intrinsic grid; replaces the horizontal scroller                         |
| reason/picker/action grids          | `auto-fit minmax`                                                                        | intrinsic; replaces stacked/scroller variants                            |

### The ONE permitted viewport breakpoint (structural, never sizing)

`@media (max-width:520px) { .wtc-head { flex-direction:column } }` — reorders the
wordmark above the solved-pill on a narrow viewport. No dimension changes here.

### Page scroll model

`PageColumn`'s `height:calc(100dvh - navbar)` bounding and the `min-height:100%`
"portrait static top block" hack are **retired** (WD4). The page is an ordinary
scrolling document; the subject compaction (WD3) keeps the confirm hero reachable
near the top on a phone without a bounded-height budget. Verified: no-JS phone
render puts the "Yes" button at y=912 in a 2367px scrollable document.

### Type & spacing

All type is `clamp(min, Ncqi, max)` (container units) — see §1c. No fixed
per-breakpoint font sizes. The retired `5.5rem` hard-coded mobile tile width
(impl brief flag) is gone, replaced by the `minmax(clamp())` grid.

---

## 4. ELEMENT → react-bootstrap PRIMITIVE (no new dependencies)

Repurposes /editor's existing component family; no display-only UI forked; shared
components gain only additive, optional, behavior-preserving props.

| element                                               | primitive / shared component                          | change                                                                                                                             |
| ----------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Yes/Not sure/No/Skip; None-of-these; Confirm&continue | `ThumbButton` = `styled(Button)` (QuestionFeed L133+) | styled override **retokenized** (gold/navy → primary/secondary/ghost) — see §5                                                     |
| candidate tiles                                       | `CandidateButton` = `styled(Button)` (cardPanel L448) | reused; sizing via container grid, not fixed rem                                                                                   |
| subject card                                          | `CardPanel` / `StaticCardPanel` (cardPanel L167/202)  | reused; blue bg → token                                                                                                            |
| mystery reveal                                        | `MysteryCard` / `MysteryCardFace` (cardPanel L88)     | reused; `--wtc-mystery-*` tokens                                                                                                   |
| shortlist container                                   | **`CandidateGrid`** styled `div` (CSS auto-fill)      | NEW shared layout primitive replacing Bootstrap `Row/Col` (policy: auto-fit grids over per-feature folding). Not a new dependency. |
| confidence pill / "suggested" badge                   | react-bootstrap `Badge`                               | reused; `bg`/tokenized                                                                                                             |
| solved-count pill                                     | react-bootstrap `Badge` (pill)                        | additive, presentation-only                                                                                                        |
| quick-negative reason chips                           | `NoMatchReasonStrip` + its `ChipCard`/`Button`        | reused; tokenized danger frame                                                                                                     |
| open-ended + artist search                            | react-bootstrap `Form.Control`                        | reused (ArtistVotePicker already uses it, L183)                                                                                    |
| tag question                                          | `QueueTagQuestion` (`Button`)                         | reused unforked                                                                                                                    |
| follow-up tri-state chips + toggles                   | `ThumbChip` = `styled(Button)` (QuestionFeed L215+)   | reused; gold→accent tokens                                                                                                         |
| landed feedback / rate-limit                          | react-bootstrap `Alert`                               | reused; success/warning variants                                                                                                   |
| moderator switcher                                    | `Nav`/`Tab` (whatsthat.tsx L199)                      | unchanged                                                                                                                          |

Additive props needed (all optional, behavior-preserving):

- `CandidateGrid` — new styled div; no props beyond children.
- `MysteryCard` — no new prop; the face colour moves to a token so no API change.
- No shared component gains a required prop.

---

## 5. FILE-LEVEL CHANGE ROWS

| file                                                                                                    | change                                                                                                                                                                                                                                                                                                                                                                                                                                                            | preserves                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/styles/styles.scss`                                                                       | (separate track) Tokyo-11 token layer active — WTC assumes it. WTC adds the 5 `--wtc-*` tokens (§1b) scoped to the page root.                                                                                                                                                                                                                                                                                                                                     | —                                                                                                                                                                      |
| `pages/whatsthat.tsx`                                                                                   | Delete `HERO_FIELD_BLUE_DEEP` + blue radial `StarburstBackground` → `--wtc-field`. Delete `PageColumn` `100dvh` bound + `@media max-width:767.98px { min-height:100% }` (WD4). Retint PWA `theme-color` (L263) to `--body` `#1a1b26`. Keep `VisuallyHiddenHeading` `<h1>`.                                                                                                                                                                                        | moderator `Tab` branch; `NoBackendDefault`; `<Head>`/manifest                                                                                                          |
| `features/questionFeed/QuestionFeed.tsx`                                                                | Delete the 3 styled gold/navy overrides (L133–248) → token variants. Delete `HeroGrid` 768px `grid-template-areas` swap → one flex `.wtc-hero` `@container`. Delete `MobileButtonRow`/`MobileCandidateScroller`/`MobileChipRow` + `mobileScrollbarCSS` (L402) → `auto-fit` grids / flex-wrap. Delete `Level2NarrowGrid` narrow special-case (L659). Wordmark drops the `WideWordmark`/`NarrowWordmark` CSS-display fork → one `WhatsThatWords` at `clamp()` size. | Level 1/2/3 flow; `getAutoTagChips`; `rejectedCandidateIds`; per-item reset (`.then()`); no-re-presentation; rate-limit; all `data-card-*` attrs + `mpc:card-selected` |
| `features/printingTags/cardPanel.tsx`                                                                   | `MysteryCardFace` `STARBURST_OUTER_COLOR` → `--wtc-mystery-face`; `?` glyph fill → `--wtc-mystery-glyph`. `CardPanel`/`CandidateButton` inherit tokens. `revealAnimation` unchanged (already reduced-motion-gated).                                                                                                                                                                                                                                               | reveal timing; stacking-context; zoom-on-hover (`ZoomableThumbnail`)                                                                                                   |
| `features/printingTags/starburstShape.ts` + `BurstSvg`                                                  | Blue/white burst → accent-purple, OR retire in favour of `--wtc-reveal-glow` (WD5 — owner Q1).                                                                                                                                                                                                                                                                                                                                                                    | —                                                                                                                                                                      |
| `features/attributeVoting/*` (`ArtistVotePicker`, `QueueTagQuestion`, `NoMatchReasonStrip`, `ChipCard`) | No structural change; inherit tokens.                                                                                                                                                                                                                                                                                                                                                                                                                             | all vote-cast behavior                                                                                                                                                 |
| `features/attributeChips/attributeChips.ts`                                                             | No change (groups/labels reused as-is).                                                                                                                                                                                                                                                                                                                                                                                                                           | exclusion-group logic                                                                                                                                                  |

---

## 6. FEATURES-ACCOUNTED CHECKLIST (vs the impl brief's component map)

- [x] `confirm_suggestion` Level-1 hero (YES/NOT SURE/NO/SKIP) → shape **a**
- [x] Singleton "NO" → isNoMatch + custom-art → noted in shape **a** flow
- [x] `identify_printing` candidate grid (Level 2) → shape **b**
- [x] `getAutoTagChips` auto-cast on candidate pick → preserved (§2)
- [x] "None of these" → `NoMatchReasonStrip` (6 reason tags) → shape **c**
- [x] "Art matches, not official" one-tap (isNoMatch + custom-art) → shape **c** / **a**
- [x] Level 3 open-exclusion-group chips (tri-state) + independent toggles → shape **L3**
- [x] `AttributeChipPanel` shown automatically by question type (A4 amendment) → never occludes the reference image (couples to A2 pinning mechanism)
- [x] `artist_vote` → `ArtistVotePicker` → shape **e1**
- [x] `tag_vote` → `QueueTagQuestion` → shape **e2**
- [x] Moderation tab (gated) → `Nav`/`Tab`, unchanged
- [x] `MysteryCard` reveal + `?` mascot → re-themed (tokens), animation preserved
- [x] Wordmark (`WhatsThatWords`) → re-themed accent, single `clamp()` tree
- [x] Per-candidate `Spinner` on tap → preserved (impl brief flag: unchanged placement)
- [x] `data-card-*` attrs + `mpc:card-selected` event → preserved (card-dom-api.md)
- [x] Rate-limit banner → `Alert`, tokenized
- [x] No-re-presentation (`rejectedCandidateIds`) → preserved
- [x] Per-item state reset semantics → preserved
- [x] PWA manifest / installability → theme-color retint only
- [x] `APIRetractImplicitVote` (display funnel; not on this page) → untouched

Nothing from the component map is dropped. The three horizontal-scroll wrappers
are the only DELETIONS, and they are replaced (not removed) by intrinsic grids.

**Implementation state (A7 amendment).** This spec shipped via PR #446 (2026-07-24),
one day after it was written; its container-first structure and token layer remain live
in QuestionFeed.tsx. PR #687 subsequently shipped direct-access Yes/No chips on the
question feed (2026-07-29). Epic #704 with children #705–#716 now tracks the open work
against this surface: spacing/size tuning, hover-zoom clipping (#705), reference-card
visibility (#710, amended 2026-08-05), title-overlay interaction (#708, amended 2026-08-05),
MTGAC applet sizing, and confirm-button size. Refer to the epic for current status rather
than duplicating its contents here.

---

## 7. OWNER-DECISION LEDGER (WTC-rebuild round)

| #   | decision                                                                                                                                                                                         | basis                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| WD1 | WTC personality re-expressed through the ruled accent purple; bespoke gold/navy/starburst-blue/deep-blue-field identity killed                                                                   | dispatch ruling 2; theme-fidelity lesson                          |
| WD2 | Orange `--primary` reserved for the confirm/action colour; purple `--accent` carries identity (wordmark, mystery card, selection, confidence pill)                                               | Tokyo-11 palette-11 semantics                                     |
| WD3 | Subject reference card compacts to horizontal (132px) on `@container hero <560px` instead of a full-portrait static top block                                                                    | phone reachability without a bounded-height hack                  |
| WD4 | `PageColumn` 100dvh bounding + the `min-height:100%` portrait hack RETIRED; page is an ordinary scrolling document                                                                               | container-first policy retires the anti-pattern                   |
| WD5 | Reveal theatrics default to the subtle `--wtc-field` + `--wtc-reveal-glow`; the full `BurstSvg` starburst is proposed for retirement (see Owner Q1)                                              | soundness note (avoid gamified habituation) — owner call          |
| WD6 | Quiet "N tagged this session" affordance kept as the ONLY reward surface; no streak/score/confetti                                                                                               | mix soundness note (rewarding, not habituating) — owner call (Q2) |
| WD7 | Question shapes are visually differentiated (confirm=orange primary, shortlist=neutral grid, negative=danger frame, open=dashed "tricky") so reflexive confirmation does not bleed across shapes | dispatch ruling 4                                                 |
| WD8 | Candidate/reason/picker/action rows become `auto-fill minmax(clamp())` grids; the three horizontal scrollers + `Level2NarrowGrid` deleted                                                        | responsive policy (first consumer)                                |

---

## DIFFICULTY-LANE MODEL (derived from data state, requires no telemetry)

Question difficulty is derived from DATA STATE, never from user profiling or
behavioural tracking:

- **easy**: an uncontested machine vote exists; the user confirms it.
- **medium**: competing votes exist; the user breaks the tie.
- **hard**: no data exists; the user answers cold.

Lanes ramp per session by default, with user override available. This model was
chosen partly BECAUSE it requires no telemetry — it reads entirely off existing
vote state (and does so without any need for the retired served-mix logging seam
of Annex A). Machine votes structurally CANNOT resolve a field alone (vote_consensus.py's
gate requires `has_human_backed`, and DEDUCTION/OCR/FEDERATED/IMPLICIT are all
machine-derived), so every derived machine vote MANUFACTURES a confirmable question
rather than removing the need to ask one. That is the premise the easy lane runs on.

**Consensus thresholds — clarity.** The gate is 60% share (`PRINTING_TAG_MIN_SHARE = 0.6`)
plus a 2-vote minimum — NOT 51%. The "51%" figure belongs to `question_feed.py`'s
separate "≥51%-likely-resolve" SERVING policy. These are separate mechanisms with
different thresholds; do not confuse them.

---

## ANNEX A — served-mix logging seam (RETIRED 2026-08-05)

The ≥51% likely-resolve mix (46,310-card 1-click supply) is a **question_feed.py
selection-layer** concern only: it changes WHICH questions are served in what
proportion, and makes ZERO change to `vote_consensus.py` weights, MIN_VOTES/
MIN_SHARE, or the D1/D4 mechanisms (data-brief soundness note, binding).

UI implications actually built here:

- The feed FEELS rewarding via the confirm shape's one-tap land + the quiet
  "N tagged this session" affordance — **not** via any score/streak (WD6).
- Hard/open shapes (c/d) are visually distinct (WD7) so a run of easy confirms
  does not condition reflexive tapping into the harder shapes.

**Backend seam (RETIRED — see A5 amendment above).** The original spec called for
logging served-mix composition (ratio + family/reason per served question) per
session in `question_feed.py`, so a future audit could correlate click latency /
agreement-rate against a session's easy-question exposure (data brief, owner ask).
This logging seam is NOT BUILT. Reason: the difficulty-lane model (see new section
above) was chosen partly BECAUSE it requires no telemetry — it reads entirely off
existing vote state, making this audit seam unnecessary for the feature's soundness.
The ONLY channel the serving policy can touch soundness through is degraded human-vote
signal quality from habituation — never any weight/threshold/gate code path. Without
the habituation risk this seam was designed to monitor, the build item is retired.
This record stands so a future reader understands the decision.

## ANNEX B — survivor_pks / issue #433 dependency (shape b)

The shortlist shape assumes a machine-narrowed candidate list exists on the
served item. Per the data brief, `CardScanLog.survivor_pks` is **null for 100%**
of the 134,370 to-review cards (documented gap, `survivor_pks` docstring: "an
open item, not built in this change"). Two ways to satisfy the shape; the UI is
agnostic to which:

- (preferred) close #433 → persist `survivor_pks` at scan time; serve it on the
  `QuestionFeedItem`.
- (fallback) `question_feed.py` recomputes candidate-narrowing live at serve
  time (the ambiguous set is 54,797 cards; recompute cost is a backend concern).

Until one lands, shape **b** degrades to shape **d** (open-ended) for the
ambiguous population — the UI already carries both, so no design change is
needed to ship, only a served-`type` downgrade. Confirm shape **a** (45,154) and
the negatives (shape **c**, 45,500) do NOT depend on #433 and are shippable now.

## ANNEX C — reveal & progress animation (reduced-motion)

- **Mystery reveal** (`MysteryCardFace` `revealAnimation`, 0.8s ease-out): the
  purple "?" face fades to the scanned image on load. Already gated —
  `prefers-reduced-motion: reduce` skips the fade (and therefore its
  `onAnimationEnd`); the revealed image is shown statically. Preserved verbatim;
  only the face COLOUR moves to `--wtc-mystery-face`.
- **Confirm-lands feedback** (`.landed` Alert): a brief fade-in on a successful
  cast, then advance. Under reduced-motion: appears instantly, no transition.
  Quiet by design (WD6) — success-tinted pill, no motion beyond the fade, no
  sound, no confetti.
- **Reveal glow** (`--wtc-reveal-glow`): a static box-shadow on the mystery
  face; no animation, so no reduced-motion concern.
- **Solved affordance**: static count + filled dots; no motion.
- If `BurstSvg` is retained (Owner Q1), its existing 5-frame animation must gain
  a reduced-motion guard (it currently has none per the impl brief) — a
  prerequisite of keeping it.

---

## OWNER QUESTIONS (genuinely yours)

1. **Starburst burst** — retire the `BurstSvg` explosion entirely in favour of the
   calmer `--wtc-field` + reveal glow (WD5, aligns with the soundness note), or
   re-express it as an accent-purple burst for more "game feel" (needs a
   reduced-motion guard it lacks today)? Default in the mockup: retired.
2. **Reward surface** — keep the quiet "N tagged this session" count (mild
   positive feedback, supports "feel rewarding"), or drop even that to avoid any
   gamification per the data-brief habituation flag? Default: kept, quiet.
3. **Subject prominence on phone** — WD3 compacts the reference card to 132px on
   narrow containers so the answer stays reachable near the top (zoom-on-tap
   still available). Acceptable, or do you want the card to stay large and let
   the answer sit below the fold?
