/**
 * "Who's That Planeswalker?" - a single-card-at-a-time queue for tagging which real-world
 * Scryfall printing a card image depicts. Walks through cards returned by
 * `2/printingTagQueue/` (which defaults to surfacing contested cards - conflicting votes
 * already cast - first, since those are the highest-value cards for a human to weigh in
 * on), one at a time, with the card's own image next to a grid of candidate Scryfall
 * renders for comparison. Deliberately standalone rather than sharing fetch/submit logic
 * with PrintingTagPicker.tsx (the quick-tag row used elsewhere): that component is already
 * shipped and covered by its own tests, and the two data-fetching flows differ enough
 * (auto-advance, skip, batched pagination) that factoring out a shared hook would add
 * indirection for both call sites rather than removing real duplication.
 */

import { keyframes } from "@emotion/react";
import styled from "@emotion/styled";
import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { getOrCreateAnonymousId } from "@/common/cookies";
import {
  PrintingCandidate,
  PrintingConsensusResponse,
} from "@/common/schema_types";
import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import { Spinner } from "@/components/Spinner";
import { AttributeVotingPanel } from "@/features/attributeVoting/AttributeVotingPanel";
import {
  APIGetPrintingCandidates,
  APIGetPrintingConsensus,
  APIGetPrintingTagQueue,
  APISubmitPrintingTag,
} from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

// "Who's That Pokemon?" style reveal: the card starts as a black silhouette with a "?" in
// the middle, holds for a beat, then fades to reveal the real art. The Scryfall candidate
// list is deliberately not rendered until this finishes (see `revealed` state below) - the
// whole point is to test recognition before handing over the answer options.
const revealAnimation = keyframes`
  0% { opacity: 1; }
  55% { opacity: 1; }
  100% { opacity: 0; }
`;

const RevealWrapper = styled.div`
  position: relative;
  overflow: hidden;
`;

const RevealOverlay = styled.div`
  position: absolute;
  inset: 0;
  background: black;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 4rem;
  font-weight: bold;
  animation: ${revealAnimation} 1.8s ease-in forwards;
  pointer-events: none;
`;

const FLAVOR_TEXT = [
  "Your spark ignites! On to the next mystery.",
  "A planeswalker's eye for detail - nicely done!",
  "The multiverse is a little better catalogued because of you.",
  "Sharper than a Sphinx's riddle. Next card incoming!",
  "That's the stuff legends are made of. Keep going!",
  "Another printing pinned down. Onward, planeswalker!",
  "You've got a good spark for this. Next!",
  "Precisely the kind of insight the Multiverse needs.",
  "Well walked, planeswalker. Here comes another.",
  "Your knowledge of the planes grows ever stronger.",
];

function randomFlavorText(): string {
  return FLAVOR_TEXT[Math.floor(Math.random() * FLAVOR_TEXT.length)];
}

export function PrintingTagQueue() {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);

  const [queueCards, setQueueCards] = useState<Array<CardDocument>>([]);
  const [currentIndex, setCurrentIndex] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pages, setPages] = useState<number>(1);
  const [hits, setHits] = useState<number>(0);
  const [loadingQueue, setLoadingQueue] = useState<boolean>(true);

  const [candidates, setCandidates] = useState<Array<PrintingCandidate>>([]);
  const [consensus, setConsensus] = useState<PrintingConsensusResponse | null>(
    null
  );
  const [loadingCard, setLoadingCard] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [flavorText, setFlavorText] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<boolean>(false);
  // whether the user has taken a printing-tag action (vote or no-match) on the *current*
  // card this session - the attribute-voting follow-up panel is step 2 after that action,
  // not shown alongside the initial printing picker on a card the user hasn't touched yet.
  const [votedThisCard, setVotedThisCard] = useState<boolean>(false);
  // guards the fetch effect below against React 18 Strict Mode's dev-time double-invoke,
  // which would otherwise append the same page's cards twice
  const fetchedPagesRef = React.useRef<Set<number>>(new Set());

  const currentCard = queueCards[currentIndex] ?? null;
  const queueExhausted =
    !loadingQueue && currentIndex >= queueCards.length && page >= pages;

  // fetch the next backend page once the locally-held batch runs out - never refetches
  // page 1, so a card the user already skipped/voted on this session won't reappear
  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    if (currentIndex < queueCards.length) {
      return; // still have locally-held cards to work through
    }
    if (queueCards.length > 0 && page >= pages) {
      return; // already fetched every available page - nothing more to ask for
    }
    const nextPage = queueCards.length === 0 ? 1 : page + 1;
    if (fetchedPagesRef.current.has(nextPage)) {
      return;
    }
    fetchedPagesRef.current.add(nextPage);
    setLoadingQueue(true);
    APIGetPrintingTagQueue(backendURL, nextPage)
      .then((response) => {
        setQueueCards((previous) => [...previous, ...response.cards]);
        setHits(response.hits);
        setPages(response.pages);
        setPage(nextPage);
      })
      .catch(() => undefined)
      .finally(() => setLoadingQueue(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, currentIndex, queueCards.length, page, pages]);

  // reset the reveal animation and attribute-voting step for each new card
  useEffect(() => {
    setRevealed(false);
    setVotedThisCard(false);
  }, [currentCard?.identifier]);

  useEffect(() => {
    if (backendURL == null || currentCard == null) {
      setCandidates([]);
      setConsensus(null);
      return;
    }
    setLoadingCard(true);
    setConsensus(null);
    Promise.all([
      APIGetPrintingCandidates(backendURL, currentCard.identifier),
      APIGetPrintingConsensus(backendURL, currentCard.identifier),
    ])
      .then(([candidatesResponse, consensusResponse]) => {
        setCandidates(candidatesResponse.results);
        setConsensus(consensusResponse);
      })
      .catch(() => {
        setCandidates([]);
        setConsensus(null);
      })
      .finally(() => setLoadingCard(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, currentCard?.identifier]);

  const advance = () => {
    setFlavorText(randomFlavorText());
    setCurrentIndex((previous) => previous + 1);
  };

  const skip = () => advance();

  const submit = (
    printingIdentifier: string | undefined,
    isNoMatch: boolean
  ) => {
    if (backendURL == null || currentCard == null) {
      return;
    }
    setSubmitting(true);
    APISubmitPrintingTag(
      backendURL,
      currentCard.identifier,
      getOrCreateAnonymousId(),
      printingIdentifier,
      isNoMatch
    )
      .then((response) => {
        setConsensus(response);
        setVotedThisCard(true);
        // if this vote itself resolved the printing (e.g. it broke a tie), there's nothing
        // left to ask about - advance immediately rather than showing the attribute panel.
        if (response.resolvedPrinting != null) {
          advance();
        }
      })
      .catch(() =>
        dispatch(
          setNotification([
            Math.random().toString(),
            {
              name: "Vote failed",
              message:
                "Something went wrong submitting your vote - please try again.",
              level: "error",
            },
          ])
        )
      )
      .finally(() => setSubmitting(false));
  };

  if (queueExhausted) {
    return (
      <div data-testid="planeswalker-queue-empty">
        <p className="text-primary">
          You&apos;re all caught up - no cards left to tag right now!
        </p>
        {flavorText != null && (
          <p
            className="text-muted"
            data-testid="planeswalker-queue-flavor-text"
          >
            {flavorText}
          </p>
        )}
      </div>
    );
  }

  return (
    <div data-testid="planeswalker-queue">
      <p className="text-primary">
        Still need a printing tagged: {hits} card{hits !== 1 && "s"}
      </p>
      {flavorText != null && (
        <p className="text-muted" data-testid="planeswalker-queue-flavor-text">
          {flavorText}
        </p>
      )}
      {currentCard == null ? (
        <div className="text-center py-4">
          <Spinner size={2} />
        </div>
      ) : (
        <div data-testid="planeswalker-queue-current-card">
          <Row className="g-4">
            <Col xs={12} md={4}>
              <RevealWrapper>
                <img
                  src={currentCard.mediumThumbnailUrl}
                  alt={currentCard.name}
                  style={{ width: "100%" }}
                />
                {!revealed && (
                  <RevealOverlay
                    data-testid="planeswalker-queue-reveal-overlay"
                    onAnimationEnd={() => setRevealed(true)}
                  >
                    ?
                  </RevealOverlay>
                )}
              </RevealWrapper>
              <div className="text-center mt-1">{currentCard.name}</div>
            </Col>
            <Col xs={12} md={8}>
              {!revealed || loadingCard ? (
                <div className="text-center py-4">
                  <Spinner size={2} />
                </div>
              ) : (
                <>
                  <div
                    className="mb-2"
                    data-testid="planeswalker-queue-consensus"
                  >
                    {consensus?.resolvedPrinting != null && (
                      <span>
                        Current consensus:{" "}
                        {consensus.resolvedPrinting.expansionCode.toUpperCase()}{" "}
                        {consensus.resolvedPrinting.collectorNumber}
                      </span>
                    )}
                    {consensus != null &&
                      consensus.resolvedPrinting == null &&
                      consensus.isNoMatch && (
                        <span>Current consensus: no matching printing</span>
                      )}
                    {consensus != null &&
                      consensus.resolvedPrinting == null &&
                      !consensus.isNoMatch && (
                        <span>
                          Not yet resolved
                          {consensus.voteTally.length > 0 ? " - contested" : ""}
                        </span>
                      )}
                  </div>
                  <Row className="g-2" xs={3} md={4}>
                    <Col>
                      <Button
                        variant={
                          consensus?.isNoMatch ? "success" : "outline-secondary"
                        }
                        className="w-100 p-1"
                        disabled={submitting}
                        onClick={() => submit(undefined, true)}
                      >
                        <img
                          src="/blank.png"
                          alt="None of these match"
                          style={{ width: "100%" }}
                        />
                        <div>No match</div>
                      </Button>
                    </Col>
                    {candidates.map((candidate) => (
                      <Col key={candidate.identifier}>
                        <Button
                          variant={
                            consensus?.resolvedPrinting?.identifier ===
                            candidate.identifier
                              ? "success"
                              : "outline-secondary"
                          }
                          className="w-100 p-1"
                          disabled={submitting}
                          onClick={() => submit(candidate.identifier, false)}
                        >
                          <img
                            src={candidate.mediumThumbnailUrl}
                            alt={`${candidate.expansionCode} ${candidate.collectorNumber}`}
                            style={{ width: "100%" }}
                          />
                          <div>
                            {candidate.expansionCode.toUpperCase()}{" "}
                            {candidate.collectorNumber}
                          </div>
                          <div className="text-muted small">
                            {candidate.artist}
                          </div>
                        </Button>
                      </Col>
                    ))}
                  </Row>
                  {votedThisCard &&
                    consensus?.resolvedPrinting == null &&
                    backendURL != null && (
                      <div className="mt-3">
                        <hr />
                        <AttributeVotingPanel
                          backendURL={backendURL}
                          cardIdentifier={currentCard.identifier}
                        />
                      </div>
                    )}
                  <div className="mt-3 d-flex gap-2">
                    <Button
                      variant="outline-secondary"
                      disabled={submitting}
                      onClick={skip}
                    >
                      Skip
                    </Button>
                    {votedThisCard && consensus?.resolvedPrinting == null && (
                      <Button variant="primary" onClick={advance}>
                        Continue
                      </Button>
                    )}
                  </div>
                </>
              )}
            </Col>
          </Row>
        </div>
      )}
    </div>
  );
}
