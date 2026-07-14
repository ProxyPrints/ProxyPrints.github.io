/**
 * The report button on the card detail modal (docs/features/moderation.md): a flag button
 * that expands into a strip of reason chips (reusing ChipCard so it reads as the same visual
 * language as the modal's voting strips). NSFW / Low quality / Wrong card info submit
 * immediately; Broken image too (report-row-only server-side); Other reveals a bounded
 * free-text box first. One report per open of the panel - after a successful submission the
 * panel collapses into a thank-you line and stays that way for this card until the modal
 * remounts, which is deliberate: the server enforces the real rate limit (10/day), this just
 * keeps the UI from soliciting repeat reports of the same card in the same breath.
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Form from "react-bootstrap/Form";
import Row from "react-bootstrap/Row";

import { getOrCreateAnonymousId } from "@/common/cookies";
import { Reason } from "@/common/schema_types";
import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { ChipCard } from "@/features/attributeVoting/ChipCard";
import { APIReportCard } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

const REPORT_TEXT_MAX_LENGTH = 280;

const REASON_CHIPS: Array<{ reason: Reason; label: string }> = [
  { reason: Reason.Nsfw, label: "NSFW" },
  { reason: Reason.LowQuality, label: "Low quality" },
  { reason: Reason.WrongCard, label: "Wrong card info" },
  { reason: Reason.BrokenImage, label: "Broken image" },
  { reason: Reason.Other, label: "Other…" },
];

interface ReportCardPanelProps {
  cardDocument: CardDocument;
}

export function ReportCardPanel({ cardDocument }: ReportCardPanelProps) {
  const dispatch = useAppDispatch();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const [open, setOpen] = useState<boolean>(false);
  const [otherText, setOtherText] = useState<string>("");
  const [showOtherText, setShowOtherText] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submitted, setSubmitted] = useState<boolean>(false);

  if (backendURL == null) {
    return null;
  }

  const submitReport = async (reason: Reason, text?: string) => {
    setSubmitting(true);
    try {
      await APIReportCard(
        backendURL,
        cardDocument.identifier,
        getOrCreateAnonymousId(),
        reason,
        text
      );
      setSubmitted(true);
    } catch (error: any) {
      dispatch(
        setNotification([
          Math.random().toString(),
          error?.status === 429
            ? {
                name: "Report limit reached",
                message:
                  "You've sent quite a few reports today - please try again tomorrow.",
                level: "warning",
              }
            : {
                name: error?.name ?? "Report failed",
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

  if (submitted) {
    return (
      <p className="text-muted small my-2" data-testid="report-card-thanks">
        Thanks — our moderators will take a look.
      </p>
    );
  }

  if (!open) {
    return (
      <div className="d-grid gap-0 mt-2">
        <Button
          variant="outline-danger"
          size="sm"
          onClick={() => setOpen(true)}
          data-testid="report-card-button"
        >
          <RightPaddedIcon bootstrapIconName="flag" /> Report this card
        </Button>
      </div>
    );
  }

  return (
    <div className="mt-2" data-testid="report-card-panel">
      <p className="text-muted small mb-2">What&apos;s wrong with this card?</p>
      <Row className="g-2">
        {REASON_CHIPS.map(({ reason, label }) => (
          <Col xs={4} key={reason}>
            <ChipCard
              label={label}
              highlighted={reason === Reason.Other && showOtherText}
              disabled={submitting}
              onClick={() =>
                reason === Reason.Other
                  ? setShowOtherText(true)
                  : submitReport(reason)
              }
              data-testid={`report-chip-${reason}`}
            />
          </Col>
        ))}
      </Row>
      {showOtherText && (
        <>
          <Form.Control
            as="textarea"
            rows={2}
            maxLength={REPORT_TEXT_MAX_LENGTH}
            placeholder="Tell us what's wrong (280 characters max)"
            value={otherText}
            onChange={(event) => setOtherText(event.target.value)}
            className="mt-2"
            data-testid="report-other-text"
          />
          <div className="d-grid gap-0 mt-2">
            <Button
              variant="danger"
              size="sm"
              disabled={submitting || otherText.trim().length === 0}
              onClick={() => submitReport(Reason.Other, otherText.trim())}
              data-testid="report-submit-other"
            >
              Submit report
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
