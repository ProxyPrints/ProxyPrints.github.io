/**
 * Lets a user vote on whether each seeded descriptor Tag applies to a card - tri-state toggle
 * chips: unvoted (no resolved consensus for this tag on this card yet), applied (resolved
 * APPLY - clicking again votes NOT_APPLICABLE), or crossed-out (resolved NOT_APPLICABLE -
 * clicking again votes APPLY). Unlike printing/artist voting, a card can carry independent,
 * simultaneous votes across many different tags at once, so each chip submits its own vote
 * immediately on click rather than requiring one shared "submit" action.
 */

import React, { useEffect, useState } from "react";
import Badge from "react-bootstrap/Badge";

import { getOrCreateAnonymousId } from "@/common/cookies";
import { TagConsensusResponse } from "@/common/schema_types";
import { useAppDispatch } from "@/common/types";
import { APIGetTagConsensus, APISubmitTagVote } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

interface TagVotePickerProps {
  backendURL: string;
  cardIdentifier: string;
}

const APPLY = 1;
const NOT_APPLICABLE = -1;

export function TagVotePicker({
  backendURL,
  cardIdentifier,
}: TagVotePickerProps) {
  const dispatch = useAppDispatch();

  const [entries, setEntries] = useState<TagConsensusResponse["tags"]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [submittingTagName, setSubmittingTagName] = useState<string | null>(
    null
  );

  useEffect(() => {
    setLoading(true);
    APIGetTagConsensus(backendURL, cardIdentifier)
      .then((response) => setEntries(response.tags))
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [backendURL, cardIdentifier]);

  const submit = (tagName: string, currentPolarity?: number | null) => {
    const nextPolarity = currentPolarity === APPLY ? NOT_APPLICABLE : APPLY;
    setSubmittingTagName(tagName);
    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      tagName,
      nextPolarity
    )
      .then((updatedEntry) => {
        setEntries((previous) =>
          previous.map((entry) =>
            entry.tagName === tagName ? updatedEntry : entry
          )
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
      .finally(() => setSubmittingTagName(null));
  };

  if (loading) {
    return <div data-testid="tag-vote-picker">Loading tags...</div>;
  }

  return (
    <div data-testid="tag-vote-picker" className="d-flex flex-wrap gap-2">
      {entries.map((entry) => (
        <Badge
          key={entry.tagName}
          pill
          bg={
            entry.resolvedPolarity === APPLY
              ? "success"
              : entry.resolvedPolarity === NOT_APPLICABLE
              ? "dark"
              : "secondary"
          }
          style={{
            cursor: submittingTagName === entry.tagName ? "wait" : "pointer",
            textDecoration:
              entry.resolvedPolarity === NOT_APPLICABLE
                ? "line-through"
                : "none",
            opacity: submittingTagName === entry.tagName ? 0.6 : 1,
          }}
          onClick={() => submit(entry.tagName, entry.resolvedPolarity)}
        >
          {entry.tagName}
        </Badge>
      ))}
    </div>
  );
}
