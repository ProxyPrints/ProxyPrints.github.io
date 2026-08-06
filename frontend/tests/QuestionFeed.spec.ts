import { expect } from "@playwright/test";

import {
  canonicalArtist1,
  cardDocument1,
  cardDocument8,
  cardDocument9,
  printingCandidate1,
  printingCandidate2,
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
  questionFeedTag,
  submitArtistVoteResolvesToCanonicalArtist1,
  submitIllustrationVoteCastsPrintingAndArtist,
  submitPrintingTagNoMatch,
  submitPrintingTagResolvesToPrintingCandidate1,
  submitPrintingTagResolvesToPrintingCandidate2,
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
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate2,
      submitTagVoteResolvesToApply,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page
      .locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
      .click();

    await expect(page.getByTestId("question-feed-level3")).toBeVisible();
    await expect(
      page.getByTestId("question-feed-level3-chip-Black Border")
    ).toBeVisible();
    // Frame ("2003" -> Modern Border) already matched, so it's not asked about again here.
    await expect(
      page.getByTestId("question-feed-level3-chip-Full Art")
    ).toHaveCount(0);
  });

  test("picking one option in Level 3 and confirming submits just that vote", async ({
    page,
    network,
  }) => {
    const submittedTagNames: string[] = [];
    network.use(
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate2,
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
      .locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
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
      questionFeedIdentifyPrinting,
      submitPrintingTagResolvesToPrintingCandidate2,
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
      .locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
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
// candidateA/B share an illustration (a real cluster), candidateC has its own distinct
// illustrationId (no sibling), candidateD carries no illustrationId at all - the nullable,
// frequently-absent shape (CanonicalPrintingMetadata.illustration_id, see
// local_illustration.py:137's isnull filter).
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

  test("only the illustration group's representative candidate renders inside its one illustration-group container; unique/null-illustration candidates don't", async ({
    page,
    network,
  }) => {
    network.use(
      questionFeedIdentifyPrintingGroupedByIllustration,
      ...defaultHandlers
    );
    await loadPageWithDefaultBackend(page, "whatsthat");

    const group = page.getByTestId("question-feed-illustration-group");
    await expect(group).toHaveCount(1);
    await expect(group).toHaveAttribute(
      "data-illustration-id",
      "illustration-shared"
    );
    await expect(
      group.locator(
        `[data-card-identifier="${illustrationGroupCandidateA.identifier}"]`
      )
    ).toHaveCount(1);
    // candidateB shares the illustration but has no art crop, so A wins the representative
    // pick and the group renders only A's tile - not B's.
    await expect(
      group.locator(
        `[data-card-identifier="${illustrationGroupCandidateB.identifier}"]`
      )
    ).toHaveCount(0);

    // candidateC (distinct illustrationId, no sibling) and candidateD (null illustrationId)
    // both render OUTSIDE the clustered group - neither forms (or joins) a cluster of one.
    await expect(
      group.locator(
        `[data-card-identifier="${illustrationGroupCandidateC.identifier}"]`
      )
    ).toHaveCount(0);
    await expect(
      group.locator(
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

    const group = page.getByTestId("question-feed-illustration-group");
    await expect(
      group.locator(
        `[data-card-identifier="${illustrationGroupCandidateA.identifier}"] img`
      )
    ).toHaveAttribute("src", illustrationGroupCandidateA.artCropUrl as string);

    const ungroupedGrid = page.getByTestId(
      "question-feed-candidate-grid-ungrouped"
    );
    await expect(
      ungroupedGrid.locator(
        `[data-card-identifier="${illustrationGroupCandidateC.identifier}"] img`
      )
    ).toHaveAttribute("src", illustrationGroupCandidateC.mediumThumbnailUrl);
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

    const credit = page.getByTestId("question-feed-illustration-credit");
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

  test("selecting an ungrouped candidate (distinct or null illustrationId) still submits to /2/submitPrintingTag/, unchanged", async ({
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

    // candidateC carries its own distinct illustrationId (no sibling, so it never clusters) -
    // exercises the "distinct" half of this title alongside candidateD's null-illustrationId
    // case already covered by the mixed-set rendering test above.
    await page
      .locator(
        `[data-card-identifier="${illustrationGroupCandidateC.identifier}"]`
      )
      .click();

    await expect
      .poll(() => submittedPrinting?.printingIdentifier)
      .toBe(illustrationGroupCandidateC.identifier);
    expect(submittedPrinting?.isNoMatch).toBe(false);
    expect(illustrationVoteSubmitted).toBe(false);
  });
});

test.describe("question feed - confirm_suggestion question type", () => {
  test("lands on Level 1 - a single suggested printing, no grid - and shows the 'Is it this one?' prompt", async ({
    page,
    network,
  }) => {
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await loadPageWithDefaultBackend(page, "whatsthat");

    await expect(
      page.getByTestId("question-feed-suggestion-prompt")
    ).toContainText("Is it this one?");
    await expect(page.getByTestId("question-feed-level1-yes")).toBeVisible();
    // no candidate grid at Level 1 - only reachable via NOT SURE/NO
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(0);

    // Regression check (#49 dropped this): Level 1 still needs its own reference render of the
    // suggested printing to compare against - "Is it this one?" is unanswerable from text alone.
    // `getByRole("img")` (not a plain `img` locator) - round 3's shared `<MysteryCard />` (own
    // comment, cardPanel.tsx) renders a SECOND `<img>` in this same container (its own "?" glyph,
    // `alt=""`), which a bare `locator("img")` now matches too, causing a Playwright strict-mode
    // violation. `alt=""` strips an <img> from the accessibility tree entirely, so `getByRole`
    // (unlike a tag-selector) unambiguously resolves to just the real reference thumbnail below.
    const referenceImage = page
      .getByTestId("question-feed-level1-reference-image")
      .getByRole("img");
    await expect(referenceImage).toBeVisible();
    await expect(referenceImage).toHaveAttribute(
      "src",
      printingCandidate1.mediumThumbnailUrl
    );
  });

  test("YES confirms the suggested printing directly, without visiting the grid", async ({
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

    await page.getByTestId("question-feed-level1-yes").click();

    await expect
      .poll(() => submittedPrintingIdentifier)
      .toBe(printingCandidate1.identifier);
  });

  test("NOT SURE drops to Level 2's candidate grid without casting a printing vote, but does POST an abstention", async ({
    page,
    network,
  }) => {
    let printingTagSubmitted = false;
    let abstentionBody: { identifier?: string; questionType?: string } = {};
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
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-level1-not-sure").click();

    const suggestedCandidate = page.locator(
      `[data-card-identifier="${printingCandidate1.identifier}"]`
    );
    await expect(suggestedCandidate).toBeVisible();
    await expect(suggestedCandidate).toHaveClass(/highlighted/);
    expect(printingTagSubmitted).toBe(false);

    await expect
      .poll(() => abstentionBody.identifier)
      .toBe(cardDocument1.identifier);
    expect(abstentionBody.questionType).toBe("confirm_suggestion");
  });

  test("NO drops to Level 2's candidate grid, excluding the rejected suggestion, without casting a vote", async ({
    page,
    network,
  }) => {
    // Double-asking fix: a candidate the user just rejected at Level 1 is never
    // re-presented as a selectable tile at Level 2 within the same item - see
    // rejectSuggestion/rejectedCandidateIds in QuestionFeed.tsx. This mock has two
    // candidates, so the remaining one (printingCandidate2) should still show.
    let printingTagSubmitted = false;
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    page.on("request", (request) => {
      if (request.url().includes("/2/submitPrintingTag/")) {
        printingTagSubmitted = true;
      }
    });
    await loadPageWithDefaultBackend(page, "whatsthat");

    await page.getByTestId("question-feed-level1-no").click();

    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(0);
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate2.identifier}"]`)
    ).toBeVisible();
    expect(printingTagSubmitted).toBe(false);
  });

  test("NO on a singleton suggestion (no other candidates) skips the grid entirely and immediately casts the terminal no-match vote", async ({
    page,
    network,
  }) => {
    // Owner-reported dedup bug (docs/features/printing-tags.md's questionFeed section): Level 1
    // "Is it M21 203?" -> NO, where M21 203 was the card's ONLY candidate. Previously (this test
    // used to assert `printingTagSubmitted === false` here - that assertion WAS the bug, not a
    // correct behavior spec) "No" cast no vote at all and merely revealed a further "None of
    // these" tap the user still had to make; if that tap never happened, no CardPrintingTag row
    // ever existed for question_feed.py's tier-1 exclusion to match against, so the exact same
    // question resurfaced on the next feed fetch. Since there is nothing else this card's "No"
    // could mean (no other candidate exists), it must now be treated as the terminal answer:
    // the same isNoMatch vote "None of these" itself casts is submitted the moment "No" is
    // tapped, with no further tap required.
    let submittedPrinting: {
      printingIdentifier?: string;
      isNoMatch?: boolean;
    } = {};
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

    await page.getByTestId("question-feed-level1-no").click();

    // the rejected candidate is never a selectable tile again
    await expect(
      page.locator(`[data-card-identifier="${printingCandidate1.identifier}"]`)
    ).toHaveCount(0);
    // contextual copy replaces the generic "Which of these is it?" grid prompt
    await expect(
      page.getByTestId("question-feed-suggestion-prompt")
    ).toContainText("Is it any official printing at all?");
    // rejected candidate stays visible as grayed, non-interactive context
    const rejectedContext = page.getByTestId("question-feed-rejected-context");
    await expect(rejectedContext).toBeVisible();
    await expect(rejectedContext).toContainText("not");

    // the terminal no-match vote is cast automatically - no further "None of these" tap needed
    await expect.poll(() => submittedPrinting.isNoMatch).toBe(true);
    expect(submittedPrinting.printingIdentifier).toBeUndefined();
    // ...and hands off to the same "why not" follow-up "None of these" itself opens
    await expect(page.getByTestId("no-match-reason-strip")).toBeVisible();
  });

  test("at a 390px mobile viewport, no answer control overlaps the card art", async ({
    page,
    network,
  }) => {
    // Regression guard for a real-device-only bug (not reproducible in this sandbox's
    // Chromium): Level 1 previously reused Level 2's sticky, negative-z-index CardPanel for
    // its own short single-screen layout, which composited incorrectly on a real phone -
    // answer controls painted overlapping the card art instead of cleanly below it. The fix
    // (StaticCardPanel - see cardPanel.tsx) puts everything back in normal document flow;
    // this asserts that property directly via bounding-box math rather than relying on visual
    // diffing this sandbox can't validate against real hardware anyway.
    network.use(questionFeedConfirmSuggestion, ...defaultHandlers);
    await page.setViewportSize({ width: 390, height: 844 });
    await loadPageWithDefaultBackend(page, "whatsthat");

    // The card's full box (art + starburst + name caption), not just the <img> - the
    // real-device bug this guards against overlapped the caption too, not only the artwork.
    const cardPanel = page.getByTestId("question-feed-level1-card-panel");
    await expect(page.getByAltText(cardDocument1.name)).toBeVisible();
    await expect(page.getByTestId("question-feed-level1-yes")).toBeVisible();

    const cardBox = await cardPanel.boundingBox();
    expect(cardBox).not.toBeNull();

    const controls = [
      page.getByTestId("question-feed-tier-badge"),
      page.getByTestId("question-feed-suggestion-prompt"),
      page.getByTestId("question-feed-level1-yes"),
      page.getByTestId("question-feed-level1-not-sure"),
      page.getByTestId("question-feed-level1-no"),
      page.getByTestId("question-feed-level1-skip"),
    ];
    for (const control of controls) {
      const controlBox = await control.boundingBox();
      expect(controlBox).not.toBeNull();
      expect(boxesIntersect(cardBox!, controlBox!)).toBe(false);
    }
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

  // Artist Support Links v1 - the post-answer moment ("Art by <Name> - support them"), a
  // zero-crawl link-out to MTG Artist Connection built deterministically from the artist name
  // the user just voted for. See docs/features/artist-support-links.md.
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
    await expect(banner).toContainText(
      `Art by ${canonicalArtist1.name} - support them`
    );
    const link = banner.getByTestId("artist-support-link");
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
