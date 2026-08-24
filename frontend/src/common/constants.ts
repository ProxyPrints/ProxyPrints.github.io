import { CardType as CardTypeSchema } from "@/common/schema_types";
import {
  CardSpacingState,
  Cardstock,
  CardType,
  Faces,
  MarginProfileState,
  SortBy,
} from "@/common/types";

export const CardWidthMM = 63;
export const CardHeightMM = 88;
// 36 pixels (each side) at 300 dpi -> 0.12 inches, convert to MM. ref: https://www.makeplayingcards.com/pops/faq-photo.html
export const BleedEdgeMM = Math.round(0.12 * 25.4 * 1000) / 1000;
// Verified (2026-08-20, fix/print-cut-guides) against mtg.wiki's "Card" page
// (https://mtg.wiki/page/Card), the same source already backing CardWidthMM/CardHeightMM above:
// "They measure 63 mm x 88 mm ... The corners of the card are cut with a radius of 2.5 mm
// (approx. 1/10")". Corroborated verbatim by the mtg.fandom.com mirror of the same page. Other
// web sources round this to a generic "~3mm / 1/8-inch playing card" figure, but that's the
// industry-generic poker-card convention, not Magic's own documented die spec - 2.5mm is the
// correct, citable value and this constant was already set to it.
export const CornerRadiusMM = 2.5;

// 0.25mm renders as a hairline at true print scale. Shared by DisplaySheetSettings' own default
// and PagePreview's prop defaults so the exported PDF and the /display screen preview start out
// identical.
export const DEFAULT_CUT_LINE_COLOR = "#8ae234";
export const DEFAULT_CUT_LINE_LENGTH_MM = 3;
export const DEFAULT_CUT_LINE_THICKNESS_MM = 0.25;

/**
 * Proposal H D18 (docs/proposals/proposal-h-display-layout-spec.md) - the /display sheet's
 * default inter-card gutter: horizontal (col) touches (0mm, eases strip cutting), vertical (row)
 * separates (14.5mm, suits die cutters). D19 makes this user-editable (the right rail's Card
 * Spacing control); this is just the seed value a fresh project or a pre-D19 saved deck starts
 * at - `cardSpacingSlice.ts`'s initial state and `deckPayload.ts`'s legacy-payload backfill both
 * import this single constant so the two never drift apart from each other.
 */
export const DefaultCardSpacing: CardSpacingState = { row: 14.5, col: 0 };

/**
 * Proposal H D5 (docs/proposals/proposal-h-display-layout-spec.md) - the /display Page Setup's
 * default margin profile: Rear-feed (3mm top/bottom, 20mm trailing edge). Borderless renders the
 * largest theoretical bleed, but the ET-8500/8550 only actually loads Letter through its rear
 * tray for this print run's paper stock - a fresh project's on-screen sheet should match the
 * margins the printer really imposes, not the best case the hardware merely supports. The bleed
 * this profile actually grants is small (see marginProfiles.ts's own D6 table) and the new
 * granted-vs-requested readout (BleedGrantedReadout.tsx) is what makes that honest at a glance
 * instead of silently assuming full bleed. `marginProfileSlice.ts`'s initial state and
 * `deckPayload.ts`'s legacy-payload backfill both import this single constant, mirroring
 * `DefaultCardSpacing`'s own precedent immediately above.
 */
export const DefaultMarginProfile: MarginProfileState = {
  profile: "rearFeed",
};

export const ProjectName = "ProxyPrints";
export const MakePlayingCards = "MakePlayingCards.com";
export const MakePlayingCardsURL = "https://www.makeplayingcards.com";
export const NotMPC = "NotMPC.com";
export const NotMPCURL = "https://www.notmpc.com";
export const PringlePrints = "PringlePrints";
export const PringlePrintsURL = "https://pringleprints.ca";

// The desktop tool itself isn't a ProxyPrints-specific build - it's chilli-axe/mpc-autofill's
// own upstream project, unmodified in this fork (confirmed: no ProxyPrints-specific strings
// anywhere under desktop-tool/, and it never talks to our backend at all - it's a browser-
// automation tool driving MakePlayingCards.com directly from local files, so there's no
// backend-API coupling to diverge on). It reads the XML this site exports, and XML 2.0's
// additions are structurally invisible to its 1.0-era parser (see downloadXML.ts's header
// comment for the full compat evidence), so upstream's own releases work here as-is. Every
// link/button pointing at it should say so honestly rather than implying it's ours.
export const UpstreamDesktopTool = "the upstream mpc-autofill desktop tool";
export const UpstreamDesktopToolReleasesURL =
  "https://github.com/chilli-axe/mpc-autofill/releases/latest/";
export const UpstreamDesktopToolWikiURL =
  "https://github.com/chilli-axe/mpc-autofill/wiki/Desktop-Tool";
export const UpstreamDesktopToolSourceURL =
  "https://github.com/chilli-axe/mpc-autofill/tree/master/desktop-tool/";

// Community-maintained MTG artist directory - not affiliated with this project. See
// ArtistSupportLink.tsx (the M2 applet) and docs/features/artist-support-links.md for the full
// design: the applet prefers MTGAC's own authoritative pageUrl (from 2/artistExternalLinks/)
// over this deterministically-constructed URL, falling back to the constructed form only when
// no data is available (cache cold, or the artist isn't indexed) - see that endpoint's own
// backend docstring for why 8.2% of constructed URLs are wrong.
export const MTGArtistConnection = "MTG Artist Connection";
export const MTGArtistConnectionArtistBaseURL =
  "https://www.mtgartistconnection.com/artist/";
export const MTGArtistConnectionHomepageURL =
  "https://www.mtgartistconnection.com/";

export const Card: CardType = CardTypeSchema.Card;
export const Cardback: CardType = CardTypeSchema.Cardback;
export const Token: CardType = CardTypeSchema.Token;

export const SelectedImageSeparator = "@";
export const CardTypeSeparator = ":";
export const FaceSeparator = "// ";
export const FaceSeparatorRegexEscaped = "s//s";

// Mirrors the backend's `printing_metadata_import.SPLIT_STYLE_LAYOUTS` - Scryfall layouts whose
// physical card has exactly one face despite a " // "-joined `name` (e.g. "Fire // Ice"),
// textually identical to the manual front/back override syntax FaceSeparator implements above.
// A slot whose front resolves to one of these layouts has no second face to search
// independently - see listenerMiddleware.ts's own back-query suppression, which is what
// actually routes on this set (the parser itself no longer decides split-vs-directive at all;
// see processing.ts's removal of its old name-list lookup).
export const SplitStyleLayouts: ReadonlySet<string> = new Set([
  "split",
  "adventure",
  "flip",
  "aftermath",
]);

export const CardTypePrefixes: { [prefix: string]: CardType } = {
  "": Card,
  b: Cardback,
  t: Token,
};

export const ReversedCardTypePrefixes = Object.fromEntries(
  Object.keys(CardTypePrefixes).map((prefix: string) => [
    CardTypePrefixes[prefix],
    prefix.length > 0 ? prefix + CardTypeSeparator : prefix,
  ])
);

export const Front: Faces = "front";
export const Back: Faces = "back";

export const NavPillButtonHeight = 40; // pixels
export const NavUnderlineButtonHeight = 42; // pixels
export const ToggleButtonHeight = 38; // pixels
// Compact metrics for dense filter panels (grid-selector modal, search settings):
// Bootstrap sm control height so full-width toggle bars stay short in narrow panels.
// The 38px ToggleButtonHeight above stays the binding value for the
// /display rail's source toggles (SPEC-display-left-rail.md) - do not conflate them.
export const CompactToggleHeight = 31; // pixels
export const SourceToggleWidth = 88; // pixels
// The tag name behind the default mature-content exclusion. Must match the backend's
// cardpicker/constants.py NSFW constant - it's the same string filename-bracket tagging
// writes into Card.tags and the seeded sensitive tag uses (docs/features/moderation.md).
export const NSFW_TAG_NAME = "NSFW";
// The tag name marking non-official art borrowing an external property (a custom
// Warhammer proxy, for example) rather than original Magic art. Must match the backend's
// EXTERNAL_IP_TAG_NAME in cardpicker/reason_tags.py - the same string voting from the
// report button and the What's That Card feed writes into Card.tags.
export const EXTERNAL_IP_TAG_NAME = "external-ip";
export const NavbarHeight = 50; // pixels - aligns with the natural height of the navbar
export const RibbonHeight = 54; // pixels
export const NavbarLogoHeight = 40; // pixels
export const ContentMaxWidth = 1200; // pixels - aligns with bootstrap's large breakpoint
export const ModalHeaderHeight = 68.7;
export const ModalFooterHeight = 71;

export const MinimumDPI = 0;
export const MaximumDPI = 1500;
export const DPIStep = 50;

export const MaximumSize = 30; // megabytes
export const SizeStep = 1;

export const CSRFKey = "csrftoken";
export const SearchSettingsKey = "searchSettings";
export const FavoritesKey = "favorites";
export const BackendURLKey = "backendURL";
export const AnonymousIdKey = "anonymousId";
export const ManualOverridesKey = "manualOverrides";
// /display left-rail Sources accordion pinned-favourites strip (#353 seam, owner-directed
// 2026-07-23 - "implement the pin UI + localStorage persistence now," the account-tied "save as
// my defaults" version stays a disabled seam under #353). Local/device-only by design for this
// round - see docs/features/display-left-rail.md's "Pinned favourite sources" section for the
// full rationale on why this specific, narrow, owner-approved case is exempt from this repo's
// usual "no localStorage for state that should survive a clear-site-data test" rule.
export const PinnedSourcesKey = "pinnedSources";
// Per-anonymous_id set of card identifiers the visitor hid for themselves via a `hide=True`
// card report (issue #714 - see docs/features/moderation.md's hidden-card section). A prefix:
// the full storage key appends the anonymous_id, so a new anonymous identity starts with an
// empty hidden set (the server-side `HiddenCard` rows are scoped the same way).
export const HiddenCardIdsKey = "hiddenCardIds";
// /display right-rail print/export settings sections (Page setup, Cut lines & snip guides,
// Export, Print quality, View) - which of these `AutofillCollapse` sections the visitor last
// left expanded vs collapsed, persisted per-device so a chosen layout survives a reload.
export const RailSectionExpansionKey = "railSectionExpansion";

export const Brackets: Array<number> = [
  18, 36, 55, 72, 90, 108, 126, 144, 162, 180, 198, 216, 234, 396, 504, 612,
];

export const ProjectMaxSize: number = Brackets[Brackets.length - 1];

export enum QueryTags {
  BackendSpecific = "backendSpecific",
  SearchResults = "searchResults",
  SampleCards = "sampleCards",
  SavedDecks = "savedDecks",
  CryptoProfile = "cryptoProfile",
  DeckShares = "deckShares",
}

// docs/proposals/proposal-g-user-accounts-saved-decks.md §8 - matches the backend's
// SAVED_DECK_MIN_KDF_ITERATIONS default (MPCAutofill/MPCAutofill/settings.py) as the iteration
// count used for every NEW crypto profile this client creates. The backend independently
// enforces its own floor server-side regardless of what a client sends.
export const SavedDeckKdfIterations = 600_000;

export const S27: Cardstock = "(S27) Smooth";
export const S30: Cardstock = "(S30) Standard Smooth";
export const S33: Cardstock = "(S33) Superior Smooth";
export const M31: Cardstock = "(M31) Linen";
export const P10: Cardstock = "(P10) Plastic";
export const Cardstocks: Array<Cardstock> = [S27, S30, S33, M31, P10];

export const CardstockFoilCompatibility: { [cardstock in Cardstock]: boolean } =
  {
    [S27]: true,
    [S30]: true,
    [S33]: true,
    [M31]: true,
    [P10]: false,
  };

export const SearchResultsEndpointPageSize = 300;
export const CardEndpointPageSize = 1000;

export enum CSVHeaders {
  quantity = "Quantity",
  frontQuery = "Front",
  frontSelectedImage = "Front ID",
  backQuery = "Back",
  backSelectedImage = "Back ID",
}

export const ExploreDebounceMS = 700;
export const ExplorePageSize = 60;

export const SortByOptions: { [option in SortBy]: string } = {
  dateCreatedDescending: "Date Created (Newest-Oldest)",
  dateCreatedAscending: "Date Created (Oldest-Newest)",
  dateModifiedDescending: "Date Modified (Newest-Oldest)",
  dateModifiedAscending: "Date Modified (Oldest-Newest)",
  nameAscending: "Name (A-Z)",
  nameDescending: "Name (Z-A)",
};

export const FavouritesSourceKey = "__favorites__";
export const UnknownSourceKey = "__unknown__";
export const Unknown = "Unknown";
export interface Printing {
  expansionCode: string;
  collectorNumber: string;
}
