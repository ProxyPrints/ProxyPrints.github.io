/**
 * The unified "What's That Card?" question feed - replaces the old printing/artist/tag tab
 * switcher (PrintingTagQueue.tsx + GenericVoteQueue.tsx, both deleted alongside this file)
 * with a single `GET 2/questionFeed/`-driven stream of one question at a time, typed per
 * cardpicker.question_feed's three-tier ranked union. See docs/features/printing-tags.md's
 * questionFeed section and journal/2026-07-14-queue-question-feed-design.md for the full
 * design writeup (chip taxonomy grounding, layout rationale, starvation-risk tradeoff).
 *
 * Re-composition, not a rewrite: the sticky starburst card panel, reveal animation, and
 * candidate-grid mechanics are the exact same code as the old PrintingTagQueue, now shared
 * via cardPanel.tsx. ArtistVotePicker and QueueTagQuestion are reused directly for their
 * question types, unforked.
 */

import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { getPrintingCandidateDataAttributes } from "@/common/cardDom";
import { getOrCreateAnonymousId } from "@/common/cookies";
import {
  PrintingCandidate,
  QuestionFeedCounts,
  QuestionFeedItem,
} from "@/common/schema_types";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { SetIcon } from "@/components/SetIcon";
import { Spinner } from "@/components/Spinner";
import {
  AttributeChipPanel,
  hasAnyExplicitChip,
  initialChipStates,
} from "@/features/attributeChips/AttributeChipPanel";
import {
  ChipVoteState,
  filterCandidatesByChipStates,
  STANDALONE_CHIPS,
} from "@/features/attributeChips/attributeChips";
import { ArtistVotePicker } from "@/features/attributeVoting/ArtistVotePicker";
import { NoMatchReasonStrip } from "@/features/attributeVoting/NoMatchReasonStrip";
import { QueueTagQuestion } from "@/features/attributeVoting/QueueTagQuestion";
import {
  ArtPlaceholder,
  BurstSvg,
  CandidateButton,
  CARD_ASPECT_RATIO,
  CardPanel,
  HoverBurst,
  randomFlavorText,
  RevealOverlay,
  RevealWrapper,
  useStarburstFrame,
  useStickyTop,
  ZoomableThumbnail,
} from "@/features/printingTags/cardPanel";
import {
  STARBURST_INNER_COLOR,
  STARBURST_INNER_FRAMES,
  STARBURST_OUTER_COLOR,
  STARBURST_OUTER_FRAMES,
  STARBURST_VIEWBOX,
} from "@/features/printingTags/starburstShape";
import {
  APIGetQuestionFeed,
  APISubmitPrintingTag,
  APISubmitTagVote,
} from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

type FollowUp = "none" | "no-match-reason";

// Frontend and backend deploy independently (GitHub Pages vs. a separate Django API) - there's
// a real window where this frontend build can be live against a not-yet-deployed backend still
// returning the old `remainingEstimate: number` shape. TypeScript's `as QuestionFeedResponse`
// cast in api.ts can't catch that at runtime, so `counts` here is trusted-but-unverified -
// without this guard, `counts.confirmable`/`counts.total` on a raw number both resolve to
// `undefined`, rendering the literal string "undefined cards" instead of degrading gracefully.
function normalizeQuestionFeedCounts(
  raw: QuestionFeedCounts | number | null | undefined
): QuestionFeedCounts | null {
  if (raw == null) {
    return null;
  }
  if (typeof raw === "number") {
    // legacy shape - no tier breakdown available, so confirmable/contested fall back to 0
    // (never show a false "quick confirmations ready" headline) and fresh mirrors total.
    return { total: raw, confirmable: 0, contested: 0, fresh: raw };
  }
  return raw;
}

export function QuestionFeed() {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const starburstFrame = useStarburstFrame();

  const [item, setItem] = useState<QuestionFeedItem | null>(null);
  const [counts, setCounts] = useState<QuestionFeedCounts | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [caughtUp, setCaughtUp] = useState<boolean>(false);
  const [flavorText, setFlavorText] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [chipStates, setChipStates] = useState<Record<string, ChipVoteState>>(
    initialChipStates()
  );
  const [followUp, setFollowUp] = useState<FollowUp>("none");
  const [fetchToken, setFetchToken] = useState<number>(0);

  const { ref: cardPanelRef, top: stickyTop } = useStickyTop([
    item?.card.identifier,
    item?.type,
  ]);

  const fetchNext = () => setFetchToken((previous) => previous + 1);

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    setLoading(true);
    APIGetQuestionFeed(backendURL, getOrCreateAnonymousId())
      .then((response) => {
        setItem(response.item ?? null);
        setCounts(normalizeQuestionFeedCounts(response.remainingEstimate));
        setCaughtUp(response.item == null);
      })
      .catch(() => {
        setItem(null);
        setCaughtUp(true);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, fetchToken]);

  // reset per-question local state whenever a new item lands
  useEffect(() => {
    setRevealed(false);
    setChipStates(initialChipStates());
    setFollowUp("none");
  }, [item?.card.identifier, item?.type]);

  const advance = () => {
    setFlavorText(randomFlavorText());
    fetchNext();
  };

  const reportVoteFailed = () =>
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
    );

  // Selecting a candidate casts the printing vote plus one positive CardTagVote per
  // standalone attribute the candidate itself carries true - see the design doc's "Auto-tag
  // on selection" section for why this only covers the standalone chips (border/frame
  // exclusion groups aren't auto-derivable in v1). PrintingConfirmStrip is deliberately not
  // rendered anywhere in this flow - everything it used to manually confirm is now auto-cast
  // here instead.
  const selectCandidate = (
    candidate: PrintingCandidate | undefined,
    isNoMatch: boolean
  ) => {
    if (backendURL == null || item == null) {
      return;
    }
    setSubmitting(true);
    const anonymousId = getOrCreateAnonymousId();
    APISubmitPrintingTag(
      backendURL,
      item.card.identifier,
      anonymousId,
      candidate?.identifier,
      isNoMatch
    )
      .then(() => {
        if (candidate != null) {
          const autoTagChips = STANDALONE_CHIPS.filter((chip) =>
            chip.matches(candidate)
          );
          Promise.all(
            autoTagChips.map((chip) =>
              APISubmitTagVote(
                backendURL,
                item.card.identifier,
                anonymousId,
                chip.tagName,
                1
              )
            )
          ).catch(() => undefined); // best-effort - a failed auto-tag shouldn't block advancing
        }
        if (isNoMatch) {
          setFollowUp("no-match-reason");
        } else {
          advance();
        }
      })
      .catch(reportVoteFailed)
      .finally(() => setSubmitting(false));
  };

  const skip = () => advance();

  if (loading && item == null) {
    return (
      <div className="text-center py-4" data-testid="question-feed-loading">
        <Spinner size={2} />
      </div>
    );
  }

  if (caughtUp || item == null || backendURL == null) {
    return (
      <div data-testid="question-feed-empty">
        <p className="text-primary">
          You&apos;re all caught up - no cards left to work on right now!
        </p>
        {flavorText != null && (
          <p className="text-muted" data-testid="question-feed-flavor-text">
            {flavorText}
          </p>
        )}
      </div>
    );
  }

  const isCandidateType =
    item.type === "confirm_suggestion" || item.type === "identify_printing";
  const allCandidates = item.candidates ?? [];
  const visibleCandidates = filterCandidatesByChipStates(
    allCandidates,
    chipStates
  );
  const hiddenCount = allCandidates.length - visibleCandidates.length;
  const noMatchDisabled = !hasAnyExplicitChip(chipStates);

  // BurstSvg renders alongside (not inside) RevealWrapper deliberately - RevealWrapper has
  // overflow: hidden (it clips the silhouette-reveal animation to the card's own box), which
  // would also clip the burst's intentional bleed if it were a descendant instead of a
  // sibling. Both size themselves against whichever positioned ancestor contains them -
  // AttributeChipPanel's CardArea now, so the burst centers on and scales with the card's own
  // rendered width specifically, not the wider ring (card + flanking chip columns) around it.
  const cardImage = (
    <>
      <BurstSvg viewBox={STARBURST_VIEWBOX}>
        <polygon
          points={STARBURST_OUTER_FRAMES[starburstFrame]}
          fill={STARBURST_OUTER_COLOR}
        />
        <polygon
          points={STARBURST_INNER_FRAMES[starburstFrame]}
          fill={STARBURST_INNER_COLOR}
        />
      </BurstSvg>
      <RevealWrapper>
        <img
          src={item.card.mediumThumbnailUrl}
          alt={item.card.name}
          style={{ width: "100%", aspectRatio: CARD_ASPECT_RATIO }}
        />
        {!revealed && (
          <RevealOverlay
            data-testid="question-feed-reveal-overlay"
            onAnimationEnd={() => setRevealed(true)}
          >
            ?
          </RevealOverlay>
        )}
      </RevealWrapper>
      <div className="text-center mt-1">{item.card.name}</div>
    </>
  );

  // The card renders dead center with chips forming a ring around it (AttributeChipPanel's
  // ChipRing grid) rather than stacked above it - the starburst behind the whole assembly is
  // purely decorative (pointer-events: none throughout), so it never competes with any of
  // this for clicks regardless of how it visually bleeds.
  const cardPanel = (
    <CardPanel
      ref={cardPanelRef}
      style={stickyTop != null ? { top: stickyTop } : undefined}
    >
      {/* cardPanel is only ever rendered from the isCandidateType branch below - the
          artist/tag branch renders its own plain image directly, uninvolved with chips or the
          starburst. BurstSvg now lives inside `cardImage` itself (see above), not here, so it
          sizes against the card's own box rather than this whole ring. */}
      <AttributeChipPanel
        backendURL={backendURL}
        cardIdentifier={item.card.identifier}
        tagConfidence={item.tagConfidence ?? {}}
        chipStates={chipStates}
        onChipStatesChange={setChipStates}
        cardSlot={cardImage}
      />
    </CardPanel>
  );

  return (
    <div data-testid="question-feed">
      {counts != null && (
        <>
          {/* Headline leads with quick confirmations (tier 1 - an unresolved AI-suggested
              printing awaiting a one-tap human yes/no) since that's the easiest, fastest-to-
              clear category - falls back to the overall total once there's nothing quick left,
              rather than always showing the same undifferentiated "cards remaining" copy. */}
          <p className="text-primary" data-testid="question-feed-headline">
            {counts.confirmable > 0
              ? `${counts.confirmable} quick confirmation${
                  counts.confirmable !== 1 ? "s" : ""
                } ready`
              : `Still need help with: ${counts.total} card${
                  counts.total !== 1 ? "s" : ""
                }`}
          </p>
          <p className="text-muted small" data-testid="question-feed-subcounts">
            {counts.total} total &middot; {counts.contested} contested &middot;{" "}
            {counts.fresh} fresh
          </p>
        </>
      )}
      {flavorText != null && (
        <p className="text-muted" data-testid="question-feed-flavor-text">
          {flavorText}
        </p>
      )}
      <div data-testid="question-feed-current-item">
        <Row className="g-4">
          {isCandidateType ? (
            <>
              <Col xs={12} md={5}>
                {!revealed ? (
                  <div className="text-center py-4">
                    <Spinner size={2} />
                  </div>
                ) : (
                  <>
                    {item.type === "confirm_suggestion" &&
                      item.suggestedPrinting != null && (
                        <p data-testid="question-feed-suggestion-prompt">
                          Is it this one?{" "}
                          <SetIcon
                            expansionCode={item.suggestedPrinting.expansionCode}
                          />{" "}
                          {item.suggestedPrinting.expansionCode.toUpperCase()}{" "}
                          {item.suggestedPrinting.collectorNumber}
                        </p>
                      )}
                    {hiddenCount > 0 && (
                      <p
                        className="text-muted small"
                        data-testid="question-feed-hidden-count"
                      >
                        {hiddenCount} hidden by your tags -{" "}
                        <a
                          href="#"
                          data-testid="question-feed-clear-filters"
                          onClick={(event) => {
                            event.preventDefault();
                            setChipStates(initialChipStates());
                          }}
                        >
                          clear
                        </a>
                      </p>
                    )}
                    <Row className="g-2" xs={3} md={4}>
                      <Col>
                        <CandidateButton
                          variant="outline-secondary"
                          className="w-100 p-1 border-0"
                          disabled={submitting || noMatchDisabled}
                          title={
                            noMatchDisabled
                              ? "Describe what you see first"
                              : undefined
                          }
                          onClick={() => selectCandidate(undefined, true)}
                          data-testid="question-feed-no-match"
                        >
                          <HoverBurst
                            className="hover-burst"
                            viewBox={STARBURST_VIEWBOX}
                          >
                            <polygon
                              points={STARBURST_OUTER_FRAMES[starburstFrame]}
                              fill={STARBURST_OUTER_COLOR}
                            />
                            <polygon
                              points={STARBURST_INNER_FRAMES[starburstFrame]}
                              fill={STARBURST_INNER_COLOR}
                            />
                          </HoverBurst>
                          <ArtPlaceholder />
                          <div>No match</div>
                        </CandidateButton>
                      </Col>
                      {visibleCandidates.map((candidate) => (
                        <Col key={candidate.identifier}>
                          <CandidateButton
                            variant="outline-secondary"
                            className={`w-100 p-1 border-0${
                              item.type === "confirm_suggestion" &&
                              item.suggestedPrinting?.identifier ===
                                candidate.identifier
                                ? " highlighted"
                                : ""
                            }`}
                            disabled={submitting}
                            onClick={() => selectCandidate(candidate, false)}
                            {...getPrintingCandidateDataAttributes(
                              item.card.name,
                              candidate
                            )}
                          >
                            <HoverBurst
                              className="hover-burst"
                              viewBox={STARBURST_VIEWBOX}
                            >
                              <polygon
                                points={STARBURST_OUTER_FRAMES[starburstFrame]}
                                fill={STARBURST_OUTER_COLOR}
                              />
                              <polygon
                                points={STARBURST_INNER_FRAMES[starburstFrame]}
                                fill={STARBURST_INNER_COLOR}
                              />
                            </HoverBurst>
                            <ArtPlaceholder>
                              <ZoomableThumbnail>
                                <img
                                  src={candidate.mediumThumbnailUrl}
                                  alt={`${candidate.expansionCode} ${candidate.collectorNumber}`}
                                />
                              </ZoomableThumbnail>
                            </ArtPlaceholder>
                            <div>
                              <SetIcon
                                expansionCode={candidate.expansionCode}
                              />{" "}
                              {candidate.expansionCode.toUpperCase()}{" "}
                              {candidate.collectorNumber}
                            </div>
                            <div className="text-muted small">
                              {candidate.artist}
                            </div>
                          </CandidateButton>
                        </Col>
                      ))}
                    </Row>
                    {followUp === "no-match-reason" && (
                      <div className="mt-3">
                        <hr />
                        <NoMatchReasonStrip
                          backendURL={backendURL}
                          cardIdentifier={item.card.identifier}
                          onDone={advance}
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
                    </div>
                  </>
                )}
              </Col>
              {/* position + a non-auto z-index together give this column its own local
                  stacking context, containing CardPanel's z-index: -1 (see cardPanel.tsx) so
                  it can't escape and render the whole panel - chips included - unclickable
                  behind this sibling column at the hit-testing layer. position: relative
                  alone does NOT establish a stacking context - see
                  docs/features/printing-tags.md's Stage 7 section for the full story. */}
              <Col xs={12} md={7} style={{ position: "relative", zIndex: 0 }}>
                {cardPanel}
              </Col>
            </>
          ) : (
            <>
              <Col xs={12} md={7}>
                {item.type === "artist" && (
                  <>
                    <h6>Who&apos;s the artist?</h6>
                    <ArtistVotePicker
                      backendURL={backendURL}
                      cardIdentifier={item.card.identifier}
                      confidentlyKnownArtistName={
                        item.confidentlyKnownArtistName
                      }
                    />
                    <div className="mt-3">
                      <Button variant="outline-secondary" onClick={skip}>
                        Skip
                      </Button>
                    </div>
                  </>
                )}
                {item.type === "tag" && item.tagName != null && (
                  <QueueTagQuestion
                    backendURL={backendURL}
                    cardIdentifier={item.card.identifier}
                    tagName={item.tagName}
                    onAnswered={advance}
                  />
                )}
              </Col>
              <Col xs={12} md={5}>
                <img
                  src={item.card.mediumThumbnailUrl}
                  alt={item.card.name}
                  style={{ width: "100%" }}
                />
                <div className="text-center mt-1">{item.card.name}</div>
              </Col>
            </>
          )}
        </Row>
      </div>
    </div>
  );
}
