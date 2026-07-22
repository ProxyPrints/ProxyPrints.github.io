/**
 * Proposal H ADDENDUM D9/F2 (docs/proposals/proposal-h-display-layout-spec.md, issue #275) - the
 * right-rail pinned Finish footer: `Save Deck` and `Print / Export →` as CO-EQUAL `btn-primary`
 * buttons of equal width side by side, a secondary `Export ▾` (`DisplayExportMenu.tsx`,
 * lightweight XML/Card Images/Decklist only) below them, and the compact "✓ Draft backed up
 * locally" note. Replaces the old three-button "Prepare Print footer" stack (Export ▾/Save PDF
 * to Google Drive/Generate PDF) - the memory-heavy Generate PDF and Save PDF to Google Drive
 * operations move OUT of this footer entirely, to the Print page (D10/pages/print.tsx), so this
 * footer itself can never trigger the OOM D9's own hard constraint warns about ("save deck
 * should come before PDF completes because we have to rely on clients available mem for the
 * PDF").
 *
 * `Save Deck` reuses useSaveDeckFlow.ts's own passphrase-setup/unlock/save modal chain (the same
 * one SavedDeckPanel.tsx's toolbar Save button already drives) - this component owns its OWN
 * hook instance (a second, independent one from the toolbar's), so both buttons work
 * independently and neither can leave the other's modal state stuck open.
 *
 * Anonymous sessions: D9(2)'s "anonymous users' nudge routes through sign-in first" (server save
 * is authenticated-only by construction) applies here too, not just to the promotion toast - the
 * button becomes a direct sign-in link (the same backendURL+loginUrl+`?next=` construction
 * AuthWidget.tsx already uses) labeled "Sign in to Save" rather than a disabled/dead control, so
 * an anonymous user always has somewhere to go from this footer, never a no-op button.
 */
import React, { useEffect, useState } from "react";
import Button from "react-bootstrap/Button";

import { useAppSelector } from "@/common/types";
import {
  DownloadManager,
  OpenDownloadManagerButton,
} from "@/features/download/DownloadManager";
import { DisplayExportMenu } from "@/features/export/DisplayExportMenu";
import { useSaveDeckFlow } from "@/features/savedDecks/useSaveDeckFlow";
import { useGetWhoamiQuery } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";

interface FinishFooterProps {
  /** useProjectDraftBackup's own `hasBackedUpThisSession` - drives the compact note below the
   * buttons. Passed in rather than re-instantiated here, since DisplayPage already owns the one
   * hook instance actually driving the debounced writes. */
  hasBackedUpThisSession: boolean;
  /** usePrePrintSaveGate's own `startPrintFlow` - runs the D9(3) persist-before-navigate sequence
   * before any PDF render begins. */
  onPrintClick: () => void;
}

export function FinishFooter({
  hasBackedUpThisSession,
  onPrintClick,
}: FinishFooterProps) {
  const { element, triggerSave, isAuthenticated, isProjectEmpty } =
    useSaveDeckFlow();
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const whoami = useGetWhoamiQuery();

  // Nav+footer redesign (2026-07-22, N10) - the cloud download-queue counter/manager used to
  // live in the global navbar (OpenDownloadManagerButton + DownloadManager), cut from there
  // per the redesign since it only ever counted in-browser export downloads (XML/card
  // images/decklist/PDF), never the abandoned desktop tool. This is one of its two new mounts
  // (the other is pages/print.tsx, which owns the memory-heavy PDF/desktop-tool downloads this
  // footer's own DisplayExportMenu deliberately excludes) - both read the same global
  // fileDownloadsSlice, so either one shows every download regardless of where it started;
  // mounting in both closes the gap where a download enqueued on the other page wouldn't be
  // visible without navigating back.
  const [showDownloadManager, setShowDownloadManager] = useState(false);

  // window isn't available during the static export build - resolved client-only, mirroring
  // AuthWidget.tsx's own identical pattern for the exact same `?next=` round-trip.
  const [currentHref, setCurrentHref] = useState<string | null>(null);
  useEffect(() => {
    setCurrentHref(window.location.href);
  }, []);

  const loginHref =
    backendURL != null && whoami.data?.loginUrl != null && currentHref != null
      ? `${backendURL}${whoami.data.loginUrl}?next=${encodeURIComponent(
          currentHref
        )}`
      : undefined;

  return (
    <div className="d-grid gap-2" data-testid="display-finish-footer">
      <div className="d-flex gap-2">
        {isAuthenticated ? (
          <Button
            variant="primary"
            className="flex-fill"
            disabled={isProjectEmpty}
            onClick={() => triggerSave()}
            data-testid="finish-footer-save-deck"
          >
            Save Deck
          </Button>
        ) : (
          <Button
            variant="primary"
            className="flex-fill"
            href={loginHref}
            disabled={loginHref == null}
            title="Sign in to save decks & track your confirmations"
            data-testid="finish-footer-save-deck-signin"
          >
            Sign in to Save
          </Button>
        )}
        <Button
          variant="primary"
          className="flex-fill"
          onClick={onPrintClick}
          data-testid="finish-footer-print-export"
        >
          Print / Export &rarr;
        </Button>
      </div>
      <div className="d-flex gap-2 align-items-center">
        {/* Issue #241 (design doc §5's export-beyond-PDF row) - XML/Card Images/Decklist,
            unchanged and unforked; the ONLY export surface this footer still owns directly, per
            D9's own "memory-heavy operations move OUT" line. */}
        <DisplayExportMenu />
        <OpenDownloadManagerButton
          handleClick={() => setShowDownloadManager(true)}
        />
      </div>
      <DownloadManager
        show={showDownloadManager}
        handleClose={() => setShowDownloadManager(false)}
      />
      {hasBackedUpThisSession && (
        <div
          className="text-muted small text-center"
          data-testid="finish-footer-draft-note"
        >
          <i className="bi bi-check-circle-fill text-success me-1" />
          Draft backed up locally
        </div>
      )}
      {element}
    </div>
  );
}
