/**
 * Read-only render of a decrypted shared deck ("PR-5, post-v1: per-deck share links" - the
 * spec's own words: "Render is read-only"). Deliberately local-state only, not wired into the
 * app's Redux `project`/`cardDocuments` slices - a recipient of a share link never edits this
 * deck, so there's no need to route it through ProjectEditor's live, mutable state at all. Card
 * thumbnails are resolved via the same plain APIGetCards + getWorkerImageURL helpers the rest of
 * the app uses, just called directly rather than through the shared search-results cache.
 */

import React, { useEffect, useState } from "react";

import { getWorkerImageURL } from "@/common/image";
import { CardDocument, CardDocuments } from "@/common/types";
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
}

function SlotFace({
  face,
  cardDocuments,
}: {
  face: DeckPayloadMemberFace | null;
  cardDocuments: CardDocuments;
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
}: SharedDeckViewerProps) {
  const [cardDocuments, setCardDocuments] = useState<CardDocuments>({});

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

  return (
    <div>
      <h3>{name || "(untitled)"}</h3>
      <p className="text-muted small">Shared on {sharedAt}</p>
      <ul className="list-unstyled">
        {payload.members.map((member, index) => (
          <li key={index} className="mb-2">
            <div className="d-flex gap-3">
              <SlotFace face={member.front} cardDocuments={cardDocuments} />
              {member.back != null && (
                <SlotFace face={member.back} cardDocuments={cardDocuments} />
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
