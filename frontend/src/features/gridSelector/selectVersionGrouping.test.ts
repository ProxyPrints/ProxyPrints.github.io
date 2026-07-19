import { CardDocument } from "@/common/types";
import { groupSelectVersionCandidates } from "@/features/gridSelector/selectVersionGrouping";

function makeCard(overrides: Partial<CardDocument> & { identifier: string }) {
  const base: CardDocument = {
    identifier: overrides.identifier,
    cardType: "CARD" as CardDocument["cardType"],
    name: overrides.identifier,
    priority: 0,
    source: "source",
    sourceName: "source",
    sourceId: 1,
    sourceVerbose: "source",
    dpi: 800,
    searchq: "",
    extension: "png",
    dateCreated: "",
    dateModified: "",
    size: 0,
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
    language: "EN",
    tags: [],
    printingTagStatus: "unresolved" as CardDocument["printingTagStatus"],
  };
  return { ...base, ...overrides };
}

describe("groupSelectVersionCandidates", () => {
  it("clusters copies of the same printing under one canonical group, keyed by identifier regardless of which field (canonicalCard/suggestedCanonicalCard) supplied it", () => {
    const resolvedCopy = makeCard({
      identifier: "resolved-copy",
      dpi: 600,
      canonicalCard: {
        identifier: "printing-A",
        expansionCode: "XYZ",
        expansionName: "XYZ Set",
        collectorNumber: "001",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });
    const suggestedCopy = makeCard({
      identifier: "suggested-copy",
      dpi: 1200,
      suggestedCanonicalCard: {
        identifier: "printing-A",
        expansionCode: "XYZ",
        expansionName: "XYZ Set",
        collectorNumber: "001",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });
    const cardDocumentsByIdentifier = {
      "resolved-copy": resolvedCopy,
      "suggested-copy": suggestedCopy,
    };

    const groups = groupSelectVersionCandidates(
      ["resolved-copy", "suggested-copy"],
      cardDocumentsByIdentifier
    );

    expect(groups.canonical).toHaveLength(1);
    expect(groups.canonical[0].key).toBe("printing-A");
    // Any member resolved -> the whole cluster counts as resolved (the edge case flagged during
    // review: canonicalCard/suggestedCanonicalCard are per-copy, not per-printing, so one copy
    // can be Resolved while a different copy of the same real printing is still Suggested).
    expect(groups.canonical[0].status).toBe("resolved");
    // Highest DPI wins the representative slot even though it's the still-suggested copy.
    expect(groups.canonical[0].representative).toBe("suggested-copy");
    expect(groups.canonical[0].rest).toEqual(["resolved-copy"]);
  });

  it("breaks a DPI tie in favor of the resolved copy", () => {
    const resolvedCopy = makeCard({
      identifier: "resolved-copy",
      dpi: 800,
      canonicalCard: {
        identifier: "printing-A",
        expansionCode: "XYZ",
        expansionName: "XYZ Set",
        collectorNumber: "001",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });
    const suggestedCopy = makeCard({
      identifier: "suggested-copy",
      dpi: 800,
      suggestedCanonicalCard: {
        identifier: "printing-A",
        expansionCode: "XYZ",
        expansionName: "XYZ Set",
        collectorNumber: "001",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });

    const groups = groupSelectVersionCandidates(
      ["suggested-copy", "resolved-copy"],
      { "suggested-copy": suggestedCopy, "resolved-copy": resolvedCopy }
    );

    expect(groups.canonical[0].representative).toBe("resolved-copy");
  });

  it("sorts resolved printings ahead of suggested ones, and the slot's own requested printing ahead of everything else regardless of status", () => {
    const resolved = makeCard({
      identifier: "resolved",
      canonicalCard: {
        identifier: "printing-resolved",
        expansionCode: "AAA",
        expansionName: "AAA Set",
        collectorNumber: "001",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });
    const suggestedRequested = makeCard({
      identifier: "suggested-requested",
      suggestedCanonicalCard: {
        identifier: "printing-requested",
        expansionCode: "ZZZ",
        expansionName: "ZZZ Set",
        collectorNumber: "099",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });
    const suggestedOther = makeCard({
      identifier: "suggested-other",
      suggestedCanonicalCard: {
        identifier: "printing-suggested-other",
        expansionCode: "BBB",
        expansionName: "BBB Set",
        collectorNumber: "002",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });

    const groups = groupSelectVersionCandidates(
      ["resolved", "suggested-requested", "suggested-other"],
      {
        resolved,
        "suggested-requested": suggestedRequested,
        "suggested-other": suggestedOther,
      },
      { expansionCode: "ZZZ", collectorNumber: "099" }
    );

    expect(groups.canonical.map((group) => group.key)).toEqual([
      "printing-requested",
      "printing-resolved",
      "printing-suggested-other",
    ]);
    expect(groups.canonical[0].isRequestedPrinting).toBe(true);
  });

  it("groups no-printing cards with a resolved reason tag into group 2, prioritized altered-frame > custom-art > ai-art, with a representative + rest", () => {
    const alteredFrame1 = makeCard({
      identifier: "altered-1",
      dpi: 400,
      tags: ["altered-frame"],
    });
    const alteredFrame2 = makeCard({
      identifier: "altered-2",
      dpi: 900,
      tags: ["altered-frame"],
    });
    const customArt = makeCard({
      identifier: "custom-1",
      tags: ["custom-art"],
    });

    const groups = groupSelectVersionCandidates(
      ["altered-1", "altered-2", "custom-1"],
      {
        "altered-1": alteredFrame1,
        "altered-2": alteredFrame2,
        "custom-1": customArt,
      }
    );

    expect(groups.nonCanonical.map((group) => group.tagName)).toEqual([
      "altered-frame",
      "custom-art",
    ]);
    const alteredGroup = groups.nonCanonical[0];
    expect(alteredGroup.representative).toBe("altered-2"); // higher DPI
    expect(alteredGroup.rest).toEqual(["altered-1"]);
  });

  it("puts cards with neither printing data nor a classifying reason tag into the unknown bucket, including cards not yet loaded", () => {
    const plain = makeCard({ identifier: "plain" });

    const groups = groupSelectVersionCandidates(["plain", "not-loaded-yet"], {
      plain,
    });

    expect(groups.canonical).toHaveLength(0);
    expect(groups.nonCanonical).toHaveLength(0);
    expect(groups.unknown).toEqual(["plain", "not-loaded-yet"]);
  });

  it("prefers a card's canonicalCard over its (mutually-exclusive-in-practice) suggestedCanonicalCard when both happen to be present", () => {
    const both = makeCard({
      identifier: "both",
      canonicalCard: {
        identifier: "printing-real",
        expansionCode: "AAA",
        expansionName: "AAA Set",
        collectorNumber: "001",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
      suggestedCanonicalCard: {
        identifier: "printing-should-not-be-used",
        expansionCode: "BBB",
        expansionName: "BBB Set",
        collectorNumber: "002",
        smallThumbnailUrl: "",
        mediumThumbnailUrl: "",
      },
    });

    const groups = groupSelectVersionCandidates(["both"], { both });

    expect(groups.canonical[0].key).toBe("printing-real");
    expect(groups.canonical[0].status).toBe("resolved");
  });
});
