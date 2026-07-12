/**
 * Lets a user tag which Scryfall printing a card (an image in the catalogue) depicts, or
 * mark it as matching no known printing. Shared between the quick-tag row in
 * CardDetailedViewModal and the printing-tag review queue page - one implementation of
 * "search/browse candidate printings and pick one."
 *
 * Deliberately a flat, single-select list of thumbnails rather than the tree-select widget
 * used elsewhere (CanonicalCardFilter.tsx) for filtering: that component is built for
 * multi-select over a naturally hierarchical expansion/collector-number tree, which doesn't
 * fit "pick exactly one printing while comparing card art" - visually comparing thumbnails
 * matters more here than the tree-select's text-based interaction.
 */

import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Form from "react-bootstrap/Form";
import OverlayTrigger from "react-bootstrap/OverlayTrigger";
import Popover from "react-bootstrap/Popover";
import Row from "react-bootstrap/Row";

import { getPrintingCandidateDataAttributes } from "@/common/cardDom";
import { getOrCreateAnonymousId } from "@/common/cookies";
import {
  PrintingCandidate,
  PrintingConsensusResponse,
} from "@/common/schema_types";
import { useAppDispatch, useAppSelector } from "@/common/types";
import {
  APIGetPrintingCandidates,
  APIGetPrintingConsensus,
  APISubmitPrintingTag,
} from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

interface PrintingTagPickerProps {
  /** The image identifier of the card being tagged. */
  cardIdentifier: string;
  /** The name of the card being tagged. */
  cardName: string;
}

export function PrintingTagPicker({
  cardIdentifier,
  cardName,
}: PrintingTagPickerProps) {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);

  const [query, setQuery] = useState<string>("");
  const [candidates, setCandidates] = useState<Array<PrintingCandidate>>([]);
  const [consensus, setConsensus] = useState<PrintingConsensusResponse | null>(
    null
  );
  const [loading, setLoading] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    APIGetPrintingConsensus(backendURL, cardIdentifier)
      .then(setConsensus)
      .catch(() => undefined);
  }, [backendURL, cardIdentifier]);

  useEffect(() => {
    if (backendURL == null) {
      return;
    }
    setLoading(true);
    APIGetPrintingCandidates(backendURL, cardIdentifier, query || undefined)
      .then((response) => setCandidates(response.results))
      .catch(() => setCandidates([]))
      .finally(() => setLoading(false));
  }, [backendURL, cardIdentifier, query]);

  const submit = (
    printingIdentifier: string | undefined,
    isNoMatch: boolean
  ) => {
    if (backendURL == null) {
      return;
    }
    setSubmitting(true);
    APISubmitPrintingTag(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      printingIdentifier,
      isNoMatch
    )
      .then((response) => {
        setConsensus(response);
        dispatch(
          setNotification([
            Math.random().toString(),
            {
              name: "Vote submitted",
              message: "Thanks for helping tag this card's printing!",
              level: "info",
            },
          ])
        );
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

  return (
    <div data-testid="printing-tag-picker">
      <div className="mb-2" data-testid="printing-tag-consensus">
        {consensus == null && "Loading current consensus..."}
        {consensus != null && consensus.resolvedPrinting != null && (
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
      <Form.Control
        type="text"
        placeholder="Search for a different card..."
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {loading ? (
        <div className="mt-2">Loading candidates...</div>
      ) : (
        <Row className="g-2 mt-1" xs={3} md={4}>
          <Col>
            <Button
              variant={consensus?.isNoMatch ? "success" : "outline-secondary"}
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
            <OverlayTrigger
              key={candidate.identifier}
              placement="auto"
              delay={{ show: 300, hide: 0 }}
              overlay={
                <Popover
                  id={`printing-candidate-preview-${candidate.identifier}`}
                >
                  <Popover.Body className="p-1">
                    <img
                      src={candidate.mediumThumbnailUrl}
                      alt={`${candidate.expansionCode} ${candidate.collectorNumber} preview`}
                      style={{ maxWidth: "240px", display: "block" }}
                    />
                  </Popover.Body>
                </Popover>
              }
            >
              <Col>
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
                  {...getPrintingCandidateDataAttributes(cardName, candidate)}
                >
                  <img
                    src={candidate.smallThumbnailUrl}
                    alt={`${candidate.expansionCode} ${candidate.collectorNumber}`}
                    style={{ width: "100%" }}
                  />
                  <div>
                    {candidate.expansionCode.toUpperCase()}{" "}
                    {candidate.collectorNumber}
                  </div>
                  <div className="text-muted small">{candidate.artist}</div>
                </Button>
              </Col>
            </OverlayTrigger>
          ))}
        </Row>
      )}
    </div>
  );
}
