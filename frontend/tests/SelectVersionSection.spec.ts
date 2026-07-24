import { expect } from "@playwright/test";
import { http, HttpResponse } from "msw";

import { computeSearchQueryHashKey } from "@/common/processing";
import { CardType } from "@/common/schema_types";
import {
  cardDocument13,
  cardDocument14,
  cardDocument15,
  cardDocument16,
  cardDocument18,
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
import { openSelectVersionSection } from "./test-utils";

// Parity wave 2 (2026-07-23, issue #272) - un-skipped. This file was never actually classic-
// editor-only: it already exercised the unified page's own rail (via openSelectVersionSection,
// test-utils.ts) from the moment it landed with issue #167 (#198), before the route swap even
// happened. It picked up the swap's blanket per-file skip marker anyway and was deliberately left
// for this wave rather than wave 1 - see test-utils.ts's own openSelectVersionSection comment.
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

  // Addendum item 2 (SPEC-display-left-rail.md §7, owner verbatim: "the 5 cards should be in 1
  // section") - the old per-group wrapper divs (`select-version-group-*`,
  // `select-version-printing-group-*`, `select-version-reason-group-*`) are GONE entirely. Group
  // membership is now a tile-corner annotation over ONE continuous, role="list" grid; ordering
  // (canonical -> non-canonical -> unknown, resolved-before-suggested within canonical) is
  // preserved as a pure sort key, not a sectioning key.
  test("packs every candidate into one continuous grid with no between-group separator, annotating group membership via tile corner tags instead of separate sections", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    await expect(page.getByTestId("select-version-section")).toBeVisible();
    const grid = page.getByTestId("select-version-continuous-grid");
    await expect(grid).toBeVisible();
    await expect(grid).toHaveAttribute("role", "list");
    // No group-wrapper testids of any kind survive the continuous-grid rewrite.
    await expect(
      page.locator(
        '[data-testid^="select-version-group-"], [data-testid^="select-version-printing-group-"], [data-testid^="select-version-reason-group-"]'
      )
    ).toHaveCount(0);

    // Resolved printing (sv-002, cardDocument15) gets a ✓ corner tag.
    await expect(
      page.getByTestId(
        `select-version-tile-corner-${cardDocument15.identifier}`
      )
    ).toHaveText("✓");
    // Non-canonical (custom-art, cardDocument16) gets an Alt corner tag.
    await expect(
      page.getByTestId(
        `select-version-tile-corner-${cardDocument16.identifier}`
      )
    ).toHaveText("Alt");
    // An unknown-bucket card (cardDocument18) gets a ? corner tag.
    await expect(
      page.getByTestId(
        `select-version-tile-corner-${cardDocument18.identifier}`
      )
    ).toHaveText("?");
    // The suggested printing's representative (cardDocument14, the higher-DPI copy) carries the
    // confirm ribbon INSTEAD of a corner tag - not yet a confirmed printing.
    await expect(
      page.getByTestId(
        `select-version-confirm-ribbon-${cardDocument14.identifier}`
      )
    ).toBeVisible();
    await expect(
      page.getByTestId(
        `select-version-tile-corner-${cardDocument14.identifier}`
      )
    ).toHaveCount(0);
  });

  test("shows resolved printings before suggested printings, and expands a printing's extra copies in place via an inline ghost tile (not a full-width text row)", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    const grid = page.getByTestId("select-version-continuous-grid");
    // sv-002 (resolved, cardDocument15) and sv-001's representative (suggested, cardDocument14)
    // are both visible from the start - DOM order (not a visual separator) is what encodes
    // resolved-before-suggested now.
    await expect(
      grid.getByTestId(`select-version-tile-${cardDocument15.identifier}`)
    ).toBeVisible();
    await expect(
      grid.getByTestId(`select-version-tile-${cardDocument14.identifier}`)
    ).toBeVisible();

    // sv-001 (cardDocument13/14) has one extra copy (cardDocument13, the lower-DPI one) - an
    // inline ghost tile ("+1"), same footprint as a real tile, sits right after the
    // representative and expands it IN PLACE rather than via a full-width text link.
    const ghost = page.getByTestId("select-version-ghost-sv-001-expand");
    await expect(ghost).toBeVisible();
    await expect(ghost).toHaveText("+1");
    await ghost.click();

    await expect(
      grid.getByTestId(`select-version-tile-${cardDocument13.identifier}`)
    ).toBeVisible();
    // The ghost tile itself swaps to a "Show fewer"-equivalent collapse control, still tile-
    // shaped (a real button, not a text row).
    await expect(
      page.getByTestId("select-version-ghost-sv-001-collapse")
    ).toBeVisible();
  });

  test("a suggested-printing representative carries the confirm ribbon (the real, unmodified DeckbuilderConfirmAffordance, scaled into a tile-corner overlay); a resolved printing does not", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    const suggestedRibbon = page.getByTestId(
      `select-version-confirm-ribbon-${cardDocument14.identifier}`
    );
    await expect(suggestedRibbon).toBeVisible();
    // The ribbon wraps the exact same DeckbuilderConfirmAffordance component (same internal
    // testid convention) other mounts of it use - only its position/scale is new.
    await expect(
      suggestedRibbon.getByTestId(
        `deckbuilder-confirm-${cardDocument14.identifier}`
      )
    ).toHaveCount(1);
    await expect(
      page.getByTestId(
        `select-version-confirm-ribbon-${cardDocument15.identifier}`
      )
    ).toHaveCount(0);
  });

  // Funnel round (funnel-spec.md F2/F3, XF1/XF2) - the flat FilterChipBar is retired from this
  // (stacked/rail) surface, replaced by the per-axis segmented `funnel-chip-*` controls (Border/
  // Frame) and the tri-state `funnel-treatment-chip-*` controls (Treatment) sharing one unified
  // block (SPEC-display-left-rail.md §6). "More like this" (the old per-tile "seed the filter
  // from this card's own tags" affordance) was DROPPED entirely when the between-group rows were
  // removed (§7's own affordance table doesn't allocate it a tile-corner slot) - filtering now
  // goes directly through the unified block's own chips.
  test("the unified Frame+Treatment block's tri-state chips filter the whole grid", async ({
    page,
    network,
  }) => {
    network.use(...selectVersionHandlers);
    await openSelectVersionSection(page);

    // cardDocument18 (unknown bucket) has a resolved "Full Art" tag and is the ONLY candidate
    // with it in this fixture set - one click cycles the Treatment chip untouched -> include.
    await page.getByTestId("funnel-treatment-chip-Full Art").click();

    await expect(page.getByTestId("funnel-active-pill-Full Art")).toBeVisible();
    // Filtering down to Full Art narrows the survivor count to 1, which collapses the axis rows
    // to the head's active-pill summary (D21's "hero" tier) - the pill is the correct place to
    // assert the chip activated, not the (now-hidden) segmented chip button itself.
    await expect(page.getByTestId("funnel-count")).toContainText("1 version");
    await expect(
      page.getByTestId(`select-version-tile-${cardDocument18.identifier}`)
    ).toBeVisible();
  });

  // §6 - Treatment's own tri-state EXCLUDE half is covered at the component level
  // (SelectVersionResults.test.tsx's "§6 unified Frame+Treatment" describe block) rather than
  // here: with this fixture's own card set, including "Full Art" (the only carrier is
  // cardDocument18) immediately narrows to 1 survivor - D21's "hero" tier - which collapses the
  // axis/chip row entirely (nothing left worth narrowing further), so the SAME chip a real user
  // would need to tap a second time (to cycle include -> exclude) is no longer in the DOM by
  // then. The Jest suite builds a fixture that stays above the hero threshold through the whole
  // cycle instead.

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
