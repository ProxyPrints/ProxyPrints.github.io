/**
 * The moderator-only Drives sub-tab (docs/features/moderation.md): a browse-and-manage view
 * over Source rows, newest-first, for spotting and cleaning up a bad or spammy drive - the
 * second half of the Moderation tab alongside ReportsPanel.tsx. Unlike ReportsPanel's
 * one-at-a-time queue, this is a scannable list with "Load more" paging, since a moderator
 * here is browsing/comparing drives rather than answering a stream of individual questions.
 *
 * Two levels: the drive list itself (POST 2/moderationDrives/), and drilling into one drive's
 * individual cards (POST 2/moderationDriveCards/) to remove a specific card. Both a single
 * card and an entire drive can be permanently removed (POST 2/moderationRemoveCard/ and
 * .../moderationRemoveDrive/ respectively) - irreversible, confirmed via window.confirm since
 * there's no undo.
 */

import React, { useEffect, useState } from "react";
import Badge from "react-bootstrap/Badge";
import Button from "react-bootstrap/Button";
import ListGroup from "react-bootstrap/ListGroup";

import { Card, ModerationDriveItem, Source } from "@/common/schema_types";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { Spinner } from "@/components/Spinner";
import {
  APIGetModerationDriveCards,
  APIGetModerationDrives,
  APIRemoveModerationCard,
  APIRemoveModerationDrive,
} from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

function useModeratorErrorNotifier() {
  const dispatch = useAppDispatch();
  return (error: any, fallbackName: string) =>
    dispatch(
      setNotification([
        Math.random().toString(),
        {
          name: error?.name ?? fallbackName,
          message: error?.message ?? "Something went wrong - please try again.",
          level: "error",
        },
      ])
    );
}

function DriveCardList({
  source,
  onBack,
}: {
  source: Source;
  onBack: () => void;
}) {
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const notifyError = useModeratorErrorNotifier();

  const [cards, setCards] = useState<Array<Card>>([]);
  const [page, setPage] = useState<number>(0);
  const [pages, setPages] = useState<number>(1);
  const [hits, setHits] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [removingIdentifier, setRemovingIdentifier] = useState<string | null>(
    null
  );

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    setLoading(true);
    APIGetModerationDriveCards(backendURL, source.pk, 1)
      .then((response) => {
        setCards(response.cards);
        setHits(response.hits);
        setPages(response.pages);
        setPage(1);
      })
      .catch((error) => notifyError(error, "Failed to load cards"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL, source.pk]);

  const loadMore = () => {
    if (backendURL == null || page >= pages) {
      return;
    }
    setLoading(true);
    APIGetModerationDriveCards(backendURL, source.pk, page + 1)
      .then((response) => {
        setCards((previous) => [...previous, ...response.cards]);
        setPage(page + 1);
      })
      .catch((error) => notifyError(error, "Failed to load cards"))
      .finally(() => setLoading(false));
  };

  const removeCard = (card: Card) => {
    if (backendURL == null) {
      return;
    }
    if (
      !window.confirm(
        `Permanently remove "${card.name}" (${card.identifier}) from ${source.name}? This can't be undone.`
      )
    ) {
      return;
    }
    setRemovingIdentifier(card.identifier);
    APIRemoveModerationCard(backendURL, card.identifier)
      .then(() => {
        setCards((previous) =>
          previous.filter((c) => c.identifier !== card.identifier)
        );
        setHits((previous) => previous - 1);
      })
      .catch((error) => notifyError(error, "Failed to remove card"))
      .finally(() => setRemovingIdentifier(null));
  };

  return (
    <div data-testid="moderation-drives-card-list">
      <Button
        variant="outline-secondary"
        size="sm"
        className="mb-3"
        onClick={onBack}
        data-testid="moderation-drives-back"
      >
        &larr; Back to drives
      </Button>
      <p className="text-primary">
        {source.name}: {hits} card{hits !== 1 && "s"}
      </p>
      <ListGroup>
        {cards.map((card) => (
          <ListGroup.Item
            key={card.identifier}
            className="d-flex align-items-center gap-3"
            data-testid="moderation-drives-card-row"
          >
            <img
              src={card.smallThumbnailUrl}
              alt={card.name}
              style={{ width: "48px" }}
            />
            <div className="flex-grow-1">
              <div>{card.name}</div>
              <div className="text-muted small">{card.identifier}</div>
            </div>
            <Button
              variant="danger"
              size="sm"
              disabled={removingIdentifier === card.identifier}
              onClick={() => removeCard(card)}
              data-testid="moderation-drives-remove-card"
            >
              Remove
            </Button>
          </ListGroup.Item>
        ))}
      </ListGroup>
      {loading && (
        <div className="text-center py-3">
          <Spinner size={2} />
        </div>
      )}
      {!loading && page < pages && (
        <div className="text-center mt-3">
          <Button variant="outline-secondary" onClick={loadMore}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}

function DriveList({
  onSelectSource,
}: {
  onSelectSource: (source: Source) => void;
}) {
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const notifyError = useModeratorErrorNotifier();

  const [items, setItems] = useState<Array<ModerationDriveItem>>([]);
  const [page, setPage] = useState<number>(0);
  const [pages, setPages] = useState<number>(1);
  const [hits, setHits] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [forbidden, setForbidden] = useState<boolean>(false);
  const [removingSourceId, setRemovingSourceId] = useState<number | null>(null);

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    setLoading(true);
    APIGetModerationDrives(backendURL, 1)
      .then((response) => {
        setItems(response.items);
        setHits(response.hits);
        setPages(response.pages);
        setPage(1);
      })
      .catch((error) => {
        if (error?.status === 403) {
          setForbidden(true);
        } else {
          notifyError(error, "Failed to load drives");
        }
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendURL]);

  const loadMore = () => {
    if (backendURL == null || page >= pages) {
      return;
    }
    setLoading(true);
    APIGetModerationDrives(backendURL, page + 1)
      .then((response) => {
        setItems((previous) => [...previous, ...response.items]);
        setPage(page + 1);
      })
      .catch((error) => notifyError(error, "Failed to load drives"))
      .finally(() => setLoading(false));
  };

  const removeDrive = (item: ModerationDriveItem) => {
    if (backendURL == null) {
      return;
    }
    const totalCards = item.qtyCards + item.qtyCardbacks + item.qtyTokens;
    if (
      !window.confirm(
        `Permanently remove the drive "${item.source.name}" and all ${totalCards} of its cards? This can't be undone.`
      )
    ) {
      return;
    }
    setRemovingSourceId(item.source.pk);
    APIRemoveModerationDrive(backendURL, item.source.pk)
      .then(() => {
        setItems((previous) =>
          previous.filter((i) => i.source.pk !== item.source.pk)
        );
        setHits((previous) => previous - 1);
      })
      .catch((error) => notifyError(error, "Failed to remove drive"))
      .finally(() => setRemovingSourceId(null));
  };

  if (forbidden) {
    return (
      <p className="text-primary" data-testid="moderation-drives-forbidden">
        You need moderator access to manage drives.
      </p>
    );
  }

  return (
    <div data-testid="moderation-drives">
      <p className="text-primary">
        {hits} drive{hits !== 1 && "s"}, newest first
      </p>
      <ListGroup>
        {items.map((item) => (
          <ListGroup.Item
            key={item.source.pk}
            className="d-flex align-items-center gap-3"
            data-testid="moderation-drives-row"
          >
            <div className="flex-grow-1">
              <div>
                {item.source.name}{" "}
                <Badge bg="secondary">{item.source.sourceType}</Badge>
              </div>
              <div className="text-muted small">
                {item.qtyCards} card{item.qtyCards !== 1 && "s"},{" "}
                {item.qtyCardbacks} cardback{item.qtyCardbacks !== 1 && "s"},{" "}
                {item.qtyTokens} token{item.qtyTokens !== 1 && "s"}
              </div>
            </div>
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={() => onSelectSource(item.source)}
              data-testid="moderation-drives-view-cards"
            >
              View cards
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={removingSourceId === item.source.pk}
              onClick={() => removeDrive(item)}
              data-testid="moderation-drives-remove-drive"
            >
              Remove drive
            </Button>
          </ListGroup.Item>
        ))}
      </ListGroup>
      {loading && (
        <div className="text-center py-3">
          <Spinner size={2} />
        </div>
      )}
      {!loading && page < pages && (
        <div className="text-center mt-3">
          <Button variant="outline-secondary" onClick={loadMore}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}

export function DrivesPanel() {
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);

  return selectedSource == null ? (
    <DriveList onSelectSource={setSelectedSource} />
  ) : (
    <DriveCardList
      source={selectedSource}
      onBack={() => setSelectedSource(null)}
    />
  );
}
