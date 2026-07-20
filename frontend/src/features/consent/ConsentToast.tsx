/**
 * Issue #204 - the contextual consent toast itself. Purely presentational (see
 * useConsentToast.ts for the per-permission-key show/decide wiring) - a bottom-corner,
 * cookie-banner-style prompt that only ever appears because SOME call site just asked for
 * consent for a SPECIFIC action, never a blanket on-load "we use cookies" banner.
 *
 * Built on react-bootstrap's `Alert` (same choice PostExportContributionPrompt.tsx made over
 * `Toast`, see that file's own top comment) rather than `Toast`/`ToastContainer`: both of those
 * components hardcode `role="alert"` on their rendered element (verified by reading
 * node_modules/react-bootstrap/{Toast,Alert}.js directly - Alert does too, UNLESS its default
 * Fade transition is disabled, in which case props - including a caller-supplied `role` - spread
 * onto the element directly and win). `role="alert"` is for a passive live-region announcement;
 * this component asks the user to make a decision via two buttons, which is `alertdialog`'s job
 * (https://www.w3.org/TR/wai-aria-1.1/#alertdialog) - `transition={false}` is the deliberate,
 * verified way to get that correct role out of the shared Alert component instead of hand-rolling
 * a whole custom widget. The cost is no fade-in/out animation, an acceptable trade for correct
 * semantics on a component that exists specifically to be decided on, not glanced at.
 */
import styled from "@emotion/styled";
import React, { useCallback, useEffect, useRef } from "react";
import Alert from "react-bootstrap/Alert";
import Button from "react-bootstrap/Button";

const PositionedWrapper = styled.div`
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  z-index: 1080; // matches Bootstrap's own --bs-toast-zindex default
  max-width: 380px;
  width: calc(100vw - 2rem);
`;

export interface ConsentToastProps {
  show: boolean;
  /** Short label for what's being asked, e.g. "Help identify this printing?" */
  title?: string;
  /** The specific action/permission this consent request is for - always caller-supplied,
   * never a generic "we use cookies" message (issue #204 requirement 1). */
  message: string;
  acceptLabel?: string;
  declineLabel?: string;
  onAccept: () => void;
  onDecline: () => void;
}

export function ConsentToast({
  show,
  title = "Before we continue",
  message,
  acceptLabel = "Allow",
  declineLabel = "No thanks",
  onAccept,
  onDecline,
}: ConsentToastProps) {
  const acceptButtonRef = useRef<HTMLButtonElement>(null);
  const titleId = "consent-toast-title";
  const descriptionId = "consent-toast-description";

  // Move focus onto the primary action when the prompt appears, since it's mounted
  // unconditionally in the layout tree (not opened via a user click that already has focus
  // context) - without this, a keyboard/screen-reader user has no cue that a new interactive
  // element just appeared off to the side of whatever they were doing.
  useEffect(() => {
    if (show) {
      acceptButtonRef.current?.focus();
    }
  }, [show]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === "Escape") {
        onDecline();
      }
    },
    [onDecline]
  );

  if (!show) {
    return null;
  }

  return (
    <PositionedWrapper
      onKeyDown={handleKeyDown}
      data-testid="consent-toast-wrapper"
    >
      <Alert
        show
        transition={false}
        variant="info"
        dismissible
        onClose={onDecline}
        className="mb-0 shadow"
        role="alertdialog"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        data-testid="consent-toast"
      >
        <Alert.Heading as="h6" id={titleId}>
          {title}
        </Alert.Heading>
        <p id={descriptionId} className="mb-2">
          {message}
        </p>
        <div className="d-flex justify-content-end gap-2">
          <Button
            size="sm"
            variant="outline-secondary"
            onClick={onDecline}
            data-testid="consent-toast-decline"
          >
            {declineLabel}
          </Button>
          <Button
            ref={acceptButtonRef}
            size="sm"
            variant="primary"
            onClick={onAccept}
            data-testid="consent-toast-accept"
          >
            {acceptLabel}
          </Button>
        </div>
      </Alert>
    </PositionedWrapper>
  );
}
