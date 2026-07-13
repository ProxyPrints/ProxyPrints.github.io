/**
 * Focused single-(card, tag)-question control for the tag-mode vote queue - deliberately not
 * a reuse of TagVotePicker.tsx's full chip grid (which shows every seeded tag at once for one
 * card - a different unit of interaction). Each queue item here is exactly one contested/
 * unresolved (card, tag) pair, so this only ever asks about that one tag: apply, not
 * applicable, or skip. Submits via the same APISubmitTagVote used by TagVotePicker.
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";

import { getOrCreateAnonymousId } from "@/common/cookies";
import { useAppDispatch } from "@/common/types";
import { APISubmitTagVote } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

interface QueueTagQuestionProps {
  backendURL: string;
  cardIdentifier: string;
  tagName: string;
  /** Called once the user has answered (apply/not applicable submitted successfully) or skipped. */
  onAnswered: () => void;
}

const APPLY = 1;
const NOT_APPLICABLE = -1;

export function QueueTagQuestion({
  backendURL,
  cardIdentifier,
  tagName,
  onAnswered,
}: QueueTagQuestionProps) {
  const dispatch = useAppDispatch();
  const [submitting, setSubmitting] = useState<boolean>(false);

  const submit = (polarity: number) => {
    setSubmitting(true);
    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      polarity
    )
      .then(() => onAnswered())
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
    <div data-testid="queue-tag-question">
      <h6>
        Does <strong>{tagName}</strong> apply?
      </h6>
      <div className="d-flex gap-2 mt-2">
        <Button
          variant="success"
          disabled={submitting}
          onClick={() => submit(APPLY)}
        >
          Apply
        </Button>
        <Button
          variant="dark"
          disabled={submitting}
          onClick={() => submit(NOT_APPLICABLE)}
        >
          Not applicable
        </Button>
        <Button
          variant="outline-secondary"
          disabled={submitting}
          onClick={onAnswered}
        >
          Skip
        </Button>
      </div>
    </div>
  );
}
