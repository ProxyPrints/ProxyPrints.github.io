/**
 * Proposal H (docs/proposals/proposal-h-unified-display-page.md) — the unified display page's
 * shell: a top toolbar, a live print-sheet preview (reusing PagePreview/computeLayout from
 * Proposal A - see PagePreview.tsx), slot selection, and the rail's always-visible status header
 * + accordion (AutofillCollapse, per the owner's accordion amendment). Choose Image is wired to
 * the real candidate/version picker (originally Step 2 PR 2a's flat GridSelectorResults grid,
 * replaced by the unified Select Version section - issue #167, SelectVersionResults.tsx - see
 * SelectVersionSection below; still shares useGridSelectorSearch.ts's search/filter state machine
 * with GridSelectorModal.tsx's own unchanged modal variant). The always-visible header now
 * carries the real requested-printing badge (Step 2 PR 2b - degraded-style variant keyed off
 * EditorSearchResponse.degradedQueries, wired end to end through searchResultsSlice's
 * selectIsSearchQueryDegraded; later extracted into its own RequestedPrintingBadge.tsx component
 * - item (c) of the frontend-polish package - so CardSlot.tsx's editor slots could mount the
 * exact same badge, one component instead of two copies that could drift) and the real
 * DeckbuilderConfirmAffordance (same component CardSlot.tsx mounts, adapted only via its
 * onOpenGridSelector prop - the rail has no modal to open, so N expands the Choose Image section
 * instead; SelectVersionResults.tsx also reuses this same component verbatim for its own
 * suggested-printing confirm moment - see that file's own module comment). Left-panel
 * unification (issue #164) filled in every remaining rail section: Attributes
 * (AttributesSection.tsx - the same tap/vote-submission logic AttributeChipPanel.tsx uses via the
 * shared useTagVoting hook, rendered as a plain vertical stack instead of a ring around a card),
 * Print Options (PrintOptionsSection.tsx - the same per-card bleed override
 * projectSlice/PDF.tsx's isBleedNormalizationEligible already implement for the classic PDF tab's
 * Bleed Overrides panel), Artist (ArtistSection.tsx - inherits ArtistSupportLink directly, per
 * docs/features/artist-support-links.md's own anticipated follow-on), and Slot Actions
 * (SlotActionsSection.tsx - the same getCardSlotMenuActions list CardSlot.tsx's 3-dot dropdown/
 * context menu use, rendered as a plain action list rather than a dropdown overlay). Every rail
 * section is now real, not a stub - see docs/proposals/proposal-h-unified-display-page.md's own
 * status line for what's still not built (tablet/mobile interaction patterns and the switchover
 * step).
 *
 * Item 3 (owner's hands-on review, flat-scroll amendment) replaced the original one-page-at-a-
 * time pager with a continuous vertical stack of every sheet (`sheets`, derived from
 * displayPagination.ts's `paginateSlotsForDisplay`) - each sheet's PagePreview mounts only when
 * on/near screen via RenderIfVisible (components/RenderIfVisible.tsx, already proven in
 * CardResultSet.tsx), so a large deck never holds more real <img> elements in memory than what's
 * actually near the viewport. The toolbar's old prev/next pager is gone; what remains is a
 * passive "Sheet N of M" readout driven by its own, tighter-band IntersectionObserver (distinct
 * from RenderIfVisible's own broader mount/unmount one - see the two effects' own comments).
 *
 * Deliberately NOT built here (see the design doc + this task's relay reports for the full
 * reasoning): the tablet off-canvas drawer and mobile bottom-sheet overlay interaction patterns
 * (§3) - below `md` the rail stacks in plain document flow below the sheet, which is usable but
 * not yet the polished drawer/overlay the doc specifies; that's follow-up work, not silently
 * dropped. Front-only pagination (see displayPagination.ts's own module comment) - a Fronts/
 * Backs toggle reuses the existing frontsVisible view setting rather than PDFGenerator's
 * export-time front-then-distinct-back interleaving.
 *
 * Issue #166 (post-export contribution prompt) - after a genuinely successful "Generate PDF" or
 * "Save PDF to Google Drive", a dismissible prompt points the user at the existing "What's That
 * Card?" vote-queue funnel (docs/features/printing-tags.md), via
 * features/export/postExportContributionPrompt.ts + usePostExportContributionPrompt.ts's
 * success-detection and show-once-per-session logic. Originally mounted from BOTH this page's
 * own inline export (item 2, below) and PDFGenerator.tsx itself; issue #275 removed this page's
 * inline export entirely (see that issue's own module comment further down), so PDFGenerator.tsx
 * - now the sole place PDF generation happens, reached via the Print page (D10, pages/print.tsx)
 * - is this feature's only remaining mount.
 *
 * Issue #238 (deck-input landing, design doc §4.1) - the `isProjectEmpty` early return used to
 * render only a plain "head to /editor" link, meaning this page could never start a project
 * standalone. See DeckInputLanding below: the same plain ImportText/ImportURL/ImportXML/ImportCSV
 * components ProjectEditor.tsx's own AddCardsPanel mounts, reused (not forked) inline in place of
 * that link - once addMembers fires, isProjectEmpty flips false and this component re-renders
 * straight into the sheet+rail layout below on its own.
 *
 * Issue #239 (Search Settings toolbar parity, design doc §5's SearchSettings row) - the toolbar
 * previously had no way to reach precise/fuzzy search type, DPI/file-size filter ranges, or
 * source reordering/toggling at all on this page. SearchSettings.tsx (the same self-contained
 * trigger-button-plus-modal ProjectEditor.tsx already mounts) is relocated in, unmodified - same
 * Modal, same searchSettingsSlice read/write, same setLocalStorageSearchSettings persistence path.
 *
 * Issue #240 (Cardback toolbar parity, design doc §5's CommonCardback row) - the toolbar
 * previously had no way to reach the project-wide cardback picker at all on this page (only the
 * classic editor's own right panel could). CardbackToolbarButton (CommonCardback.tsx) is a new,
 * small button+modal pairing - reusing MemoizedCommonCardbackGridSelector's existing
 * GridSelectorModal verbatim - rather than mounting CommonCardback itself, since that component's
 * swatch/prev-next CardFooter chrome belongs to the editor's right panel, not a toolbar button.
 *
 * Issue #241 (Export ▾ toolbar parity, design doc §5's export-beyond-PDF row) - the last of the
 * three toolbar-parity findings from the same audit. DisplayExportMenu.tsx composes the same
 * unchanged ExportXML/ExportImages/ExportDecklist Dropdown.Items Export.tsx already mounts on the
 * classic editor's own "Download" dropdown - same hooks, same gating selectors. ExportPDF.tsx's
 * own item is deliberately excluded, since PDF generation itself lives on the Print page (D10,
 * pages/print.tsx) now, not this one - see issue #275's own module comment further down.
 *
 * Issue #266 (mobile responsive shell - docs/proposals' /display layout spec, owner-approved
 * 2026-07-21, §2/§4/§6 rows R1/R2/R4/R5/R6) replaced the single always-rendered `RailWrapper`
 * (static below md, sticky-in-place from md up) with the spec's real four-tier shell:
 *   - The sheet region now measures its own width via `ResizeObserver` (`sheetRenderWidthPx`)
 *     instead of a fixed constant, so `PagePreview`'s existing `maxWidthPx` prop fits the sheet to
 *     whatever width is actually available - phones get the WHOLE landscape page, scaled down,
 *     rather than a fixed-width sheet clipped by the viewport (the design doc's "only the middle
 *     cards visible" symptom, issue #266's own repro). No `PagePreview` changes - it already scales
 *     to any width.
 *   - Both rails are now ONE `Offcanvas` node each (`responsive="lg"` left, `responsive="xl"`
 *     right) - inline/sticky at their own breakpoint, a real dismissible drawer below it
 *     (`useViewportTier.ts` drives the left rail's phone-bottom-sheet vs. tablet-start-drawer
 *     placement switch, since Offcanvas's own `responsive` prop only knows one breakpoint at a
 *     time). Selecting a slot opens the left rail even where it's a drawer (harmless at inline
 *     tiers, where `show` is ignored - see Offcanvas's own source). Opening either rail closes the
 *     other, so the two overlays never stack.
 *   - The right rail is new: the settings/export controls this page used to keep in the toolbar
 *     unconditionally (paper size, bleed, guides, Fronts/Backs, Search Settings, Cardback, the
 *     export cluster, and the fetch-progress bar) are relocated there, reachable via the action
 *     bar's gear button below `xl` (hidden entirely at `xl`+, where the rail is already inline).
 *     This is, necessarily, also half of the design doc's §6 row T1 (the OTHER half - the
 *     populated-state add-cards search bar replacing the rest of the toolbar, T2-T5/I1 - is
 *     issue #267's own scope, not touched here): R4 (#266) can't have real content in its new
 *     placement without the controls actually moving out of the toolbar, so that move happens
 *     here using the existing components completely unforked, not the full #267 action-bar
 *     redesign. The right rail's sections are plain, always-expanded groups (not yet the spec's
 *     `AutofillCollapse` per-section chrome/collapsed-by-default hierarchy) - deferred to keep
 *     this PR's test surface to "open the drawer first", not "expand a section first" too.
 *   - Deliberately NOT built here (see the design doc's own issue-mapping + this file's own
 *     module comment history): the `CardDetailedViewBody` extraction and D3's promoted/demoted
 *     content reorder (design doc §7.5/R3 - its own follow-up, the rail's existing accordion
 *     content is reused as-is in the new placements), the D4-D6 4x2/margins/bleed defaults and D8
 *     color calibration (new scope beyond #266-268, own future issues), the #267 search-bar
 *     migration/action-bar sticky wrapper, and the #268 saved-decks landing.
 *
 * Issue #267 (design doc §3/§6 T2-T5/I1, ADDENDUM D12/D13/D15 - owner's locked comment on #267,
 * 2026-07-21) finishes the populated-state action bar #266 deferred, plus the row-mapped polish
 * additions:
 *   - The search bar (§3): a dual-mode Add/Browse `ToggleButtonGroup` prefix, one shared
 *     `searchBarText` state. Add mode mounts `ImportText`'s new "inline" `variant` prop (T3 -
 *     additive, default-unchanged, so every existing block-variant caller is untouched) - Enter
 *     runs the exact same `convertLinesIntoSlotProjectMembers`/`addMembers` pipeline the block
 *     variant does. Browse mode (D12, owner's locked comment: "v1 is FILTERS-FIRST plus plain
 *     text - typed operator grammar is #276, explicitly out of scope") binds the SAME text state
 *     to a plain controlled `Form.Control` instead - `ImportText` itself stays entirely unaware
 *     of Browse mode, per the "shared components gain only additive optional props" constraint.
 *     Beside the input, the existing `Import.tsx` dropdown (D15, = T4 restated) mounts verbatim -
 *     Text/XML/CSV/URL, zero new importer UI, closing the "add cards to a non-empty project"
 *     parity gap.
 *   - Browse results (D12/F10): a new `CatalogBrowseResults.tsx` (own module comment has the full
 *     reasoning, including a documented tile-reuse deviation) renders in the CENTER region,
 *     behind a "Print sheets"/"Browse results" `ToggleButtonGroup` bound to the SAME
 *     `isBrowseMode` state as the search bar's own mode toggle - one state, two controls, per the
 *     mockup's own demonstrated behavior (not the more elaborate two-independent-states reading
 *     the spec prose alone could suggest).
 *   - Invalid-identifiers feedback (D13's landing/search-bar half only - the right-rail Status
 *     row is issue #272's own remaining scope, not this one): `InvalidIdentifiersStatus` (already
 *     self-hiding, already dispatching `showModal("invalidIdentifiers")` into the globally-mounted
 *     `InvalidIdentifiersModal` - see `Layout.tsx`'s `<Modals />`) is mounted unmodified in both
 *     the populated-state action bar and the empty-project `DeckInputLanding`.
 *   - Phone condensation (T5): `ActionBarSearchGroup`'s own `@media (max-width: 767.98px)` rule
 *     gives the search-bar group the design doc §1 region table's specified "Full-width 2nd row"
 *     treatment, not just whatever a bare `flex-wrap` reflow happens to produce.
 *
 * Issue #268 (design doc §5/§6 rows S1-S3, landing cohesion with saved decks) - the empty-project
 * `DeckInputLanding` gains a saved-decks column (`SavedDecksLandingPanel.tsx`) beside the existing
 * paste/URL/XML/CSV import surfaces, `Col lg={4}` decks / `Col lg={8}` import at >=992px, decks
 * first when stacked below that. `DeckRow` (now exported, gained an `openLabel` prop) and a new
 * `useLoadSavedDeck` hook are extracted from `MyDecksPage.tsx` - the exact same open/load
 * (`loadProject`/`loadFinishSettings`/`setCurrentSavedDeck`, unlock prompt, and dirty-project
 * safety-save orchestration), just without the `navigateTo` hop MyDecksPage itself still uses, so
 * loading a deck from here simply populates the current project in place; this page's own
 * `isProjectEmpty` re-render (already relied on by #238's inline importers) takes it from there.
 * `useHasSavedDecksForLanding` decides whether the grid column is reserved at all - false (no
 * empty shell) for an anonymous session or one with zero saved rows ever created; see
 * SavedDecksLandingPanel.tsx's own module comment for the full two-tier visibility rationale,
 * including why the locked-session unlock prompt is deliberately NOT suppressed here.
 *
 * Issue #275 (proposal-h-display-layout-spec.md ADDENDUM D9/D10) replaces the old "Prepare Print
 * footer" three-button stack (Export ▾/Save PDF to Google Drive/Generate PDF) with the new
 * FinishFooter.tsx: `Save Deck` and `Print / Export →` as CO-EQUAL `btn-primary` buttons, plus
 * the same unchanged `Export ▾` below them. Per D9's own hard owner constraint ("save deck
 * should come before PDF completes because we have to rely on clients available mem for the
 * PDF"), the memory-heavy Generate PDF / Save PDF to Google Drive operations - and this page's
 * entire item-2 inline export pipeline that drove them (useDownloadPDF/useSaveToDrivePDF/
 * ImageFailureConfirmModal/the fetch-progress bar/the post-export contribution prompt) - are
 * REMOVED from this page outright, not merely hidden: the Print page (D10, `pages/print.tsx`)
 * now owns PDF generation exclusively, via its own unchanged `FinishedMyProject`/`PDFGenerator`,
 * which already mounts `PostExportContributionPrompt` itself (so the /whatsthat funnel still
 * fires there, for free - no regression). `useProjectDraftBackup.ts` (F1) mirrors the working
 * project to `localStorage` (indexes/settings only, governing premise "we index, we do not
 * store images") on a debounce, offers a restore nudge on `DeckInputLanding` when a prior
 * session's draft outlives an emptied project, and fires D9(2)'s promotion nudge post-import;
 * `PrePrintSaveGate.tsx` (F3) runs the D9(3) flush-then-optionally-prompt-then-navigate sequence
 * the Finish footer's "Print / Export →" button triggers, landing on the new `pages/print.tsx`
 * (D10/F5) - a thin wrapper mirroring `pages/myDecks.tsx`'s own `MyDecksPage` pattern,
 * `FinishedMyProject.tsx` itself UNCHANGED. Deliberately NOT built here (D10's own owner
 * addendum, tracked as its own follow-up): the Print page's tab REORDER/new PDF default, and the
 * PDF tab's own preview removal - see `pages/print.tsx`'s own module comment.
 *
 * Known, deliberately-out-of-scope gap this leaves (documented, not silently accepted): this
 * page's own Page Setup controls (paper size/bleed edge/guides - plain `DisplaySheetSettings`
 * component state, never persisted) don't carry over to the Print page's classic `PDFGenerator`,
 * which has always had its own separate settings and doesn't read this page's margin-profile/
 * card-spacing redux slices either. A user who configures those here and then prints lands on a
 * PDFGenerator with its own unrelated defaults - a genuine settings-parity gap, out of scope for
 * this issue (D9/D10 resolve the SAVE-vs-PRINT ordering and the route linkage, not settings
 * portability), left for a future issue.
 *
 * Editor-completion package, E19/X19 (lime rounded corner-only cut guides) inherits this exact
 * same gap: PagePreview.tsx's screenPresentation variant now renders the reference's lime corner
 * guides on THIS page's own live sheet (screen-only, gated on screenPresentation - PDFGenerator's
 * own fast preview is unaffected), but the REAL exported PDF's guide style is drawn by
 * PDFGenerator.tsx/PDF.tsx's own independent cutLineColor/cutLineShape settings on the Print page -
 * upstream already carries the corner-only geometry this needs (`CutLineCorner`, `cutLineShape:
 * "InsideOnly"` - confirmed by reading `upstream/master`'s `PDF.tsx` directly, not assumed), so no
 * new PDF engine work is required, only wiring a lime preset through - genuine screen/print parity
 * for the guide COLOR is blocked on the same settings-portability gap above, not attempted here.
 */
import styled from "@emotion/styled";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Accordion } from "react-bootstrap";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Collapse from "react-bootstrap/Collapse";
import Form from "react-bootstrap/Form";
import Offcanvas, { OffcanvasPlacement } from "react-bootstrap/Offcanvas";
import Row from "react-bootstrap/Row";
import ToggleButton from "react-bootstrap/ToggleButton";
import ToggleButtonGroup from "react-bootstrap/ToggleButtonGroup";

import { isRecoveryReloadInFlight } from "@/common/chunkErrorRecovery";
import { Back, CardHeightMM, CardWidthMM, Front } from "@/common/constants";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { doesSearchQueryFilterOnPrinting } from "@/common/processing";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import {
  CardDocument,
  Faces,
  MarginProfileKey,
  SearchQuery,
  useAppDispatch,
  useAppSelector,
} from "@/common/types";
import { useLongPress } from "@/common/useLongPress";
import { RightPaddedIcon } from "@/components/icon";
import { RenderIfVisible } from "@/components/RenderIfVisible";
import { CardSlotContextMenu } from "@/features/card/CardSlotContextMenu";
import { getCardSlotMenuActions } from "@/features/card/CardSlotMenuActions";
import { CardbackToolbarButton } from "@/features/card/CommonCardback";
import { RequestedPrintingBadge } from "@/features/card/RequestedPrintingBadge";
import {
  CardDownloadFavorite,
  CardMetaTable,
  PrintingTagsBlock,
  ReportBlock,
} from "@/features/cardDetailedView/CardDetailedViewBody";
import { ArtistSection } from "@/features/display/ArtistSection";
import { CardSpacingControl } from "@/features/display/CardSpacingControl";
import { CatalogBrowseResults } from "@/features/display/CatalogBrowseResults";
import { ConfidenceElement } from "@/features/display/ConfidenceElement";
import { paginateSlotsForDisplay } from "@/features/display/displayPagination";
import { FinishFooter } from "@/features/display/FinishFooter";
import { MarginProfileControl } from "@/features/display/MarginProfileControl";
import { MARGIN_PROFILES } from "@/features/display/marginProfiles";
import { usePrePrintSaveGate } from "@/features/display/PrePrintSaveGate";
import { PrintOptionsSection } from "@/features/display/PrintOptionsSection";
import {
  SavedDecksLandingPanel,
  useHasSavedDecksForLanding,
} from "@/features/display/SavedDecksLandingPanel";
import {
  buildScryfallReferenceImageUrl,
  buildScryfallReferenceUrl,
} from "@/features/display/scryfallReference";
import { SlotActionsSection } from "@/features/display/SlotActionsSection";
import { SourcesAccordion } from "@/features/display/SourcesAccordion";
import {
  ProjectDraftSummary,
  useProjectDraftBackup,
} from "@/features/display/useProjectDraftBackup";
import { useViewportTier } from "@/features/display/useViewportTier";
import {
  SelectVersionResults,
  VoteLayerProps,
} from "@/features/gridSelector/SelectVersionResults";
import { useGridSelectorSearch } from "@/features/gridSelector/useGridSelectorSearch";
import { Import } from "@/features/import/Import";
import { ImportCSV } from "@/features/import/ImportCSV";
import { ImportText } from "@/features/import/ImportText";
import { ImportURL } from "@/features/import/ImportURL";
import { ImportXML } from "@/features/import/ImportXML";
import { InvalidIdentifiersStatus } from "@/features/invalidIdentifiers/InvalidIdentifiersStatus";
import { STANDARD_BLEED_MARGIN_MM } from "@/features/pdf/bleedNormalize";
import { computeLayout } from "@/features/pdf/layout";
import {
  PagePreview,
  PagePreviewSlotContent,
} from "@/features/pdf/PagePreview";
import { getPageSizeMM, PageSize } from "@/features/pdf/PDF";
import { SavedDeckPanel } from "@/features/savedDecks/SavedDeckPanel";
import { SearchSettings } from "@/features/searchSettings/SearchSettings";
import { APICastImplicitVote, APIRetractImplicitVote } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { useCardDocumentsByIdentifier } from "@/store/slices/cardDocumentsSlice";
import {
  selectCardSpacing,
  setCardSpacingCol,
  setCardSpacingRow,
} from "@/store/slices/cardSpacingSlice";
import {
  selectMarginProfile,
  setMarginProfile,
} from "@/store/slices/marginProfileSlice";
import { showChangeQueryModal } from "@/store/slices/modalsSlice";
import {
  bulkRemovePrintingFilter,
  deleteSlots,
  duplicateSlot,
  selectIsProjectEmpty,
  selectProjectCardback,
  selectProjectMember,
  selectProjectMembers,
  setSelectedImages,
} from "@/store/slices/projectSlice";
import { selectSearchResultsForQueryOrDefault } from "@/store/slices/searchResultsSlice";
import {
  selectFrontsVisible,
  toggleFaces,
} from "@/store/slices/viewSettingsSlice";

//# region local, page-only settings state
//
// A deliberately small subset of PDFGenerator.tsx's full settings panel - just enough to drive
// a genuinely live sheet (real computeLayout() inputs, not fake ones). The rest of that panel
// (card selection mode, cut-line geometry, quality/DPI, SCM mode, spacing/margins) stays on the
// classic PDF tab for now; relocating all of it here is Step 3 (switchover) in the design doc's
// §6 sequencing, not Step 1.

interface DisplaySheetSettings {
  pageSize: keyof typeof PageSize;
  bleedEdgeMM: number;
  showCutLines: boolean;
}

// Proposal H D1/D4/D6 (docs/proposals/proposal-h-display-layout-spec.md, amended by issue #286's
// comment) - LETTER (not A4) is the default paper size: the D4-D6 4x2 fit math is computed
// against US Letter throughout (279.4x215.9mm landscape), and A4's own 297x210mm landscape ratio
// (1.414, vs Letter's 1.294) doesn't land on the same grid. STANDARD_BLEED_MARGIN_MM (3.175, the
// MPC 1/8in convention) replaces the old BleedEdgeMM (3.048, an Epson-margin-shaped constant
// inherited from upstream) as the default bleed edge - see D6's own fit table for why 3.175 only
// fits a 4x2 sheet under the Borderless margin profile (marginProfileSlice.ts's own default).
const DEFAULT_SHEET_SETTINGS: DisplaySheetSettings = {
  pageSize: "LETTER",
  bleedEdgeMM: STANDARD_BLEED_MARGIN_MM,
  showCutLines: true,
};

// Upper bound, in real CSS px, on every sheet's rendered width - was PagePreview's own fixed
// maxWidthPx={960} prop before Item 3, and stayed a fixed value until issue #266's fit-to-width
// rule: the sheet-region ResizeObserver below now clamps to whichever is SMALLER, this cap or the
// region's actual measured width, so a narrow viewport (phone/tablet, or a laptop/desktop rail
// eating into the region) shrinks the sheet instead of clipping it. Still the same shared constant
// sheetPixelHeightPx needs for its own height estimate, just no longer the only input.
const SHEET_MAX_WIDTH_PX = 960;

//# endregion

//# region rail-delegacy round (SPEC-rail-delegacy.md) - the nine grey AutofillCollapse sections
//
// The editor-completion package's "demoted zone" (RailSection/AutofillCollapse, Card Details ->
// Attributes -> Printing Tags -> Print Options -> Slot Actions -> Report) is REMOVED - every one
// of those grey drop-downs is gone from the rail per the owner-approved rail-delegacy round
// (2026-07-24). Their contents fold into designed elements instead (§B/§F of the spec):
//   - Card Details' metadata + Download/Favourite -> the rail-head "More details" disclosure
//     (RailHeader below); the printing identifier itself moves to the D14 band (ONE occurrence).
//   - Attributes (the separate `.achip` explicit-vote fieldset, AttributesSection.tsx) is
//     SCRAPPED outright (RD1/O1) - the funnel's own Border/Frame/Treatment chips (already the
//     implicit-vote surface, SelectVersionResults.tsx) are the ONE chip surface now; explicit
//     attribute voting stays only in the D14 identify follow-up (AttributeVotingPanel, inside
//     PrintingTagsBlock below).
//   - Printing Tags (PrintingTagsBlock - PrintingTagPicker + AttributeVotingPanel follow-up) ->
//     the IdentifyPanel band hanging directly off D14 (item 6).
//   - Print Options + Slot Actions + Report -> the one bottom ControlStack (item 7).
// Jump to Version (GridSelectorFilters' own AutofillCollapse) is separately scrapped inside
// SelectVersionResults.tsx/GridSelectorFilters.tsx's own hiddenSections wiring - not this file's
// concern.

//# endregion

//# region always-visible rail header (rail-delegacy round, rev #1/#2/#3 - SPEC-rail-delegacy.md §B/§C;
//         editor-polish round items 4/5/6/9 - SPEC-editor-polish.md §D.1, amendment 1)
//
// Rewritten for the rail-delegacy round (2026-07-24, owner-approved): the rail-head stays LEAN
// (RD6) - a subject-card preview of the slot's own selected art (RD8, `.subject`, a dashed "No
// art selected" empty state otherwise) beside the identity column (slot/face + name), a
// conditional requested≠resolved MISMATCH flag only (RD7 - `RequestedPrintingBadge`'s new
// `showOnlyOnMismatch` prop; the canonical printing id itself lives ONCE, in the D14 band below,
// never repeated here).
//
// Editor-polish round (SPEC-editor-polish.md §D.1/§C, owner amendment 1):
//   - EP5 (REV RD8) - the subject grows 66px -> 116px.
//   - EP6 (N) - a per-slot Front/Back toggle (`.fbtoggle`) beside the identity text; flipping it
//     swaps ONLY the subject preview's own image/label to the OTHER face's own resolved art (a
//     real, distinct ProjectMember - Front/Back are separate slots in this app's own data model,
//     not one card's two sides) - never the D14/identify/More-details data below, which all stay
//     pinned to the slot's actual editing face throughout (EP6's own wording scopes this to "the
//     subject preview" specifically). No real back-face resolution (e.g. a plain shared cardback,
//     or nothing selected at all) renders the `.backart` placeholder stripe instead of a second
//     empty state.
//   - EP4 (REV RD5) - Slot Actions (Change/Duplicate/Delete) relocate here as a compact icon row
//     (`SlotActionsSection`'s new `compact` prop), beside the subject image; REMOVED from the
//     bottom `ControlStack` (see that component's own comment).
//   - EP9 (N) - the Scryfall compare reveal (trigger now lives on the D14 pill,
//     `ConfidenceElement.tsx`) renders HERE, `position:absolute; left:126px` (116px subject +
//     10px `.rhead-row` gap), since it must anchor beside the subject image, a different
//     component than the D14 band that triggers it - see `Rail`'s own comment for the lifted
//     `compareOpen` state this seam depends on.
//   - Amendment 1 (owner, 2026-07-24 post-review, BINDING) - "More details" RELOCATES out of the
//     rail head entirely, to directly under the D14 band (`MoreDetailsSection` below, mounted
//     from `PromotedZone`) - ruled without a design re-pass, so this component drops both the
//     `.detmore` toggle AND the `.detbody` Collapse it used to own; `MoreDetailsSection` inherits
//     that exact JSX unchanged (same `CardMetaTable`/`CardDownloadFavorite`, same testids), just
//     moved.

interface RailHeaderProps {
  face: Faces;
  slot: number;
  cardName: string | undefined;
  searchQuery: SearchQuery | undefined;
  cardDocument: CardDocument | undefined;
  /** EP6 - which face's art the `.subject` box currently shows; defaults to `face` when the
   * toggle has never been touched (see `Rail`'s own `faceOverride` state). */
  previewFace: Faces;
  previewCardDocument: CardDocument | undefined;
  onToggleFace: (face: Faces) => void;
  /** EP4 - threaded straight to the relocated `SlotActionsSection` (same props that component
   * always took; only its render SITE and `compact` layout changed). */
  onSlotDeleted: () => void;
  /** EP9 - lifted from `Rail` (see that component's own comment); `undefined` printing (nothing
   * resolved yet) never renders the reveal regardless of `compareOpen`. */
  compareOpen: boolean;
  comparePrinting: { expansionCode: string; collectorNumber: string } | null;
}

const RailHeader = ({
  face,
  slot,
  cardName,
  searchQuery,
  cardDocument,
  previewFace,
  previewCardDocument,
  onToggleFace,
  onSlotDeleted,
  compareOpen,
  comparePrinting,
}: RailHeaderProps) => {
  const resolvedPrinting =
    cardDocument?.canonicalCard ?? cardDocument?.suggestedCanonicalCard ?? null;
  const compareImageUrl =
    comparePrinting != null
      ? buildScryfallReferenceImageUrl(
          comparePrinting.expansionCode,
          comparePrinting.collectorNumber
        )
      : undefined;
  const showBackArtPlaceholder =
    previewFace !== face && previewCardDocument == null;
  return (
    <div className="rail-head" data-testid="display-rail-header">
      <div className="rhead-row">
        {/* RD8 (rev #3)/EP5 - a PREVIEW of the same thumbnail URL the selected `.vtile`/
            `CardImage` already renders (not a second full render; Select Version stays the art
            surface). EP6 - previews `previewFace`, not always the slot's own editing `face`. */}
        {previewCardDocument != null ? (
          <div
            className="subject"
            data-testid="display-rail-subject"
            data-face={previewFace}
          >
            <img
              src={previewCardDocument.smallThumbnailUrl}
              alt=""
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </div>
        ) : showBackArtPlaceholder ? (
          <div
            className="subject backart"
            data-testid="display-rail-subject-backart"
            data-face={previewFace}
          >
            Back face
            <br />
            not set
          </div>
        ) : (
          <div
            className="subject empty"
            data-testid="display-rail-subject-empty"
            aria-label="No art selected"
          >
            No art
            <br />
            selected
          </div>
        )}
        <div className="idcol">
          <div className="slot">
            Slot {slot + 1} <span className="face">{previewFace}</span>
          </div>
          <div className={cardName != null ? "name" : "name none"}>
            {cardName ?? "No art selected yet"}
          </div>
          {/* RD7 - the canonical printing id lives ONCE, in D14; this is a conditional MISMATCH
              flag only (requested printing differs from the resolved/suggested one), never a
              static second copy. */}
          <RequestedPrintingBadge
            query={searchQuery}
            showOnlyOnMismatch
            resolvedPrinting={resolvedPrinting}
          />
          {/* EP6 - only offered once a front is actually selected (nothing to flip away from
              otherwise); a real `ToggleButtonGroup` (aria-pressed per segment, §G). */}
          {cardDocument != null && (
            <ToggleButtonGroup
              type="radio"
              name={`rail-face-toggle-${slot}`}
              className="fbtoggle"
              value={previewFace}
              onChange={(value: Faces) => onToggleFace(value)}
            >
              <ToggleButton
                id={`rail-face-toggle-${slot}-front`}
                value={Front}
                variant="outline-info"
                size="sm"
                aria-pressed={previewFace === Front}
              >
                Front
              </ToggleButton>
              <ToggleButton
                id={`rail-face-toggle-${slot}-back`}
                value={Back}
                variant="outline-info"
                size="sm"
                aria-pressed={previewFace === Back}
              >
                Back
              </ToggleButton>
            </ToggleButtonGroup>
          )}
          {/* EP4 (REV RD5) - the compact icon row, relocated from the bottom control stack. */}
          <SlotActionsSection
            face={face}
            slot={slot}
            searchQuery={searchQuery}
            onDeleted={onSlotDeleted}
            compact
          />
        </div>
        {/* EP9 - anchored beside the subject image (`left:126px` = 116px subject + 10px
            `.rhead-row` gap); only mounted while open, so its own hover/tap logic
            (`ConfidenceElement.tsx`) never has to coordinate unmount timing with this component. */}
        {compareOpen && compareImageUrl != null && (
          <div className="compare" data-testid="display-rail-compare">
            <img
              src={compareImageUrl}
              alt={
                comparePrinting != null
                  ? `Scryfall reference image for ${comparePrinting.expansionCode.toUpperCase()} ${
                      comparePrinting.collectorNumber
                    }`
                  : "Scryfall reference image"
              }
            />
            <div className="cap">
              Scryfall CDN · <b>display-only, nothing stored</b>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

//# endregion

//# region promoted zone - Artist line + Confidence element (E2, L2/L3)
//
// Editor-completion package, E2 (#2/#3) - the always-visible zone between the status header and
// the (also always-open) Select Version surface below. ArtistSection.tsx is reused verbatim, not
// forked (D3: artist support is top-priority, always visible - a collapsed accordion hid the one
// thing D3 says must be promoted); only its mount location and outer chrome (the `.artist-line`
// lifted-CSS class, E1/§5) changed - the "Artist" AutofillCollapse wrapper this used to sit inside
// is simply gone. ConfidenceElement.tsx is net-new (D14/L3 - see that file's own module comment
// for why this round ships the narrower placeholder cut, not the full interactive version).

interface PromotedZoneProps {
  cardDocument: CardDocument | undefined;
  backendURL: string;
  identifyOpen: boolean;
  onToggleIdentify: () => void;
  detailsOpen: boolean;
  onToggleDetails: () => void;
  compareOpen: boolean;
  onCompareToggle: () => void;
  onCompareShow: () => void;
  onCompareHide: () => void;
}

// Editor-polish round, owner amendment 1 (2026-07-24, BINDING) - "More details" RELOCATES from
// the rail head to directly under the D14 band; this is the exact JSX `RailHeader` used to own
// (same `CardMetaTable`/`CardDownloadFavorite`, same testids - `display-rail-more-details-*` -
// so every existing behavior assertion querying those testids keeps working unchanged), just
// moved into `PromotedZone`, between `ConfidenceElement` and `IdentifyPanel` per the amendment's
// own "renders directly under the D14 confidence band" instruction.
interface MoreDetailsSectionProps {
  cardDocument: CardDocument | undefined;
  open: boolean;
  onToggle: () => void;
}

const MoreDetailsSection = ({
  cardDocument,
  open,
  onToggle,
}: MoreDetailsSectionProps) => (
  <div className="detmore-wrap">
    <button
      type="button"
      className="detmore"
      aria-expanded={open}
      onClick={onToggle}
      data-testid="display-rail-more-details-toggle"
    >
      More details <span className="chev">{open ? "⌄" : "›"}</span>
    </button>
    <Collapse in={open}>
      <div>
        {/* RD6 (O2 answered) - the WHOLE Card-Details metadata block (Resolution/DPI, File
            size, Source, Source type, Class, Identifier, Language, Tags, dates) plus Download +
            Favourite lives ONLY here now - one of the nine removed grey AutofillCollapse
            sections, folded in place. */}
        <div className="detbody" data-testid="display-rail-more-details-body">
          {cardDocument != null ? (
            <>
              {/* RD7 - the printing id lives ONCE, in D14; drop CardMetaTable's own
                  "Canonical Card" row here so it's never a static second copy. */}
              <CardMetaTable
                cardDocument={cardDocument}
                showCanonicalCard={false}
              />
              <CardDownloadFavorite cardDocument={cardDocument} />
            </>
          ) : (
            <p className="text-muted small mb-0">
              Select an image for this slot first.
            </p>
          )}
        </div>
      </div>
    </Collapse>
  </div>
);

// Rail-delegacy round (item 6, SPEC-rail-delegacy.md §B/§F) - the "Printing Tags" grey accordion
// (PrintingTagPicker consensus/search/candidate-grid + the AttributeVotingPanel follow-up) is
// REMOVED as a standalone section and rehung directly off the D14 band it's ABOUT ("what printing
// is this"), opened on demand - never a grey accordion. `PrintingTagsBlock` is reused verbatim
// (CardDetailedViewBody.tsx) - it already owns the exact PrintingTagPicker + conditional
// AttributeVotingPanel-when-unresolved composition item 6/RD1 call for; the ONE explicit
// attribute-vote surface stays here (RD1/O1) - the funnel's own chips (SelectVersionResults.tsx)
// are implicit-only.
interface IdentifyPanelProps {
  cardDocument: CardDocument | undefined;
  open: boolean;
  onToggle: () => void;
}

const IdentifyPanel = ({
  cardDocument,
  open,
  onToggle,
}: IdentifyPanelProps) => {
  if (cardDocument == null) {
    return null;
  }
  return (
    <div className="idhang" data-testid="display-identify-panel">
      <button
        type="button"
        className="idtoggle"
        aria-expanded={open}
        onClick={onToggle}
        data-testid="display-identify-toggle"
      >
        Wrong printing? Search the right one{" "}
        <span className="chev">{open ? "⌄" : "›"}</span>
      </button>
      <Collapse in={open}>
        <div>
          <div className="idbody" data-testid="display-identify-body">
            <PrintingTagsBlock cardDocument={cardDocument} />
          </div>
        </div>
      </Collapse>
    </div>
  );
};

// Fix round (SPEC-display-left-rail.md §3): ConfidenceElement now renders FIRST - it's identity
// (directly under the header's name/RequestedPrintingBadge), not demoted metadata, per the
// spec's explicit placement call. ArtistSection follows, still promoted/always-visible (D3),
// just no longer ahead of D14. ConfidenceElement owns its own full-width band styling
// (`.d14` - background/border-bottom/padding all live in its own markup now, RailRoot's CSS
// below), so it no longer needs an outer padded wrapper here; ArtistSection still does
// (`.artist-line`) - density (§2): `px-2 py-1` (8/4) -> explicit `8px 10px`. Rail-delegacy round
// adds the IdentifyPanel directly below ConfidenceElement (item 6 - "hangs off D14", same subject).
const PromotedZone = ({
  cardDocument,
  backendURL,
  identifyOpen,
  onToggleIdentify,
  detailsOpen,
  onToggleDetails,
  compareOpen,
  onCompareToggle,
  onCompareShow,
  onCompareHide,
}: PromotedZoneProps) => (
  <>
    <ConfidenceElement
      cardDocument={cardDocument}
      backendURL={backendURL}
      compareOpen={compareOpen}
      onCompareToggle={onCompareToggle}
      onCompareShow={onCompareShow}
      onCompareHide={onCompareHide}
    />
    {/* Amendment 1 - directly under the D14 band, ahead of the identify panel. */}
    <MoreDetailsSection
      cardDocument={cardDocument}
      open={detailsOpen}
      onToggle={onToggleDetails}
    />
    <IdentifyPanel
      cardDocument={cardDocument}
      open={identifyOpen}
      onToggle={onToggleIdentify}
    />
    <div
      // O1 fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - see RailHeader's
      // own identical comment for why the Bootstrap `.border-bottom` utility is retired here too.
      // Machine-diff fix round: the `small` Bootstrap utility (0.875em -> 14px off a 16px parent)
      // was CLOSE to the spec's own literal `.artist-line` binding value but not exact - replaced
      // with an explicit `13px` inline style (component-scoped, this exact node only) matching
      // §D.1 precisely.
      className="artist-line"
      style={{ padding: "8px 10px", fontSize: "13px" }}
    >
      <ArtistSection cardDocument={cardDocument} />
    </div>
  </>
);

//# endregion

//# region Select Version section (issue #167 - the unified Select Version section, spec §4.4′)
//
// Editor-completion package, E2/E3/L4 (Bkg 1/2/4/5) - promoted to the always-visible, always-open
// art surface (renamed "Select Version", no AutofillCollapse wrapper at all - it's no longer a
// collapsible section, "Choose Image" as an accordion key is gone from AccordionSectionKey
// entirely). `initialSettingsVisible={false}` on useGridSelectorSearch and `layout="stacked"` on
// SelectVersionResults fix the redline's Bkg 2/4/5 breakages (filters auto-opening cramped inside
// the 380px rail, "Jump to Version" wrapping vertically, bottom controls clipping at the rail
// edge) - see those two files' own prop comments.

interface SelectVersionSectionProps {
  face: Faces;
  slot: number;
  query: SearchQuery | undefined;
  selectedImage: string | undefined;
  backendURL: string;
  /** Funnel round (funnel-spec.md F4/F5, XF6) - the vote layer's cast/retract half, already
   * bound to this slot's (face, slot) by the caller (DisplayPage's own `handleImplicitSupport`,
   * which owns the per-slot retract-on-reselect bookkeeping - see that function's own comment for
   * why it has to live above this component, which fully remounts per slot). `undefined` would
   * disable the vote layer entirely (F5) - DisplayPage always supplies it in production. */
  onImplicitSupport?: (
    candidateIdentifier: string,
    supportTagNames: string[]
  ) => void;
}

// Reuses the same real search/filter machinery GridSelectorModal itself now delegates to
// (useGridSelectorSearch, still shared with the modal variant) rather than a modal - the design
// doc's §4.4 calls for this to render inline in the rail's own scroll container, not a second
// overlapping dialog. Selecting an image dispatches the same setSelectedImages action
// CardSlot.tsx's own grid selector uses, so the sheet's thumbnail for this slot updates
// immediately (same Redux state, same PagePreview render path). The results themselves are now
// SelectVersionResults (issue #167) - grouped by printing/reason-tag/unknown per the spec's §4.4′
// rather than GridSelectorResults' flat CardResultSet grid; GridSelectorModal.tsx's own modal
// variant (CardSlot.tsx's editor grid) is untouched, out of this issue's scope.
const SelectVersionSection = ({
  face,
  slot,
  query,
  selectedImage,
  backendURL,
  onImplicitSupport,
}: SelectVersionSectionProps) => {
  const dispatch = useAppDispatch();
  const getTagDisplayName = useTagDisplayName();
  // Funnel round (F5/F7.2) - the single vote-layer seam SelectVersionResults' "stacked" layout
  // consults. `suggestedTagNames`/`awarenessCopy` are pure reads over data already on the
  // CardDocument/active-tag-name list this component already has in scope; `onImplicitSupport`
  // is the caller-bound cast/retract half (see this component's own prop comment).
  //
  // FIX ROUND (owner-ratified condition 6, Tron's PR #329 review): `suggestedTagNames` now
  // reads `card.suggestedFilterTagNames`, NOT `card.tagVoteStatuses`. `tagVoteStatuses` is a
  // source-agnostic collapse - the backend serializer maps BOTH CONTESTED and UNRESOLVED to the
  // same `"suggested"` string, with no implicit-vote exclusion and no weight floor - so a tag
  // with ONLY implicit votes (or one sub-threshold machine vote, or a REJECT-leaning split) also
  // reads `"suggested"` there. Since a "suggested" chip drives BOTH the dashed-chip UI AND F4b's
  // implicit-vote cast on pick, sourcing either off `tagVoteStatuses` let an already-implicit-only
  // signal seed MORE implicit votes for itself - the self-seeding loop condition 6 forbids.
  // `suggestedFilterTagNames` is the compliant source (`get_suggested_filter_tags_overlay`,
  // docs/features/printing-tags.md): implicit weight excluded entirely, a real non-implicit
  // APPLY-leaning floor, and RESOLVED/CONTESTED/PENDING_APPROVAL/SENSITIVE pairs already
  // excluded server-side. `null`/absent (the backend wiring for this field lands in a parallel
  // PR - until deployed the wire value is `null`) degrades to `[]` here via `?? []`, so the
  // funnel stays fully functional on settled/metadata chips with zero suggested chips, never a
  // crash.
  const voteLayer: VoteLayerProps | undefined =
    onImplicitSupport != null
      ? {
          onImplicitSupport,
          suggestedTagNames: (card) =>
            (card.suggestedFilterTagNames ?? []).filter(
              (tagName) => !card.tags.includes(tagName)
            ),
          awarenessCopy: (activeTagNames) =>
            `Picking a card here supports ${activeTagNames
              .map(getTagDisplayName)
              .join(" · ")} for it. Undo by re-picking.`,
        }
      : undefined;
  const searchResultsForQuery =
    useAppSelector((state) =>
      selectSearchResultsForQueryOrDefault(
        state,
        query?.query,
        query?.cardType,
        query?.expansionCode,
        query?.collectorNumber,
        face
      )
    ) ?? [];
  const focusRef = useRef<HTMLInputElement>(null);
  // E3/X2 (Bkg 5) - the rail always starts with Filters collapsed, regardless of viewport width
  // (the modal's own GridSelectorModal caller doesn't pass this, so its width-based default is
  // unchanged).
  const search = useGridSelectorSearch({
    imageIdentifiers: searchResultsForQuery,
    active: true,
    initialSettingsVisible: false,
  });

  const onSelectImage = (identifier: string) => {
    dispatch(
      setSelectedImages({
        slots: [[face, slot]],
        selectedImage: identifier,
        deselect: true,
      })
    );
  };

  if (searchResultsForQuery.length === 0) {
    // E17 - the Select-Version empty state is one of the two directed-help homes the spec names
    // (the other is the on-card sheet slot, see PagePreview's own loadState="failed" rendering);
    // a deterministic Scryfall reference link costs zero backend work (buildScryfallReferenceUrl,
    // scryfallReference.ts).
    const findCardUrl = buildScryfallReferenceUrl(query);
    return (
      <div>
        <p className="text-muted small mb-1">
          No candidate images found for this slot&apos;s query.
        </p>
        {findCardUrl != null && (
          <a
            href={findCardUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="small"
            data-testid="display-select-version-find-card-link"
          >
            Find this card ↗
          </a>
        )}
      </div>
    );
  }

  // Funnel round (funnel-spec.md F1, XF2) - the "N results · ▸ Filters" head line used to live
  // here, outside SelectVersionResults; it's now rendered INSIDE the funnel itself (head A: count
  // · active-tag pills · the Filters disclosure toggle), since it's part of the ONE funnel column
  // the spec describes, not a separate wrapper element.
  return (
    <>
      <SelectVersionResults
        imageIdentifiers={searchResultsForQuery}
        selectedImage={selectedImage}
        onSelectImage={onSelectImage}
        focusRef={focusRef}
        search={search}
        requestedPrinting={
          query?.expansionCode != null
            ? {
                expansionCode: query.expansionCode,
                collectorNumber: query.collectorNumber,
              }
            : undefined
        }
        backendURL={backendURL}
        layout="stacked"
        voteLayer={voteLayer}
      />
    </>
  );
};

//# endregion

//# region deck-input landing (issue #238, design doc §4.1)

// Renders the same plain import components ProjectEditor.tsx's own AddCardsPanel mounts on the
// classic editor's "Add Cards" tab - ImportText/ImportURL/ImportXML/ImportCSV - inline, in place
// of the old "go to /editor" link, so an empty project can be started without ever leaving this
// page. Deliberately NOT AddCardsPanel itself: that component wraps its two columns in an
// OverflowCol sized via a heightDelta of NavPillButtonHeight + NavbarHeight, both editor-tab-
// specific concepts this page has neither of (this page also has no bottom nav-pill tab strip to
// account for) - and NavbarHeight is a currently-wrong hardcoded constant (issue #250, navbar
// renders at 64px not the constant's 50px), so a second surface deriving a forced 100vh-minus-
// NavbarHeight scroll region from it would just compound that same bug here. This page's own
// root already sits inside Layout.tsx's fixed-position, overflow-y:scroll ContentContainer (see
// this file's own flat-scroll comment above), so the landing just flows in that existing scroll
// container - no forced height calc of its own needed.
//
// onImportComplete is intentionally omitted (design doc §4.1 step 3): once addMembers fires,
// selectIsProjectEmpty flips false and DisplayPage re-renders straight into the sheet+rail layout
// on its own - there's no separate tab to switch away from here, unlike ProjectEditor.tsx's own
// use of this same callback to flip its Tab.Panes. Confirmed safe to omit by reading all four
// components' own onImportComplete call sites: each dispatches addMembers synchronously, then
// (if the prop is provided at all) calls onImportComplete as its very last statement with no
// state updates afterwards - nothing here depends on this page's own subtree remaining mounted
// once that callback fires.
//
// Issue #268 (design doc §5/§6 rows S1-S3) - a signed-in session with at least one unlocked
// saved deck gets a third, LEADING column: SavedDecksLandingPanel.tsx, `Col lg={4}` beside the
// import surfaces' own `Col lg={8}` at >=992px, stacked above them (saved decks first) below
// that. `useSavedDecksForLanding` returns null for an anonymous or deck-less session - in that
// case the layout falls straight back to today's plain two-column import grid, never reserving
// an empty column for a panel with nothing to show.
const ImportColumns = () => (
  <>
    <Col lg={6} md={6} sm={12} xs={12} className="px-2">
      <h5>Enter a Card List</h5>
      <ImportText />
      {/* Design doc ADDENDUM D13 (issue #267's landing/search-bar feedback half) - the same
          self-contained, self-hiding status component (visible only when
          selectInvalidIdentifiersCount > 0) the populated-state action bar mounts below;
          attached here too so an import that leaves unresolved identifiers is visible on the
          empty-project landing, not just once a project already exists. */}
      <InvalidIdentifiersStatus />
    </Col>
    <Col lg={6} md={6} sm={12} xs={12} className="px-2">
      <h5>Import a File or URL</h5>
      <Accordion defaultActiveKey="url">
        <Accordion.Item eventKey="url">
          <Accordion.Header>
            <RightPaddedIcon bootstrapIconName="link-45deg" /> URL
          </Accordion.Header>
          <Accordion.Body>
            <ImportURL />
          </Accordion.Body>
        </Accordion.Item>
        <Accordion.Item eventKey="xml">
          <Accordion.Header>
            <RightPaddedIcon bootstrapIconName="file-code" /> XML
          </Accordion.Header>
          <Accordion.Body>
            <ImportXML />
          </Accordion.Body>
        </Accordion.Item>
        <Accordion.Item eventKey="csv">
          <Accordion.Header>
            <RightPaddedIcon bootstrapIconName="file-earmark-spreadsheet" /> CSV
          </Accordion.Header>
          <Accordion.Body>
            <ImportCSV />
          </Accordion.Body>
        </Accordion.Item>
      </Accordion>
    </Col>
  </>
);

interface DeckInputLandingProps {
  // Issue #275 (design doc ADDENDUM D9(1)/F1) - useProjectDraftBackup's own restore nudge:
  // non-null only when a prior session's draft outlives this one's now-empty project. Passed in
  // rather than a second hook instance here, since DisplayPage already owns the one instance
  // actually driving the debounced writes (see this file's own module comment).
  restorableDraft: ProjectDraftSummary | null;
  onRestoreDraft: () => void;
  onDismissDraft: () => void;
}

const DeckInputLanding = ({
  restorableDraft,
  onRestoreDraft,
  onDismissDraft,
}: DeckInputLandingProps) => {
  const hasSavedDecks = useHasSavedDecksForLanding();
  return (
    <div className="p-3" data-testid="display-empty-state">
      {restorableDraft != null && (
        <div
          className="d-flex align-items-center gap-2 border rounded p-2 mb-3"
          data-testid="display-restore-draft-banner"
        >
          <span className="me-auto">
            Restore your unsaved work? A local backup of{" "}
            {restorableDraft.memberCount} card
            {restorableDraft.memberCount !== 1 ? "s" : ""} from this browser is
            still here.
          </span>
          <Button
            size="sm"
            variant="primary"
            onClick={onRestoreDraft}
            data-testid="display-restore-draft-accept"
          >
            Restore
          </Button>
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={onDismissDraft}
            data-testid="display-restore-draft-dismiss"
          >
            Dismiss
          </Button>
        </div>
      )}
      {hasSavedDecks ? (
        <Row className="g-0">
          <Col lg={4} className="px-2">
            <SavedDecksLandingPanel />
          </Col>
          <Col lg={8} className="px-2">
            <Row className="g-0">
              <ImportColumns />
            </Row>
          </Col>
        </Row>
      ) : (
        <Row className="g-0">
          <ImportColumns />
        </Row>
      )}
    </div>
  );
};

//# endregion

interface SelectedSlotRef {
  face: Faces;
  slot: number;
}

// Issue #266 (design doc §4/§6 R2/R4) - the three-region body: left rail · sheet · right rail,
// laid out as a single flex row only once EITHER rail actually goes inline (`lg`, 992px - the
// left rail's own inline threshold, the first of the two). Below that, both rails render as
// fixed-position Offcanvas drawers (out of normal flow entirely - see LeftRailOffcanvas/
// RightRailOffcanvas below), so this wrapper only ever needs to arrange the sheet region itself.
// `position: relative; z-index: 0` is scoped to the SAME `lg`-up media query - the specific fix
// docs/lessons.md's sticky/z-index entry documents (part 3) - deliberately NOT applied below `lg`:
// react-bootstrap's Offcanvas dialog renders through a portal while open (its own z-index escapes
// any ancestor stacking context), so an unconditional zIndex: 0 parent here would only reintroduce
// the exact stacking trap this fix exists to avoid, for no benefit, on tiers where the rail is a
// drawer instead of an inline sibling (see the design doc's own portal note, §context/R2).
const DisplayBodyRegion = styled.div`
  display: flex;
  flex-direction: column;
  align-items: stretch;
  flex-grow: 1;

  @media (min-width: 992px) {
    flex-direction: row;
    align-items: flex-start;
    position: relative;
    z-index: 0;
  }
`;

// Both rails are ONE `Offcanvas` node each (design doc §4's "hard precedent... no d-none
// duplicate renders"): `responsive` picks the CSS class Bootstrap keys its own breakpoint media
// queries off (`.offcanvas-lg`/`.offcanvas-xl`), which - above that breakpoint - already resets
// `position`/`display` to plain in-flow values and hides `.offcanvas-header` entirely (Bootstrap's
// own stock CSS, not custom here). Everything below fills in what Bootstrap's inline reset
// deliberately leaves unstyled: a fixed width, sticky positioning, and its own scroll container -
// see the design doc's §4 "Inline styling... attaches via a wrapper class scoped to the inline
// tiers" instruction. The bottom-sheet's 72vh height + rounded top corners (design doc §4.1) are
// scoped to `.offcanvas-bottom` specifically, since this same node also renders as `.offcanvas-
// start` on tablet (leftPlacement below) - the two placements should not share sizing.
//
// Live report follow-up (deployed commit 85bd3a37): the "72vh height" half of the paragraph above
// was true in intent only - never actually written below - so the phone bottom sheet fell back to
// Bootstrap's own stock $offcanvas-vertical-height default (30vh, bootstrap/scss/_variables.scss),
// not this doc's 72vh. Closed state was NOT the bug (confirmed against the live site: Bootstrap's
// own visibility: hidden plus transform: translateY(100%) both still applied correctly to the
// closed, statically-rendered node - see react-bootstrap's Offcanvas.js, the
// "!showOffcanvas && responsive" render branch) - what the owner's live report actually saw
// ("pinned to the bottom and mostly non visible") was a genuinely-open drawer only 30vh tall, most
// of its own content clipped below that. The explicit height (not max-height) below matches the
// approved mockup's own bottom-sheet rule exactly - see the design doc's R5 row.
const LeftRailOffcanvas = styled(Offcanvas)`
  &.offcanvas-bottom {
    height: 72vh;
    border-top-left-radius: 0.75rem;
    border-top-right-radius: 0.75rem;
  }

  @media (min-width: 992px) {
    &.offcanvas-lg {
      width: 380px;
      max-width: 380px;
      flex: 0 0 380px;
      position: sticky;
      top: 0;
      max-height: 100vh;
      overflow-y: auto;
      border-right: var(--bs-border-width) solid
        var(--bs-border-color-translucent);
    }
  }
`;

const RightRailOffcanvas = styled(Offcanvas)`
  @media (min-width: 1200px) {
    &.offcanvas-xl {
      width: 300px;
      max-width: 300px;
      flex: 0 0 300px;
      position: sticky;
      top: 0;
      max-height: 100vh;
      overflow-y: auto;
      border-left: var(--bs-border-width) solid
        var(--bs-border-color-translucent);
    }
  }
`;

// Design doc §4.1's tablet-only discoverability affordance: "a 'Card details' edge handle keeps
// it discoverable with nothing selected" - without this, a tablet user with no slot selected has
// no visible way to reach the left rail at all (there's nothing on the sheet to tap yet, and the
// gear only opens the RIGHT rail). Phone doesn't need this (D2's mockup omits it there too) -
// nothing-selected still shows the rail's own idle message, which is reachable by tapping any
// slot the moment one exists. Laptop/desktop don't need it either - the rail's already inline.
const TabletRailHandle = styled(Button)`
  display: none;

  @media (min-width: 768px) and (max-width: 991.98px) {
    display: block;
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    z-index: 1030;
    writing-mode: vertical-rl;
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
  }
`;

// Issue #267 (design doc §1's region table + §6 T5) - "Add-cards search bar ... Full-width 2nd
// row" on phone specifically, not just whatever a bare `flex-wrap` reflow happens to produce
// (the mockup's own `.addbar{flex-basis:100%;order:9;}` chunk - see display-mockup.html). Below
// `md`, this group becomes its own full-width row (ordered after the sheet-indicator/SavedDeckPanel
// pair, before the gear) instead of squeezing into whatever horizontal space is left in the bar.
const ActionBarSearchGroup = styled.div`
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1 1 240px;
  min-width: 0;

  @media (max-width: 767.98px) {
    flex-basis: 100%;
    order: 9;
  }
`;

// Editor-polish round, item 2 (EP2, SPEC-editor-polish.md §D.6 `.abtn`) - the page-wide button-
// contrast floor: the toolbar's `outline-secondary` "Add"/"Add card"/etc buttons resolve to
// Bootstrap Superhero's own `$secondary` (`#4e5d6c`) border/text, which reads as a near-
// invisible grey ghost on this dark chrome. Scoped to the toolbar's own DOM subtree (this
// styled-component wraps it - see `data-testid="display-toolbar"`'s own call site below) so
// every OTHER `outline-secondary` button sitewide (outside this page) is unaffected - the same
// component-scoped-override discipline as `.rail-source-toggle`/`.cstack .form-select` above.
const ToolbarRoot = styled.div`
  .btn-outline-secondary {
    background: #22303f;
    color: #ebebeb;
    border: 1px solid #46586a;
  }
  .btn-outline-secondary:hover,
  .btn-outline-secondary:focus {
    background: #22303f;
    color: #ebebeb;
    border-color: #abb6c2;
  }
`;

// Editor-completion package, E1/X6 - the mockup's rail stylesheet, lifted verbatim per the
// owner's grant (spec §5: "the left rail MAY lift the mockup's CSS verbatim rather than
// re-approximate through react-bootstrap idioms").
// Fix round (SPEC-display-left-rail.md §0/§2/§3, owner-approved 2026-07-23): the mockup's rail
// stylesheet, lifted verbatim per the owner's existing grant (spec §5 of the earlier
// editor-completion round: "the left rail MAY lift the mockup's CSS verbatim rather than
// re-approximate through react-bootstrap idioms") - re-extracted against the REAL #302 theme
// tokens this round's spec documents in its own §0 table (the previous round's values were
// close approximations, not the actual bootswatch/superhero + styles.scss values). `.d14`/
// `.seticon`/`.idtext`/`.statepill`/`.notthis` replace the old `.confidence`/`.set-symbol`/
// `.conf-badge`/`.conf-x` set (ConfidenceElement.tsx's own markup was rewritten to match - see
// that file's own module comment).
//
// CSS-fidelity pass (owner-reported regression, 2026-07-23): §2's density table has its own row
// for "AutofillCollapse header in rail" (Superhero's stock `.card-header` `0.5rem 1rem` (8/16) ->
// rail-scoped `padding:7px 10px`) - this was in the spec from the start but never actually
// landed as CSS (the comment this replaced claimed the demoted accordions deliberately "keep
// today's proven pattern," which was true for the CARD look/chrome but wrong for padding - the
// spec never carved padding out of scope). Originally fixed here via a plain `.card-header`
// descendant selector (clobbering Bootstrap's bare global `.card-header` rule by selector
// specificity, not by scope - the exact "pinned in a higher location than expected" pattern
// SPEC-display-left-rail.md's "Source map addendum" flags as this fork's CSS-regression
// recurrence signature). CSS-fidelity source-map pass (follow-up): retired in favour of
// AutofillCollapse's own additive `headerPadding` prop, passed directly at each rail call site
// (RailSection/SourcesAccordion) - the value now travels WITH the component invocation instead
// of being injected from this ancestor wrapper two files away. See that prop's own comment in
// AutofillCollapse.tsx for the full before/after.
//
// O1 fix round (SPEC-display-left-rail.md §D.1/§A "Introduced this round" #1, corrected
// 2026-07-23, owner-approved): divider normalization to #16202b, 1px, on every rail block
// boundary. Shipped code was inconsistent - `.d14` already used the explicit `#16202b` literal
// below, while `.rail-head`/`.artist-line`/`.sources` (SourcesAccordion.tsx's own outer wrapper -
// a descendant of this styled-component's scope, so the selector below reaches it too) instead
// used Bootstrap's `.border-bottom` utility, whose active `--bs-border-color` is genuinely
// ambiguous in the compiled CSS (`#495057` vs `#ced4da` both present - the light value would
// render a pale line on this dark rail). Retired in favour of the one explicit shipped dark value
// everywhere; the Select Version wrapper gains a boundary hairline it never had before (mockup:
// `.sv{border-bottom:1px solid var(--divider)}`).
const RailRoot = styled.div`
  .rail-head {
    background: #22303f;
    border-bottom: 1px solid #16202b;
    padding: 8px 10px;
  }
  .artist-line {
    background: #22303f;
    border-bottom: 1px solid #16202b;
  }
  .sources {
    border-bottom: 1px solid #16202b;
  }
  .select-version-wrapper {
    border-bottom: 1px solid #16202b;
  }
  .select-version-heading {
    margin: 0;
    padding: 8px 0 4px;
    font-weight: 600;
    /* Machine-diff fix round (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - this
       bespoke, single-use classname had no font-size rule at all, so it fell through to the
       Bootstrap body default (16px) instead of the spec's own 14px. This selector is invented
       for this one heading element only (not a reused Bootstrap classname like the old
       .card-header pattern), so extending its existing RailRoot rule is component-scoped in the
       sense the #400 rule cares about - it cannot clobber anything else on the page. */
    font-size: 14px;
  }
  /* D14 confidence band - full-width, no floating chip inset margin (density §2: "kills the
     floating-chip inset margin"). */
  .d14 {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin: 0;
    padding: 8px 10px;
    background: #2b3e50;
    border-bottom: 1px solid #16202b;
    font-size: 12px;
  }
  /* Deliberate radius exception (spec §0) - kept, not invented: the set icon's own circular
     shape and the status pills' pill radius are the two rounded exceptions Superhero's flat
     (border-radius:0) rule doesn't otherwise allow. */
  .seticon {
    position: relative;
    width: 30px;
    height: 30px;
    flex: 0 0 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: #4e5d6c;
    border: 1px solid #7f8fa0;
    border-radius: 50%;
    cursor: pointer;
  }
  .seticon .ss {
    font-size: 15px;
    color: #ebebeb;
  }
  .seticon .check {
    position: absolute;
    right: -3px;
    bottom: -3px;
    width: 15px;
    height: 15px;
    background: #5cb85c;
    color: #fff;
    border: 2px solid #2b3e50;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    font-weight: 900;
  }
  .seticon .score {
    position: absolute;
    right: -7px;
    bottom: -7px;
    background: #df6919;
    color: #fff;
    border: 2px solid #2b3e50;
    border-radius: 10px;
    font-size: 9px;
    font-weight: 800;
    padding: 1px 4px;
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .d14 .idtext {
    font-size: 12px;
    font-family: monospace;
  }
  .d14 .statepill {
    padding: 1px 8px;
    border: 1px solid #4e5d6c;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
  }
  .d14 .statepill.confirmed {
    border-color: #3f7a2f;
    color: #a7e08a;
  }
  .d14 .statepill.suggested {
    border-color: #df6919;
    color: #ffb27d;
  }
  .d14 .notthis {
    margin-left: auto;
  }
  /* Owner answer #2 (2026-07-23): the ✗ vote stays available on an already-confirmed printing
     too (dispute is always possible, D1 semantics) - de-emphasised via opacity, not hidden. */
  .d14 .notthis[data-confirmed="true"] {
    opacity: 0.6;
  }
  /* Machine-diff fix round (owner ruling, 2026-07-23) - restyles the shared
     react-bootstrap-toggle library into the corrected mockup's static two-cell segmented look
     (both On/Off labels always visible, side by side) instead of its own stock sliding
     single-label switch. Scoped to .rail-source-toggle (the className SourcesAccordion.tsx's own
     Toggle passes) so every OTHER react-bootstrap-toggle mount sitewide (FinishSettings,
     PDFGenerator, SearchTypeSettings, the filter Toggles, etc) is completely unaffected - this
     selector can only ever match the rail's own Sources list toggles. The library's real DOM
     already renders both toggle-on/toggle-off spans, each already carrying the requested
     btn-primary/btn-secondary colour classes unconditionally (confirmed by reading
     node_modules/react-bootstrap-toggle/dist/react-bootstrap-toggle.js) - only the sliding
     positioning/overflow-clipping needed overriding to reveal both at once. */
  .rail-source-toggle {
    overflow: visible;
    background: transparent;
    border: 1px solid #6b7d8e;
  }
  .rail-source-toggle .toggle-group {
    position: static;
    width: 100%;
    display: flex;
    left: 0 !important;
    transition: none;
  }
  .rail-source-toggle .toggle-on,
  .rail-source-toggle .toggle-off {
    position: static;
    flex: 1;
    left: auto;
    right: auto;
    padding: 0;
    margin: 0;
    font-size: 11px;
    font-weight: 700;
  }
  .rail-source-toggle .toggle-off {
    color: #8fa0b0;
  }
  .rail-source-toggle .toggle-handle {
    display: none;
  }

  /* ============================================================================
     Rail-delegacy round (SPEC-rail-delegacy.md §D.2) - tokens for the elements that
     replace the nine removed grey AutofillCollapse sections.
     ============================================================================ */

  /* rail-head: rev #1/#2/#3 - lean identity + subject-card preview.
     Editor-polish round (SPEC-editor-polish.md §D.1) - EP5 grows the subject 66px -> 116px, EP9
     needs '.rhead-row' positioned so the '.compare' reveal (further down) can anchor to it. */
  .rhead-row {
    position: relative;
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }
  .subject {
    flex: 0 0 116px;
    width: 116px;
    aspect-ratio: 63 / 88;
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(235, 235, 235, 0.15);
  }
  .subject img {
    display: block;
  }
  .subject.empty {
    background: transparent;
    border: 1px dashed #abb6c2;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: #8fa0b0;
    font-size: 9px;
    padding: 4px;
    line-height: 1.3;
  }
  /* EP6 (N) - the back-face-not-set placeholder stripe: shown only while previewing the back
     face AND nothing real resolved for it (never a second dashed empty box - visually distinct
     from '.subject.empty' per §D.1's own literal token). */
  .subject.backart {
    background: linear-gradient(135deg, #2a2320, #1f1a17);
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: #a99;
    font-size: 9px;
    padding: 4px;
    line-height: 1.3;
  }
  .idcol {
    flex: 1;
    min-width: 0;
  }
  .rail-head .slot {
    font-weight: 700;
    font-size: 14px;
  }
  .rail-head .slot .face {
    font-weight: 400;
    color: #8fa0b0;
    font-size: 11px;
    text-transform: uppercase;
    margin-left: 6px;
  }
  .rail-head .name {
    font-size: 15px;
    margin-top: 1px;
  }
  .rail-head .name.none {
    color: #8fa0b0;
    font-style: italic;
  }
  /* EP6 (N) - the per-slot Front/Back segmented toggle, 'ToggleButtonGroup' restyled to the
     spec's own literal tokens (react-bootstrap's own outline-info variant is fully overridden
     here, component-scoped to '.fbtoggle' only - no other 'ToggleButtonGroup' mount sitewide
     carries this class). */
  .fbtoggle {
    margin-top: 7px;
    border: 1px solid #6b7d8e;
  }
  .fbtoggle .btn {
    font-size: 11px;
    font-weight: 700;
    padding: 2px 12px;
    background: #22303f;
    color: #8fa0b0;
    border-color: #6b7d8e;
    border-radius: 0;
  }
  .fbtoggle .btn.active,
  .fbtoggle .btn:focus,
  .fbtoggle .btn:hover {
    background: #5bc0de;
    color: #062430;
    border-color: #5bc0de;
    box-shadow: none;
  }
  /* EP4 (REV RD5, §D.1 '.slotacts-top .iact') - the compact icon row's OWN sizing lives in
     'SlotActionsSection.tsx''s 'IconAction' styled-component (component-scoped there, same
     discipline as '.rail-source-toggle'/'.cstack .form-select' elsewhere in this file); this
     selector only carries the row's own gap/margin, which is genuinely this call site's concern
     (the compact row's OTHER caller, if one is ever added, may want different spacing). */
  .slotacts-top {
    gap: 6px;
    margin-top: 8px;
  }
  /* Amendment 1 (owner, 2026-07-24, BINDING) - "More details" moved out of the rail head to
     directly under the D14 band; same padded/divider rhythm as its new neighbours ('.d14'/
     '.idhang', both '#2b3e50') rather than the rail-head's own '#22303f', since it's still
     "about the currently-identified printing," the same subject D14 covers. */
  .detmore-wrap {
    background: #2b3e50;
    border-bottom: 1px solid #16202b;
    padding: 8px 10px;
  }
  .detmore {
    background: transparent;
    border: none;
    color: #8fa0b0;
    font-size: 11px;
    cursor: pointer;
    padding: 0;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-family: inherit;
  }
  .detmore:hover {
    color: #ebebeb;
  }
  .detbody {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #16202b;
    font-size: 11px;
  }
  /* EP9 (N, §D.1 '.compare') - the Scryfall reference reveal, anchored beside the 116px subject
     image (116 + the '.rhead-row' 10px gap = 126). 'pointer-events: none' is load-bearing, not
     decorative: at z-index 40 this panel paints ABOVE later DOM siblings (the D14 band sits
     right after the rail head, and the panel's own aspect-ratio height easily reaches down far
     enough to visually cover the very pill that triggered it) - without this, the panel would
     intercept the pointer the instant it appears, firing a real mouseleave on the now-covered
     pill, hiding the panel, un-covering the pill, re-firing mouseenter, and re-showing it - an
     infinite open/close oscillation confirmed live via Playwright (repeated onMouseEnter firing
     with the state never settling to true) before this fix. Purely visual, never itself a
     click/hover target - ConfidenceElement.tsx's own pill stays the sole interactive surface,
     exactly as the mockup's own hover-reveal (not a second interactive layer) intends. */
  .compare {
    position: absolute;
    left: 126px;
    top: 0;
    z-index: 40;
    width: 150px;
    background: #0b1520;
    border: 1px solid #5bc0de;
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.6);
    padding: 5px;
    pointer-events: none;
  }
  .compare img {
    display: block;
    width: 100%;
    aspect-ratio: 63 / 88;
    object-fit: cover;
  }
  .compare .cap {
    font-size: 9px;
    color: #8fa0b0;
    margin-top: 4px;
  }
  .compare .cap b {
    color: #5bc0de;
    font-weight: 700;
  }

  /* identify panel band (item 6) - hangs off D14, same surface (§2/#2b3e50) */
  .idhang {
    background: #2b3e50;
    border-bottom: 1px solid #16202b;
    padding: 0 10px 8px;
  }
  .idtoggle {
    background: transparent;
    border: 1px solid #6b7d8e;
    color: #abb6c2;
    font-size: 12px;
    padding: 3px 8px;
    cursor: pointer;
    font-family: inherit;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .idtoggle:hover {
    border-color: #abb6c2;
    color: #ebebeb;
  }
  .idbody {
    margin-top: 8px;
    background: #22303f;
    border: 1px solid #16202b;
    padding: 8px;
  }

  /* Select Version header row (item 2 - Sort/Filters) */
  .svhead {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
    font-size: 12px;
    color: #8fa0b0;
    flex-wrap: wrap;
  }
  .svhead .n {
    color: #ebebeb;
    font-weight: 700;
  }
  /* EP7 (SPEC-editor-polish.md §D.4 '.sortsel', REV RD2) - 'max-width' 150px -> 172px. */
  .sortsel {
    background: #22303f;
    color: #ebebeb;
    border: 1px solid #4e5d6c;
    font-size: 12px;
    padding: 3px 6px;
    border-radius: 0;
    max-width: 172px;
  }
  /* EP10 (N, §D.4 '.vloading') - replaces '.vgrid' while 'search.displaySpinner' is true. */
  .vloading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    min-height: 140px;
    color: #8fa0b0;
    font-size: 12px;
  }
  /* EP10 - tints the site's canonical spinner '--primary' inside the rail only (component-
     scoped via this ancestor selector, same discipline as '.rail-source-toggle' above - it
     cannot reach a 'Spinner' mounted anywhere outside this styled-component's own DOM scope). */
  .vloading .spinner-border {
    color: #df6919;
  }
  .filtersbtn {
    background: transparent;
    border: 1px solid #abb6c2;
    color: #abb6c2;
    font-size: 14px;
    padding: 4px 8px;
    cursor: pointer;
    font-family: inherit;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .filtersbtn:hover {
    background: #abb6c2;
    color: #111;
  }

  /* Filters panel - one shared fieldset body, tier-conditional container (RD4/O3): phone = the
     in-rail .fpanel.inline below, still inside this styled-component's own DOM/CSS scope.
     Desktop/tablet's own .fpanel.float + .fscrim are portaled to document.body instead (see
     SelectVersionResults.tsx's FloatFiltersPortalRoot comment for why a plain in-tree
     position:fixed node isn't enough here) - those two classes' rules travel WITH that portal
     component, duplicated in lockstep, not defined here. */
  .fpanel {
    background: #22303f;
    border: 1px solid #16202b;
    padding: 8px;
  }
  .fpanel.inline {
    margin-bottom: 8px;
  }
  .fset {
    border: none;
    margin: 0 0 9px;
    padding: 0;
  }
  .fset:last-child {
    margin-bottom: 0;
  }
  .fset > .lg {
    display: block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #8fa0b0;
    margin-bottom: 4px;
  }
  .fsep {
    height: 1px;
    background: #16202b;
    margin: 9px -8px;
  }
  .implicit-note {
    font-size: 10px;
    color: #8fa0b0;
    margin-top: 7px;
    display: flex;
    gap: 5px;
    align-items: flex-start;
    line-height: 1.4;
  }
  .implicit-note .ic {
    color: #5bc0de;
    flex: 0 0 auto;
  }

  /* control stack (item 7) - Print Options + Slot Actions + Report */
  .cstack {
    padding: 8px 10px;
  }
  .cs-group {
    margin-bottom: 10px;
  }
  .cs-legend {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #8fa0b0;
    margin-bottom: 5px;
  }
  /* Component-scoped override of PrintOptionsSection's own Form.Select (same non-fork discipline
     as .rail-source-toggle above - reused component, rail-scoped CSS only). */
  .cstack .form-select {
    background: #22303f;
    color: #ebebeb;
    border: 1px solid #4e5d6c;
    font-size: 13px;
    padding: 4px 8px;
    width: 100%;
    border-radius: 0;
  }
  .cstack p.text-muted {
    font-size: 10px;
    color: #8fa0b0;
    margin-top: 4px;
  }
  .cs-foot {
    border-top: 1px solid #16202b;
    padding-top: 8px;
  }
`;

//# region bottom control stack (item 7, SPEC-rail-delegacy.md §B/§F/RD5;
//         editor-polish item 4, SPEC-editor-polish.md §D.7 - REVISES RD5)
//
// Print Options + Report - EP4 (REV RD5, §D.7) moves Slot Actions OUT of this stack entirely, up
// into the rail head's compact icon row (`RailHeader`'s own `SlotActionsSection compact` mount) -
// "no full-width slot-action buttons anywhere" per EP4's own wording. What's left collapses into
// ONE designed `.cstack` at the rail bottom (RD5): a per-group `.cs-legend` label replaces each
// section's own accordion header, and Report is a single `btn-outline-danger` that expands to
// `ReportCardPanel`'s reason chips in place (already that component's own stock behavior -
// `ReportBlock` needs no changes at all).

interface ControlStackProps {
  selectedCardDocument: CardDocument | undefined;
}

const ControlStack = ({ selectedCardDocument }: ControlStackProps) => (
  <div className="cstack" data-testid="display-control-stack">
    <div className="cs-group">
      <div className="cs-legend">Print options</div>
      <PrintOptionsSection cardDocument={selectedCardDocument} />
    </div>
    <div className="cs-foot">
      {selectedCardDocument != null ? (
        <ReportBlock cardDocument={selectedCardDocument} />
      ) : (
        <p className="text-muted small mb-0">
          Select an image for this slot first.
        </p>
      )}
    </div>
  </div>
);

//# endregion

interface RailProps {
  selectedSlotRef: SelectedSlotRef | null;
  // CardDocument | undefined, not just CardDocument: useCardDocumentsByIdentifier's own return
  // type (cardDocumentsSlice.ts) is deliberately widened to include undefined - a project
  // member's CardDocument may not have been fetched yet, and the missing annotation used to
  // hide that from tsc entirely (see that file's own comment, task #135). Every actual field
  // access below already goes through `?.`, so this is a type-only fix - no behavior change.
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined };
  backendURL: string;
  // Called after Slot Actions' Delete - see SlotActionsSection's own prop comment for why the
  // rail needs to hand control back to the page rather than just re-rendering its own subtree.
  onSlotDeleted: () => void;
  /** Funnel round (F4/F5, XF6) - already bound to this Rail's own (face, slot) by the caller
   * (see SelectVersionSection's own prop comment); threaded straight through to it. */
  onImplicitSupport?: (
    candidateIdentifier: string,
    supportTagNames: string[]
  ) => void;
}

const Rail = ({
  selectedSlotRef,
  cardDocumentsByIdentifier,
  backendURL,
  onSlotDeleted,
  onImplicitSupport,
}: RailProps) => {
  // Rail-delegacy round - the old six-key `expandedSections` accordion state is gone with the
  // grey sections it drove; the two remaining disclosures ("More details", the D14 identify
  // panel) each get their own plain boolean, defaulting closed per slot (this component fully
  // remounts on slot change via its caller's own `key`, so these reset for free - see
  // LeftRailOffcanvas's own comment on that `key`).
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [identifyOpen, setIdentifyOpen] = useState(false);
  // EP6 - which face's art the rail-head subject preview currently shows; `null` means "the
  // slot's own editing face" (the default, reset on every slot change for the same reason as
  // `detailsOpen`/`identifyOpen` above).
  const [faceOverride, setFaceOverride] = useState<Faces | null>(null);
  // EP9 - the D14 pill's compare-reveal, lifted here since the trigger (ConfidenceElement,
  // inside PromotedZone) and the reveal itself (anchored beside the subject image, inside
  // RailHeader) are sibling components. `compareOpen` covers BOTH the click-toggle (persists
  // until toggled again or a hover leaves) and the hover/focus show/hide pair - see
  // `ConfidenceElement`'s own `compareProps` for how the two compose without fighting each other.
  const [compareOpen, setCompareOpen] = useState(false);

  const projectMember = useAppSelector((state) =>
    selectedSlotRef != null
      ? selectProjectMember(state, selectedSlotRef.face, selectedSlotRef.slot)
      : undefined
  );
  const query = projectMember?.query;

  // EP6 - the OTHER face's own ProjectMember (Front/Back are separate slots in this app's data
  // model, not two sides of one card - see RailHeader's own module comment). Always computed
  // (never conditionally-called) so this hook call is unconditional regardless of
  // `selectedSlotRef`, matching `projectMember`'s own pattern just above.
  const otherFace: Faces | null =
    selectedSlotRef != null
      ? selectedSlotRef.face === Front
        ? Back
        : Front
      : null;
  const otherProjectMember = useAppSelector((state) =>
    selectedSlotRef != null && otherFace != null
      ? selectProjectMember(state, otherFace, selectedSlotRef.slot)
      : undefined
  );

  if (selectedSlotRef == null) {
    return (
      <div
        className="text-muted text-center fst-italic p-4"
        data-testid="display-rail-idle"
      >
        Select a card on the sheet to see its details.
      </div>
    );
  }

  const selectedImage = projectMember?.selectedImage;
  const cardName =
    selectedImage != null
      ? cardDocumentsByIdentifier[selectedImage]?.name
      : undefined;

  const selectedCardDocument =
    selectedImage != null
      ? cardDocumentsByIdentifier[selectedImage]
      : undefined;

  const otherCardDocument =
    otherProjectMember?.selectedImage != null
      ? cardDocumentsByIdentifier[otherProjectMember.selectedImage]
      : undefined;

  const previewFace = faceOverride ?? selectedSlotRef.face;
  const previewCardDocument =
    previewFace === selectedSlotRef.face
      ? selectedCardDocument
      : otherCardDocument;

  const resolvedPrinting =
    selectedCardDocument?.canonicalCard ??
    selectedCardDocument?.suggestedCanonicalCard ??
    null;
  const comparePrinting =
    resolvedPrinting != null
      ? {
          expansionCode: resolvedPrinting.expansionCode,
          collectorNumber: resolvedPrinting.collectorNumber,
        }
      : null;

  return (
    <RailRoot data-testid="display-rail-content">
      <RailHeader
        face={selectedSlotRef.face}
        slot={selectedSlotRef.slot}
        cardName={cardName}
        searchQuery={query}
        cardDocument={selectedCardDocument}
        previewFace={previewFace}
        previewCardDocument={previewCardDocument}
        onToggleFace={setFaceOverride}
        onSlotDeleted={onSlotDeleted}
        compareOpen={compareOpen}
        comparePrinting={comparePrinting}
      />
      {/* E2 (#2/#3) - the promoted, always-visible zone: D14 confidence element + "More details"
          (amendment 1) + the identify panel that hangs off it (item 6) + artist support line,
          none of which are collapsible accordion sections (D3). Fix round
          (SPEC-display-left-rail.md §3): ConfidenceElement renders BEFORE ArtistSection - it is
          identity, not demoted metadata; see PromotedZone's own comment for the full ordering
          rationale. */}
      <PromotedZone
        cardDocument={selectedCardDocument}
        backendURL={backendURL}
        identifyOpen={identifyOpen}
        onToggleIdentify={() => setIdentifyOpen((previous) => !previous)}
        detailsOpen={detailsOpen}
        onToggleDetails={() => setDetailsOpen((previous) => !previous)}
        compareOpen={compareOpen}
        onCompareToggle={() => setCompareOpen((previous) => !previous)}
        onCompareShow={() => setCompareOpen(true)}
        onCompareHide={() => setCompareOpen(false)}
      />
      {/* Fix round (SPEC-display-left-rail.md §4): the Sources accordion - sources gate art
          availability, so the owner brief puts it in the LEFT rail (a deviation from
          proposal-h-display-layout-spec.md §4.2's right-rail placement - see
          SourcesAccordion.tsx's own module comment for the full note). Sits between the promoted
          identity zone and Select Version, matching the mockup's own left-rail order. NOT one of
          the nine removed grey sections (SPEC-rail-delegacy.md §B/RD - owner answer #3).*/}
      <SourcesAccordion />
      {/* E2/E3/L4 - Select Version, promoted + always open (renamed from "Choose Image", no
          collapse chrome at all - the primary art surface, not one accordion among several).
          Density (§2): `px-2 pt-2` (8/8-top) -> explicit `8px 10px`. O1 fix round
          (SPEC-display-left-rail.md §D.1, corrected 2026-07-23) - this wrapper gains a
          `select-version-wrapper` class carrying the normalized `#16202b` bottom hairline (see
          RailRoot's own rule below) - it had no block-boundary divider of its own before. */}
      <div
        className="select-version-wrapper sv"
        style={{ padding: "8px 10px" }}
      >
        <h6 className="select-version-heading">Select Version</h6>
        <SelectVersionSection
          face={selectedSlotRef.face}
          slot={selectedSlotRef.slot}
          query={query}
          selectedImage={selectedImage}
          backendURL={backendURL}
          onImplicitSupport={onImplicitSupport}
        />
      </div>
      {/* Rail-delegacy round (item 7, RD5)/editor-polish item 4 (REV RD5) - Print Options +
          Report collapse into ONE designed control stack (Slot Actions moved up to the rail
          head - see ControlStack's own comment). AddCardToProjectForm is deliberately not
          mounted (the slot is already in the project). */}
      <ControlStack selectedCardDocument={selectedCardDocument} />
    </RailRoot>
  );
};

export function DisplayPage() {
  const dispatch = useAppDispatch();
  const projectMembers = useAppSelector(selectProjectMembers);
  const projectCardback = useAppSelector(selectProjectCardback);
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);
  const frontsVisible = useAppSelector(selectFrontsVisible);
  // E17/E18 (X18) - the sheet's own dark loading/failed slot states use the SAME coarse,
  // whole-app fetch-status flag CardGrid.tsx already reads for its own loading affordance,
  // rather than a per-query resolved-candidates check (which would need per-slot store access
  // from inside a plain .map() callback, outside a selector context) - an approximation, not
  // E17's literal per-query condition, documented as a deviation in this task's own report.
  const searchResultsLoading = useAppSelector(
    (state) => state.searchResults.status === "loading"
  );
  const cardDocumentsByIdentifier = useCardDocumentsByIdentifier();

  // Issue #275 (design doc ADDENDUM D9) - the silent local draft auto-backup (F1) and the
  // pre-print save gate (F3). ONE instance of each, here - both FinishFooter and
  // DeckInputLanding below are handed the relevant pieces as props rather than each mounting
  // their own hook instance (see useProjectDraftBackup.ts's own module comment on why a second
  // instance would duplicate the debounced-write effect).
  const draftBackup = useProjectDraftBackup();
  const prePrintSaveGate = usePrePrintSaveGate({
    flushDraftNow: draftBackup.flushDraftNow,
    notifyPromoteDraftPrePrint: draftBackup.notifyPromoteDraftPrePrint,
  });

  // Proposal H switchover (2026-07-23, issues #231/#272) - ported verbatim from
  // `ProjectEditor.tsx`'s own beforeunload guard, which this page replaces. That guard lived only
  // in the classic component's function body, never extracted to a shared hook, so it did NOT
  // "naturally inherit" onto this page the way most reused instruments did - without this block,
  // the unrouted classic page taking the beforeunload warning with it would have been a silent,
  // real safety-net regression (closing/reloading a tab with unsaved cards would warn no one).
  // Must NOT fire for the app's own chunk-load-error recovery reload (chunkErrorRecovery.ts) -
  // see ProjectEditor.tsx's own comment (still present there, component unrouted but left
  // in-tree) for the full diagnosis this mirrors.
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!isProjectEmpty && !isRecoveryReloadInFlight()) {
        event.preventDefault();
        return false;
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => {
      window.removeEventListener("beforeunload", handler);
    };
  }, [isProjectEmpty]);

  const [settings, setSettings] = useState<DisplaySheetSettings>(
    DEFAULT_SHEET_SETTINGS
  );
  const [selectedSlotRef, setSelectedSlotRef] =
    useState<SelectedSlotRef | null>(null);
  // EP6 (item 6/E24, SPEC-editor-polish.md §D.8 `.slot-flip`) - which slots (by their own
  // `entry.slot` number, not page-relative index - the same slot can appear on different pages
  // across re-layouts) are currently previewing their OTHER face on the SHEET itself, via the
  // reserved corner `⟲` button. Distinct from `activeFace` (the project-wide Fronts/Backs view
  // setting) - this is a per-slot, sheet-local override on top of it, the same "preview only,
  // doesn't touch selection state" posture `Rail`'s own `faceOverride` takes for the rail-head
  // subject box.
  const [flippedPreviewSlots, setFlippedPreviewSlots] = useState<Set<number>>(
    new Set()
  );

  // Issue #267 (design doc ADDENDUM D12/F9) - the populated-state search bar's dual Add/Browse
  // mode. One boolean drives BOTH the search bar's own mode toggle and the center region's
  // "Print sheets"/"Browse results" switch (see DisplayBodyRegion's own render below) - the
  // mockup's real JS (setBrowse(on)) demonstrates these as one combined state, not two
  // independently toggleable pieces of state, so that's what's implemented here rather than the
  // more elaborate reading the spec prose alone could suggest. The search bar's own text is
  // shared between both modes too (Add mode's ImportText "inline" variant vs. Browse mode's
  // CatalogBrowseResults query) - see the action bar's own render below for why ImportText
  // itself stays entirely unaware of Browse mode (additive-prop-only constraint).
  const [isBrowseMode, setIsBrowseMode] = useState(false);
  const [searchBarText, setSearchBarText] = useState("");

  // Issue #266 (design doc §4) - which tier drives the left rail's drawer placement (phone:
  // bottom sheet, tablet: start drawer; laptop/desktop: inline, where placement is moot - see
  // LeftRailOffcanvas's own comment) and the gear button's visibility.
  const viewportTier = useViewportTier();
  const leftPlacement: OffcanvasPlacement =
    viewportTier === "phone" ? "bottom" : "start";
  const [leftRailOpen, setLeftRailOpen] = useState(false);
  const [rightRailOpen, setRightRailOpen] = useState(false);
  // Design doc §4's "two overlays, one screen" invariant - opening either rail closes the other,
  // so they never stack below their own inline tier. Harmless to call at inline tiers too:
  // Offcanvas ignores `show` there entirely (see its own source - `hideResponsiveOffcanvas`
  // forces the portal closed once the viewport reaches the `responsive` breakpoint).
  const openLeftRail = () => {
    setRightRailOpen(false);
    setLeftRailOpen(true);
  };
  const openRightRail = () => {
    setLeftRailOpen(false);
    setRightRailOpen(true);
  };

  const activeFace: Faces = frontsVisible ? Front : Back;

  // Landscape: PDF.tsx's own PageSize table is portrait-oriented (matches the classic PDF
  // export's own page-size semantics, unchanged there) - swapping width/height here is what
  // makes THIS page's sheet landscape, per the design doc's own default. See the design doc's
  // §1 for the computeLayout() math confirming this yields a 4x2 grid at A4 + realistic bleed.
  const portraitSize = getPageSizeMM(settings.pageSize, undefined, undefined);
  const sheetWidthMM = portraitSize.height;
  const sheetHeightMM = portraitSize.width;

  // Issue #266 (design doc §2, D1) - fit-to-width: the sheet region measures its own real
  // available width, and the rendered sheet is the SMALLER of that and SHEET_MAX_WIDTH_PX - no
  // PagePreview change, this only changes what's passed into its existing maxWidthPx prop. The
  // landscape page's own aspect ratio (already handled by PagePreview's scale-to-fit math) is
  // what naturally "letterboxes" it on a narrow viewport - the whole page shrinks proportionally,
  // it isn't a separately-drawn letterbox frame. Quantized to the nearest 8px so a sub-pixel
  // ResizeObserver jitter (common when a scrollbar appears/disappears) doesn't cause a visible
  // reflow loop.
  const [sheetRenderWidthPx, setSheetRenderWidthPx] =
    useState<number>(SHEET_MAX_WIDTH_PX);

  // The sheet-region div doesn't exist at the very first (empty-project) mount - this page's own
  // early-return below swaps the whole tree to `DeckInputLanding` until a project actually
  // starts - so the ResizeObserver has to attach lazily, once the real div mounts, not just once
  // at component-mount time. A callback ref writing into state (React's own documented pattern
  // for "an effect that needs to react to a DOM node changing", since a plain ref object's
  // mutation is invisible to React and won't re-run a dependent effect) is what makes the effect
  // below re-run whenever that div mounts/unmounts/remounts - covering the empty→populated
  // transition and any StrictMode-driven remount identically, with no risk of a stale observer
  // instance surviving past its own node (an earlier lazy-ref-initialized single ResizeObserver
  // wired up via ad hoc disconnect()/observe() calls in the ref callback itself was NOT
  // StrictMode-safe: dev-mode's double invoke of mount/cleanup could leave more than one live
  // observer instance racing to set this state, with a stale one's oversized last-fired
  // measurement winning and never getting corrected - see docs/troubleshooting.md's entry on
  // this, filed after CI caught the resulting overlap in `SelectVersionSection.spec.ts`).
  const [sheetRegionNode, setSheetRegionNode] = useState<HTMLDivElement | null>(
    null
  );
  const sheetRegionRef = useCallback((element: HTMLDivElement | null) => {
    setSheetRegionNode(element);
  }, []);

  useEffect(() => {
    if (sheetRegionNode == null || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const measuredWidthPx = entries[0]?.contentRect.width;
      if (measuredWidthPx == null || measuredWidthPx <= 0) {
        return;
      }
      const clampedWidthPx = Math.min(SHEET_MAX_WIDTH_PX, measuredWidthPx);
      setSheetRenderWidthPx(Math.max(160, Math.round(clampedWidthPx / 8) * 8));
    });
    observer.observe(sheetRegionNode);
    return () => observer.disconnect();
  }, [sheetRegionNode]);

  // Matches PagePreview's own internal scale-to-fit math exactly (scale = maxWidthPx /
  // pageWidthMM-in-px, height = pageHeightMM-in-px * scale - the px-per-mm factor cancels out),
  // so this estimate is exact, not approximate - RenderIfVisible's defaultHeight/visibleOffset
  // never has to correct a wrong guess via its own ResizeObserver fallback. Derives from the same
  // measured sheetRenderWidthPx (not the fixed cap) so virtualization placeholders stay exact at
  // every viewport, not just the desktop one.
  const sheetPixelHeightPx =
    sheetRenderWidthPx * (sheetHeightMM / sheetWidthMM);

  // Proposal H D5 (docs/proposals/proposal-h-display-layout-spec.md) - no longer a hardcoded
  // `useMemo` constant (was `{ top: 5, bottom: 5, left: 5, right: 5 }`): this is now live state
  // (marginProfileSlice), seeded from D5's Borderless default and made user-editable by the
  // right rail's Margin profile control below (MARGIN_PROFILES, marginProfiles.ts). Every
  // existing consumer (computeLayout, PagePreview's margins prop, exportPdfProps' pageMargin*MM)
  // stays wired to this same value, so the control moves the on-screen sheet and the exported
  // PDF in lockstep with no extra plumbing - mirrors D18/D19's own cardSpacing precedent exactly.
  const marginProfile = useAppSelector(selectMarginProfile).profile;
  const margins = useMemo(
    () => MARGIN_PROFILES[marginProfile].margins,
    [marginProfile]
  );
  // Proposal H D18/D19 (docs/proposals/proposal-h-display-layout-spec.md) - no longer a hardcoded
  // constant: this is now live state (cardSpacingSlice), seeded from D18's asymmetric default
  // (0mm horizontal / 14.5mm vertical) and made user-editable by the right rail's Card Spacing
  // control below. Every existing consumer (computeLayout, PagePreview's spacing prop,
  // exportPdfProps' cardSpacingRowMM/ColMM) stays wired to this same value, so the control moves
  // the on-screen sheet and the exported PDF in lockstep with no extra plumbing.
  const spacing = useAppSelector(selectCardSpacing);

  // Still needed below (SelectVersionSection's own backendURL prop) - issue #275 removed every
  // OTHER consumer this used to have (the inline export pipeline, see this file's own module
  // comment for where that pipeline moved).
  const backendURL = useAppSelector(selectRemoteBackendURL);

  // Funnel round (funnel-spec.md F4d, XF6) - per-slot "what did we last implicitly cast for this
  // slot's currently-picked candidate" bookkeeping. Lives HERE, above <Rail>, deliberately: Rail
  // fully remounts (via its own `key`) every time the selected slot changes (see the `<Rail
  // key=.../>` comment below), so any state this retraction logic needs has to survive that
  // remount - a plain ref (not reactive state; nothing here ever needs to trigger a re-render)
  // keyed by "face-slot" is the simplest thing that does.
  const lastImplicitSupportRef = useRef<
    Record<string, { identifier: string; tagNames: string[] }>
  >({});

  // Funnel round (funnel-spec.md F4b/F4d) - called on every pick made through the funnel (see
  // SelectVersionResults.tsx's own handleSelect), even when `supportTagNames` is empty: retracts
  // whatever this slot's PREVIOUS pick cast (if anything), then casts `supportTagNames` for the
  // new one. Both calls are fire-and-forget and silently swallow failures - "the pick itself
  // always succeeds; voting is a best-effort side effect" (funnel-spec.md F4/D24) - a refused or
  // failed implicit vote must never surface a user-visible error.
  const handleImplicitSupport = (
    face: Faces,
    slot: number,
    candidateIdentifier: string,
    supportTagNames: string[]
  ) => {
    if (backendURL == null) {
      return;
    }
    const key = `${face}-${slot}`;
    const anonymousId = getOrCreateAnonymousId();
    const previous = lastImplicitSupportRef.current[key];
    if (previous != null) {
      previous.tagNames.forEach((tagName) => {
        APIRetractImplicitVote(
          backendURL,
          previous.identifier,
          anonymousId,
          tagName
        ).catch(() => undefined);
      });
    }
    if (supportTagNames.length > 0) {
      APICastImplicitVote(
        backendURL,
        candidateIdentifier,
        anonymousId,
        supportTagNames
      ).catch(() => undefined);
      lastImplicitSupportRef.current[key] = {
        identifier: candidateIdentifier,
        tagNames: supportTagNames,
      };
    } else {
      delete lastImplicitSupportRef.current[key];
    }
  };

  const layout = useMemo(
    // Mirrors PagePreview's own computeLayout() call so cardsPerPage here matches exactly
    // what the sheet itself will render - both this page and PagePreview compute from the
    // same inputs via the same pure function, rather than one deriving cardsPerPage from the
    // other's internals.
    () =>
      computeLayout(
        sheetWidthMM,
        sheetHeightMM,
        CardWidthMM,
        CardHeightMM,
        settings.bleedEdgeMM,
        margins,
        spacing
      ),
    [sheetWidthMM, sheetHeightMM, settings.bleedEdgeMM, margins, spacing]
  );
  const cardsPerPage = layout.cardsPerRow * layout.cardsPerCol;

  const pages = useMemo(
    () => paginateSlotsForDisplay(projectMembers, cardsPerPage),
    [projectMembers, cardsPerPage]
  );
  // Item 3 (owner's hands-on review, flat scroll amendment) - EVERY sheet's slots get resolved
  // here now, not just one page's, since the whole deck renders as one continuous vertical
  // stack. This is still cheap index/string bookkeeping, not image work - the actual per-slot
  // <img> only mounts once RenderIfVisible below decides a given sheet is on/near-screen, which
  // is what keeps this in line with the design doc's original "don't hold more image memory
  // than what's already on screen" rule. Always at least one sheet, even for an empty page's
  // worth of grid capacity - matches the page-shell's pre-flat-scroll behaviour of always
  // showing one (possibly all-placeholder) sheet rather than rendering nothing.
  const sheets = useMemo(
    () =>
      (pages.length > 0 ? pages : [[]]).map((entries, pageIndex) => ({
        pageIndex,
        entries,
        slots: entries.map((entry) => {
          // EP6 - a slot in `flippedPreviewSlots` renders its OTHER face's own resolved image on
          // the sheet itself (preview only - `activeFace`/selection state are untouched); only
          // actually flips when that other face has a real member to show.
          const otherFace = activeFace === Front ? Back : Front;
          const effectiveFace =
            flippedPreviewSlots.has(entry.slot) &&
            entry.member[otherFace] != null
              ? otherFace
              : activeFace;
          const projectMember = entry.member[effectiveFace];
          const identifier = projectMember?.selectedImage;
          const cardDocument =
            identifier != null
              ? cardDocumentsByIdentifier[identifier]
              : undefined;
          const query = projectMember?.query;
          // Item 1 (owner's hands-on review) - a slot with no resolved thumbnail shows this on
          // the sheet itself instead of a blank hole. `undefined` only for a genuinely
          // query-less slot (a shared-cardback back face) - PagePreview then falls back to
          // `name`'s own "Slot N".
          const queryText =
            query?.query != null && query.query.length > 0
              ? `${query.query}${
                  query.expansionCode != null
                    ? ` (${query.expansionCode.toUpperCase()}${
                        query.collectorNumber ? " " + query.collectorNumber : ""
                      })`
                    : ""
                }`
              : undefined;
          // E17/E18 (X18) - a slot with an active query but no resolved image is either still
          // being fetched (dark loading sweep) or definitively empty (dark "no art" mark + the
          // deterministic Scryfall reference link, E17 v1); a genuinely query-less slot (e.g. a
          // shared-cardback back face) gets neither, same as before this round.
          const hasQuery =
            (query?.query != null && query.query.length > 0) ||
            query?.expansionCode != null;
          const loadState: "loading" | "failed" | undefined =
            identifier == null && hasQuery
              ? searchResultsLoading
                ? "loading"
                : "failed"
              : undefined;
          const content: PagePreviewSlotContent = {
            imageUrl: cardDocument?.mediumThumbnailUrl,
            name: cardDocument?.name ?? `Slot ${entry.slot + 1}`,
            queryText,
            loadState,
            findCardUrl:
              loadState === "failed"
                ? buildScryfallReferenceUrl(query)
                : undefined,
            // Foreign-order resilience Phase 1 follow-up (issue #324) - PagePreview's own
            // OrphanBadge equivalent, same "sourceName" text Card.tsx already shows for this
            // identifier on the classic editor surface.
            orphanLabel: cardDocument?.isOrphan
              ? cardDocument.sourceName
              : undefined,
            // EP6/item 6/E24 - a card on EITHER face (not just the currently-effective one) -
            // see PagePreviewSlotContent's own `flippable` comment for why this must be
            // independent of `imageUrl`.
            flippable:
              entry.member.front?.selectedImage != null ||
              entry.member.back?.selectedImage != null,
          };
          return content;
        }),
      })),
    [
      pages,
      activeFace,
      cardDocumentsByIdentifier,
      searchResultsLoading,
      flippedPreviewSlots,
    ]
  );

  // EP6 - toggles a slot's sheet-local face preview (see `flippedPreviewSlots`' own comment).
  const handleSlotFlip = (pageIndex: number, indexOnPage: number) => {
    const entry = sheets[pageIndex]?.entries[indexOnPage];
    if (entry == null) {
      return;
    }
    setFlippedPreviewSlots((previous) => {
      const next = new Set(previous);
      if (next.has(entry.slot)) {
        next.delete(entry.slot);
      } else {
        next.add(entry.slot);
      }
      return next;
    });
  };

  const handleSlotClick = (pageIndex: number, indexOnPage: number) => {
    const entry = sheets[pageIndex]?.entries[indexOnPage];
    if (entry == null) {
      return;
    }
    setSelectedSlotRef({ face: activeFace, slot: entry.slot });
    // Issue #266 (design doc §4.1) - "fixes 'tapping a card shows nothing'": below `lg`, the left
    // rail is a closed-by-default drawer, so selecting a slot must also open it. No-op at `lg`+,
    // where the rail is already inline and ignores `show` entirely.
    openLeftRail();
  };

  // Funnel round (funnel-spec.md F6/D22, XF7) - the /display center sheet's right-click/long-
  // press/⋯-cue context menu. Reuses the EXISTING `CardSlotContextMenu` + `getCardSlotMenuActions`
  // (the same 4-action list `CardSlot.tsx`'s own 3-dot dropdown and SlotActionsSection already
  // share) - "no new action, just three more ways to reach it on /display" per the spec.
  const [contextMenuState, setContextMenuState] = useState<{
    face: Faces;
    slot: number;
    query: SearchQuery | undefined;
    x: number;
    y: number;
  } | null>(null);

  const handleSlotContextMenu = (
    pageIndex: number,
    indexOnPage: number,
    x: number,
    y: number
  ) => {
    const entry = sheets[pageIndex]?.entries[indexOnPage];
    if (entry == null) {
      return;
    }
    const query = entry.member[activeFace]?.query;
    setContextMenuState({ face: activeFace, slot: entry.slot, query, x, y });
  };

  // Which sheet (not just which slot-on-a-page) currently holds the selected slot - needed now
  // that every sheet renders simultaneously, rather than only ever having "the current page"'s
  // own local index to check.
  const selectedSheetIndex =
    selectedSlotRef != null && selectedSlotRef.face === activeFace
      ? sheets.findIndex((sheet) =>
          sheet.entries.some((entry) => entry.slot === selectedSlotRef.slot)
        )
      : -1;

  // Passive "Sheet N of M" scroll-position indicator (design doc's flat-scroll amendment - a
  // read-only reflection of scroll position, not a navigation control like the old prev/next
  // pager). Deliberately its own IntersectionObserver, distinct from RenderIfVisible's below -
  // that one asks "should this sheet's images be mounted at all" (generous, ±1-sheet-ish
  // rootMargin); this one asks "which single sheet is the user currently looking at" (a thin
  // band near vertical centre), and the two thresholds are unrelated by design.
  const sheetRefs = useRef<Array<HTMLDivElement | null>>([]);
  const [visibleSheetIndex, setVisibleSheetIndex] = useState(0);

  useEffect(() => {
    const indexByElement = new Map<Element, number>();
    sheetRefs.current.forEach((element, index) => {
      if (element != null) {
        indexByElement.set(element, index);
      }
    });
    if (indexByElement.size === 0) {
      return;
    }
    const lastIndex = sheets.length - 1;
    // D17 follow-up (docs/troubleshooting.md "sheet-position pill under-reports the last
    // sheet") - the centre-band check below can structurally never see the FIRST or LAST
    // sheet as "current": once the container is scrolled to its true extreme, there's no
    // room left to move a short boundary sheet any further through the centre band (measured
    // directly - at phone width with a short trailing sheet, the container's own maxScroll
    // can be hundreds of px short of what centring that sheet would require). This isn't tied
    // to any one card count or viewport; it's inherent to a fixed centre-band test on a
    // boundary item. So check the real scroll position FIRST, ahead of the centre-band
    // result, on every firing of this same observer - at either true edge of the scrollable
    // container, the boundary sheet IS the one on-screen, full stop.
    const observer = new IntersectionObserver(
      (entries) => {
        const scrollContainer = entries[0]?.target.closest<HTMLElement>(
          '[data-testid="content-container"]'
        );
        if (scrollContainer != null) {
          const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
          const EPSILON = 2;
          if (scrollTop <= EPSILON) {
            setVisibleSheetIndex(0);
            return;
          }
          if (scrollTop + clientHeight >= scrollHeight - EPSILON) {
            setVisibleSheetIndex(lastIndex);
            return;
          }
        }
        const intersectingIndices = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => indexByElement.get(entry.target))
          .filter((index): index is number => index != null);
        if (intersectingIndices.length > 0) {
          setVisibleSheetIndex(Math.min(...intersectingIndices));
        }
      },
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 }
    );
    indexByElement.forEach((_index, element) => observer.observe(element));
    return () => observer.disconnect();
  }, [sheets.length]);

  const clampedVisibleSheetIndex = Math.min(
    visibleSheetIndex,
    sheets.length - 1
  );

  if (isProjectEmpty) {
    return (
      <DeckInputLanding
        restorableDraft={draftBackup.restorableDraft}
        onRestoreDraft={draftBackup.restoreDraft}
        onDismissDraft={draftBackup.dismissRestoreDraft}
      />
    );
  }

  return (
    <div className="d-flex flex-column" data-testid="display-page">
      {/* Issue #266 (design doc §3/§6 R4) - identity + the gear that opens the right rail; the
          settings/export controls this toolbar used to hold unconditionally now live in
          RightRailOffcanvas below (necessarily also half of design doc row T1 - see this file's
          own module comment for why). Issue #267 (design doc §3/§6 T2-T5, ADDENDUM D12/D15) adds
          the populated-state add-cards/browse search bar: a dual-mode Add/Browse
          ToggleButtonGroup, the shared search-bar input (ImportText's "inline" variant in Add
          mode, a plain controlled Form.Control in Browse mode - see ActionBarSearchGroup's own
          comment for why ImportText itself stays unaware of Browse mode), and the existing
          Import.tsx dropdown (D15 - Text/XML/CSV/URL, verbatim, unforked). */}
      <ToolbarRoot
        className="d-flex align-items-center flex-wrap gap-2 px-3 py-2 border-bottom"
        data-testid="display-toolbar"
      >
        {/* D17 (proposal-h-display-layout-spec.md ADDENDUM) retired this action-bar readout in
            favor of ONE floating "n/M" pill living in the center sheet region itself (see
            display-sheet-position-indicator below) - the visibleSheetIndex IntersectionObserver
            above now drives that pill instead of this span. */}

        {/* Issue #165, Proposal G save integration - the same reverse-breadcrumb + Save
            button ProjectEditor.tsx mounts (SavedDeckPanel is fully route-agnostic; only
            the spacing differs - see that component's own comment). Renders nothing at all
            for an anonymous session, matching the editor's degradation exactly. Doubles as
            this toolbar's "deck name" slot (design doc §2's information architecture never
            anticipated saved decks, since Proposal G landed after that doc's own pass - see
            saved-decks.md's "Where it's wired in" section for the full cross-reference). */}
        <SavedDeckPanel className="" />

        <ActionBarSearchGroup data-testid="display-search-bar-group">
          <ToggleButtonGroup
            type="radio"
            name="display-search-mode"
            value={isBrowseMode ? "browse" : "add"}
            onChange={(value) => setIsBrowseMode(value === "browse")}
          >
            <ToggleButton
              id="display-search-mode-add"
              value="add"
              variant="outline-secondary"
              size="sm"
              data-testid="display-search-mode-add"
            >
              Add
            </ToggleButton>
            <ToggleButton
              id="display-search-mode-browse"
              value="browse"
              variant="outline-secondary"
              size="sm"
              data-testid="display-search-mode-browse"
            >
              Browse
            </ToggleButton>
          </ToggleButtonGroup>

          {isBrowseMode ? (
            // Browse mode: the same shared searchBarText state, bound to a plain controlled
            // input rather than ImportText - CatalogBrowseResults (mounted in the center region
            // below) debounces off this value itself, there is no submit step here at all.
            <Form.Control
              size="sm"
              type="text"
              placeholder="Search the catalog… (e.g. Lightning Bolt)"
              value={searchBarText}
              onChange={(event) => setSearchBarText(event.target.value)}
              aria-label="catalog-browse-search"
              data-testid="display-browse-search-input"
            />
          ) : (
            <ImportText
              variant="inline"
              textValue={searchBarText}
              onTextChange={setSearchBarText}
              onImportComplete={() => setSearchBarText("")}
            />
          )}

          {/* Design doc ADDENDUM D15 (= §6 T4, restated) - the existing Import.tsx dropdown
              (Text/XML/CSV/URL *Button modal variants), mounted verbatim: no new importer UI,
              closes the "add cards to a non-empty project" parity gap #267 names. */}
          <Import />
        </ActionBarSearchGroup>

        {/* Design doc ADDENDUM D13 (issue #267's landing/search-bar feedback half) - self-hides
            when selectInvalidIdentifiersCount === 0, so this costs nothing when the project is
            clean. Its own flex-basis:100% (see the className below) keeps it from squeezing the
            bar's other controls - it wraps onto its own row only when it actually has something
            to show. */}
        <div className="w-100" style={{ order: 20 }}>
          <InvalidIdentifiersStatus />
        </div>

        {/* Design doc §1's region table: hidden entirely at desktop (≥1200, xl) where the right
            rail is already inline - visible at every narrower tier, where it's the only way to
            open it. */}
        <Button
          size="sm"
          variant="outline-secondary"
          className="ms-auto d-xl-none"
          onClick={openRightRail}
          aria-expanded={rightRailOpen}
          data-testid="display-gear-button"
          aria-label="Print & Settings"
        >
          <RightPaddedIcon bootstrapIconName="gear" />
          Print &amp; Settings
        </Button>
      </ToolbarRoot>

      <DisplayBodyRegion>
        {/* Issue #266 (design doc §4.1) - ONE node, all widths: inline sticky 380px column at
            `lg`+, `placement="start"` drawer on tablet, `placement="bottom"` 72vh sheet on phone
            (leftPlacement, driven by useViewportTier.ts). Opens on slot tap below `lg`
            (handleSlotClick's own openLeftRail call) - closing does NOT clear selectedSlotRef, so
            re-opening (gear/handle/another slot tap) comes back to the same card. */}
        <LeftRailOffcanvas
          show={leftRailOpen}
          onHide={() => setLeftRailOpen(false)}
          responsive="lg"
          placement={leftPlacement}
          data-testid="display-rail"
          aria-label="Card details and art selection"
        >
          {leftPlacement === "bottom" && (
            <div
              className="d-flex justify-content-center pt-2 pb-1 d-lg-none"
              role="button"
              aria-label="Dismiss"
              onClick={() => setLeftRailOpen(false)}
            >
              <span
                style={{
                  width: 44,
                  height: 5,
                  borderRadius: 3,
                  backgroundColor: "var(--bs-border-color-translucent)",
                  display: "block",
                }}
              />
            </div>
          )}
          <Offcanvas.Header closeButton>
            <Offcanvas.Title>Card details</Offcanvas.Title>
          </Offcanvas.Header>
          <Offcanvas.Body>
            {/* `key` here (not inside Rail itself) is what actually forces a remount on slot
                change - a key set on an element INSIDE a component's own render output has no
                effect on that same component's hooks; only the key the PARENT assigns to the
                component element does. Caught by this page's own Playwright suite: without this,
                expandedSections silently persisted across slot selections instead of resetting to
                the documented per-slot default (see the design doc's §4.2). */}
            <Rail
              key={
                selectedSlotRef != null
                  ? `${selectedSlotRef.face}-${selectedSlotRef.slot}`
                  : "idle"
              }
              selectedSlotRef={selectedSlotRef}
              cardDocumentsByIdentifier={cardDocumentsByIdentifier}
              backendURL={backendURL ?? ""}
              onSlotDeleted={() => setSelectedSlotRef(null)}
              onImplicitSupport={
                selectedSlotRef != null
                  ? (candidateIdentifier, supportTagNames) =>
                      handleImplicitSupport(
                        selectedSlotRef.face,
                        selectedSlotRef.slot,
                        candidateIdentifier,
                        supportTagNames
                      )
                  : undefined
              }
            />
          </Offcanvas.Body>
        </LeftRailOffcanvas>

        <div
          ref={sheetRegionRef}
          className="flex-grow-1 d-flex flex-column align-items-center p-3"
          data-testid="display-sheet-region"
          style={{ minWidth: 0, width: "100%" }}
        >
          {/* Design doc ADDENDUM D12/F10 - the center region's own "Print sheets"/"Browse
              results" switch, bound to the SAME isBrowseMode state the action bar's Add/Browse
              toggle drives (see that state's own comment) - two controls for one state, not two
              independent ones, matching the mockup's real behavior. */}
          <ToggleButtonGroup
            type="radio"
            name="display-center-view"
            value={isBrowseMode ? "browse" : "sheets"}
            onChange={(value) => setIsBrowseMode(value === "browse")}
            className="mb-2"
          >
            <ToggleButton
              id="display-center-view-sheets"
              value="sheets"
              variant="outline-secondary"
              size="sm"
              data-testid="display-center-view-sheets"
            >
              Print sheets
            </ToggleButton>
            <ToggleButton
              id="display-center-view-browse"
              value="browse"
              variant="outline-secondary"
              size="sm"
              data-testid="display-center-view-browse"
            >
              Browse results
            </ToggleButton>
          </ToggleButtonGroup>

          {isBrowseMode ? (
            <CatalogBrowseResults query={searchBarText} />
          ) : (
            <>
              {/* D17 (proposal-h-display-layout-spec.md ADDENDUM) - the single floating "n/M"
                  sheet-position indicator that replaces BOTH the removed per-sheet "Sheet N of M"
                  label lines below and the action bar's own retired static readout (see that
                  comment above). `position: sticky` + `alignSelf: flex-end` floats it at the
                  top-right of this flex column; it's a child of the center region only, so it's
                  structurally confined there and can never collide with either rail/drawer at any
                  breakpoint (they're siblings or portaled elsewhere). `pointerEvents: none` so it
                  never eats a scroll/tap. Driven by the same visibleSheetIndex
                  IntersectionObserver above - no new observer, just a new place to write it. */}
              <div
                data-testid="display-sheet-position-indicator"
                aria-live="polite"
                className="bg-dark bg-opacity-75 text-light rounded-pill px-3 py-1 small border"
                style={{
                  position: "sticky",
                  top: 8,
                  alignSelf: "flex-end",
                  marginBottom: -30,
                  zIndex: 5,
                  pointerEvents: "none",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {clampedVisibleSheetIndex + 1}
                <span className="mx-1 text-secondary">/</span>
                {sheets.length}
              </div>
              {sheets.map((sheet) => (
                <div
                  key={sheet.pageIndex}
                  ref={(element) => {
                    sheetRefs.current[sheet.pageIndex] = element;
                  }}
                  data-sheet-index={sheet.pageIndex}
                  data-testid="display-sheet-wrapper"
                  className="d-flex flex-column align-items-center"
                  style={{ marginBottom: 4 }}
                >
                  {/* Sheet-level virtualization (Item 3's benchmark-gated requirement): only the
                    sheet(s) within one sheet-height of the viewport actually mount their
                    PagePreview (real <img> tags); everything further away is a fixed-height
                    placeholder div, per RenderIfVisible's own contract - see this component's
                    module comment for why a from-scratch IntersectionObserver wasn't needed here.
                    The first sheet starts mounted unconditionally so the common single-sheet case
                    never waits on an observer round-trip. */}
                  <RenderIfVisible
                    initialVisible={sheet.pageIndex === 0}
                    defaultHeight={sheetPixelHeightPx}
                    visibleOffset={sheetPixelHeightPx}
                  >
                    <PagePreview
                      pageWidthMM={sheetWidthMM}
                      pageHeightMM={sheetHeightMM}
                      bleedEdgeMM={settings.bleedEdgeMM}
                      margins={margins}
                      spacing={spacing}
                      slots={sheet.slots}
                      showCutLines={settings.showCutLines}
                      maxWidthPx={sheetRenderWidthPx}
                      // R7/D17 - screen-only presentation (no white fill/box-shadow, a hairline
                      // pinline instead); the exported PDF (exportPdfProps above) never reads
                      // this prop, so print output is untouched.
                      screenPresentation
                      onSlotClick={(indexOnPage) =>
                        handleSlotClick(sheet.pageIndex, indexOnPage)
                      }
                      selectedSlotIndex={
                        selectedSheetIndex === sheet.pageIndex
                          ? sheet.entries.findIndex(
                              (entry) => entry.slot === selectedSlotRef?.slot
                            )
                          : undefined
                      }
                      onSlotContextMenu={(indexOnPage, x, y) =>
                        handleSlotContextMenu(
                          sheet.pageIndex,
                          indexOnPage,
                          x,
                          y
                        )
                      }
                      onSlotFlip={(indexOnPage) =>
                        handleSlotFlip(sheet.pageIndex, indexOnPage)
                      }
                    />
                  </RenderIfVisible>
                </div>
              ))}
            </>
          )}
        </div>

        {/* Funnel round (funnel-spec.md F6/D22, XF7) - one shared context menu for whichever
            sheet slot was right-clicked/long-pressed/⋯-tapped; `CardSlotContextMenu` itself is
            fixed-positioned at (x, y) so mounting it once here (rather than once per slot) is
            enough. */}
        {contextMenuState != null && (
          <CardSlotContextMenu
            actions={getCardSlotMenuActions({
              onChangeQuery: () => {
                const { face, slot, query } = contextMenuState;
                let stringifiedSearchQuery: string | null = null;
                if (query?.query) {
                  stringifiedSearchQuery = query.query;
                  if (query.expansionCode) {
                    stringifiedSearchQuery += ` (${query.expansionCode})`;
                    if (query.collectorNumber) {
                      stringifiedSearchQuery += ` ${query.collectorNumber}`;
                    }
                  }
                }
                dispatch(
                  showChangeQueryModal({
                    slots: [[face, slot]],
                    query: stringifiedSearchQuery,
                  })
                );
              },
              onDuplicate: () =>
                dispatch(
                  duplicateSlot({ slot: contextMenuState.slot, quantity: 1 })
                ),
              onDelete: () => {
                dispatch(deleteSlots({ slots: [contextMenuState.slot] }));
                if (selectedSlotRef?.slot === contextMenuState.slot) {
                  setSelectedSlotRef(null);
                }
              },
              onUnfilterPrinting: () =>
                dispatch(
                  bulkRemovePrintingFilter({
                    slots: [[contextMenuState.face, contextMenuState.slot]],
                  })
                ),
              showUnfilterPrinting: !!doesSearchQueryFilterOnPrinting(
                contextMenuState.query
              ),
            })}
            position={{ x: contextMenuState.x, y: contextMenuState.y }}
            onClose={() => setContextMenuState(null)}
          />
        )}

        {/* Issue #266 (design doc §4.2) - editing settings + preparing print, ONE node, all
            widths: inline sticky 300px column at `xl`+ (≥1200 - the region table's own "Laptop
            deliberately keeps the right rail as a drawer" call, 380+300 doesn't fit under the
            1200px ContentMaxWidth cap), `placement="end"` drawer everywhere narrower, opened by
            the action bar's gear button. Content here is the same components the toolbar used to
            mount unconditionally, relocated verbatim - not yet the design doc's own
            `AutofillCollapse` per-section chrome (deferred, see this file's own module comment). */}
        <RightRailOffcanvas
          show={rightRailOpen}
          onHide={() => setRightRailOpen(false)}
          responsive="xl"
          placement="end"
          style={
            {
              "--bs-offcanvas-width": "min(92vw, 320px)",
            } as React.CSSProperties
          }
          data-testid="display-print-settings-rail"
          aria-label="Print and project settings"
        >
          <Offcanvas.Header closeButton>
            <Offcanvas.Title>Print &amp; Settings</Offcanvas.Title>
          </Offcanvas.Header>
          <Offcanvas.Body className="d-flex flex-column p-0">
            <div className="flex-grow-1 overflow-auto p-3">
              <div className="mb-3">
                <h6>Page Setup</h6>
                <Form.Select
                  size="sm"
                  className="mb-2"
                  value={settings.pageSize}
                  onChange={(event) =>
                    setSettings((previous) => ({
                      ...previous,
                      pageSize: event.target.value as keyof typeof PageSize,
                    }))
                  }
                  aria-label="Paper size"
                >
                  {Object.keys(PageSize)
                    .filter((key) => key !== "CUSTOM")
                    .map((key) => (
                      <option key={key} value={key}>
                        {key} (landscape)
                      </option>
                    ))}
                </Form.Select>

                <Form.Group className="mb-2">
                  <Form.Label className="small mb-1">
                    Bleed edge (mm)
                  </Form.Label>
                  <Form.Control
                    size="sm"
                    type="number"
                    min={0}
                    step={0.1}
                    value={settings.bleedEdgeMM}
                    onChange={(event) => {
                      const value = parseFloat(event.target.value);
                      if (!Number.isNaN(value)) {
                        setSettings((previous) => ({
                          ...previous,
                          bleedEdgeMM: value,
                        }));
                      }
                    }}
                    aria-label="Bleed edge (mm)"
                  />
                </Form.Group>

                {/* D5 (proposal-h-display-layout-spec.md) - the margin-profile control: no
                    `max` clamp on the Bleed edge input above (removed the old `max={BleedEdgeMM}`
                    cap - 3.048mm, below the new 3.175mm default) since the task's own instruction
                    is to WARN, never hard-clamp, when a bleed edge exceeds a profile's cap; this
                    control surfaces that warning instead. */}
                <MarginProfileControl
                  profile={marginProfile}
                  onChange={(profile: MarginProfileKey) =>
                    dispatch(setMarginProfile(profile))
                  }
                  bleedEdgeMM={settings.bleedEdgeMM}
                  pageWidthMM={sheetWidthMM}
                  cardWidthMM={CardWidthMM}
                  spacingColMM={spacing.col}
                />

                <Form.Check
                  type="switch"
                  id="display-cut-lines-toggle"
                  label="Guides"
                  checked={settings.showCutLines}
                  onChange={(event) =>
                    setSettings((previous) => ({
                      ...previous,
                      showCutLines: event.target.checked,
                    }))
                  }
                />

                {/* D19 (proposal-h-display-layout-spec.md ADDENDUM) - Horizontal (X ->
                    spacing.col) / Vertical (Y -> spacing.row) numeric inputs + a link/unlink
                    toggle, seeded from D18's asymmetric default and persisted per deck via the
                    cardSpacing redux slice -> deckPayload.ts (mirrors finishSettingsSlice's own
                    precedent - see that slice's module comment). Extracted into its own
                    component (CardSpacingControl.tsx) for a plain unit-test target on the
                    link/unlink behavior. */}
                <CardSpacingControl
                  spacing={spacing}
                  onChangeCol={(value) => dispatch(setCardSpacingCol(value))}
                  onChangeRow={(value) => dispatch(setCardSpacingRow(value))}
                />
              </div>

              <div className="mb-3">
                <h6>View</h6>
                <Button
                  size="sm"
                  variant="outline-secondary"
                  onClick={() => dispatch(toggleFaces())}
                >
                  {frontsVisible ? "Showing: Fronts" : "Showing: Backs"}
                </Button>
              </div>

              <div className="mb-3">
                {/* No section heading here (unlike Page Setup/View above) - the button's own
                    label already reads "Cardback", and a separate identical-text heading would
                    make any future generic getByText("Cardback") locator ambiguous, exactly the
                    ambiguity the Search Settings section right below used to hit (see this file's
                    own history/PR notes). Issue #240 (design doc §5's CommonCardback row) - a
                    project-wide setting (true of the whole deck, not one selected slot),
                    relocated here unmodified - opens the same GridSelectorModal instance
                    CommonCardback.tsx's editor mount already owns (see that component's own
                    CardbackToolbarButton comment). */}
                <CardbackToolbarButton />
              </div>

              <div>
                {/* Issue #239 (design doc §5's SearchSettings row) - the same self-contained
                    trigger-button-plus-modal ProjectEditor.tsx already mounts, relocated here
                    unmodified: same Modal, same searchSettingsSlice read/write, same
                    setLocalStorageSearchSettings persistence path. No section heading (see the
                    Cardback div above) - the button's own label already reads "Search Settings",
                    and test-utils.ts's shared openSearchSettingsModal helper uses a plain
                    getByText(/Search Settings/) that a duplicate heading would make ambiguous. */}
                <SearchSettings />
              </div>
            </div>

            {/* Design doc §4.2's "Prepare Print footer - pinned, always visible at the rail's
                bottom (flex column: body scrolls, footer doesn't)". Issue #275 (ADDENDUM D9/F2)
                replaces the old three-button stack with FinishFooter's own co-equal Save
                Deck/Print - Export pair + the unchanged Export dropdown - see this file's own
                module comment for the full rationale. */}
            <div className="border-top p-3">
              <FinishFooter
                hasBackedUpThisSession={draftBackup.hasBackedUpThisSession}
                onPrintClick={prePrintSaveGate.startPrintFlow}
              />
            </div>
          </Offcanvas.Body>
        </RightRailOffcanvas>
      </DisplayBodyRegion>

      {/* Design doc §4.1's tablet-only discoverability affordance - see TabletRailHandle's own
          comment for why this doesn't exist on phone/laptop/desktop. */}
      <TabletRailHandle
        variant="primary"
        size="sm"
        onClick={openLeftRail}
        data-testid="display-rail-handle"
        aria-label="Card details"
      >
        Card details
      </TabletRailHandle>

      {prePrintSaveGate.element}
    </div>
  );
}
