/**
 * The recipient-side view for a per-deck share link ("PR-5, post-v1: per-deck share links" -
 * docs/proposals/proposal-g-user-accounts-saved-decks.md). No sign-in, master key, or
 * passphrase involved - see deckShare.ts's header for why `shareId` is a query param
 * (`?shareId=...`) rather than the spec's literal path-segment shape, and why `shareKey` still
 * travels only in the URL fragment exactly as specified. Split out of pages/shared.tsx (rather
 * than living there directly) for the same reason MyDecksPage.tsx is split from pages/myDecks.tsx
 * - a plain, testable feature component behind a thin page wrapper.
 */

import { useRouter } from "next/router";
import React, { useEffect, useState } from "react";
import Spinner from "react-bootstrap/Spinner";

import { useAppSelector } from "@/common/types";
import {
  DecryptedSharedDeck,
  decryptSharedDeck,
} from "@/features/savedDecks/deckShare";
import { SharedDeckViewer } from "@/features/savedDecks/SharedDeckViewer";
import { APIGetSharedDeck } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";

export function SharedDeckPage() {
  const router = useRouter();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const [shared, setShared] = useState<DecryptedSharedDeck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!router.isReady || backendURL == null) {
      return;
    }
    const shareId =
      typeof router.query.shareId === "string" ? router.query.shareId : null;
    // the shareKey never reaches the server, or Next's own router.query (which only ever
    // reflects the path+query, never the fragment) - read it directly from the browser.
    const shareKeyFragment =
      typeof window !== "undefined" ? window.location.hash.slice(1) : "";
    if (shareId == null || shareKeyFragment.length === 0) {
      setError("This share link is missing its shareId or key.");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    APIGetSharedDeck(backendURL, shareId)
      .then((response) => decryptSharedDeck(response, shareKeyFragment))
      .then((decrypted) => {
        if (!cancelled) {
          setShared(decrypted);
        }
      })
      .catch((thrown) => {
        if (!cancelled) {
          setError(
            thrown instanceof Error
              ? thrown.message
              : "This share link is invalid, expired, or has been revoked."
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router.isReady, router.query.shareId, backendURL]);

  if (loading) {
    return <Spinner animation="border" />;
  }
  if (error != null) {
    return <p className="text-danger">{error}</p>;
  }
  if (shared == null) {
    return null;
  }
  const shareId =
    typeof router.query.shareId === "string" ? router.query.shareId : undefined;
  return (
    <SharedDeckViewer
      backendURL={backendURL as string}
      name={shared.name}
      sharedAt={shared.sharedAt}
      payload={shared.payload}
      shareId={shareId}
    />
  );
}
