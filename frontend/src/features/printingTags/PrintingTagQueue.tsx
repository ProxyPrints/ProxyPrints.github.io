/**
 * A paginated list of cards that still need a human to tag their printing (see
 * cardpicker.models.PrintingTagStatus on the backend) - clicking a card opens the same
 * CardDetailedViewModal used everywhere else in the app, which already has the
 * PrintingTagPicker wired in as of the quick-tag row added there.
 */

import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Row from "react-bootstrap/Row";

import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import { Spinner } from "@/components/Spinner";
import { MemoizedCard } from "@/features/card/Card";
import { APIGetPrintingTagQueue } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { showCardDetailedViewModal } from "@/store/slices/modalsSlice";

export function PrintingTagQueue() {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);

  const [page, setPage] = useState<number>(1);
  const [cards, setCards] = useState<Array<CardDocument>>([]);
  const [hits, setHits] = useState<number>(0);
  const [pages, setPages] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    setLoading(true);
    APIGetPrintingTagQueue(backendURL, page)
      .then((response) => {
        setCards((previous) =>
          page === 1 ? response.cards : [...previous, ...response.cards]
        );
        setHits(response.hits);
        setPages(response.pages);
      })
      .finally(() => setLoading(false));
    // intentionally only re-fetch when the page counter changes, not on every backendURL
    // reference change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  return (
    <>
      <p className="text-primary">
        Still need a printing tagged: {hits} card{hits !== 1 && "s"}
      </p>
      <Row xxl={6} lg={4} md={3} sm={2} xs={2} className="g-0">
        {cards.map((card) => (
          <MemoizedCard
            key={`printing-tag-queue-card-${card.identifier}`}
            maybeCardDocument={card}
            cardHeaderTitle={card.name}
            noResultsFound={false}
            cardOnClick={() => dispatch(showCardDetailedViewModal({ card }))}
          />
        ))}
      </Row>
      <br />
      {page < pages && (
        <div className="d-grid gap-0 mx-auto" style={{ maxWidth: "20%" }}>
          <Button onClick={() => setPage(page + 1)} disabled={loading}>
            {loading ? <Spinner size={1.5} /> : "Load More"}
          </Button>
        </div>
      )}
    </>
  );
}
