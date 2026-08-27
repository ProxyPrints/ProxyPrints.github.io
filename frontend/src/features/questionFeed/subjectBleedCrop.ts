/**
 * Crop fractions for the What's That Card subject scan (QuestionFeed.tsx's `heroImageSrc`/
 * `subjectImageSrc`), so the voter judges the card as it would be cut rather than the raw scan
 * with whatever bleed surround the source included. Reads the SAME per-card measured bleed the
 * backend's bleed calculator already computes (`Card.measuredBleedMm`, `local_bleed_calculator.
 * py`'s Method A) rather than re-measuring anything client-side - falls back to
 * `STANDARD_BLEED_MARGIN_MM`, the same profile-default bleed `/display`'s own margin profiles
 * already assume, only when this card has no measured value yet.
 *
 * THE MATH: a card image carrying `b` mm of bleed on every edge has its own pixel aspect ratio
 * fixed at `(CardWidthMM + 2b) : (CardHeightMM + 2b)` - Method A's own closed-form reading of
 * that ratio is how `b` was derived in the first place. Cropping fraction `x = b / (CardWidthMM
 * + 2b)` off the left and right edges, and fraction `y = b / (CardHeightMM + 2b)` off the top
 * and bottom, therefore always yields a remaining region whose own ratio is exactly
 * `CardWidthMM : CardHeightMM` - the trimmed card - for ANY `b`, not just the profile default.
 * `x` and `y` differ (a portrait card's height crops less, proportionally, than its width) -
 * a single shared crop fraction would either leave bleed showing on one axis or eat into real
 * card content on the other, which is exactly what plain CSS `object-fit: cover` gets wrong
 * here (it picks one axis to crop based on the box's OWN ratio, not the measured bleed).
 */

import type { CSSProperties } from "react";

import { CardHeightMM, CardWidthMM } from "@/common/constants";
import { STANDARD_BLEED_MARGIN_MM } from "@/features/pdf/bleedNormalize";

export interface SubjectCropFractions {
  x: number;
  y: number;
}

export function subjectCropFractions(
  measuredBleedMm: number | null | undefined
): SubjectCropFractions {
  const bleedMm =
    measuredBleedMm != null && measuredBleedMm > 0
      ? measuredBleedMm
      : STANDARD_BLEED_MARGIN_MM;
  return {
    x: bleedMm / (CardWidthMM + 2 * bleedMm),
    y: bleedMm / (CardHeightMM + 2 * bleedMm),
  };
}

/**
 * The absolutely-positioned `<img>` style that performs the crop: the image is scaled up
 * (independently per axis - see this module's own doc comment for why that's correct here,
 * not a distortion) so that once its edges are pushed outside an `overflow: hidden` ancestor
 * sized to the TRIMMED card ratio (`CARD_ASPECT_RATIO`, cardPanel.tsx), exactly the bled-off
 * fraction on each side is what ends up clipped away. The ancestor must be `position: relative`
 * with `overflow: hidden` - `RevealWrapper`/`SubjectArtImage` already are.
 */
export function subjectCropImageStyle(
  measuredBleedMm: number | null | undefined
): CSSProperties {
  const { x, y } = subjectCropFractions(measuredBleedMm);
  return {
    position: "absolute",
    left: `${(-x / (1 - 2 * x)) * 100}%`,
    top: `${(-y / (1 - 2 * y)) * 100}%`,
    width: `${100 / (1 - 2 * x)}%`,
    height: `${100 / (1 - 2 * y)}%`,
    objectFit: "fill",
  };
}
