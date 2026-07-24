import styled from "@emotion/styled";
import Head from "next/head";
import React, { useState } from "react";
import Nav from "react-bootstrap/Nav";
import Tab from "react-bootstrap/Tab";

import { ProjectName } from "@/common/constants";
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

// WTC rebuild (2026-07-24, SPEC-wtc-rebuild.md) - "the page renders native on the ruled
// Tokyo-11 token layer" (section 0). The page-private `--wtc-*` identity tokens (section 1b)
// derive from the sitewide `--accent`/`--body`/`--conf` tokens the Tokyo-11 re-theme
// (styles.scss/_theme-tokens.scss, a separate, in-flight track per the train note) emits at
// `:root` as `--bs-*` (Bootstrap-generated, from that file's `$primary`/`$success`/etc.
// overrides) and `--theme-*` (this repo's own runtime-custom-property bridge for tokens
// Bootstrap has no equivalent for - accent/raised/divider/muted/btn-ink/radii).
//
// TRAIN SEQUENCING (deviation, reasoned): this branch is cut off current master, which does
// NOT yet carry that token layer (the Tokyo-11 PR is still in-flight, expected to land BEFORE
// this one per the train note) - referencing `--bs-primary`/`--theme-accent`/etc. unqualified
// today would resolve to nothing. Every inherited token below is `var(--runtime-name,
// <exact Tokyo-11 hex from the spec's own section 1a table>)` - a CSS custom-property fallback,
// not a literal colour choice of this page's own: once the Tokyo-11 branch merges ahead of this
// one (as the train note directs), the real `:root` custom properties take over automatically,
// with zero code change here. Until then, the page renders with the exact spec-mandated Tokyo-11
// values via the fallback. This is the "build token-first so the theme swap lands under you
// cleanly" instruction, applied literally.
const WtcTokenScope = styled.div`
  --body: var(--bs-body-bg, #1a1b26);
  --conf: var(--theme-band-bg, #222234);
  --raised: var(--theme-raised-bg, #24283b);
  --panel: var(--bs-secondary, #2f3549);
  --divider: var(--theme-divider, #16161e);
  --text: var(--bs-body-color, #c0caf5);
  --muted: var(--theme-muted, #8c94bf);
  --primary: var(--bs-primary, #ff9e64);
  --accent: var(--theme-accent, #bb9af7);
  --success: var(--bs-success, #9ece6a);
  --warning: var(--bs-warning, #e0af68);
  --danger: var(--bs-danger, #f7768e);
  --btn-ink: var(--theme-btn-ink, #1a1b26);
  --r-btn: var(--theme-radius-base, 6px);
  --r-input: var(--theme-radius-base, 6px);
  --r-card: var(--theme-radius-card, 8px);
  --r-pill: var(--theme-radius-pill, 10px);

  /* WTC-identity tokens (N, section 1b) - token-DERIVED from --accent/--body/--conf above, the
     ONLY page-private tokens this page defines. Each re-expresses one of the three retired
     bespoke elements (WD1): the deep-blue field (#123a6b), the starburst-blue mystery card
     (#4d8ddf), and the gold/navy wordmark (#F8D42B/#124063). */
  --wtc-field: radial-gradient(
    125% 115% at 30% 34%,
    color-mix(in srgb, var(--accent) 15%, var(--body)) 0%,
    var(--body) 58%
  );
  --wtc-mystery-face: linear-gradient(
    158deg,
    color-mix(in srgb, var(--accent) 26%, var(--conf)),
    color-mix(in srgb, var(--accent) 8%, var(--conf))
  );
  --wtc-mystery-glyph: var(--accent);
  --wtc-reveal-glow: color-mix(in srgb, var(--accent) 55%, transparent);
  --wtc-wordmark: var(--accent);
`;

// The page field wrapper (SPEC-wtc-rebuild.md section 1c "page field wrapper" row: bg
// `--wtc-field`, pad `14px 16px 22px`) - retires the old `StarburstBackground` (the deep-blue
// `#123a6b` radial + full-bleed viewport-width breakout) entirely. WD4 also retires
// `PageColumn`'s `100dvh - navbar` height bound and the `@media max-width: 767.98px
// { min-height: 100% }` "portrait static top block" hack alongside it - the container-first
// policy's subject-compaction (WD3, QuestionFeed.tsx) keeps the confirm hero reachable near the
// top on a phone without a bounded-height budget, so this is now an ordinary, un-height-bounded
// block that scrolls with the rest of the page (Layout.tsx's own ContentContainer), same as
// every other route.
const WtcField = styled.div`
  background: var(--wtc-field);
  padding: 14px 16px 22px;
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
      <WtcTokenScope>
        <WtcField>
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
        </WtcField>
      </WtcTokenScope>
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
            WTC rebuild (2026-07-24) - retinted from the retired deep-blue field
            (HERO_FIELD_BLUE_DEEP, #123a6b) to the Tokyo-11 `--body` value (#1a1b26, the same
            fallback WtcTokenScope's own `--body` resolves to pre-Tokyo-11-merge) - the
            installed-app chrome now matches the page's own (near-flat, --wtc-field-derived)
            body colour instead of the retired bespoke blue. */}
        <link rel="manifest" href="/whatsthat-manifest.json" />
        <meta name="theme-color" content="#1a1b26" />
        <link rel="apple-touch-icon" href="/whatsthat-icon-192.png" />
      </Head>
      <PrintingQueueOrDefault />
    </ProjectContainer>
  );
}
