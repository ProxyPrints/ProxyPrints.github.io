import { expect } from "@playwright/test";

import {
  canonicalArtist1,
  cardDocument1,
  cardDocument8,
  cardDocument9,
  printingCandidate1,
  printingCandidate2,
  printingCandidate3,
} from "@/common/test-constants";
import {
  artistCandidatesTwoResults,
  artistConsensusUnresolved,
  defaultHandlers,
  illustrationGroupCandidateA,
  illustrationGroupCandidateB,
  illustrationGroupCandidateC,
  illustrationGroupCandidateD,
  questionFeedArtist,
  questionFeedArtistConfidentlyKnown,
  questionFeedArtistWithIllustration,
  questionFeedConfirmSuggestion,
  questionFeedConfirmSuggestionSingleton,
  questionFeedIdentifyPrinting,
  questionFeedIdentifyPrintingGroupedByIllustration,
  questionFeedIdentifyPrintingOpenBorderColor,
  questionFeedTag,
  submitArtistVoteResolvesToCanonicalArtist1,
  submitIllustrationVoteCastsPrintingAndArtist,
  submitPrintingTagNoMatch,
  submitPrintingTagResolvesToPrintingCandidate1,
  submitPrintingTagResolvesToPrintingCandidate2,
  submitPrintingTagResolvesToPrintingCandidate3,
  submitQuestionAbstentionRecorded,
  submitTagVoteResolvesToApply,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { loadPageWithDefaultBackend } from "./test-utils";

// Rectangles intersect iff they overlap on both axes - the standard axis-aligned bounding box
// (AABB) test. Any edge-touching (a.right === b.left) counts as NOT intersecting, matching how
// two adjacent, non-overlapping page elements normally abut each other.
function boxesIntersect(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number }
): boolean {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}

test.describe("question feed - Level 2 (candidate grid)", () => {
  test("the attribute-chip filter is shown automatically for identify_printing questions, and can be hidden", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("attribute-chip-panel")).toBeVisible();
    await expect(page.getByTestId("question-feed-filter-toggle")).toHaveText(
      "Hide filters"
    );

    await page.getByTestId("question-feed-filter-toggle").click();

    await expect(page.getByTestId("attribute-chip-panel")).not.toBeVisible();
    await expect(page.getByTestId("question-feed-filter-toggle")).toHaveText(
      "Filter by attribute"
    );
  });

  test("narrowing by a chip hides non-matching candidates behind a clearable count, once expanded", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("attribute-chip-Full Art-yes").click(); // candidate1 is fullArt=false

    await expect(page.getByTestId("question-feed-hidden-count")).toContainText(
      "1 hidden"
    );
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(0);

    await page.getByTestId("question-feed-clear-filters").click();
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toBeVisible();
  });

  test("chip axes: Borderless hides its own Border Color siblings only; Showcase/Extended Art are mutually exclusive; Full Art is independent of both", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrinting,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("attribute-chip-Black Border")).toBeVisible();

    // Borderless is a Border Color sibling of Black/White/Silver (Scryfall's own border_color
    // enum) - it hides them, but leaves Full Art/Showcase/Extended (different axes) untouched.
    await page.getByTestId("attribute-chip-Borderless-yes").click();
    await expect(page.getByTestId("attribute-chip-Borderless")).toHaveAttribute(
      "data-chip-state",
      "positive"
    );
    await expect(page.getByTestId("attribute-chip-Black Border")).toHaveCount(
      0
    );
    await expect(page.getByTestId("attribute-chip-White Border")).toHaveCount(
      0
    );
    await expect(page.getByTestId("attribute-chip-Silver Border")).toHaveCount(
      0
    );
    await expect(page.getByTestId("attribute-chip-Full Art")).toBeVisible();
    await expect(page.getByTestId("attribute-chip-Showcase")).toBeVisible();
    await expect(page.getByTestId("attribute-chip-Extended")).toBeVisible();

    // retracting Borderless restores the rest of Border Color
    await page.getByTestId("attribute-chip-Borderless-yes").click();
    await expect(page.getByTestId("attribute-chip-Black Border")).toBeVisible();

    // Showcase and Extended Art are the one genuinely exclusive pair (0 co-occurrences,
    // measured against CanonicalPrintingMetadata) - Showcase hides Extended, but leaves Border
    // Color and Full Art (both independent of this axis) untouched.
    await page.getByTestId("attribute-chip-Showcase-yes").click();
    await expect(page.getByTestId("attribute-chip-Showcase")).toHaveAttribute(
      "data-chip-state",
      "positive"
    );
    await expect(page.getByTestId("attribute-chip-Extended")).toHaveCount(0);
    await expect(page.getByTestId("attribute-chip-Black Border")).toBeVisible();
    await expect(page.getByTestId("attribute-chip-Full Art")).toBeVisible();
    await page.getByTestId("attribute-chip-Showcase-yes").click();

    // Full Art is independent of every other axis - it never hides Border Color, Showcase, or
    // Extended Art (82% of borderless printings are also full art - Ghalta, Primal Hunger).
    await page.getByTestId("attribute-chip-Full Art-yes").click();
    await expect(page.getByTestId("attribute-chip-Full Art")).toHaveAttribute(
      "data-chip-state",
      "positive"
    );
    await expect(page.getByTestId("attribute-chip-Black Border")).toBeVisible();
    await expect(page.getByTestId("attribute-chip-White Border")).toBeVisible();
    await expect(
      page.getByTestId("attribute-chip-Silver Border")
    ).toBeVisible();
    await expect(page.getByTestId("attribute-chip-Showcase")).toBeVisible();
    await expect(page.getByTestId("attribute-chip-Extended")).toBeVisible();
  });

  test('"Art matches, not an official printing" casts a no-match printing vote plus a positive custom-art tag vote, then advances', async ({
    page,
    network,
  }) => {
    let submittedPrinting: {
      printingIdentifier?: string;
      isNoMatch?: boolean;
    } = {};
    let submittedTag: { tagName?: string; polarity?: number } = {};
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate1,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        submittedPrinting = request.postDataJSON();
      }
      if (request.url().includes("/2/submitTagVote/")) {
        submittedTag = request.postDataJSON();
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-custom-art").click();

    await expect.poll(() => submittedPrinting.isNoMatch).toBe(true);
    expect(submittedPrinting.printingIdentifier).toBeUndefined();
    await expect.poll(() => submittedTag.tagName).toBe("custom-art");
    expect(submittedTag.polarity).toBe(1);
  });
});

test.describe("question feed - Level 3 (conditional open-attribute confirm)", () => {
  test("selecting a candidate whose border color falls outside the taxonomy opens Level 3 for Border Color only", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrintingOpenBorderColor,
      submitPrintingTagResolvesToPrintingCandidate3,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(`[data-card-identifier="${printingCandidate3.identifier}"]`)
      .click();

    await expect(page.getByTestId("question-feed-level3")).toBeVisible();
    await expect(
      page.getByTestId("question-feed-level3-chip-Black Border")
    ).toBeVisible();
    // Frame Treatment (Showcase) already matched, so it's not asked about again here.
    await expect(
      page.getByTestId("question-feed-level3-chip-Showcase")
    ).toHaveCount(0);
  });

  test("picking one option in Level 3 and confirming submits just that vote", async ({
    page,
    network,
  }) => {
    const submittedTagNames: string[] = [];
    network.use(
      questionFeedIdentifyPrintingOpenBorderColor,
      submitPrintingTagResolvesToPrintingCandidate3,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        const tagName = request.postDataJSON()?.tagName;
        if (tagName != null) submittedTagNames.push(tagName);
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(`[data-card-identifier="${printingCandidate3.identifier}"]`)
      .click();
    await expect(page.getByTestId("question-feed-level3")).toBeVisible();

    await page.getByTestId("question-feed-level3-chip-White Border").click();
    await page.getByTestId("question-feed-level3-confirm").click();

    await expect
      .poll(() => submittedTagNames.includes("White Border"))
      .toBe(true);
  });

  test("Level 3's skip advances without submitting any open-question vote", async ({
    page,
    network,
  }) => {
    let tagVoteSubmitted = false;
    network.use(
      questionFeedIdentifyPrintingOpenBorderColor,
      submitPrintingTagResolvesToPrintingCandidate3,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitTagVote/")) {
        tagVoteSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(`[data-card-identifier="${printingCandidate3.identifier}"]`)
      .click();
    await expect(page.getByTestId("question-feed-level3")).toBeVisible();
    tagVoteSubmitted = false; // ignore the auto-tag votes cast on selection itself

    await page.getByTestId("question-feed-level3-skip").click();

    // the static mock re-serves the identical item on refetch (no stateful "next card"), so
    // this only asserts the negative - no open-question vote was submitted by Skip - rather
    // than a post-advance UI state the mock can't actually produce.
    await page.waitForTimeout(200);
    expect(tagVoteSubmitted).toBe(false);
  });
});

// Issue #503 (WTC phase C1) - grouping the Level 2 candidate grid by shared Scryfall
// illustration. `questionFeedIdentifyPrintingGroupedByIllustration` serves a MIXED set:
// candidateA/B share an illustration (a real 2-member cluster), candidateC has its own
// distinct illustrationId (a cluster of one - group size is orthogonal to whether a candidate
// clusters at all), candidateD carries no illustrationId at all - the nullable,
// frequently-absent shape (CanonicalPrintingMetadata.illustration_id, see
// local_illustration.py:137's isnull filter) and the only one of the four that never clusters.
test.describe("question feed - Level 2 illustration grouping", () => {
  test("every candidate in a mixed illustration set is accounted for - a group collapses to its one representative tile, ungrouped candidates still render individually", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    // candidateA carries the art crop, so it's the group's chosen representative
    // (QuestionFeed.tsx's `group.find((c) => c.artCropUrl) ?? group[0]`) - the group renders
    // ONE tile for the whole cluster, not one per member.
    await expect(
      page.locator(
        `[data-card-identifier="${illustrationGroupCandidateA.identifier}"]`
      )
    ).toHaveCount(1);
    // candidateB shares the illustration but loses the representative pick to A - it renders
    // no tile of its own anywhere; its vote is carried by A's tile, not silently dropped.
    await expect(
      page.locator(
        `[data-card-identifier="${illustrationGroupCandidateB.identifier}"]`
      )
    ).toHaveCount(0);

    // The regression guard this task calls out explicitly: an exact count, not just "at least
    // one" - a candidate silently vanishing (e.g. because it has no illustrationId) is exactly
    // the correctness regression a weaker assertion would miss.
    for (const candidate of [
      illustrationGroupCandidateC,
      illustrationGroupCandidateD,
    ]) {
      await expect(
        page.locator(`[data-card-identifier="${candidate.identifier}"]`)
      ).toHaveCount(1);
    }
  });

  test("only the illustration group's representative candidate renders inside its own illustration-group container; a null-illustration candidate never clusters", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    // Two groups render: A/B's real 2-member cluster, and C's own cluster of one (group size
    // is orthogonal to whether a candidate clusters at all).
    const groups = page.getByTestId("question-feed-illustration-group");
    await expect(groups).toHaveCount(2);

    const sharedGroup = page.locator(
      '[data-testid="question-feed-illustration-group"][data-illustration-id="illustration-shared"]'
    );
    await expect(
      sharedGroup.locator(
        `[data-card-identifier="${illustrationGroupCandidateA.identifier}"]`
      )
    ).toHaveCount(1);
    // candidateB shares the illustration but has no art crop, so A wins the representative
    // pick and the group renders only A's tile - not B's.
    await expect(
      sharedGroup.locator(
        `[data-card-identifier="${illustrationGroupCandidateB.identifier}"]`
      )
    ).toHaveCount(0);

    const soloGroup = page.locator(
      '[data-testid="question-feed-illustration-group"][data-illustration-id="illustration-unique-to-c"]'
    );
    await expect(
      soloGroup.locator(
        `[data-card-identifier="${illustrationGroupCandidateC.identifier}"]`
      )
    ).toHaveCount(1);

    // candidateD (null illustrationId) never forms or joins any cluster.
    await expect(
      groups.locator(
        `[data-card-identifier="${illustrationGroupCandidateD.identifier}"]`
      )
    ).toHaveCount(0);
  });

  test("the illustration group's one tile renders its representative candidate's art crop; ungrouped tiles keep the printing scan regardless", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    const sharedGroup = page.locator(
      '[data-testid="question-feed-illustration-group"][data-illustration-id="illustration-shared"]'
    );
    await expect(
      sharedGroup.locator(
        `[data-card-identifier="${illustrationGroupCandidateA.identifier}"] img`
      )
    ).toHaveAttribute("src", illustrationGroupCandidateA.artCropUrl as string);

    // candidateD is the only member of this mixed set with no illustrationId, so it's the
    // only one that stays in the flat ungrouped grid at all.
    const ungroupedGrid = page.getByTestId(
      "question-feed-candidate-grid-ungrouped"
    );
    await expect(
      ungroupedGrid.locator(
        `[data-card-identifier="${illustrationGroupCandidateD.identifier}"] img`
      )
    ).toHaveAttribute("src", illustrationGroupCandidateD.mediumThumbnailUrl);
  });

  // Issue #746 - the illustration crop isn't card-shaped, so its tile's frame must not force
  // the full-card 63/88 ratio the way an ungrouped (full-scan) tile's frame still does.
  test("the illustration group's tile uses a landscape frame; an ungrouped tile keeps the card-ratio frame", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    // Measured on the art frame itself (question-feed-candidate-art-frame), not the whole
    // tile - the tile's total height also includes the caption strip below the frame, whose
    // own fixed text height would dilute the frame's actual aspect ratio at narrow tile
    // widths where the caption is a larger fraction of the total.
    const sharedGroup = page.locator(
      '[data-testid="question-feed-illustration-group"][data-illustration-id="illustration-shared"]'
    );
    const groupFrameBox = await sharedGroup
      .locator(
        `[data-card-identifier="${illustrationGroupCandidateA.identifier}"]`
      )
      .getByTestId("question-feed-candidate-art-frame")
      .boundingBox();
    expect(groupFrameBox).not.toBeNull();
    const groupFrameRatio = groupFrameBox!.width / groupFrameBox!.height;
    // Landscape (584/444 ~= 1.315) - wider than tall.
    expect(groupFrameRatio).toBeGreaterThan(1.2);
    expect(groupFrameRatio).toBeLessThan(1.4);

    // candidateD is the only member of this mixed set that stays in the flat ungrouped grid.
    const ungroupedGrid = page.getByTestId(
      "question-feed-candidate-grid-ungrouped"
    );
    const ungroupedFrameBox = await ungroupedGrid
      .locator(
        `[data-card-identifier="${illustrationGroupCandidateD.identifier}"]`
      )
      .getByTestId("question-feed-candidate-art-frame")
      .boundingBox();
    expect(ungroupedFrameBox).not.toBeNull();
    const ungroupedFrameRatio =
      ungroupedFrameBox!.width / ungroupedFrameBox!.height;
    // Portrait card ratio (63/88 ~= 0.716) - taller than wide.
    expect(ungroupedFrameRatio).toBeGreaterThan(0.65);
    expect(ungroupedFrameRatio).toBeLessThan(0.78);
  });

  // Issue #709 - the illustration-credit ArtistSupportLink used to always stack the page-link
  // button, up to five commerce buttons, a badge, and a credit line next to the question - up to
  // ~8 rows. It now defaults to one collapsed line and expands on demand; the expansion must
  // never cover the pinned reference image (SPEC-wtc-rebuild.md Amendment A2).
  test("the illustration-credit Artist Support Link is compact by default and its expansion never overlaps the pinned reference image", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    // Both illustration groups (A/B's cluster and C's own cluster of one) carry the same
    // artist, so scope to the shared-illustration group specifically to keep this locator
    // unambiguous.
    const sharedGroup = page.locator(
      '[data-testid="question-feed-illustration-group"][data-illustration-id="illustration-shared"]'
    );
    const credit = sharedGroup.getByTestId("question-feed-illustration-credit");
    const applet = credit.getByTestId("artist-support-applet");
    await expect(applet.getByTestId("artist-support-link")).toContainText(
      "Some Artist"
    );
    await expect(applet.getByTestId("artist-support-credit")).toHaveCount(0);
    await expect(
      applet.getByTestId("artist-support-commerce-links")
    ).toHaveCount(0);

    // Collapsed: one line, well under the height a stacked applet (page link + credit, let
    // alone commerce buttons) would need.
    const collapsedBox = await applet.boundingBox();
    expect(collapsedBox).not.toBeNull();
    expect((collapsedBox as { height: number }).height).toBeLessThan(40);

    await applet.getByTestId("artist-support-toggle").click();
    await expect(applet.getByTestId("artist-support-credit")).toBeVisible();

    const subjectBox = await page
      .getByTestId("question-feed-subject-art")
      .boundingBox();
    const expandedBox = await applet.boundingBox();
    expect(subjectBox).not.toBeNull();
    expect(expandedBox).not.toBeNull();
    expect(
      boxesIntersect(
        subjectBox as { x: number; y: number; width: number; height: number },
        expandedBox as {
          x: number;
          y: number;
          width: number;
          height: number;
        }
      )
    ).toBe(false);

    // Collapsing again hides the credit without unmounting the applet.
    await applet.getByTestId("artist-support-toggle").click();
    await expect(applet.getByTestId("artist-support-credit")).toHaveCount(0);
  });

  // Issue #503 (WTC phase C2) / #524 - supersedes this describe block's former "selecting a
  // grouped candidate submits the identical payload to the identical endpoint as an ungrouped
  // one" test (see .github/coverage-acks.txt for the rename ack). That title asserted phase
  // C1's contract: C1 was deliberately presentation-only, so tapping any candidate - grouped
  // or not - submitted the identical /2/submitPrintingTag/ payload. C2 intentionally splits
  // that: a grouped tap now goes to /2/submitIllustrationVote/ with ONE illustrationId, never
  // a printing list, while an ungrouped tap is unchanged. These two tests assert that split.
  test("selecting a grouped candidate submits its illustrationId to /2/submitIllustrationVote/, not a printing list", async ({
    page,
    network,
  }) => {
    let submittedIllustrationVote:
      | { illustrationId?: string; isUnknown?: boolean }
      | undefined;
    let printingTagSubmitted = false;
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      submitIllustrationVoteCastsPrintingAndArtist,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitIllustrationVote/")) {
        submittedIllustrationVote = request.postDataJSON();
      }
      if (request.url().includes("/2/submitPrintingTag/")) {
        printingTagSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(
        `[data-card-identifier="${illustrationGroupCandidateA.identifier}"]`
      )
      .click();

    await expect
      .poll(() => submittedIllustrationVote?.illustrationId)
      .toBe("illustration-shared");
    expect(submittedIllustrationVote?.isUnknown).toBe(false);
    expect(submittedIllustrationVote).not.toHaveProperty("printingIdentifier");
    expect(printingTagSubmitted).toBe(false);
  });

  test("selecting a null-illustration candidate still submits to /2/submitPrintingTag/, unchanged", async ({
    page,
    network,
  }) => {
    let submittedPrinting:
      | { printingIdentifier?: string; isNoMatch?: boolean }
      | undefined;
    let illustrationVoteSubmitted = false;
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      submitPrintingTagResolvesToPrintingCandidate1,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        submittedPrinting = request.postDataJSON();
      }
      if (request.url().includes("/2/submitIllustrationVote/")) {
        illustrationVoteSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // candidateD is the only member of this mixed set with no illustrationId - the only one
    // that never clusters and stays on the ungrouped /2/submitPrintingTag/ path.
    await page
      .locator(
        `[data-card-identifier="${illustrationGroupCandidateD.identifier}"]`
      )
      .click();

    await expect
      .poll(() => submittedPrinting?.printingIdentifier)
      .toBe(illustrationGroupCandidateD.identifier);
    expect(submittedPrinting?.isNoMatch).toBe(false);
    expect(illustrationVoteSubmitted).toBe(false);
  });

  // Issue #503 (WTC composition pass) - the old `>= 2` cluster rule is deleted: group size is
  // orthogonal to whether a candidate clusters at all. candidateC has its own distinct
  // illustrationId and no sibling, but still forms a cluster of one and still votes through
  // the illustration channel, never a direct printing vote.
  test("a singleton illustration still submits its illustrationId to /2/submitIllustrationVote/, never /2/submitPrintingTag/", async ({
    page,
    network,
  }) => {
    let submittedIllustrationVote:
      | { illustrationId?: string; isUnknown?: boolean }
      | undefined;
    let printingTagSubmitted = false;
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      submitIllustrationVoteCastsPrintingAndArtist,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitIllustrationVote/")) {
        submittedIllustrationVote = request.postDataJSON();
      }
      if (request.url().includes("/2/submitPrintingTag/")) {
        printingTagSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(
        `[data-card-identifier="${illustrationGroupCandidateC.identifier}"]`
      )
      .click();

    await expect
      .poll(() => submittedIllustrationVote?.illustrationId)
      .toBe("illustration-unique-to-c");
    expect(submittedIllustrationVote).not.toHaveProperty("printingIdentifier");
    expect(printingTagSubmitted).toBe(false);
  });
});

test.describe("question feed - confirm_suggestion question type", () => {
  test("lands on the suggested-match question - the suggestion is asked about in its own slot, never re-presented as a grid tile", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(
      page.getByTestId("question-feed-suggestion-prompt")
    ).toContainText("Is it this one?");
    await expect(
      page.getByTestId("question-feed-suggestion-yes")
    ).toBeVisible();
    // The suggested candidate is judged once, in its own slot, never re-presented as a tile -
    // the rest of the candidates render only once "Not this art" summons the identification
    // question (its own dedicated test above), not on this fresh page.
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(0);

    // Regression check (#49 dropped this): the suggestion slot still needs its own reference
    // render of the suggested printing to compare against - "Is it this one?" is
    // unanswerable from text alone. `getByRole("img")` (not a plain `img` locator) - round
    // 3's shared `<MysteryCard />` (own comment, cardPanel.tsx) renders a SECOND `<img>` in
    // this same container (its own "?" glyph, `alt=""`), which a bare `locator("img")` now
    // matches too, causing a Playwright strict-mode violation. `alt=""` strips an <img> from
    // the accessibility tree entirely, so `getByRole` (unlike a tag-selector) unambiguously
    // resolves to just the real reference thumbnail below.
    const referenceImage = page
      .getByTestId("question-feed-suggestion-reference-image")
      .getByRole("img");
    await expect(referenceImage).toBeVisible();
    await expect(referenceImage).toHaveAttribute(
      "src",
      printingCandidate1.mediumThumbnailUrl
    );
  });

  test("YES on the suggestion casts the printing vote for it directly", async ({
    page,
    network,
  }) => {
    let submittedPrintingIdentifier: string | undefined;
    network.use(
      questionFeedConfirmSuggestion,
      submitPrintingTagResolvesToPrintingCandidate1,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        submittedPrintingIdentifier =
          request.postDataJSON()?.printingIdentifier;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-suggestion-yes").click();

    await expect
      .poll(() => submittedPrintingIdentifier)
      .toBe(printingCandidate1.identifier);
  });

  test("confirm_suggestion's own question renders no chip panel and no candidate grid", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(
      page.getByTestId("question-feed-suggestion-yes")
    ).toBeVisible();
    await expect(page.getByTestId("attribute-chip-panel")).toHaveCount(0);
    await expect(
      page.getByTestId("question-feed-candidate-grid-ungrouped")
    ).toHaveCount(0);
  });

  test("SKIP records an abstention and advances to the next question, without casting a printing vote", async ({
    page,
    network,
  }) => {
    let printingTagSubmitted = false;
    let abstentionBody: { identifier?: string; questionType?: string } = {};
    let feedFetchCount = 0;
    network.use(
      questionFeedConfirmSuggestion,
      submitQuestionAbstentionRecorded,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        printingTagSubmitted = true;
      }
      if (request.url().includes("/2/submitQuestionAbstention/")) {
        abstentionBody = request.postDataJSON();
      }
      if (request.url().includes("/2/questionFeed/")) {
        feedFetchCount += 1;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-suggestion-skip").click();

    expect(printingTagSubmitted).toBe(false);
    await expect.poll(() => feedFetchCount).toBeGreaterThanOrEqual(2);
    await expect
      .poll(() => abstentionBody.identifier)
      .toBe(cardDocument1.identifier);
    expect(abstentionBody.questionType).toBe("confirm_suggestion");
  });

  test("'Not this art' gives way to the candidate-grid identification question, where the rejected suggestion stays as a de-emphasised, re-selectable tile, and keeps the remaining candidates selectable, without casting a vote", async ({
    page,
    network,
  }) => {
    // Issue #728 - the suggestion slot is judged once and gives way on "Not this art" (no
    // stage transition); issue #748 - the rejected suggestion does NOT vanish: it joins the
    // grid as a de-emphasised (`data-rejected="true"`) tile that stays fully selectable (the
    // reconsider path), while the remaining candidate (printingCandidate2) stays selectable
    // on the SAME page. "Not this art" itself casts no vote - see markNotThisArt in
    // QuestionFeed.tsx for why no backend channel records "this specific illustration is
    // wrong".
    let printingTagSubmitted = false;
    let illustrationVoteSubmitted = false;
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        printingTagSubmitted = true;
      }
      if (request.url().includes("/2/submitIllustrationVote/")) {
        illustrationVoteSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-suggestion-not-this-art").click();

    // #748 - the rejected suggestion is present, but only as the de-emphasised tile.
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(1);
    await expect(
      page.locator(
        `[data-card-identifier="${printingCandidate1.identifier}"][data-rejected="true"]`
      )
    ).toBeVisible();
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
    ).toBeVisible();
    // contextual copy replaces the suggestion slot's "Is it this one?"
    await expect(
      page.getByTestId("question-feed-suggestion-prompt")
    ).toContainText("let's find the actual printing");
    expect(printingTagSubmitted).toBe(false);
    expect(illustrationVoteSubmitted).toBe(false);
  });

  test("'Not this art' on a singleton suggestion leaves the rejected candidate as the grid's one de-emphasised tile and casts nothing automatically", async ({
    page,
    network,
  }) => {
    // The singleton case no longer auto-casts a terminal isNoMatch vote (that shortcut
    // belonged to the old "No, different printing" answer, whose claim was "no OTHER
    // candidate matches" - a claim "Not this art" doesn't make; "wrong artwork entirely" has
    // nothing to auto-vote). The user reaches the same "None of these" fallback explicitly,
    // via the identification body's own bottom row, same as identify_printing.
    let submittedPrinting:
      | { printingIdentifier?: string; isNoMatch?: boolean }
      | undefined;
    network.use(
      questionFeedConfirmSuggestionSingleton,
      submitPrintingTagNoMatch,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        submittedPrinting = request.postDataJSON();
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-suggestion-not-this-art").click();

    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(1);
    await expect(
      page.locator(
        `[data-card-identifier="${printingCandidate1.identifier}"][data-rejected="true"]`
      )
    ).toBeVisible();
    const rejectedContext = page.getByTestId("question-feed-rejected-context");
    await expect(rejectedContext).toBeVisible();
    await expect(rejectedContext).toContainText("not");
    // nothing cast automatically - "None of these" is still one explicit tap away
    expect(submittedPrinting).toBeUndefined();

    await page.getByTestId("question-feed-no-match").click();
    await expect.poll(() => submittedPrinting?.isNoMatch).toBe(true);
    expect(submittedPrinting?.printingIdentifier).toBeUndefined();
    await expect(page.getByTestId("no-match-reason-strip")).toBeVisible();
  });

  test("'Same art, but...' casts the illustration vote for the suggested printing on tap, then summons the border/frame attribute chips - no candidate grid", async ({
    page,
    network,
  }) => {
    let submittedIllustrationVote:
      | { illustrationId?: string; isUnknown?: boolean }
      | undefined;
    network.use(
      questionFeedConfirmSuggestion,
      submitIllustrationVoteCastsPrintingAndArtist,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    page.on("request", (request) => {
      if (request.url().includes("/2/submitIllustrationVote/")) {
        submittedIllustrationVote = request.postDataJSON();
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-suggestion-same-art-but").click();

    await expect
      .poll(() => submittedIllustrationVote?.illustrationId)
      .toBe(printingCandidate1.illustrationId);
    await expect(page.getByTestId("attribute-chip-panel")).toBeVisible();
    await expect(
      page.getByTestId("question-feed-candidate-grid-ungrouped")
    ).toHaveCount(0);
  });

  test("at a 390px mobile viewport, no answer control overlaps the card art", async ({
    page,
    network,
  }) => {
    // Regression guard for a real-device-only bug (not reproducible in this sandbox's
    // Chromium): the pinned reference card (Subject, A2) used a sticky, negative-z-index
    // CardPanel that composited incorrectly on a real phone at narrow widths - answer controls
    // painted overlapping the card art instead of cleanly below it. This asserts the
    // non-overlap property directly via bounding-box math rather than relying on visual
    // diffing this sandbox can't validate against real hardware anyway.
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // The card's full box (art + starburst + name caption), not just the <img> - the
    // real-device bug this guards against overlapped the caption too, not only the artwork.
    const cardPanel = page.getByTestId("question-feed-card-panel");
    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await expect(
      page.getByTestId("question-feed-suggestion-yes")
    ).toBeVisible();

    const cardBox = await cardPanel.boundingBox();
    expect(cardBox).not.toBeNull();

    const controls = [
      page.getByTestId("question-feed-tier-badge"),
      page.getByTestId("question-feed-suggestion-prompt"),
      page.getByTestId("question-feed-suggestion-yes"),
      page.getByTestId("question-feed-suggestion-same-art-but"),
      page.getByTestId("question-feed-suggestion-not-this-art"),
      page.getByTestId("question-feed-suggestion-skip"),
    ];
    for (const control of controls) {
      const controlBox = await control.boundingBox();
      expect(controlBox).not.toBeNull();
      expect(boxesIntersect(cardBox!, controlBox!)).toBe(false);
    }
  });
});

// Issue #741 - the subject art title used to sit absolutely-positioned inside the artwork's
// own box, covering its bottom edge; it now renders below the art in normal document flow.
test.describe("question feed - subject art title placement (issue #741)", () => {
  test("at Level 1, the title never overlaps the artwork, and sits below it", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    const artBox = await page
      .getByTestId("question-feed-subject-art-image")
      .boundingBox();
    const titleBox = await page
      .getByTestId("question-feed-subject-art-title")
      .boundingBox();
    expect(artBox).not.toBeNull();
    expect(titleBox).not.toBeNull();
    expect(boxesIntersect(artBox!, titleBox!)).toBe(false);
    expect(titleBox!.y).toBeGreaterThanOrEqual(artBox!.y + artBox!.height);
  });

  test("at Level 2 (pinned subject sidebar), the title never overlaps the artwork, and sits below it", async ({
    page,
    network,
  }) => {
    network.use(questionFeedIdentifyPrinting, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    const artBox = await page
      .getByTestId("question-feed-subject-art-image")
      .boundingBox();
    const titleBox = await page
      .getByTestId("question-feed-subject-art-title")
      .boundingBox();
    expect(artBox).not.toBeNull();
    expect(titleBox).not.toBeNull();
    expect(boxesIntersect(artBox!, titleBox!)).toBe(false);
    expect(titleBox!.y).toBeGreaterThanOrEqual(artBox!.y + artBox!.height);
  });
});

// One Playwright flow per question type, per the queue-redesign task spec's TESTS
// requirement - artist and tag types reuse ArtistVotePicker/QueueTagQuestion directly (no
// forks), so these assert the unified feed renders them correctly, not the pickers'
// internals (already covered by VotePickers.spec.ts elsewhere).
test.describe("question feed - artist question type", () => {
  test("renders ArtistVotePicker for an artist-type item", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtist,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByAltText(cardDocument8.name)).toBeVisible();
    await expect(page.getByTestId("artist-vote-picker")).toBeVisible();
    await expect(
      page.getByPlaceholder("Search for an artist...")
    ).toBeVisible();
  });

  // WTC artist question re-frame: the subject image substitutes the canonical printing's
  // Scryfall art-crop URL when the backend surfaces one, so the voter judges the art itself
  // rather than the scanned card. See QuestionFeed.tsx's subjectImageSrc.
  test("renders the Scryfall art crop as the subject image when the item carries one", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtistWithIllustration,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("question-feed-artist-art")).toHaveAttribute(
      "src",
      "https://cards.scryfall.io/art_crop/front/a/b/ab000000-0000-0000-0000-000000000000.jpg"
    );
  });

  // Same re-frame, opposite branch: no harvested art crop (no canonical printing, or its
  // metadata carries no art_crop_url) falls back to the plain card image rather than the
  // Scryfall URL.
  test("falls back to the plain card image when the artist item carries no art crop", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtist,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    // cardDocument8 has no mediumThumbnailUrl, so the fallback heroImageSrc is "" - the
    // point under test is that it is NOT the Scryfall art-crop URL, matching
    // questionFeedArtist's scryfallIllustrationUrl: null.
    await expect(page.getByTestId("question-feed-artist-art")).toHaveAttribute(
      "src",
      ""
    );
  });

  test("a confidently-known artist collapses behind a 'wrong?' link", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtistConfidentlyKnown,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    const picker = page.getByTestId("artist-vote-picker");
    await expect(picker.getByText("Alpha Artist")).toBeVisible();
    const wrongLink = page.getByTestId("artist-vote-wrong-link");
    await expect(wrongLink).toBeVisible();

    await wrongLink.click();
    await expect(picker.getByTestId("artist-vote-consensus")).toBeVisible();
    await expect(
      picker.getByPlaceholder("Search for an artist...")
    ).toBeVisible();
  });

  // Artist Support Links v1 - the post-answer moment, a zero-crawl link-out to MTG Artist
  // Connection built deterministically from the artist name the user just voted for. See
  // docs/features/artist-support-links.md.
  test("voting for a named artist shows the Artist Support Link, built from that artist's name", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtist,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      submitArtistVoteResolvesToCanonicalArtist1,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByTestId("question-feed-artist-support")).toHaveCount(
      0
    );

    await page
      .getByTestId("artist-vote-picker")
      .getByText(canonicalArtist1.name)
      .click();
    await expect(page.getByText("Vote submitted")).toBeVisible();

    const banner = page.getByTestId("question-feed-artist-support");
    await expect(banner).toBeVisible();
    const link = banner.getByTestId("artist-support-link");
    await expect(link).toContainText(canonicalArtist1.name);
    await expect(link).toHaveAttribute(
      "href",
      `https://www.mtgartistconnection.com/artist/${encodeURIComponent(
        canonicalArtist1.name
      )}`
    );
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("voting 'Unknown artist' never shows the Artist Support Link (nothing to link to)", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedArtist,
      artistCandidatesTwoResults,
      artistConsensusUnresolved,
      submitArtistVoteResolvesToCanonicalArtist1,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByRole("button", { name: "Unknown artist" }).click();
    await expect(page.getByText("Vote submitted")).toBeVisible();

    await expect(page.getByTestId("question-feed-artist-support")).toHaveCount(
      0
    );
  });
});

test.describe("question feed - tag question type", () => {
  test("renders QueueTagQuestion for a tag-type item", async ({
    page,
    network,
  }) => {
    network.use(questionFeedTag, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(page.getByAltText(cardDocument9.name)).toBeVisible();
    await expect(page.getByTestId("queue-tag-question")).toBeVisible();
    await expect(page.getByText("Does Borderless apply?")).toBeVisible();
  });
});
