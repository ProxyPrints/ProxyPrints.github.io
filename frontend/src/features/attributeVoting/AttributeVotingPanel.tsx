/**
 * Follow-up voting panel shown once a card's printing-tag consensus hasn't resolved a
 * printing (see the two call sites - CardDetailedViewModal.tsx and PrintingTagQueue.tsx - for
 * the exact trigger condition, which is the same in both: `resolvedPrinting == null`, covering
 * both an explicit "no match" vote and a plain not-yet-resolved card). One panel, two
 * independently optional/skippable sections - artist and tags - rather than a modal chain.
 */

import React from "react";

import { ArtistVotePicker } from "@/features/attributeVoting/ArtistVotePicker";
import { TagVotePicker } from "@/features/attributeVoting/TagVotePicker";

interface AttributeVotingPanelProps {
  backendURL: string;
  cardIdentifier: string;
  /** Threaded straight through to ArtistVotePicker - see that component's own prop docstring. */
  confidentlyKnownArtistName?: string | null;
}

export function AttributeVotingPanel({
  backendURL,
  cardIdentifier,
  confidentlyKnownArtistName,
}: AttributeVotingPanelProps) {
  return (
    <div data-testid="attribute-voting-panel">
      <h6>Who&apos;s the artist?</h6>
      <ArtistVotePicker
        backendURL={backendURL}
        cardIdentifier={cardIdentifier}
        confidentlyKnownArtistName={confidentlyKnownArtistName}
      />
      <h6 className="mt-3">Do any of these tags apply?</h6>
      <TagVotePicker backendURL={backendURL} cardIdentifier={cardIdentifier} />
    </div>
  );
}
