/**
 * "Why no match?" follow-up shown in PrintingTagQueue.tsx immediately after a user submits
 * an explicit "No match" printing vote (not shown for a still-contested candidate pick -
 * that case keeps using the general AttributeVotingPanel, see the call site). One tap on a
 * reason chip casts a single positive CardTagVote for that reason and advances; Skip
 * advances without voting. Deliberately not the full TagVotePicker grid - this is a
 * narrower, faster "why" prompt matched to the moment right after a no-match tap, not a
 * general tagging surface.
 *
 * Keep the six tagName values below in sync with cardpicker/reason_tags.py (seeded via the
 * `seed_no_match_reason_tags` management command, not a migration - see that module's
 * header comment for why) - and see the same file for why these are a separate taxonomy
 * from cardpicker.default_tags.DEFAULT_TAGS and why renaming any of them is a breaking
 * change.
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { getOrCreateAnonymousId } from "@/common/cookies";
import { useAppDispatch } from "@/common/types";
import { ChipCard } from "@/features/attributeVoting/ChipCard";
import { APISubmitTagVote } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

const APPLY = 1;

const NO_MATCH_REASONS: Array<{ tagName: string; label: string }> = [
  { tagName: "custom-art", label: "Custom art" },
  { tagName: "altered-frame", label: "Altered frame" },
  { tagName: "upscaled", label: "Upscaled" },
  { tagName: "ai-art", label: "AI art" },
  { tagName: "no-collector-line", label: "No collector line" },
  { tagName: "non-english", label: "Non-English" },
];

interface NoMatchReasonStripProps {
  backendURL: string;
  cardIdentifier: string;
  /** Called once a reason has been submitted, or the user skips. */
  onDone: () => void;
}

export function NoMatchReasonStrip({
  backendURL,
  cardIdentifier,
  onDone,
}: NoMatchReasonStripProps) {
  const dispatch = useAppDispatch();
  const [submittingTagName, setSubmittingTagName] = useState<string | null>(
    null
  );

  const choose = (tagName: string) => {
    setSubmittingTagName(tagName);
    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      APPLY
    )
      .then(() => onDone())
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
      .finally(() => setSubmittingTagName(null));
  };

  return (
    <div data-testid="no-match-reason-strip">
      <h6>Why no match?</h6>
      <Row className="g-2" xs={2} md={3}>
        {NO_MATCH_REASONS.map((reason) => (
          <Col key={reason.tagName}>
            <ChipCard
              label={reason.label}
              disabled={submittingTagName != null}
              onClick={() => choose(reason.tagName)}
              data-testid={`no-match-reason-${reason.tagName}`}
            />
          </Col>
        ))}
      </Row>
      <div className="mt-2">
        <Button
          variant="outline-secondary"
          disabled={submittingTagName != null}
          onClick={onDone}
          data-testid="no-match-reason-skip"
        >
          Skip
        </Button>
      </div>
    </div>
  );
}
