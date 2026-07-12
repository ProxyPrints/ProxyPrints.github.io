import styled from "@emotion/styled";
import Head from "next/head";
import React, { useEffect, useState } from "react";

import { ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { PrintingTagQueue } from "@/features/printingTags/PrintingTagQueue";
import {
  STARBURST_BACKGROUND_COLOR,
  STARBURST_INNER_COLOR,
  STARBURST_INNER_FRAMES,
  STARBURST_OUTER_COLOR,
  STARBURST_OUTER_FRAMES,
  STARBURST_VIEWBOX,
} from "@/features/printingTags/starburstShape";
import { useElementAnchor } from "@/features/printingTags/useElementAnchor";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import {
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

// "Who's That Pokemon?" style radiating starburst behind the game itself - a jagged
// "explosion" burst (see starburstShape.ts) built from two overlapping SVG polygons rather
// than a static image, so it scales to any container size with no asset to host/maintain.
// Kept off the Footer below, which should still look like the rest of the site's chrome.
const StarburstBackground = styled.div`
  position: relative;
  overflow: hidden;
  background: ${STARBURST_BACKGROUND_COLOR};
  color: white;
  /* text-shadow is an inherited CSS property, so this covers every descendant - needed
     since plain white text loses contrast wherever it crosses the burst below */
  text-shadow: 0 0 6px rgba(0, 0, 0, 0.85), 0 0 2px rgba(0, 0, 0, 0.95);
  border-radius: 0.5rem;
  padding: 1.5rem;
  margin-bottom: 1rem;
`;

// The burst is centred on (and sized relative to) the subject card itself, not the
// container - measured via useElementAnchor - so it stays anchored to the card's own
// position on the page instead of drifting when sibling content (the candidate printing
// grid) grows or shrinks beside it.
const StarburstSvg = styled.svg`
  position: absolute;
  z-index: 0;
  pointer-events: none;
  transform: translate(-50%, -50%);
`;

const StarburstContent = styled.div`
  position: relative;
  z-index: 1;
`;

const BURST_SIZE_FACTOR = 3.4;
const BURST_SIZE_MIN_PX = 420;
const BURST_SIZE_MAX_PX = 1200;

function burstSizePx(cardWidth: number): number {
  return Math.min(
    BURST_SIZE_MAX_PX,
    Math.max(BURST_SIZE_MIN_PX, cardWidth * BURST_SIZE_FACTOR)
  );
}

const STARBURST_FRAME_INTERVAL_MS = 150;

// Cycles through the precomputed jagged frames (see starburstShape.ts) to reproduce the
// reference gif's flicker. Always starts at frame 0 and only starts advancing inside
// useEffect (client-only, post-mount), so server-rendered and first-client-render markup
// stay identical - no hydration mismatch. Skips animating entirely under
// prefers-reduced-motion.
function useStarburstFrame(frameCount: number): number {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const id = setInterval(() => {
      setFrame((previous) => (previous + 1) % frameCount);
    }, STARBURST_FRAME_INTERVAL_MS);
    return () => clearInterval(id);
  }, [frameCount]);

  return frame;
}

function PrintingQueueOrDefault() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  const { containerRef, targetRef, anchor } = useElementAnchor();
  const frame = useStarburstFrame(STARBURST_OUTER_FRAMES.length);

  return remoteBackendConfigured ? (
    <>
      <StarburstBackground ref={containerRef}>
        {anchor != null && (
          <StarburstSvg
            viewBox={STARBURST_VIEWBOX}
            style={{
              top: anchor.y,
              left: anchor.x,
              width: burstSizePx(anchor.width),
              height: burstSizePx(anchor.width),
            }}
          >
            <polygon
              points={STARBURST_OUTER_FRAMES[frame]}
              fill={STARBURST_OUTER_COLOR}
            />
            <polygon
              points={STARBURST_INNER_FRAMES[frame]}
              fill={STARBURST_INNER_COLOR}
            />
          </StarburstSvg>
        )}
        <StarburstContent>
          <h1>Who&apos;s That Planeswalker?</h1>
          <p>
            Test your Magic: the Gathering knowledge! One card at a time, help
            identify which real-world printing each card image depicts -
            contested cards come first, since they need your eyes the most.
          </p>
          <PrintingTagQueue cardAnchorRef={targetRef} />
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
