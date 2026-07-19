/**
 * Shown once per session whenever a "locked" saved-deck action is attempted (see cryptoSession.tsx's
 * status). Two paths: the normal passphrase unlock, or "forgot your passphrase?" - the recovery
 * flow, which unwraps via the recovery key, sets a new passphrase, and reissues a fresh recovery
 * key (docs/proposals/proposal-g-user-accounts-saved-decks.md ZK addendum), shown exactly once
 * via the same RecoveryKeyDisplay the first-save flow uses.
 */

import React, { FormEvent, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";

import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import { RecoveryKeyDisplay } from "@/features/savedDecks/RecoveryKeyDisplay";

interface UnlockModalProps {
  show: boolean;
  onCancel: () => void;
  onUnlocked: () => void;
}

const MIN_PASSPHRASE_LENGTH = 12;

type UnlockMode = "unlock" | "recover";

export function UnlockModal({ show, onCancel, onUnlocked }: UnlockModalProps) {
  const session = useCryptoSession();
  // The crypto profile fetch (see cryptoSession.tsx) can still be in flight the instant this
  // modal opens - submitting before it resolves would throw "no profile" and get misreported
  // as a wrong passphrase/recovery key, so both forms stay disabled until it's settled.
  const isProfileLoading = session.status === "loading";
  const [mode, setMode] = useState<UnlockMode>("unlock");
  const [passphrase, setPassphrase] = useState("");
  const [recoveryKeyInput, setRecoveryKeyInput] = useState("");
  const [newPassphrase, setNewPassphrase] = useState("");
  const [newRecoveryKey, setNewRecoveryKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setMode("unlock");
    setPassphrase("");
    setRecoveryKeyInput("");
    setNewPassphrase("");
    setNewRecoveryKey(null);
    setError(null);
    setSubmitting(false);
  };

  const handleUnlockSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isProfileLoading) {
      return;
    }
    setError(null);
    setSubmitting(true);
    session
      .unlockWithPassphrase(passphrase)
      .then(onUnlocked)
      .catch(() => setError("That passphrase doesn't match."))
      .finally(() => setSubmitting(false));
  };

  const handleRecoverSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isProfileLoading) {
      return;
    }
    if (newPassphrase.length < MIN_PASSPHRASE_LENGTH) {
      setError(
        `Your new passphrase must be at least ${MIN_PASSPHRASE_LENGTH} characters.`
      );
      return;
    }
    setError(null);
    setSubmitting(true);
    session
      .recoverAndSetNewPassphrase(recoveryKeyInput.trim(), newPassphrase)
      .then(setNewRecoveryKey)
      .catch(() => setError("That recovery key doesn't match."))
      .finally(() => setSubmitting(false));
  };

  return (
    <Modal
      show={show}
      onHide={onCancel}
      onExited={reset}
      data-testid="unlock-modal"
    >
      <Modal.Header closeButton={newRecoveryKey == null}>
        <Modal.Title>
          {newRecoveryKey != null
            ? "Save your new recovery key"
            : mode === "unlock"
            ? "Unlock your saved decks"
            : "Recover using your recovery key"}
        </Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {newRecoveryKey != null ? (
          <RecoveryKeyDisplay
            recoveryKeyBase64={newRecoveryKey}
            onAcknowledge={onUnlocked}
          />
        ) : mode === "unlock" ? (
          <>
            <Form onSubmit={handleUnlockSubmit} id="unlock-form">
              <Form.Group className="mb-3">
                <Form.Label>Passphrase</Form.Label>
                <Form.Control
                  type="password"
                  value={passphrase}
                  onChange={(event) => setPassphrase(event.target.value)}
                  autoFocus
                  aria-label="unlock-passphrase"
                />
              </Form.Group>
              {error != null && <p className="text-danger">{error}</p>}
            </Form>
            <Button
              variant="link"
              className="p-0"
              onClick={() => {
                setError(null);
                setMode("recover");
              }}
            >
              Forgot your passphrase?
            </Button>
          </>
        ) : (
          <>
            <p>
              Paste your recovery key below, then set a new passphrase. This
              will replace your old passphrase and issue you a new recovery key
              - your saved decks themselves aren&apos;t touched.
            </p>
            <Form onSubmit={handleRecoverSubmit} id="recover-form">
              <Form.Group className="mb-3">
                <Form.Label>Recovery key</Form.Label>
                <Form.Control
                  type="text"
                  value={recoveryKeyInput}
                  onChange={(event) => setRecoveryKeyInput(event.target.value)}
                  autoFocus
                  aria-label="recovery-key-input"
                />
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>New passphrase</Form.Label>
                <Form.Control
                  type="password"
                  value={newPassphrase}
                  onChange={(event) => setNewPassphrase(event.target.value)}
                  aria-label="new-passphrase-after-recovery"
                />
              </Form.Group>
              {error != null && <p className="text-danger">{error}</p>}
            </Form>
            <Button
              variant="link"
              className="p-0"
              onClick={() => {
                setError(null);
                setMode("unlock");
              }}
            >
              Back to unlock
            </Button>
          </>
        )}
      </Modal.Body>
      {newRecoveryKey == null && (
        <Modal.Footer>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="submit"
            form={mode === "unlock" ? "unlock-form" : "recover-form"}
            variant="primary"
            disabled={submitting || isProfileLoading}
          >
            {isProfileLoading
              ? "Loading…"
              : mode === "unlock"
              ? submitting
                ? "Unlocking…"
                : "Unlock"
              : submitting
              ? "Recovering…"
              : "Recover"}
          </Button>
        </Modal.Footer>
      )}
    </Modal>
  );
}
