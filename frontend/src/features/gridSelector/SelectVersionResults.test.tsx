/**
 * Unit coverage for the /display art-picker FUNNEL (funnel-spec.md F1-F7) that's cheaper and more
 * precise to assert directly against the component than through a full Playwright/DisplayPage
 * round-trip: per-axis exclusivity, membership-driven axis rendering, count-proportional
 * disclosure tiers, SUGGESTED-chip rendering, and F5's votes-off completeness guarantee. The
 * implicit-vote CAST/reset/ack flow and the retraction-on-reselect wiring are covered end-to-end
 * in tests/SelectVersionSection.spec.ts instead (they need the real DisplayPage caller that owns
 * the retract bookkeeping - see DisplayPage.tsx's own `handleImplicitSupport` comment).
 *
 * `search` (GridSelectorSearch) is a plain object literal matching the hook's own return shape,
 * NOT the real `useGridSelectorSearch()` - that hook needs `ClientSearchContextProvider` plus a
 * real (or heavily stubbed) `ClientSearchService`, which buys nothing here: this component only
 * ever reads `search`'s fields, it never calls the hook itself.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Provider } from "react-redux";

import { TagVoteDisplayStatus } from "@/common/schema_types";
import { CardDocument } from "@/common/types";
import { ClientSearchContextProvider } from "@/features/clientSearch/clientSearchContext";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { addCardDocuments } from "@/store/slices/cardDocumentsSlice";
import { getDefaultSearchSettings } from "@/store/slices/searchSettingsSlice";
import { setupStore } from "@/store/store";

import { SelectVersionResults, VoteLayerProps } from "./SelectVersionResults";
import { GridSelectorSearch } from "./useGridSelectorSearch";

// Card.tsx's own image-source hook unconditionally reads this context (regardless of source
// type) - same stub Card.test.tsx/Navbar.test.tsx/Footer.test.tsx already use.
const stubClientSearchContext = {
  clientSearchService: {} as ClientSearchService,
  forceUpdate: () => undefined,
  forceUpdateValue: 0,
};

function makeCard(
  identifier: string,
  tags: string[],
  options: {
    tagVoteStatuses?: Record<string, TagVoteDisplayStatus>;
    suggestedFilterTagNames?: string[];
  } = {}
): CardDocument {
  return {
    identifier,
    cardType: "CARD" as CardDocument["cardType"],
    name: `Card ${identifier}`,
    priority: 0,
    source: "src",
    sourceName: "src",
    sourceId: 1,
    sourceVerbose: "src",
    dpi: 800,
    searchq: identifier,
    extension: "png",
    dateCreated: "1st January, 2000",
    dateModified: "1st January, 2000",
    size: 1_000_000,
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
    language: "EN",
    tags,
    tagVoteStatuses: options.tagVoteStatuses,
    suggestedFilterTagNames: options.suggestedFilterTagNames,
    printingTagStatus: "no_match" as CardDocument["printingTagStatus"],
  };
}

// Fix round (owner-ratified condition 6, Tron's PR #329 review) - the funnel's own compliant
// voteLayer.suggestedTagNames implementation, mirroring DisplayPage.tsx's real one exactly:
// sourced from `suggestedFilterTagNames` (implicit-excluded, floor-gated server-side), NEVER
// `tagVoteStatuses` (a source-agnostic collapse with no such guarantee - see
// attributeChips.ts's chipMembershipState comment for the full reasoning).
function buildVoteLayer(
  overrides: Partial<VoteLayerProps> = {}
): VoteLayerProps {
  return {
    onImplicitSupport: jest.fn(),
    suggestedTagNames: (card) =>
      (card.suggestedFilterTagNames ?? []).filter(
        (tagName) => !card.tags.includes(tagName)
      ),
    awarenessCopy: (tags) => `supports ${tags.join(", ")}`,
    ...overrides,
  };
}

function makeSearch(identifiers: string[]): GridSelectorSearch {
  const defaults = getDefaultSearchSettings({});
  return {
    settingsVisible: false,
    setSettingsVisible: jest.fn(),
    filterSettings: defaults.filterSettings,
    setFilterSettings: jest.fn(),
    sourceSettings: defaults.sourceSettings,
    setSourceSettings: jest.fn(),
    sortBy: undefined,
    setSortBy: jest.fn(),
    artists: [],
    setArtists: jest.fn(),
    printings: [],
    setPrintings: jest.fn(),
    sortedFilteredIdentifiers: identifiers,
    favoriteIdentifiersInFilteredResults: [],
    originalIndexMap: new Map(identifiers.map((id, index) => [id, index])),
    displaySpinner: false,
    noSearchResults: identifiers.length === 0,
    projectFilter: undefined,
    resultCount: identifiers.length,
  };
}

function renderFunnel(
  cards: CardDocument[],
  voteLayer?: VoteLayerProps,
  onSelectImage: (identifier: string) => void = jest.fn()
) {
  const store = setupStore();
  store.dispatch(
    addCardDocuments(
      Object.fromEntries(cards.map((card) => [card.identifier, card]))
    )
  );
  const identifiers = cards.map((card) => card.identifier);
  render(
    <Provider store={store}>
      <ClientSearchContextProvider value={stubClientSearchContext}>
        <SelectVersionResults
          imageIdentifiers={identifiers}
          selectedImage={undefined}
          onSelectImage={onSelectImage}
          focusRef={{ current: null }}
          search={makeSearch(identifiers)}
          requestedPrinting={undefined}
          backendURL="http://localhost:8000"
          layout="stacked"
          voteLayer={voteLayer}
        />
      </ClientSearchContextProvider>
    </Provider>
  );
}

describe("SelectVersionResults funnel (funnel-spec.md F1-F7)", () => {
  it("F2/D23 - Border axis is radio-exclusive: selecting a segment deselects the sibling, re-tapping the active one clears it", async () => {
    const user = userEvent.setup();
    // 4 Black + 4 White (not <=2 survivors even AFTER filtering to just one color) keeps the
    // tier at "medium" throughout the whole test, so the axis rows never collapse mid-test
    // (D21's hero-tier axis collapse, which would otherwise detach these very chip elements the
    // moment a filter narrows survivors to <=2).
    renderFunnel([
      ...Array.from({ length: 4 }, (_, i) =>
        makeCard(`black-${i}`, ["Black Border"])
      ),
      ...Array.from({ length: 4 }, (_, i) =>
        makeCard(`white-${i}`, ["White Border"])
      ),
    ]);

    const black = screen.getByTestId("funnel-chip-Black Border");
    const white = screen.getByTestId("funnel-chip-White Border");
    expect(black).toHaveAttribute("data-active", "false");

    await user.click(black);
    await waitFor(() => expect(black).toHaveAttribute("data-active", "true"));
    expect(white).toHaveAttribute("data-active", "false");

    await user.click(white);
    await waitFor(() => expect(white).toHaveAttribute("data-active", "true"));
    expect(black).toHaveAttribute("data-active", "false");

    // D23 - re-tapping the currently-active segment clears the axis back to "any".
    await user.click(white);
    await waitFor(() => expect(white).toHaveAttribute("data-active", "false"));
    expect(white).toHaveAttribute("data-active", "false");
  });

  it("F3 - only axes with >=1 surviving candidate render (Frame stays hidden with no Frame-tagged survivor)", () => {
    renderFunnel([
      makeCard("card-1", ["Black Border"]),
      makeCard("card-2", ["Full Art"]),
      makeCard("card-3", []),
    ]);

    expect(screen.getByTestId("funnel-axis-borderColor")).toBeInTheDocument();
    expect(screen.getByTestId("funnel-axis-treatment")).toBeInTheDocument();
    expect(screen.queryByTestId("funnel-axis-frameStyle")).toBeNull();
  });

  it("F1/D21 - count-proportional disclosure tiers: dense (>8), medium (3-8), hero (<=2)", () => {
    const many = Array.from({ length: 12 }, (_, i) => makeCard(`m-${i}`, []));
    renderFunnel(many);
    expect(screen.getByTestId("select-version-section")).toHaveAttribute(
      "data-funnel-tier",
      "dense"
    );
  });

  it("F1/D21 - medium tier at 5 survivors", () => {
    const some = Array.from({ length: 5 }, (_, i) => makeCard(`s-${i}`, []));
    renderFunnel(some);
    expect(screen.getByTestId("select-version-section")).toHaveAttribute(
      "data-funnel-tier",
      "medium"
    );
  });

  it("F1/D21 - hero tier at 1 survivor, axes collapse (not rendered)", () => {
    renderFunnel([makeCard("only-1", ["Black Border"])]);
    expect(screen.getByTestId("select-version-section")).toHaveAttribute(
      "data-funnel-tier",
      "hero"
    );
    expect(screen.queryByTestId("funnel-axes")).toBeNull();
  });

  it("F1/D21 - none tier at 0 survivors shows the empty state", () => {
    renderFunnel([]);
    expect(screen.getByTestId("select-version-section")).toHaveAttribute(
      "data-funnel-tier",
      "none"
    );
    expect(screen.getByTestId("funnel-empty-state")).toBeVisible();
  });

  // 3 candidates (not <=2) throughout this test so the tier stays "medium" and axes stay
  // visible (D21's hero-tier collapse would otherwise hide the chip regardless of membership,
  // confounding what this test is actually asserting). Fix round (condition 6) - the "suggested"
  // signal is `suggestedFilterTagNames`, the compliant source, NOT `tagVoteStatuses`.
  const suggestedOldBorderFixture = () => [
    makeCard("s-1", [], { suggestedFilterTagNames: ["Old Border"] }),
    makeCard("s-2", []),
    makeCard("s-3", []),
  ];

  it("F3 - a chip whose only surviving carrier is suggested (not resolved) renders dashed/unconfirmed, ONLY when a vote layer is supplied", () => {
    renderFunnel(suggestedOldBorderFixture(), buildVoteLayer());
    const chip = screen.getByTestId("funnel-chip-Old Border");
    expect(chip).toHaveAttribute("data-chip-membership", "suggested");
  });

  // Fix round (owner-ratified condition 6, Tron's PR #329 review) - the exact non-compliance
  // caught in review, pinned at the unit level: a card whose `tagVoteStatuses` calls a tag
  // "suggested" (the source-agnostic collapse - CONTESTED/UNRESOLVED/an implicit-only lean all
  // read this way) but whose `suggestedFilterTagNames` does NOT include it (the compliant,
  // implicit-excluded, floor-gated source says this tag doesn't qualify) must render NO suggested
  // chip and must never appear in `onImplicitSupport`'s cast set on pick.
  it("F3/condition 6 - a tag tagVoteStatuses calls 'suggested' but suggestedFilterTagNames excludes renders no suggested chip and casts no implicit vote for it", async () => {
    const user = userEvent.setup();
    const onImplicitSupport = jest.fn();
    const cards = [
      makeCard("noncompliant-1", [], {
        tagVoteStatuses: { "Old Border": TagVoteDisplayStatus.Suggested },
        suggestedFilterTagNames: [],
      }),
      makeCard("filler-1", ["Full Art"]),
      makeCard("filler-2", []),
    ];
    renderFunnel(cards, buildVoteLayer({ onImplicitSupport }));

    // No "Old Border" chip anywhere - the only carrier's tagVoteStatuses lean is not
    // corroborated by the compliant suggestedFilterTagNames source.
    expect(screen.queryByTestId("funnel-chip-Old Border")).toBeNull();

    // Activate the Full Art chip (a genuinely SETTLED, unrelated axis) and pick the
    // non-compliant candidate - it must cast no support for "Old Border" (it was never eligible),
    // and since it doesn't resolve/suggest Full Art either, it won't even survive that filter -
    // pick it directly with no filter active instead, to isolate the assertion.
    await user.click(
      screen
        .getByTestId("select-version-tile-noncompliant-1")
        .querySelector(".mpccard") as HTMLElement
    );
    expect(onImplicitSupport).toHaveBeenCalledWith("noncompliant-1", []);
  });

  it("F5 - votes-off completeness: no voteLayer means a suggested-only chip never renders (nothing to honestly filter by), and no awareness line even with active chips", () => {
    renderFunnel(suggestedOldBorderFixture(), undefined);

    // Without a vote layer, the suggested-only signal is never consulted at all (F5) - no
    // surviving candidate RESOLVES "Old Border", so the chip has nothing settled to filter by and
    // doesn't render (never a dashed/"suggested" chip in the base funnel).
    expect(screen.queryByTestId("funnel-chip-Old Border")).toBeNull();
    expect(screen.queryByTestId("funnel-awareness-line")).toBeNull();
  });

  it("F5 - votes-off completeness: a SETTLED (resolved) chip still renders and filters correctly with no vote layer, and picking under it casts no vote / shows no ack", async () => {
    const user = userEvent.setup();
    const onSelectImage = jest.fn();
    const fullArtCards = [
      makeCard("fa-1", ["Full Art"]),
      makeCard("fa-2", []),
      makeCard("fa-3", []),
    ];
    renderFunnel(fullArtCards, undefined, onSelectImage);

    const chip = screen.getByTestId("funnel-chip-Full Art");
    expect(chip).toHaveAttribute("data-chip-membership", "settled");
    await user.click(chip);
    // Filtering down to Full Art narrows the survivor count to 1 (only fa-1 carries it), which
    // collapses the axis rows per D21's hero tier - the ORIGINAL `chip` element is detached once
    // that happens, so the active state is asserted via the head's persistent active-pill instead
    // (F1's summary line, which survives the collapse) rather than re-querying the gone chip.
    await waitFor(() =>
      expect(screen.getByTestId("funnel-count")).toHaveTextContent("1 version")
    );
    expect(screen.getByTestId("funnel-active-pill-Full Art")).toBeVisible();

    const tile = screen.getByTestId("select-version-tile-fa-1");
    const card = tile.querySelector(".mpccard") as HTMLElement;
    await user.click(card);
    expect(onSelectImage).toHaveBeenCalledWith("fa-1");
    // Picking under an active (settled, metadata-equivalent) chip with no vote layer never shows
    // an ack or awareness line - a plain metadata filter, per F5.
    expect(screen.queryByTestId("funnel-support-ack")).toBeNull();
    expect(screen.queryByTestId("funnel-awareness-line")).toBeNull();
  });
});
