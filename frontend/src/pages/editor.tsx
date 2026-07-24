import Head from "next/head";

import { ProjectName } from "@/common/constants";
import { isUnifiedDisplayPageEnabled } from "@/common/featureFlags";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { DisplayPage } from "@/features/display/DisplayPage";
import { GenericErrorPage } from "@/features/ui/GenericErrorPage";
import { ProjectContainer } from "@/features/ui/Layout";
import { useAnyBackendConfigured } from "@/store/slices/backendSlice";
require("bootstrap-icons/font/bootstrap-icons.css");

// Proposal H switchover (2026-07-23, issues #231/#272, following up on nav-redesign PR #313) -
// /editor now serves the unified sheet+rail page that used to live at /display, per the owner's
// explicit direction that the swap should be a real route swap (the new page AT /editor), not
// just a nav-label pointing at a separate /display route. /display itself is now a plain
// client-side redirect here (see pages/display.tsx) so old bookmarks/links keep working. The
// classic grid `ProjectEditor` this replaces is fully unrouted - `components/ProjectEditor.tsx`
// and its own child components are left in-tree unchanged (deletion is a separate later cleanup
// decision, not part of this swap) but nothing routes to them anymore.
//
// Still gated behind NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED (confirmed "true" in the production
// deploy variable since 2026-07-18) as a defensive kill switch, same as this page carried at
// /display before the swap - the difference is that flipping the var off now disables the
// ENTIRE editor, since there's no classic fallback left to drop back to (there was, briefly,
// between #87 and this task). See docs/proposals/proposal-h-unified-display-page.md §6 for the
// migration plan this completes (step 5, "flip the default nav entry point to the new page") -
// step 6 (deleting the legacy component files once usage data/owner sign-off allows) is
// deliberately still open, see this PR's own report.
function EditorPageOrDefault() {
  const anyBackendConfigured = useAnyBackendConfigured();
  return anyBackendConfigured ? (
    <DisplayPage />
  ) : (
    <NoBackendDefault requirement="any" />
  );
}

export default function Editor() {
  if (!isUnifiedDisplayPageEnabled()) {
    return (
      <GenericErrorPage
        title="Page Not Found"
        text={["You took a bad turn! Sorry about that."]}
      />
    );
  }
  return (
    // Issue #287 - opts out of the app-wide 1200px ContentMaxWidth cap: at >=1200px viewports
    // with both rails inline, the cap otherwise leaves only ~520px for the center sheet region
    // (1200 - 380 left rail - 300 right rail) where the approved design calls for ~720px (the
    // same width the naturally-uncapped <1200px laptop tier already renders at). See Layout.tsx's
    // ProjectContainer/MaxWidthContainer for the additive mechanism this opts into. (Carried over
    // unchanged from the page's time at /display.)
    <ProjectContainer gutter={0} fullWidth>
      <Head>
        <title>Edit Project</title>
        <meta
          name="description"
          content={`${ProjectName}'s rich project editor.`}
        />
      </Head>
      <EditorPageOrDefault />
    </ProjectContainer>
  );
}
