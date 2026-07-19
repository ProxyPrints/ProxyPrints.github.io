import styled from "@emotion/styled";
import Head from "next/head";
import React, { useState } from "react";
import Nav from "react-bootstrap/Nav";
import Tab from "react-bootstrap/Tab";

import { ContentMaxWidth, ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
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

// Page-scoped accent override (owner-directed, 2026-07-18, closing the /whatsthat visual
// diagnosis's orange-background question): the loud #ff4719 background stays - it's the
// page's deliberate identity - but the site-wide theme accent (--bs-primary/link color,
// #4c9be8) measures a WCAG contrast ratio of just 1.16:1 against it, nowhere close to AA's
// 4.5:1 for text. Even pure white only reaches 3.41:1 against this specific orange (a
// mid-luminance, highly saturated color - no light tint of ANY hue clears 4.5:1 against it;
// only a sufficiently dark one does, same reason StarburstBackground below already settled on
// black body text over the white it started with). Derived from Superhero's own info/cyan
// (#5bc0de) by uniform multiplicative darkening (preserves hue/saturation, only reduces
// luminance) until AA-for-text is comfortably cleared: measured background-orange contrast
// 4.60:1 (passes 4.5 AA-normal-text), white-on-it 15.68:1 (comfortably passes AA on the
// button side too). The override lives ON StarburstBackground below (not a separate wrapper) -
// exactly the element whose own background IS the orange, and NOT the Footer (a sibling
// outside it, rendered by PrintingQueueOrDefault below), which sits on the standard dark body
// background where the site-wide accent already has good contrast and must stay unchanged.
// Nothing outside this page's own render tree is touched, so nothing leaks to other routes.
// Bootstrap 5.2 reads --bs-link-color-rgb at the link's own point of use (so an ancestor
// override reaches it directly), but bakes button/nav-pills colors into component-local custom
// properties at SASS-compile time (--bs-btn-bg, --bs-nav-pills-link-active-bg etc. on
// .btn-primary/.nav-pills themselves, not a var() reference to --bs-primary) - each needs its
// own override here rather than a single --bs-primary swap covering everything.
const ACCENT_NAVY = "#12262c";
const ACCENT_NAVY_HOVER = "#1c343c";
const ACCENT_NAVY_ACTIVE = "#0c1c21";
const ACCENT_NAVY_RGB = "18, 38, 44";

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

  --bs-link-color-rgb: ${ACCENT_NAVY_RGB};
  --bs-link-hover-color-rgb: ${ACCENT_NAVY_RGB};

  /* "Filter by attribute" / "Hide filters" (QuestionFeed.tsx) is a Button variant="link", not
     a plain <a> - .btn-link reads its color from --bs-btn-color (not --bs-link-color-rgb), and
     unlike .btn-primary this one genuinely IS custom-property-driven with no bootswatch
     hardcode (bootswatch's per-variant background loop only covers $theme-colors, and "link"
     isn't one), so no extra literal-property fallback is needed here. */
  .btn-link {
    --bs-btn-color: ${ACCENT_NAVY};
    --bs-btn-hover-color: ${ACCENT_NAVY_HOVER};
    --bs-btn-active-color: ${ACCENT_NAVY_ACTIVE};
    --bs-btn-focus-shadow-rgb: ${ACCENT_NAVY_RGB};
  }

  /* Level 3's "Confirm & continue" (QuestionFeed.tsx) is this page's only variant="primary"
     button - hover/active are simple lighten/darken steps off the AA-verified base, not
     independently contrast-checked (the base and its white text are the two ratios that
     matter for AA; interaction-state tints don't carry their own text-legibility burden).
     background-color/border-color set directly (not just the --bs-btn-bg/-border-color custom
     properties) because bootswatch's Superhero theme (_bootswatch.scss) hardcodes a LITERAL
     background-color on .btn-primary itself, at the same specificity as Bootstrap's own
     var(--bs-btn-bg)-based .btn rule and later in the compiled source order - it wins the
     cascade over any custom-property override alone, found by comparing the queried
     --bs-btn-bg value (correctly overridden) against the actually-rendered background-color
     (still the old theme blue) on a live element. Hover/active/focus DON'T have this problem
     (bootswatch only hardcodes the base fill, not those states), so those stay custom-property-
     only. */
  .btn-primary {
    --bs-btn-color: #fff;
    --bs-btn-bg: ${ACCENT_NAVY};
    --bs-btn-border-color: ${ACCENT_NAVY};
    --bs-btn-hover-color: #fff;
    --bs-btn-hover-bg: ${ACCENT_NAVY_HOVER};
    --bs-btn-hover-border-color: ${ACCENT_NAVY_HOVER};
    --bs-btn-active-color: #fff;
    --bs-btn-active-bg: ${ACCENT_NAVY_ACTIVE};
    --bs-btn-active-border-color: ${ACCENT_NAVY_ACTIVE};
    --bs-btn-focus-shadow-rgb: ${ACCENT_NAVY_RGB};
    color: #fff;
    background-color: ${ACCENT_NAVY};
    border-color: ${ACCENT_NAVY};
  }

  /* The moderator tab switcher's active pill (Nav variant="pills" below). */
  .nav-pills {
    --bs-nav-pills-link-active-bg: ${ACCENT_NAVY};
  }
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

// Branding integration (frontend-polish package) - the mark+wordmark lockup
// (frontend/public/whatsthat-composite.svg, sourced from the assets/whatsthat-branding branch;
// gradient id wtc-grad-comp is pre-namespaced there specifically so it can't collide with the
// mark-only/wordmark-only SVGs' own wtc-grad-mark/wtc-grad-word ids if more than one ever ends
// up on the same page at once - none currently do, but the namespacing was already done
// upstream of this integration, not invented here). Replaces the plain text <h1> this page had
// - wrapped in an actual <h1> (not just a bare <img>) so the page's semantic heading and its
// accessible name both survive the swap to a screen reader/outline view, exactly as they were
// before, just rendered as the real logo now. `right` alignment (inline like text, so IntroText's
// own text-align: right lines it up with the paragraph below it, same as the text heading did).
// Sized by width with a natural aspect-ratio height - the SVG's own viewBox is a wide ~2.34:1
// lockup, comfortable up to the column's own max-width without ever forcing IntroText past it.
const BrandLockup = styled.img`
  width: min(480px, 100%);
  height: auto;
  vertical-align: middle;
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
            <h1 className="mb-2">
              <BrandLockup
                src="/whatsthat-composite.svg"
                alt="What's That Card?"
                data-testid="whatsthat-brand-lockup"
              />
            </h1>
            <p>
              Test your Magic: the Gathering knowledge! One card at a time, help
              identify which real-world printing, artist, or descriptor tag each
              card image depicts - contested and machine-suggested cards come
              first, since they need your eyes the most.
            </p>
          </IntroText>
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
