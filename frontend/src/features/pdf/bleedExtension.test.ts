import { computeBleedExtensionGeometry } from "@/features/pdf/bleedExtension";

describe("computeBleedExtensionGeometry", () => {
  it("all sides zero (source already matches target): dest equals source, no crop/extend", () => {
    const geometry = computeBleedExtensionGeometry(100, 140, {
      top: 0,
      bottom: 0,
      left: 0,
      right: 0,
    });
    expect(geometry.destWidthPx).toBe(100);
    expect(geometry.destHeightPx).toBe(140);
    expect(geometry.cropLeftPx).toBe(0);
    expect(geometry.extendLeftPx).toBe(0);
    expect(geometry.croppedWidthPx).toBe(100);
    expect(geometry.croppedHeightPx).toBe(140);
  });

  it("pure extend (deficit on every side): dest grows by the extension, source is placed inset, uncropped", () => {
    const geometry = computeBleedExtensionGeometry(100, 140, {
      top: 5,
      bottom: 5,
      left: 3,
      right: 3,
    });
    expect(geometry.destWidthPx).toBe(106);
    expect(geometry.destHeightPx).toBe(150);
    expect(geometry.cropLeftPx).toBe(0);
    expect(geometry.cropTopPx).toBe(0);
    expect(geometry.croppedWidthPx).toBe(100);
    expect(geometry.croppedHeightPx).toBe(140);
    expect(geometry.extendLeftPx).toBe(3);
    expect(geometry.extendTopPx).toBe(5);
    expect(geometry.extendRightPx).toBe(3);
    expect(geometry.extendBottomPx).toBe(5);
  });

  it("pure trim (excess on every side): dest shrinks by the trim, source is cropped, no extension", () => {
    const geometry = computeBleedExtensionGeometry(100, 140, {
      top: -5,
      bottom: -5,
      left: -3,
      right: -3,
    });
    expect(geometry.destWidthPx).toBe(94);
    expect(geometry.destHeightPx).toBe(130);
    expect(geometry.cropLeftPx).toBe(3);
    expect(geometry.cropTopPx).toBe(5);
    expect(geometry.croppedWidthPx).toBe(94);
    expect(geometry.croppedHeightPx).toBe(130);
    expect(geometry.extendLeftPx).toBe(0);
    expect(geometry.extendTopPx).toBe(0);
  });

  it("mixed (asymmetric) plan: each side resolves independently, dest reflects the net of all four", () => {
    const geometry = computeBleedExtensionGeometry(100, 140, {
      top: 10, // extend
      bottom: -4, // trim
      left: 0,
      right: 6, // extend
    });
    expect(geometry.cropTopPx).toBe(0);
    expect(geometry.extendTopPx).toBe(10);
    // No separate cropBottomPx/cropRightPx fields - trims on the "far" sides are absorbed
    // directly into croppedWidthPx/croppedHeightPx, since nothing downstream needs them split
    // out (the crop always starts at cropLeftPx/cropTopPx regardless of which side trimmed).
    expect(geometry.croppedHeightPx).toBe(140 - 4); // bottom trimmed by 4
    expect(geometry.destHeightPx).toBe(136 + 10); // trimmed content + top extension
    expect(geometry.extendLeftPx).toBe(0);
    expect(geometry.extendRightPx).toBe(6);
    expect(geometry.croppedWidthPx).toBe(100);
    expect(geometry.destWidthPx).toBe(106);
  });

  it("clamps an excessive trim so the cropped size never goes non-positive (real Playwright regression)", () => {
    // A real fixture hit this exactly: a small (267x372px) source image whose recorded dpi
    // implied a much larger physical size, producing a confident-but-wrong measurement that
    // wanted to trim 227px off BOTH the top and bottom of a 372px-tall image (454px total,
    // more than the image has) - see the module comment on clampOpposingCrop.
    const geometry = computeBleedExtensionGeometry(267, 372, {
      top: -227,
      bottom: -227,
      left: -122,
      right: -122,
    });
    expect(geometry.croppedWidthPx).toBeGreaterThan(0);
    expect(geometry.croppedHeightPx).toBeGreaterThan(0);
    expect(geometry.destWidthPx).toBeGreaterThan(0);
    expect(geometry.destHeightPx).toBeGreaterThan(0);
    // Clamped proportionally - top and bottom each still get roughly half of whatever crop
    // budget remains (neither side is favored over the other).
    expect(geometry.cropTopPx).toBeGreaterThan(0);
    expect(geometry.cropTopPx).toBeLessThan(227);
  });

  it("does not clamp a trim that already fits within the source", () => {
    const geometry = computeBleedExtensionGeometry(267, 372, {
      top: -50,
      bottom: -50,
      left: -20,
      right: -20,
    });
    expect(geometry.cropTopPx).toBe(50);
    expect(geometry.croppedHeightPx).toBe(372 - 100);
    expect(geometry.cropLeftPx).toBe(20);
    expect(geometry.croppedWidthPx).toBe(267 - 40);
  });
});
