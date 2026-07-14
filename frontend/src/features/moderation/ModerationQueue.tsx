/**
 * The moderator-only review queue (docs/features/moderation.md): (card, sensitive-tag)
 * pairs awaiting a privileged co-sign, most-reported first. Mirrors GenericVoteQueue's
 * item/advance/lazy-pagination mechanics but is typed to the moderation endpoint's richer
 * item shape (report count + excerpts) and its actions are Approve/Reject - which are
 * ordinary submitTagVote calls sent with credentials so the backend records this
 * moderator's user on the vote and the pair resolves through the normal consensus pass.
 *
 * Distinct `moderation-queue*` testids rather than reusing "vote-queue" - see
 * docs/features/printing-tags.md's testid-collision lesson.
 *
 * The tab that mounts this is already gated on whoami, but hidden is not secured - the
 * backend 403s non-moderators, and this component renders that defensively too.
 */

import React, { useEffect, useState } from "react";
import Badge from "react-bootstrap/Badge";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { getOrCreateAnonymousId } from "@/common/cookies";
import { ModerationQueueItem } from "@/common/schema_types";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { Spinner } from "@/components/Spinner";
import { APIGetModerationQueue, APISubmitTagVote } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

export function ModerationQueue() {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const getTagDisplayName = useTagDisplayName();

  const [queueItems, setQueueItems] = useState<Array<ModerationQueueItem>>([]);
  const [currentIndex, setCurrentIndex] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pages, setPages] = useState<number>(1);
  const [hits, setHits] = useState<number>(0);
  const [loadingQueue, setLoadingQueue] = useState<boolean>(true);
  const [forbidden, setForbidden] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const fetchedPagesRef = React.useRef<Set<number>>(new Set());

  const currentItem = queueItems[currentIndex] ?? null;
  const queueExhausted =
    !loadingQueue && currentIndex >= queueItems.length && page >= pages;

  useEffect(() => {
    if (backendURL == null || forbidden) {
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
    APIGetModerationQueue(backendURL, nextPage)
      .then((response) => {
        setQueueItems((previous) => [...previous, ...response.items]);
        setHits(response.hits);
        setPages(response.pages);
        setPage(nextPage);
      })
      .catch((error) => {
        if (error?.status === 403) {
          setForbidden(true);
        }
      })
      .finally(() => setLoadingQueue(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, currentIndex, queueItems.length, page, pages, forbidden]);

  const advance = () => setCurrentIndex((previous) => previous + 1);

  const castModeratorVote = async (polarity: 1 | -1) => {
    if (backendURL == null || currentItem == null) {
      return;
    }
    setSubmitting(true);
    try {
      await APISubmitTagVote(
        backendURL,
        currentItem.card.identifier,
        getOrCreateAnonymousId(),
        currentItem.tagName,
        polarity,
        "include" // attach the moderator session so this vote is privileged
      );
      advance();
    } catch (error: any) {
      dispatch(
        setNotification([
          Math.random().toString(),
          {
            name: error?.name ?? "Vote failed",
            message:
              error?.message ?? "Something went wrong - please try again.",
            level: "error",
          },
        ])
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (forbidden) {
    return (
      <p className="text-primary" data-testid="moderation-queue-forbidden">
        You need moderator access to review this queue.
      </p>
    );
  }

  if (queueExhausted) {
    return (
      <div data-testid="moderation-queue-empty">
        <p className="text-primary">
          Nothing awaiting approval - the queue is clear!
        </p>
      </div>
    );
  }

  return (
    <div data-testid="moderation-queue">
      <p className="text-primary">
        Awaiting approval: {hits} item{hits !== 1 && "s"}
      </p>
      {currentItem == null || backendURL == null ? (
        <div className="text-center py-4">
          <Spinner size={2} />
        </div>
      ) : (
        <div data-testid="moderation-queue-current-item">
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
              <p>
                Should this card carry the tag{" "}
                <b>{getTagDisplayName(currentItem.tagName)}</b>?
              </p>
              <p>
                <Badge bg="danger" data-testid="moderation-queue-report-count">
                  {currentItem.reportCount} report
                  {currentItem.reportCount !== 1 && "s"}
                </Badge>
              </p>
              {currentItem.reportExcerpts.length > 0 && (
                <ul
                  className="text-muted small"
                  data-testid="moderation-queue-excerpts"
                >
                  {currentItem.reportExcerpts.map((excerpt, index) => (
                    <li key={index}>&ldquo;{excerpt}&rdquo;</li>
                  ))}
                </ul>
              )}
              <div className="d-flex gap-2 mt-3">
                <Button
                  variant="success"
                  disabled={submitting}
                  onClick={() => castModeratorVote(1)}
                  data-testid="moderation-queue-approve"
                >
                  Approve
                </Button>
                <Button
                  variant="danger"
                  disabled={submitting}
                  onClick={() => castModeratorVote(-1)}
                  data-testid="moderation-queue-reject"
                >
                  Reject
                </Button>
                <Button
                  variant="outline-secondary"
                  disabled={submitting}
                  onClick={advance}
                  data-testid="moderation-queue-skip"
                >
                  Skip
                </Button>
              </div>
            </Col>
          </Row>
        </div>
      )}
    </div>
  );
}
