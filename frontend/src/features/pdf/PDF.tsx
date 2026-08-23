import {
  Document,
  DocumentProps,
  Image,
  Page,
  Rect,
  StyleSheet,
  Svg,
  View,
} from "@react-pdf/renderer";
import React, { createContext, useContext } from "react";

import {
  BleedEdgeMM,
  CardHeightMM,
  CardWidthMM,
  CornerRadiusMM,
} from "@/common/constants";
import { SourceType } from "@/common/schema_types";
import { CardDocument, SlotProjectMembers } from "@/common/types";
import { chunk } from "@/common/utils";
import { normalizeCardBleed } from "@/features/pdf/bleedExtension";
import { BleedPrior, ManualOverride } from "@/features/pdf/bleedNormalize";
import { computeLayout, LayoutEdgeBleed } from "@/features/pdf/layout";
import { getPageSizeMM, PageSize } from "@/features/pdf/pageSize";
import {
  computeBleedCropMM,
  computeRenderedBleedMM,
  createTrackedObjectURL,
  getPDFImageBlob,
  getPDFImageURL,
  PDFImageQuality,
} from "@/features/pdf/pdfImage";
import {
  ScmPaperSize,
  ScmRegistration,
  ScmVariant,
} from "@/features/pdf/scm/scmLayout";
import {
  computeSCMPDFPageCount,
  SCMPDF,
  SCMPDFProps,
} from "@/features/pdf/scm/SCMPDF";

export { getPageSizeMM, PageSize };

const PDFContext = createContext<PDFProps | undefined>(undefined);

const usePDFContext = (): PDFProps => {
  const context = useContext(PDFContext);
  if (!context) {
    throw new Error("Attempted to use pdfContext outside of provider");
  }
  return context;
};

// Thin wrapper over the shared computeLayout() - was previously two independently-tuned
// algorithms (a greedy container-fit loop, and a separate division-based cards-per-row/col
// re-derivation) at each of this file's three call sites; see layout.ts's module comment.
const layoutForPage = (
  pageWidthMM: number,
  pageHeightMM: number,
  bleedEdgeMM: number,
  cardSpacingRowMM: number,
  cardSpacingColMM: number,
  pageMarginTopMM: number,
  pageMarginBottomMM: number,
  pageMarginLeftMM: number,
  pageMarginRightMM: number
) =>
  computeLayout(
    pageWidthMM,
    pageHeightMM,
    CardWidthMM,
    CardHeightMM,
    bleedEdgeMM,
    {
      top: pageMarginTopMM,
      bottom: pageMarginBottomMM,
      left: pageMarginLeftMM,
      right: pageMarginRightMM,
    },
    { row: cardSpacingRowMM, col: cardSpacingColMM }
  );

const ZERO_BLEED: LayoutEdgeBleed = { top: 0, bottom: 0, left: 0, right: 0 };

// #301 (croppable bleed) - the per-edge bleed computeLayout() actually granted every slot on
// this page (uniform across the whole page - see layout.ts's LayoutSlot.bleedMM comment for
// why that's the correct answer, not a simplification). Every render site below that used to
// read the flat `bleedEdgeMM` context value as "the" bleed (PDFCardImage's box size,
// PDFCardCutLines'/PageCutLines' cut-line placement) now reads THIS instead - `bleedEdgeMM`
// itself is only the per-edge MAXIMUM a #299-normalized card carries, not what actually
// renders. Takes the whole PDFProps context object rather than 9 separate fields so call sites
// don't have to destructure every layout-relevant prop just to ask this one question.
const contextAvailableBleedMM = (ctx: PDFProps): LayoutEdgeBleed => {
  const size = getPageSizeMM(ctx.pageSize, ctx.pageWidth, ctx.pageHeight);
  const layout = layoutForPage(
    size.width,
    size.height,
    ctx.bleedEdgeMM,
    ctx.cardSpacingRowMM,
    ctx.cardSpacingColMM,
    ctx.pageMarginTopMM,
    ctx.pageMarginBottomMM,
    ctx.pageMarginLeftMM,
    ctx.pageMarginRightMM
  );
  // computeLayout() always resolves at least 1 slot per axis (see fitAxisWithBleed's own "never
  // returns 0 cards" note) - the fallback here is purely defensive, not expected to fire.
  return layout.slots[0]?.bleedMM ?? ZERO_BLEED;
};

export const CardSelectionMode = {
  frontsAndDistinctBacks: "Fronts + Distinct Backs",
  frontsOnly: "Fronts Only",
  frontsAndBacks: "Fronts + Backs",
  backsOnly: "Backs Only",
} as const;

// The mode a fresh export starts in. Must be a mode that emits a back for every card:
// "Fronts + Distinct Backs" deliberately omits the shared project cardback (it is meant to be
// printed in bulk once, not once per card), so a deck whose cards all share the project
// cardback would export fronts-only with no warning - exactly the scenario the pre-print
// cardback reminder gate warns about. "Fronts + Backs" emits every card's back, so a
// shared-cardback deck still gets a duplex-printable file. Users who want the paper-saving
// behaviour can still select "Fronts + Distinct Backs" explicitly.
export const DEFAULT_CARD_SELECTION_MODE: keyof typeof CardSelectionMode =
  "frontsAndBacks";

// Create styles
const styles = StyleSheet.create({
  section: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "flex-start",
  },
});

export interface PDFProps {
  cardSelectionMode: keyof typeof CardSelectionMode;
  pageSize: keyof typeof PageSize;
  pageWidth: number | undefined;
  pageHeight: number | undefined;
  bleedEdgeMM: number;
  roundCorners: boolean;
  drawCardCutLines: boolean;
  drawPageCutLines: boolean;
  // Optional crosshair corner marks alongside the default dashed bleed outline `drawCardCutLines`
  // already draws - default off (most users just need the outline; the marks are for anyone who
  // specifically wants a traditional corner-mark guide too). Independent of drawCardCutLines'
  // own on/off state in principle, but only rendered when it's on (nothing to add marks to
  // otherwise) - see PDFCardCutLines' own render.
  showCrossCutLines: boolean;
  cutLineLengthMM: number;
  cutLineOffsetMM: number;
  cutLineThicknessMM: number;
  cutLineColor: string;
  cardSpacingRowMM: number;
  cardSpacingColMM: number;
  pageMarginTopMM: number;
  pageMarginBottomMM: number;
  pageMarginLeftMM: number;
  pageMarginRightMM: number;
  // Registration compensation (PageOffsetControl.tsx, /display's right rail) - shifts the whole
  // CardGrid container away from its otherwise-centered position, applied AFTER layoutForPage has
  // already resolved card counts/granted bleed, never fed into that computation itself: it must
  // never change either. Never clamped to the page's own margins/slack (a real printer
  // correction can legitimately exceed them) - see CardGrid's own render for where this applies.
  // Optional, additive, defaults to 0 (via `?? 0` at the one render site that reads it) so every
  // existing caller (none of which set it yet) renders at the exact position it always did.
  pageOffsetXMM?: number;
  pageOffsetYMM?: number;
  // 1-indexed, inclusive; applied AFTER pagination has already resolved the full page set (see
  // sliceToPageRange below) - never changes card selection, layout, or page count itself, only
  // which of the already-computed pages are emitted. `undefined` on either bound means "no
  // restriction on that end" - both undefined (every existing caller) exports every page, same
  // as before this field existed.
  pageRangeStart?: number;
  pageRangeEnd?: number;
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined };
  projectMembers: Array<SlotProjectMembers>;
  projectCardback: string | undefined;
  imageQuality: PDFImageQuality;
  imageDPI: number | undefined;
  jpgQuality: number;
  fileHandles: { [identifier: string]: FileSystemFileHandle };
  // Called (by pdf.worker.ts, which supplies this internally - not by any
  // caller of the public PDF render hooks) once per card image that couldn't
  // be fetched, so the worker can report which cards ended up blank instead
  // of that failure being silently invisible. Optional so existing render
  // props unrelated to failure tracking don't need to know about it.
  reportImageFailure?: (identifier: string, label: string) => void;
  // Called (by pdf.worker.ts, same as reportImageFailure above) once per card image slot that
  // FINISHES resolving, success or failure - lets the export UI show live "fetching images:
  // N/M" progress instead of a static spinner for the several-minutes-plus a large export can
  // take once full-resolution fetches are paced to the image CDN's shared rate limit (see
  // pdfImage.ts's fetchFullResolutionImageAsBlob). No arguments - the worker-side closure that
  // supplies this owns the actual counting/total, this is just the "one more happened" signal.
  reportImageProgress?: () => void;
  // Proposal B (docs/proposals/proposal-b-bleed-normalization.md) - export-time per-side bleed
  // normalization. Both maps are keyed by card identifier and pre-resolved on the MAIN thread
  // (PDFGenerator.tsx) before the render worker is invoked - not fetched from inside the worker
  // itself, since APIGetTagConsensus's CSRF header needs document.cookie, which doesn't exist in
  // a Worker context. A missing entry for a given identifier defaults to "unresolved"/"auto"
  // respectively (see bleedNormalize.ts), so this stays fully optional for any caller (SCM mode,
  // existing tests) that doesn't populate it.
  bleedPriors?: { [identifier: string]: BleedPrior };
  bleedOverrides?: { [identifier: string]: ManualOverride };
  // SCM (Silhouette Card Maker) mode. When scmMode is true, the standard
  // parametric layout above is ignored in favour of an SCM-template-compatible
  // layout with registration marks (see scm/SCMPDF.tsx).
  scmMode: boolean;
  scmPaperSize: ScmPaperSize;
  scmVariant: ScmVariant;
  scmRegistration: ScmRegistration;
  scmDuplex: boolean;
  scmOffsetXMM: number;
  scmOffsetYMM: number;
  scmOffsetAngleDeg: number;
}

interface PDFCardThumbnailProps {
  cardDocument: CardDocument;
}

type CutLineCornerPosition =
  | "top-left"
  | "top-right"
  | "bottom-left"
  | "bottom-right";

interface CutLineCornerProps {
  position: CutLineCornerPosition;
  lengthMM: number;
  horizontalLeftLengthOverrideMM?: number;
  horizontalRightLengthOverrideMM?: number;
  verticalUpLengthOverrideMM?: number;
  verticalDownLengthOverrideMM?: number;
}

// Gap between dashes on the bleed outline (PDFCardCutLines' Svg/Rect strokeDasharray) - the dash
// length itself is the user-adjustable cutLineLengthMM, so only the fixed gap lives here.
const CUT_LINE_DASH_GAP_MM = 1;

// @react-pdf/renderer's Svg/Rect (unlike View's mm-string styles) take bare point values - see
// PDFCardCutLines' own comment where this is used.
const mmToPt = (mm: number): number => (mm / 25.4) * 72;

// One arm of a CutLineCorner mark (the optional crosshair guide) - "positive" extends right/down
// from the corner's own anchor point, "negative" extends left/up. Always a single solid bar; the
// dashed guide is the bleed outline (PDFCardCutLines' Svg/Rect), not these marks.
const CutLineBar = ({
  axis,
  direction,
  lengthMM,
  thicknessMM,
  color,
}: {
  axis: "horizontal" | "vertical";
  direction: "positive" | "negative";
  lengthMM: number;
  thicknessMM: number;
  color: string;
}) => {
  const style =
    axis === "vertical"
      ? {
          position: "absolute" as const,
          width: thicknessMM + "mm",
          height: lengthMM + "mm",
          backgroundColor: color,
          left: 0,
          ...(direction === "positive" ? { top: 0 } : { bottom: 0 }),
        }
      : {
          position: "absolute" as const,
          width: lengthMM + "mm",
          height: thicknessMM + "mm",
          backgroundColor: color,
          top: 0,
          ...(direction === "positive" ? { left: 0 } : { right: 0 }),
        };
  return <View style={style} />;
};

// The optional crosshair corner-mark guide (PDFProps.showCrossCutLines) - anchored at the slot's
// own outer edge (the true bleed boundary), the same anchor PDFCardCutLines' dashed outline
// below uses. This is the only placement CutLineCorner ever needed even before the cut-guide
// redesign (PageCutLines, further down, already hardcoded it).
const CutLineCorner = ({
  position,
  lengthMM,
  horizontalLeftLengthOverrideMM,
  horizontalRightLengthOverrideMM,
  verticalUpLengthOverrideMM,
  verticalDownLengthOverrideMM,
}: CutLineCornerProps) => {
  const ctx = usePDFContext();
  const { cutLineThicknessMM, cutLineColor, cutLineOffsetMM } = ctx;

  const positionLookup: {
    [location in CutLineCornerPosition]: {
      verticalCssProperty: "top" | "bottom";
      horizontalCssProperty: "left" | "right";
    };
  } = {
    "top-left": { verticalCssProperty: "top", horizontalCssProperty: "left" },
    "top-right": {
      verticalCssProperty: "top",
      horizontalCssProperty: "right",
    },
    "bottom-left": {
      verticalCssProperty: "bottom",
      horizontalCssProperty: "left",
    },
    "bottom-right": {
      verticalCssProperty: "bottom",
      horizontalCssProperty: "right",
    },
  };

  const inside = positionLookup[position];
  // Offset 0 sits exactly on the slot's own outer edge (the true bleed boundary, the same box
  // PDFCardCutLines' outline traces below); a positive offset grows the mark outward past it.
  const horizontalOffset = -cutLineOffsetMM;
  const verticalOffset = -cutLineOffsetMM;

  return (
    <View
      style={{
        position: "absolute" as const,
        ...(inside.verticalCssProperty === "top" && {
          top: verticalOffset + "mm",
        }),
        ...(inside.verticalCssProperty === "bottom" && {
          bottom: verticalOffset + cutLineThicknessMM + "mm",
        }),
        ...(inside.horizontalCssProperty === "left" && {
          left: horizontalOffset + "mm",
        }),
        ...(inside.horizontalCssProperty === "right" && {
          right: horizontalOffset + cutLineThicknessMM + "mm",
        }),
      }}
    >
      <CutLineBar
        axis="vertical"
        direction="positive"
        lengthMM={verticalDownLengthOverrideMM ?? lengthMM}
        thicknessMM={cutLineThicknessMM}
        color={cutLineColor}
      />
      <CutLineBar
        axis="vertical"
        direction="negative"
        lengthMM={verticalUpLengthOverrideMM ?? lengthMM}
        thicknessMM={cutLineThicknessMM}
        color={cutLineColor}
      />
      <CutLineBar
        axis="horizontal"
        direction="positive"
        lengthMM={horizontalRightLengthOverrideMM ?? lengthMM}
        thicknessMM={cutLineThicknessMM}
        color={cutLineColor}
      />
      <CutLineBar
        axis="horizontal"
        direction="negative"
        lengthMM={horizontalLeftLengthOverrideMM ?? lengthMM}
        thicknessMM={cutLineThicknessMM}
        color={cutLineColor}
      />
    </View>
  );
};

// Proposal B (docs/proposals/proposal-b-bleed-normalization.md) - full-resolution images from
// Google Drive or a local file are the only ones bleed normalization applies to (the two
// sources that carry a real, decodable full-res bitmap; the thumbnail tiers are cheap-preview
// quality, not what real printing bleed geometry needs). SCM mode's own image path
// (scm/SCMPDF.tsx) is untouched - out of scope for this pass, see the proposal doc.
// Exported (Proposal H pane migration) so the display page's rail Print Options section
// (DisplayPage.tsx) can gate its per-card bleed override control with the exact same
// eligibility rule PDFGenerator.tsx's own BleedOverrideSettings panel uses, rather than
// re-deriving a second copy of this source-type check that could silently drift from it.
export const isBleedNormalizationEligible = (
  cardDocument: CardDocument,
  imageQuality: PDFImageQuality
): boolean =>
  imageQuality === "full-resolution" &&
  (cardDocument.sourceType === SourceType.GoogleDrive ||
    cardDocument.sourceType === SourceType.LocalFile);

const uniformBleedMM = (mm: number): LayoutEdgeBleed => ({
  top: mm,
  bottom: mm,
  left: mm,
  right: mm,
});

// Renders only the card image, with no cut lines.
const PDFCardImage = ({ cardDocument }: PDFCardThumbnailProps) => {
  const ctx = usePDFContext();
  const {
    bleedEdgeMM,
    roundCorners,
    imageQuality,
    imageDPI,
    jpgQuality,
    fileHandles,
    reportImageFailure,
    reportImageProgress,
    bleedPriors,
    bleedOverrides,
  } = ctx;
  const bleedNormalized = isBleedNormalizationEligible(
    cardDocument,
    imageQuality
  );

  // #301 - what this card's image actually CARRIES vs what the layout has room to RENDER.
  // Bleed-normalized output is synthesized to exactly `bleedEdgeMM` on every side (see
  // normalizeCardBleed) - the rare exception (a too-small source hitting bleedExtension.ts's
  // own `clampOpposingCrop` shortfall) is an already-accepted "slightly-short bleed margin"
  // trade documented there, not something this layer can see into without touching that
  // excluded file. A non-normalized source (thumbnail tier, SCM, or any card
  // isBleedNormalizationEligible rejects) is assumed to carry the fixed STANDARD constant
  // (matches the pre-#301 proportional-rescale assumption below, unchanged).
  const carriedBleedMM = uniformBleedMM(
    bleedNormalized ? bleedEdgeMM : BleedEdgeMM
  );
  const availableBleedMM = contextAvailableBleedMM(ctx);
  const renderedBleedMM = computeRenderedBleedMM(
    carriedBleedMM,
    availableBleedMM
  );
  const height = CardHeightMM + renderedBleedMM.top + renderedBleedMM.bottom;
  const width = CardWidthMM + renderedBleedMM.left + renderedBleedMM.right;

  // Rounding is drawn on this box (card + bleed), but the bleed is exactly what a trim along
  // the cut guide removes - a flat CornerRadiusMM here would sit entirely inside that discarded
  // margin and vanish the moment the card is actually cut out. Growing the radius by the
  // adjoining bleed means the arc reaches the TRUE card edge, so the CUT card's own corner comes
  // out at exactly CornerRadiusMM (trimming a rounded rect by `b` on each edge shrinks its
  // radius by `b`). min() of the two edges meeting at a corner handles the rare case where a
  // crowded page axis has cropped one of them below the configured bleed (#301).
  const cornerRadiusMM = (edgeAMM: number, edgeBMM: number): number =>
    roundCorners ? CornerRadiusMM + Math.min(edgeAMM, edgeBMM) : 0;
  const topLeftRadiusMM = cornerRadiusMM(
    renderedBleedMM.top,
    renderedBleedMM.left
  );
  const topRightRadiusMM = cornerRadiusMM(
    renderedBleedMM.top,
    renderedBleedMM.right
  );
  const bottomLeftRadiusMM = cornerRadiusMM(
    renderedBleedMM.bottom,
    renderedBleedMM.left
  );
  const bottomRightRadiusMM = cornerRadiusMM(
    renderedBleedMM.bottom,
    renderedBleedMM.right
  );

  // Non-normalized path only (bleedNormalized short-circuits this - see below): the old
  // proportion-based rescale, fixing up an image assumed to be at the STANDARD bleed amount
  // into whatever box size this slot actually grants. @react-pdf/renderer's own style
  // processor (processTransform in @react-pdf/stylesheet) has a real bug where a single-token
  // transform value like "none" crashes deep inside its parser (normalizeTransformOperation
  // ends up calling .map() on undefined), hanging the whole render with no error surfaced
  // anywhere - found via a real Playwright regression, not by reading their source
  // speculatively. Omitting the key entirely (not "none") sidesteps their parser altogether,
  // which is what "no transform" actually needs anyway.
  const heightProportion = (CardHeightMM + 2 * BleedEdgeMM) / height;
  const widthProportion = (CardWidthMM + 2 * BleedEdgeMM) / width;
  const scaleTransform = bleedNormalized
    ? undefined
    : `scale(${widthProportion}, ${heightProportion})`;

  // #301 - normalized output is always the FULL carried bleed box (CardSize + 2*bleedEdgeMM,
  // symmetric on every side by normalizeCardBleed's own contract); this slot may afford less
  // than that. Rather than re-decode/re-encode a second canvas pass just to crop (pdfImage.ts's
  // own module doc explains why that boundary - real canvas work vs pure geometry - is kept
  // thin/imperative), the oversized image is positioned at a negative offset within an
  // `overflow: hidden` box sized to what's actually rendered - the visible result is pixel-
  // identical to a real crop, since react-pdf still rasterizes only the visible region into the
  // final PDF. `computeBleedCropMM` (pdfImage.ts) is the same pure, unit-tested geometry either
  // approach would need.
  const cropMM = bleedNormalized
    ? computeBleedCropMM(carriedBleedMM, availableBleedMM)
    : ZERO_BLEED;
  const fullCarriedWidthMM =
    CardWidthMM + carriedBleedMM.left + carriedBleedMM.right;
  const fullCarriedHeightMM =
    CardHeightMM + carriedBleedMM.top + carriedBleedMM.bottom;

  const imageSrc = async () => {
    try {
      if (bleedNormalized) {
        const blob = await getPDFImageBlob(
          cardDocument,
          imageDPI,
          jpgQuality,
          fileHandles
        );
        // cardDocument.dpi is the source's own recorded resolution, but a lower imageDPI
        // setting can make the Worker serve a downscaled image below that - if so, the
        // BYTES actually fetched are at imageDPI, not cardDocument.dpi, and px->mm
        // conversion needs to match what was really decoded, not the source's original
        // resolution. Never assumed higher than the source's own recorded dpi (that would
        // imply an upscale, which getWorkerImageURL doesn't do).
        const effectiveDpi =
          imageDPI != null && imageDPI < cardDocument.dpi
            ? imageDPI
            : cardDocument.dpi;
        const prior = bleedPriors?.[cardDocument.identifier] ?? "unresolved";
        const manualOverride =
          bleedOverrides?.[cardDocument.identifier] ?? "auto";
        const normalized = await normalizeCardBleed(
          blob,
          effectiveDpi,
          bleedEdgeMM,
          prior,
          manualOverride
        );
        return createTrackedObjectURL(normalized);
      }
      return await getPDFImageURL(
        cardDocument,
        imageQuality,
        imageDPI,
        jpgQuality,
        fileHandles
      );
    } catch {
      reportImageFailure?.(cardDocument.identifier, cardDocument.name);
      return undefined;
    } finally {
      reportImageProgress?.();
    }
  };

  if (bleedNormalized) {
    // The visible box - exactly what this slot renders, corners rounded HERE (the inner Image
    // is deliberately larger and offset, so rounding it directly would clip the wrong rect).
    return (
      <View
        style={{
          width: width + "mm",
          minWidth: width + "mm",
          height: height + "mm",
          minHeight: height + "mm",
          position: "relative" as const,
          overflow: "hidden",
          borderTopLeftRadius: topLeftRadiusMM + "mm",
          borderTopRightRadius: topRightRadiusMM + "mm",
          borderBottomRightRadius: bottomRightRadiusMM + "mm",
          borderBottomLeftRadius: bottomLeftRadiusMM + "mm",
        }}
      >
        <Image
          src={imageSrc}
          style={
            {
              position: "absolute" as const,
              width: fullCarriedWidthMM + "mm",
              minWidth: fullCarriedWidthMM + "mm",
              height: fullCarriedHeightMM + "mm",
              minHeight: fullCarriedHeightMM + "mm",
              left: -cropMM.left + "mm",
              top: -cropMM.top + "mm",
            } as const
          }
        />
      </View>
    );
  }

  return (
    <View
      style={{
        width: width + "mm",
        minWidth: width + "mm",
        height: height + "mm",
        minHeight: height + "mm",
      }}
    >
      <Image
        src={imageSrc}
        style={
          {
            width: width + "mm",
            minWidth: width + "mm",
            height: height + "mm",
            minHeight: height + "mm",
            transform: scaleTransform,
            overflow: "hidden",
            borderTopLeftRadius: topLeftRadiusMM + "mm",
            borderTopRightRadius: topRightRadiusMM + "mm",
            borderBottomRightRadius: bottomRightRadiusMM + "mm",
            borderBottomLeftRadius: bottomLeftRadiusMM + "mm",
          } as const
        }
      />
    </View>
  );
};

// Renders cut lines for a single card slot, absolutely positioned within the overlay layer to
// match the card at (colIndex, rowIndex) in the grid. The default guide is a dashed rounded-rect
// outline traced directly on the bleed boundary (an Svg/Rect, not a corner mark - native SVG
// stroke-dashing continues the pattern seamlessly around the rounded corners, which the old
// segment-by-segment CutLineBar approach couldn't do for a full perimeter); the crosshair corner
// marks (CutLineCorner, same component PageCutLines uses for the sheet-wide guillotine lines) are
// an opt-in addition, not an alternative shape.
const PDFCardCutLines = ({
  colIndex,
  rowIndex,
}: {
  colIndex: number;
  rowIndex: number;
}) => {
  const ctx = usePDFContext();
  const {
    cardSpacingRowMM,
    cardSpacingColMM,
    cutLineLengthMM,
    cutLineThicknessMM,
    cutLineColor,
    cutLineOffsetMM,
    roundCorners,
    showCrossCutLines,
  } = ctx;
  // #301 - this slot's actual rendered size (may be less than CardSize + 2*bleedEdgeMM on a
  // crowded axis - see layout.ts's fitAxisWithBleed), not the flat target-bleed box the pre-
  // #301 version assumed every slot always got.
  const bleedMM = contextAvailableBleedMM(ctx);
  const cardSlotWidth = CardWidthMM + bleedMM.left + bleedMM.right;
  const cardSlotHeight = CardHeightMM + bleedMM.top + bleedMM.bottom;

  const left = colIndex * (cardSlotWidth + cardSpacingColMM);
  const top = rowIndex * (cardSlotHeight + cardSpacingRowMM);

  // The outline's own path grows outward from the slot's own bleed box (cardSlotWidth x
  // cardSlotHeight, at the slot's own origin) by cutLineOffsetMM on every side - offset 0 (the
  // default) puts the path exactly on the true bleed edge, entirely outside the printed card
  // face, which is what "sits on the bleed boundary" means for a drawn line. The Svg viewport is
  // padded by half the stroke width beyond that so the stroke's own outer edge never sits
  // exactly on (and risks being clipped at) the viewport bound.
  const outlineWidthMM = cardSlotWidth + 2 * cutLineOffsetMM;
  const outlineHeightMM = cardSlotHeight + 2 * cutLineOffsetMM;
  const strokePadMM = cutLineThicknessMM / 2;
  const svgLeftMM = -cutLineOffsetMM - strokePadMM;
  const svgTopMM = -cutLineOffsetMM - strokePadMM;
  // Kept at the card's own die-cut radius rather than grown by the bleed depth - matching that
  // would need the same edge-dependent growth PDFCardImage's own cornerRadiusMM() applies, which
  // is a change to what roundCorners means, not to this guide's position or color.
  const radiusMM = roundCorners ? CornerRadiusMM : 0;
  // Rasterized proof (fix/print-cut-guides verification pass): Svg's own width/height props
  // (unlike a View's mm-string styles, which DO get react-pdf's box-model unit conversion) are
  // read as bare point values - "63mm" renders at 63pt (~22mm), not 63mm. The Rect's own
  // coordinates share whatever physical scale the Svg viewport resolves to (no viewBox is set),
  // so every number handed to Svg/Rect below is pre-converted to points explicitly; only the
  // outer wrapping View's position (mm strings) needs no conversion.
  const outlineWidthPt = mmToPt(outlineWidthMM);
  const outlineHeightPt = mmToPt(outlineHeightMM);
  const strokePadPt = mmToPt(strokePadMM);
  const radiusPt = mmToPt(radiusMM);
  const strokeWidthPt = mmToPt(cutLineThicknessMM);
  const dashLengthPt = mmToPt(cutLineLengthMM);
  const dashGapPt = mmToPt(CUT_LINE_DASH_GAP_MM);

  return (
    <View
      style={{
        position: "absolute" as const,
        left: left + "mm",
        top: top + "mm",
        width: cardSlotWidth + "mm",
        height: cardSlotHeight + "mm",
      }}
    >
      <Svg
        style={{
          position: "absolute" as const,
          left: svgLeftMM + "mm",
          top: svgTopMM + "mm",
        }}
        width={outlineWidthPt + 2 * strokePadPt}
        height={outlineHeightPt + 2 * strokePadPt}
      >
        <Rect
          x={strokePadPt}
          y={strokePadPt}
          width={outlineWidthPt}
          height={outlineHeightPt}
          rx={radiusPt}
          ry={radiusPt}
          fill="none"
          stroke={cutLineColor}
          strokeWidth={strokeWidthPt}
          strokeDasharray={`${dashLengthPt} ${dashGapPt}`}
        />
      </Svg>
      {showCrossCutLines && (
        <>
          <CutLineCorner position="top-left" lengthMM={cutLineLengthMM} />
          <CutLineCorner position="top-right" lengthMM={cutLineLengthMM} />
          <CutLineCorner position="bottom-left" lengthMM={cutLineLengthMM} />
          <CutLineCorner position="bottom-right" lengthMM={cutLineLengthMM} />
        </>
      )}
    </View>
  );
};

const PageCutLines = ({
  colIndex,
  rowIndex,
}: {
  colIndex: number;
  rowIndex: number;
}) => {
  const {
    bleedEdgeMM,
    cardSpacingRowMM,
    cardSpacingColMM,
    pageSize,
    pageWidth,
    pageHeight,
    pageMarginLeftMM,
    pageMarginRightMM,
    pageMarginTopMM,
    pageMarginBottomMM,
    cutLineLengthMM,
  } = usePDFContext();

  const size = getPageSizeMM(pageSize, pageWidth, pageHeight);
  const lengthMM = Math.max(size.width, size.height);

  const { cardsPerRow, cardsPerCol, slots } = layoutForPage(
    size.width,
    size.height,
    bleedEdgeMM,
    cardSpacingRowMM,
    cardSpacingColMM,
    pageMarginTopMM,
    pageMarginBottomMM,
    pageMarginLeftMM,
    pageMarginRightMM
  );
  // #301 - this slot's actual rendered size (see PDFCardCutLines' own comment - same rationale).
  const bleedMM = slots[0]?.bleedMM ?? ZERO_BLEED;
  const cardSlotWidth = CardWidthMM + bleedMM.left + bleedMM.right;
  const cardSlotHeight = CardHeightMM + bleedMM.top + bleedMM.bottom;

  const left = colIndex * (cardSlotWidth + cardSpacingColMM);
  const top = rowIndex * (cardSlotHeight + cardSpacingRowMM);

  return (
    <View
      style={{
        position: "absolute" as const,
        left: left + "mm",
        top: top + "mm",
        width: cardSlotWidth + "mm",
        height: cardSlotHeight + "mm",
      }}
    >
      <CutLineCorner
        position="top-left"
        lengthMM={cutLineLengthMM}
        {...(colIndex === 0 && { horizontalLeftLengthOverrideMM: lengthMM })}
        {...(rowIndex === 0 && { verticalUpLengthOverrideMM: lengthMM })}
      />
      <CutLineCorner
        position="top-right"
        lengthMM={cutLineLengthMM}
        {...(colIndex === cardsPerRow - 1 && {
          horizontalRightLengthOverrideMM: lengthMM,
        })}
        {...(rowIndex === 0 && { verticalUpLengthOverrideMM: lengthMM })}
      />
      <CutLineCorner
        position="bottom-left"
        lengthMM={cutLineLengthMM}
        {...(colIndex === 0 && { horizontalLeftLengthOverrideMM: lengthMM })}
        {...(rowIndex === cardsPerCol - 1 && {
          verticalDownLengthOverrideMM: lengthMM,
        })}
      />
      <CutLineCorner
        position="bottom-right"
        lengthMM={cutLineLengthMM}
        {...(colIndex === cardsPerRow - 1 && {
          horizontalRightLengthOverrideMM: lengthMM,
        })}
        {...(rowIndex === cardsPerCol - 1 && {
          verticalDownLengthOverrideMM: lengthMM,
        })}
      />
    </View>
  );
};

const CardGrid = ({
  pageWidthMM,
  pageHeightMM,
  cardDocuments,
}: {
  pageWidthMM: number;
  pageHeightMM: number;
  cardDocuments: (CardDocument | undefined)[];
}) => {
  const {
    bleedEdgeMM,
    drawCardCutLines,
    drawPageCutLines,
    cardSpacingRowMM,
    cardSpacingColMM,
    pageMarginLeftMM,
    pageMarginRightMM,
    pageMarginTopMM,
    pageMarginBottomMM,
    pageOffsetXMM,
    pageOffsetYMM,
  } = usePDFContext();

  const {
    containerWidthMM: containerWidth,
    containerHeightMM: containerHeight,
    cardsPerRow,
    cardsPerCol,
    slots,
  } = layoutForPage(
    pageWidthMM,
    pageHeightMM,
    bleedEdgeMM,
    cardSpacingRowMM,
    cardSpacingColMM,
    pageMarginTopMM,
    pageMarginBottomMM,
    pageMarginLeftMM,
    pageMarginRightMM
  );
  // #301 - an empty slot's placeholder must match what a real card in this same row/column
  // actually renders at (the layout-granted bleed, `slots[0].bleedMM`), not the flat
  // `bleedEdgeMM` cap - otherwise a placeholder would be OVERSIZED on a crowded axis and throw
  // off the flex-wrap row alongside real (correctly cropped) card images.
  const placeholderBleedMM = slots[0]?.bleedMM ?? ZERO_BLEED;
  const placeholderWidthMM =
    CardWidthMM + placeholderBleedMM.left + placeholderBleedMM.right;
  const placeholderHeightMM =
    CardHeightMM + placeholderBleedMM.top + placeholderBleedMM.bottom;

  return (
    <View
      style={{
        width: containerWidth + "mm",
        height: containerHeight + "mm",
        alignSelf: "center",
        position: "relative" as const,
        // Registration compensation - shifts this already-centered container, applied on top of
        // (not instead of) the centering above. Never clamped: a negative margin here is exactly
        // as valid as a positive one, and react-pdf/Yoga's flexbox honors it the same way a
        // browser would.
        marginLeft: (pageOffsetXMM ?? 0) + "mm",
        marginTop: (pageOffsetYMM ?? 0) + "mm",
      }}
    >
      {/* Pass 0: page cut-line underlay — painted before all images so it is always on bottom */}
      {drawPageCutLines && (
        <View
          style={{
            position: "absolute" as const,
            top: 0,
            left: 0,
            width: containerWidth + "mm",
            height: containerHeight + "mm",
          }}
        >
          {Array(cardsPerCol)
            .keys()
            .toArray()
            .flatMap((rowIndex) =>
              Array(cardsPerRow)
                .keys()
                .toArray()
                .map((colIndex) => (
                  <PageCutLines
                    key={`cutlines-${rowIndex}-${colIndex}`}
                    colIndex={colIndex}
                    rowIndex={rowIndex}
                  />
                ))
            )}
        </View>
      )}

      {/* Pass 1: all card images laid out in a flex-wrap row */}
      <View
        style={{
          ...styles.section,
          width: containerWidth + "mm",
          rowGap: cardSpacingRowMM + "mm",
          columnGap: cardSpacingColMM + "mm",
        }}
      >
        {cardDocuments.map((doc, i) =>
          doc ? (
            <PDFCardImage key={`img-${i}`} cardDocument={doc} />
          ) : (
            // Empty placeholder keeps flex positions consistent for slots
            // where a card document is missing.
            <View
              key={`placeholder-${i}`}
              style={{
                width: placeholderWidthMM + "mm",
                minWidth: placeholderWidthMM + "mm",
                height: placeholderHeightMM + "mm",
                minHeight: placeholderHeightMM + "mm",
              }}
            />
          )
        )}
      </View>

      {/* Pass 2: card cut-line overlay — painted after all images so it is always on top */}
      {drawCardCutLines && (
        <View
          style={{
            position: "absolute" as const,
            top: 0,
            left: 0,
            width: containerWidth + "mm",
            height: containerHeight + "mm",
          }}
        >
          {cardDocuments.map((_, i) => {
            const colIndex = i % cardsPerRow;
            const rowIndex = Math.floor(i / cardsPerRow);
            return (
              <PDFCardCutLines
                key={`cutlines-${i}`}
                colIndex={colIndex}
                rowIndex={rowIndex}
              />
            );
          })}
        </View>
      )}
    </View>
  );
};

// Re-exported for existing importers (PDFGenerator.tsx, SCMPDF.tsx) - the implementation
// itself now lives in common/utils.ts; see that module's own comment for why.
export { chunk };

const paginateFrontsAndDistinctBacks = (
  projectMembers: Array<SlotProjectMembers>,
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined },
  projectCardback: string | undefined,
  cardsPerPage: number
): Array<Array<CardDocument>> => [
  projectMembers.flatMap((member) => {
    const front =
      member.front?.selectedImage !== undefined
        ? cardDocumentsByIdentifier[member.front.selectedImage]
        : undefined;
    const back =
      member.back?.selectedImage !== undefined &&
      member.back.selectedImage !== projectCardback
        ? cardDocumentsByIdentifier[member.back.selectedImage]
        : undefined;
    return [front, back].filter((d): d is CardDocument => d !== undefined);
  }),
];

const paginateFrontsOnly = (
  projectMembers: Array<SlotProjectMembers>,
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined },
  projectCardback: string | undefined,
  cardsPerPage: number
): Array<Array<CardDocument>> => [
  projectMembers
    .map((member) =>
      member.front?.selectedImage !== undefined
        ? cardDocumentsByIdentifier[member.front.selectedImage]
        : undefined
    )
    .filter((d): d is CardDocument => d !== undefined),
];

const paginateBacksOnly = (
  projectMembers: Array<SlotProjectMembers>,
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined },
  projectCardback: string | undefined,
  cardsPerPage: number
): Array<Array<CardDocument>> => [
  projectMembers
    .map((member) =>
      member.back?.selectedImage !== undefined
        ? cardDocumentsByIdentifier[member.back.selectedImage]
        : undefined
    )
    .filter((d): d is CardDocument => d !== undefined),
];

const paginateFrontsAndBacks = (
  projectMembers: Array<SlotProjectMembers>,
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined },
  projectCardback: string | undefined,
  cardsPerPage: number
): Array<Array<CardDocument>> => {
  const fronts = paginateFrontsOnly(
    projectMembers,
    cardDocumentsByIdentifier,
    projectCardback,
    cardsPerPage
  )[0];
  const backs = paginateBacksOnly(
    projectMembers,
    cardDocumentsByIdentifier,
    projectCardback,
    cardsPerPage
  )[0];
  const frontPages = chunk(fronts, cardsPerPage);
  const backPages = chunk(backs, cardsPerPage);
  const maxPages = Math.max(frontPages.length, backPages.length);
  return Array.from({ length: maxPages }, (_, i) =>
    [frontPages[i], backPages[i]].filter(
      (page): page is Array<CardDocument> => page !== undefined
    )
  ).flat();
};

// See the `chunk` export comment above - same reason.
export const CardSelectionModeToPaginator: {
  [cardSelectionMode in keyof typeof CardSelectionMode]: (
    projectMembers: Array<SlotProjectMembers>,
    cardDocumentsByIdentifier: {
      [identifier: string]: CardDocument | undefined;
    },
    projectCardback: string | undefined,
    cardsPerPage: number
  ) => Array<Array<CardDocument>>;
} = {
  frontsAndDistinctBacks: paginateFrontsAndDistinctBacks,
  frontsOnly: paginateFrontsOnly,
  backsOnly: paginateBacksOnly,
  frontsAndBacks: paginateFrontsAndBacks,
};

// Everything CardSelectionModeToPaginator + the per-page chunking needs - the same subset both
// the real render (PDF, below) and a caller that only wants the page COUNT (computePDFPageCount,
// for a page-range control that must reflect the real total - see PDFProps.pageRangeStart/End's
// own comment) require. Deliberately does not depend on pageRangeStart/pageRangeEnd - the range
// slices this result, it never changes what this computes.
type PDFPaginationInput = Pick<
  PDFProps,
  | "pageSize"
  | "pageWidth"
  | "pageHeight"
  | "bleedEdgeMM"
  | "cardSpacingRowMM"
  | "cardSpacingColMM"
  | "pageMarginTopMM"
  | "pageMarginBottomMM"
  | "pageMarginLeftMM"
  | "pageMarginRightMM"
  | "cardSelectionMode"
  | "projectMembers"
  | "cardDocumentsByIdentifier"
  | "projectCardback"
>;

const computePDFPages = (
  props: PDFPaginationInput
): Array<Array<CardDocument>> => {
  const size = getPageSizeMM(props.pageSize, props.pageWidth, props.pageHeight);

  const { cardsPerRow, cardsPerCol } = layoutForPage(
    size.width,
    size.height,
    props.bleedEdgeMM,
    props.cardSpacingRowMM,
    props.cardSpacingColMM,
    props.pageMarginTopMM,
    props.pageMarginBottomMM,
    props.pageMarginLeftMM,
    props.pageMarginRightMM
  );
  const cardsPerPage = cardsPerRow * cardsPerCol;

  const cardDocumentSets = CardSelectionModeToPaginator[
    props.cardSelectionMode
  ](
    props.projectMembers,
    props.cardDocumentsByIdentifier,
    props.projectCardback,
    cardsPerPage
  );
  return cardDocumentSets.flatMap((set) => chunk(set, cardsPerPage));
};

// The real, un-ranged page count a page-range control needs to show/clamp against (see
// PDFProps.pageRangeStart/End's own comment on why the control can't know this up front) -
// SCM mode paginates independently inside SCMPDF.tsx and isn't covered by this count.
export const computePDFPageCount = (props: PDFPaginationInput): number =>
  computePDFPages(props).length;

// 1-indexed, inclusive bounds, clamped defensively against the real page count so an
// out-of-range value (e.g. a stale range left over from a larger project) degrades to the
// nearest valid page rather than producing an empty or out-of-bounds slice.
const sliceToPageRange = (
  pages: Array<Array<CardDocument>>,
  pageRangeStart: number | undefined,
  pageRangeEnd: number | undefined
): Array<Array<CardDocument>> => {
  if (pageRangeStart == null && pageRangeEnd == null) {
    return pages;
  }
  const startIndex = Math.max(0, (pageRangeStart ?? 1) - 1);
  const endIndex = Math.min(pages.length, pageRangeEnd ?? pages.length);
  return pages.slice(startIndex, endIndex);
};

// The distinct card identifiers this export's page-range-sliced output actually renders - the
// same set PDFCardImage will call getPDFImageURL for. A caller that needs to fetch something
// ONCE PER CARD ahead of / alongside the render itself (pdfDownload.tsx's bleed-prior
// resolution, which hits the backend once per identifier) should scope to this list rather than
// every project member, or a page-range-restricted export still pays for the whole project.
// SCM mode paginates independently (SCMPDF.tsx) and never reads bleedPriors - nothing to scope.
// Takes the same PDFPaginationInput subset computePDFPages does (plus the range/SCM fields it
// doesn't) rather than full PDFProps, since callers resolving this ahead of the render (e.g.
// pdfDownload.tsx) don't have fileHandles populated yet.
export const computeExportedCardIdentifiers = (
  props: PDFPaginationInput &
    Pick<PDFProps, "scmMode" | "pageRangeStart" | "pageRangeEnd">
): Array<string> => {
  if (props.scmMode) {
    return [];
  }
  const pages = sliceToPageRange(
    computePDFPages(props),
    props.pageRangeStart,
    props.pageRangeEnd
  );
  return Array.from(
    new Set(pages.flat().map((cardDocument) => cardDocument.identifier))
  );
};

// The exact SCMPDFProps the SCM branch of PDF() renders with - factored out so the page count
// (computePDFRenderPageCount below) plans against the same props set, not a re-derived copy.
const scmPropsFromPDFProps = (props: PDFProps): SCMPDFProps => ({
  scmPaperSize: props.scmPaperSize,
  scmVariant: props.scmVariant,
  scmRegistration: props.scmRegistration,
  scmDuplex: props.scmDuplex,
  scmOffsetXMM: props.scmOffsetXMM,
  scmOffsetYMM: props.scmOffsetYMM,
  scmOffsetAngleDeg: props.scmOffsetAngleDeg,
  cardDocumentsByIdentifier: props.cardDocumentsByIdentifier,
  projectMembers: props.projectMembers,
  projectCardback: props.projectCardback,
  imageQuality: props.imageQuality,
  imageDPI: props.imageDPI,
  jpgQuality: props.jpgQuality,
  fileHandles: props.fileHandles,
  reportImageFailure: props.reportImageFailure,
  reportImageProgress: props.reportImageProgress,
  pageRangeStart: props.pageRangeStart,
  pageRangeEnd: props.pageRangeEnd,
});

export const PDF = (props: PDFProps) => {
  if (props.scmMode) {
    return <SCMPDF {...scmPropsFromPDFProps(props)} />;
  }

  const size = getPageSizeMM(props.pageSize, props.pageWidth, props.pageHeight);
  const pages = sliceToPageRange(
    computePDFPages(props),
    props.pageRangeStart,
    props.pageRangeEnd
  );

  return (
    <PDFContext.Provider value={props}>
      <Document pageMode="useThumbs">
        {(pages.length > 0 ? pages : [[]]).map((pageCards, i) => (
          <Page
            key={i}
            size={{ width: size.width + "mm", height: size.height + "mm" }}
            style={{
              paddingTop: props.pageMarginTopMM + "mm",
              paddingBottom: props.pageMarginBottomMM + "mm",
              paddingLeft: props.pageMarginLeftMM + "mm",
              paddingRight: props.pageMarginRightMM + "mm",
              display: "flex",
              justifyContent: "center",
            }}
          >
            <CardGrid
              pageWidthMM={size.width}
              pageHeightMM={size.height}
              cardDocuments={pageCards}
            />
          </Page>
        ))}
      </Document>
    </PDFContext.Provider>
  );
};

// The page COUNT a batch renderer plans against - the range-sliced page total for the standard
// path (mirrors what PDF() emits, including its single-empty-page fallback for an empty export),
// and the range-sliced SCM total for SCM mode (which paginates independently inside SCMPDF.tsx).
// pdf.worker.ts slices this total into PAGES_PER_BATCH chunks and re-renders each chunk via
// overloaded pageRangeStart/pageRangeEnd - matching PDF()'s own slice semantics is what makes
// the per-batch outputs concatenate back into exactly the single-shot document.
export const computePDFRenderPageCount = (props: PDFProps): number => {
  if (props.scmMode) {
    return computeSCMPDFPageCount(scmPropsFromPDFProps(props));
  }
  const pages = sliceToPageRange(
    computePDFPages(props),
    props.pageRangeStart,
    props.pageRangeEnd
  );
  return pages.length > 0 ? pages.length : 1;
};

// The worker's page-batch loop needs its ranges in ABSOLUTE deck-page numbers: PDF()/SCMPDF()
// always slice the FULL deck by pageRangeStart/pageRangeEnd, so a batch rendering the slice's
// k..m-th pages must restate them as full-deck page numbers (startPage + k - 1 .. + m - 1) -
// batch-relative bounds would re-slice the deck from page 1 and drop the caller's offset.
export const computePDFRenderWindow = (
  props: PDFProps
): { startPage: number; totalPages: number } => ({
  startPage: Math.max(0, (props.pageRangeStart ?? 1) - 1) + 1,
  totalPages: computePDFRenderPageCount(props),
});

// The per-batch element pdf.worker.ts hands to @react-pdf/renderer's pdf(). Built here (a .tsx
// module) rather than in the worker so it is constructed with JSX: createElement would type it
// ReactElement<PDFProps>, which pdf()'s ReactElement<DocumentProps> parameter rejects, while a
// JSX expression is typed JSX.Element (ReactElement<any, any>) and satisfies it - no type escape
// hatch needed at the call site.
export const createPDFElement = (
  props: PDFProps
): React.ReactElement<DocumentProps> => <PDF {...props} />;
