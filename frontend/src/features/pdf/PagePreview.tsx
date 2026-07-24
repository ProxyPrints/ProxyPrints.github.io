/**
 * WYSIWYG page preview, without PDF rendering (Proposal A of the print-preview design task -
 * see the held proposal artifact for the full findings/mocks this implements). Feeds off the
 * same computeLayout() the PDF generator itself uses, so slot positions match exactly, and
 * renders with plain DOM/CSS - no canvas, no @react-pdf/renderer, no pdf.js. Card art is drawn
 * from the small-tier thumbnail URLs the caller already has in memory (the same URLs the
 * editor grid displays) - this component never fetches an image itself, so it adds zero new
 * image memory beyond whatever's already resident (the anti-crash requirement the whole design
 * task is built around; see the artifact's RAM findings on Proxxied's export-time crash class).
 *
 * "CSS-transform-scaled": the page itself is sized in real mm (a valid absolute CSS unit,
 * browsers already know 1mm = 96/25.4 px), then the whole thing is scaled down via
 * `transform: scale()` to fit the available preview width - so every measurement inside stays
 * in mm, matching computeLayout()'s own units, and only the single outer transform changes
 * when the preview panel resizes.
 *
 * Editor-completion package (E18/E19/E20/X18/X19) - the screenPresentation variant (R7/D17)
 * gained three more screen-only treatments, all gated on that same prop so PDFGenerator's own
 * fast preview (screenPresentation's default, false) is completely unaffected:
 *   - E20 (the no-white invariant): the slot fill switches from the light `#d9d9d9` placeholder
 *     to the theme's dark field color, always - this is what kills the `<img>`'s own pre-paint
 *     white flash too (the background sits behind the img the whole time it's decoding).
 *   - E18 (dark empty/loading/failed states): a slot with no resolved image renders a distinct-
 *     grey pinline (never the same line as the page's own pinline) plus either an indeterminate
 *     orange loading sweep or a muted "no art" mark + directed-help link, additively alongside
 *     the existing name/query-text label (item 1, owner's hands-on review) - never replacing it,
 *     so a slot's own accessible name/query text stays exactly as findable as before.
 *   - E19 (lime rounded corner-only cut guides): the screen-side guide render swaps the full
 *     dashed-rectangle trim line for four small corner L-brackets at true scale, matching the
 *     mockup's redline. PDFGenerator's own fast preview keeps today's full-rectangle
 *     approximation - this is a screen-only restyle of the /display sheet, not a new shared
 *     default. See PagePreview's own PDF-parity note further down for why the ACTUAL exported
 *     PDF's guide style is out of this task's scope, not silently left inconsistent.
 */

import { keyframes } from "@emotion/react";
import styled from "@emotion/styled";
import React, { useMemo } from "react";

import { CardHeightMM, CardWidthMM } from "@/common/constants";
import { useLongPress } from "@/common/useLongPress";
import {
  computeLayout,
  LayoutMargins,
  LayoutSpacing,
} from "@/features/pdf/layout";

// E20 - the anti-white-flash fill: sits behind both the slot itself and every <img> it renders,
// so there's never a frame where an empty/loading slot or a still-decoding image shows white.
const SCREEN_SLOT_BG = "#2B3E50";
// E18 - deliberately distinct from the page's own pinline (rgba(235,235,235,.18), see this
// component's screenPresentation page-border rule above) so the two never read as the same line.
const SCREEN_SLOT_PINLINE = "rgba(143, 160, 176, 0.4)";
const SCREEN_MUTED_TEXT = "#8fa0b0";
const LIME_GUIDE_COLOR = "#8ae234";

// E18 - the indeterminate loading sweep. `prefers-reduced-motion` gets a static bar at a fixed
// position instead of an animated one, matching E11's own reduced-motion rule elsewhere in this
// package (no transform/opacity animation under that preference).
const loadingSweep = keyframes`
  0% { transform: translateX(-20%); }
  100% { transform: translateX(240%); }
`;

const LoadingTrack = styled.div`
  position: absolute;
  left: 12%;
  right: 12%;
  top: calc(50% - 2px);
  height: 4px;
  border-radius: 2px;
  background: #22303f;
  overflow: hidden;
`;

const LoadingSweep = styled.div`
  position: absolute;
  left: 12%;
  top: calc(50% - 2px);
  height: 4px;
  width: 35%;
  border-radius: 2px;
  background: #df6919;
  animation: ${loadingSweep} 1.1s ease-in-out infinite;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
    width: 60%;
  }
`;

// F6/D22 - the visible `⋯` context-menu cue: hover/focus-reveal on desktop (a mouse user already
// has right-click as the primary trigger), persistent under `(pointer: coarse)` (a touch-primary
// device has no hover state to reveal it via - E9's original "gesture-invoked, no visible
// three-dots button" stance is deliberately revised here, see funnel-spec.md D22).
//
// Editor-polish round (EPcue, SPEC-editor-polish.md §D.8 `.slot-cue`, REV) - grows `20×20` ->
// `26×26`, glyph `13px` -> `17px`, higher-contrast (`rgba(22,32,43,.85)` -> `rgba(11,21,32,.92)`,
// border `1px #7f8fa0` -> `1.5px #abb6c2`, `#ebebeb` -> `#fff` glyph) so it reads over card art;
// gains a drop-shadow. The render GATE (whether this mounts at all) is the caller's concern, not
// this styled-component's - see `PagePreviewSlotEl`'s own updated gate comment below.
const SlotMenuCue = styled.button`
  position: absolute;
  bottom: 3px;
  right: 3px;
  z-index: 3;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(11, 21, 32, 0.92);
  border: 1.5px solid #abb6c2;
  color: #fff;
  font-size: 17px;
  line-height: 1;
  border-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
  opacity: 0;
  transition: opacity 0.15s ease;
  padding: 0;

  .page-preview-slot:hover &,
  .page-preview-slot:focus-within & {
    opacity: 1;
  }

  @media (pointer: coarse) {
    opacity: 1;
  }

  &:hover {
    background: #df6919;
    border-color: #df6919;
  }
`;

// EP6 (item 6, SPEC-editor-polish.md §D.8 `.slot-flip`, N) - ships the reserved E24 top-right
// corner (see this file's own `⟲` render site further down for the "reserved per the ruling"
// comment this fulfils). Same reveal behaviour as `SlotMenuCue` (hover/focus-reveal on desktop,
// persistent under `(pointer: coarse)`), gated to filled cells only (nothing to flip on an empty
// slot).
const SlotFlipButton = styled.button`
  position: absolute;
  top: 3px;
  right: 3px;
  z-index: 3;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(11, 21, 32, 0.92);
  border: 1.5px solid #abb6c2;
  color: #fff;
  font-size: 14px;
  line-height: 1;
  border-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
  opacity: 0;
  transition: opacity 0.15s ease;
  padding: 0;

  .page-preview-slot:hover &,
  .page-preview-slot:focus-within & {
    opacity: 1;
  }

  @media (pointer: coarse) {
    opacity: 1;
  }

  &:hover {
    background: #5bc0de;
    border-color: #5bc0de;
    color: #062430;
  }
`;

// E19 - the lime, rounded, corner-only cut guide: a small L-bracket (two legs) at each of a
// card's four trim corners, replacing the full dashed-rectangle trim line the screenPresentation
// sheet used to draw. Dimensions match the mockup's own rendered interpretation ("0.6mm stroke +
// ~3mm legs" - see the design spec's own flagged-for-visual-approval note): real mm units, so the
// legs/stroke scale at true sheet scale automatically via this component's one outer
// `transform: scale()`, no cqw container-query trick needed (unlike the static mockup, this is a
// live React tree already inside that transform).
const CUT_GUIDE_LEG_MM = 3;
const CUT_GUIDE_STROKE_MM = 0.6;

const CutCornerLeg = styled.div<{
  axis: "horizontal" | "vertical";
  corner: "tl" | "tr" | "bl" | "br";
}>`
  position: absolute;
  background: ${LIME_GUIDE_COLOR};
  border-radius: ${CUT_GUIDE_STROKE_MM / 2}mm;
  width: ${(props) =>
    props.axis === "horizontal" ? CUT_GUIDE_LEG_MM : CUT_GUIDE_STROKE_MM}mm;
  height: ${(props) =>
    props.axis === "horizontal" ? CUT_GUIDE_STROKE_MM : CUT_GUIDE_LEG_MM}mm;
  ${(props) =>
    props.corner === "tl" || props.corner === "bl" ? "left: 0;" : "right: 0;"}
  ${(props) =>
    props.corner === "tl" || props.corner === "tr" ? "top: 0;" : "bottom: 0;"}
`;

const CutCornerMark = ({ corner }: { corner: "tl" | "tr" | "bl" | "br" }) => (
  <>
    <CutCornerLeg axis="horizontal" corner={corner} />
    <CutCornerLeg axis="vertical" corner={corner} />
  </>
);

// Matches the CSS spec's own absolute definition of "mm" (96px per inch, 25.4mm per inch) -
// used only to size the outer non-scaled wrapper so it doesn't reserve extra blank space
// around the scaled-down page; every measurement on the page itself stays in real "mm" units.
const CSS_PX_PER_MM = 96 / 25.4;

export interface PagePreviewSlotContent {
  /** Small-tier thumbnail URL already resident in the browser/editor - never fetched by this
   * component. Undefined renders an empty placeholder slot (e.g. a page with fewer cards than
   * grid capacity). */
  imageUrl: string | undefined;
  /** Rendered as the slot's accessible name; also shown as a fallback label when imageUrl is
   * undefined. */
  name: string;
  /** Proposal B PR-3's hedged preview badge - "bleed will be generated", never confirmed-fact
   * framing, since the real per-side measurement only happens at export (see this file's own
   * module comment). Precomputed by the caller (`willLikelyGenerateBleed` in bleedNormalize.ts)
   * rather than derived here, so this component stays a dumb renderer with no knowledge of the
   * bleed-normalization algorithm itself. `undefined` renders no badge (bleed normalization
   * doesn't apply to this card, or its signal hasn't resolved yet - never guess). */
  willGenerateBleed?: boolean;
  /** Proposal H, item 1 (owner's hands-on review) - a slot with no resolved image (no card
   * selected yet, or its thumbnail hasn't loaded) shows this instead of a blank hole, since the
   * page IS the print artifact and a blank slot reads as "this position was skipped" rather than
   * "still waiting on art". Typically the slot's own search query text; `undefined` when there's
   * genuinely no query to show (e.g. a shared-cardback slot). Ignored when imageUrl is set. */
  queryText?: string;
  /** Editor-completion package, E17/E18 (X18) - only meaningful on the screenPresentation
   * variant, and only for a slot with no resolved imageUrl. `"loading"` renders the dark
   * indeterminate sweep (candidates/image still being fetched); `"failed"` renders the muted "no
   * art" mark + (when findCardUrl is set) the directed-help link. `undefined` (every non-/display
   * caller, and any /display slot with no active query at all - e.g. a shared-cardback back
   * face) renders neither, same as before this round. */
  loadState?: "loading" | "failed";
  /** Editor-completion package, E17 - a deterministic Scryfall reference link
   * (scryfallReference.ts), shown only alongside `loadState === "failed"`. `undefined` renders no
   * link (there was nothing in the query to build one from). */
  findCardUrl?: string;
  /** Foreign-order resilience Phase 1 follow-up (issue #324) - porting Card.tsx's own
   * `OrphanBadge` corner label to this, the /display sheet's own renderer, which previously had
   * no orphan visual treatment at all (a recorded gap in
   * docs/features/foreign-order-resilience.md). Set to the synthesized CardDocument's own
   * `sourceName` ("Your file" on this - the author/editor - surface, same text Card.tsx already
   * shows) whenever `cardDocument.isOrphan` is true; `undefined` (every non-orphan slot, and any
   * slot with no resolved image yet) renders no badge. Only shown alongside a resolved
   * `imageUrl` - same gating Card.tsx's own badge uses (never drawn over the empty/loading/failed
   * placeholder states above, which already carry their own distinct visual language). */
  orphanLabel?: string;
  /** Editor-polish round, item 6/E24 (SPEC-editor-polish.md §D.8 `.slot-flip`) - whether the
   * `⟲` flip button renders at ALL for this slot, independent of `imageUrl` (the CURRENTLY
   * effective face's own resolution). Deliberately a SEPARATE flag: gating the flip button on
   * `imageUrl` the same way the cue does would strand a user the moment they flip TO a face
   * with no art of its own - the button gating what let them flip would itself vanish along
   * with the image, with no way back. `true` when the slot has a real card on EITHER face
   * (front and/or back); `undefined`/`false` (a genuinely empty slot, nothing on either face)
   * renders no flip button, same as `onSlotFlip` simply being omitted. */
  flippable?: boolean;
}

export interface PagePreviewProps {
  pageWidthMM: number;
  pageHeightMM: number;
  bleedEdgeMM: number;
  margins: LayoutMargins;
  spacing: LayoutSpacing;
  /** One entry per slot on this page, in the same row-major order computeLayout() returns.
   * Fewer entries than grid capacity is fine - remaining slots render empty. */
  slots: Array<PagePreviewSlotContent>;
  /** Renders a dashed trim-line rectangle inside each slot's bleed box, matching the PDF
   * generator's own drawCardCutLines toggle - a visual approximation (not exact
   * CutLineCorner geometry, which stays PDF-only), for at-a-glance placement checking, not
   * print-accurate cut-line rendering. */
  showCutLines: boolean;
  /** Width, in real CSS px, of the preview panel this scales down to fit. */
  maxWidthPx: number;
  /** Proposal H (docs/proposals/proposal-h-unified-display-page.md): when provided, each slot
   * becomes clickable and calls back with its row-major index - the unified display page's own
   * slot-select interaction. Omitted by existing callers (PDFGenerator's fast preview), which
   * stay non-interactive with zero behavior change. */
  onSlotClick?: (index: number) => void;
  /** Row-major index of the slot to render with a selected outline. Ignored when onSlotClick
   * isn't provided. */
  selectedSlotIndex?: number;
  /** Proposal H R7/D17 (docs/proposals/proposal-h-display-layout-spec.md) - the /display sheet
   * stack's screen-only presentation: a fully clear page (no white fill, no drop shadow) with a
   * hairline, low-alpha pinline boundary and rounded corners instead of a drawn box. Border/
   * radius widths are computed against this component's OWN scale factor (see `scale` below) so
   * they render as a constant ~1px/~7px of real screen space regardless of how far the mm-sized
   * page has been scaled down to fit `maxWidthPx` - a raw 1px pre-scale border would nearly
   * vanish on a heavily letterboxed phone sheet (issue #266's own fit-to-width rule). The exported
   * PDF (PDF.tsx) never reads this prop - it's a screen-presentation-only flag. Omitted (false)
   * by every existing caller (PDFGenerator.tsx's own fast preview), which keeps today's white-
   * page/box-shadow look with zero behavior change. */
  screenPresentation?: boolean;
  /** Funnel round (funnel-spec.md F6, XF8) - opens a context menu for the slot at `index`,
   * anchored to the trigger's viewport (x, y). Wired from BOTH a right-click (desktop,
   * `preventDefault`ed so the browser's native menu never shows on a slot) and a long-press
   * (touch, `useLongPress`) on every slot, plus the visible `⋯` cue button (D22) - the same
   * "one action list, several triggers" pattern `CardSlot.tsx`'s own context menu already uses.
   * `undefined` (every existing caller - PDFGenerator's fast preview, and any /display sheet not
   * opting in) renders with zero behavior change: no cue, no long-press handlers, right-click
   * falls through to the browser's default menu exactly as today. */
  onSlotContextMenu?: (index: number, x: number, y: number) => void;
  /** Editor-polish round, item 6/E24 (SPEC-editor-polish.md §D.8 `.slot-flip`, N) - ships the
   * `⟲` corner flip button at the slot's reserved top-right corner, gated to slots that already
   * hold a real image (`content.imageUrl != null`) - nothing to flip on an empty slot.
   * `undefined` (every existing caller) renders with zero behavior change: no flip button at
   * all, same as before this round. */
  onSlotFlip?: (index: number) => void;
}

export function PagePreview({
  pageWidthMM,
  pageHeightMM,
  bleedEdgeMM,
  margins,
  spacing,
  slots,
  showCutLines,
  maxWidthPx,
  onSlotClick,
  selectedSlotIndex,
  screenPresentation = false,
  onSlotContextMenu,
  onSlotFlip,
}: PagePreviewProps) {
  const layout = useMemo(
    () =>
      computeLayout(
        pageWidthMM,
        pageHeightMM,
        CardWidthMM,
        CardHeightMM,
        bleedEdgeMM,
        margins,
        spacing
      ),
    // deliberately depend on each primitive field, not the margins/spacing objects themselves -
    // callers (e.g. PDFGenerator) construct a fresh { top, bottom, left, right } object every
    // render, which would defeat this memo entirely if it were a dependency
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      pageWidthMM,
      pageHeightMM,
      bleedEdgeMM,
      margins.top,
      margins.bottom,
      margins.left,
      margins.right,
      spacing.row,
      spacing.col,
    ]
  );

  const scale = maxWidthPx / (pageWidthMM * CSS_PX_PER_MM);
  const slotWidthMM = CardWidthMM + 2 * bleedEdgeMM;
  const slotHeightMM = CardHeightMM + 2 * bleedEdgeMM;

  return (
    <div
      data-testid="page-preview"
      style={{
        width: maxWidthPx,
        height: pageHeightMM * CSS_PX_PER_MM * scale,
        overflow: "hidden",
      }}
    >
      <div
        data-testid="page-preview-page"
        style={{
          width: pageWidthMM + "mm",
          height: pageHeightMM + "mm",
          position: "relative",
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          ...(screenPresentation
            ? {
                background: "transparent",
                border: `${1 / scale}px solid rgba(235, 235, 235, 0.18)`,
                borderRadius: `${7 / scale}px`,
              }
            : {
                background: "white",
                boxShadow: "0 2px 10px rgba(0, 0, 0, 0.25)",
              }),
        }}
      >
        {layout.slots.map((slot, index) => (
          <PagePreviewSlotEl
            key={index}
            index={index}
            content={slots[index]}
            xMM={slot.xMM}
            yMM={slot.yMM}
            slotWidthMM={slotWidthMM}
            slotHeightMM={slotHeightMM}
            bleedEdgeMM={bleedEdgeMM}
            showCutLines={showCutLines}
            screenPresentation={screenPresentation}
            isSelected={onSlotClick != null && selectedSlotIndex === index}
            onSlotClick={onSlotClick}
            onSlotContextMenu={onSlotContextMenu}
            onSlotFlip={onSlotFlip}
          />
        ))}
      </div>
    </div>
  );
}

interface PagePreviewSlotElProps {
  index: number;
  content: PagePreviewSlotContent | undefined;
  xMM: number;
  yMM: number;
  slotWidthMM: number;
  slotHeightMM: number;
  bleedEdgeMM: number;
  showCutLines: boolean;
  screenPresentation: boolean;
  isSelected: boolean;
  onSlotClick?: (index: number) => void;
  onSlotContextMenu?: (index: number, x: number, y: number) => void;
  onSlotFlip?: (index: number) => void;
}

/**
 * Funnel round (funnel-spec.md F6, XF7/XF8) - extracted out of PagePreview's own render loop so
 * this can call `useLongPress` once per slot (a hook can't be called conditionally/in a loop body
 * directly). Behavior-preserving for every existing caller: `onSlotContextMenu` absent renders
 * exactly as before this round (no cue, no long-press handlers, no `onContextMenu` at all - the
 * browser's native menu is untouched).
 */
function PagePreviewSlotEl({
  index,
  content,
  xMM,
  yMM,
  slotWidthMM,
  slotHeightMM,
  bleedEdgeMM,
  showCutLines,
  screenPresentation,
  isSelected,
  onSlotClick,
  onSlotContextMenu,
  onSlotFlip,
}: PagePreviewSlotElProps) {
  const longPressHandlers = useLongPress((x, y) =>
    onSlotContextMenu?.(index, x, y)
  );

  return (
    <div
      data-testid="page-preview-slot"
      className="page-preview-slot"
      onClick={onSlotClick != null ? () => onSlotClick(index) : undefined}
      onContextMenu={
        onSlotContextMenu != null
          ? (event) => {
              event.preventDefault();
              onSlotContextMenu(index, event.clientX, event.clientY);
            }
          : undefined
      }
      {...(onSlotContextMenu != null ? longPressHandlers : {})}
      role={onSlotClick != null ? "button" : undefined}
      aria-label={onSlotClick != null ? content?.name : undefined}
      aria-pressed={onSlotClick != null ? isSelected : undefined}
      style={{
        position: "absolute",
        left: xMM + "mm",
        top: yMM + "mm",
        width: slotWidthMM + "mm",
        height: slotHeightMM + "mm",
        overflow: "hidden",
        // E20 - always the dark field color on the screenPresentation variant (never just
        // for empty/loading/failed slots): this is what's behind the <img> below too, so
        // there's no white pre-paint flash while a filled slot's own image decodes.
        background: screenPresentation ? SCREEN_SLOT_BG : "#d9d9d9",
        border:
          screenPresentation && content?.loadState != null
            ? `1px solid ${SCREEN_SLOT_PINLINE}`
            : undefined,
        cursor: onSlotClick != null ? "pointer" : undefined,
        outline: isSelected ? "3px solid #df691a" : undefined,
        outlineOffset: isSelected ? "-3px" : undefined,
      }}
    >
      {/* Everything below sits within the slot's own box (bottom:2px/right:2px insets for the
          cue, well within 0..100%), so the removed wrapper's overflow:hidden is safely restored
          directly on this outer element - no extra DOM node needed just to clip the <img>. */}
      {content?.imageUrl != null && (
        <img
          src={content.imageUrl}
          alt={content.name}
          loading="lazy"
          decoding="async"
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            display: "block",
            pointerEvents: "none",
            // E20 - the img's own box, pre-paint (impl note from the spec: set it on the
            // slot container AND the img itself - the flash is the img's own box, not just
            // its parent's).
            backgroundColor: screenPresentation ? SCREEN_SLOT_BG : undefined,
          }}
        />
      )}
      {content?.imageUrl != null && content.orphanLabel != null && (
        // Foreign-order resilience Phase 1 follow-up (issue #324) - same visual treatment as
        // Card.tsx's own `OrphanBadge` (blue pill, white uppercase text), ported to this
        // component's own mm-unit idiom (matching the bleed badge just below rather than
        // Card.tsx's px-based styled-component) so it stays legible at any `maxWidthPx`
        // letterboxing after the outer `transform: scale()` - see this file's own module comment
        // on why every overlay here is sized in mm, not px. Top-right, deliberately not the
        // bleed badge's top-left corner: the two are mutually exclusive in practice (an orphan
        // has no sourceType, so PDF.tsx's bleed-normalization eligibility check never fires for
        // one - see the docs' "Bleed normalization for orphans" deferred note), but keeping them
        // visually separable costs nothing.
        <div
          data-testid="orphan-badge"
          style={{
            position: "absolute",
            right: "1mm",
            top: "1mm",
            padding: "0.5mm 1.5mm",
            fontSize: "2.2mm",
            fontWeight: 700,
            lineHeight: 1.2,
            textTransform: "uppercase",
            letterSpacing: "0.03em",
            color: "white",
            background: "rgba(13, 110, 253, 0.85)",
            borderRadius: "1mm",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          {content.orphanLabel}
        </div>
      )}
      {content != null && content.imageUrl == null && (
        <div
          data-testid="page-preview-empty-slot-label"
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "1mm",
            padding: "2mm",
            textAlign: "center",
            color: screenPresentation ? SCREEN_MUTED_TEXT : "#4a4a4a",
            pointerEvents: "none",
          }}
        >
          <span
            style={{
              fontSize: "2.6mm",
              fontWeight: 600,
              lineHeight: 1.2,
              overflowWrap: "anywhere",
            }}
          >
            {content.name}
          </span>
          {content.queryText != null && (
            <span
              style={{
                fontSize: "2.2mm",
                fontStyle: "italic",
                lineHeight: 1.2,
                overflowWrap: "anywhere",
              }}
            >
              {content.queryText}
            </span>
          )}
          {/* E17/E18 - additive to the name/query-text label above (never replacing it):
                a slim indeterminate loading sweep while candidates/the image are still
                being fetched, or a muted "no art" mark + directed-help link once that's
                settled with nothing found. Screen-only, gated on loadState (undefined for
                every non-/display caller and any /display slot with no active query at
                all). */}
          {screenPresentation && content.loadState === "loading" && (
            <LoadingTrack data-testid="page-preview-slot-loading">
              <LoadingSweep />
            </LoadingTrack>
          )}
          {screenPresentation && content.loadState === "failed" && (
            <div
              data-testid="page-preview-slot-failed"
              style={{ pointerEvents: "auto" }}
            >
              <span style={{ fontSize: "2.4mm" }}>✗ no art</span>
              {content.findCardUrl != null && (
                <div>
                  <a
                    href={content.findCardUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="page-preview-find-card-link"
                    style={{
                      color: "#df6919",
                      fontSize: "2.2mm",
                      textDecoration: "underline",
                    }}
                  >
                    Find this card ↗
                  </a>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {showCutLines &&
        (screenPresentation ? (
          <div
            data-testid="page-preview-cut-line"
            style={{
              position: "absolute",
              left: bleedEdgeMM + "mm",
              top: bleedEdgeMM + "mm",
              width: CardWidthMM + "mm",
              height: CardHeightMM + "mm",
              pointerEvents: "none",
            }}
          >
            <CutCornerMark corner="tl" />
            <CutCornerMark corner="tr" />
            <CutCornerMark corner="bl" />
            <CutCornerMark corner="br" />
          </div>
        ) : (
          <div
            data-testid="page-preview-cut-line"
            style={{
              position: "absolute",
              left: bleedEdgeMM + "mm",
              top: bleedEdgeMM + "mm",
              width: CardWidthMM + "mm",
              height: CardHeightMM + "mm",
              outline: "0.25mm dashed rgba(220, 30, 30, 0.75)",
              pointerEvents: "none",
            }}
          />
        ))}
      {content?.willGenerateBleed === true && (
        <div
          data-testid="page-preview-bleed-badge"
          style={{
            position: "absolute",
            left: "1mm",
            top: "1mm",
            padding: "0.5mm 1.5mm",
            fontSize: "2.2mm",
            lineHeight: 1.2,
            color: "white",
            background: "rgba(0, 0, 0, 0.65)",
            borderRadius: "1mm",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          Bleed will be generated
        </div>
      )}
      {/* F6/D22 - the visible touch-discoverable menu cue, BOTTOM-RIGHT of the slot (its own
          corner - top-left is the E8 selection checkbox, top-right is the E24 flip button, ships
          just below, EPcue/item 6). Hover/focus-reveal on desktop (a mouse user has right-click);
          persistent under `(pointer: coarse)` (a touch-primary device, which has no hover state
          to reveal it via).
          EPcue (SPEC-editor-polish.md §D.8, REV) - the render gate TIGHTENS from "a context menu
          is wired" alone to "the slot holds a card AND a context menu is wired" - an empty slot
          has nothing a menu could act on, so it now shows no cue at all (previously rendered on
          every slot, filled or not, whenever `onSlotContextMenu` was supplied). */}
      {onSlotContextMenu != null && content?.imageUrl != null && (
        <SlotMenuCue
          type="button"
          aria-label="Open card menu"
          data-testid="page-preview-slot-menu-cue"
          onClick={(event) => {
            event.stopPropagation();
            const rect = event.currentTarget.getBoundingClientRect();
            onSlotContextMenu(index, rect.left, rect.bottom);
          }}
        >
          ⋯
        </SlotMenuCue>
      )}
      {/* EP6/item 6/E24 (SPEC-editor-polish.md §D.8 `.slot-flip`, N) - ships the reserved
          top-right corner; gated on `content.flippable` (a card on EITHER face), NOT
          `content.imageUrl` (the CURRENTLY effective face) - see that field's own comment for
          why gating on the latter would strand a user the moment they flip to a face with no
          art of its own. */}
      {onSlotFlip != null && content?.flippable === true && (
        <SlotFlipButton
          type="button"
          aria-label="Preview the other face of this card"
          data-testid="page-preview-slot-flip"
          onClick={(event) => {
            event.stopPropagation();
            onSlotFlip(index);
          }}
        >
          ⟲
        </SlotFlipButton>
      )}
    </div>
  );
}
