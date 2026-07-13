/**
 * Shared queue shell for the artist and tag modes of the "What's That Card?" vote
 * queue, driven by the generalized `2/voteQueue/` endpoint. Printing mode is deliberately NOT
 * folded into this - it keeps using PrintingTagQueue.tsx and `2/printingTagQueue/` completely
 * unchanged (its own data source/shape, and its exact existing behavior is a hard constraint),
 * so this component only ever needs to handle the two new kinds, which do share one response
 * shape (`VoteQueueItem[]`) and can reasonably share one fetch/pagination/flavor-text
 * implementation instead of duplicating it twice.
 */

import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { Kind, VoteQueueItem } from "@/common/schema_types";
import { useAppSelector } from "@/common/types";
import { Spinner } from "@/components/Spinner";
import { ArtistVotePicker } from "@/features/attributeVoting/ArtistVotePicker";
import { QueueTagQuestion } from "@/features/attributeVoting/QueueTagQuestion";
import { APIGetVoteQueue } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";

const FLAVOR_TEXT = [
  "Your spark ignites! On to the next mystery.",
  "A collector's eye for detail - nicely done!",
  "The multiverse is a little better catalogued because of you.",
  "Sharper than a Sphinx's riddle. Next card incoming!",
  "That's the stuff legends are made of. Keep going!",
  "Another printing pinned down. Onward!",
  "You've got a good spark for this. Next!",
  "Precisely the kind of insight the Multiverse needs.",
  "Well spotted. Here comes another.",
  "Your knowledge of the planes grows ever stronger.",
];

function randomFlavorText(): string {
  return FLAVOR_TEXT[Math.floor(Math.random() * FLAVOR_TEXT.length)];
}

interface GenericVoteQueueProps {
  kind: typeof Kind.Artist | typeof Kind.Tag;
  label: string;
}

export function GenericVoteQueue({ kind, label }: GenericVoteQueueProps) {
  const backendURL = useAppSelector(selectRemoteBackendURL);

  const [queueItems, setQueueItems] = useState<Array<VoteQueueItem>>([]);
  const [currentIndex, setCurrentIndex] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pages, setPages] = useState<number>(1);
  const [hits, setHits] = useState<number>(0);
  const [loadingQueue, setLoadingQueue] = useState<boolean>(true);
  const [flavorText, setFlavorText] = useState<string | null>(null);
  const fetchedPagesRef = React.useRef<Set<number>>(new Set());

  const currentItem = queueItems[currentIndex] ?? null;
  const queueExhausted =
    !loadingQueue && currentIndex >= queueItems.length && page >= pages;

  // reset the locally-held queue whenever the kind changes (switching tabs)
  useEffect(() => {
    setQueueItems([]);
    setCurrentIndex(0);
    setPage(1);
    setPages(1);
    setHits(0);
    fetchedPagesRef.current = new Set();
  }, [kind]);

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    if (currentIndex < queueItems.length) {
      return;
    }
    if (queueItems.length > 0 && page >= pages) {
      return;
    }
    const nextPage = queueItems.length === 0 ? 1 : page + 1;
    if (fetchedPagesRef.current.has(nextPage)) {
      return;
    }
    fetchedPagesRef.current.add(nextPage);
    setLoadingQueue(true);
    APIGetVoteQueue(backendURL, kind, nextPage)
      .then((response) => {
        setQueueItems((previous) => [...previous, ...response.items]);
        setHits(response.hits);
        setPages(response.pages);
        setPage(nextPage);
      })
      .catch(() => undefined)
      .finally(() => setLoadingQueue(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, kind, currentIndex, queueItems.length, page, pages]);

  const advance = () => {
    setFlavorText(randomFlavorText());
    setCurrentIndex((previous) => previous + 1);
  };

  if (queueExhausted) {
    return (
      <div data-testid="vote-queue-empty">
        <p className="text-primary">
          You&apos;re all caught up - no cards left to tag right now!
        </p>
        {flavorText != null && (
          <p className="text-muted" data-testid="vote-queue-flavor-text">
            {flavorText}
          </p>
        )}
      </div>
    );
  }

  return (
    <div data-testid="vote-queue">
      <p className="text-primary">
        Still need {label}: {hits} card{hits !== 1 && "s"}
      </p>
      {flavorText != null && (
        <p className="text-muted" data-testid="vote-queue-flavor-text">
          {flavorText}
        </p>
      )}
      {currentItem == null || backendURL == null ? (
        <div className="text-center py-4">
          <Spinner size={2} />
        </div>
      ) : (
        <div data-testid="vote-queue-current-item">
          <Row className="g-4">
            <Col xs={12} md={4}>
              <img
                src={currentItem.card.mediumThumbnailUrl}
                alt={currentItem.card.name}
                style={{ width: "100%" }}
              />
              <div className="text-center mt-1">{currentItem.card.name}</div>
            </Col>
            <Col xs={12} md={8}>
              {kind === Kind.Tag && currentItem.tagName != null ? (
                <QueueTagQuestion
                  backendURL={backendURL}
                  cardIdentifier={currentItem.card.identifier}
                  tagName={currentItem.tagName}
                  onAnswered={advance}
                />
              ) : (
                <>
                  <ArtistVotePicker
                    backendURL={backendURL}
                    cardIdentifier={currentItem.card.identifier}
                    confidentlyKnownArtistName={
                      currentItem.card.canonicalArtist != null &&
                      !currentItem.card.canonicalArtistIsFromVoteOnly
                        ? currentItem.card.canonicalArtist.name
                        : null
                    }
                  />
                  <div className="mt-3">
                    <Button variant="outline-secondary" onClick={advance}>
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
