```
TASK: Proposal H — unified display page, design doc + visual mockups
(survey + design + HOLD, zero feature code). Branch:
claude/proposal-h-display-design-04bam2. PR: #84 (draft, HOLD) —
https://github.com/ProxyPrints/ProxyPrints.github.io/pull/84.
Commit: 7140c97c.

WHAT SHIPPED:
1. Surveyed the existing components the rail's instruments come from
   before designing anything: CardSlot.tsx, GridSelectorModal.tsx +
   GridSelectorFilters.tsx + JumpToVersion.tsx, PagePreview.tsx,
   layout.ts (computeLayout), PDFGenerator.tsx, PDF.tsx,
   DeckbuilderConfirmAffordance.tsx, AttributeChipPanel.tsx +
   attributeChips.ts, CardSlotMenuActions.ts, bleedNormalize.ts,
   schema_types.ts (degradedQueries), plus proposal-b's own status
   doc and docs/lessons.md's sticky/z-index entry. Every citation in
   the design doc's §1 traces to a specific file (and usually a line
   range) I actually read this session.
2. Wrote docs/proposals/proposal-h-unified-display-page.md: vision
   restated in our own words; grounding/prior-art section (§1);
   information architecture (§2); annotated layout for desktop 1920,
   laptop 1366, tablet 768-992, and mobile <768 (§3); five numbered
   interaction walkthroughs — deck-input landing, slot select,
   confirm flow, printing switch, export (§4); a component-mapping
   table (existing component -> new location -> change needed) (§5);
   a migration/sequencing plan in 4 steps (§6); and a 6-item Open
   Decisions list.
3. Built 5 static HTML+CSS mockups under
   docs/proposals/mockups/proposal-h/ (desktop.html, laptop.html,
   tablet.html, mobile.html, mobile-rail-open.html) plus a shared.css
   using the real Superhero palette values (#2B3E50/#4E5D6C/#EBEBEB/
   #DF691A/#5cb85c/#d9534f, border-radius 0) and 63:88 card-aspect
   gray placeholders. All 7 rail instruments are visibly arranged and
   labeled in every mockup that shows an open rail.
4. Wrote docs/proposals/mockups/proposal-h/README.md linking all 5
   mockups + how to view them.
5. Updated docs/README.md's proposal status table with a Proposal H /
   HOLD row (in-place table edit, no dated section appended).
6. Committed all of the above to
   claude/proposal-h-display-design-04bam2, pushed, and opened PR #84
   as a DRAFT titled "HOLD: Proposal H — unified display page (design
   doc + mockups only)" against master.

DEVIATIONS from spec, each with reasoning:
1. **Bleed-override control corrected against live docs, not built
   as literally briefed.** The brief described the per-card bleed
   override (Auto/Force bleed/Force trimmed) as an existing,
   localStorage-persisted instrument. Reading
   docs/proposals/proposal-b-bleed-normalization.md directly showed
   this is wrong on two counts: the UI + persistence are explicitly
   listed as NOT YET BUILT (only resolveBleedPlan's algorithm exists
   today), and the owner has already decided persistence will go to
   projectSlice, not localStorage, once it ships. The design doc's
   §1 and §5 document this correction explicitly and assign the rail
   slot as blocked on Proposal B PR-2, rather than silently
   preserving the brief's inaccurate premise.
2. **Artist line + support link is new UI, not a restyle.** Grepped
   the whole frontend for "mtgartistconnection"/"Art by" and found no
   existing artist-line-with-outbound-link component. Documented in
   §5 as new presentational wiring over already-available artist
   metadata (e.g. ArtistVotePicker.tsx's own artist-name handling),
   not a relocation of an existing instrument.
3. **Tablet mockup shows two states in one file (closed default +
   open drawer)** rather than only the open state, so the off-canvas
   drawer's *entrance* behavior (edge handle, dimmed backdrop) is
   documented visually, not just its content.
4. **Report relay branch is a second, separate branch**
   (claude/proposal-h-relay-04bam2, forked from origin/master, not
   from the feature branch) per docs/lessons.md's branch-collision
   lesson and the bare-`report-relay`-is-retired convention — kept
   fully separate from the feature branch/PR so this report's commit
   never touches PR #84's diff.
5. Everything else matches the brief as given.

VERIFICATION:
- Grepped every new committed file (design doc, all 5 mockups,
  README, this report, and the PR body I opened) case-insensitively
  for "proxxied", "moxfield", "archidekt" — zero hits in every file
  this task authored. (A broader repo-wide grep turned up unrelated,
  pre-existing hits — "Moxfield" as a legitimately-named external
  deck-import source in docs/infrastructure.md and older report
  files, and "Proxxied" in the pre-existing proposal-b/proposal-g
  docs from before this task — none of those are files this task
  touched, and none were edited.)
- Rendered all 5 mockup HTML files with the environment's
  pre-installed headless Chromium
  (executablePath: /opt/pw-browsers/chromium, via a scratch
  playwright-core install since frontend/node_modules isn't
  installed in this session) at their target viewport sizes and
  visually confirmed: the sheet renders as a real 4x2 grid at 63:88
  card aspect, the selected-slot outline shows, all 7 rail
  instruments render with correct labels/content in desktop/laptop/
  tablet-open/mobile-rail-open, and the tablet closed state shows
  only the edge handle with no rail content. Screenshots were
  scratch-only (not committed) — the mockups are the deliverable,
  not the screenshots taken to check them.
- Confirmed the "default 4x2" grid claim algebraically against
  layout.ts's real computeLayout() math (A4 landscape, 5mm margins,
  both 0mm and 3.175mm bleed both resolve to 4 columns x 2 rows) —
  documented inline in the design doc's §1 rather than asserted
  without checking.
- Did NOT run the frontend's own lint/test suite — this PR touches
  zero application code (docs + hand-written static HTML/CSS only,
  per the amendment's explicit allowance for mockups), so there is
  nothing in frontend/src for those to check against.

OPEN ITEMS / DECISIONS NEEDED (mirrors the design doc's own Open
Decisions list — full detail there):
1. New route's URL/name (`/display` is a placeholder).
2. Exact toolbar-popover-collapse breakpoint (between 1366 and 992
   width) isn't pinned to a specific value.
3. Tablet drawer's first-visit default (auto-open once vs. always
   start closed) — no usage data exists to decide from.
4. Multi-select/bulk-operation mapping onto a per-page sheet (today's
   editor grid supports shift-click/double-click bulk selection
   across the whole deck at once; this design's flows only cover
   single-slot select).
5. Idle-rail and tablet-handle copy is placeholder text, not
   reviewed.
6. Whether the sheet needs its own zoom control at narrower rail
   widths (laptop) — flagged as a possible follow-up, not designed.

LIVE STATE:
- PR #84 is open, DRAFT, titled with a HOLD prefix, against
  ProxyPrints/ProxyPrints.github.io master. No CI/merge action taken
  or requested.
- Feature branch claude/proposal-h-display-design-04bam2 is pushed
  and up to date with commit 7140c97c (the only commit this task
  made there).
- This report is being committed to a separate relay branch,
  claude/proposal-h-relay-04bam2 (forked from origin/master), which
  will also be pushed and left open for the owner to merge or discard
  — it carries no code, only this one report file.
- No feature build has started. No flag, no route, no component
  changes exist anywhere outside docs/.
```
