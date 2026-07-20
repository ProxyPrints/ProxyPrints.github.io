/**
 * Issue #166 - the post-export contribution prompt itself. Purely presentational (see
 * usePostExportContributionPrompt.ts for the show-once-per-session logic) - a dismissible
 * Alert, not a self-hiding Toast (Toasts.tsx's own 7s autohide is wrong for a CTA the user
 * should be able to actually act on, not just glance at before it vanishes), following the same
 * `<Alert dismissible onClose={...}>` shape QuestionFeed.tsx's own rate-limit notice already
 * uses. Routes into the EXISTING "What's That Card?" vote-queue funnel (docs/features/
 * printing-tags.md) via the same /whatsthat route Navbar.tsx and HomepagePanel.tsx already link
 * to - no parallel entry point invented for this.
 */
import Link from "next/link";
import React from "react";
import Alert from "react-bootstrap/Alert";

export interface PostExportContributionPromptProps {
  show: boolean;
  onDismiss: () => void;
}

export function PostExportContributionPrompt({
  show,
  onDismiss,
}: PostExportContributionPromptProps) {
  if (!show) {
    return null;
  }
  return (
    <Alert
      variant="info"
      dismissible
      onClose={onDismiss}
      className="mb-0"
      data-testid="post-export-contribution-prompt"
    >
      <p className="mb-2">
        Your PDF is ready. If you recognised one of these printings, a quick
        confirmation on <b>What&apos;s That Card?</b> helps keep the catalog
        accurate for the next person - one tap, never required.
      </p>
      <Link href="/whatsthat" passHref legacyBehavior>
        <Alert.Link as="a" data-testid="post-export-contribution-prompt-link">
          Help identify a card
        </Alert.Link>
      </Link>
    </Alert>
  );
}
