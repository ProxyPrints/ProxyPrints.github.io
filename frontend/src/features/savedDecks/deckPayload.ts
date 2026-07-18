/**
 * The plaintext shape encrypted wholesale (including its own `name`) as a saved deck's
 * ciphertext - see docs/proposals/proposal-g-user-accounts-saved-decks.md §8. Nothing in this
 * shape, or its serialized JSON string form, is ever sent to the server unencrypted.
 */

import {
  CardDocuments,
  FinishSettingsState,
  Project,
  ProjectMember,
  SlotProjectMembers,
} from "@/common/types";
import { SourceType } from "@/common/schema_types";

export const DECK_PAYLOAD_VERSION = 1;

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

export interface DeckPayloadV1 {
  version: 1;
  name: string;
  members: Array<DeckPayloadMember>;
  cardback: string | null;
  manualOverrides: Project["manualOverrides"];
  finishSettings: FinishSettingsState;
}

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

export function buildDeckPayload(
  name: string,
  project: Project,
  finishSettings: FinishSettingsState,
  cardDocuments: CardDocuments
): DeckPayloadV1 {
  const isDeviceLocal = (identifier: string | undefined): boolean =>
    identifier != null &&
    cardDocuments[identifier]?.sourceType === SourceType.LocalFile;

  return {
    version: DECK_PAYLOAD_VERSION,
    name,
    members: project.members.map((member: SlotProjectMembers) => ({
      front: toPayloadFace(member.front, isDeviceLocal),
      back: toPayloadFace(member.back, isDeviceLocal),
    })),
    cardback: project.cardback,
    manualOverrides: project.manualOverrides,
    finishSettings,
  };
}

/**
 * Canonical string form of a payload - the encryption plaintext, and also the dirty-check
 * comparison baseline (comparing two of these strings is cheaper and simpler than a deep
 * object comparison, and is exactly as precise since both sides go through this same function).
 */
export function serializeDeckPayload(payload: DeckPayloadV1): string {
  return JSON.stringify(payload);
}

export function parseDeckPayload(serialized: string): DeckPayloadV1 {
  const parsed = JSON.parse(serialized);
  if (parsed?.version !== DECK_PAYLOAD_VERSION) {
    throw new Error(
      `Unsupported saved deck payload version: ${parsed?.version}`
    );
  }
  return parsed as DeckPayloadV1;
}

export function countDeviceLocalSlots(payload: DeckPayloadV1): number {
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
export function projectFromDeckPayload(payload: DeckPayloadV1): {
  project: Omit<Project, "mostRecentlySelectedSlot">;
  finishSettings: FinishSettingsState;
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
    name: payload.name,
  };
}
