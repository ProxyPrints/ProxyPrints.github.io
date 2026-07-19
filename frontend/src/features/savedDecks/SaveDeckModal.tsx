/**
 * The explicit, user-triggered Save action (docs/proposals/proposal-g-user-accounts-saved-decks.md
 * §4) - prompts for a name (pre-filled with the current deck's name if loaded from/last saved
 * as one), warns about local-file-sourced slots that won't restore elsewhere, then encrypts and
 * calls saveDeck. Assumes the crypto session is already unlocked - callers (SavedDeckPanel) are
 * responsible for running PassphraseSetupModal/UnlockModal first if it isn't.
 */

import React, { FormEvent, useEffect, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";

import { LoadDeckResponseKind } from "@/common/schema_types";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import {
  buildDeckPayload,
  countDeviceLocalSlots,
  encryptDeckPayloadForSave,
  serializeDeckPayload,
} from "@/features/savedDecks/deckPayload";
import { useSaveDeckMutation } from "@/store/api";
import { selectFinishSettings } from "@/store/slices/finishSettingsSlice";
import {
  selectCurrentSavedDeck,
  setCurrentSavedDeck,
} from "@/store/slices/savedDeckSessionSlice";
import { RootState } from "@/store/store";

interface SaveDeckModalProps {
  show: boolean;
  onCancel: () => void;
  onSaved: () => void;
}

export function SaveDeckModal({ show, onCancel, onSaved }: SaveDeckModalProps) {
  const dispatch = useAppDispatch();
  const session = useCryptoSession();
  const currentSavedDeck = useAppSelector(selectCurrentSavedDeck);
  const project = useAppSelector((state: RootState) => state.project);
  const finishSettings = useAppSelector(selectFinishSettings);
  const cardDocuments = useAppSelector(
    (state: RootState) => state.cardDocuments.cardDocuments
  );
  const [saveDeck] = useSaveDeckMutation();

  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (show) {
      setName(currentSavedDeck.currentDeckName ?? "");
      setError(null);
    }
  }, [show, currentSavedDeck.currentDeckName]);

  const previewPayload = buildDeckPayload(
    name.trim() || "Untitled deck",
    project,
    finishSettings,
    cardDocuments
  );
  const deviceLocalCount = countDeviceLocalSlots(previewPayload);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (session.masterKey == null) {
      return;
    }
    setSubmitting(true);
    setError(null);
    const finalName = name.trim() || "Untitled deck";
    const payload = buildDeckPayload(
      finalName,
      project,
      finishSettings,
      cardDocuments
    );
    encryptDeckPayloadForSave(payload, session.masterKey)
      .then((encrypted) =>
        saveDeck({
          key: currentSavedDeck.currentDeckKey,
          kind: LoadDeckResponseKind.Deck,
          ...encrypted,
        }).unwrap()
      )
      .then((response) => {
        dispatch(
          setCurrentSavedDeck({
            key: response.key,
            name: finalName,
            serialized: serializeDeckPayload(payload),
          })
        );
        onSaved();
      })
      .catch((thrown) =>
        setError(thrown instanceof Error ? thrown.message : String(thrown))
      )
      .finally(() => setSubmitting(false));
  };

  return (
    <Modal show={show} onHide={onCancel} data-testid="save-deck-modal">
      <Modal.Header closeButton>
        <Modal.Title>Save deck</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <Form onSubmit={handleSubmit} id="save-deck-form">
          <Form.Group className="mb-3">
            <Form.Label>Name</Form.Label>
            <Form.Control
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
              aria-label="save-deck-name"
            />
          </Form.Group>
          {deviceLocalCount > 0 && (
            <p className="text-warning">
              {deviceLocalCount} card{deviceLocalCount === 1 ? "" : "s"} from
              local files won&apos;t be restorable on another device.
            </p>
          )}
          {error != null && <p className="text-danger">{error}</p>}
        </Form>
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="submit"
          form="save-deck-form"
          variant="primary"
          disabled={submitting}
        >
          {submitting ? "Saving…" : "Save"}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
