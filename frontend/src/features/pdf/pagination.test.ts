import { Card } from "@/common/constants";
import { SourceType } from "@/common/schema_types";
import { CardDocument, SlotProjectMembers } from "@/common/types";
import { chunk } from "@/common/utils";

import {
  CardSelectionMode,
  CardSelectionModeToPaginator,
  DEFAULT_CARD_SELECTION_MODE,
} from "./PDF";

// PDF.tsx pulls in @react-pdf/renderer at module scope (StyleSheet.create); the paginators
// under test never touch it, so stub the renderer out rather than booting it in jsdom.
jest.mock("@react-pdf/renderer", () => ({
  Document: () => null,
  Image: () => null,
  Page: () => null,
  StyleSheet: { create: (styles: unknown) => styles },
  View: () => null,
}));

const cardDoc = (identifier: string): CardDocument =>
  ({
    identifier,
    name: `Card ${identifier}`,
    sourceType: SourceType.GoogleDrive,
  } as CardDocument);

interface ProjectFixture {
  projectMembers: Array<SlotProjectMembers>;
  cardDocumentsByIdentifier: { [identifier: string]: CardDocument | undefined };
  projectCardback: string;
}

// Every member's back is the shared project cardback - the ordinary deck the pre-print
// cardback reminder gate warns about.
const sharedCardbackProject = (count: number): ProjectFixture => {
  const projectCardback = "cardback-shared";
  const projectMembers = Array.from({ length: count }, (_, i) => ({
    id: `slot-${i}`,
    front: {
      query: { cardType: Card, query: `front-${i}` },
      selectedImage: `front-${i}`,
      selected: true,
    },
    back: {
      query: { cardType: Card, query: projectCardback },
      selectedImage: projectCardback,
      selected: true,
    },
  }));
  const identifiers = [
    ...projectMembers.map((m) => m.front.selectedImage as string),
    projectCardback,
  ];
  return {
    projectMembers,
    cardDocumentsByIdentifier: Object.fromEntries(
      identifiers.map((id) => [id, cardDoc(id)])
    ),
    projectCardback,
  };
};

// Members 0..sharedCount-1 use the shared cardback; the rest use their own custom back.
const mixedBacksProject = (
  count: number,
  sharedCount: number
): ProjectFixture => {
  const projectCardback = "cardback-shared";
  const projectMembers = Array.from({ length: count }, (_, i) => {
    const backImage = i < sharedCount ? projectCardback : `custom-back-${i}`;
    return {
      id: `slot-${i}`,
      front: {
        query: { cardType: Card, query: `front-${i}` },
        selectedImage: `front-${i}`,
        selected: true,
      },
      back: {
        query: { cardType: Card, query: backImage },
        selectedImage: backImage,
        selected: true,
      },
    };
  });
  const identifiers = [
    ...projectMembers.map((m) => m.front.selectedImage as string),
    ...projectMembers.map((m) => m.back.selectedImage as string),
  ];
  return {
    projectMembers,
    cardDocumentsByIdentifier: Object.fromEntries(
      identifiers.map((id) => [id, cardDoc(id)])
    ),
    projectCardback,
  };
};

// Mirrors how the PDF component turns paginator output into pages: each set is chunked by
// cards-per-page, in order.
const pagesOf = (
  fixture: ProjectFixture,
  mode: keyof typeof CardSelectionMode,
  cardsPerPage: number
): Array<Array<CardDocument>> =>
  CardSelectionModeToPaginator[mode](
    fixture.projectMembers,
    fixture.cardDocumentsByIdentifier,
    fixture.projectCardback,
    cardsPerPage
  ).flatMap((set) => chunk(set, cardsPerPage));

describe("PDF pagination - default card selection mode", () => {
  it("exports backs for a deck whose every card uses the shared project cardback", () => {
    const fixture = sharedCardbackProject(14);
    const sets = CardSelectionModeToPaginator[DEFAULT_CARD_SELECTION_MODE](
      fixture.projectMembers,
      fixture.cardDocumentsByIdentifier,
      fixture.projectCardback,
      9
    );
    const allDocs = sets.flat();
    // Every member must contribute a front AND a back - a fronts-only file is the defect.
    expect(allDocs).toHaveLength(fixture.projectMembers.length * 2);
    expect(
      allDocs.filter((d) => d.identifier === fixture.projectCardback)
    ).toHaveLength(fixture.projectMembers.length);
  });

  it("keeps back pages aligned with their front pages for a shared-cardback deck", () => {
    const fixture = sharedCardbackProject(10);
    const pages = pagesOf(fixture, DEFAULT_CARD_SELECTION_MODE, 4);
    expect(pages).toHaveLength(6); // F1, B1, F2, B2, F3, B3
    for (let i = 0; i < pages.length; i += 2) {
      const frontPage = pages[i];
      const backPage = pages[i + 1];
      expect(backPage).toHaveLength(frontPage.length);
      expect(frontPage.every((d) => d.identifier.startsWith("front-"))).toBe(
        true
      );
      expect(
        backPage.every((d) => d.identifier === fixture.projectCardback)
      ).toBe(true);
    }
  });

  it("keeps each back page positionally matched to its front page when backs are mixed", () => {
    const fixture = mixedBacksProject(10, 4);
    const backOf: { [frontIdentifier: string]: string } = Object.fromEntries(
      fixture.projectMembers.map((m) => [
        m.front!.selectedImage as string,
        m.back!.selectedImage as string,
      ])
    );
    const pages = pagesOf(fixture, DEFAULT_CARD_SELECTION_MODE, 4);
    expect(pages).toHaveLength(6);
    for (let i = 0; i < pages.length; i += 2) {
      const frontPage = pages[i];
      const backPage = pages[i + 1];
      expect(backPage).toHaveLength(frontPage.length);
      frontPage.forEach((frontDoc, j) => {
        expect(backPage[j].identifier).toBe(backOf[frontDoc.identifier]);
      });
    }
  });
});

describe("PDF pagination - frontsAndDistinctBacks paper-saving workflow", () => {
  it("still omits the shared project cardback (printed in bulk once, not per card)", () => {
    const fixture = sharedCardbackProject(14);
    const allDocs = pagesOf(fixture, "frontsAndDistinctBacks", 9).flat();
    expect(allDocs).toHaveLength(fixture.projectMembers.length);
    expect(
      allDocs.filter((d) => d.identifier === fixture.projectCardback)
    ).toHaveLength(0);
  });

  it("emits only the custom backs alongside the fronts for a mixed deck", () => {
    const fixture = mixedBacksProject(10, 4);
    const allDocs = pagesOf(fixture, "frontsAndDistinctBacks", 9).flat();
    const customBacks = allDocs.filter((d) =>
      d.identifier.startsWith("custom-back-")
    );
    expect(customBacks).toHaveLength(6);
    expect(
      allDocs.filter((d) => d.identifier === fixture.projectCardback)
    ).toHaveLength(0);
  });
});
