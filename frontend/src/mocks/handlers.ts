import { http, HttpResponse } from "msw";

import { Card, Cardback, Token } from "@/common/constants";
import { computeSearchQueryHashKey } from "@/common/processing";
import {
  Campaign,
  CardType,
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
  localBackend,
  printingCandidate1,
  printingCandidate2,
  sourceDocument1,
  sourceDocument2,
  sourceDocument3,
} from "@/common/test-constants";

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
 * Re-route ping.js favicon request to frontend for E2E tests
 */
export const favicon = http.get(buildRoute("favicon.ico"), async () => {
  const image = await fetch("http://localhost:3000/favicon.ico").then((res) =>
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
const NO_MATCH_REASON_TAG_DISPLAY_NAMES: Array<[string, string]> = [
  ["custom-art", "Custom art"],
  ["altered-frame", "Altered frame"],
  ["upscaled", "Upscaled"],
  ["ai-art", "AI art"],
  ["no-collector-line", "No collector line"],
  ["non-english", "Non-English"],
];

// all six no-match reason tags exist server-side - NoMatchReasonStrip shows every chip
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

// only two of the six reason tags exist server-side (seed_no_match_reason_tags hasn't fully
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

// printingCandidate2 (unlike printingCandidate1) has fullArt/isBorderless both true - used to
// exercise PrintingConfirmStrip's pre-fill-from-candidate-metadata behaviour in both states.
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
          { tagName: "Borderless", resolvedPolarity: null, tally: [] },
          { tagName: "Extended", resolvedPolarity: null, tally: [] },
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
        tally: [{ polarity: 1, count: 1 }],
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

//# endregion

//# region presets

export const defaultHandlers = [
  favicon,
  sourceDocumentsNoResults,
  cardDocumentsNoResults,
  cardbacksNoResults,
  searchResultsNoResults,
  dfcPairsNoResults,
  languagesTwoResults,
  tagsNoResults,
  importSitesOneResult,
  sampleCards,
  backendInfo,
  patreon,
  searchEngineHealthy,
  whoamiAnonymous,
];

//# endregion
