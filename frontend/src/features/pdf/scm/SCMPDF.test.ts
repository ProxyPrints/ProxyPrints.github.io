import { SourceType } from "@/common/schema_types";
import { CardDocument } from "@/common/types";

import { SCMPDFProps } from "./SCMPDF";
import { computeSCMPDFPageCount, slicePageGroups } from "./SCMPDF";

// SCMPDF.tsx imports @react-pdf/renderer at module scope; the pagination/count logic under test
// never touches it, so stub the components out - same pattern as displayPdfProps.test.ts.
jest.mock("@react-pdf/renderer", () => ({
  Document: () => null,
  Image: () => null,
  Page: () => null,
  StyleSheet: { create: (styles: unknown) => styles },
  View: () => null,
}));

const cardDoc = (id: string): CardDocument =>
  ({
    identifier: id,
    name: `Card ${id}`,
    sourceType: SourceType.GoogleDrive,
  } as CardDocument);

const makeSCMProps = (overrides: Partial<SCMPDFProps> = {}): SCMPDFProps => ({
  scmPaperSize: "letter",
  scmVariant: "default",
  scmRegistration: 3,
  scmDuplex: true,
  scmOffsetXMM: 0,
  scmOffsetYMM: 0,
  scmOffsetAngleDeg: 0,
  cardDocumentsByIdentifier: {},
  projectMembers: [],
  projectCardback: undefined,
  imageQuality: "full-resolution",
  imageDPI: 600,
  jpgQuality: 100,
  fileHandles: {},
  pageRangeStart: undefined,
  pageRangeEnd: undefined,
  ...overrides,
});

// A deck of `count` members, each with a resolvable front card. `resolvable` (default: every
// member) controls how many of those fronts are actually present in cardDocumentsByIdentifier -
// members whose front can't be resolved are dropped from pagination (resolveSCMPDFCards).
const deckProps = (count: number, resolvable = count): SCMPDFProps => {
  const members = Array.from({ length: count }, (_, i) => ({
    front: { selectedImage: `card-${i}` },
    back: null,
  }));
  const docs: { [id: string]: CardDocument | undefined } = {};
  for (let i = 0; i < resolvable; i++) {
    docs[`card-${i}`] = cardDoc(`card-${i}`);
  }
  return makeSCMProps({
    projectMembers: members,
    cardDocumentsByIdentifier: docs,
  });
};

describe("slicePageGroups - pure page-range slicing over the SCM page sequence", () => {
  it("3 groups, duplex: front/back interleaved, all pages", () => {
    expect(slicePageGroups(3, 2, undefined, undefined)).toEqual([
      { groupIndex: 0, isBack: false },
      { groupIndex: 0, isBack: true },
      { groupIndex: 1, isBack: false },
      { groupIndex: 1, isBack: true },
      { groupIndex: 2, isBack: false },
      { groupIndex: 2, isBack: true },
    ]);
  });

  it("3 groups, non-duplex: one front page per group", () => {
    expect(slicePageGroups(3, 1, undefined, undefined)).toEqual([
      { groupIndex: 0, isBack: false },
      { groupIndex: 1, isBack: false },
      { groupIndex: 2, isBack: false },
    ]);
  });

  it("a narrow range keeps group identity: pages 2..3 = group0 back, group1 front", () => {
    expect(slicePageGroups(3, 2, 2, 3)).toEqual([
      { groupIndex: 0, isBack: true },
      { groupIndex: 1, isBack: false },
    ]);
  });

  it("a single page range is 1-indexed inclusive: page 2 alone is group0's back", () => {
    expect(slicePageGroups(3, 2, 2, 2)).toEqual([
      { groupIndex: 0, isBack: true },
    ]);
  });

  it("the final range pages 4..6 (of a 3-group duplex export) end on group2's back", () => {
    expect(slicePageGroups(3, 2, 4, 6)).toEqual([
      { groupIndex: 1, isBack: true },
      { groupIndex: 2, isBack: false },
      { groupIndex: 2, isBack: true },
    ]);
  });

  it("end beyond the total clamps to the final page", () => {
    const refs = slicePageGroups(2, 2, 3, 99);
    expect(refs).toHaveLength(2); // pages 3,4 = group1 front+back
    expect(refs[0]).toEqual({ groupIndex: 1, isBack: false });
    expect(refs[1]).toEqual({ groupIndex: 1, isBack: true });
  });

  it("an out-of-sequence range yields no pages", () => {
    expect(slicePageGroups(2, 2, 5, 6)).toEqual([]); // beyond the 4-page total
    expect(slicePageGroups(2, 2, 3, 2)).toEqual([]); // start after end
  });

  it("zero groups yields no pages", () => {
    expect(slicePageGroups(0, 2, undefined, undefined)).toEqual([]);
  });
});

describe("computeSCMPDFPageCount", () => {
  it("an empty deck still emits the fallback page(s): 1 non-duplex, 2 duplex", () => {
    expect(computeSCMPDFPageCount(makeSCMProps({ scmDuplex: false }))).toBe(1);
    expect(computeSCMPDFPageCount(makeSCMProps({ scmDuplex: true }))).toBe(2);
  });

  it("20 cards on letter default (2x4 = 8/page): 3 groups -> 6 duplex pages", () => {
    expect(computeSCMPDFPageCount(deckProps(20))).toBe(6);
  });

  it("the same deck non-duplex is 1 page per group (3 pages)", () => {
    expect(
      computeSCMPDFPageCount(
        makeSCMProps({ ...deckProps(20), scmDuplex: false })
      )
    ).toBe(3);
  });

  it("a range slices the group-derived page total, front/back interleaved", () => {
    // Pages 2..4 of the 6-page duplex export = group0 back, group1 front, group1 back.
    const props = makeSCMProps({
      ...deckProps(20),
      pageRangeStart: 2,
      pageRangeEnd: 4,
    });
    expect(computeSCMPDFPageCount(props)).toBe(3);
  });

  it("members whose front card doesn't resolve are dropped from pagination", () => {
    // 20 members but only 16 resolvable fronts -> 16/8 = 2 groups -> 4 duplex pages.
    expect(computeSCMPDFPageCount(deckProps(20, 16))).toBe(4);
  });

  it("a4 borderless (3x3 = 9/page) paginates at the a4 layout's own card count", () => {
    const props = makeSCMProps({
      ...deckProps(20),
      scmPaperSize: "a4",
      scmVariant: "borderless",
    });
    // 20/9 = 3 groups (2 full + 1 partial) -> 6 duplex pages.
    expect(computeSCMPDFPageCount(props)).toBe(6);
  });
});
