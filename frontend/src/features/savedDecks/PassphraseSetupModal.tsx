/**
 * The first-save flow (docs/proposals/proposal-g-user-accounts-saved-decks.md §8): create a
 * passphrase, then show the recovery key exactly once. Two steps in one modal rather than two
 * separate modals, since the recovery key step only exists once the first step succeeds.
 */

import React, { FormEvent, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";

import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import { RecoveryKeyDisplay } from "@/features/savedDecks/RecoveryKeyDisplay";

interface PassphraseSetupModalProps {
  show: boolean;
  onCancel: () => void;
  onComplete: () => void;
}

// An arbitrary, reasonable floor - not a strength meter. The backend has no length
// requirement of its own (it never sees the passphrase at all).
const MIN_PASSPHRASE_LENGTH = 12;

export function PassphraseSetupModal({
  show,
  onCancel,
  onComplete,
}: PassphraseSetupModalProps) {
  const session = useCryptoSession();
  const [passphrase, setPassphrase] = useState("");
  const [confirmPassphrase, setConfirmPassphrase] = useState("");
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setPassphrase("");
    setConfirmPassphrase("");
    setRecoveryKey(null);
    setError(null);
    setSubmitting(false);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (passphrase.length < MIN_PASSPHRASE_LENGTH) {
      setError(
        `Your passphrase must be at least ${MIN_PASSPHRASE_LENGTH} characters.`
      );
      return;
    }
    if (passphrase !== confirmPassphrase) {
      setError("Passphrases don't match.");
      return;
    }
    setError(null);
    setSubmitting(true);
    session
      .createProfile(passphrase)
      .then(setRecoveryKey)
      .catch((thrown) =>
        setError(thrown instanceof Error ? thrown.message : String(thrown))
      )
      .finally(() => setSubmitting(false));
  };

  return (
    <Modal
      show={show}
      onHide={onCancel}
      onExited={reset}
      data-testid="passphrase-setup-modal"
    >
      <Modal.Header closeButton={recoveryKey == null}>
        <Modal.Title>
          {recoveryKey == null
            ? "Create a passphrase"
            : "Save your recovery key"}
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {recoveryKey == null ? (
          <>
            <p>
              Your saved decks are encrypted in your browser before they&apos;re
              sent anywhere - we never see the contents, and we can&apos;t
              decrypt them for you.
            </p>
            <p className="text-danger">
              <strong>
                If you forget this passphrase, your saved decks are permanently
                unrecoverable - we cannot reset it, by design.
              </strong>{" "}
              (You&apos;ll get a recovery key next, as a backup.)
            </p>
            <Form onSubmit={handleSubmit} id="passphrase-setup-form">
              <Form.Group className="mb-3">
                <Form.Label>Passphrase</Form.Label>
                <Form.Control
                  type="password"
                  value={passphrase}
                  onChange={(event) => setPassphrase(event.target.value)}
                  autoFocus
                  aria-label="new-passphrase"
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Confirm passphrase</Form.Label>
                <Form.Control
                  type="password"
                  value={confirmPassphrase}
                  onChange={(event) => setConfirmPassphrase(event.target.value)}
                  aria-label="confirm-new-passphrase"
                />
              </Form.Group>
              {error != null && <p className="text-danger">{error}</p>}
            </Form>
          </>
        ) : (
          <RecoveryKeyDisplay
            recoveryKeyBase64={recoveryKey}
            onAcknowledge={onComplete}
          />
        )}
      </Modal.Body>
      {recoveryKey == null && (
        <Modal.Footer>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="passphrase-setup-form"
            variant="primary"
            disabled={submitting}
          >
            {submitting ? "Creating…" : "Create passphrase"}
          </Button>
        </Modal.Footer>
      )}
    </Modal>
  );
}
