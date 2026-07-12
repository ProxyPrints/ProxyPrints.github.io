import styled from "@emotion/styled";
import Head from "next/head";
import React from "react";

import { ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { PrintingTagQueue } from "@/features/printingTags/PrintingTagQueue";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import {
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

// "Who's That Pokemon?" style alternating diagonal stripes behind the game itself - kept
// off the Footer below, which should still look like the rest of the site's chrome.
const StripedBackground = styled.div`
  background: repeating-linear-gradient(
    45deg,
    #241b3a,
    #241b3a 40px,
    #3d2a63 40px,
    #3d2a63 80px
  );
  color: white;
  border-radius: 0.5rem;
  padding: 1.5rem;
  margin-bottom: 1rem;
`;

function PrintingQueueOrDefault() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  return remoteBackendConfigured ? (
    <>
      <StripedBackground>
        <h1>Who&apos;s That Planeswalker?</h1>
        <p>
          Test your Magic: the Gathering knowledge! One card at a time, help
          identify which real-world printing each card image depicts - contested
          cards come first, since they need your eyes the most.
        </p>
        <PrintingTagQueue />
      </StripedBackground>
      <Footer />
    </>
  ) : (
    <NoBackendDefault requirement="remote" />
  );
}

export default function PrintingQueue() {
  const projectName = useProjectName();
  return (
    <ProjectContainer>
      <Head>
        <title>{`${projectName} Who's That Planeswalker?`}</title>
        <meta
          name="description"
          content={`Test your Magic: the Gathering knowledge and help tag which real-world printing each card image in ${ProjectName} depicts.`}
        />
      </Head>
      <PrintingQueueOrDefault />
    </ProjectContainer>
  );
}
