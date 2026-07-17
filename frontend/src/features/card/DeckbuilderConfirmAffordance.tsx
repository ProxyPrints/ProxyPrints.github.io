/**
 * Level 0 of the "What's That Card?" funnel redesign (see the held funnel-proposal artifact,
 * PR #47's body) - an in-context confirmation affordance for slots imported with a canonical
 * printing ID (a specific-set/collector-number search query) whose chosen image hasn't yet
 * been human-confirmed for that printing. The deckbuilder's primary workflow is the
 * highest-quality confirmation source this catalogue has: the user has already declared
 * intent (the canonical ID), is already visually comparing art, and self-interestedly wants
 * the right printing - but this must never obstruct deck-building, so the affordance is a
 * small, inert badge until interacted with, never a modal or nag.
 *
 * Gate condition (approved Finding 4): reuses `getPrintingMatchLabel`'s own logic, inverted -
 * shown when the slot's search query names a specific printing but that printing isn't yet
 * the human-resolved consensus for the currently selected image. `canonicalCard` can't be
 * used directly for this - it's only populated once `printingTagStatus === Resolved`, exactly
 * the population this excludes.
 *
 * Density (approved decision 3): no cap on how many slots show this at once, but each is
 * genuinely inert (no color, no animation, no badge count) until interacted with, and once
 * explicitly resolved (YES/NO) never reappears for that specific image this session - see
 * `resolvedThisSession` below. No banners, no counters, no review mode in v1.
 */

import styled from "@emotion/styled";
import React, { useState } from "react";

import { errorToNotification, isRateLimited } from "@/common/apiErrors";
import { getOrCreateAnonymousId } from "@/common/cookies";
import { getPrintingMatchLabel } from "@/common/processing";
import { PrintingCandidate } from "@/common/schema_types";
import { SearchQuery, useAppDispatch, useAppSelector } from "@/common/types";
import { APIGetPrintingCandidates, APISubmitPrintingTag } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { selectCardDocumentByIdentifier } from "@/store/slices/cardDocumentsSlice";
import { setNotification } from "@/store/slices/toastsSlice";

// Module-level, in-memory "resolved this session" set - not persisted (a page reload starts
// fresh) and not a server-side flag. Keeping this local, rather than waiting for the vote to
// actually flip the card's own `printingTagStatus` to Resolved (which needs a consensus
// threshold, not just this one vote), is what makes "disappears on confirmation" achievable
// without the deck task ever feeling audited by a slow-to-update global state.
const resolvedThisSession = new Set<string>();

const Badge = styled.button`
  border: 1px solid rgba(0, 0, 0, 0.25);
  border-radius: 50%;
  width: 1.4rem;
  height: 1.4rem;
  line-height: 1;
  padding: 0;
  font-size: 0.75rem;
  background: rgba(13, 110, 253, 0.08);
  color: inherit;
`;

const Row = styled.div`
  display: flex;
  align-items: center;
  gap: 0.35rem;
  justify-content: center;
  margin-top: 0.25rem;
`;

const YesNoButton = styled.button`
  border: 1px solid rgba(0, 0, 0, 0.25);
  border-radius: 0.35rem;
  padding: 0.05rem 0.4rem;
  font-size: 0.75rem;
  font-weight: 700;
  background: transparent;
  color: inherit;

  &:disabled {
    opacity: 0.4;
  }
`;

const ComparePin = styled.div`
  position: absolute;
  z-index: 5;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  width: 120px;
  padding: 3px;
  border: 1px solid rgba(0, 0, 0, 0.25);
  border-radius: 0.35rem;
  background: var(--bs-body-bg, #fff);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);

  img {
    width: 100%;
    display: block;
  }
`;

const Wrapper = styled.div`
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 0.25rem;
`;

interface DeckbuilderConfirmAffordanceProps {
  /** The slot's currently selected image identifier - the (card, printing) pair being
   * confirmed, not the slot itself (swapping the image swaps which pair this refers to). */
  cardIdentifier: string;
  searchQuery: SearchQuery | undefined;
  /** Opens the same GridSelectorModal this slot already owns via its own
   * showGridSelector/setShowGridSelector state - NO is just another caller of that existing
   * setter, no new plumbing needed for it. */
  onOpenGridSelector: () => void;
}

export function DeckbuilderConfirmAffordance({
  cardIdentifier,
  searchQuery,
  onOpenGridSelector,
}: DeckbuilderConfirmAffordanceProps) {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const card = useAppSelector((state) =>
    selectCardDocumentByIdentifier(state, cardIdentifier)
  );

  const [resolved, setResolved] = useState<boolean>(() =>
    resolvedThisSession.has(cardIdentifier)
  );
  const [hasComparedOnce, setHasComparedOnce] = useState<boolean>(false);
  const [showPin, setShowPin] = useState<boolean>(false);
  const [referenceCandidate, setReferenceCandidate] =
    useState<PrintingCandidate | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);

  const isUnconfirmedCanonicalImport =
    searchQuery?.expansionCode != null &&
    getPrintingMatchLabel(
      searchQuery,
      card?.canonicalCard,
      card?.printingTagStatus
    ) == null;

  const triggerCompare = () => {
    setShowPin(true);
    if (
      hasComparedOnce ||
      backendURL == null ||
      searchQuery?.expansionCode == null
    ) {
      return;
    }
    setHasComparedOnce(true);
    APIGetPrintingCandidates(
      backendURL,
      cardIdentifier,
      `${searchQuery.expansionCode} ${searchQuery.collectorNumber ?? ""}`.trim()
    )
      .then((response) => {
        const match = response.results.find(
          (candidate) =>
            candidate.expansionCode.toUpperCase() ===
              searchQuery.expansionCode?.toUpperCase() &&
            (searchQuery.collectorNumber == null ||
              candidate.collectorNumber === searchQuery.collectorNumber)
        );
        setReferenceCandidate(match ?? null);
      })
      .catch(() => setReferenceCandidate(null));
  };

  const resolve = () => {
    resolvedThisSession.add(cardIdentifier);
    setResolved(true);
  };

  const submitYes = () => {
    if (backendURL == null || referenceCandidate == null) {
      return;
    }
    setSubmitting(true);
    APISubmitPrintingTag(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      referenceCandidate.identifier,
      false,
      "deckbuilder"
    )
      .then(() => resolve())
      .catch((error) => {
        if (isRateLimited(error)) {
          return;
        }
        dispatch(
          setNotification([
            Math.random().toString(),
            errorToNotification(error, {
              name: "Vote failed",
              message:
                "Something went wrong submitting your vote - please try again.",
            }),
          ])
        );
      })
      .finally(() => setSubmitting(false));
  };

  const handleNo = () => {
    // No targeted "this specific printing is wrong" vote exists in the schema -
    // CardPrintingTag is either a positive vote for one printing or a global is_no_match=True
    // (see MPCAutofill/cardpicker/models.py) - casting is_no_match here would incorrectly
    // claim no known printing matches this card image at all, which isn't what "wrong art for
    // this particular import" means. NO is pure navigation, no vote cast - the same choice
    // already made for the funnel's Level 1 NO/NOT SURE.
    resolve();
    onOpenGridSelector();
  };

  if (!isUnconfirmedCanonicalImport || resolved || card == null) {
    return null;
  }

  return (
    <Wrapper data-testid={`deckbuilder-confirm-${cardIdentifier}`}>
      {showPin && referenceCandidate != null && (
        <ComparePin data-testid="deckbuilder-compare-pin">
          <img
            src={referenceCandidate.mediumThumbnailUrl}
            alt={`Reference printing: ${referenceCandidate.expansionCode.toUpperCase()} ${
              referenceCandidate.collectorNumber
            }`}
          />
        </ComparePin>
      )}
      <Badge
        type="button"
        aria-label="Compare against the imported printing"
        data-testid="deckbuilder-confirm-badge"
        onMouseEnter={triggerCompare}
        onMouseLeave={() => setShowPin(false)}
        onClick={() => (showPin ? setShowPin(false) : triggerCompare())}
      >
        ?
      </Badge>
      <Row>
        <YesNoButton
          type="button"
          disabled={
            !hasComparedOnce || submitting || referenceCandidate == null
          }
          onClick={submitYes}
          data-testid="deckbuilder-confirm-yes"
        >
          Y
        </YesNoButton>
        <YesNoButton
          type="button"
          disabled={!hasComparedOnce || submitting}
          onClick={handleNo}
          data-testid="deckbuilder-confirm-no"
        >
          N
        </YesNoButton>
      </Row>
    </Wrapper>
  );
}
