/**
 * Per-deck share links (docs/proposals/proposal-g-user-accounts-saved-decks.md's "PR-5,
 * post-v1: per-deck share links") - owner-side surface: create a new share link for one deck,
 * and manage (list/revoke) that deck's existing shares. Assumes the crypto session is already
 * unlocked, same convention as SaveDeckModal/LoadSafetyModal.
 *
 * The generated shareKey (the URL fragment) is NEVER persisted anywhere - not in Redux, not in
 * localStorage, not on the server (see deckShare.ts's header). Once this modal closes without
 * the link being copied, that specific link is gone for good; the only recovery is creating a
 * new share (or, if the old one is still listed below, revoking it as dead weight).
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";
import ListGroup from "react-bootstrap/ListGroup";
import Modal from "react-bootstrap/Modal";
import Spinner from "react-bootstrap/Spinner";

import { base64ToBytes } from "@/common/savedDeckCrypto";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import {
  buildShareUrl,
  prepareDeckShare,
} from "@/features/savedDecks/deckShare";
import {
  useCreateDeckShareMutation,
  useGetDeckSharesQuery,
  useRevokeDeckShareMutation,
} from "@/store/api";

const EXPIRY_OPTIONS: Array<{ label: string; days: number | null }> = [
  { label: "Never", days: null },
  { label: "1 day", days: 1 },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
];

interface ShareDeckModalProps {
  show: boolean;
  onClose: () => void;
  deckKey: string;
  deckName: string;
  wrappedDek: string;
  wrappedDekNonce: string;
}

export function ShareDeckModal({
  show,
  onClose,
  deckKey,
  deckName,
  wrappedDek,
  wrappedDekNonce,
}: ShareDeckModalProps) {
  const session = useCryptoSession();
  const [createDeckShare] = useCreateDeckShareMutation();
  const [revokeDeckShare] = useRevokeDeckShareMutation();
  const sharesQuery = useGetDeckSharesQuery({ skip: !show });

  const [expiresInDays, setExpiresInDays] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shareLink, setShareLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const sharesForThisDeck = (sharesQuery.data?.shares ?? []).filter(
    (share) => share.deckKey === deckKey
  );

  const handleCreate = () => {
    if (session.masterKey == null) {
      return;
    }
    setCreating(true);
    setError(null);
    setShareLink(null);
    setCopied(false);
    prepareDeckShare(
      {
        wrapped: base64ToBytes(wrappedDek),
        nonce: base64ToBytes(wrappedDekNonce),
      },
      session.masterKey
    )
      .then((prepared) =>
        createDeckShare({
          deckKey,
          wrappedDek: prepared.wrappedDek,
          wrappedDekNonce: prepared.wrappedDekNonce,
          expiresInDays,
        })
          .unwrap()
          .then((response) =>
            buildShareUrl(
              window.location.origin,
              response.shareId,
              prepared.shareKeyFragment
            )
          )
      )
      .then((url) => setShareLink(url))
      .catch((thrown) =>
        setError(thrown instanceof Error ? thrown.message : String(thrown))
      )
      .finally(() => setCreating(false));
  };

  const handleCopy = () => {
    if (shareLink == null) {
      return;
    }
    navigator.clipboard?.writeText(shareLink).then(() => setCopied(true));
  };

  const handleRevoke = (shareId: string) => {
    if (
      !window.confirm(
        "Revoke this share link? It will stop working immediately for anyone who has it."
      )
    ) {
      return;
    }
    revokeDeckShare({ shareId });
  };

  return (
    <Modal show={show} onHide={onClose} data-testid="share-deck-modal">
      <Modal.Header closeButton>
        <Modal.Title>Share &quot;{deckName || "(untitled)"}&quot;</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <p className="text-muted small">
          Anyone with the link can view (but not edit) this deck as it stands
          right now. Editing the deck afterwards does not update links
          you&apos;ve already shared - revoke and re-share if you want
          recipients to see your latest changes.
        </p>
        <Form.Group className="mb-3">
          <Form.Label>Link expires</Form.Label>
          <Form.Select
            aria-label="share-expiry"
            value={expiresInDays ?? "never"}
            onChange={(event) =>
              setExpiresInDays(
                event.target.value === "never"
                  ? null
                  : Number(event.target.value)
              )
            }
          >
            {EXPIRY_OPTIONS.map((option) => (
              <option key={option.label} value={option.days ?? "never"}>
                {option.label}
              </option>
            ))}
          </Form.Select>
        </Form.Group>
        <Button
          variant="primary"
          onClick={handleCreate}
          disabled={creating || session.masterKey == null}
        >
          {creating ? "Creating…" : "Create share link"}
        </Button>
        {error != null && <p className="text-danger mt-2">{error}</p>}
        {shareLink != null && (
          <div className="mt-3">
            <p className="mb-1">
              <strong>
                Copy this link now - it can&apos;t be shown again.
              </strong>{" "}
              If you lose it, revoke it below and create a new one.
            </p>
            <pre
              data-testid="share-link-text"
              className="p-2 bg-light border rounded"
              style={{ wordBreak: "break-all", whiteSpace: "pre-wrap" }}
            >
              {shareLink}
            </pre>
            <Button variant="secondary" size="sm" onClick={handleCopy}>
              {copied ? "Copied!" : "Copy link"}
            </Button>
          </div>
        )}
        <hr />
        <h6>Active shares</h6>
        {sharesQuery.isLoading && <Spinner animation="border" size="sm" />}
        {sharesForThisDeck.length === 0 && !sharesQuery.isLoading ? (
          <p className="text-muted small">
            No active shares for this deck yet.
          </p>
        ) : (
          <ListGroup data-testid="active-shares-list">
            {sharesForThisDeck.map((share) => (
              <ListGroup.Item
                key={share.shareId}
                className="d-flex justify-content-between align-items-center"
              >
                <span className="small">
                  Created {share.createdAt}
                  {share.expiresAt != null
                    ? ` · expires ${share.expiresAt}`
                    : ""}
                </span>
                <Button
                  size="sm"
                  variant="outline-danger"
                  onClick={() => handleRevoke(share.shareId)}
                >
                  Revoke
                </Button>
              </ListGroup.Item>
            ))}
          </ListGroup>
        )}
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
