import styled from "@emotion/styled";
import Head from "next/head";
import React, { useState } from "react";
import Nav from "react-bootstrap/Nav";
import Tab from "react-bootstrap/Tab";

import { ContentMaxWidth, ProjectName } from "@/common/constants";
import { useNavbarHeight } from "@/common/useNavbarHeight";
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
// Fix round (PR #305/#308 owner review): PrintingQueueOrDefault below wraps StarburstBackground
// + Footer in this flex column instead of two plain siblings - QuestionFeed.tsx's own
// HERO_MAX_HEIGHT used to reserve `100dvh - navbar - 2rem` for the hero grid alone, which
// ignored BOTH this element's own padding/margin (4.5rem total, not the flat 2rem it assumed)
// AND Footer's entire height below it - so the true total content height regularly exceeded
// ContentContainer's (Layout.tsx) available height even when the navbar-height math was
// otherwise exactly right, forcing ContentContainer's own scrollbar to activate and the "hero
// stays pinned" invariant (owner addendum, wtc-redesign-spec.md) to fail live despite passing
// CI (confirmed via a real wheel-scroll + boundingBox() diff - a scrollTop-only assertion on
// the inner questions box never exercises this outer container at all). Flex does the
// arithmetic instead of a hand-maintained calc: Footer sizes to its own natural content height
// as always, and StarburstBackground (flex: 1 1 auto; min-height: 0 below) claims exactly
// whatever's left, so it structurally can't drift out of sync with Footer's real height again.
// Height-constrained at every width (`useNavbarHeight` below, not the static NavbarHeight
// constant - see that hook's own comment for why).
//
// Fix round (owner live-review, "portrait static top block") - this used to only bound height
// at >= md, leaving the whole page free to scroll normally below md (matching the mobile
// sticky-bar design that design intended). That design is gone (see HeroCardArea and
// QuestionFeed.tsx's own comments) - below md the reference card, its name/badge/question text,
// and the static "Filter by attribute"/"None of these" action row must now all be reachable
// with zero scrolling, and only the candidate row below them scrolls (horizontally). That's only
// possible if the whole hero is bounded to the viewport at narrow widths too, the same way it
// already was at >= md, so QuestionFeedResponsive.spec.ts's Pixel-7 "no page scroll needed"
// assertion has a real, resolvable height to size the candidate row's remaining space against.
const PageColumn = styled.div<{ $navbarHeight: number }>`
  display: flex;
  flex-direction: column;
  height: calc(100dvh - ${(props) => props.$navbarHeight}px);
`;

const StarburstBackground = styled.div`
  position: relative;
  /* clip-path, not overflow: hidden - SUPERSEDED reasoning (this used to protect
     QuestionFeed.tsx's mobile HeroCardArea's own position: sticky condensed card bar, since
     an overflow value other than visible on ANY ancestor of a sticky element silently breaks
     its stickiness). That mobile sticky bar is gone (fix round, owner live-review, "portrait
     static top block" - see HeroCardArea's own comment), but clip-path is kept anyway - it
     clips the full-bleed background the same way overflow: hidden would, with no functional
     downside now that stickiness is no longer a consideration either way. */
  clip-path: inset(0);
  /* Deep-blue field (wtc-redesign-spec.md W6, issue #305) - retires the page's old loud
     #ff4719 orange full-bleed field, reconciling with the new sitewide orange accent (#302's
     retheme) rather than clashing with it. Sells the "blue and white starbursts" hero (#305)
     and matches the quiz-reveal reference.
     Fix round (PR #305/#308 owner review, "the blue fade feels unnatural") - the original
     three-stop radial (a lighter highlight fading through the deep blue down to a much darker
     near-black edge, 78% away) read as a much stronger vignette than intended. Flattened to
     a small, subtle highlight around the starburst's own center that settles into a flat
     deep blue well before the edges (no third, darker stop at all - the
     gradient simply has nothing left to fade toward past its one real transition), so the
     field reads as near-flat deep blue rather than a spotlight/vignette effect. The starburst
     itself (BurstSvg/HoverBurst, unchanged) is still blue/white as approved. */
  background: radial-gradient(
    120% 120% at 30% 40%,
    #1d4d82 0%,
    ${HERO_FIELD_BLUE_DEEP} 55%
  );
  width: 100vw;
  margin-left: calc(50% - 50vw);
  /* Fix round (owner blocker, post-#310; extended below md by the "portrait static top block"
     fix round) - originally 1.5rem/2rem/1rem, trimmed to 0.5rem/0/0 at >= md only, since below
     md the whole page used to scroll normally (PageColumn had no explicit height there) and
     this padding/margin cost nothing structurally. Now that PageColumn bounds height at every
     width (see its own comment), the trimmed values apply everywhere - every pixel here is a
     direct subtraction from HeroGrid's own bounded height (the same budget the word-stack
     fix in WhatsThatWords.tsx and HeroGrid's own row-gap trim in QuestionFeed.tsx also draw
     from), and the phone-sized hero (reference card, its text, the static action row, and the
     candidate row) needs every one of those pixels back just as much as the desktop hero does.
     padding-top stays a nonzero 0.5rem (unlike the other two) purely so the burst/card visuals
     below the fixed navbar keep a little breathing room rather than touching it edge-to-edge. */
  padding: 0.5rem 0 0;
  margin-bottom: 0;
  flex: 1 1 auto;
  min-height: 0;

  /* Fix round (owner live-review, "portrait static top block") - Footer.tsx's own responsive
     layout stacks its columns vertically below md, running considerably taller there than at
     >= md (confirmed empirically - a real Playwright run at 360px showed this area crushed to
     ~4px tall, Footer rendering at its full natural height instead, once PageColumn started
     bounding height below md too). min-height: 0 above lets this area shrink to make room for
     Footer's own natural size WHENEVER that combined total still fits PageColumn's own bounded
     height (true at >= md, where Footer is compact) - but Footer's own default min-height: auto
     gives it an un-overridable floor at its own natural content size, so on a viewport where
     Footer's real (stacked, multi-row) mobile height alone approaches or exceeds PageColumn's
     entire budget, flexbox has nowhere else to draw the deficit from and crushes THIS box
     instead, toward zero - exactly backwards from the actual priority (the hero, not Footer, is
     what the whole "static top block/scrollable candidate row" redesign needs protected).
     min-height: 100% below md restores that priority: this box now has a hard floor at
     PageColumn's own FULL height, so if Footer's natural size can't also fit inside that budget,
     Footer is the one pushed below PageColumn's own bottom edge instead - still fully reachable,
     just via the page's own ordinary scroll (Layout.tsx's ContentContainer), the same way any
     long page's footer normally is. Scoped to below md only - >= md's existing "genuinely share
     the fixed budget with Footer, whichever is shorter" behavior (Footer fully visible with no
     scroll needed) is unchanged; only below md gets the hard floor, since only below md does
     Footer's own real height threaten to exceed the budget in the first place. */
  @media (max-width: 767.98px) {
    min-height: 100%;
  }

  /* The questions region simply inherits the sitewide theme now (wtc-redesign-spec.md W7) -
     the ACCENT_NAVY override this page used to carry existed only because buttons/links/pills
     sat on the old #ff4719 orange field (nothing light cleared AA on it). Off that field and
     onto the standard dark body (#0f2537, the same color this gradient bottoms out to), the
     sitewide accent #df6919 already clears AA (4.61:1 - theme-spec Open Q1), so there is
     nothing left to override here. */
`;

// Sits above CardPanel's own local stacking context (see cardPanel.tsx) so the burst bleeding
// out from behind the card doesn't cover the words/questions columns rendered alongside it.
//
// `display: flex; flex-direction: column; height: 100%` (PageColumn/StarburstBackground fix
// round above) hands QuestionFeed.tsx's own root a real, resolvable height to flex against -
// QuestionFeed.tsx's own FeedRoot opts into `flex: 1; min-height: 0` to consume it (replacing
// HeroGrid's old NavbarHeight-derived `max-height` calc), so the hero's own height ultimately
// traces back to PageColumn's real measured navbar height with no separate guess of its own.
// Safe for the moderator Tab.Container branch too (see PrintingQueueOrDefault below) - that
// branch simply doesn't opt into `flex: 1`, so it keeps its previous natural/auto height,
// unchanged. PageColumn now bounds height at every width, not just >= md (fix round, owner
// live-review, "portrait static top block" - see that component's own comment), so this
// `height: 100%` is meaningful below md too.
const StarburstContent = styled.div`
  position: relative;
  z-index: 1;
  max-width: ${ContentMaxWidth}px;
  margin: 0 auto;
  padding: 0 1.5rem;
  display: flex;
  flex-direction: column;
  height: 100%;
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
  const navbarHeight = useNavbarHeight();

  return remoteBackendConfigured ? (
    <PageColumn $navbarHeight={navbarHeight}>
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
    </PageColumn>
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
