import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType } from "@/common/schema_types";
import {
  cardDocument13,
  cardDocument15,
  cardDocument19,
  localBackendURL,
} from "@/common/test-constants";
import {
  cardDocumentsSelectVersionMixedResults,
  castImplicitVoteSuccess,
  defaultHandlers,
  retractImplicitVoteSuccess,
  searchResultsSelectVersionMixedResults,
  sourceDocumentsOneResult,
  submitTagVoteResolvesToApply,
  tagConsensusTwoUnresolvedTags,
} from "@/mocks/handlers";

import { test } from "../playwright.setup";
import { importText, loadPageWithDefaultBackend } from "./test-utils";

function buildRoute(route: string): string {
  return `${localBackendURL}/${route}`;
}

const selectVersionHandlers = [
  cardDocumentsSelectVersionMixedResults,
  sourceDocumentsOneResult,
  searchResultsSelectVersionMixedResults,
  // The Attributes rail section fetches tag consensus the moment a slot is selected regardless
  // of whether it's ever opened - see DisplayPage.spec.ts's own identical comment.
  tagConsensusTwoUnresolvedTags,
  submitTagVoteResolvesToApply,
  castImplicitVoteSuccess,
  retractImplicitVoteSuccess,
  ...defaultHandlers,
];

// Issue #167 - the unified Select Version section
// (docs/proposals/proposal-h-unified-display-page.md §4.4′), mounted as the display page rail's
// always-open "Select Version" surface (editor-completion package, E2/E3/L4 - promoted, renamed
// from "Choose Image", no longer a collapsible accordion). cardDocumentsSelectVersionMixedResults/
// searchResultsSelectVersionMixedResults (mocks/handlers.ts) cover all three of the spec's
// groups in one result set - see those fixtures' own comments for the exact shape.
test.describe("SelectVersionSection (issue #167)", () => {
  test.describe.configure({ timeout: 60_000 });

  const openSelectVersionSection = async (
    page: import("@playwright/test").Page
  ) => {
    await loadPageWithDefaultBackend(page);
    await importText(page, "my search query");
    await page.getByRole("link", { name: "Editor" }).click();
    await page.getByTestId("page-preview-slot").first().click();
    // The rail always renders compressed tiles now (editor-completion package, E4/L9 - the
    // toggle is gone entirely, hard-pinned true) - no "Compressed" click needed any more.
  };

  test("groups candidates into canonical (by printing), non-canonical (by reason tag), and unknown sections", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    await expect(page.getByTestId("select-version-section")).toBeVisible();
    await expect(
      page.getByTestId("select-version-group-canonical")
    ).toBeVisible();
    await expect(
      page.getByTestId("select-version-group-non-canonical")
    ).toBeVisible();
    await expect(
      page.getByTestId("select-version-group-unknown")
    ).toBeVisible();

    // Two distinct printings in this result set (sv-001 suggested, sv-002 resolved) -> two
    // canonical printing groups.
    await expect(
      page.locator('[data-testid^="select-version-printing-group-"]')
    ).toHaveCount(2);
    // One reason-tag group (custom-art).
    await expect(
      page.getByTestId("select-version-reason-group-custom-art")
    ).toBeVisible();
  });

  test("shows resolved printings before suggested printings, each with a representative and a '+N more of this printing' expander", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    const printingGroups = page.locator(
      '[data-testid^="select-version-printing-group-"]'
    );
    // sv-002 (resolved, single copy) sorts before sv-001 (suggested, two copies) - resolved
    // printings sort ahead of suggested ones per the spec.
    await expect(printingGroups.nth(0)).toHaveAttribute(
      "data-status",
      "resolved"
    );
    await expect(printingGroups.nth(1)).toHaveAttribute(
      "data-status",
      "suggested"
    );

    // The suggested printing (sv-001) has two copies (cardDocument13/14) - one representative
    // (the higher-DPI copy, cardDocument14) plus a "+1 more" expander for the other.
    const suggestedGroup = printingGroups.nth(1);
    await expect(
      suggestedGroup.getByText("+1 more of this printing")
    ).toBeVisible();
    await suggestedGroup.getByText("+1 more of this printing").click();
    await expect(suggestedGroup.getByText("Show fewer")).toBeVisible();
  });

  test("a suggested-printing representative carries the Confirm affordance; a resolved printing does not", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    const printingGroups = page.locator(
      '[data-testid^="select-version-printing-group-"]'
    );
    const resolvedGroup = printingGroups.nth(0);
    const suggestedGroup = printingGroups.nth(1);

    // Exact testid, not a prefix match - DeckbuilderConfirmAffordance's own internal badge/yes/no
    // controls all also start with "deckbuilder-confirm-" (see its own component), so a prefix
    // regex here would over-match those too.
    await expect(
      suggestedGroup.getByTestId(
        "deckbuilder-confirm-1hH2iI3jJ4kK5lL6mM7nN8oO9pP0qQ"
      )
    ).toHaveCount(1);
    await expect(
      resolvedGroup.getByTestId(/^deckbuilder-confirm-/)
    ).toHaveCount(0);
  });

  // Funnel round (funnel-spec.md F2/F3, XF1/XF2) - the flat FilterChipBar is retired from this
  // (stacked/rail) surface, replaced by the per-axis segmented `funnel-chip-*` controls; "More
  // like this" still seeds `activeAttributeTags` from a card's own resolved tags, just rendered
  // through the new axis chips instead of the old flat bar.
  test("the per-axis funnel chips filter the whole section, and 'More like this' seeds them from a card's own resolved tags", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    // cardDocument18 (in the unknown group) has a resolved "Full Art" tag - its "More like this"
    // button should activate the Full Art funnel chip (Treatment axis). It's the only candidate
    // with that tag in this fixture set, so filtering narrows to a single survivor - D21's "hero"
    // tier - which collapses the axis rows to the head's active-pill summary (F1); the pill is
    // therefore the correct place to assert the chip actually activated, not the (now-hidden)
    // segmented chip button itself.
    const unknownGroup = page.getByTestId("select-version-group-unknown");
    await unknownGroup
      .getByTestId(/^select-version-more-like-this-/)
      .first()
      .click();

    await expect(page.getByTestId("funnel-active-pill-Full Art")).toBeVisible();
    await expect(page.getByTestId("funnel-count")).toContainText("1 version");
    // Filtering down to Full Art should still show cardDocument18 (it has the tag) and hide the
    // custom-art-only / unknown cards that don't.
    await expect(
      page.getByTestId("select-version-group-non-canonical")
    ).toHaveCount(0);
  });

  // D20/F4 - the two-tap ConfirmChip is retired on this surface: picking a candidate while a
  // suggested-only tag is active automatically casts support, resets the chips, and shows a
  // fading ack - no ✓/✕ prompt.
  test("selecting a card while a filter tag is active but only 'suggested' (not resolved) on that specific card casts implicit support, resets the filter, and shows a fading ack", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    // Manually activate the "Old Border" funnel chip - cardDocument18 carries a *suggested* (not
    // resolved) Old Border vote, so it should still be filtered in (resolved-OR-suggested when
    // the vote layer is on) and its selection should cast an implicit support vote.
    await page.getByTestId("funnel-chip-Old Border").click();
    await expect(page.getByTestId("funnel-awareness-line")).toBeVisible();

    const tile = page.getByTestId(
      "select-version-tile-1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU"
    );
    await expect(tile).toBeVisible();
    await tile.locator(".mpccard").click();

    await expect(page.getByTestId("funnel-support-ack")).toBeVisible();
    await expect(page.getByTestId("funnel-support-ack")).toContainText(
      "Old Border"
    );
    // The pick resets the active chips - the awareness line (gated on >=1 active chip) disappears
    // along with it.
    await expect(page.getByTestId("funnel-awareness-line")).toHaveCount(0);
    // No two-tap confirm chip anywhere on this surface any more (D20).
    await expect(
      page.getByTestId(
        "select-version-confirm-chip-1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU-Old Border"
      )
    ).toHaveCount(0);
  });

  // D20/F4d - "retraction = deselection": reselecting a DIFFERENT candidate for the same slot
  // withdraws the previous pick's implicit support. This bookkeeping lives in DisplayPage.tsx's
  // own handleImplicitSupport (it has to survive the Rail's per-slot remount - see that
  // function's own comment), so it's exercised here through the real page, not a component-level
  // mock.
  test("reselecting a different candidate for the same slot retracts the previous pick's implicit support", async ({
    page,
    network,
  }) => {
    const retractedCalls: Array<{ identifier: string; tagName: string }> = [];
    network.use(
      // Listed FIRST - MSW/the network fixture matches handlers in array order, and
      // selectVersionHandlers already carries its own retractImplicitVoteSuccess (needed by the
      // OTHER tests in this file); this one has to win the match to actually observe the calls.
      http.post(buildRoute("2/retractImplicitVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          identifier: string;
          tagName: string;
        };
        retractedCalls.push({
          identifier: body.identifier,
          tagName: body.tagName,
        });
        return HttpResponse.json(
          {
            tagName: body.tagName,
            resolvedPolarity: null,
            netPolarity: 0,
            tally: [],
          },
          { status: 200 }
        );
      }),
      ...selectVersionHandlers
    );
    await openSelectVersionSection(page);

    // First pick: cardDocument18 (1lL2...), under the active "Old Border" chip - casts support.
    await page.getByTestId("funnel-chip-Old Border").click();
    await page
      .getByTestId("select-version-tile-1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU")
      .locator(".mpccard")
      .click();
    await expect(page.getByTestId("funnel-support-ack")).toBeVisible();

    // Second pick: cardDocument15 (the sole, always-visible representative of the resolved
    // printing group - no "+N more" expansion needed), with NO filters active this time - must
    // still retract the FIRST pick's support (cardDocument18 / Old Border), even though this pick
    // itself casts nothing new.
    await page
      .getByTestId("select-version-tile-1iI2jJ3kK4lL5mM6nN7oO8pP9qQ0rR")
      .locator(".mpccard")
      .click();

    await expect
      .poll(() => retractedCalls)
      .toEqual([
        { identifier: "1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU", tagName: "Old Border" },
      ]);
  });

  // Fix round (owner-ratified condition 6, Tron's PR #329 review) - the exact non-compliance
  // caught in review, pinned as a regression test: cardDocument19 carries
  // `tagVoteStatuses: {"Old Border": "suggested"}` (the source-agnostic collapse - could be an
  // implicit-only lean, a sub-threshold machine vote, or a REJECT-leaning split) but an EMPTY
  // `suggestedFilterTagNames` (the compliant, implicit-excluded, floor-gated source says this tag
  // does NOT qualify). The funnel must render NO suggested chip for "Old Border" on this
  // candidate set, and picking cardDocument19 while a DIFFERENT active chip is on must cast NO
  // implicit vote for "Old Border" specifically (nothing to cast - it was never in the support
  // set in the first place).
  test("a tag that tagVoteStatuses calls 'suggested' but suggestedFilterTagNames excludes renders no suggested chip and casts no implicit vote for it (condition 6)", async ({
    page,
    network,
  }) => {
    const castCalls: Array<{ identifier: string; tagNames: string[] }> = [];
    network.use(
      http.post(buildRoute("2/cards/"), () =>
        HttpResponse.json(
          {
            results: {
              [cardDocument19.identifier]: cardDocument19,
              [cardDocument13.identifier]: cardDocument13,
              [cardDocument15.identifier]: cardDocument15,
            },
          },
          { status: 200 }
        )
      ),
      http.post(buildRoute("3/editorSearch/"), () =>
        HttpResponse.json(
          {
            results: {
              [computeSearchQueryHashKey({
                query: "my search query",
                cardType: CardType.Card,
              })]: [
                cardDocument19.identifier,
                cardDocument13.identifier,
                cardDocument15.identifier,
              ],
            },
          },
          { status: 200 }
        )
      ),
      http.post(buildRoute("2/castImplicitVote/"), async ({ request }) => {
        const body = (await request.json()) as {
          identifier: string;
          tagNames: string[];
        };
        castCalls.push({
          identifier: body.identifier,
          tagNames: body.tagNames,
        });
        return HttpResponse.json({ tags: [] }, { status: 200 });
      }),
      sourceDocumentsOneResult,
      tagConsensusTwoUnresolvedTags,
      submitTagVoteResolvesToApply,
      retractImplicitVoteSuccess,
      ...defaultHandlers
    );
    await openSelectVersionSection(page);

    // No suggested chip for "Old Border" at all - the only candidate that carries it
    // (cardDocument19) does so via tagVoteStatuses only, which the funnel no longer consults for
    // the suggested read.
    await expect(page.getByTestId("funnel-chip-Old Border")).toHaveCount(0);

    // Activate a DIFFERENT axis (Treatment has no membership here since none of these three carry
    // a Treatment tag at all) isn't available, so instead: pick cardDocument19 directly with NO
    // filters active - an ordinary pick, no vote, no ack, no awareness line.
    await page
      .getByTestId(`select-version-tile-${cardDocument19.identifier}`)
      .locator(".mpccard")
      .click();
    await expect(page.getByTestId("funnel-support-ack")).toHaveCount(0);
    await expect(page.getByTestId("funnel-awareness-line")).toHaveCount(0);

    // Belt-and-suspenders: even if some OTHER mechanism tried to cast for this card, "Old
    // Border" must never appear in any cast call's tagNames for cardDocument19.
    const castsForCard19 = castCalls.filter(
      (call) => call.identifier === cardDocument19.identifier
    );
    expect(
      castsForCard19.some((call) => call.tagNames.includes("Old Border"))
    ).toBe(false);
  });
});
