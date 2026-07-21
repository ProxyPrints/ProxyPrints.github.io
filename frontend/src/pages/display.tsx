import Head from "next/head";

import { ProjectName } from "@/common/constants";
import { isUnifiedDisplayPageEnabled } from "@/common/featureFlags";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { DisplayPage } from "@/features/display/DisplayPage";
import { GenericErrorPage } from "@/features/ui/GenericErrorPage";
import { ProjectContainer } from "@/features/ui/Layout";
import { useAnyBackendConfigured } from "@/store/slices/backendSlice";
require("bootstrap-icons/font/bootstrap-icons.css");

// Proposal H, Step 1 (docs/proposals/proposal-h-unified-display-page.md) - this route is
// entirely behind NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED per the design doc's §6 migration plan
// ("new route behind a flag"). It renders a real 404-shaped page rather than actually 404ing
// (Next's static export has no server-side route gating) - functionally equivalent from a
// visitor's perspective, since nothing links here while the flag is off.
function DisplayPageOrDefault() {
  const anyBackendConfigured = useAnyBackendConfigured();
  return anyBackendConfigured ? (
    <DisplayPage />
  ) : (
    <NoBackendDefault requirement="any" />
  );
}

export default function Display() {
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
    // ProjectContainer/MaxWidthContainer for the additive mechanism this opts into.
    <ProjectContainer gutter={0} fullWidth>
      <Head>
        <title>Display (Preview)</title>
        <meta
          name="description"
          content={`${ProjectName}'s unified print-sheet display page (in development).`}
        />
      </Head>
      <DisplayPageOrDefault />
    </ProjectContainer>
  );
}
