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

import { getPrintingCandidateDataAttributes } from "@/common/cardDom";
import { getOrCreateAnonymousId } from "@/common/cookies";
import {
  PrintingCandidate,
  PrintingConsensusResponse,
} from "@/common/schema_types";
import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import { Spinner } from "@/components/Spinner";
import {
  STARBURST_INNER_COLOR,
  STARBURST_INNER_FRAMES,
  STARBURST_OUTER_COLOR,
  STARBURST_OUTER_FRAMES,
  STARBURST_VIEWBOX,
} from "@/features/printingTags/starburstShape";
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

// Same blue as ArtPlaceholder below (and the starburst itself) rather than a plain black
// box, so the "mystery card" reveal reads as one consistent visual language with the
// candidate grid's own "?" placeholders instead of a mismatched black flash. Black text
// (matching the page-wide font colour) checked against this blue: contrast ratio ~6.2:1,
// clearly better than the white it replaced (~3.4:1).
const RevealOverlay = styled.div`
  position: absolute;
  inset: 0;
  background: ${STARBURST_OUTER_COLOR};
  color: black;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 4rem;
  font-weight: bold;
  animation: ${revealAnimation} 1.8s ease-in forwards;
  pointer-events: none;
`;

// The card, and the starburst behind it, stay glued to the viewport as the page scrolls
// (position: sticky) rather than scrolling away with the rest of the page. "top" is set via
// inline style (see useStickyTop below) to wherever the panel naturally rendered when it
// first mounted, rather than a fixed offset - so it pins at its own original location on
// the page and never visibly jumps to a different spot once scrolling starts, it just stops
// moving exactly where it already was.
//
// z-index: -1 here (not just on BurstSvg) is deliberate and easy to get backwards: a sticky
// element always establishes its own stacking context, and *any* positioned descendant -
// even at the default z-index: auto - paints in front of plain, non-positioned in-flow
// siblings (the CSS spec's stacking order puts positioned content ahead of ordinary flow
// content, independent of DOM order or z-index value). Left at the default, that meant the
// whole panel - including the burst bleeding out of it - painted on top of the "Who's That
// Planeswalker?" heading and the candidate grid's plain text/borders, hiding them. Pushing
// CardPanel itself to a negative stack level is what actually fixes that (giving BurstSvg
// alone a negative z-index only reorders it against its own siblings *inside* CardPanel,
// it can't reach past the sticky boundary). The two columns never overlap horizontally at
// any breakpoint this page uses (side-by-side on desktop, stacked full-width on mobile), so
// this can't accidentally bury the actual card art behind the candidate grid - only the
// burst's intentional bleed into that space is affected.
const CardPanel = styled.div`
  position: sticky;
  top: 0;
  z-index: -1;
`;

// Measures how far the panel naturally sits below the top of its scrolling ancestor (see
// ContentContainer in Layout.tsx - the app's content area is a fixed-position, internally
// scrolling box, not the normal document body) right after it mounts, and uses that as the
// sticky "top" offset. Re-measures whenever the subject card changes (a new card can nudge
// the layout by a few px - e.g. flavor text length), so each card pins at wherever it
// actually rendered rather than an offset carried over from a previous card. Runs in a
// plain useEffect, not useLayoutEffect - the measured value only matters once the user
// scrolls far enough for sticky to engage, so there's nothing to flash before it settles,
// and useLayoutEffect warns during Next's static export (no DOM on the server).
function useStickyTop(deps: React.DependencyList): {
  ref: React.RefObject<HTMLDivElement>;
  top: number | null;
} {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [top, setTop] = useState<number | null>(null);

  useEffect(() => {
    const panel = ref.current;
    if (panel == null) {
      return;
    }
    let scrollParent: HTMLElement | null = panel.parentElement;
    while (
      scrollParent != null &&
      !["scroll", "auto"].includes(
        window.getComputedStyle(scrollParent).overflowY
      )
    ) {
      scrollParent = scrollParent.parentElement;
    }
    if (scrollParent == null) {
      return;
    }
    const panelRect = panel.getBoundingClientRect();
    const scrollRect = scrollParent.getBoundingClientRect();
    setTop(panelRect.top - scrollRect.top + scrollParent.scrollTop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ref, top };
}

// Sized and centred purely with CSS (percentage width + aspect-ratio, both relative to
// CardPanel's own box) rather than a JS measurement - it scales naturally with the card's
// own responsive width at every breakpoint, and travels with CardPanel automatically under
// sticky scrolling with no extra code.
const BurstSvg = styled.svg`
  position: absolute;
  top: 50%;
  left: 50%;
  width: 340%;
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
  z-index: -1;
  pointer-events: none;
`;

const STARBURST_FRAME_INTERVAL_MS = 150;

// Cycles through the precomputed jagged frames (see starburstShape.ts) to reproduce the
// reference gif's flicker. Always starts at frame 0 and only starts advancing inside
// useEffect (client-only, post-mount), so server-rendered and first-client-render markup
// stay identical - no hydration mismatch. Skips animating entirely under
// prefers-reduced-motion.
function useStarburstFrame(frameCount: number): number {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const id = setInterval(() => {
      setFrame((previous) => (previous + 1) % frameCount);
    }, STARBURST_FRAME_INTERVAL_MS);
    return () => clearInterval(id);
  }, [frameCount]);

  return frame;
}

// Zooms the thumbnail in on hover, rather than the whole button, so the border/label stay
// put and only the artwork itself grows. Deliberately left uncropped (no overflow: hidden)
// so the enlarged art is fully visible rather than cut off at the original box edge -
// raised above its siblings on hover so it doesn't render underneath the neighbouring grid
// cells it now overlaps.
const ZoomableThumbnail = styled.div`
  position: relative;
  z-index: 0;

  img {
    transition: transform 0.15s ease-out;
  }

  &:hover {
    z-index: 2;
  }

  &:hover img {
    transform: scale(1.6);
  }
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

// Real Magic card ratio (63mm x 88mm), matching the print-ready `.ratio-7x5` convention
// already used elsewhere (custom.css) - reserves each thumbnail's box up front via CSS
// alone, so an image resolving its intrinsic size late over the network can't reflow the
// page (the starburst is centred on the card's own box - see CardPanel - so any unreserved
// reflow here would visibly resize the burst along with it).
const CARD_ASPECT_RATIO = "63 / 88";

// Shared "mystery card" backdrop for every Scryfall art box in the candidate grid - reuses
// the starburst's own blue so it reads as one consistent visual language against the orange
// background rather than a mismatched placeholder colour. Candidates render their real
// artwork on top of this (so a slow-loading image transitions from a blue "?" card into the
// real art instead of a blank flash), and it's also the entire visual for the "No match"
// option, which has no real artwork to show at all - replacing the old black
// "Card Not Found :(" placeholder image.
const ArtPlaceholder = styled.div`
  position: relative;
  width: 100%;
  aspect-ratio: ${CARD_ASPECT_RATIO};
  background: ${STARBURST_OUTER_COLOR};
  /* Deliberately no overflow: hidden here - object-fit: cover below already keeps the image
     contained within this box on its own (it crops the underlying image content to fit,
     it doesn't make the <img> element itself overflow), and clipping at this level was
     silently re-breaking ZoomableThumbnail's hover-zoom (added in a previous round
     specifically *without* overflow: hidden, so the enlarged art could pop out uncropped) -
     since ArtPlaceholder wraps ZoomableThumbnail, its own overflow: hidden clipped the zoom
     right back down to this box's edge, reading as a hard rectangular cut through the
     enlarged artwork. */

  &::before {
    content: "?";
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: rgba(0, 0, 0, 0.5);
    font-size: 3rem;
    font-weight: bold;
  }

  img {
    position: relative;
    z-index: 1;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
`;

// Bootstrap's `outline-secondary` border doesn't scale with the hover-zoomed thumbnail
// inside it (see ZoomableThumbnail) - it stays put as a stationary frame while the art
// visibly grows past it, breaking the effect - so it's dropped entirely (`border-0`,
// applied at each call site below) and this component only needs to own the "highlighted"
// look. Bootstrap's green `success` variant clashed with the page's blue "mystery" motif
// established elsewhere (ArtPlaceholder, RevealOverlay, the starburst itself), so "this is
// the resolved consensus pick" is now a solid fill in that same blue instead - there's no
// built-in Bootstrap variant in this exact shade, hence the custom class rather than
// swapping to `variant="primary"`. Black text (matching the page-wide font colour) checked
// against it: ~6.2:1 contrast, clearly better than white's ~3.4:1; the artist line below it
// is Bootstrap's `.text-muted` grey, which nearly disappeared against this blue, so it's
// darkened to translucent black specifically inside `.highlighted` (needs `!important` -
// Bootstrap's own text-color utilities are declared `!important`, so nothing else can win
// against it).
//
// Bootstrap's own `.btn-outline-secondary:hover` background (a flat grey) was still
// showing through around the card on hover, which read as a mismatched grey frame against
// the page's blue theme. Per direct request, that hover highlight is now a scaled-down copy
// of the page's own starburst (HoverBurst below) instead of a flat colour - `position:
// relative` + `z-index: 0` here gives HoverBurst's `z-index: -1` a local stacking context
// to sit behind ArtPlaceholder/the text without leaking out to sit behind this button's
// *siblings* in the grid too (the same mechanism as CardPanel/BurstSvg on the page-level
// starburst - see the comment there for the underlying CSS stacking rule).
const CandidateButton = styled(Button)`
  position: relative;
  z-index: 0;
  overflow: visible;

  &:hover,
  &:focus {
    background-color: transparent !important;
  }

  &:hover .hover-burst {
    opacity: 1;
    transform: translate(-50%, -50%) scale(1);
  }

  &.highlighted {
    background-color: ${STARBURST_OUTER_COLOR};
    color: #000000;
  }

  &.highlighted .text-muted {
    color: rgba(0, 0, 0, 0.65) !important;
  }
`;

// A smaller copy of the same starburst geometry, driven by the same shared
// `starburstFrame` state as the page-level burst (see useStarburstFrame below) rather than
// a frame of its own, so a zoomed card's highlight visibly flickers/moves in lockstep with
// the big one on the left instead of holding still - every instance ticks over together
// regardless of which card is actually hovered, since only the hovered one is visible
// (opacity 0 otherwise) and re-rendering a handful of invisible polygons every frame is
// cheap. Centred on and scaled up from the button's own box, the same way the page-level
// burst is centred on the subject card. Faded/scaled in via CSS on CandidateButton's
// `:hover` above rather than JS state, so nothing needs to track which card is hovered.
const HoverBurst = styled.svg`
  position: absolute;
  top: 50%;
  left: 50%;
  width: 331.2%;
  aspect-ratio: 1;
  transform: translate(-50%, -50%) scale(0.75);
  opacity: 0;
  transition: opacity 0.18s ease-out, transform 0.18s ease-out;
  pointer-events: none;
  z-index: -1;
`;

export function PrintingTagQueue() {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const starburstFrame = useStarburstFrame(STARBURST_OUTER_FRAMES.length);

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
  // guards the fetch effect below against React 18 Strict Mode's dev-time double-invoke,
  // which would otherwise append the same page's cards twice
  const fetchedPagesRef = React.useRef<Set<number>>(new Set());

  const currentCard = queueCards[currentIndex] ?? null;
  const queueExhausted =
    !loadingQueue && currentIndex >= queueCards.length && page >= pages;
  const { ref: cardPanelRef, top: stickyTop } = useStickyTop([
    currentCard?.identifier,
  ]);

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

  // reset the reveal animation for each new card
  useEffect(() => {
    setRevealed(false);
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
      .then(() => advance())
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
              <CardPanel
                ref={cardPanelRef}
                style={stickyTop != null ? { top: stickyTop } : undefined}
              >
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
                    src={currentCard.mediumThumbnailUrl}
                    alt={currentCard.name}
                    style={{ width: "100%", aspectRatio: CARD_ASPECT_RATIO }}
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
              </CardPanel>
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
                      <CandidateButton
                        variant="outline-secondary"
                        className={`w-100 p-1 border-0${
                          consensus?.isNoMatch ? " highlighted" : ""
                        }`}
                        disabled={submitting}
                        onClick={() => submit(undefined, true)}
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
                    {candidates.map((candidate) => (
                      <Col key={candidate.identifier}>
                        <CandidateButton
                          variant="outline-secondary"
                          className={`w-100 p-1 border-0${
                            consensus?.resolvedPrinting?.identifier ===
                            candidate.identifier
                              ? " highlighted"
                              : ""
                          }`}
                          disabled={submitting}
                          onClick={() => submit(candidate.identifier, false)}
                          {...getPrintingCandidateDataAttributes(
                            currentCard.name,
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
          </Row>
        </div>
      )}
    </div>
  );
}
