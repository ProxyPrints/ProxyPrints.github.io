/**
 * "My Decks" (docs/proposals/proposal-g-user-accounts-saved-decks.md §4) - lists every saved
 * deck, decrypted client-side (the server only ever holds ciphertext - see getSavedDecks's own
 * docstring for why this means fetching every row's full ciphertext, not lightweight metadata).
 * Snapshots (the auto-snapshot safety net - see ProjectEditor's load flow) render in their own
 * group, separate from ordinarily-saved decks.
 */

import React, { useEffect, useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import ListGroup from "react-bootstrap/ListGroup";
import Spinner from "react-bootstrap/Spinner";

import { RightPaddedIcon } from "@/components/icon";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import {
  buildExportBundle,
  downloadExportBundle,
} from "@/features/savedDecks/deckExportImport";
import {
  DecryptedSavedDeck,
  decryptSavedDeckSummary,
} from "@/features/savedDecks/deckPayload";
import { ImportDeckModal } from "@/features/savedDecks/ImportDeckModal";
import { ShareDeckModal } from "@/features/savedDecks/ShareDeckModal";
import { useLoadSavedDeck } from "@/features/savedDecks/useLoadSavedDeck";
import {
  useDeleteDeckMutation,
  useGetCryptoProfileQuery,
  useGetSavedDecksQuery,
  useGetWhoamiQuery,
  useResetSavedDecksMutation,
} from "@/store/api";

function sortByUpdatedAtDescending(decks: Array<DecryptedSavedDeck>) {
  return [...decks].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

// Exported (design doc §5/§6 row S1, issue #268) so the /display empty-project landing's
// SavedDecksLandingPanel.tsx can reuse this exact row - same markup, same buttons - rather than
// forking it. `openLabel` defaults to this page's own original copy, so MyDecksPage itself is
// byte-for-byte unchanged.
export function DeckRow({
  deck,
  onOpen,
  onDelete,
  onShare,
  openLabel = "Open in editor",
}: {
  deck: DecryptedSavedDeck;
  onOpen: (deck: DecryptedSavedDeck) => void;
  onDelete?: (deck: DecryptedSavedDeck) => void;
  // Sharing is a `kind=deck` concept only (see post_create_deck_share) - omitted for snapshot
  // rows, which never get a Share button.
  onShare?: (deck: DecryptedSavedDeck) => void;
  openLabel?: string;
}) {
  return (
    <ListGroup.Item className="d-flex justify-content-between align-items-center">
      <span>{deck.name || "(untitled)"}</span>
      <div>
        {onShare != null && (
          <Button
            size="sm"
            variant="outline-primary"
            className="me-2"
            onClick={() => onShare(deck)}
          >
            Share
          </Button>
        )}
        <Button
          size="sm"
          variant="primary"
          className="me-2"
          onClick={() => onOpen(deck)}
        >
          {openLabel}
        </Button>
        {onDelete != null && (
          <Button
            size="sm"
            variant="outline-danger"
            onClick={() => onDelete(deck)}
          >
            Delete
          </Button>
        )}
      </div>
    </ListGroup.Item>
  );
}

export function MyDecksPage() {
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const session = useCryptoSession();

  const shouldFetchDecks =
    session.status === "locked" || session.status === "unlocked";
  const savedDecksQuery = useGetSavedDecksQuery({ skip: !shouldFetchDecks });
  // Export requires no unlock (docs/proposals/.../PR-6's own explicit requirement) - fetched
  // independently of the crypto session's unlocked state, same gate as savedDecksQuery above.
  const cryptoProfileQuery = useGetCryptoProfileQuery({
    skip: !shouldFetchDecks,
  });
  const [deleteDeck] = useDeleteDeckMutation();
  const [resetSavedDecks] = useResetSavedDecksMutation();

  // Extracted (design doc §5/§6 row S1, issue #268) into useLoadSavedDeck.ts so the /display
  // landing's SavedDecksLandingPanel can share the exact same open/load path - this page passes
  // navigateTo: "/editor" (its own long-standing behaviour), the landing omits it. This page also
  // opts into autoPromptOnLock: arriving at /myDecks already IS the user's deliberate "open my
  // saved decks" action, unlike the /display landing where the hook mounts ambiently alongside
  // unrelated import functionality (see useLoadSavedDeck.ts's own module comment).
  const {
    element: loadSavedDeckModals,
    openDeck,
    showUnlock,
    openUnlock,
  } = useLoadSavedDeck({ navigateTo: "/editor", autoPromptOnLock: true });

  const [decrypted, setDecrypted] = useState<Array<DecryptedSavedDeck>>([]);
  const [decrypting, setDecrypting] = useState(false);
  const [decryptError, setDecryptError] = useState<string | null>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [sharingDeck, setSharingDeck] = useState<DecryptedSavedDeck | null>(
    null
  );

  useEffect(() => {
    let cancelled = false;
    if (
      session.status === "unlocked" &&
      session.masterKey != null &&
      savedDecksQuery.data != null
    ) {
      setDecrypting(true);
      setDecryptError(null);
      Promise.all(
        savedDecksQuery.data.decks.map((summary) =>
          decryptSavedDeckSummary(summary, session.masterKey!)
        )
      )
        .then((results) => {
          if (!cancelled) {
            setDecrypted(results);
          }
        })
        .catch((thrown) => {
          if (!cancelled) {
            setDecryptError(
              thrown instanceof Error ? thrown.message : String(thrown)
            );
          }
        })
        .finally(() => {
          if (!cancelled) {
            setDecrypting(false);
          }
        });
    }
    return () => {
      cancelled = true;
    };
  }, [session.status, session.masterKey, savedDecksQuery.data]);

  const namedDecks = useMemo(
    () => sortByUpdatedAtDescending(decrypted.filter((d) => d.kind === "deck")),
    [decrypted]
  );
  const snapshots = useMemo(
    () =>
      sortByUpdatedAtDescending(decrypted.filter((d) => d.kind === "snapshot")),
    [decrypted]
  );

  const handleExport = () => {
    if (savedDecksQuery.data == null || cryptoProfileQuery.data == null) {
      return;
    }
    setExportError(null);
    try {
      const bundle = buildExportBundle(
        cryptoProfileQuery.data,
        savedDecksQuery.data.decks
      );
      downloadExportBundle(bundle);
    } catch (thrown) {
      setExportError(thrown instanceof Error ? thrown.message : String(thrown));
    }
  };

  const handleDelete = (deck: DecryptedSavedDeck) => {
    if (
      !window.confirm(
        `Permanently delete "${
          deck.name || "(untitled)"
        }"? This can't be undone.`
      )
    ) {
      return;
    }
    deleteDeck({ key: deck.key });
  };

  // Raw (still-wrapped) fields for whichever deck is currently being shared - ShareDeckModal
  // needs the deck's CURRENT wrappedDek/wrappedDekNonce (straight off the summary this page
  // already fetched), not anything from the already-decrypted DecryptedSavedDeck shape.
  const sharingDeckSummary = useMemo(
    () =>
      sharingDeck == null
        ? undefined
        : savedDecksQuery.data?.decks.find((s) => s.key === sharingDeck.key),
    [sharingDeck, savedDecksQuery.data]
  );

  const handleReset = () => {
    if (!confirmingReset) {
      setConfirmingReset(true);
      return;
    }
    resetSavedDecks({ confirm: true }).then(() => {
      setConfirmingReset(false);
      setDecrypted([]);
    });
  };

  if (!isAuthenticated) {
    return <p>Sign in from the navbar above to save and load decks.</p>;
  }

  if (session.status === "loading") {
    return <Spinner animation="border" />;
  }

  if (session.status === "no-profile") {
    return (
      <p>
        You haven&apos;t saved any decks yet - save your current project from
        the editor to get started.
      </p>
    );
  }

  const deckCount = savedDecksQuery.data?.decks.length ?? 0;

  return (
    <>
      {loadSavedDeckModals}
      {session.masterKey != null && (
        <ImportDeckModal
          show={showImport}
          onCancel={() => setShowImport(false)}
          onImported={(count) => {
            setShowImport(false);
            setImportMessage(
              `Imported ${count} deck${count === 1 ? "" : "s"} as new.`
            );
            savedDecksQuery.refetch();
          }}
          masterKey={session.masterKey}
        />
      )}
      {sharingDeck != null && sharingDeckSummary != null && (
        <ShareDeckModal
          show
          onClose={() => setSharingDeck(null)}
          deckKey={sharingDeck.key}
          deckName={sharingDeck.name}
          wrappedDek={sharingDeckSummary.wrappedDek}
          wrappedDekNonce={sharingDeckSummary.wrappedDekNonce}
        />
      )}
      {session.status === "locked" && !showUnlock && (
        <p>
          <Button onClick={openUnlock}>Unlock my saved decks</Button>
        </p>
      )}
      {shouldFetchDecks && (
        <p>
          {/* Export requires no unlock (docs/proposals/.../PR-6) - it's the same opaque bytes
          the server already holds, so it works whether or not this session has ever unlocked. */}
          <Button
            variant="outline-secondary"
            size="sm"
            className="me-2"
            onClick={handleExport}
            disabled={deckCount === 0}
            data-testid="export-my-decks"
          >
            Export my decks
          </Button>
          {/* Import needs somewhere to PERSIST the decrypted decks to, so it needs THIS
          session's own master key unlocked - unlike export. */}
          <Button
            variant="outline-secondary"
            size="sm"
            onClick={() => setShowImport(true)}
            disabled={session.status !== "unlocked"}
            data-testid="open-import-decks"
          >
            Import decks
          </Button>
        </p>
      )}
      {exportError != null && <p className="text-danger">{exportError}</p>}
      {importMessage != null && <p className="text-success">{importMessage}</p>}
      {decrypting && <Spinner animation="border" />}
      {decryptError != null && <p className="text-danger">{decryptError}</p>}
      {session.status === "unlocked" && !decrypting && (
        <>
          <div className="d-flex justify-content-between align-items-center mb-3">
            <h3 className="m-0">My Decks</h3>
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={session.lock}
            >
              <RightPaddedIcon bootstrapIconName="lock" /> Lock
            </Button>
          </div>
          {namedDecks.length === 0 ? (
            <p>You haven&apos;t saved any decks yet.</p>
          ) : (
            <ListGroup className="mb-4" data-testid="named-decks-list">
              {namedDecks.map((deck) => (
                <DeckRow
                  key={deck.key}
                  deck={deck}
                  onOpen={openDeck}
                  onDelete={handleDelete}
                  onShare={setSharingDeck}
                />
              ))}
            </ListGroup>
          )}
          {snapshots.length > 0 && (
            <>
              <h5>Snapshots</h5>
              <p className="text-muted small">
                Automatic safety copies made when loading a deck over unsaved
                changes.
              </p>
              <ListGroup className="mb-4" data-testid="snapshots-list">
                {snapshots.map((deck) => (
                  <DeckRow
                    key={deck.key}
                    deck={deck}
                    onOpen={openDeck}
                    onDelete={handleDelete}
                  />
                ))}
              </ListGroup>
            </>
          )}
        </>
      )}
      {shouldFetchDecks && (
        <>
          <hr />
          <p className="text-muted">
            Forgot your passphrase and lost your recovery key? There&apos;s no
            way for us to decrypt your decks for you - but you can reset your
            account and start fresh. This permanently deletes all {deckCount} of
            your saved decks.
          </p>
          <Button
            variant={confirmingReset ? "danger" : "outline-danger"}
            onClick={handleReset}
            data-testid="reset-saved-decks"
          >
            {confirmingReset
              ? `Yes, permanently delete all ${deckCount} saved decks`
              : "Reset my saved decks"}
          </Button>
          {confirmingReset && (
            <Button variant="link" onClick={() => setConfirmingReset(false)}>
              Cancel
            </Button>
          )}
        </>
      )}
    </>
  );
}
