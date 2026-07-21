/**
 * The plaintext shape encrypted wholesale (including its own `name`) as a saved deck's
 * ciphertext - see docs/proposals/proposal-g-user-accounts-saved-decks.md §8. Nothing in this
 * shape, or its serialized JSON string form, is ever sent to the server unencrypted.
 *
 * v2 (PR-6, "Revision tracking"): adds `revision`/`modifiedAt`, both PRIVATE fields living
 * inside the encrypted payload (never server-visible) that make an export/import round-trip
 * self-describing - see that section for the full rationale. This `version` field doubles as
 * the "PR-6/PR-7 shared versioning rule" the spec refers to: there is deliberately no
 * separately-named `formatVersion` field inside this private payload - PR-7's art-provenance
 * addition is expected to become v3 of this same counter, via the same upgrade-dispatch pattern
 * `parseDeckPayload` already uses below for v1 -> v2.
 */

import { DefaultCardSpacing } from "@/common/constants";
import {
  base64ToBytes,
  bytesToBase64,
  createDeckKey,
  decryptDeckPayload,
  encryptDeckPayload,
  unlockDeckKey,
  WrappedKey,
} from "@/common/savedDeckCrypto";
import {
  LoadDeckResponseKind,
  SavedDeckSummary,
  SourceType,
} from "@/common/schema_types";
import {
  CardDocuments,
  CardSpacingState,
  FinishSettingsState,
  Project,
  ProjectMember,
  SlotProjectMembers,
} from "@/common/types";

/** The current (latest) version every fresh save produces. Bump alongside adding a new
 * `DeckPayloadVN` interface and a new `case` in `parseDeckPayload`'s upgrade dispatch below. */
export const DECK_PAYLOAD_VERSION = 2;

export interface DeckPayloadMemberFace {
  query: ProjectMember["query"];
  selectedImage?: string;
  /**
   * True if `selectedImage` was sourced from a local file/folder at save time. The identifier
   * itself is device/browser-specific (a `FileSystemFileHandle` reference) and meaningless on
   * another device, so it's deliberately NOT serialized - only this flag survives, so a later
   * load elsewhere can show an honest "needs re-picking" placeholder (the card's existing
   * empty-slot/search-query UI) instead of a broken tile.
   */
  deviceLocal?: boolean;
}

export interface DeckPayloadMember {
  front: DeckPayloadMemberFace | null;
  back: DeckPayloadMemberFace | null;
}

/** The fields every version shares - everything a deck payload needs MINUS the version tag and
 * MINUS any version-specific bookkeeping (v2's `revision`/`modifiedAt`). Kept as its own type so
 * `buildDeckPayload`'s output (used for dirty-checking and previews, see below) never itself
 * carries `modifiedAt` - a fresh timestamp on every call would otherwise make an unchanged
 * project compare as "dirty" against its own last-saved baseline every single render. */
export interface DeckPayloadContent {
  name: string;
  members: Array<DeckPayloadMember>;
  cardback: Project["cardback"];
  manualOverrides: Project["manualOverrides"];
  finishSettings: FinishSettingsState;
  /**
   * Proposal H D18/D19 (docs/proposals/proposal-h-display-layout-spec.md) - the /display sheet's
   * inter-card gutter (mm), persisted per deck alongside `finishSettings`. Optional (rather than
   * required like `finishSettings`) purely so every EXISTING call site/fixture built before this
   * field existed keeps compiling unchanged - `buildDeckPayload` below always fills it with
   * `DefaultCardSpacing` when the caller omits it, and `projectFromDeckPayload`/
   * `deckContentForComparison` backfill the same default when reading an already-saved payload
   * that predates this field, so a legacy deck's dirty-check baseline and a freshly-rebuilt
   * payload agree on the same value rather than differing by the key's mere presence.
   */
  cardSpacing?: CardSpacingState;
}

export interface DeckPayloadV1 extends DeckPayloadContent {
  version: 1;
}

export interface DeckPayloadV2 extends DeckPayloadContent {
  version: 2;
  /** Incremented on every save of this same server-side row (never on a brand-new row - "Save
   * as new snapshot", and import, both always start a fresh row at revision 1). */
  revision: number;
  /** ISO 8601 timestamp of the save that produced this revision. */
  modifiedAt: string;
}

/** Any version this codebase can still read (never write - `buildDeckPayload` only ever
 * produces the latest, `DECK_PAYLOAD_VERSION`-tagged shape). */
export type DeckPayload = DeckPayloadV1 | DeckPayloadV2;

function toPayloadFace(
  face: ProjectMember | null,
  isDeviceLocal: (identifier: string | undefined) => boolean
): DeckPayloadMemberFace | null {
  if (face == null) {
    return null;
  }
  const deviceLocal = isDeviceLocal(face.selectedImage);
  return {
    query: face.query,
    selectedImage: deviceLocal ? undefined : face.selectedImage,
    ...(deviceLocal ? { deviceLocal: true } : {}),
  };
}

/**
 * Builds the CONTENT of a deck payload - no version tag, no revision/modifiedAt. Used for: the
 * Save modal's preview (local-file warning count), the dirty-check baseline (selectors.ts), and
 * as the input to `encryptDeckPayloadForSave` below, which stamps the version/revision/
 * modifiedAt fields on right before encryption.
 */
export function buildDeckPayload(
  name: string,
  project: Project,
  finishSettings: FinishSettingsState,
  cardDocuments: CardDocuments,
  // Optional (defaulted, not required) so every existing call site built before D19 - mostly
  // test fixtures - keeps compiling with no changes; every REAL call site (selectors.ts's dirty
  // check, SaveDeckModal, LoadSafetyModal) passes the live `selectCardSpacing` value explicitly.
  cardSpacing: CardSpacingState = DefaultCardSpacing
): DeckPayloadContent {
  const isDeviceLocal = (identifier: string | undefined): boolean =>
    identifier != null &&
    cardDocuments[identifier]?.sourceType === SourceType.LocalFile;

  return {
    name,
    members: project.members.map((member: SlotProjectMembers) => ({
      front: toPayloadFace(member.front, isDeviceLocal),
      back: toPayloadFace(member.back, isDeviceLocal),
    })),
    cardback: project.cardback,
    manualOverrides: project.manualOverrides,
    finishSettings,
    cardSpacing,
  };
}

/**
 * Canonical string form of a payload (or payload content) - the encryption plaintext, and also
 * the dirty-check comparison baseline (comparing two of these strings is cheaper and simpler
 * than a deep object comparison, and is exactly as precise since both sides go through this
 * same function).
 */
export function serializeDeckPayload(
  payload: DeckPayloadContent | DeckPayload
): string {
  return JSON.stringify(payload);
}

/**
 * Strips version/revision/modifiedAt bookkeeping from an already-parsed payload, leaving just
 * the content fields - the same shape `buildDeckPayload` returns. Used wherever a FULL decrypted
 * payload (e.g. freshly loaded from the server) needs to become a dirty-check baseline: without
 * this, the baseline would carry `modifiedAt`/`revision` that a freshly-rebuilt payload from the
 * live editor never has, so every load would immediately compare as "dirty".
 */
export function deckContentForComparison(
  payload: DeckPayload
): DeckPayloadContent {
  const { name, members, cardback, manualOverrides, finishSettings } = payload;
  return {
    name,
    members,
    cardback,
    manualOverrides,
    finishSettings,
    // Backfills the same default `buildDeckPayload` fills in for an omitted argument - a deck
    // saved before D19 has no `cardSpacing` key at all, but the dirty-check's "freshly rebuilt"
    // side always carries one (selectors.ts always passes the live redux value), so this baseline
    // must carry the SAME default or a legacy deck reads as dirty the instant it's loaded.
    cardSpacing: payload.cardSpacing ?? DefaultCardSpacing,
  };
}

/**
 * Parses a decrypted payload string, upgrading any older version forward to the latest shape
 * this codebase understands. Never throws on a recognised OLDER version - real, already-saved
 * decks exist at v1 today, and rejecting them the moment v2 ships would break every one of them.
 * `fallbackModifiedAt` (typically the deck's own server-side `updatedAt`) backfills v1's missing
 * `modifiedAt` - the closest honest proxy available, since v1 never tracked this itself.
 */
export function parseDeckPayload(
  serialized: string,
  fallbackModifiedAt?: string
): DeckPayloadV2 {
  const parsed = JSON.parse(serialized);
  switch (parsed?.version) {
    case 2:
      return parsed as DeckPayloadV2;
    case 1: {
      const v1 = parsed as DeckPayloadV1;
      return {
        ...v1,
        version: 2,
        // Never actually revised under v1's tracking (it didn't exist) - 0 so the very next real
        // save (revision 1) always reads as strictly newer than an untouched legacy row.
        revision: 0,
        modifiedAt: fallbackModifiedAt ?? new Date(0).toISOString(),
      };
    }
    default:
      throw new Error(
        `Unsupported saved deck payload version: ${parsed?.version}`
      );
  }
}

export function countDeviceLocalSlots(payload: {
  members: Array<DeckPayloadMember>;
}): number {
  return payload.members.reduce(
    (count, member) =>
      count +
      (member.front?.deviceLocal ? 1 : 0) +
      (member.back?.deviceLocal ? 1 : 0),
    0
  );
}

/**
 * Converts a decrypted payload back into the shapes `loadProject`/`loadFinishSettings` consume
 * directly. `deviceLocal` slots simply have no `selectedImage` here - the card grid already
 * renders that as an empty, re-pickable slot with the original search query intact.
 */
export function projectFromDeckPayload(payload: DeckPayload): {
  project: Omit<Project, "mostRecentlySelectedSlot">;
  finishSettings: FinishSettingsState;
  cardSpacing: CardSpacingState;
  name: string;
} {
  return {
    project: {
      members: payload.members.map((member, index) => ({
        id: `member-${index}`,
        front:
          member.front != null
            ? {
                query: member.front.query,
                selectedImage: member.front.selectedImage,
                selected: false,
              }
            : null,
        back:
          member.back != null
            ? {
                query: member.back.query,
                selectedImage: member.back.selectedImage,
                selected: false,
              }
            : null,
      })),
      nextMemberId: payload.members.length,
      cardback: payload.cardback,
      manualOverrides: payload.manualOverrides,
    },
    finishSettings: payload.finishSettings,
    // Same backfill as deckContentForComparison above - a deck saved before D19 has no
    // cardSpacing key, and both must agree on the same default or the freshly-loaded project
    // reads as dirty against its own baseline before any edit happens.
    cardSpacing: payload.cardSpacing ?? DefaultCardSpacing,
    name: payload.name,
  };
}

/** The base64 wire-format fields every save-deck request/response shares. */
export interface EncryptedDeckFields {
  ciphertext: string;
  ciphertextNonce: string;
  wrappedDek: string;
  wrappedDekNonce: string;
}

/**
 * Encrypts an ALREADY-FINALIZED payload (i.e. one that already carries its own version/
 * revision/modifiedAt, exactly as it should be persisted) verbatim, under a FRESH per-save DEK -
 * simpler than tracking and reusing an existing deck's DEK across updates, and the server has no
 * preference either way (post_save_deck just overwrites whatever ciphertext/wrappedDek it's
 * given, create or update). Used directly by deck-portability import (docs/proposals/.../PR-6):
 * an imported deck's `revision`/`modifiedAt` must survive re-encryption unchanged, since they're
 * what makes a later re-export/re-import round-trip self-describing.
 */
export async function encryptFinalizedDeckPayload(
  payload: DeckPayload,
  masterKey: CryptoKey
): Promise<EncryptedDeckFields> {
  const { dek, wrappedDek } = await createDeckKey(masterKey);
  const { ciphertext, nonce } = await encryptDeckPayload(
    serializeDeckPayload(payload),
    dek
  );
  return {
    ciphertext: bytesToBase64(ciphertext),
    ciphertextNonce: bytesToBase64(nonce),
    wrappedDek: bytesToBase64(wrappedDek.wrapped),
    wrappedDekNonce: bytesToBase64(wrappedDek.nonce),
  };
}

export interface EncryptDeckPayloadForSaveResult extends EncryptedDeckFields {
  revision: number;
  modifiedAt: string;
}

/**
 * The ordinary save path: stamps `content` with the latest version tag plus a freshly-bumped
 * `revision`/`modifiedAt` (docs/proposals/.../PR-6 "Revision tracking"), then encrypts. Pass
 * `previousRevision` as the row's last-known revision when overwriting the SAME server-side row
 * (an "update"); pass `null` for a brand-new row (a fresh deck, "Save as new snapshot", or an
 * imported-as-new deck that's being re-saved rather than persisted verbatim) so it starts at 1.
 */
export async function encryptDeckPayloadForSave(
  content: DeckPayloadContent,
  masterKey: CryptoKey,
  previousRevision: number | null
): Promise<EncryptDeckPayloadForSaveResult> {
  const revision = (previousRevision ?? 0) + 1;
  const modifiedAt = new Date().toISOString();
  const payload: DeckPayloadV2 = {
    ...content,
    version: DECK_PAYLOAD_VERSION,
    revision,
    modifiedAt,
  };
  const encrypted = await encryptFinalizedDeckPayload(payload, masterKey);
  return { ...encrypted, revision, modifiedAt };
}

export interface DecryptedSavedDeck {
  key: string;
  kind: LoadDeckResponseKind;
  name: string;
  createdAt: string;
  updatedAt: string;
  payload: DeckPayloadV2;
}

/** Reverses encryptDeckPayloadForSave/encryptFinalizedDeckPayload - unwraps the deck's DEK with
 * the given (already-unlocked) master key, then decrypts and parses its payload. Throws
 * (AES-GCM auth failure) on a wrong master key or any tampered ciphertext/wrapped-DEK byte.
 * `masterKey` need not be the LIVE session's master key - deck-portability import
 * (docs/proposals/.../PR-6) calls this with a bundle's own (possibly different-account) master
 * key to decrypt an imported entry before re-encrypting it under the current session's key. */
export async function decryptSavedDeckSummary(
  summary: SavedDeckSummary,
  masterKey: CryptoKey
): Promise<DecryptedSavedDeck> {
  const wrappedDek: WrappedKey = {
    wrapped: base64ToBytes(summary.wrappedDek),
    nonce: base64ToBytes(summary.wrappedDekNonce),
  };
  const dek = await unlockDeckKey(wrappedDek, masterKey);
  const plaintext = await decryptDeckPayload(
    base64ToBytes(summary.ciphertext),
    base64ToBytes(summary.ciphertextNonce),
    dek
  );
  const payload = parseDeckPayload(plaintext, summary.updatedAt);
  return {
    key: summary.key,
    kind: summary.kind,
    name: payload.name,
    createdAt: summary.createdAt,
    updatedAt: summary.updatedAt,
    payload,
  };
}
