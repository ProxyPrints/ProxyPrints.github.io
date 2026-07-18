import { CardType as CardTypeSchema } from "@/common/schema_types";
import { Cardstock, CardType, Faces, SortBy } from "@/common/types";

export const CardWidthMM = 63;
export const CardHeightMM = 88;
// 36 pixels (each side) at 300 dpi -> 0.12 inches, convert to MM. ref: https://www.makeplayingcards.com/pops/faq-photo.html
export const BleedEdgeMM = Math.round(0.12 * 25.4 * 1000) / 1000;
export const CornerRadiusMM = 2.5;

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

export const Card: CardType = CardTypeSchema.Card;
export const Cardback: CardType = CardTypeSchema.Cardback;
export const Token: CardType = CardTypeSchema.Token;

export const SelectedImageSeparator = "@";
export const CardTypeSeparator = ":";
export const FaceSeparator = "// ";
export const FaceSeparatorRegexEscaped = "s//s";

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
// The tag name behind the default mature-content exclusion. Must match the backend's
// cardpicker/constants.py NSFW constant - it's the same string filename-bracket tagging
// writes into Card.tags and the seeded sensitive tag uses (docs/features/moderation.md).
export const NSFW_TAG_NAME = "NSFW";
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

export const Brackets: Array<number> = [
  18, 36, 55, 72, 90, 108, 126, 144, 162, 180, 198, 216, 234, 396, 504, 612,
];

export const ProjectMaxSize: number = Brackets[Brackets.length - 1];

export enum QueryTags {
  BackendSpecific = "backendSpecific",
  SearchResults = "searchResults",
  SampleCards = "sampleCards",
}

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
