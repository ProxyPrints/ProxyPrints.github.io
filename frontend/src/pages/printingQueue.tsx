import styled from "@emotion/styled";
import Head from "next/head";
import React from "react";

import { ContentMaxWidth, ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { PrintingTagQueue } from "@/features/printingTags/PrintingTagQueue";
import { STARBURST_BACKGROUND_COLOR } from "@/features/printingTags/starburstShape";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import {
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

// "Who's That Pokemon?" style radiating starburst behind the game itself - a jagged
// "explosion" burst (see starburstShape.ts, rendered inside PrintingTagQueue.tsx alongside
// the subject card so the two stay glued together under position: sticky as the page
// scrolls) built from two overlapping SVG polygons rather than a static image, so it scales
// to any container size with no asset to host/maintain. Full-bleed to the viewport edges
// (rather than confined to the site's normal centered content column) to read as a banner/
// bumper rather than a boxed card - the standard "break out of a centered container" trick,
// with StarburstContent re-establishing the normal centered reading width for the actual
// text/controls inside it. Kept off the Footer below, which should still look like the rest
// of the site's chrome.
const StarburstBackground = styled.div`
  position: relative;
  /* Deliberately clip-path, not overflow: hidden - the card+burst panel inside this uses
     position: sticky (see CardPanel in PrintingTagQueue.tsx), and an overflow value other
     than visible on ANY ancestor of a sticky element - even one that never actually
     scrolls - silently breaks its stickiness (a well-documented CSS gotcha: it changes
     what the sticky element's nearest scrolling ancestor resolves to). clip-path clips the
     same way visually without establishing a scroll container, so it doesn't have that
     side effect. */
  clip-path: inset(0);
  background: ${STARBURST_BACKGROUND_COLOR};
  color: white;
  /* text-shadow is an inherited CSS property, so this covers every descendant - needed
     since plain white text loses contrast wherever it crosses the burst below */
  text-shadow: 0 0 6px rgba(0, 0, 0, 0.85), 0 0 2px rgba(0, 0, 0, 0.95);
  width: 100vw;
  margin-left: calc(50% - 50vw);
  padding: 1.5rem 0;
  margin-bottom: 1rem;
`;

// Sits above the sticky card panel's stacking context (see CardPanel in
// PrintingTagQueue.tsx) so the burst bleeding out from behind the card doesn't cover this
// intro text, at the initial (unscrolled) position where they visually overlap.
const StarburstContent = styled.div`
  position: relative;
  z-index: 1;
  max-width: ${ContentMaxWidth}px;
  margin: 0 auto;
  padding: 0 1.5rem;
`;

function PrintingQueueOrDefault() {
  const remoteBackendConfigured = useRemoteBackendConfigured();

  return remoteBackendConfigured ? (
    <>
      <StarburstBackground>
        <StarburstContent>
          <h1>Who&apos;s That Planeswalker?</h1>
          <p>
            Test your Magic: the Gathering knowledge! One card at a time, help
            identify which real-world printing each card image depicts -
            contested cards come first, since they need your eyes the most.
          </p>
          <PrintingTagQueue />
        </StarburstContent>
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
