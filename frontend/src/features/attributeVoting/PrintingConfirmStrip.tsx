/**
 * "Confirm what you see" follow-up shown in PrintingTagQueue.tsx immediately after a vote
 * resolves a card's printing. Two chips - Full art / Borderless - pre-filled (highlighted)
 * from the resolved candidate's own metadata (already present on the PrintingCandidate
 * payload as `fullArt`/`isBorderless`), so the chip's resting state previews the vote a tap
 * would cast. Tapping a chip confirms that preview by casting one CardTagVote for the
 * existing "Full Art"/"Borderless" tags (seeded by cardpicker.default_tags, not new tags)
 * with polarity matching the previewed state; Skip/Continue moves on without voting.
 * Deliberately reuses the existing Full Art/Borderless taxonomy rather than minting new
 * tags - this strip is just a fast, pre-filled way to cast the same votes TagVotePicker
 * already supports. Chip labels are the seeded `display_name` for each tag (useTagDisplayName),
 * not hardcoded text.
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { getOrCreateAnonymousId } from "@/common/cookies";
import { PrintingCandidate } from "@/common/schema_types";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { useAppDispatch } from "@/common/types";
import { ChipCard } from "@/features/attributeVoting/ChipCard";
import { APISubmitTagVote } from "@/store/api";
import { setNotification } from "@/store/slices/toastsSlice";

const APPLY = 1;
const NOT_APPLICABLE = -1;

interface ConfirmToggle {
  tagName: string;
  previewValue: boolean;
}

interface PrintingConfirmStripProps {
  backendURL: string;
  cardIdentifier: string;
  candidate: PrintingCandidate;
  /** Called once the user has confirmed both toggles (or skipped). */
  onDone: () => void;
}

export function PrintingConfirmStrip({
  backendURL,
  cardIdentifier,
  candidate,
  onDone,
}: PrintingConfirmStripProps) {
  const dispatch = useAppDispatch();
  const getTagDisplayName = useTagDisplayName();
  const [confirmedTagNames, setConfirmedTagNames] = useState<Set<string>>(
    new Set()
  );
  const [submittingTagName, setSubmittingTagName] = useState<string | null>(
    null
  );

  const toggles: ConfirmToggle[] = [
    { tagName: "Full Art", previewValue: candidate.fullArt },
    { tagName: "Borderless", previewValue: candidate.isBorderless },
  ];

  const confirm = (toggle: ConfirmToggle) => {
    setSubmittingTagName(toggle.tagName);
    APISubmitTagVote(
      backendURL,
      cardIdentifier,
      getOrCreateAnonymousId(),
      toggle.tagName,
      toggle.previewValue ? APPLY : NOT_APPLICABLE
    )
      .then(() =>
        setConfirmedTagNames((previous) =>
          new Set(previous).add(toggle.tagName)
        )
      )
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
    <div data-testid="printing-confirm-strip">
      <h6>Confirm what you see</h6>
      <Row className="g-2" xs={2}>
        {toggles.map((toggle) => (
          <Col key={toggle.tagName}>
            <ChipCard
              label={getTagDisplayName(toggle.tagName)}
              sublabel={
                confirmedTagNames.has(toggle.tagName) ? "Confirmed" : undefined
              }
              highlighted={toggle.previewValue}
              disabled={
                submittingTagName != null ||
                confirmedTagNames.has(toggle.tagName)
              }
              onClick={() => confirm(toggle)}
              data-testid={`printing-confirm-${toggle.tagName
                .toLowerCase()
                .replace(" ", "-")}`}
            />
          </Col>
        ))}
      </Row>
      <div className="mt-2 d-flex gap-2">
        <Button
          variant="outline-secondary"
          disabled={submittingTagName != null}
          onClick={onDone}
          data-testid="printing-confirm-skip"
        >
          Skip
        </Button>
        <Button
          variant="primary"
          disabled={submittingTagName != null}
          onClick={onDone}
          data-testid="printing-confirm-continue"
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
