/**
 * Lets a user tag which artist illustrated a card, or mark it as an unlisted/unknown artist.
 * Shown as part of AttributeVotingPanel, once a card's printing-tag consensus hasn't resolved
 * a printing (see that component for the trigger condition) - mirrors PrintingTagPicker.tsx's
 * fetch/submit structure, but candidates here are plain named chips (CanonicalArtist has no
 * thumbnail image) rather than thumbnail buttons.
 */

import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Form from "react-bootstrap/Form";
import Row from "react-bootstrap/Row";

import { getOrCreateAnonymousId } from "@/common/cookies";
import {
  ArtistConsensusResponse,
  CanonicalArtist,
} from "@/common/schema_types";
import { useAppDispatch } from "@/common/types";
import {
  APIGetArtistCandidates,
  APIGetArtistConsensus,
  APISubmitArtistVote,
} from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

interface ArtistVotePickerProps {
  backendURL: string;
  cardIdentifier: string;
}

export function ArtistVotePicker({
  backendURL,
  cardIdentifier,
}: ArtistVotePickerProps) {
  const dispatch = useAppDispatch();

  const [query, setQuery] = useState<string>("");
  const [candidates, setCandidates] = useState<Array<CanonicalArtist>>([]);
  const [consensus, setConsensus] = useState<ArtistConsensusResponse | null>(
    null
  );
  const [loading, setLoading] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);

  useEffect(() => {
    APIGetArtistConsensus(backendURL, cardIdentifier)
      .then(setConsensus)
      .catch(() => undefined);
  }, [backendURL, cardIdentifier]);

  useEffect(() => {
    setLoading(true);
    APIGetArtistCandidates(backendURL, cardIdentifier, query || undefined)
      .then((response) =>
        setCandidates(
          response.results.filter(
            (candidate): candidate is CanonicalArtist => candidate != null
          )
        )
      )
      .catch(() => setCandidates([]))
      .finally(() => setLoading(false));
  }, [backendURL, cardIdentifier, query]);

  const submit = (artistName: string | undefined, isUnknown: boolean) => {
    setSubmitting(true);
    APISubmitArtistVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      artistName,
      isUnknown
    )
      .then((response) => {
        setConsensus(response);
        dispatch(
          setNotification([
            Math.random().toString(),
            {
              name: "Vote submitted",
              message: "Thanks for helping tag this card's artist!",
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
    <div data-testid="artist-vote-picker">
      <div className="mb-2" data-testid="artist-vote-consensus">
        {consensus == null && "Loading current consensus..."}
        {consensus != null && consensus.resolvedArtist != null && (
          <span>Current consensus: {consensus.resolvedArtist.name}</span>
        )}
        {consensus != null &&
          consensus.resolvedArtist == null &&
          consensus.isUnknown && <span>Current consensus: unknown artist</span>}
        {consensus != null &&
          consensus.resolvedArtist == null &&
          !consensus.isUnknown && (
            <span>
              Not yet resolved
              {consensus.voteTally.length > 0 ? " - contested" : ""}
            </span>
          )}
      </div>
      <Form.Control
        type="text"
        placeholder="Search for an artist..."
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {loading ? (
        <div className="mt-2">Loading candidates...</div>
      ) : (
        <Row className="g-2 mt-1" xs={2} md={3}>
          <Col>
            <Button
              variant={consensus?.isUnknown ? "success" : "outline-secondary"}
              className="w-100"
              disabled={submitting}
              onClick={() => submit(undefined, true)}
            >
              Unknown artist
            </Button>
          </Col>
          {candidates.map((candidate) => (
            <Col key={candidate.name}>
              <Button
                variant={
                  consensus?.resolvedArtist?.name === candidate.name
                    ? "success"
                    : "outline-secondary"
                }
                className="w-100"
                disabled={submitting}
                onClick={() => submit(candidate.name, false)}
              >
                {candidate.name}
              </Button>
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
}
