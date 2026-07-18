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
    <ProjectContainer gutter={0}>
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
