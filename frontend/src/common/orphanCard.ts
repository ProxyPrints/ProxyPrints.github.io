/**
 * Foreign-order resilience, Phase 1 (issue #324): rendering support for project slots whose
 * selected image is a Google Drive file ID this catalog has never indexed - e.g. a text or XML
 * import built against another mpc-autofill instance. An "orphan" card is addressed purely by
 * its Drive file ID and is never routed through our own image-CDN Worker or R2 bucket (that
 * cache stays catalog-only, per the issue's own Phase 1 bullet) - it's fetched direct from
 * Google's own image-serving domain, at the SAME two size tiers (400px/800px "height" params)
 * our own Worker already uses for its small/large thumbnail tiers (see
 * image-cdn/src/service/GoogleDriveService.ts's getLH4Params/getImageURL and
 * image-cdn/src/types.ts's ImageSizes) - same visual-size discipline the owner's 2026-07-22
 * resolution-tiering ruling requires, just built from this module instead of going through the
 * Worker. See docs/features/foreign-order-resilience.md for the full design.
 */

import { CardType, PrintingTagStatus } from "@/common/schema_types";
import { CardDocument } from "@/common/types";

/**
 * Owner-ratified allowlist (2026-07-22 security review comment on issue #324): validated before
 * ANY URL is built from an identifier that didn't come from our own indexing pipeline. A
 * rejection here is treated as a genuinely invalid identifier - it's never used to construct a
 * fetch, regardless of how plausible it looks otherwise.
 */
export const DriveFileIdPattern = /^[A-Za-z0-9_-]{10,200}$/;

export const isLikelyDriveFileId = (identifier: string): boolean =>
  DriveFileIdPattern.test(identifier);

/** Mirrors image-cdn/src/types.ts's ImageSizes exactly - the small/large thumbnail tiers an
 * orphan's editor-grid rendering must match in size discipline (owner ruling, 2026-07-22). */
const OrphanImageHeightPx = { small: 400, large: 800 } as const;

const DirectGoogleImageOrigin = "https://lh4.googleusercontent.com";

/**
 * Build a direct-from-Google image URL for an orphan identifier - NEVER routed through our
 * image-CDN Worker or R2 bucket (see module doc). `height` mirrors the Worker's own `=h<px>`
 * URL suffix (GoogleDriveService.getImageURL) for the small/large tiers; omitting it requests
 * the original, unresized file - the "full" tier, used only for PDF export, never the editor
 * grid (owner ruling: "the editor grid never requests it").
 *
 * The identifier is validated against `DriveFileIdPattern` before it ever reaches URL
 * construction, and is placed in the URL via the `URL` constructor (not string
 * interpolation) - only the size suffix, which is always one of two code-fixed values, is
 * appended as a literal.
 */
export const buildOrphanImageURL = (
  identifier: string,
  height: number | undefined
): string | undefined => {
  if (!isLikelyDriveFileId(identifier)) {
    return undefined;
  }
  const base = new URL(`/d/${identifier}`, DirectGoogleImageOrigin).toString();
  return height !== undefined ? `${base}=h${height}` : base;
};

/** The editor grid / preview tile tier - never used for PDF export. */
export const getOrphanSmallImageURL = (
  identifier: string
): string | undefined =>
  buildOrphanImageURL(identifier, OrphanImageHeightPx.small);

/** Unused today (no orphan-specific "large" surface yet), kept for parity with the catalog
 * path's own small/large/full tier triad. */
export const getOrphanLargeImageURL = (
  identifier: string
): string | undefined =>
  buildOrphanImageURL(identifier, OrphanImageHeightPx.large);

/** The PDF-export tier - original resolution, fetched only on an explicit export action, never
 * speculatively (owner ruling). */
export const getOrphanFullResolutionImageURL = (
  identifier: string
): string | undefined => buildOrphanImageURL(identifier, undefined);

// Built from character codes rather than a literal escape sequence in this source
// file, to avoid embedding raw control bytes in the repo - equivalent to
// /[\x00-\x1F\x7F]/g.
const ControlCharPattern = new RegExp(
  `[${String.fromCharCode(0)}-${String.fromCharCode(31)}${String.fromCharCode(
    127
  )}]`,
  "g"
);
const StandInNameMaxLength = 120;

/**
 * The stand-in name Phase 1 shows for an orphan (its slot's own XML/text search query) is
 * untrusted input from a file the user uploaded, not our own indexing pipeline - stripped of
 * control characters and length-capped before it reaches any display or `data-card-*` sink
 * (owner ruling, 2026-07-22 security review). React's JSX text nodes and `getCardDataAttributes`'s
 * DOM-API attribute assignment are already immune to injection either way (see
 * docs/features/card-dom-api.md), but the cap/strip still applies as defence in depth and to
 * keep a maliciously huge query string from bloating the DOM.
 */
export const sanitizeStandInName = (rawName: string): string => {
  const stripped = rawName.replace(ControlCharPattern, "").trim();
  return stripped.length > StandInNameMaxLength
    ? `${stripped.slice(0, StandInNameMaxLength)}…`
    : stripped;
};

/** Shown when an orphan's originating slot carried no usable query text (e.g. the reported
 * `b:null` back-face case - the foreign XML's own `<query>` element was empty). */
export const OrphanFallbackName = "Unindexed card";

/**
 * Synthesize a minimal CardDocument for an identifier the catalog has never indexed - Phase 1's
 * "on identifier lookup miss" step. Only ever called for identifiers that already passed
 * `isLikelyDriveFileId` (see cardDocumentsSlice.ts's fetchCardDocuments thunk, the sole caller).
 * Deliberately never sets `sourceType` - leaving it `undefined` is what keeps
 * `common/image.ts`'s bucket/Worker URL builders (which gate on
 * `sourceType === SourceType.GoogleDrive`) and `pdfImage.ts`'s source-type switch from ever
 * routing an orphan through our own CDN; `isOrphan: true` is the one field every consumer that
 * needs to special-case an orphan actually checks.
 */
export const synthesizeOrphanCardDocument = (
  identifier: string,
  standInQuery?: { name: string | null; cardType: CardType } | undefined
): CardDocument => {
  const rawName = standInQuery?.name;
  const sanitizedName =
    rawName != null && rawName.length > 0
      ? sanitizeStandInName(rawName)
      : undefined;
  return {
    cardType: standInQuery?.cardType ?? CardType.Card,
    dateCreated: "",
    dateModified: "",
    dpi: 0,
    extension: "",
    identifier,
    isOrphan: true,
    language: "EN",
    mediumThumbnailUrl: getOrphanLargeImageURL(identifier),
    name: sanitizedName ?? OrphanFallbackName,
    printingTagStatus: PrintingTagStatus.NoMatch,
    priority: 0,
    // Deliberately NOT the sanitized display name - this is the round-trip field
    // downloadXML.ts's createCardElement reads to rebuild the `<query>` element on re-export
    // (see docs/features/foreign-order-resilience.md's round-trip section). Falling back to the
    // fabricated OrphanFallbackName here would corrupt a re-exported file with text that was
    // never actually the user's search query.
    searchq: sanitizedName ?? "",
    size: 0,
    smallThumbnailUrl: getOrphanSmallImageURL(identifier),
    source: "",
    sourceId: -1,
    sourceName: "Your file",
    sourceVerbose: "Your file",
    tags: [],
  };
};

/**
 * Build orphan CardDocuments for every identifier in `identifiers` that looks like a real Drive
 * file ID - anything else is left out entirely (genuinely invalid, not an orphan candidate).
 * `standInQueryByIdentifier` supplies each identifier's own project-member query text/cardType
 * when known (see cardDocumentsSlice.ts), so the synthesized name and the XML round-trip's
 * `searchq` field reflect what the user actually asked for, not a generic placeholder.
 */
export const buildOrphanCardDocuments = (
  identifiers: Array<string>,
  standInQueryByIdentifier: Map<
    string,
    { name: string | null; cardType: CardType }
  > = new Map()
): { [identifier: string]: CardDocument } =>
  Object.fromEntries(
    identifiers
      .filter(isLikelyDriveFileId)
      .map((identifier) => [
        identifier,
        synthesizeOrphanCardDocument(
          identifier,
          standInQueryByIdentifier.get(identifier)
        ),
      ])
  );
