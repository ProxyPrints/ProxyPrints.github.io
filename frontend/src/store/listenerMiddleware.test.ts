/**
 * Foreign-order resilience Phase 1 (issue #324): the invalid-identifier listener in
 * listenerMiddleware.ts must NOT clear/invalidate a project member's selectedImage just
 * because it's absent from the catalog's own search results, when that identifier is (or might
 * still turn out to be) an orphan - a Drive file ID this catalog has never indexed. This is the
 * root cause of both symptoms from the owner's 2026-07-23 high-priority promotion: the text
 * import token not registering, and the XML "Back | b:null | <id>" Invalid Cards row - in both
 * cases this listener was unconditionally clearing the selectedImage the moment it noticed the
 * catalog's search didn't back it up, before this feature.
 */

import { Card as CardTypeConst } from "@/common/constants";
import { synthesizeOrphanCardDocument } from "@/common/orphanCard";
import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType, PrintingTagStatus } from "@/common/schema_types";
import { SlotProjectMembers } from "@/common/types";
import { fetchCardbacks } from "@/store/slices/cardbackSlice";
import { fetchCardDocuments } from "@/store/slices/cardDocumentsSlice";
import { selectInvalidIdentifiers } from "@/store/slices/invalidIdentifiersSlice";
import { selectProjectCardback } from "@/store/slices/projectSlice";
import { fetchSearchResults } from "@/store/slices/searchResultsSlice";
import { RootState, setupStore } from "@/store/store";

const driveId = "1FItgPw7VK_Tbv6dMiqdy5zd-jAoEC9mn";
const query = "kharn";
const hashKey = computeSearchQueryHashKey({
  query,
  cardType: CardTypeConst,
});

function buildOneFrontMemberState(
  selectedImage: string,
  cardDocuments?: RootState["cardDocuments"]["cardDocuments"]
): Partial<RootState> {
  const members: Array<SlotProjectMembers> = [
    {
      id: "slot-1",
      front: {
        query: { query, cardType: CardTypeConst },
        selectedImage,
        selected: false,
      },
      back: null,
    },
  ];
  return {
    project: {
      members,
      nextMemberId: 1,
      cardback: null,
      mostRecentlySelectedSlot: null,
      manualOverrides: {},
    },
    cardDocuments: {
      cardDocuments: cardDocuments ?? {},
      status: "idle",
      error: null,
    },
  };
}

describe("foreign-order resilience Phase 1 - invalid-identifier listener (issue #324)", () => {
  it("keeps a Drive-ID-shaped selectedImage selected when it's not yet resolved either way (early pass)", () => {
    const store = setupStore(buildOneFrontMemberState(driveId));

    store.dispatch(
      fetchSearchResults.fulfilled(
        { results: { [hashKey]: [] }, degradedQueryHashKeys: [] },
        "request-1",
        undefined
      )
    );

    expect(store.getState().project.members[0].front?.selectedImage).toBe(
      driveId
    );
    expect(selectInvalidIdentifiers(store.getState())).toEqual([]);
  });

  it("keeps a selectedImage selected once it's resolved to a synthesized orphan CardDocument", () => {
    const orphanDoc = synthesizeOrphanCardDocument(driveId, {
      name: query,
      cardType: CardType.Card,
    });
    const store = setupStore(buildOneFrontMemberState(driveId));

    // Populate search results too (empty, i.e. the catalog's search genuinely doesn't back
    // this identifier up) so the listener's per-member block actually runs, same as it would
    // once fetchSearchResults itself has resolved in a real load cycle.
    store.dispatch(
      fetchSearchResults.fulfilled(
        { results: { [hashKey]: [] }, degradedQueryHashKeys: [] },
        "request-2a",
        undefined
      )
    );
    store.dispatch(
      fetchCardDocuments.fulfilled(
        { [driveId]: orphanDoc },
        "request-2b",
        undefined
      )
    );

    expect(store.getState().project.members[0].front?.selectedImage).toBe(
      driveId
    );
    expect(
      store.getState().cardDocuments.cardDocuments[driveId]?.isOrphan
    ).toBe(true);
    expect(selectInvalidIdentifiers(store.getState())).toEqual([]);
  });

  it("still clears and records a genuinely invalid (non-Drive-ID-shaped) identifier", () => {
    const store = setupStore(buildOneFrontMemberState("too-short"));

    store.dispatch(
      fetchSearchResults.fulfilled(
        {
          results: { [hashKey]: ["a-different-real-result-id"] },
          degradedQueryHashKeys: [],
        },
        "request-3",
        undefined
      )
    );

    // Not preserved as-is: an invalidated selection gets deselected and, since real search
    // results exist for this query, replaced with the first of them - same pre-existing
    // behaviour as before this feature, unaffected for a genuinely invalid identifier.
    expect(store.getState().project.members[0].front?.selectedImage).toBe(
      "a-different-real-result-id"
    );
    expect(selectInvalidIdentifiers(store.getState())[0]?.front?.[1]).toBe(
      "too-short"
    );
  });

  it("still clears and records a known catalog card that's since been filtered out of search results (regression guard)", () => {
    const knownCard = {
      cardType: CardType.Card,
      dateCreated: "",
      dateModified: "",
      dpi: 100,
      extension: "png",
      identifier: driveId,
      language: "EN",
      mediumThumbnailUrl: "",
      name: "Kharn",
      printingTagStatus: PrintingTagStatus.Unresolved,
      priority: 0,
      searchq: query,
      size: 0,
      smallThumbnailUrl: "",
      source: "some-source",
      sourceId: 1,
      sourceName: "Some Source",
      sourceVerbose: "Some Source",
      tags: [],
    };
    const store = setupStore(
      buildOneFrontMemberState(driveId, { [driveId]: knownCard })
    );

    store.dispatch(
      fetchSearchResults.fulfilled(
        {
          results: { [hashKey]: ["a-different-real-result-id"] },
          degradedQueryHashKeys: [],
        },
        "request-4",
        undefined
      )
    );

    expect(store.getState().project.members[0].front?.selectedImage).toBe(
      "a-different-real-result-id"
    );
    expect(selectInvalidIdentifiers(store.getState())[0]?.front?.[1]).toBe(
      driveId
    );
  });
});

// Foreign-order resilience Phase 1 follow-up (issue #324, owner-observed 2026-07-23) - the
// "Common Cardback" panel (CommonCardback.tsx, the classic editor's right panel; also the source
// of truth ImportXML.tsx's own project-cardback propagation feeds) showed "Card not found" for
// an imported orphan back face. Root cause traced to THIS listener: unlike the per-slot
// invalid-identifier listener above (already fixed), it unconditionally cleared
// state.project.cardback the moment it wasn't in the catalog's own indexed cardbacks list, with
// no orphan-candidate carve-out at all - a SEPARATE concept from any individual slot's own back
// (see cardDocumentsSlice.ts's own comment on that distinction).
describe("foreign-order resilience Phase 1 follow-up - project cardback listener (issue #324)", () => {
  function buildCardbackState(
    cardback: string | null,
    cardDocuments?: RootState["cardDocuments"]["cardDocuments"]
  ): Partial<RootState> {
    return {
      project: {
        members: [],
        nextMemberId: 0,
        cardback,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      cardDocuments: {
        cardDocuments: cardDocuments ?? {},
        status: "idle",
        error: null,
      },
    };
  }

  it("keeps an orphan-looking project cardback selected when the catalog's own cardbacks list doesn't include it", () => {
    const store = setupStore(buildCardbackState(driveId));

    store.dispatch(fetchCardbacks.fulfilled([], "request-cb-1", undefined));

    expect(selectProjectCardback(store.getState())).toBe(driveId);
  });

  it("keeps a project cardback already resolved to a synthesized orphan CardDocument selected", () => {
    const orphanDoc = synthesizeOrphanCardDocument(driveId, {
      name: null,
      cardType: CardType.Cardback,
    });
    const store = setupStore(
      buildCardbackState(driveId, { [driveId]: orphanDoc })
    );

    store.dispatch(fetchCardbacks.fulfilled([], "request-cb-2", undefined));
    store.dispatch(
      fetchCardDocuments.fulfilled(
        { [driveId]: orphanDoc },
        "request-cb-2b",
        undefined
      )
    );

    expect(selectProjectCardback(store.getState())).toBe(driveId);
  });

  it("still clears and replaces a genuinely invalid (non-Drive-ID-shaped) project cardback with the first real cardback", () => {
    const store = setupStore(buildCardbackState("too-short"));

    store.dispatch(
      fetchCardbacks.fulfilled(["a-real-cardback"], "request-cb-3", undefined)
    );

    expect(selectProjectCardback(store.getState())).toBe("a-real-cardback");
  });

  it("still clears a known catalog cardback that's since been removed from the indexed list (regression guard)", () => {
    const knownCardback = {
      cardType: CardType.Cardback,
      dateCreated: "",
      dateModified: "",
      dpi: 100,
      extension: "png",
      identifier: driveId,
      language: "EN",
      mediumThumbnailUrl: "",
      name: "Some Cardback",
      printingTagStatus: PrintingTagStatus.Unresolved,
      priority: 0,
      searchq: "",
      size: 0,
      smallThumbnailUrl: "",
      source: "some-source",
      sourceId: 1,
      sourceName: "Some Source",
      sourceVerbose: "Some Source",
      tags: [],
    };
    const store = setupStore(
      buildCardbackState(driveId, { [driveId]: knownCardback })
    );

    store.dispatch(
      fetchCardbacks.fulfilled(
        ["a-different-real-cardback"],
        "request-cb-4",
        undefined
      )
    );
    store.dispatch(
      fetchCardDocuments.fulfilled(
        { [driveId]: knownCardback },
        "request-cb-4b",
        undefined
      )
    );

    expect(selectProjectCardback(store.getState())).toBe(
      "a-different-real-cardback"
    );
  });
});

// Route faces on layout, not on a fetched name list - processing.ts's unpackLine no longer
// decides split-vs-directive at parse time at all (see its own module comment), so "Fire //
// Ice" and "Opt // Char" both arrive at this listener as a front query plus an independent
// back query. The distinction can only be made once the front query resolves to a real
// CardDocument and its `layout` is known.
describe("split-face routing - back-query suppression for a split-style front layout", () => {
  const frontQuery = { query: "fire", cardType: CardTypeConst };
  const backQuery = { query: "ice", cardType: CardTypeConst };
  const frontHashKey = computeSearchQueryHashKey(frontQuery);
  const backHashKey = computeSearchQueryHashKey(backQuery);
  const frontId = "front-result-id";
  const backId = "back-result-id";
  const projectCardbackId = "project-cardback-id";

  function buildTwoFaceMemberState(): Partial<RootState> {
    const members: Array<SlotProjectMembers> = [
      {
        id: "slot-1",
        front: { query: frontQuery, selectedImage: undefined, selected: false },
        back: { query: backQuery, selectedImage: undefined, selected: false },
      },
    ];
    return {
      project: {
        members,
        nextMemberId: 1,
        cardback: projectCardbackId,
        mostRecentlySelectedSlot: null,
        manualOverrides: {},
      },
      cardDocuments: { cardDocuments: {}, status: "idle", error: null },
    };
  }

  function dispatchSearchAndResolve(
    store: ReturnType<typeof setupStore>,
    frontCardDocument: Record<string, unknown>
  ) {
    store.dispatch(
      fetchSearchResults.fulfilled(
        {
          results: { [frontHashKey]: [frontId], [backHashKey]: [backId] },
          degradedQueryHashKeys: [],
        },
        "split-request-1",
        undefined
      )
    );
    store.dispatch(
      fetchCardDocuments.fulfilled(
        { [frontId]: frontCardDocument as never },
        "split-request-2",
        undefined
      )
    );
  }

  it("clears the back query once the front resolves to a split-style layout (Fire // Ice)", () => {
    const store = setupStore(buildTwoFaceMemberState());

    dispatchSearchAndResolve(store, {
      cardType: CardType.Card,
      dateCreated: "",
      dateModified: "",
      dpi: 100,
      extension: "png",
      identifier: frontId,
      language: "EN",
      layout: "split",
      mediumThumbnailUrl: "",
      name: "Fire // Ice",
      printingTagStatus: PrintingTagStatus.Unresolved,
      priority: 0,
      searchq: "fire ice",
      size: 0,
      smallThumbnailUrl: "",
      source: "some-source",
      sourceId: 1,
      sourceName: "Some Source",
      sourceVerbose: "Some Source",
      tags: [],
    });

    const [member] = store.getState().project.members;
    expect(member.front?.selectedImage).toBe(frontId);
    expect(member.back?.query.query).toBeNull();
    expect(member.back?.selectedImage).toBe(projectCardbackId);
  });

  it("still resolves the back face of a genuine double-faced (transform) front", () => {
    const store = setupStore(buildTwoFaceMemberState());

    dispatchSearchAndResolve(store, {
      cardType: CardType.Card,
      dateCreated: "",
      dateModified: "",
      dpi: 100,
      extension: "png",
      identifier: frontId,
      language: "EN",
      layout: "transform",
      mediumThumbnailUrl: "",
      name: "Delver of Secrets",
      printingTagStatus: PrintingTagStatus.Unresolved,
      priority: 0,
      searchq: "delver of secrets",
      size: 0,
      smallThumbnailUrl: "",
      source: "some-source",
      sourceId: 1,
      sourceName: "Some Source",
      sourceVerbose: "Some Source",
      tags: [],
    });

    const [member] = store.getState().project.members;
    expect(member.front?.selectedImage).toBe(frontId);
    expect(member.back?.query.query).toBe("ice");
    expect(member.back?.selectedImage).toBe(backId);
  });

  it("leaves the back query untouched when the front's layout is unknown", () => {
    const store = setupStore(buildTwoFaceMemberState());

    dispatchSearchAndResolve(store, {
      cardType: CardType.Card,
      dateCreated: "",
      dateModified: "",
      dpi: 100,
      extension: "png",
      identifier: frontId,
      language: "EN",
      mediumThumbnailUrl: "",
      name: "Fire",
      printingTagStatus: PrintingTagStatus.Unresolved,
      priority: 0,
      searchq: "fire",
      size: 0,
      smallThumbnailUrl: "",
      source: "some-source",
      sourceId: 1,
      sourceName: "Some Source",
      sourceVerbose: "Some Source",
      tags: [],
      // layout intentionally omitted
    });

    const [member] = store.getState().project.members;
    expect(member.front?.selectedImage).toBe(frontId);
    expect(member.back?.query.query).toBe("ice");
    expect(member.back?.selectedImage).toBe(backId);
  });
});
