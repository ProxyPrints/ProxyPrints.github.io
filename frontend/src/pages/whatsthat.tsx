import styled from "@emotion/styled";
import Head from "next/head";
import React, { useState } from "react";
import Nav from "react-bootstrap/Nav";
import Tab from "react-bootstrap/Tab";

import { ContentMaxWidth, ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { AuthWidget } from "@/features/moderation/AuthWidget";
import { ModerationTab } from "@/features/moderation/ModerationTab";
import { STARBURST_BACKGROUND_COLOR } from "@/features/printingTags/starburstShape";
import { QuestionFeed } from "@/features/questionFeed/QuestionFeed";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import { useGetWhoamiQuery } from "@/store/api";
import {
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

type WhatsThatTab = "feed" | "moderation";

// Radiating starburst behind the game itself - a jagged
// "explosion" burst (see starburstShape.ts, rendered inside QuestionFeed.tsx alongside
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
     position: sticky (see CardPanel in cardPanel.tsx), and an overflow value other
     than visible on ANY ancestor of a sticky element - even one that never actually
     scrolls - silently breaks its stickiness (a well-documented CSS gotcha: it changes
     what the sticky element's nearest scrolling ancestor resolves to). clip-path clips the
     same way visually without establishing a scroll container, so it doesn't have that
     side effect. */
  clip-path: inset(0);
  background: ${STARBURST_BACKGROUND_COLOR};
  /* Black reads better here than the white this started as - checked contrast against both
     the orange background (~6.2:1) and the starburst's own blue (~6.2:1), both clearly
     better than white's ~3.4:1 against either. */
  color: black;
  /* text-shadow is an inherited CSS property, so this covers every descendant - needed
     since plain black text loses definition wherever it crosses the burst below (a light
     halo behind dark text, mirroring the dark halo this used behind the white text it
     replaced) */
  text-shadow: 0 0 6px rgba(255, 255, 255, 0.85),
    0 0 2px rgba(255, 255, 255, 0.95);
  width: 100vw;
  margin-left: calc(50% - 50vw);
  padding: 1.5rem 0;
  margin-bottom: 1rem;
`;

// Sits above the sticky card panel's stacking context (see CardPanel in
// cardPanel.tsx) so the burst bleeding out from behind the card doesn't cover this
// intro text, at the initial (unscrolled) position where they visually overlap.
const StarburstContent = styled.div`
  position: relative;
  z-index: 1;
  max-width: ${ContentMaxWidth}px;
  margin: 0 auto;
  padding: 0 1.5rem;
`;

// The starburst+card assembly anchors to the right of the page (see QuestionFeed.tsx's
// column order), so the intro copy above it reads right-to-left too, keeping the whole
// header visually aligned with what sits below it rather than starting from the opposite edge.
const IntroText = styled.div`
  text-align: right;
`;

function PrintingQueueOrDefault() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  const [activeTab, setActiveTab] = useState<WhatsThatTab>("feed");
  // gating the tab is presentation only - every moderation endpoint 403s non-moderators
  // regardless (see docs/features/moderation.md)
  const whoami = useGetWhoamiQuery();
  const isModerator = whoami.data?.moderator === true;

  return remoteBackendConfigured ? (
    <>
      <StarburstBackground>
        <StarburstContent>
          <IntroText>
            <h1>What&apos;s That Card?</h1>
            <p>
              Test your Magic: the Gathering knowledge! One card at a time, help
              identify which real-world printing, artist, or descriptor tag each
              card image depicts - contested and machine-suggested cards come
              first, since they need your eyes the most.
            </p>
          </IntroText>
          <AuthWidget />
          {isModerator ? (
            <Tab.Container
              activeKey={activeTab}
              onSelect={(key) => {
                if (key) setActiveTab(key as WhatsThatTab);
              }}
            >
              <Nav variant="pills" className="mb-3">
                <Nav.Item>
                  <Nav.Link eventKey="feed">Question Feed</Nav.Link>
                </Nav.Item>
                <Nav.Item>
                  <Nav.Link eventKey="moderation">Moderation</Nav.Link>
                </Nav.Item>
              </Nav>
              <Tab.Content>
                {/* mountOnEnter on both, unmountOnExit only on moderation - the question feed's
                    own behavior/mount timing is unchanged from before this switcher existed
                    for the common (non-moderator) case, matching the pre-redesign printing/
                    artist/tag tab switcher's identical rationale for the same asymmetry. */}
                <Tab.Pane eventKey="feed" mountOnEnter>
                  <QuestionFeed />
                </Tab.Pane>
                <Tab.Pane eventKey="moderation" mountOnEnter unmountOnExit>
                  <ModerationTab />
                </Tab.Pane>
              </Tab.Content>
            </Tab.Container>
          ) : (
            <QuestionFeed />
          )}
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
        <title>{`${projectName} What's That Card?`}</title>
        <meta
          name="description"
          content={`Test your Magic: the Gathering knowledge and help tag which real-world printing each card image in ${ProjectName} depicts.`}
        />
      </Head>
      <PrintingQueueOrDefault />
    </ProjectContainer>
  );
}
