/**
 * Deck portability's import half (docs/proposals/proposal-g-user-accounts-saved-decks.md,
 * "PR-6, post-v1: deck portability"): reads a previously-exported bundle (see
 * deckExportImport.ts), decrypts it client-side using the BUNDLE's own passphrase or recovery
 * key (never the live session's, since a bundle may come from a different account or a
 * different, compatible instance entirely), then persists every deck it contains under the
 * CURRENT signed-in account.
 *
 * Conflict rule (spec's own words): always import-as-new. Every imported deck lands as its own
 * row (`key: null`), never overwriting an existing deck by matching key or name - there's no
 * server-visible name to match against anyway once titles are encrypted, and overwriting would
 * risk destroying newer data with a stale export. Each imported deck keeps its OWN
 * `revision`/`modifiedAt` verbatim (via `encryptFinalizedDeckPayload`, not
 * `encryptDeckPayloadForSave`) - importing isn't itself "a save", it's a restore, and
 * overwriting those fields would break the whole point of tracking them (comparing an imported
 * bundle's revision against what's already saved to tell which copy is newer).
 *
 * Assumes the current session is already unlocked (SavedDeckPanel/MyDecksPage are responsible
 * for that, same convention as SaveDeckModal) - importing into a brand-new account with no
 * crypto profile yet isn't handled here; the "Import decks" entry point is disabled until then.
 */

import React, { ChangeEvent, FormEvent, useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import Modal from "react-bootstrap/Modal";

import {
  decryptBundleDecks,
  ExportBundleV1,
  parseExportBundle,
  unlockBundleMasterKeyWithPassphrase,
  unlockBundleMasterKeyWithRecoveryKey,
} from "@/features/savedDecks/deckExportImport";
import { encryptFinalizedDeckPayload } from "@/features/savedDecks/deckPayload";
import { useSaveDeckMutation } from "@/store/api";

interface ImportDeckModalProps {
  show: boolean;
  onCancel: () => void;
  /** Called once every deck in the bundle has been persisted, with the count imported. */
  onImported: (count: number) => void;
  /** The CURRENT (already-unlocked) session's master key - every imported deck is re-encrypted
   * under this key, never the bundle's own. */
  masterKey: CryptoKey;
}

type UnlockMode = "passphrase" | "recovery";

export function ImportDeckModal({
  show,
  onCancel,
  onImported,
  masterKey,
}: ImportDeckModalProps) {
  const [saveDeck] = useSaveDeckMutation();

  const [bundle, setBundle] = useState<ExportBundleV1 | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [mode, setMode] = useState<UnlockMode>("passphrase");
  const [passphrase, setPassphrase] = useState("");
  const [recoveryKeyInput, setRecoveryKeyInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setBundle(null);
    setFileError(null);
    setMode("passphrase");
    setPassphrase("");
    setRecoveryKeyInput("");
    setError(null);
    setSubmitting(false);
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setBundle(null);
    setFileError(null);
    setError(null);
    if (file == null) {
      return;
    }
    // FileReader rather than Blob.text() - broader runtime support (the latter isn't universally
    // available, e.g. in this project's own jsdom test environment).
    const reader = new FileReader();
    reader.onload = () => {
      try {
        setBundle(parseExportBundle(reader.result as string));
      } catch (thrown) {
        setFileError(
          thrown instanceof Error
            ? thrown.message
            : "That file isn't a valid saved-deck export."
        );
      }
    };
    reader.onerror = () =>
      setFileError("That file isn't a valid saved-deck export.");
    reader.readAsText(file);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (bundle == null) {
      return;
    }
    setError(null);
    setSubmitting(true);
    const unlockBundle =
      mode === "passphrase"
        ? unlockBundleMasterKeyWithPassphrase(bundle, passphrase)
        : unlockBundleMasterKeyWithRecoveryKey(bundle, recoveryKeyInput.trim());
    unlockBundle
      .then((bundleMasterKey) => decryptBundleDecks(bundle, bundleMasterKey))
      .then((decryptedDecks) =>
        Promise.all(
          decryptedDecks.map((decrypted) =>
            encryptFinalizedDeckPayload(decrypted.payload, masterKey).then(
              (encrypted) =>
                saveDeck({
                  key: null,
                  kind: decrypted.kind,
                  ciphertext: encrypted.ciphertext,
                  ciphertextNonce: encrypted.ciphertextNonce,
                  wrappedDek: encrypted.wrappedDek,
                  wrappedDekNonce: encrypted.wrappedDekNonce,
                }).unwrap()
            )
          )
        )
      )
      .then((saved) => {
        setSubmitting(false);
        onImported(saved.length);
      })
      .catch(() => {
        setSubmitting(false);
        setError(
          mode === "passphrase"
            ? "That passphrase doesn't match this file."
            : "That recovery key doesn't match this file."
        );
      });
  };

  return (
    <Modal
      show={show}
      onHide={onCancel}
      onExited={reset}
      data-testid="import-deck-modal"
    >
      <Modal.Header closeButton>
        <Modal.Title>Import decks</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <p>
          Choose a previously-exported saved-decks file. Every deck it contains
          is imported as a brand-new deck here - nothing existing is ever
          overwritten.
        </p>
        <Form onSubmit={handleSubmit} id="import-deck-form">
          <Form.Group className="mb-3">
            <Form.Label>Export file</Form.Label>
            <Form.Control
              type="file"
              accept="application/json"
              onChange={handleFileChange}
              aria-label="import-file"
            />
          </Form.Group>
          {fileError != null && <p className="text-danger">{fileError}</p>}
          {bundle != null && (
            <>
              <p>
                {bundle.decks.length} deck
                {bundle.decks.length === 1 ? "" : "s"} found - enter the
                passphrase (or recovery key) it was exported with to decrypt
                them.
              </p>
              {mode === "passphrase" ? (
                <Form.Group className="mb-3">
                  <Form.Label>Passphrase</Form.Label>
                  <Form.Control
                    type="password"
                    value={passphrase}
                    onChange={(event) => setPassphrase(event.target.value)}
                    autoFocus
                    aria-label="import-passphrase"
                  />
                </Form.Group>
              ) : (
                <Form.Group className="mb-3">
                  <Form.Label>Recovery key</Form.Label>
                  <Form.Control
                    type="text"
                    value={recoveryKeyInput}
                    onChange={(event) =>
                      setRecoveryKeyInput(event.target.value)
                    }
                    autoFocus
                    aria-label="import-recovery-key"
                  />
                </Form.Group>
              )}
              <Button
                variant="link"
                className="p-0"
                onClick={() =>
                  setMode(mode === "passphrase" ? "recovery" : "passphrase")
                }
              >
                {mode === "passphrase"
                  ? "Use a recovery key instead"
                  : "Use a passphrase instead"}
              </Button>
            </>
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
          form="import-deck-form"
          variant="primary"
          disabled={bundle == null || submitting}
        >
          {submitting ? "Importing…" : "Import"}
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
