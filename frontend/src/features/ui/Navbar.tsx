import styled from "@emotion/styled";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/router";
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Container from "react-bootstrap/Container";
import Nav from "react-bootstrap/Nav";
import Navbar from "react-bootstrap/Navbar";

import { NavbarLogoHeight } from "@/common/constants";
import { isUnifiedDisplayPageEnabled } from "@/common/featureFlags";
import DisableSSR from "@/components/DisableSSR";
import { RightPaddedIcon } from "@/components/icon";
import { BackendConfig } from "@/features/backend/BackendConfig";
import { AuthWidget } from "@/features/moderation/AuthWidget";
import {
  useAnyBackendConfigured,
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

// Nav+footer redesign (2026-07-22) - N6: unbinds the navbar from the app-wide
// `ContentMaxWidth` cap, the same `max-width: none` + `fluid` mechanism Layout.tsx's
// `ProjectContainer`/`MaxWidthContainer` established for #287/#289 (see that file's own
// comment). This is a Navbar-local escape hatch rather than routing through
// `ProjectContainer` - the navbar has always owned its own local `Container` instance, never
// `ProjectContainer`'s, so unbinding it doesn't touch any content page's own cap.
const FullWidthContainer = styled(Container)`
  max-width: none;
`;

const NoVerticalPaddingNavbar = styled(Navbar)`
  --bs-navbar-padding-y: 0px;
`;

const BoldCollapse = styled(Navbar.Collapse)`
  font-weight: bold;
`;

// Sitewide theme (issue #302, mockup C-B): color the brand wordmark in the theme accent
// (var(--bs-primary), Superhero-native orange #df6919) so it reads as the mockup's orange
// wordmark on the dark navbar chrome, instead of inheriting the navbar's plain light text
// color. References the CSS custom property (not a literal hex) so it stays in sync with
// styles.scss's token layer automatically if the accent is ever retuned again.
const BrandWordmark = styled.b`
  color: var(--bs-primary);
`;

// N7 - now that What's New?/Explore/My Decks/Download/Contributions/Guide are all gone (cut
// to the footer or dropped entirely, see this redesign's spec §1), the left cluster has room
// to breathe: a generous ~1.75rem gap reads better with only 2-3 links left. Only applied at
// >= the `lg` breakpoint where the links sit inline - the collapsed mobile panel keeps its
// normal stacked block spacing.
const LeftNav = styled(Nav)`
  @media (min-width: 992px) {
    gap: 1.75rem;
  }
`;

const RightNav = styled(Nav)`
  gap: 1rem;
`;

// N3 - "What's That Card?" no longer wraps across multiple lines now that the bar has room;
// this used to be the label that tipped the old, crowded left row into a wrapping navbar-height
// overflow (see this file's pre-redesign history).
const NoWrapNavLink = styled(Nav.Link)`
  white-space: nowrap;
`;

export default function ProjectNavbar() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  const anyBackendConfigured = useAnyBackendConfigured();

  const [showBackendConfig, setShowBackendConfig] = useState(false);
  const handleCloseBackendConfig = () => setShowBackendConfig(false);
  const handleShowBackendConfig = () => setShowBackendConfig(true);

  const projectName = useProjectName();
  const router = useRouter();

  return (
    <DisableSSR>
      <NoVerticalPaddingNavbar
        expand="lg"
        fixed="top"
        variant="dark"
        bg="dark"
        collapseOnSelect
      >
        <FullWidthContainer
          fluid
          className="justify-content-center align-middle"
        >
          <Navbar.Brand href="/" as={Link}>
            <Image
              src="/logolowres.png"
              alt="logo"
              width={NavbarLogoHeight}
              height={NavbarLogoHeight}
            />{" "}
            <span className="align-middle">
              <BrandWordmark>{projectName}</BrandWordmark>
            </span>
          </Navbar.Brand>
          <Navbar.Toggle aria-controls="basic-navbar-nav" />
          <BoldCollapse id="basic-navbar-nav">
            <LeftNav className="me-auto">
              {/* N1/N2 - the nav's five-surface reduction: "Editor" points at /editor, which now
                  serves the unified sheet+rail page (Proposal H switchover, 2026-07-23, issues
                  #231/#272) - the classic grid editor this replaces has left routing entirely
                  (unreachable by URL, not just delisted from the nav; see pages/editor.tsx's own
                  comment for the full swap rationale and pages/display.tsx for the redirect that
                  now covers the old /display URL). Kept behind the same isUnifiedDisplayPageEnabled()
                  flag the old "Display (beta)" link carried (in addition to anyBackendConfigured) -
                  dropping the flag here would leave NO editing surface reachable from the nav at
                  all while NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED is off, since /editor itself now
                  404s behind that same flag with no classic fallback left (confirmed "true" in the
                  production deploy variable since 2026-07-18). */}
              {anyBackendConfigured && isUnifiedDisplayPageEnabled() && (
                <Nav.Link
                  as={Link}
                  href="/editor"
                  active={router.route === "/editor"}
                  eventKey="/editor"
                >
                  Editor
                </Nav.Link>
              )}
              {remoteBackendConfigured && (
                <NoWrapNavLink
                  as={Link}
                  href="/whatsthat"
                  active={router.route === "/whatsthat"}
                  eventKey="/whatsthat"
                >
                  What&apos;s That Card?
                </NoWrapNavLink>
              )}
              {/* N4 - "Wiki" replaces "Guide" (same on-site /guide target, renamed label only).
                  Not gated on anyBackendConfigured/remoteBackendConfigured (unlike Editor/What's
                  That Card? above) - /guide is build-time-static content sourced from docs/ (see
                  docs/proposals/proposal-i-docs-as-site-source.md), with no backend dependency.
                  router.pathname (not router.route) is required here since
                  /guide/[[...slug]].tsx is one catch-all page file serving every /guide/* route -
                  router.route is that one literal page-file path for all of them, so a
                  startsWith("/guide") check on router.pathname is what actually highlights this
                  link on both /guide and /guide/using-it. */}
              <Nav.Link
                as={Link}
                href="/guide"
                active={router.pathname.startsWith("/guide")}
                eventKey="/guide"
              >
                Wiki
              </Nav.Link>
            </LeftNav>
            <RightNav className="ms-auto d-flex align-items-center">
              {/* Deliberately NOT a Nav.Link (unlike Sources below) - react-bootstrap's
                  Nav.Link-with-eventKey renders its own <a href="#"> around whatever children
                  it's given, and AuthWidget already supplies a real interactive element of its
                  own for every state (the signed-in dropdown menu, the signed-out Discord pill).
                  Wrapping a real anchor/button in another anchor is invalid, nested-anchor HTML -
                  see docs/lessons.md's "components that each correctly render an anchor can
                  compose into invalid nested-anchor HTML" entry. */}
              {remoteBackendConfigured && (
                <div className="m-0 py-0">
                  <AuthWidget />
                </div>
              )}
              <Nav.Link className="m-0 py-0" eventKey="configure-backend">
                <Button
                  className="my-0"
                  variant="success"
                  onClick={handleShowBackendConfig}
                  aria-label="configure-server-btn"
                >
                  <RightPaddedIcon bootstrapIconName="database" />
                  Sources
                </Button>
              </Nav.Link>
            </RightNav>
          </BoldCollapse>
        </FullWidthContainer>
      </NoVerticalPaddingNavbar>
      <BackendConfig
        show={showBackendConfig}
        handleClose={handleCloseBackendConfig}
      />
    </DisableSSR>
  );
}
