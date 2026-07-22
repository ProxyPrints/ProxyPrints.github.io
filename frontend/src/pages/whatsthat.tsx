import styled from "@emotion/styled";
import Head from "next/head";
import React, { useState } from "react";
import Nav from "react-bootstrap/Nav";
import Tab from "react-bootstrap/Tab";

import { ContentMaxWidth, ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { ModerationTab } from "@/features/moderation/ModerationTab";
import { QuestionFeed } from "@/features/questionFeed/QuestionFeed";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import { useGetWhoamiQuery } from "@/store/api";
import {
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

type WhatsThatTab = "feed" | "moderation";

// wtc-redesign-spec.md's "hero blue field" theme color (W6/W7, issue #305) - the deep-blue
// vignette below (SUPERSEDES the 2026-07-18 "the loud #ff4719 stays" decision, see
// docs/features/printing-tags.md). Also drives the PWA theme-color/manifest retint below.
export const HERO_FIELD_BLUE_DEEP = "#123a6b";

// Radiating starburst behind the game itself - a jagged
// "explosion" burst (see starburstShape.ts, rendered inside QuestionFeed.tsx alongside
// the subject card) built from two overlapping SVG polygons rather than a static image, so it
// scales to any container size with no asset to host/maintain. Full-bleed to the viewport
// edges (rather than confined to the site's normal centered content column) to read as a
// banner/bumper rather than a boxed card - the standard "break out of a centered container"
// trick, with StarburstContent re-establishing the normal centered reading width for the
// actual text/controls inside it. Kept off the Footer below, which should still look like the
// rest of the site's chrome.
const StarburstBackground = styled.div`
  position: relative;
  /* Deliberately clip-path, not overflow: hidden - QuestionFeed.tsx's mobile HeroCardArea
     uses position: sticky for its condensed card bar, and an overflow value other than
     visible on ANY ancestor of a sticky element - even one that never actually scrolls -
     silently breaks its stickiness (a well-documented CSS gotcha: it changes what the sticky
     element's nearest scrolling ancestor resolves to). clip-path clips the same way visually
     without establishing a scroll container, so it doesn't have that side effect. */
  clip-path: inset(0);
  /* Deep-blue radial vignette (wtc-redesign-spec.md W6, issue #305) - retires the page's old
     loud #ff4719 orange full-bleed field, reconciling with the new sitewide orange accent
     (#302's retheme) rather than clashing with it. Sells the "blue and white starbursts"
     hero (#305) and matches the quiz-reveal reference. */
  background: radial-gradient(
    120% 130% at 30% 42%,
    #1a4f8a 0%,
    ${HERO_FIELD_BLUE_DEEP} 46%,
    #0f2537 78%
  );
  width: 100vw;
  margin-left: calc(50% - 50vw);
  padding: 1.5rem 0 2rem;
  margin-bottom: 1rem;

  /* The questions region simply inherits the sitewide theme now (wtc-redesign-spec.md W7) -
     the ACCENT_NAVY override this page used to carry existed only because buttons/links/pills
     sat on the old #ff4719 orange field (nothing light cleared AA on it). Off that field and
     onto the standard dark body (#0f2537, the same color this gradient bottoms out to), the
     sitewide accent #df6919 already clears AA (4.61:1 - theme-spec Open Q1), so there is
     nothing left to override here. */
`;

// Sits above CardPanel's own local stacking context (see cardPanel.tsx) so the burst bleeding
// out from behind the card doesn't cover the words/questions columns rendered alongside it.
const StarburstContent = styled.div`
  position: relative;
  z-index: 1;
  max-width: ${ContentMaxWidth}px;
  margin: 0 auto;
  padding: 0 1.5rem;
`;

// The wordmark's sliced-word teaser (WhatsThatWords, rendered inside QuestionFeed.tsx's hero
// grid) is now the page's visual title (wtc-redesign-spec.md W4/W5) - this stays a real,
// visually-hidden <h1> purely so the page keeps a semantic heading and accessible name for
// screen readers/the document outline, the same guarantee the old BrandLockup <h1> gave.
const VisuallyHiddenHeading = styled.h1`
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
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
          <VisuallyHiddenHeading>What&apos;s That Card?</VisuallyHiddenHeading>
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
        {/* PWA installability (mobile funnel pass) - deliberately scoped to /whatsthat only
            (start_url/scope both "/whatsthat" in the manifest itself), not a site-wide
            manifest on _document.tsx: the game is the installable "app" here, not the whole
            catalog/editor, and Next.js's per-page <Head> content lands only in this route's
            own generated HTML under `output: "export"`'s static per-page output - so this
            link is genuinely absent from every other page's markup, not just visually unused
            there. Icons generated from whatsthat-mark.svg (the branding integration's own
            source asset - see docs/features/artist-support-links.md's sibling doc,
            docs/features/printing-tags.md's "Branding integration" bullet) via a one-off
            Playwright rasterization (not committed - see this task's own report), not a new
            build-time asset pipeline; PNGs are checked in directly like the SVGs themselves.
            Retinted to HERO_FIELD_BLUE_DEEP alongside the manifest (issue #305/W6's blue hero
            field) - the installed-app chrome now matches the page's own field color instead of
            the retired #ff4719 orange. */}
        <link rel="manifest" href="/whatsthat-manifest.json" />
        <meta name="theme-color" content={HERO_FIELD_BLUE_DEEP} />
        <link rel="apple-touch-icon" href="/whatsthat-icon-192.png" />
      </Head>
      <PrintingQueueOrDefault />
    </ProjectContainer>
  );
}
