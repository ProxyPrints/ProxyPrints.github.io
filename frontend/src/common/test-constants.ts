/**
 * Some pre-built objects which can be used to build up Redux state for tests.
 */

import { Card, MaximumDPI, MaximumSize, MinimumDPI } from "@/common/constants";
import {
  CanonicalArtist,
  CardType as CardTypeSchema,
  PrintingCandidate,
  PrintingTagStatus,
  SourceType,
  TagVoteDisplayStatus,
} from "@/common/schema_types";
import {
  BackendState,
  CardDocument,
  Project,
  SearchSettings,
  SourceDocument,
  SourceDocuments,
} from "@/common/types";

//# region backend

export const localBackendURL = "http://127.0.0.1:8000";
export const localBackend: BackendState = { url: localBackendURL };
export const noBackend: BackendState = { url: null };

//# endregion

//# region sources

export const sourceDocument1: SourceDocument = {
  pk: 0,
  key: "source_1",
  name: "Source 1",
  sourceType: SourceType.GoogleDrive,
  externalLink: undefined,
  description: "",
};

export const sourceDocument2: SourceDocument = {
  pk: 1,
  key: "source_2",
  name: "Source 2",
  sourceType: SourceType.GoogleDrive,
  externalLink: undefined,
  description: "",
};

export const sourceDocument3: SourceDocument = {
  pk: 2,
  key: "source_3",
  name: "Source 3",
  sourceType: SourceType.GoogleDrive,
  externalLink: undefined,
  description: "",
};

export const sourceDocument4: SourceDocument = {
  pk: 3,
  key: "source_4",
  name: "Source 4",
  sourceType: SourceType.GoogleDrive,
  externalLink: undefined,
  description: "",
};

export const sourceDocuments: SourceDocuments = {
  [sourceDocument1.pk]: sourceDocument1,
  [sourceDocument2.pk]: sourceDocument2,
  [sourceDocument3.pk]: sourceDocument3,
  [sourceDocument4.pk]: sourceDocument4,
};

//# endregion

//# region cards

export const cardDocument1: CardDocument = {
  identifier: "1c4M-sK9gd0Xju0NXCPtqeTW_DQTldVU5",
  cardType: CardTypeSchema.Card,
  name: "Card 1",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card one",
  extension: "png",
  dateCreated: "1st January, 2000", // formatted by backend
  dateModified: "1st January, 2000", // formatted by backend
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

export const cardDocument2: CardDocument = {
  identifier: "1IDtqSjJ4Yo45AnNA4SplOiN7ewibifMa",
  cardType: CardTypeSchema.Card,
  name: "Card 2",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 2",
  extension: "png",
  dateCreated: "1st January, 2000", // formatted by backend
  dateModified: "1st January, 2000", // formatted by backend
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

export const cardDocument3: CardDocument = {
  identifier: "1HsvTYs1jFGe1c8U1PnNZ9aB8jkAW7KU0",
  cardType: CardTypeSchema.Card,
  name: "Card 3",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 3",
  extension: "png",
  dateCreated: "1st January, 2000", // formatted by backend
  dateModified: "1st January, 2000", // formatted by backend
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

export const cardDocument4: CardDocument = {
  identifier: "1-dcs0FEE05MTGiYbKqs9HnRdhXkgtIJG",
  cardType: CardTypeSchema.Card,
  name: "Card 4",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 4",
  extension: "png",
  dateCreated: "1st January, 2000", // formatted by backend
  dateModified: "1st January, 2000", // formatted by backend
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

export const cardDocument5: CardDocument = {
  identifier: "1JtXL6Ca9nQkvhwZZRR9ZuKA9_DzsFf1V",
  cardType: CardTypeSchema.Cardback,
  name: "Card 5",
  priority: 0,
  source: sourceDocument2.key,
  sourceName: sourceDocument2.name,
  sourceId: sourceDocument2.pk,
  sourceVerbose: `${sourceDocument2.name} Cardbacks`,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 5",
  extension: "png",
  dateCreated: "1st January, 2000", // formatted by backend
  dateModified: "1st January, 2000", // formatted by backend
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

export const cardDocument6: CardDocument = {
  identifier: "1oigI6wz0zA--pNMuExKTs40kBNH6VRP_",
  cardType: CardTypeSchema.Token,
  name: "Card 6",
  priority: 0,
  source: sourceDocument3.key,
  sourceName: sourceDocument3.name,
  sourceId: sourceDocument3.pk,
  sourceVerbose: `${sourceDocument3.name} Tokens`,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 6",
  extension: "png",
  dateCreated: "1st January, 2000", // formatted by backend
  dateModified: "1st January, 2000", // formatted by backend
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

// Card from source2 (for multi-source grid selector tests)
export const cardDocument7: CardDocument = {
  identifier: "1aA2bB3cC4dD5eE6fF7gG8hH9iI0jJ",
  cardType: CardTypeSchema.Card,
  name: "Card 7",
  priority: 0,
  source: sourceDocument2.key,
  sourceName: sourceDocument2.name,
  sourceId: sourceDocument2.pk,
  sourceVerbose: sourceDocument2.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 7",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

// Cards with canonicalCard data (for CanonicalCardFilter tests)
export const cardDocument8: CardDocument = {
  identifier: "1bB2cC3dD4eE5fF6gG7hH8iI9jJ0kK",
  cardType: CardTypeSchema.Card,
  name: "Card 8",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 8",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
  canonicalCard: {
    expansionCode: "xyz",
    expansionName: "XYZ Set",
    collectorNumber: "001",
    identifier: "xyz-001",
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
  },
  canonicalArtist: {
    name: "Alpha Artist",
  },
};

export const cardDocument9: CardDocument = {
  identifier: "1cC2dD3eE4fF5gG6hH7iI8jJ9kK0lL",
  cardType: CardTypeSchema.Card,
  name: "Card 9",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 9",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
  canonicalCard: {
    expansionCode: "xyz",
    expansionName: "XYZ Set",
    collectorNumber: "002",
    identifier: "xyz-002",
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
  },
  canonicalArtist: {
    name: "Beta Artist",
  },
};

export const cardDocument10: CardDocument = {
  identifier: "1dD2eE3fF4gG5hH6iI7jJ8kK9lL0mM",
  cardType: CardTypeSchema.Card,
  name: "Card 10",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 10",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
  canonicalCard: {
    expansionCode: "abc",
    expansionName: "ABC Set",
    collectorNumber: "001",
    identifier: "abc-001",
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
  },
  canonicalArtist: {
    name: "Alpha Artist",
  },
};

// Card with no canonicalCard data (for Unknown handling in CanonicalCardFilter)
export const cardDocument11: CardDocument = {
  identifier: "1eE2fF3gG4hH5iI6jJ7kK8lL9mM0nN",
  cardType: CardTypeSchema.Card,
  name: "Card 11",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 11",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
  canonicalCard: null,
};

// Community-vote-resolved printing match (2ED #162) - for decklist set/collector-number
// re-rank + match indicator tests (Playwright: ImportText.spec.ts)
export const cardDocument12: CardDocument = {
  identifier: "1fF2gG3hH4iI5jJ6kK7lL8mM9nN0oO",
  cardType: CardTypeSchema.Card,
  name: "Lightning Bolt",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "lightning bolt",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Resolved,
  canonicalCard: {
    expansionCode: "2ED",
    expansionName: "Unlimited Edition",
    collectorNumber: "162",
    identifier: "2ed-162",
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
  },
};

// Issue #167 (Select Version section, unified spec) fixtures below. Two copies of the same
// suggested printing (sv-001), differing DPI, so grouping/representative-selection tests have a
// real "+N more of this printing" cluster to expand.
export const cardDocument13: CardDocument = {
  identifier: "1gG2hH3iI4jJ5kK6lL7mM8nN9oO0pP",
  cardType: CardTypeSchema.Card,
  name: "Card 13 (suggested printing, lower DPI copy)",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 600,
  searchq: "card 13",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
  suggestedCanonicalCard: {
    identifier: "sv-001",
    expansionCode: "sv1",
    expansionName: "Select Version Set One",
    collectorNumber: "010",
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
  },
};

export const cardDocument14: CardDocument = {
  identifier: "1hH2iI3jJ4kK5lL6mM7nN8oO9pP0qQ",
  cardType: CardTypeSchema.Card,
  name: "Card 14 (suggested printing, higher DPI copy)",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 1200,
  searchq: "card 14",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
  suggestedCanonicalCard: {
    identifier: "sv-001",
    expansionCode: "sv1",
    expansionName: "Select Version Set One",
    collectorNumber: "010",
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
  },
};

// A resolved printing (sv-002) - sole member of its own canonical group.
export const cardDocument15: CardDocument = {
  identifier: "1iI2jJ3kK4lL5mM6nN7oO8pP9qQ0rR",
  cardType: CardTypeSchema.Card,
  name: "Card 15 (resolved printing)",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 800,
  searchq: "card 15",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Resolved,
  canonicalCard: {
    identifier: "sv-002",
    expansionCode: "sv2",
    expansionName: "Select Version Set Two",
    collectorNumber: "020",
    smallThumbnailUrl: "",
    mediumThumbnailUrl: "",
  },
};

// No printing data at all, but a resolved no-match reason tag - group 2 (non-canonical).
export const cardDocument16: CardDocument = {
  identifier: "1jJ2kK3lL4mM5nN6oO7pP8qQ9rR0sS",
  cardType: CardTypeSchema.Card,
  name: "Card 16 (custom art, no printing)",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 800,
  searchq: "card 16",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: ["custom-art"],
  printingTagStatus: PrintingTagStatus.NoMatch,
};

// Neither printing data nor a classifying reason tag - the "unknown" residue group.
export const cardDocument17: CardDocument = {
  identifier: "1kK2lL3mM4nN5oO6pP7qQ8rR9sS0tT",
  cardType: CardTypeSchema.Card,
  name: "Card 17 (unknown)",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 800,
  searchq: "card 17",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
};

// Carries a resolved "Full Art" attribute tag (for moment (b)'s "More like this" seeding) AND an
// unresolved/suggested "Old Border" vote (for moment (c)'s filtered-selection confirm chip, once
// a caller manually activates the "Old Border" filter - it's a different tag from the resolved
// one on purpose, since a resolved tag could never surface the confirm chip - see
// SelectVersionResults.tsx's own module comment for why).
export const cardDocument18: CardDocument = {
  identifier: "1lL2mM3nN4oO5pP6qQ7rR8sS9tT0uU",
  cardType: CardTypeSchema.Card,
  name: "Card 18 (resolved Full Art, suggested Old Border)",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 800,
  searchq: "card 18",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: ["Full Art"],
  printingTagStatus: PrintingTagStatus.Unresolved,
  tagVoteStatuses: {
    "Full Art": TagVoteDisplayStatus.Resolved,
    "Old Border": TagVoteDisplayStatus.Suggested,
  },
  // Fix round (owner-ratified condition 6, PR #329 review) - the funnel's SUGGESTED chip
  // state/implicit-vote-cast eligibility now reads THIS field, not tagVoteStatuses (which is a
  // source-agnostic collapse with no implicit-vote exclusion or weight floor - see
  // attributeChips.ts's chipMembershipState comment). "Old Border" appears in BOTH fields on
  // this fixture deliberately, so existing funnel tests exercising the compliant path keep
  // passing; see cardDocument19 below for the fixture proving the NON-compliant
  // (tagVoteStatuses-only) case renders no suggested chip and casts no implicit vote.
  suggestedFilterTagNames: ["Old Border"],
};

// Fix round (owner-ratified condition 6, PR #329 review) - the exact non-compliance Tron caught,
// pinned as a fixture: tagVoteStatuses says "suggested" for "Old Border", but
// suggestedFilterTagNames does NOT include it (e.g. the leaning is implicit-only, or a single
// sub-threshold machine vote, or a REJECT-leaning split - none of which clear the compliant
// source's real, non-implicit APPLY-leaning floor). The funnel must render NO suggested chip and
// cast NO implicit vote for this tag on this card.
export const cardDocument19: CardDocument = {
  identifier: "1mM2nN3oO4pP5qQ6rR7sS8tT9uU0vV",
  cardType: CardTypeSchema.Card,
  name: "Card 19 (tagVoteStatuses says suggested, suggestedFilterTagNames does not)",
  priority: 0,
  source: sourceDocument1.key,
  sourceName: sourceDocument1.name,
  sourceId: sourceDocument1.pk,
  sourceVerbose: sourceDocument1.name,
  sourceType: SourceType.GoogleDrive,
  sourceExternalLink: undefined,
  dpi: 800,
  searchq: "card 19",
  extension: "png",
  dateCreated: "1st January, 2000",
  dateModified: "1st January, 2000",
  size: 10_000_000,
  smallThumbnailUrl: "",
  mediumThumbnailUrl: "",
  language: "EN",
  tags: [],
  printingTagStatus: PrintingTagStatus.Unresolved,
  tagVoteStatuses: {
    "Old Border": TagVoteDisplayStatus.Suggested,
  },
  suggestedFilterTagNames: [],
};

//# endregion

//# region project

export const projectSelectedImage1: Project = {
  members: [
    {
      id: "t-0",
      front: {
        query: { query: "my search query", cardType: Card },
        selectedImage: cardDocument1.identifier,
        selected: false,
      },
      back: null,
    },
  ],
  nextMemberId: 1,
  cardback: null,
  mostRecentlySelectedSlot: null,
  manualOverrides: {},
};

export const projectThreeMembersSelectedImage1: Project = {
  members: [
    {
      id: "t-0",
      front: {
        query: { query: "my search query", cardType: Card },
        selectedImage: cardDocument1.identifier,
        selected: false,
      },
      back: null,
    },
    {
      id: "t-1",
      front: {
        query: { query: "my search query", cardType: Card },
        selectedImage: cardDocument1.identifier,
        selected: false,
      },
      back: null,
    },
    {
      id: "t-2",
      front: {
        query: { query: "my search query", cardType: Card },
        selectedImage: cardDocument1.identifier,
        selected: false,
      },
      back: null,
    },
  ],
  nextMemberId: 3,
  cardback: null,
  mostRecentlySelectedSlot: null,
  manualOverrides: {},
};

export const projectSelectedImage2: Project = {
  members: [
    {
      id: "t-0",
      front: {
        query: { query: "my search query", cardType: Card },
        selectedImage: cardDocument2.identifier,
        selected: false,
      },
      back: null,
    },
  ],
  nextMemberId: 1,
  cardback: null,
  mostRecentlySelectedSlot: null,
  manualOverrides: {},
};

//# endregion

//# region search settings

export const defaultSettings: SearchSettings = {
  searchTypeSettings: { fuzzySearch: false, filterCardbacks: false },
  sourceSettings: {
    sources: [
      [sourceDocument1.pk, true],
      [sourceDocument2.pk, true],
      [sourceDocument3.pk, true],
      [sourceDocument4.pk, true],
    ],
  },
  filterSettings: {
    minimumDPI: MinimumDPI,
    maximumDPI: MaximumDPI,
    maximumSize: MaximumSize,
    languages: [],
    includesTags: [],
    excludesTags: ["NSFW"],
    fullArtOnly: false,
    borderlessOnly: false,
  },
};

export const printingCandidate1: PrintingCandidate = {
  identifier: "printing-candidate-1",
  canonicalId: "canonical-1",
  expansionCode: "abc",
  expansionName: "A Big Cardset",
  collectorNumber: "1",
  artist: "Some Artist",
  smallThumbnailUrl: "https://example.com/small1.png",
  mediumThumbnailUrl: "https://example.com/medium1.png",
  fullArt: false,
  isBorderless: false,
  frame: "2015",
  borderColor: "black",
  isShowcase: false,
  isExtendedArt: false,
  isEtched: false,
  releasedAt: "2020-01-01",
};

export const printingCandidate2: PrintingCandidate = {
  identifier: "printing-candidate-2",
  canonicalId: "canonical-1",
  expansionCode: "xyz",
  expansionName: "Another Cardset",
  collectorNumber: "42",
  artist: "Another Artist",
  smallThumbnailUrl: "https://example.com/small2.png",
  mediumThumbnailUrl: "https://example.com/medium2.png",
  fullArt: true,
  isBorderless: true,
  frame: "2003",
  borderColor: "borderless",
  isShowcase: true,
  isExtendedArt: false,
  isEtched: false,
  releasedAt: "2010-06-15",
};

export const canonicalArtist1: CanonicalArtist = { name: "Some Artist" };
export const canonicalArtist2: CanonicalArtist = { name: "Another Artist" };

//# endregion
