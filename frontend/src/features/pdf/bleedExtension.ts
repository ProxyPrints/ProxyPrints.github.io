/**
 * Proposal B (docs/proposals/proposal-b-bleed-normalization.md) - the canvas-based synthesis
 * half. bleedNormalize.ts measures + resolves a per-side BleedPlan (mm, positive=extend,
 * negative=trim); this module turns that plan into actual pixels. Split the same way layout.ts
 * is split from PDF.tsx: computeBleedExtensionGeometry is pure px-domain rect math (unit
 * tested, no canvas/DOM needed); normalizeCardBleed is the thin imperative OffscreenCanvas
 * pipeline around it (not unit tested - no canvas polyfill in this repo's test setup, same
 * boundary pdfImage.ts's own fetch/decode logic already sits at).
 *
 * v1 = simple canvas edge-extension (approved scope - GPU Jump Flood explicitly deferred to a
 * feedback-justified v2, per the approved spec). Corners are filled by ordering the four
 * extension passes left/right THEN top/bottom-spanning-full-width, so a top/bottom pass's
 * 1px-wide source row already includes whatever the left/right pass just wrote at that row -
 * not a true diagonal extension, but a defensible, simple v1 corner treatment.
 */

import {
  BLEED_SIDES,
  BleedPrior,
  BleedSide,
  ManualOverride,
  measureCardBleedPx,
  mmToPx,
  PixelBuffer,
  resolveBleedPlan,
} from "@/features/pdf/bleedNormalize";

export interface BleedExtensionGeometry {
  destWidthPx: number;
  destHeightPx: number;
  cropLeftPx: number;
  cropTopPx: number;
  croppedWidthPx: number;
  croppedHeightPx: number;
  extendLeftPx: number;
  extendTopPx: number;
  extendRightPx: number;
  extendBottomPx: number;
}

/**
 * Scales down a pair of opposing-side crop amounts (proportionally, preserving their ratio) so
 * their sum never exceeds availablePx - 1, leaving at least 1px of real content. Found via a
 * real Playwright regression, not a synthetic fixture: a small source image (a low-res test
 * fixture, but the same shape of bug a genuinely tiny real source could hit) combined with a
 * recorded card dpi implying a much larger physical size can make a confident-but-wrong
 * measurement (e.g. "half the image is uniform margin" on a mostly solid-color image) imply
 * trimming more than the image actually has - resolveBleedPlan's OVERSIZED_MULTIPLE check
 * catches an implausibly large MEASURED bleed relative to the target, but not an implausible
 * TRIM relative to the source's own actual pixel dimensions, which is a distinct failure mode.
 * This is the last line of defense before the numbers reach OffscreenCanvas, which throws on a
 * non-positive dimension.
 */
function clampOpposingCrop(
  cropA: number,
  cropB: number,
  availablePx: number
): [number, number] {
  const total = cropA + cropB;
  const max = Math.max(0, availablePx - 1);
  if (total <= max || total === 0) {
    return [cropA, cropB];
  }
  const scale = max / total;
  return [cropA * scale, cropB * scale];
}

/**
 * Turns a per-side plan (px, positive=extend outward, negative=trim inward - see
 * bleedNormalize.ts's BleedPlan) into concrete source-crop and dest-canvas rects. destWidthPx/
 * destHeightPx come out to sourceWidthPx/HeightPx adjusted by each side's plan, by construction
 * (crop and extend for a side are mutually exclusive - see resolveBleedPlan) - equal to the
 * card's target bleed box size when the plan was resolved against that target, UNLESS the crop
 * needed clamping (see clampOpposingCrop) - in that case the output is smaller than the target
 * bleed box, a deliberate trade (a slightly-short bleed margin) against the alternative (a
 * crashed render).
 */
export function computeBleedExtensionGeometry(
  sourceWidthPx: number,
  sourceHeightPx: number,
  planPx: Record<BleedSide, number>
): BleedExtensionGeometry {
  const [cropLeftPx, cropRightPx] = clampOpposingCrop(
    Math.max(0, -planPx.left),
    Math.max(0, -planPx.right),
    sourceWidthPx
  );
  const [cropTopPx, cropBottomPx] = clampOpposingCrop(
    Math.max(0, -planPx.top),
    Math.max(0, -planPx.bottom),
    sourceHeightPx
  );
  const extendLeftPx = Math.max(0, planPx.left);
  const extendRightPx = Math.max(0, planPx.right);
  const extendTopPx = Math.max(0, planPx.top);
  const extendBottomPx = Math.max(0, planPx.bottom);

  const croppedWidthPx = sourceWidthPx - cropLeftPx - cropRightPx;
  const croppedHeightPx = sourceHeightPx - cropTopPx - cropBottomPx;

  return {
    destWidthPx: croppedWidthPx + extendLeftPx + extendRightPx,
    destHeightPx: croppedHeightPx + extendTopPx + extendBottomPx,
    cropLeftPx,
    cropTopPx,
    croppedWidthPx,
    croppedHeightPx,
    extendLeftPx,
    extendTopPx,
    extendRightPx,
    extendBottomPx,
  };
}

/**
 * Draws the (possibly cropped) source bitmap onto ctx.canvas at its extend-inset position, then
 * edge-extends any deficit sides by re-drawing the canvas's own already-rendered edge pixels
 * (canvas-onto-itself, a standard stretch-the-edge technique) outward. Every read rect below is
 * disjoint from every write rect in the same call - never draws a canvas region onto itself
 * overlapping its own source, which is the one case real implementations disagree on.
 */
function drawNormalized(
  ctx: OffscreenCanvasRenderingContext2D,
  bitmap: ImageBitmap,
  geometry: BleedExtensionGeometry
): void {
  const {
    cropLeftPx,
    cropTopPx,
    croppedWidthPx,
    croppedHeightPx,
    extendLeftPx,
    extendTopPx,
    extendRightPx,
    extendBottomPx,
    destWidthPx,
  } = geometry;

  ctx.drawImage(
    bitmap,
    cropLeftPx,
    cropTopPx,
    croppedWidthPx,
    croppedHeightPx,
    extendLeftPx,
    extendTopPx,
    croppedWidthPx,
    croppedHeightPx
  );

  const contentTop = extendTopPx;
  if (extendLeftPx > 0) {
    ctx.drawImage(
      ctx.canvas,
      extendLeftPx,
      contentTop,
      1,
      croppedHeightPx,
      0,
      contentTop,
      extendLeftPx,
      croppedHeightPx
    );
  }
  if (extendRightPx > 0) {
    const rightEdgeX = extendLeftPx + croppedWidthPx - 1;
    ctx.drawImage(
      ctx.canvas,
      rightEdgeX,
      contentTop,
      1,
      croppedHeightPx,
      rightEdgeX + 1,
      contentTop,
      extendRightPx,
      croppedHeightPx
    );
  }
  // Top/bottom span the FULL dest width (including whatever left/right just wrote) so corners
  // inherit a sensible fill instead of staying blank - see the module comment.
  if (extendTopPx > 0) {
    ctx.drawImage(
      ctx.canvas,
      0,
      extendTopPx,
      destWidthPx,
      1,
      0,
      0,
      destWidthPx,
      extendTopPx
    );
  }
  if (extendBottomPx > 0) {
    const bottomEdgeY = contentTop + croppedHeightPx - 1;
    ctx.drawImage(
      ctx.canvas,
      0,
      bottomEdgeY,
      destWidthPx,
      1,
      0,
      bottomEdgeY + 1,
      destWidthPx,
      extendBottomPx
    );
  }
}

/** Draws `bitmap` onto a same-sized canvas and reads it back as a PixelBuffer - the only way to
 * get raw pixel access to an already-decoded ImageBitmap, needed for bleedNormalize.ts's
 * measurement pass. This canvas is separate from (and disposed before) the one the final
 * extended output gets drawn into - it never leaves this function. */
function pixelBufferFromBitmap(bitmap: ImageBitmap): PixelBuffer {
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = canvas.getContext("2d");
  if (ctx == null) {
    throw new Error("2D canvas context unavailable for bleed measurement");
  }
  ctx.drawImage(bitmap, 0, 0);
  const { data, width, height } = ctx.getImageData(
    0,
    0,
    bitmap.width,
    bitmap.height
  );
  return { data, width, height };
}

/**
 * The full per-card pipeline: decode once -> measure -> resolve the plan -> draw+extend using
 * the SAME decoded bitmap (no second decode of the source) -> encode -> release. Runs inside the
 * PDF render worker (pdf.worker.ts), where OffscreenCanvas/createImageBitmap are natively
 * available (this is exactly what they're for - off-main-thread canvas work). bitmap.close()
 * releases the decoded pixel buffer as soon as this card is done, per the approved spec's
 * memory-discipline requirement ("one card at a time... RELEASE bitmap") - see PDF.tsx's
 * PDFCardImage, the only caller, which awaits this once per card rather than batching.
 */
export async function normalizeCardBleed(
  sourceBlob: Blob,
  dpi: number,
  targetBleedMM: number,
  prior: BleedPrior,
  manualOverride: ManualOverride
): Promise<Blob> {
  const bitmap = await createImageBitmap(sourceBlob);
  try {
    const targetBleedPx = mmToPx(targetBleedMM, dpi);
    const buffer = pixelBufferFromBitmap(bitmap);
    const measurement = measureCardBleedPx(buffer, targetBleedPx);
    const planMM = resolveBleedPlan(
      measurement,
      dpi,
      targetBleedMM,
      prior,
      bitmap.width,
      bitmap.height,
      manualOverride
    );
    const planPx = Object.fromEntries(
      BLEED_SIDES.map((side) => [side, mmToPx(planMM[side], dpi)])
    ) as Record<BleedSide, number>;

    const geometry = computeBleedExtensionGeometry(
      bitmap.width,
      bitmap.height,
      planPx
    );
    const canvas = new OffscreenCanvas(
      geometry.destWidthPx,
      geometry.destHeightPx
    );
    const ctx = canvas.getContext("2d");
    if (ctx == null) {
      throw new Error("2D canvas context unavailable for bleed synthesis");
    }
    drawNormalized(ctx, bitmap, geometry);
    return await canvas.convertToBlob({ type: "image/png" });
  } finally {
    bitmap.close();
  }
}
