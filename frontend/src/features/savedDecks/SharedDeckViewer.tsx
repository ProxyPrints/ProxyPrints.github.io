/**
 * Read-only render of a decrypted shared deck ("PR-5, post-v1: per-deck share links" - the
 * spec's own words: "Render is read-only"). Deliberately local-state only, not wired into the
 * app's Redux `project`/`cardDocuments` slices - a recipient of a share link never edits this
 * deck, so there's no need to route it through ProjectEditor's live, mutable state at all. Card
 * thumbnails are resolved via the same plain APIGetCards + getWorkerImageURL helpers the rest of
 * the app uses, just called directly rather than through the shared search-results cache.
 *
 * Editor-polish round, item 11 (EP11, SPEC-editor-polish.md §D.8/§D.9, amendment 3) - this is
 * the genuine "recipient of a shared deck" surface (docs/features/foreign-order-resilience.md's
 * own "Explicitly deferred" note: "SharedDeckViewer.tsx and any other read-only viewer were not
 * touched, so they simply don't synthesize orphan CardDocuments at all yet... Building that
 * opt-in UI is future work"). A face whose `selectedImage` is a real Google Drive file ID
 * (`isLikelyDriveFileId`, orphanCard.ts) but wasn't resolved by `APIGetCards` (unindexed by this
 * catalog - exactly Phase 1's own "orphan" definition) is an ORPHAN here too - deny-by-default
 * (per the deferred note's own ruling: "shared decks viewed by others deny-by-default behind an
 * explicit per-deck recipient opt-in with a reversible 'Hide' control"):
 *   - `useConsentToast` (`consent/*`, base `Promise<boolean>` contract UNTOUCHED per amendment 3)
 *     asks once, keyed `shared-deck-orphans:${shareId}` - PER-DECK (amendment 3(a): "yes"), so a
 *     second shared deck asks independently even in the same session/sessionStorage.
 *   - Declining (or dismissing - the base toast's own deny-by-default contract) leaves every
 *     orphan face showing the `🔒 External image hidden` placeholder (§D.8 `.cell.ext` tokens,
 *     adapted to this list-row layout rather than a sheet cell - this page has no `PagePreview`
 *     sheet to attach the literal `.cell.ext`/cue-suppression to).
 *   - The reversibility amendment 3(b) asks for lives OUTSIDE the toast entirely, in a persistent
 *     `.extbanner`-styled banner ("N external images hidden — Review"/"Hide") - a plain local
 *     `imagesRevealed` boolean the banner toggles directly, independent of the toast's own
 *     terminal accept/decline decision (which only ever asks once).
 * Deliberately NOT built: NO images are fetched by this component until `imagesRevealed` is
 * true (governing premise - nothing pre-fetched/cached before the recipient actually opts in).
 */

import styled from "@emotion/styled";
import React, { useEffect, useRef, useState } from "react";

import { getWorkerImageURL } from "@/common/image";
import {
  getOrphanSmallImageURL,
  isLikelyDriveFileId,
} from "@/common/orphanCard";
import { CardDocument, CardDocuments } from "@/common/types";
import { useConsentToast } from "@/features/consent/useConsentToast";
import {
  DeckPayloadMemberFace,
  DeckPayloadV2,
} from "@/features/savedDecks/deckPayload";
import { APIGetCards } from "@/store/api";

interface SharedDeckViewerProps {
  backendURL: string;
  name: string;
  sharedAt: string;
  // decryptSharedDeck (deckShare.ts) always upgrades to the latest payload shape (v2) before
  // handing it back - a recipient never sees a raw, un-upgraded v1 payload.
  payload: DeckPayloadV2;
  /** EP11 - the per-deck consent-key scope (amendment 3(a)); undefined only for a caller with
   * no real shareId in scope (defensively falls back to a shared, non-deck-specific key rather
   * than throwing - every real caller, SharedDeckPage.tsx, always has one). */
  shareId?: string;
}

// EP11 (SPEC-editor-polish.md §D.8 `.cell.ext`, adapted) - the hidden-orphan placeholder, same
// colour/border tokens as the sheet-cell idiom the spec names, in this list-row's own shape.
const HiddenOrphanBadge = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #141f2b;
  color: #8fa0b0;
  font-size: 11px;
  border: 1px dashed #46586a;
  padding: 4px 8px;
`;

// EP11 (§D.8 `.extbanner`, adapted from its sheet-overlay positioning to this page's own plain
// flow - there's no PagePreview sheet here to float over).
const ExtBanner = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(11, 21, 32, 0.95);
  color: #ebebeb;
  border: 1px solid #5bc0de;
  font-size: 11px;
  padding: 8px 10px;
  margin-bottom: 10px;
`;

const ExtBannerLink = styled.button`
  background: transparent;
  border: none;
  color: #5bc0de;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
  font: inherit;
`;

interface OrphanFaceInfo {
  identifier: string;
  standInName: string | null;
}

function isOrphanFace(
  face: DeckPayloadMemberFace,
  cardDocuments: CardDocuments
): OrphanFaceInfo | null {
  if (face.deviceLocal || face.selectedImage == null) {
    return null;
  }
  if (cardDocuments[face.selectedImage] != null) {
    return null;
  }
  if (!isLikelyDriveFileId(face.selectedImage)) {
    return null;
  }
  return { identifier: face.selectedImage, standInName: face.query.query };
}

function SlotFace({
  face,
  cardDocuments,
  imagesRevealed,
}: {
  face: DeckPayloadMemberFace | null;
  cardDocuments: CardDocuments;
  imagesRevealed: boolean;
}) {
  if (face == null) {
    return <span className="text-muted small">(empty)</span>;
  }
  const cardDocument: CardDocument | undefined =
    face.selectedImage != null ? cardDocuments[face.selectedImage] : undefined;
  if (face.deviceLocal) {
    return (
      <span className="text-muted small">
        {face.query.query ?? "(unnamed card)"} - from a local file, not
        available in a shared preview
      </span>
    );
  }
  if (cardDocument != null) {
    return (
      <div className="d-flex align-items-center gap-2">
        {/* eslint-disable-next-line @next/next/no-img-element -- external image-CDN URL, same
        precedent as QuestionFeed.tsx/PagePreview.tsx's plain <img> usage for these */}
        <img
          src={getWorkerImageURL(cardDocument, "small")}
          alt={cardDocument.name}
          width={80}
        />
        <span className="small">{cardDocument.name}</span>
      </div>
    );
  }
  // EP11 - a real, unindexed Google Drive identifier: an orphan (see this file's own module
  // comment). Governing premise - never even builds the direct-Google image URL until the
  // recipient has actually opted in.
  const orphan = isOrphanFace(face, cardDocuments);
  if (orphan != null) {
    if (!imagesRevealed) {
      return (
        <HiddenOrphanBadge data-testid="shared-deck-hidden-orphan">
          🔒 External image hidden
        </HiddenOrphanBadge>
      );
    }
    const imageUrl = getOrphanSmallImageURL(orphan.identifier);
    return (
      <div className="d-flex align-items-center gap-2">
        {/* eslint-disable-next-line @next/next/no-img-element -- direct-from-Google URL, never
        routed through our own image-CDN Worker/R2 (orphanCard.ts's own module comment) */}
        <img
          src={imageUrl}
          alt={orphan.standInName ?? "Unindexed card"}
          width={80}
          data-testid="shared-deck-orphan-image"
        />
        <span className="small">
          {orphan.standInName ?? "Unindexed card"} (external, unverified)
        </span>
      </div>
    );
  }
  return (
    <span className="text-muted small">
      {face.query.query ?? "(unnamed card)"}
    </span>
  );
}

export function SharedDeckViewer({
  backendURL,
  name,
  sharedAt,
  payload,
  shareId,
}: SharedDeckViewerProps) {
  const [cardDocuments, setCardDocuments] = useState<CardDocuments>({});
  const [imagesRevealed, setImagesRevealed] = useState(false);
  const { element: consentElement, requestConsent } = useConsentToast();
  const consentRequestedRef = useRef(false);

  useEffect(() => {
    const identifiers = Array.from(
      new Set(
        payload.members
          .flatMap((member) => [member.front, member.back])
          .filter(
            (face): face is DeckPayloadMemberFace =>
              face != null && face.selectedImage != null && !face.deviceLocal
          )
          .map((face) => face.selectedImage as string)
      )
    );
    if (identifiers.length === 0) {
      return;
    }
    let cancelled = false;
    APIGetCards(backendURL, identifiers).then((results) => {
      if (!cancelled) {
        setCardDocuments(results);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, payload]);

  const orphanCount = payload.members.reduce(
    (count, member) =>
      count +
      [member.front, member.back].filter(
        (face) => face != null && isOrphanFace(face, cardDocuments) != null
      ).length,
    0
  );

  // EP11 - asks once per deck (amendment 3(a): keyed per-deck id), only once there's actually
  // something to ask about; `useConsentToast`'s own per-key sessionStorage means a decision
  // already made for THIS shareId this session never re-prompts (base contract, untouched).
  useEffect(() => {
    if (orphanCount === 0 || consentRequestedRef.current) {
      return;
    }
    consentRequestedRef.current = true;
    requestConsent({
      key: `shared-deck-orphans:${shareId ?? "unknown"}`,
      title: "External images in this shared deck",
      message:
        "This deck references card art hosted outside this catalog (an unverified external " +
        "source). Show these images now? You can change this later from the banner below.",
      acceptLabel: "Show images",
      declineLabel: "Keep hidden",
    }).then((accepted) => setImagesRevealed(accepted));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orphanCount, shareId]);

  return (
    <div>
      {consentElement}
      <h3>{name || "(untitled)"}</h3>
      <p className="text-muted small">Shared on {sharedAt}</p>
      {/* EP11 (§D.9 `.extbanner`, adapted) - the reversible Show/Hide, independent of the
          toast's own one-shot decision (amendment 3(b)). */}
      {orphanCount > 0 && (
        <ExtBanner data-testid="shared-deck-ext-banner">
          <span>
            {orphanCount} external image{orphanCount !== 1 ? "s" : ""}{" "}
            {imagesRevealed ? "shown" : "hidden"}
          </span>
          <ExtBannerLink
            onClick={() => setImagesRevealed((previous) => !previous)}
            data-testid="shared-deck-ext-banner-toggle"
          >
            {imagesRevealed ? "Hide" : "Review"}
          </ExtBannerLink>
        </ExtBanner>
      )}
      <ul className="list-unstyled">
        {payload.members.map((member, index) => (
          <li key={index} className="mb-2">
            <div className="d-flex gap-3">
              <SlotFace
                face={member.front}
                cardDocuments={cardDocuments}
                imagesRevealed={imagesRevealed}
              />
              {member.back != null && (
                <SlotFace
                  face={member.back}
                  cardDocuments={cardDocuments}
                  imagesRevealed={imagesRevealed}
                />
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
