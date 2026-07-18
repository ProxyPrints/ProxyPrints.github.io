/**
 * "My Decks" (docs/proposals/proposal-g-user-accounts-saved-decks.md §4) - lists every saved
 * deck, decrypted client-side (the server only ever holds ciphertext - see getSavedDecks's own
 * docstring for why this means fetching every row's full ciphertext, not lightweight metadata).
 * Snapshots (the auto-snapshot safety net - see ProjectEditor's load flow) render in their own
 * group, separate from ordinarily-saved decks.
 */

import { useRouter } from "next/router";
import React, { useEffect, useMemo, useState } from "react";
import Button from "react-bootstrap/Button";
import ListGroup from "react-bootstrap/ListGroup";
import Spinner from "react-bootstrap/Spinner";

import { useAppDispatch } from "@/common/types";
import { RightPaddedIcon } from "@/components/icon";
import { useCryptoSession } from "@/features/savedDecks/cryptoSession";
import {
  DecryptedSavedDeck,
  decryptSavedDeckSummary,
  projectFromDeckPayload,
  serializeDeckPayload,
} from "@/features/savedDecks/deckPayload";
import { UnlockModal } from "@/features/savedDecks/UnlockModal";
import {
  useDeleteDeckMutation,
  useGetSavedDecksQuery,
  useGetWhoamiQuery,
  useResetSavedDecksMutation,
} from "@/store/api";
import { loadFinishSettings } from "@/store/slices/finishSettingsSlice";
import { loadProject } from "@/store/slices/projectSlice";
import { setCurrentSavedDeck } from "@/store/slices/savedDeckSessionSlice";

function sortByUpdatedAtDescending(decks: Array<DecryptedSavedDeck>) {
  return [...decks].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function DeckRow({
  deck,
  onOpen,
  onDelete,
}: {
  deck: DecryptedSavedDeck;
  onOpen: (deck: DecryptedSavedDeck) => void;
  onDelete: (deck: DecryptedSavedDeck) => void;
}) {
  return (
    <ListGroup.Item className="d-flex justify-content-between align-items-center">
      <span>{deck.name || "(untitled)"}</span>
      <div>
        <Button
          size="sm"
          variant="primary"
          className="me-2"
          onClick={() => onOpen(deck)}
        >
          Open in editor
        </Button>
        <Button
          size="sm"
          variant="outline-danger"
          onClick={() => onDelete(deck)}
        >
          Delete
        </Button>
      </div>
    </ListGroup.Item>
  );
}

export function MyDecksPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;
  const session = useCryptoSession();

  const shouldFetchDecks =
    session.status === "locked" || session.status === "unlocked";
  const savedDecksQuery = useGetSavedDecksQuery({ skip: !shouldFetchDecks });
  const [deleteDeck] = useDeleteDeckMutation();
  const [resetSavedDecks] = useResetSavedDecksMutation();

  const [decrypted, setDecrypted] = useState<Array<DecryptedSavedDeck>>([]);
  const [decrypting, setDecrypting] = useState(false);
  const [decryptError, setDecryptError] = useState<string | null>(null);
  const [showUnlock, setShowUnlock] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  useEffect(() => {
    if (session.status === "locked") {
      setShowUnlock(true);
    }
  }, [session.status]);

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

  const openInEditor = (deck: DecryptedSavedDeck) => {
    const { project, finishSettings, name } = projectFromDeckPayload(
      deck.payload
    );
    dispatch(loadProject(project));
    dispatch(loadFinishSettings(finishSettings));
    dispatch(
      setCurrentSavedDeck({
        key: deck.key,
        name,
        serialized: serializeDeckPayload(deck.payload),
      })
    );
    router.push("/editor");
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
      <UnlockModal
        show={showUnlock}
        onCancel={() => setShowUnlock(false)}
        onUnlocked={() => setShowUnlock(false)}
      />
      {session.status === "locked" && !showUnlock && (
        <p>
          <Button onClick={() => setShowUnlock(true)}>
            Unlock my saved decks
          </Button>
        </p>
      )}
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
                  onOpen={openInEditor}
                  onDelete={handleDelete}
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
                    onOpen={openInEditor}
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
