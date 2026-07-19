import styled from "@emotion/styled";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/router";
import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Container from "react-bootstrap/Container";
import Nav from "react-bootstrap/Nav";
import Navbar from "react-bootstrap/Navbar";

import {
  ContentMaxWidth,
  NavbarHeight,
  NavbarLogoHeight,
  UpstreamDesktopTool,
  UpstreamDesktopToolReleasesURL,
} from "@/common/constants";
import { isUnifiedDisplayPageEnabled } from "@/common/featureFlags";
import DisableSSR from "@/components/DisableSSR";
import { RightPaddedIcon } from "@/components/icon";
import { BackendConfig } from "@/features/backend/BackendConfig";
import {
  DownloadManager,
  OpenDownloadManagerButton,
} from "@/features/download/DownloadManager";
import { AuthWidget } from "@/features/moderation/AuthWidget";
import { useGetWhoamiQuery } from "@/store/api";
import {
  useAnyBackendConfigured,
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

const MaxWidthContainer = styled(Container)`
  max-width: ${ContentMaxWidth}px;
`;

const NoVerticalPaddingNavbar = styled(Navbar)`
  --bs-navbar-padding-y: 0px;
`;

const BoldCollapse = styled(Navbar.Collapse)`
  font-weight: bold;
`;

export default function ProjectNavbar() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  const anyBackendConfigured = useAnyBackendConfigured();

  const [shownOffcanvas, setShownOffcanvas] = useState<
    "backendConfig" | "downloadManager" | null
  >(null);
  const handleCloseOffcanvas = () => setShownOffcanvas(null);
  const handleShowBackendConfig = () => setShownOffcanvas("backendConfig");
  const handleShowDownloadManager = () => setShownOffcanvas("downloadManager");

  const projectName = useProjectName();
  const router = useRouter();
  const whoami = useGetWhoamiQuery();
  const isAuthenticated = whoami.data?.authenticated === true;

  return (
    <DisableSSR>
      <NoVerticalPaddingNavbar
        expand="lg"
        fixed="top"
        variant="dark"
        bg="primary"
        collapseOnSelect
      >
        <MaxWidthContainer className="justify-content-center align-middle">
          <Navbar.Brand href="/" as={Link}>
            <Image
              src="/logolowres.png"
              alt="logo"
              width={NavbarLogoHeight}
              height={NavbarLogoHeight}
            />{" "}
            <span className="align-middle">
              <b>{projectName}</b>
            </span>
          </Navbar.Brand>
          <Navbar.Toggle aria-controls="basic-navbar-nav" />
          <BoldCollapse id="basic-navbar-nav">
            <Nav className="me-auto">
              {anyBackendConfigured && (
                <Nav.Link
                  as={Link}
                  href="/editor"
                  active={router.route === "/editor"}
                  eventKey="/editor"
                >
                  Editor
                </Nav.Link>
              )}
              {anyBackendConfigured && isUnifiedDisplayPageEnabled() && (
                <Nav.Link
                  as={Link}
                  href="/display"
                  active={router.route === "/display"}
                  eventKey="/display"
                >
                  Display (beta)
                </Nav.Link>
              )}
              {remoteBackendConfigured && (
                <Nav.Link
                  as={Link}
                  href="/new"
                  active={router.route === "/new"}
                  eventKey="/new"
                >
                  What&apos;s New?
                </Nav.Link>
              )}
              {anyBackendConfigured && (
                <Nav.Link
                  as={Link}
                  href="/explore"
                  active={router.route === "/explore"}
                  eventKey="/explore"
                >
                  Explore
                </Nav.Link>
              )}
              {remoteBackendConfigured && (
                <Nav.Link
                  as={Link}
                  href="/contributions"
                  active={router.route === "/contributions"}
                  eventKey="/contributions"
                >
                  Contributions
                </Nav.Link>
              )}
              {remoteBackendConfigured && (
                <Nav.Link
                  as={Link}
                  href="/whatsthat"
                  active={router.route === "/whatsthat"}
                  eventKey="/whatsthat"
                >
                  What&apos;s That Card?
                </Nav.Link>
              )}
              {remoteBackendConfigured && isAuthenticated && (
                <Nav.Link
                  as={Link}
                  href="/myDecks"
                  active={router.route === "/myDecks"}
                  eventKey="/myDecks"
                >
                  My Decks
                </Nav.Link>
              )}
              <Nav.Link
                href={UpstreamDesktopToolReleasesURL}
                target="_blank"
                title={`${UpstreamDesktopTool} (compatible with ${projectName} project files)`}
              >
                Download
              </Nav.Link>
            </Nav>
            <Nav className="ms-auto d-flex align-items-center">
              {/* Deliberately NOT a Nav.Link (unlike its siblings below) - react-bootstrap's
                  Nav.Link-with-eventKey renders its own <a href="#"> around whatever children
                  it's given, and AuthWidget already supplies a real <a> of its own for both the
                  signed-in ("Sign out") and signed-out ("Sign in") states. Wrapping a real anchor
                  in another anchor is invalid, nested-anchor HTML - the outer <a> silently
                  intercepts every click, so the inner Discord/logout link never actually
                  navigates (no error, no console warning - see docs/lessons.md's "components
                  that each correctly render an anchor can compose into invalid nested-anchor
                  HTML" entry). A plain wrapper carrying the same m-0 py-0 spacing the Nav.Link
                  used to provide is all this needs - AuthWidget has no use for Nav.Link's
                  active/eventKey tab machinery anyway. */}
              {remoteBackendConfigured && (
                <div className="m-0 py-0">
                  <AuthWidget />
                </div>
              )}
              <Nav.Link className="m-0 py-0" eventKey="download-manager">
                <OpenDownloadManagerButton
                  handleClick={handleShowDownloadManager}
                />
              </Nav.Link>
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
            </Nav>
          </BoldCollapse>
        </MaxWidthContainer>
      </NoVerticalPaddingNavbar>
      <BackendConfig
        show={shownOffcanvas === "backendConfig"}
        handleClose={handleCloseOffcanvas}
      />
      <DownloadManager
        show={shownOffcanvas === "downloadManager"}
        handleClose={handleCloseOffcanvas}
      />
    </DisableSSR>
  );
}
