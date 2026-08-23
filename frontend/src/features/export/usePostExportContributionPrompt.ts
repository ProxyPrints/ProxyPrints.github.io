/**
 * React-side wiring for the post-export contribution prompt - see postExportContributionPrompt.ts
 * for the pure session-flag/download-success logic this hook composes. `notifyExportSucceeded`
 * is the only thing a caller needs to invoke, from wherever it already knows an export just
 * genuinely succeeded (DisplayPage.tsx's own generatePdf/saveToDrive wrappers,
 * PDFGenerator.tsx's downloadPDF/saveToDrive button handlers) - this hook owns whether that
 * translates into actually showing the prompt (never twice in one session).
 */
import { useCallback, useEffect, useState } from "react";

import {
  hasShownPostExportContributionPromptThisSession,
  markPostExportContributionPromptShown,
  shouldShowPostExportContributionPrompt,
} from "@/features/export/postExportContributionPrompt";

export interface PostExportContributionPromptState {
  visible: boolean;
  notifyExportSucceeded: () => void;
  dismiss: () => void;
}

// Longer than Toasts.tsx's shared 7s autohide (PostExportContributionPrompt.tsx's own module
// comment explains why a CTA needs more read time than a glance-and-vanish notice) but still
// finite, so the prompt doesn't sit on screen for the rest of the session if the user never
// interacts with it.
const AUTO_DISMISS_DELAY_MS = 20000;

export function usePostExportContributionPrompt(): PostExportContributionPromptState {
  const [visible, setVisible] = useState(false);

  const notifyExportSucceeded = useCallback(() => {
    if (
      !shouldShowPostExportContributionPrompt(
        hasShownPostExportContributionPromptThisSession()
      )
    ) {
      return;
    }
    // Marked at show-time, not only on dismiss - "never repeats within a session" means the
    // FIRST export's prompt is the only one for the whole session, whether the user reads it,
    // dismisses it, or just exports again without ever interacting with it.
    markPostExportContributionPromptShown();
    setVisible(true);
  }, []);

  const dismiss = useCallback(() => setVisible(false), []);

  useEffect(() => {
    if (!visible) {
      return;
    }
    const timeoutId = window.setTimeout(dismiss, AUTO_DISMISS_DELAY_MS);
    return () => window.clearTimeout(timeoutId);
  }, [visible, dismiss]);

  return { visible, notifyExportSucceeded, dismiss };
}
