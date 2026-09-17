import {
  CardHeightMM,
  CardWidthMM,
  CornerRadiusMM,
  CutLineShape,
} from "@/common/constants";
import type { LayoutEdgeBleed } from "@/features/pdf/layout";

export const CUT_LINE_DASH_GAP_MM = 1;

/** Per-corner radii (mm) for the card+bleed box, matching the exporter's own formula.
 * When `roundCorners` is true, each corner's radius is `CornerRadiusMM + min(edgeA, edgeB)`
 * where `edgeA`/`edgeB` are the two adjoining bleed edges — growing the radius so the arc
 * reaches the true card edge after trimming. Returns 0 for every corner when off. */
export interface CardCornerRadius {
  topLeftMM: number;
  topRightMM: number;
  bottomLeftMM: number;
  bottomRightMM: number;
}

export const computeCardCornerRadius = (
  bleedMM: LayoutEdgeBleed,
  roundCorners: boolean
): CardCornerRadius => {
  if (!roundCorners) {
    return { topLeftMM: 0, topRightMM: 0, bottomLeftMM: 0, bottomRightMM: 0 };
  }
  const cornerMM = (a: number, b: number): number =>
    CornerRadiusMM + Math.min(a, b);
  return {
    topLeftMM: cornerMM(bleedMM.top, bleedMM.left),
    topRightMM: cornerMM(bleedMM.top, bleedMM.right),
    bottomLeftMM: cornerMM(bleedMM.bottom, bleedMM.left),
    bottomRightMM: cornerMM(bleedMM.bottom, bleedMM.right),
  };
};

export interface CutGuideInputs {
  bleedMM: LayoutEdgeBleed;
  cutLineOffsetMM: number;
  cutLineThicknessMM: number;
  cutLineLengthMM: number;
  cutLineColor: string;
  roundCorners: boolean;
  cutLineShape: CutLineShape;
}

export interface GuideRect {
  xMM: number;
  yMM: number;
  widthMM: number;
  heightMM: number;
  radiusMM: number;
  strokeWidthMM: number;
  dashLengthMM: number;
  dashGapMM: number;
  color: string;
}

export interface CornerMarkLeg {
  xMM: number;
  yMM: number;
  widthMM: number;
  heightMM: number;
  color: string;
}

export interface CutGuideGeometry {
  shouldDrawPerimeter: boolean;
  shouldDrawCornerMarks: boolean;
  perimeter: GuideRect | null;
  cornerMarks: CornerMarkLeg[];
}

export const computeCutGuideGeometry = (
  inputs: CutGuideInputs
): CutGuideGeometry => {
  const {
    bleedMM,
    cutLineOffsetMM,
    cutLineThicknessMM,
    cutLineLengthMM,
    cutLineColor,
    roundCorners,
    cutLineShape,
  } = inputs;

  const shouldDrawPerimeter =
    cutLineShape === "perimeter" || cutLineShape === "both";
  const shouldDrawCornerMarks =
    cutLineShape === "cornerMarks" || cutLineShape === "both";

  const guideXMM = bleedMM.left - cutLineOffsetMM;
  const guideYMM = bleedMM.top - cutLineOffsetMM;
  const guideWidthMM = CardWidthMM + 2 * cutLineOffsetMM;
  const guideHeightMM = CardHeightMM + 2 * cutLineOffsetMM;
  const radiusMM = roundCorners ? CornerRadiusMM : 0;

  const perimeter: GuideRect | null = shouldDrawPerimeter
    ? {
        xMM: guideXMM,
        yMM: guideYMM,
        widthMM: guideWidthMM,
        heightMM: guideHeightMM,
        radiusMM,
        strokeWidthMM: cutLineThicknessMM,
        dashLengthMM: cutLineLengthMM,
        dashGapMM: CUT_LINE_DASH_GAP_MM,
        color: cutLineColor,
      }
    : null;

  const cornerMarks: CornerMarkLeg[] = [];
  if (shouldDrawCornerMarks) {
    const leg = cutLineLengthMM;
    const stroke = cutLineThicknessMM;

    // top-left: horizontal goes right, vertical goes down
    cornerMarks.push(
      {
        xMM: guideXMM,
        yMM: guideYMM,
        widthMM: leg,
        heightMM: stroke,
        color: cutLineColor,
      },
      {
        xMM: guideXMM,
        yMM: guideYMM,
        widthMM: stroke,
        heightMM: leg,
        color: cutLineColor,
      }
    );
    // top-right: horizontal goes left, vertical goes down
    cornerMarks.push(
      {
        xMM: guideXMM + guideWidthMM - leg,
        yMM: guideYMM,
        widthMM: leg,
        heightMM: stroke,
        color: cutLineColor,
      },
      {
        xMM: guideXMM + guideWidthMM - stroke,
        yMM: guideYMM,
        widthMM: stroke,
        heightMM: leg,
        color: cutLineColor,
      }
    );
    // bottom-left: horizontal goes right, vertical goes up
    cornerMarks.push(
      {
        xMM: guideXMM,
        yMM: guideYMM + guideHeightMM - stroke,
        widthMM: leg,
        heightMM: stroke,
        color: cutLineColor,
      },
      {
        xMM: guideXMM,
        yMM: guideYMM + guideHeightMM - leg,
        widthMM: stroke,
        heightMM: leg,
        color: cutLineColor,
      }
    );
    // bottom-right: horizontal goes left, vertical goes up
    cornerMarks.push(
      {
        xMM: guideXMM + guideWidthMM - leg,
        yMM: guideYMM + guideHeightMM - stroke,
        widthMM: leg,
        heightMM: stroke,
        color: cutLineColor,
      },
      {
        xMM: guideXMM + guideWidthMM - stroke,
        yMM: guideYMM + guideHeightMM - leg,
        widthMM: stroke,
        heightMM: leg,
        color: cutLineColor,
      }
    );
  }

  return { shouldDrawPerimeter, shouldDrawCornerMarks, perimeter, cornerMarks };
};
