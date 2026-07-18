/**
 * The auto-snapshot safety flow (docs/proposals/proposal-g-user-accounts-saved-decks.md §4,
 * "Load-into-editor flow - loss-proof by construction, not by dialog"): shown only when the
 * editor is dirty and about to be overwritten by loading a different saved deck. Something is
 * always saved automatically before the load proceeds - skipping isn't offered. The only choice
 * is WHERE the safety copy goes:
 *  - current content is itself an already-saved deck: "Update {name}" (overwrites that same
 *    deck with the dirty content) vs. "Save as new snapshot" (leaves that deck alone).
 *  - current content was never saved: a single snapshot save, with only an inline rename
 *    prompt (pre-filled with a sane default) - no "skip" option.
 */

import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";

import { LoadDeckResponseKind } from "@/common/schema_types";
import { useAppSelector } from "@/common/types";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import {
  buildDeckPayload,
  encryptDeckPayloadForSave,
} from "@/features/savedDecks/deckPayload";
import { useSaveDeckMutation } from "@/store/api";
import { selectFinishSettings } from "@/store/slices/finishSettingsSlice";
import { selectCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";
import { RootState } from "@/store/store";

interface LoadSafetyModalProps {
  show: boolean;
  onCancel: () => void;
  onSafetyCompleted: () => void;
}

function defaultSnapshotName(): string {
  return `Backup - ${new Date().toISOString().slice(0, 10)}`;
}

export function LoadSafetyModal({
  show,
  onCancel,
  onSafetyCompleted,
}: LoadSafetyModalProps) {
  const session = useCryptoSession();
  const currentSavedDeck = useAppSelector(selectCurrentSavedDeck);
  const project = useAppSelector((state: RootState) => state.project);
  const finishSettings = useAppSelector(selectFinishSettings);
  const cardDocuments = useAppSelector(
    (state: RootState) => state.cardDocuments.cardDocuments
  );
  const [saveDeck] = useSaveDeckMutation();

  const [snapshotName, setSnapshotName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasExistingDeck = currentSavedDeck.currentDeckKey != null;

  useEffect(() => {
    if (show) {
      setSnapshotName(defaultSnapshotName());
      setError(null);
    }
  }, [show]);

  const doSafetySave = (asUpdate: boolean) => {
    if (session.masterKey == null) {
      return;
    }
    setSubmitting(true);
    setError(null);
    const name = asUpdate
      ? currentSavedDeck.currentDeckName ?? "Untitled deck"
      : snapshotName.trim() || defaultSnapshotName();
    const payload = buildDeckPayload(
      name,
      project,
      finishSettings,
      cardDocuments
    );
    encryptDeckPayloadForSave(payload, session.masterKey)
      .then((encrypted) =>
        saveDeck({
          key: asUpdate ? currentSavedDeck.currentDeckKey : null,
          kind: asUpdate
            ? LoadDeckResponseKind.Deck
            : LoadDeckResponseKind.Snapshot,
          ...encrypted,
        }).unwrap()
      )
      .then(() => {
        setSubmitting(false);
        onSafetyCompleted();
      })
      .catch((thrown) => {
        setSubmitting(false);
        setError(thrown instanceof Error ? thrown.message : String(thrown));
      });
  };

  return (
    <Modal show={show} onHide={onCancel} data-testid="load-safety-modal">
      <Modal.Header closeButton>
        <Modal.Title>Save your current work first?</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <p>
          Loading a different deck will replace what&apos;s in the editor - your
          current changes are saved automatically first.
        </p>
        {hasExistingDeck ? (
          <p>
            The editor currently has unsaved changes to{" "}
            <strong>{currentSavedDeck.currentDeckName}</strong>.
          </p>
        ) : (
          <Form.Group className="mb-3">
            <Form.Label>Name this backup</Form.Label>
            <Form.Control
              type="text"
              value={snapshotName}
              onChange={(event) => setSnapshotName(event.target.value)}
              aria-label="snapshot-name"
              autoFocus
            />
          </Form.Group>
        )}
        {error != null && <p className="text-danger">{error}</p>}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
        {hasExistingDeck && (
          <Button
            variant="outline-primary"
            onClick={() => doSafetySave(false)}
            disabled={submitting}
          >
            Save as new snapshot
          </Button>
        )}
        <Button
          variant="primary"
          onClick={() => doSafetySave(hasExistingDeck)}
          disabled={submitting}
        >
          {submitting
            ? "Saving…"
            : hasExistingDeck
            ? `Update ${currentSavedDeck.currentDeckName}`
            : "Save backup and continue"}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
