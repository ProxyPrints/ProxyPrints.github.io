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

// "Who's That Pokemon?" style radiating starburst behind the game itself, matching the
// real TV bumper's look (deep navy background, bright yellow sunburst rays radiating from
// center) - a CSS repeating-conic-gradient rather than a static image, so it scales to any
// container size with no asset to host/maintain. The ::before layer is oversized (250% of
// the container, centered) so the rays fill the whole container edge-to-edge instead of
// visibly terminating in a circle partway through it. Kept off the Footer below, which
// should still look like the rest of the site's chrome.
const StarburstBackground = styled.div`
  position: relative;
  overflow: hidden;
  background: #12123a;
  color: white;
  /* text-shadow is an inherited CSS property, so this covers every descendant - needed
     since plain white text loses contrast wherever it crosses one of the bright yellow
     rays below */
  text-shadow: 0 0 6px rgba(0, 0, 0, 0.85), 0 0 2px rgba(0, 0, 0, 0.95);
  border-radius: 0.5rem;
  padding: 1.5rem;
  margin-bottom: 1rem;

  &::before {
    content: "";
    position: absolute;
    top: 50%;
    left: 50%;
    width: 250%;
    height: 250%;
    transform: translate(-50%, -50%);
    background: repeating-conic-gradient(#ffd400 0deg 9deg, #12123a 9deg 18deg);
    opacity: 0.9;
    z-index: 0;
  }

  > * {
    position: relative;
    z-index: 1;
  }
`;

function PrintingQueueOrDefault() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  return remoteBackendConfigured ? (
    <>
      <StarburstBackground>
        <h1>Who&apos;s That Planeswalker?</h1>
        <p>
          Test your Magic: the Gathering knowledge! One card at a time, help
          identify which real-world printing each card image depicts - contested
          cards come first, since they need your eyes the most.
        </p>
        <PrintingTagQueue />
      </StarburstBackground>
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
