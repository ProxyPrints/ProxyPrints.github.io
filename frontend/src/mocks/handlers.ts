import { delay, http, HttpResponse } from "msw";

import { Card, Cardback, Token } from "@/common/constants";
import { computeSearchQueryHashKey } from "@/common/processing";
import {
  Campaign,
  CardType,
  PrintingCandidate,
  QuestionFeedCounts,
  Supporter,
  SupporterTier,
} from "@/common/schema_types";
import {
  canonicalArtist1,
  canonicalArtist2,
  cardDocument1,
  cardDocument2,
  cardDocument3,
  cardDocument4,
  cardDocument5,
  cardDocument6,
  cardDocument7,
  cardDocument8,
  cardDocument9,
  cardDocument10,
  cardDocument11,
  cardDocument12,
  cardDocument13,
  cardDocument14,
  cardDocument15,
  cardDocument16,
  cardDocument17,
  cardDocument18,
  localBackend,
  printingCandidate1,
  printingCandidate2,
  printingCandidate3,
  sourceDocument1,
  sourceDocument2,
  sourceDocument3,
} from "@/common/test-constants";
import {
  participationAtRevealThreshold,
  participationCurrentRatio,
  participationPostSweep,
} from "@/features/stats/testFixtures";

const createError = (name: string) => ({
  name,
  message: "A message that describes the error",
});

/**
 * Not including the correct leading and trailing slashes can break things.
 * This little helper function ensures the given relative API route is associated
 * with the local backend URL correctly.
 * TODO: not sure how true the above statement is as of MSW 2.7
 */
function buildRoute(route: string) {
  const re = /^\/?(.*?)\/?$/g;
  return `${localBackend.url}/${(re.exec(route) ?? ["", ""])[1]}`;
}

/**
 * Re-route ping.js favicon request to frontend for E2E tests.
 *
 * `@msw/playwright` runs this handler in the Playwright NODE process, not in the page, so it
 * cannot use an origin-relative URL and cannot assume a fixed port either: since the E2E dev
 * server takes a per-run port (`playwright.config.ts`'s `resolvePort`), the port has to be read
 * back out of the environment that resolved it. The literal 3000 stays only as the fallback for
 * a caller that never went through that config (jest), matching the previous behaviour exactly.
 */
function frontendOrigin(): string {
  return `http://localhost:${process.env.PLAYWRIGHT_PORT ?? 3000}`;
}

export const favicon = http.get(buildRoute("favicon.ico"), async () => {
  const image = await fetch(`${frontendOrigin()}/favicon.ico`).then((res) =>
    res.arrayBuffer()
  );
  return HttpResponse.arrayBuffer(image, {
    headers: { "content-type": "image/png" },
  });
});

//# region source

export const sourceDocumentsNoResults = http.get(buildRoute("2/sources/"), () =>
  HttpResponse.json({ results: {} }, { status: 200 })
);

export const sourceDocumentsTwoResults = http.get(
  buildRoute("2/sources/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [sourceDocument1.pk]: sourceDocument1,
          [sourceDocument2.pk]: sourceDocument2,
        },
      },
      { status: 200 }
    )
);

export const sourceDocumentsOneResult = http.get(buildRoute("2/sources/"), () =>
  HttpResponse.json(
    {
      results: {
        [sourceDocument1.pk]: sourceDocument1,
      },
    },
    { status: 200 }
  )
);

export const sourceDocumentsThreeResults = http.get(
  buildRoute("2/sources/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [sourceDocument1.pk]: sourceDocument1,
          [sourceDocument2.pk]: sourceDocument2,
          [sourceDocument3.pk]: sourceDocument3,
        },
      },
      { status: 200 }
    )
);

export const sourceDocumentsServerError = http.get(
  buildRoute("2/sources/"),
  () => HttpResponse.json(createError("2/sources"), { status: 500 })
);

//# endregion

//# region card

export const cardDocumentsNoResults = http.post(buildRoute("2/cards/"), () =>
  HttpResponse.json({ results: {} }, { status: 200 })
);

export const cardDocumentsOneResult = http.post(buildRoute("2/cards/"), () =>
  HttpResponse.json(
    {
      results: {
        [cardDocument1.identifier]: cardDocument1,
      },
    },
    { status: 200 }
  )
);

// Same as cardDocumentsOneResult, but with a canonicalArtist set - cardDocument1 itself has none
// (exercises the "Unknown" no-link path in CardDetailedViewModal's Artist Support Link row),
// so this variant exists specifically to exercise the has-a-known-artist path.
export const cardDocumentsOneResultWithCanonicalArtist = http.post(
  buildRoute("2/cards/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [cardDocument1.identifier]: {
            ...cardDocument1,
            canonicalArtist: canonicalArtist1,
          },
        },
      },
      { status: 200 }
    )
);

export const cardDocumentsThreeResults = http.post(buildRoute("2/cards/"), () =>
  HttpResponse.json(
    {
      results: {
        [cardDocument1.identifier]: cardDocument1,
        [cardDocument2.identifier]: cardDocument2,
        [cardDocument3.identifier]: cardDocument3,
      },
    },
    { status: 200 }
  )
);

export const cardDocumentsFourResults = http.post(buildRoute("2/cards/"), () =>
  HttpResponse.json(
    {
      results: {
        [cardDocument1.identifier]: cardDocument1,
        [cardDocument2.identifier]: cardDocument2,
        [cardDocument3.identifier]: cardDocument3,
        [cardDocument4.identifier]: cardDocument4,
      },
    },
    { status: 200 }
  )
);

export const cardDocumentsSixResults = http.post(buildRoute("2/cards/"), () =>
  HttpResponse.json(
    {
      results: {
        [cardDocument1.identifier]: cardDocument1,
        [cardDocument2.identifier]: cardDocument2,
        [cardDocument3.identifier]: cardDocument3,
        [cardDocument4.identifier]: cardDocument4,
        [cardDocument5.identifier]: cardDocument5,
        [cardDocument6.identifier]: cardDocument6,
      },
    },
    { status: 200 }
  )
);

// Two sources: card1+card2 from source1, card7 from source2
export const cardDocumentsTwoSources = http.post(buildRoute("2/cards/"), () =>
  HttpResponse.json(
    {
      results: {
        [cardDocument1.identifier]: cardDocument1,
        [cardDocument2.identifier]: cardDocument2,
        [cardDocument7.identifier]: cardDocument7,
      },
    },
    { status: 200 }
  )
);

// Cards with canonicalCard data for CanonicalCardFilter tests
export const cardDocumentsWithCanonicalCards = http.post(
  buildRoute("2/cards/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [cardDocument8.identifier]: cardDocument8,
          [cardDocument9.identifier]: cardDocument9,
          [cardDocument10.identifier]: cardDocument10,
          [cardDocument11.identifier]: cardDocument11,
        },
      },
      { status: 200 }
    )
);

export const cardDocumentsServerError = http.post(buildRoute("2/cards/"), () =>
  HttpResponse.json(createError("2/cards"), { status: 500 })
);

// Community-vote-resolved printing match, for decklist set/collector-number import tests
export const cardDocumentsWithResolvedPrintingMatch = http.post(
  buildRoute("2/cards/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [cardDocument12.identifier]: cardDocument12,
        },
      },
      { status: 200 }
    )
);

// Issue #167 (Select Version section) - a mixed result set covering all three of the spec's
// groups: two copies of one suggested printing (13/14, "+1 more" once grouped), one resolved
// printing (15), one non-canonical custom-art card (16), and two "unknown" cards (17 plain, 18
// carrying a resolved Full Art tag + a separate suggested Old Border vote for the filter-chip/
// confirm-chip tests).
export const cardDocumentsSelectVersionMixedResults = http.post(
  buildRoute("2/cards/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [cardDocument13.identifier]: cardDocument13,
          [cardDocument14.identifier]: cardDocument14,
          [cardDocument15.identifier]: cardDocument15,
          [cardDocument16.identifier]: cardDocument16,
          [cardDocument17.identifier]: cardDocument17,
          [cardDocument18.identifier]: cardDocument18,
        },
      },
      { status: 200 }
    )
);

//# endregion

//# region cardback

export const cardbacksNoResults = http.post(buildRoute("2/cardbacks"), () =>
  HttpResponse.json({ cardbacks: [] }, { status: 200 })
);

export const cardbacksOneResult = http.post(buildRoute("2/cardbacks"), () =>
  HttpResponse.json(
    {
      cardbacks: [cardDocument1.identifier],
    },
    { status: 200 }
  )
);

export const cardbacksOneOtherResult = http.post(
  buildRoute("2/cardbacks"),
  () =>
    HttpResponse.json(
      {
        cardbacks: [cardDocument5.identifier],
      },
      { status: 200 }
    )
);

export const cardbacksTwoResults = http.post(buildRoute("2/cardbacks"), () =>
  HttpResponse.json(
    {
      cardbacks: [cardDocument1.identifier, cardDocument2.identifier],
    },
    { status: 200 }
  )
);

export const cardbacksTwoOtherResults = http.post(
  buildRoute("2/cardbacks"),
  () =>
    HttpResponse.json(
      {
        cardbacks: [cardDocument2.identifier, cardDocument3.identifier],
      },
      { status: 200 }
    )
);

export const cardbacksServerError = http.post(buildRoute("2/cardbacks/"), () =>
  HttpResponse.json(createError("2/cardbacks"), { status: 500 })
);

// GridSelectorModal parity port (2026-07-24, issue #272 wave 3). GridSelectorModal.tsx's only
// surviving mount post-route-swap is the project-wide cardback picker behind CardbackRailControl's
// "Browse all cardbacks…" button (CommonCardback.tsx; R9 round replaces the old CardbackToolbarButton
// trigger) - it's fed by the `2/cardbacks` identifier list, not a search query, so
// the classic per-slot cluster's own `2/cards/` + `3/editorSearch/` fixture pairs (below) need a
// `2/cardbacks` counterpart naming the same identifiers to reuse unchanged for this wave's ported
// tests. The modal itself doesn't care what a given identifier's underlying CardDocument's own
// name/art actually depicts (see GridSelectorModal.tsx: a bare `imageIdentifiers` array + `onClick`
// callback) - reusing `cardDocumentsThreeResults`' cast as "cardbacks" here is cosmetic only,
// already an established pattern (see cardbacksTwoResults/cardbacksOneResult above, both cast
// plain search-result cardDocument1/2 as cardbacks the same way).
export const cardbacksThreeResults = http.post(buildRoute("2/cardbacks"), () =>
  HttpResponse.json(
    {
      cardbacks: [
        cardDocument1.identifier,
        cardDocument2.identifier,
        cardDocument3.identifier,
      ],
    },
    { status: 200 }
  )
);

// Matches cardDocumentsFourResults' identifier set - used by CardSlot.visual.spec.ts's grid-
// selector aria-snapshot pair, re-anchored onto the cardback picker this wave.
export const cardbacksFourResults = http.post(buildRoute("2/cardbacks"), () =>
  HttpResponse.json(
    {
      cardbacks: [
        cardDocument1.identifier,
        cardDocument2.identifier,
        cardDocument3.identifier,
        cardDocument4.identifier,
      ],
    },
    { status: 200 }
  )
);

// Matches cardDocumentsTwoSources' identifier set (card1+card2 from source1, card7 from source2)
// - used by GridSelectorModal.spec.ts's source-filter test.
export const cardbacksTwoSources = http.post(buildRoute("2/cardbacks"), () =>
  HttpResponse.json(
    {
      cardbacks: [
        cardDocument1.identifier,
        cardDocument2.identifier,
        cardDocument7.identifier,
      ],
    },
    { status: 200 }
  )
);

// Matches cardDocumentsWithCanonicalCards' identifier set - used by GridSelectorModal.spec.ts's
// CanonicalCardFilter/Printing-grouping tests.
export const cardbacksWithCanonicalCards = http.post(
  buildRoute("2/cardbacks"),
  () =>
    HttpResponse.json(
      {
        cardbacks: [
          cardDocument8.identifier,
          cardDocument9.identifier,
          cardDocument10.identifier,
          cardDocument11.identifier,
        ],
      },
      { status: 200 }
    )
);

//# endregion

//# region search results

export const searchResultsNoResults = http.post(
  buildRoute("3/editorSearch/"),
  () => HttpResponse.json({ results: {} }, { status: 200 })
);

export const searchResultsOneResult = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [cardDocument1.identifier],
        },
      },
      { status: 200 }
    )
);

// processQuery strips "/" as punctuation, so a split card's own compound name (e.g.
// "Fire // Ice") arrives here as "fire ice" once isKnownSingleFacedCompoundName has kept it
// from being split into a front/back pair - see processing.ts's own handling.
export const searchResultsForSplitCardName = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "fire ice",
            cardType: CardType.Card,
          })]: [cardDocument1.identifier],
        },
      },
      { status: 200 }
    )
);

export const searchResultsOneResultCorrectSearchq = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: cardDocument1.searchq,
            cardType: CardType.Card,
          })]: [cardDocument1.identifier],
        },
      },
      { status: 200 }
    )
);

export const searchResultsThreeResults = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [
            cardDocument1.identifier,
            cardDocument2.identifier,
            cardDocument3.identifier,
          ],
        },
      },
      { status: 200 }
    )
);

// Issue #267 (design doc ADDENDUM D12) - like searchResultsThreeResults, but ALSO resolves a
// direct-add-by-identifier line built the same way AddCardToProjectForm.tsx's own
// handleAddToProject constructs one (`${quantity} ${cardDocument.searchq}${SelectedImageSeparator}
// ${cardDocument.identifier}`) - here, for cardDocument2. Without this second hash key,
// listenerMiddleware.ts's "ensure selected images are valid" listener (fires on every
// fetchSearchResults.fulfilled) finds cardDocument2's query ("card 2") resolving to an empty
// result set - the plain searchResultsThreeResults handler is canned to ONE hash key regardless of
// the actual request body - and deselects the very image AddCardToProjectForm just set, which is
// exactly the trap AddCardToProjectForm.spec.ts's own existing precedent avoids by using a query
// whose mock (searchResultsOneResultCorrectSearchq) already matches the added card's own searchq.
export const searchResultsThreeResultsPlusCard2SelfQuery = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [
            cardDocument1.identifier,
            cardDocument2.identifier,
            cardDocument3.identifier,
          ],
          [computeSearchQueryHashKey({
            query: cardDocument2.searchq,
            cardType: CardType.Card,
          })]: [cardDocument2.identifier],
        },
      },
      { status: 200 }
    )
);

// Two sources: card1+card2 from source1, card7 from source2
export const searchResultsTwoSources = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [
            cardDocument1.identifier,
            cardDocument2.identifier,
            cardDocument7.identifier,
          ],
        },
      },
      { status: 200 }
    )
);

// Cards with canonicalCard data for CanonicalCardFilter tests
export const searchResultsWithCanonicalCards = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [
            cardDocument8.identifier,
            cardDocument9.identifier,
            cardDocument10.identifier,
            cardDocument11.identifier,
          ],
        },
      },
      { status: 200 }
    )
);

// Community-vote-resolved printing match, for decklist set/collector-number import tests -
// simulates the backend's re-rank already having placed the matched printing first (and, in
// this case, only) result for a query carrying expansionCode/collectorNumber.
export const searchResultsResolvedPrintingMatch = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "lightning bolt",
            cardType: CardType.Card,
            expansionCode: "2ED",
            collectorNumber: "162",
          })]: [cardDocument12.identifier],
        },
      },
      { status: 200 }
    )
);

// Same shape as searchResultsResolvedPrintingMatch, but the card ISN'T yet Resolved -
// cardDocument8 already carries a matching canonicalCard (xyz/001) with
// printingTagStatus: Unresolved, so this is the "imported with a canonical printing ID, not
// yet human-confirmed" case Level 0's deckbuilder-confirmation affordance gates on (see
// DeckbuilderConfirmAffordance.tsx). Two results (not one, unlike
// searchResultsResolvedPrintingMatch) so CardSlot's own grid-selector-modal gate
// (searchResultsForQuery.length > 1) actually opens for the NO path's test coverage.
export const searchResultsUnresolvedCanonicalImport = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "card 8",
            cardType: CardType.Card,
            expansionCode: "XYZ",
            collectorNumber: "001",
          })]: [cardDocument8.identifier, cardDocument9.identifier],
        },
      },
      { status: 200 }
    )
);

// Issue #167 (Select Version section) - pairs with cardDocumentsSelectVersionMixedResults.
export const searchResultsSelectVersionMixedResults = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [
            cardDocument13.identifier,
            cardDocument14.identifier,
            cardDocument15.identifier,
            cardDocument16.identifier,
            cardDocument17.identifier,
            cardDocument18.identifier,
          ],
        },
      },
      { status: 200 }
    )
);

export const searchResultsFourResults = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [
            cardDocument1.identifier,
            cardDocument2.identifier,
            cardDocument3.identifier,
            cardDocument4.identifier,
          ],
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Cardback,
          })]: [cardDocument5.identifier],
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Token,
          })]: [cardDocument6.identifier],
        },
      },
      { status: 200 }
    )
);

export const searchResultsSixResults = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "query 1",
            cardType: CardType.Card,
          })]: [cardDocument1.identifier],
          [computeSearchQueryHashKey({
            query: "query 2",
            cardType: CardType.Card,
          })]: [cardDocument2.identifier],
          [computeSearchQueryHashKey({
            query: "query 3",
            cardType: CardType.Card,
          })]: [cardDocument3.identifier],
          [computeSearchQueryHashKey({
            query: "query 4",
            cardType: CardType.Card,
          })]: [cardDocument4.identifier],
          [computeSearchQueryHashKey({
            query: "query 5",
            cardType: CardType.Cardback,
          })]: [cardDocument5.identifier],
          [computeSearchQueryHashKey({
            query: "query 6",
            cardType: CardType.Token,
          })]: [cardDocument6.identifier],
        },
      },
      { status: 200 }
    )
);

export const searchResultsForDFCMatchedCards1And4 = http.post(
  buildRoute("3/editorSearch/"),
  () =>
    HttpResponse.json(
      {
        results: {
          [computeSearchQueryHashKey({
            query: "my search query",
            cardType: CardType.Card,
          })]: [cardDocument1.identifier],
          [computeSearchQueryHashKey({
            query: "card 3",
            cardType: CardType.Card,
          })]: [cardDocument3.identifier],
          [computeSearchQueryHashKey({
            query: "card 4",
            cardType: CardType.Card,
          })]: [cardDocument4.identifier],
        },
      },
      { status: 200 }
    )
);

// A printing-specific search whose filter found nothing and was retried unfiltered - the backend
// reports this via degradedQueries (schema_types.ts), which the requested-printing badge's
// degraded-style variant is keyed off (Proposal H, Step 2 PR 2b). cardDocument1 carries no
// canonicalCard data, so this is deliberately independent of the printing-confirmation affordance
// fixtures above - the two instruments are tested in isolation from each other.
export const searchResultsDegradedPrinting = http.post(
  buildRoute("3/editorSearch/"),
  () => {
    const hashKey = computeSearchQueryHashKey({
      query: "my search query",
      cardType: CardType.Card,
      expansionCode: "XYZ",
      collectorNumber: "999",
    });
    return HttpResponse.json(
      {
        results: { [hashKey]: [cardDocument1.identifier] },
        degradedQueries: [hashKey],
      },
      { status: 200 }
    );
  }
);

export const searchResultsServerError = http.post(
  buildRoute("3/editorSearch/"),
  () => HttpResponse.json(createError("3/editorSearch"), { status: 200 })
);

//# endregion

//# region dfc pairs

export const dfcPairsNoResults = http.get(buildRoute("2/DFCPairs/"), () =>
  HttpResponse.json({ dfcPairs: {} }, { status: 200 })
);

export const dfcPairsMatchingCards1And4 = http.get(
  buildRoute("2/DFCPairs/"),
  () =>
    HttpResponse.json(
      { dfcPairs: { ["my search query"]: cardDocument4.name } },
      { status: 200 }
    )
);

export const dfcPairsServerError = http.get(buildRoute("2/DFCPairs/"), () =>
  HttpResponse.json(createError("2/DFCPairs"), { status: 500 })
);

//# endregion

//# region split card names

export const splitCardNamesNoResults = http.get(
  buildRoute("2/SplitCardNames/"),
  () => HttpResponse.json({ names: [] }, { status: 200 })
);

export const splitCardNamesMatchingFireIce = http.get(
  buildRoute("2/SplitCardNames/"),
  () => HttpResponse.json({ names: ["Fire // Ice"] }, { status: 200 })
);

export const splitCardNamesServerError = http.get(
  buildRoute("2/SplitCardNames/"),
  () => HttpResponse.json(createError("2/SplitCardNames"), { status: 500 })
);

//# endregion

//# region languages

export const languagesNoResults = http.get(buildRoute("2/languages/"), () =>
  HttpResponse.json({ languages: [] }, { status: 200 })
);

export const languagesTwoResults = http.get(buildRoute("2/languages/"), () =>
  HttpResponse.json(
    {
      languages: [
        { name: "English", code: "EN" },
        { name: "French", code: "FR" },
      ],
    },
    { status: 200 }
  )
);

//# endregion

//# region tags

export const tagsNoResults = http.get(buildRoute("2/tags/"), () =>
  HttpResponse.json({ tags: [] }, { status: 200 })
);

export const tagsTwoResults = http.get(buildRoute("2/tags/"), () =>
  HttpResponse.json({ tags: ["Tag 1", "Tag 2"] }, { status: 200 })
);

const serialisedTag = (name: string, displayName: string | null = null) => ({
  name,
  displayName,
  aliases: [],
  isEnabledByDefault: true,
  parent: null,
  children: [],
});

// keep in sync with cardpicker/reason_tags.py's NO_MATCH_REASON_TAGS - real seeded
// (name, displayName) pairs, mirrored here so mocked tests exercise the same
// displayName-lookup path a real seeded backend would.
//
// Exported so NoMatchReasonStrip.spec.ts's exhaustiveness test can check
// NoMatchReasonStrip.tsx's NO_MATCH_REASON_TAG_GROUPS partition against an INDEPENDENT
// mirror of the backend contract (this list), not against itself - a test that only
// compared the partition to a flat list re-derived from the same partition object would
// never actually catch drift.
export const NO_MATCH_REASON_TAG_DISPLAY_NAMES: Array<[string, string]> = [
  ["custom-art", "Custom art"],
  ["altered-frame", "Altered frame"],
  ["upscaled", "Upscaled"],
  ["ai-art", "AI art"],
  ["no-collector-line", "No collector line"],
  ["non-english", "Non-English"],
  ["external-ip", "External IP"],
];

// all seven no-match reason tags exist server-side - NoMatchReasonStrip shows every chip
export const tagsAllNoMatchReasonTags = http.get(buildRoute("2/tags/"), () =>
  HttpResponse.json(
    {
      tags: NO_MATCH_REASON_TAG_DISPLAY_NAMES.map(([name, displayName]) =>
        serialisedTag(name, displayName)
      ),
    },
    { status: 200 }
  )
);

// only two of the seven reason tags exist server-side (seed_no_match_reason_tags hasn't fully
// run, or ran on an older version of the taxonomy) - NoMatchReasonStrip should hide the rest
export const tagsSomeNoMatchReasonTags = http.get(buildRoute("2/tags/"), () =>
  HttpResponse.json(
    {
      tags: NO_MATCH_REASON_TAG_DISPLAY_NAMES.filter(([name]) =>
        ["custom-art", "ai-art"].includes(name)
      ).map(([name, displayName]) => serialisedTag(name, displayName)),
    },
    { status: 200 }
  )
);

// one tag with no displayName set (falls back to raw name) alongside one with a real
// displayName - for asserting the fallback-vs-lookup behaviour directly.
export const tagsOneWithDisplayNameOneWithout = http.get(
  buildRoute("2/tags/"),
  () =>
    HttpResponse.json(
      {
        tags: [
          serialisedTag("custom-art", "Custom art"),
          serialisedTag("altered-frame", null),
        ],
      },
      { status: 200 }
    )
);

// "Borderless" has a displayName deliberately different from its name, so a test asserting
// the mapped label is visible (and the raw name isn't) can't pass by coincidence.
export const tagsBorderlessWithDisplayName = http.get(
  buildRoute("2/tags/"),
  () =>
    HttpResponse.json(
      { tags: [serialisedTag("Borderless", "Frameless Border")] },
      { status: 200 }
    )
);

//# endregion

//# region sample cards

export const sampleCards = http.get(buildRoute("2/sampleCards"), () =>
  HttpResponse.json(
    {
      cards: {
        [Card]: [cardDocument1, cardDocument2, cardDocument3, cardDocument4],
        [Cardback]: [cardDocument5],
        [Token]: [cardDocument6],
      },
    },
    { status: 200 }
  )
);

export const sampleCardsServerError = http.get(
  buildRoute("2/sampleCards/"),
  () => HttpResponse.json(createError("2/sampleCards"), { status: 500 })
);

//# endregion

//# region contributions

// Contrast-audit round (2026-07-25) - /contributions previously had no msw coverage at all, so
// the page always fell back to NoBackendDefault in tests; the "Contribution Guidelines"
// accordion bug the owner reported live only renders once a remote backend (and this endpoint)
// is configured. Minimal one-source fixture, just enough to render both the summary and the
// per-source table alongside the accordion under test.
export const contributionsOneSource = http.get(
  buildRoute("2/contributions/"),
  () =>
    HttpResponse.json(
      {
        cardCountByType: { CARD: 10, CARDBACK: 1, TOKEN: 2 },
        sources: [
          {
            name: "Test Source",
            sourceType: "AWS S3",
            externalLink: "",
            description: "A test source",
            qtyCards: "10",
            qtyCardbacks: "1",
            qtyTokens: "2",
            avgdpi: "300",
            size: "1 GB",
          },
        ],
        totalDatabaseSize: 1_000_000_000,
      },
      { status: 200 }
    )
);

//# endregion

//# region catalog stats

// Proposal F /stats page (docs/features/catalog-stats.md, GET 1/catalogStats/). Two "populated"
// fixtures on purpose, not one - `participationCurrentRatio` matches this task's own directive's
// real, measured 2026-07-29 production numbers (0.05% human/machine vote ratio);
// `participationPostSweep` models the world after the pending full machine sweep the 2026-07-29
// coordinator amendment describes (confirmable/contested grow as more machine work becomes
// human-actionable, humanVotes/distinctHumanVoters held FLAT - the amendment's own instruction,
// "human votes unchanged at ~237"). Both come from features/stats/testFixtures.ts, shared with
// that feature's own Jest unit tests so the two never drift apart.
const catalogStatsContributionsOverTime = {
  bucketDays: 7,
  series: [
    { weekStart: "2026-07-07", bySurface: { "question-feed": 40 } },
    {
      weekStart: "2026-07-14",
      bySurface: { "question-feed": 85, "review-cluster-confirm": 12 },
    },
    { weekStart: "2026-07-21", bySurface: { "question-feed": 100 } },
  ],
};

const catalogStatsSkipBreakdown = {
  byReason: [
    { reason: "no-clear-winner", count: 812 },
    { reason: "too-many-candidates", count: 430 },
    { reason: "no-text", count: 210 },
  ],
  byReasonAndEngine: [
    { reason: "no-clear-winner", engine: "local-ocr-v1", count: 500 },
    { reason: "no-clear-winner", engine: "local-phash-v1", count: 312 },
    { reason: "too-many-candidates", engine: "local-fallback-v1", count: 430 },
    { reason: "no-text", engine: "local-ocr-v1", count: 210 },
  ],
};

const catalogStatsRunHistory = {
  recent: [
    {
      runId: "run-4",
      command: "local_identify_printing_tags",
      status: "running",
      startedAt: "2026-07-29T00:00:00Z",
      finishedAt: null,
      durationSeconds: null,
      votesWritten: null,
    },
    {
      runId: "run-3",
      command: "local_name_frequency_elimination",
      status: "failed",
      startedAt: "2026-07-27T10:00:00Z",
      finishedAt: "2026-07-27T10:05:00Z",
      durationSeconds: 300,
      votesWritten: 0,
    },
    {
      runId: "run-2",
      // votesWritten is null here on purpose - stage_e_streaming_dispatch rows never populate
      // the top-level column (see catalog_stats.py's compute_run_history docstring) - the
      // fixture exists specifically so a test can assert this renders as "—", never "0".
      command: "stage_e_streaming_dispatch",
      status: "completed",
      startedAt: "2026-07-28T02:00:00Z",
      finishedAt: "2026-07-28T02:55:00Z",
      durationSeconds: 3300,
      votesWritten: null,
    },
    {
      runId: "run-1",
      command: "local_identify_printing_tags",
      status: "completed",
      startedAt: "2026-07-28T01:00:00Z",
      finishedAt: "2026-07-28T01:42:00Z",
      durationSeconds: 2520,
      votesWritten: 1840,
    },
  ],
};

const catalogStatsCatalogComposition = {
  sources: [
    {
      name: "Test Source",
      sourceType: "AWS S3",
      externalLink: "",
      description: "A test source",
      qtyCards: "210000",
      qtyCardbacks: "15000",
      qtyTokens: "5770",
      avgdpi: "300",
      size: "512 GB",
    },
  ],
  cardCountByType: { CARD: 210000, CARDBACK: 15000, TOKEN: 5770 },
  totalDatabaseSize: 512_000_000_000,
};

export const catalogStatsCurrentRatio = http.get(
  buildRoute("1/catalogStats/"),
  () =>
    HttpResponse.json(
      {
        generatedAt: "2026-07-29T06:00:00Z",
        contributionsOverTime: catalogStatsContributionsOverTime,
        skipBreakdown: catalogStatsSkipBreakdown,
        runHistory: catalogStatsRunHistory,
        catalogComposition: catalogStatsCatalogComposition,
        participation: participationCurrentRatio,
      },
      { status: 200 }
    )
);

export const catalogStatsPostSweep = http.get(
  buildRoute("1/catalogStats/"),
  () =>
    HttpResponse.json(
      {
        generatedAt: "2026-08-05T06:00:00Z",
        contributionsOverTime: catalogStatsContributionsOverTime,
        skipBreakdown: catalogStatsSkipBreakdown,
        runHistory: catalogStatsRunHistory,
        catalogComposition: catalogStatsCatalogComposition,
        participation: participationPostSweep,
      },
      { status: 200 }
    )
);

// 2026-07-29 owner ruling (features/stats/humanProgressReveal.ts) - the homepage's gated
// human-progress series. `participationAtRevealThreshold` sits exactly at
// HUMAN_VOTE_REVEAL_PERCENT's default (10%), so this handler exercises the real-browser "series
// is visible" path (ParticipationGraph.spec.ts) the same way catalogStatsCurrentRatio/PostSweep
// exercise the "series absent" path.
export const catalogStatsAtRevealThreshold = http.get(
  buildRoute("1/catalogStats/"),
  () =>
    HttpResponse.json(
      {
        generatedAt: "2026-07-29T06:00:00Z",
        contributionsOverTime: catalogStatsContributionsOverTime,
        skipBreakdown: catalogStatsSkipBreakdown,
        runHistory: catalogStatsRunHistory,
        catalogComposition: catalogStatsCatalogComposition,
        participation: participationAtRevealThreshold,
      },
      { status: 200 }
    )
);

// The cache-miss shape (`zeroed_catalog_stats()`, catalog_stats.py) - cold cache, or the
// "shared" cache backend not configured yet. `generatedAt: null`, every other field at its
// zero/empty value - pages/stats.tsx and the homepage's HomepageParticipationGraph must both
// render their "not computed yet" state here, never the zeroed panels as if they were real.
export const catalogStatsNotComputedYet = http.get(
  buildRoute("1/catalogStats/"),
  () =>
    HttpResponse.json(
      {
        generatedAt: null,
        contributionsOverTime: { bucketDays: 7, series: [] },
        skipBreakdown: { byReason: [], byReasonAndEngine: [] },
        runHistory: { recent: [] },
        catalogComposition: {
          sources: [],
          cardCountByType: {},
          totalDatabaseSize: 0,
        },
        participation: {
          total: 0,
          confirmable: 0,
          contested: 0,
          fresh: 0,
          humanVotes: { printingTag: 0, artist: 0, tag: 0, total: 0 },
          distinctHumanVoters: 0,
          md5Groups: {
            groupsWithMultipleCards: 0,
            cardsInMultiCardGroups: 0,
            largestGroupSize: 0,
          },
        },
      },
      { status: 200 }
    )
);

//# endregion

//# region import sites

export const importSitesNoResults = http.get(buildRoute("2/importSites"), () =>
  HttpResponse.json({ importSites: [] }, { status: 200 })
);

export const importSitesOneResult = http.get(buildRoute("2/importSites"), () =>
  HttpResponse.json(
    { importSites: [{ name: "test", url: "test.com" }] },
    { status: 200 }
  )
);

export const importSitesServerError = http.get(
  buildRoute("2/importSites/"),
  () => HttpResponse.json(createError("2/importSites"), { status: 500 })
);

//# endregion

//# region what's new

export const newCardsFirstPageWithTwoSources = http.get(
  buildRoute("2/newCardsFirstPages"),
  () =>
    HttpResponse.json(
      {
        results: {
          [sourceDocument1.key]: {
            source: sourceDocument1,
            hits: 4,
            pages: 2,
            cards: [cardDocument1, cardDocument2],
          },
          [sourceDocument2.key]: {
            source: sourceDocument2,
            hits: 1,
            pages: 1,
            cards: [cardDocument5],
          },
        },
      },
      { status: 200 }
    )
);

export const newCardsFirstPageNoResults = http.get(
  buildRoute("2/newCardsFirstPages"),
  () =>
    HttpResponse.json(
      {
        results: {},
      },
      { status: 200 }
    )
);

export const newCardsPageForSource1 = http.get(
  buildRoute(`2/newCardsPage`),
  ({ request }) => {
    const url = new URL(request.url);
    const source = url.searchParams.get("source");
    const page = url.searchParams.get("page");
    if (source === sourceDocument1.key && page === "2") {
      return HttpResponse.json(
        { cards: [cardDocument3, cardDocument4] },
        { status: 200 }
      );
    }
    return HttpResponse.json(null, { status: 404 });
  }
);

export const newCardsFirstPageServerError = http.get(
  buildRoute("2/newCardsFirstPages"),
  () => HttpResponse.json(createError("2/newCardsFirstPage"), { status: 500 })
);

//# endregion

//# region backend info

export const backendInfo = http.get(buildRoute("2/info"), () =>
  HttpResponse.json(
    {
      info: {
        name: "Test Site",
        description: "Test runner site",
        email: "test@test.com",
        reddit: "reddit.com",
        discord: "discord.com",
      },
    },
    { status: 200 }
  )
);
export const patreon = http.get(buildRoute("2/patreon"), () =>
  HttpResponse.json(
    {
      patreon: {
        campaign: null,
        members: [],
        tiers: null,
        url: null,
      },
    },
    { status: 200 }
  )
);

export const backendInfoServerError = http.get(buildRoute("2/info/"), () =>
  HttpResponse.json(createError("2/info"), { status: 500 })
);

//# endregion

//# region artist external links (M2 applet - ArtistSupportLink.tsx)

// SYNTHETIC DATA ONLY - same rule and reason as cardpicker.tests.mtgac_synthetic_fixtures on the
// backend: MTGAC's real export contains named artists' personal email addresses, which MTGAC
// cannot license away on those individuals' behalf, so no value here is copied from a real
// export. Every artist name/URL below is invented.

const artistExternalLinksNotFoundResponse = {
  found: false,
  pageUrl: null,
  location: null,
  links: [],
  hasSignatureService: false,
};

// The default, catch-all response for this route: `found: false` for ANY artist name - this is
// the applet's fallback-to-deterministic-URL path, and the correct default for every existing
// test that doesn't care about this feature (added to defaultHandlers below).
export const artistExternalLinksNotFound = http.get(
  buildRoute("2/artistExternalLinks/"),
  () => HttpResponse.json(artistExternalLinksNotFoundResponse, { status: 200 })
);

// Named synthetic artists, one per test scenario the M2 applet needs coverage for - each
// handler below only responds to ITS OWN artist name (falling back to the not-found shape for
// any other name), so a test can compose exactly the ONE handler its own artist needs without
// the others interfering.
export const ArtistExternalLinksTestArtists = {
  zeroLinks: "Wisteria Hallowell",
  oneLink: "Cormac Windemere",
  fullRow: "Seraphina Duskwood",
  instagramOnly: "Percival Ashgrove",
  signatureService: "Odalys Ferngrove",
  // A name whose deterministic construction (buildArtistSupportURL) would NOT match MTGAC's
  // real slug - the 8.2% divergence class (accents folded, periods dropped, case normalised,
  // truncation - see docs/features/artist-support-links.md). The synthetic pageUrl below is
  // deliberately NOT `buildArtistSupportURL("Aurélien D. Vasseur")`, so a test asserting
  // pageUrl-preference actually proves preference rather than coincidental equality.
  divergentSlug: "Aurélien D. Vasseur",
};

function buildArtistExternalLinksHandler(
  artistName: string,
  response: {
    pageUrl: string;
    location: string | null;
    links: Array<{ type: string; url: string }>;
    hasSignatureService: boolean;
  }
) {
  return http.get(buildRoute("2/artistExternalLinks/"), ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("name") !== artistName) {
      return HttpResponse.json(artistExternalLinksNotFoundResponse, {
        status: 200,
      });
    }
    return HttpResponse.json({ found: true, ...response }, { status: 200 });
  });
}

// 812 of 2,389 real artists have zero commerce links under the allowlist - the applet must still
// show the MTGAC page link and the credit, never an empty box.
export const artistExternalLinksZeroLinks = buildArtistExternalLinksHandler(
  ArtistExternalLinksTestArtists.zeroLinks,
  {
    pageUrl: `https://www.mtgartistconnection.example/artist/${encodeURIComponent(
      ArtistExternalLinksTestArtists.zeroLinks
    )}`,
    location: "Testland",
    links: [],
    hasSignatureService: false,
  }
);

// 818 of 2,389 real artists have exactly one commerce link - the second-most-common case.
export const artistExternalLinksOneLink = buildArtistExternalLinksHandler(
  ArtistExternalLinksTestArtists.oneLink,
  {
    pageUrl: `https://www.mtgartistconnection.example/artist/${encodeURIComponent(
      ArtistExternalLinksTestArtists.oneLink
    )}`,
    location: "Testland",
    links: [{ type: "website", url: "https://cormacwindemere.example/" }],
    hasSignatureService: false,
  }
);

// All 5 commerce links, in the backend's fixed priority order (only 13 of 2,389 real artists
// have all five) - proves the priority order/5-cap render correctly at the applet level.
export const artistExternalLinksFullRow = buildArtistExternalLinksHandler(
  ArtistExternalLinksTestArtists.fullRow,
  {
    pageUrl: `https://www.mtgartistconnection.example/artist/${encodeURIComponent(
      ArtistExternalLinksTestArtists.fullRow
    )}`,
    location: "Testland",
    links: [
      { type: "website", url: "https://seraphinaduskwood.example/" },
      {
        type: "artstation",
        url: "https://www.artstation.example/seraphinaduskwood",
      },
      {
        type: "inprnt",
        url: "https://www.inprnt.example/gallery/seraphinaduskwood/",
      },
      {
        type: "mountainmage",
        url: "https://mountainmagesigs.example/products/seraphina-duskwood",
      },
      {
        type: "omalink",
        url: "https://original-art.example/collections/seraphina-duskwood",
      },
    ],
    hasSignatureService: false,
  }
);

// The 157-artist rescue scenario `instagram`'s last-resort allowlisting exists for (owner
// ruling): no commerce link at all, instagram is this artist's ONLY link.
export const artistExternalLinksInstagramOnly = buildArtistExternalLinksHandler(
  ArtistExternalLinksTestArtists.instagramOnly,
  {
    pageUrl: `https://www.mtgartistconnection.example/artist/${encodeURIComponent(
      ArtistExternalLinksTestArtists.instagramOnly
    )}`,
    location: null,
    links: [
      {
        type: "instagram",
        url: "https://www.instagram.example/percivalashgrove/",
      },
    ],
    hasSignatureService: false,
  }
);

// Mark's Signature Service badge (true on 227 of 2,389 real artists) - a badge, never a link.
export const artistExternalLinksWithSignatureBadge =
  buildArtistExternalLinksHandler(
    ArtistExternalLinksTestArtists.signatureService,
    {
      pageUrl: `https://www.mtgartistconnection.example/artist/${encodeURIComponent(
        ArtistExternalLinksTestArtists.signatureService
      )}`,
      location: "Testland",
      links: [{ type: "website", url: "https://odalysferngrove.example/" }],
      hasSignatureService: true,
    }
  );

// MTGAC's real pageUrl deliberately does NOT match this project's deterministic
// buildArtistSupportURL construction - the 8.2% slug-divergence class this whole M2 applet
// exists to fix (see docs/features/artist-support-links.md and this file's own module comment).
export const artistExternalLinksDivergentSlug = buildArtistExternalLinksHandler(
  ArtistExternalLinksTestArtists.divergentSlug,
  {
    pageUrl:
      "https://www.mtgartistconnection.example/artist/Aurelien%20D%20Vasseur",
    location: "Testland",
    links: [],
    hasSignatureService: false,
  }
);

//# endregion

//# region health

export const searchEngineHealthy = http.get(
  buildRoute("2/searchEngineHealth/"),
  () => HttpResponse.json({ online: true }, { status: 200 })
);

//# endregion

//# region printing tags

export const printingCandidatesTwoResults = http.post(
  buildRoute("2/printingCandidates/"),
  () =>
    HttpResponse.json(
      { results: [printingCandidate1, printingCandidate2] },
      { status: 200 }
    )
);

export const printingConsensusUnresolved = http.post(
  buildRoute("2/printingConsensus/"),
  () =>
    HttpResponse.json(
      { resolvedPrinting: null, isNoMatch: false, voteTally: [] },
      { status: 200 }
    )
);

export const submitPrintingTagResolvesToPrintingCandidate1 = http.post(
  buildRoute("2/submitPrintingTag/"),
  () =>
    HttpResponse.json(
      {
        resolvedPrinting: printingCandidate1,
        isNoMatch: false,
        voteTally: [
          { printing: printingCandidate1, isNoMatch: false, count: 1 },
        ],
      },
      { status: 200 }
    )
);

// printingCandidate2 (unlike printingCandidate1) has fullArt/isBorderless/isShowcase all true
// - used to exercise QuestionFeed's auto-tag-on-selection behaviour (see attributeChips.ts's
// STANDALONE_CHIPS) across both states.
export const submitPrintingTagResolvesToPrintingCandidate2 = http.post(
  buildRoute("2/submitPrintingTag/"),
  () =>
    HttpResponse.json(
      {
        resolvedPrinting: printingCandidate2,
        isNoMatch: false,
        voteTally: [
          { printing: printingCandidate2, isNoMatch: false, count: 1 },
        ],
      },
      { status: 200 }
    )
);

// printingCandidate3's border color falls outside the taxonomy (not Borderless like candidate2),
// so its Border Color question stays open - used by the Level 3 open-border-color coverage.
export const submitPrintingTagResolvesToPrintingCandidate3 = http.post(
  buildRoute("2/submitPrintingTag/"),
  () =>
    HttpResponse.json(
      {
        resolvedPrinting: printingCandidate3,
        isNoMatch: false,
        voteTally: [
          { printing: printingCandidate3, isNoMatch: false, count: 1 },
        ],
      },
      { status: 200 }
    )
);

export const submitQuestionAbstentionRecorded = http.post(
  buildRoute("2/submitQuestionAbstention/"),
  () => HttpResponse.json({ recorded: true }, { status: 200 })
);

export const submitPrintingTagNoMatch = http.post(
  buildRoute("2/submitPrintingTag/"),
  () =>
    HttpResponse.json(
      {
        resolvedPrinting: null,
        isNoMatch: true,
        voteTally: [{ isNoMatch: true, count: 1 }],
      },
      { status: 200 }
    )
);

export const printingTagQueueOneResult = http.get(
  buildRoute("2/printingTagQueue/"),
  () =>
    HttpResponse.json(
      { hits: 1, pages: 1, cards: [cardDocument1] },
      { status: 200 }
    )
);

export const printingTagQueueTwoResults = http.get(
  buildRoute("2/printingTagQueue/"),
  () =>
    HttpResponse.json(
      { hits: 2, pages: 1, cards: [cardDocument1, cardDocument2] },
      { status: 200 }
    )
);

export const printingTagQueueNoResults = http.get(
  buildRoute("2/printingTagQueue/"),
  () => HttpResponse.json({ hits: 0, pages: 1, cards: [] }, { status: 200 })
);

// 2/voteQueue/ is shared by all three kinds (kind is in the POST body, not the URL), so this
// one handler branches on it rather than registering three separate handlers for the same route.
export const voteQueueArtistOneTagOneResults = http.post(
  buildRoute("2/voteQueue/"),
  async ({ request }) => {
    const body = (await request.json()) as { kind: string; page: number };
    if (body.kind === "artist") {
      return HttpResponse.json(
        { hits: 1, pages: 1, items: [{ card: cardDocument8, tagName: null }] },
        { status: 200 }
      );
    }
    if (body.kind === "tag") {
      return HttpResponse.json(
        {
          hits: 1,
          pages: 1,
          // deliberately a different card than the printing/artist mock fixtures use - the
          // printing tab's mount is never torn down when switching away (matches its
          // existing, unchanged behavior), so reusing the same card here would produce two
          // simultaneous elements with the same alt text once the tag tab is active
          items: [{ card: cardDocument9, tagName: "Borderless" }],
        },
        { status: 200 }
      );
    }
    return HttpResponse.json({ hits: 0, pages: 1, items: [] }, { status: 200 });
  }
);

export const voteQueueNoResults = http.post(buildRoute("2/voteQueue/"), () =>
  HttpResponse.json({ hits: 0, pages: 1, items: [] }, { status: 200 })
);

//# endregion

//# region question feed

// counts default to a plausible non-zero breakdown (one bucket standing in for "some work
// remains") - callers that care about a specific bucket's value pass an override rather than
// every mock spelling out all four fields for a number the test doesn't actually check.
function questionFeedCounts(
  overrides: Partial<QuestionFeedCounts> = {}
): QuestionFeedCounts {
  return { total: 5, confirmable: 0, contested: 0, fresh: 5, ...overrides };
}

export const questionFeedConfirmSuggestion = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "confirm_suggestion",
          card: cardDocument1,
          suggestedPrinting: printingCandidate1,
          candidates: [printingCandidate1, printingCandidate2],
          tagConfidence: { "Full Art": 0, Borderless: 0 },
        },
        remainingEstimate: questionFeedCounts({
          total: 5,
          confirmable: 5,
          fresh: 0,
        }),
      },
      { status: 200 }
    )
);

// Singleton variant of questionFeedConfirmSuggestion above - candidates contains ONLY the
// suggested printing, exercising the case where rejecting it at Level 1 empties the remaining
// set entirely (see QuestionFeed.tsx's suggestionRejectedWithNoneLeft / the double-asking fix).
export const questionFeedConfirmSuggestionSingleton = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "confirm_suggestion",
          card: cardDocument1,
          suggestedPrinting: printingCandidate1,
          candidates: [printingCandidate1],
          tagConfidence: { "Full Art": 0, Borderless: 0 },
        },
        remainingEstimate: questionFeedCounts({
          total: 5,
          confirmable: 5,
          fresh: 0,
        }),
      },
      { status: 200 }
    )
);

export const questionFeedIdentifyPrinting = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "identify_printing",
          card: cardDocument1,
          candidates: [printingCandidate1, printingCandidate2],
          tagConfidence: { "Full Art": 0, Borderless: 0.6 },
        },
        remainingEstimate: questionFeedCounts({ total: 3, fresh: 3 }),
      },
      { status: 200 }
    )
);

// Level 3 border-color coverage needs a candidate whose Frame Treatment resolves (Showcase)
// while its Border Color genuinely stays open (borderColor outside the taxonomy) - candidate2
// can't serve this since it's itself Borderless, which resolves its own Border Color chip.
export const questionFeedIdentifyPrintingOpenBorderColor = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "identify_printing",
          card: cardDocument1,
          candidates: [printingCandidate1, printingCandidate3],
          tagConfidence: { "Full Art": 0, Borderless: 0.6 },
        },
        remainingEstimate: questionFeedCounts({ total: 3, fresh: 3 }),
      },
      { status: 200 }
    )
);

// Issue #503 (WTC phase C1) - a MIXED candidate set for the illustration-grouping regression
// guard: `illustrationGroupCandidateA`/`B` share an illustration (a real 2+ cluster),
// `illustrationGroupCandidateC` has its own distinct illustrationId (no sibling - forms a
// cluster of its own, size 1: group size is orthogonal to whether a candidate clusters at
// all), and `illustrationGroupCandidateD` carries no illustrationId at all
// (CanonicalPrintingMetadata.illustration_id is nullable and frequently absent - see
// local_illustration.py:137) - the only member of this set that never clusters. Built by
// spreading the existing printingCandidate1/2 fixtures rather than editing test-constants.ts,
// which is out of this change's scope.
// candidateA carries an art crop (the common case); candidateB shares its illustration but
// has none (a metadata sidecar gap) - together they cover both the swap and its fallback.
export const illustrationGroupCandidateA: PrintingCandidate = {
  ...printingCandidate1,
  identifier: "illustration-group-candidate-a",
  collectorNumber: "101",
  illustrationId: "illustration-shared",
  artCropUrl: "https://example.com/art-crop-a.png",
};
export const illustrationGroupCandidateB: PrintingCandidate = {
  ...printingCandidate2,
  identifier: "illustration-group-candidate-b",
  collectorNumber: "102",
  illustrationId: "illustration-shared",
  artCropUrl: null,
};
export const illustrationGroupCandidateC: PrintingCandidate = {
  ...printingCandidate1,
  identifier: "illustration-group-candidate-c",
  collectorNumber: "103",
  illustrationId: "illustration-unique-to-c",
};
export const illustrationGroupCandidateD: PrintingCandidate = {
  ...printingCandidate2,
  identifier: "illustration-group-candidate-d",
  collectorNumber: "104",
  illustrationId: null,
};

// The illustration question type (wtc-question-model.md §7.2) - art crops only, grouped by
// unique illustrationId. `A` and `C` carry distinct illustrationIds (each tile is its own
// question option), unlike `A`/`B` above which deliberately share one for the identify_printing
// clustering guard - the backend's own dedup (`_illustration_item`) never sends the frontend two
// candidates with the same illustrationId, so this fixture's shape matches a real payload.
export const questionFeedIllustration = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "illustration",
          card: cardDocument1,
          illustrationCandidates: [
            illustrationGroupCandidateA,
            illustrationGroupCandidateC,
          ],
          tagConfidence: {},
        },
        remainingEstimate: questionFeedCounts({ total: 2, fresh: 2 }),
      },
      { status: 200 }
    )
);

export const questionFeedIdentifyPrintingGroupedByIllustration = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "identify_printing",
          card: cardDocument1,
          candidates: [
            illustrationGroupCandidateA,
            illustrationGroupCandidateB,
            illustrationGroupCandidateC,
            illustrationGroupCandidateD,
          ],
          tagConfidence: { "Full Art": 0, Borderless: 0.6 },
        },
        remainingEstimate: questionFeedCounts({ total: 4, fresh: 4 }),
      },
      { status: 200 }
    )
);

// Issue #503 (WTC phase C2) / #524 - 2/submitIllustrationVote/. Mirrors the shape
// `illustration_vote.py`'s IllustrationVoteOutcome serialises: `printingVoteCast` true only at
// a live 1:1 printing match, `artistVoteCast` true only when the artist channel actually wrote.
export const submitIllustrationVoteCastsPrintingAndArtist = http.post(
  buildRoute("2/submitIllustrationVote/"),
  () =>
    HttpResponse.json(
      {
        illustrationId: "illustration-shared",
        isUnknown: false,
        printingVoteCast: true,
        resolvedPrinting: illustrationGroupCandidateA,
        artistVoteCast: true,
      },
      { status: 200 }
    )
);

// N>1 live printings - nothing on the printing channel, the normal outcome for a genuine
// multi-printing illustration cluster.
export const submitIllustrationVoteCastsNothingOnPrintingChannel = http.post(
  buildRoute("2/submitIllustrationVote/"),
  () =>
    HttpResponse.json(
      {
        illustrationId: "illustration-shared",
        isUnknown: false,
        printingVoteCast: false,
        artistVoteCast: true,
      },
      { status: 200 }
    )
);

// "Not this art" - 2/submitIllustrationRejection/. Mirrors SubmitIllustrationRejectionResponse's
// narrower shape (no printing/artist channel to report on - see that response's own comment).
export const submitIllustrationRejection = http.post(
  buildRoute("2/submitIllustrationRejection/"),
  () =>
    HttpResponse.json(
      { illustrationId: "illustration-shared" },
      { status: 200 }
    )
);

export const questionFeedArtist = http.get(buildRoute("2/questionFeed/"), () =>
  HttpResponse.json(
    {
      item: {
        type: "artist",
        card: cardDocument8,
        confidentlyKnownArtistName: null,
        scryfallIllustrationUrl: null,
      },
      remainingEstimate: questionFeedCounts({ total: 2, fresh: 2 }),
    },
    { status: 200 }
  )
);

// Same as questionFeedArtist but the card's canonical printing carries a harvested Scryfall
// art-crop URL - exercises the WTC artist re-frame's subject-image substitution (QuestionFeed.
// tsx's subjectImageSrc) rather than questionFeedArtist's null-falls-back-to-card-image case.
export const questionFeedArtistWithIllustration = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "artist",
          card: cardDocument8,
          confidentlyKnownArtistName: null,
          scryfallIllustrationUrl:
            "https://cards.scryfall.io/art_crop/front/a/b/ab000000-0000-0000-0000-000000000000.jpg",
        },
        remainingEstimate: questionFeedCounts({ total: 2, fresh: 2 }),
      },
      { status: 200 }
    )
);

// cardDocument8 has a confidently-known canonicalArtist (Alpha Artist) - this mock exercises
// ArtistVotePicker's collapsed pre-filled state (see its own "wrong?" affordance) via real
// questionFeed-shaped data, distinct from questionFeedArtist's plain-picker (unresolved) case.
export const questionFeedArtistConfidentlyKnown = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      {
        item: {
          type: "artist",
          card: cardDocument8,
          confidentlyKnownArtistName: "Alpha Artist",
        },
        remainingEstimate: questionFeedCounts({ total: 2, fresh: 2 }),
      },
      { status: 200 }
    )
);

export const questionFeedTag = http.get(buildRoute("2/questionFeed/"), () =>
  HttpResponse.json(
    {
      item: {
        type: "tag",
        card: cardDocument9,
        tagName: "Borderless",
      },
      remainingEstimate: questionFeedCounts({ total: 1, fresh: 1 }),
    },
    { status: 200 }
  )
);

// The border question type's answer surface is the BORDER_COLOR_GROUP chips, the Full Art
// chip, and FRAME_TREATMENT_GROUP's Showcase/Extended Art chips (see BorderColorQuestion.tsx)
// - the mock seeds tagConfidence the way the backend `_border_item` builder does
// (question_feed.py's `_tag_confidence`: the full chip set), so the chips render with a
// realistic lean the moment the question lands.
export const questionFeedBorder = http.get(buildRoute("2/questionFeed/"), () =>
  HttpResponse.json(
    {
      item: {
        type: "border",
        card: cardDocument9,
        tagConfidence: {
          "Black Border": 0.8,
          "White Border": 0,
          "Silver Border": 0,
          Borderless: 0,
          "Full Art": 0,
          Showcase: 0,
          Extended: 0,
        },
      },
      remainingEstimate: questionFeedCounts({ total: 1, fresh: 1 }),
    },
    { status: 200 }
  )
);

export const questionFeedCaughtUp = http.get(
  buildRoute("2/questionFeed/"),
  () =>
    HttpResponse.json(
      { remainingEstimate: questionFeedCounts({ total: 0, fresh: 0 }) },
      { status: 200 }
    )
);

//# endregion

//# region attribute voting

export const artistCandidatesTwoResults = http.post(
  buildRoute("2/artistCandidates/"),
  () =>
    HttpResponse.json(
      { results: [canonicalArtist1, canonicalArtist2] },
      { status: 200 }
    )
);

export const artistConsensusUnresolved = http.post(
  buildRoute("2/artistConsensus/"),
  () =>
    HttpResponse.json(
      { resolvedArtist: null, isUnknown: false, voteTally: [] },
      { status: 200 }
    )
);

export const submitArtistVoteResolvesToCanonicalArtist1 = http.post(
  buildRoute("2/submitArtistVote/"),
  () =>
    HttpResponse.json(
      {
        resolvedArtist: canonicalArtist1,
        isUnknown: false,
        voteTally: [{ artist: canonicalArtist1, isUnknown: false, count: 1 }],
      },
      { status: 200 }
    )
);

export const tagConsensusTwoUnresolvedTags = http.post(
  buildRoute("2/tagConsensus/"),
  () =>
    HttpResponse.json(
      {
        tags: [
          {
            tagName: "Borderless",
            resolvedPolarity: null,
            netPolarity: 0,
            tally: [],
          },
          {
            tagName: "Extended",
            resolvedPolarity: null,
            netPolarity: 0,
            tally: [],
          },
        ],
      },
      { status: 200 }
    )
);

// Proposal B PR-3: a clearly-negative "appropriate-bleed" lean, resolved via
// resolveSingleBleedPrior to prior "trimmed" - the fallback case (extend the full target),
// which willLikelyGenerateBleed maps to "the preview badge should show".
export const tagConsensusAppropriateBleedTrimmed = http.post(
  buildRoute("2/tagConsensus/"),
  () =>
    HttpResponse.json(
      {
        tags: [
          {
            tagName: "appropriate-bleed",
            resolvedPolarity: -1,
            netPolarity: -3,
            tally: [],
          },
        ],
      },
      { status: 200 }
    )
);

export const submitTagVoteResolvesToApply = http.post(
  buildRoute("2/submitTagVote/"),
  () =>
    HttpResponse.json(
      {
        tagName: "Borderless",
        resolvedPolarity: 1,
        netPolarity: 1,
        tally: [{ polarity: 1, count: 1 }],
      },
      { status: 200 }
    )
);

// Funnel round (funnel-spec.md F4b/D20) - the /display art-picker funnel's implicit-support-on-
// pick mechanic. Response shape mirrors the real endpoint (PR #325's
// post_cast_implicit_vote/post_retract_implicit_vote): castImplicitVote wraps a list in `tags`
// (TagConsensusResponse); retractImplicitVote returns a single TagConsensusEntry, no wrapper.
export const castImplicitVoteSuccess = http.post(
  buildRoute("2/castImplicitVote/"),
  () =>
    HttpResponse.json(
      {
        tags: [
          {
            tagName: "Old Border",
            resolvedPolarity: null,
            netPolarity: 0.25,
            tally: [{ polarity: 1, count: 1 }],
          },
        ],
      },
      { status: 200 }
    )
);

export const retractImplicitVoteSuccess = http.post(
  buildRoute("2/retractImplicitVote/"),
  () =>
    HttpResponse.json(
      {
        tagName: "Old Border",
        resolvedPolarity: null,
        netPolarity: 0,
        tally: [],
      },
      { status: 200 }
    )
);

export const reportCardSuccess = http.post(buildRoute("2/reportCard/"), () =>
  HttpResponse.json({ reported: true, voteCast: true }, { status: 200 })
);

export const reportCardRateLimited = http.post(
  buildRoute("2/reportCard/"),
  () => HttpResponse.json(createError("Report limit reached"), { status: 429 })
);

const whoami = (body: {
  authenticated: boolean;
  username: string | null;
  moderator: boolean;
  discordEnabled: boolean;
  loginUrl: string | null;
  logoutUrl: string | null;
}) =>
  http.get(buildRoute("2/whoami/"), () =>
    HttpResponse.json(body, { status: 200 })
  );

// in defaultHandlers below: the vote-queue page always fires the whoami query now, and the
// pre-moderation behavior (no login link, no Moderation tab) is the anonymous+disabled case
export const whoamiAnonymous = whoami({
  authenticated: false,
  username: null,
  moderator: false,
  discordEnabled: false,
  loginUrl: null,
  logoutUrl: null,
});

export const whoamiAnonymousDiscordEnabled = whoami({
  authenticated: false,
  username: null,
  moderator: false,
  discordEnabled: true,
  loginUrl: "/accounts/discord/login/",
  logoutUrl: null,
});

export const whoamiSignedInNotModerator = whoami({
  authenticated: true,
  username: "somebody",
  moderator: false,
  discordEnabled: true,
  loginUrl: "/accounts/discord/login/",
  logoutUrl: "/accounts/logout/",
});

export const whoamiModerator = whoami({
  authenticated: true,
  username: "mod",
  moderator: true,
  discordEnabled: true,
  loginUrl: "/accounts/discord/login/",
  logoutUrl: "/accounts/logout/",
});

// `whoami` resolves asynchronously in production (~450ms measured live) - `isModerator`
// starts false on first paint and flips true once this settles. Exercises that flip
// directly, standing in for `whoamiModerator` above wherever a test needs the async gap
// itself, not just the eventual moderator state (see whatsthat.tsx's PrintingQueueOrDefault
// and its regression test in ModerationTab.spec.ts).
export const whoamiModeratorAfterDelay = http.get(
  buildRoute("2/whoami/"),
  async () => {
    await delay(300);
    return HttpResponse.json(
      {
        authenticated: true,
        username: "mod",
        moderator: true,
        discordEnabled: true,
        loginUrl: "/accounts/discord/login/",
        logoutUrl: "/accounts/logout/",
      },
      { status: 200 }
    );
  }
);

export const moderationQueueOneResult = http.post(
  buildRoute("2/moderationQueue/"),
  () =>
    HttpResponse.json(
      {
        hits: 1,
        pages: 1,
        items: [
          {
            card: cardDocument1,
            tagName: "NSFW",
            reportCount: 3,
            reportExcerpts: ["way too spicy", "really not ok"],
          },
        ],
      },
      { status: 200 }
    )
);

export const moderationQueueForbidden = http.post(
  buildRoute("2/moderationQueue/"),
  () =>
    HttpResponse.json(createError("Moderator access required"), {
      status: 403,
    })
);

export const moderationDrivesTwoResults = http.post(
  buildRoute("2/moderationDrives/"),
  () =>
    HttpResponse.json(
      {
        hits: 2,
        pages: 1,
        items: [
          {
            source: sourceDocument2,
            qtyCards: 3,
            qtyCardbacks: 0,
            qtyTokens: 1,
          },
          {
            source: sourceDocument1,
            qtyCards: 1,
            qtyCardbacks: 1,
            qtyTokens: 0,
          },
        ],
      },
      { status: 200 }
    )
);

export const moderationDrivesForbidden = http.post(
  buildRoute("2/moderationDrives/"),
  () =>
    HttpResponse.json(createError("Moderator access required"), {
      status: 403,
    })
);

export const moderationDriveCardsOneResult = http.post(
  buildRoute("2/moderationDriveCards/"),
  () =>
    HttpResponse.json(
      {
        hits: 1,
        pages: 1,
        source: sourceDocument1,
        cards: [cardDocument1],
      },
      { status: 200 }
    )
);

export const moderationRemoveCardSucceeds = http.post(
  buildRoute("2/moderationRemoveCard/"),
  () => HttpResponse.json({ removed: true }, { status: 200 })
);

export const moderationRemoveDriveSucceeds = http.post(
  buildRoute("2/moderationRemoveDrive/"),
  () => HttpResponse.json({ removed: true, cardsRemoved: 1 }, { status: 200 })
);

//# endregion

//# region presets

export const defaultHandlers = [
  favicon,
  sourceDocumentsNoResults,
  cardDocumentsNoResults,
  cardbacksNoResults,
  searchResultsNoResults,
  dfcPairsNoResults,
  splitCardNamesNoResults,
  languagesTwoResults,
  tagsNoResults,
  importSitesOneResult,
  sampleCards,
  backendInfo,
  patreon,
  artistExternalLinksNotFound,
  searchEngineHealthy,
  whoamiAnonymous,
];

//# endregion
