/**
 * The editor's printshop ordering guides - `DisplayExportMenu.tsx`'s fifth entry, alongside
 * XML/Card Images/Decklist/PDF. These are the three ordering instructions that used to live on
 * the retired `/print` page's "Print!" tab (`FinishedMyProject.tsx`): PringlePrints,
 * MakePlayingCards, and NotMPC, each behind a flag icon in its own tab. The instructions
 * themselves are ported verbatim from that page (including their "steps current as of July
 * 2026 — confirm before ordering" caveats and the TODO comments flagging them as site-read
 * derived, not manually walked through) with two step-1 rewrites for the new home: the
 * PringlePrints tab now points at the Export menu's own PDF item instead of the old "PDF" tab,
 * and the MakePlayingCards tab's first step now points at the Export menu's XML item instead of
 * an in-place "Download Project as XML" button (the Export menu's XML item is the same
 * `useDownloadXML`-driven download that button used).
 *
 * Rather than a route (the retired page) or a full-height panel, these guides open in a modal
 * from the Export menu - they are reference material for an ordering run, not a workspace, and
 * a modal keeps them out of the way until wanted.
 *
 * The tab bar uses plain `react-bootstrap/Tabs` with flag icons in the titles, matching the
 * retired page's own flag-per-printshop navigation. Flag artwork is the same vendored static
 * SVG set (`@/components/flags.tsx`) the old tab bar used - deliberately not unicode emoji
 * flags, which Windows browsers render as plain letter pairs (see `docs/features/
 * print-export-page.md`'s retirement note for the history).
 *
 * ## Home-printing guidance
 *
 * The modal opens with an Alert on print-at-home scaling: a browser/printer driver set to
 * "Fit to Page" (or a borderless "Expansion" above its minimum) enlarges the whole sheet, which
 * no page-layout setting in the app can compensate for. This is the export affordance's own
 * single placement for that guidance - deliberately not duplicated on the PDF item.
 */
import styled from "@emotion/styled";
import React, { useState } from "react";
import Alert from "react-bootstrap/Alert";
import Col from "react-bootstrap/Col";
import Container from "react-bootstrap/Container";
import Dropdown from "react-bootstrap/Dropdown";
import Modal from "react-bootstrap/Modal";
import Row from "react-bootstrap/Row";
import Tab from "react-bootstrap/Tab";
import Tabs from "react-bootstrap/Tabs";

import {
  UpstreamDesktopTool,
  UpstreamDesktopToolReleasesURL,
  UpstreamDesktopToolSourceURL,
  UpstreamDesktopToolWikiURL,
} from "@/common/constants";
import { Coffee } from "@/components/Coffee";
import { CanadaFlag, ChinaFlag, USAFlag } from "@/components/flags";
import { RightPaddedIcon } from "@/components/icon";
import { MakePlayingCardsLink } from "@/components/MakePlayingCardsLink";
import { NotMPCLink } from "@/components/NotMPCLink";
import { PringlePrintsLink } from "@/components/PringlePrintsLink";
import { useLocalFilesDirectoryHandle } from "@/features/clientSearch/clientSearchHooks";

import { MobileStatus } from "../mobile/MobileStatus";

const BigOL = styled.ol`
  list-style-type: none;
`;

const BigLI = styled.li`
  counter-increment: step-counter;
  position: relative;
  padding: 10px 10px;
  &::before {
    content: counter(step-counter);
    color: white;
    font-size: 1.5rem;
    position: absolute;
    --size: 32px;
    left: calc(-1 * var(--size) - 2px);
    line-height: var(--size);
    width: var(--size);
    height: var(--size);
    border-radius: 50%;
    border: white 1px solid;
    text-align: center;
  }
`;

const DownloadButton = styled(Col)`
  text-align: center;
  border-color: lightblue;
  border-width: 2px;
  border-style: solid;
  border-radius: 6px;
  padding-top: 10px;
  padding-bottom: 10px;
  transition: background-color 0.15s ease-in-out;
  background-color: rgba(0, 0, 0, 0);
  &:hover {
    background-color: rgba(255, 255, 255, 0.7);
  }
  cursor: pointer;
`;

const DownloadButtonLink = styled.a`
  &:link {
    color: white;
    text-decoration: none;
  }
  &:visited {
    color: white;
    text-decoration: none;
  }
  &:not([href]) {
    color: white;
    text-decoration: none;
  }
`;

const LocalFilesInstructions = () => {
  const directoryHandle = useLocalFilesDirectoryHandle();
  return (
    directoryHandle !== undefined && (
      <Alert variant="primary" className="text-center">
        You&apos;ve configured <b>{directoryHandle.name}</b> as your local
        folder &mdash; your <b>XML</b> and <b>Desktop Tool</b> downloads will go
        into <b>{directoryHandle.name}</b>.
      </Alert>
    )
  );
};

const RunDesktopToolInstructions = () => {
  const directoryHandle = useLocalFilesDirectoryHandle();
  return (
    <>
      {directoryHandle !== undefined ? (
        <p>
          Double-click the Desktop Tool in <b>{directoryHandle.name}</b> to run
          it!
        </p>
      ) : (
        <p>
          Move the Desktop Tool and your XML file into <b>the same folder</b>{" "}
          (for example, put them both on your desktop), then double-click the
          Desktop Tool to run it!
        </p>
      )}
      <p>
        It&apos;ll ask you a few questions when it starts up, then you get to
        sit back and watch the magic happen. Check out {UpstreamDesktopTool}
        &apos;s wiki{" "}
        <a href={UpstreamDesktopToolWikiURL} target="_blank">
          here
        </a>{" "}
        for more detailed instructions.
      </p>
    </>
  );
};

// These used to auto-download a per-platform ZIP from download.mpcautofill.com via an
// in-app fetch - that domain isn't owned by this fork's infrastructure and the deploy job
// that was meant to route it always fails (see docs/infrastructure.md), so it never actually
// worked. Rather than guess at a direct per-platform GitHub release asset URL we can't verify
// from here, every platform button now links straight to the upstream project's own releases
// page, where the real, current asset names are always correct because GitHub is serving them
// directly - honest and unbreakable, at the cost of one extra click to pick the right file.
function PlatformDownload({
  platformName,
  icon,
}: {
  platformName: string;
  icon: string;
}) {
  return (
    <>
      <DownloadButton>
        <DownloadButtonLink
          href={UpstreamDesktopToolReleasesURL}
          target="_blank"
        >
          <h1 className={`bi bi-${icon}`}></h1>
          <h4>{platformName}</h4>
        </DownloadButtonLink>
      </DownloadButton>
      <br />
    </>
  );
}

function DesktopToolDownload() {
  return (
    <>
      <MobileStatus />
      <p>
        Download {UpstreamDesktopTool} for your platform below - it reads the
        XML file from step 1 and drives <MakePlayingCardsLink /> for you. If
        you&apos;d rather download the source code instead, you can find it{" "}
        <a href={UpstreamDesktopToolSourceURL} target="_blank">
          here
        </a>
        !
      </p>
      <Row gap={2}>
        <Col sm={3}>
          <PlatformDownload platformName="Windows" icon="windows" />
        </Col>
        <Col sm={3}>
          <PlatformDownload platformName="macOS — Intel" icon="apple" />
        </Col>
        <Col sm={3}>
          <PlatformDownload platformName="macOS — ARM" icon="apple" />
        </Col>
        <Col sm={3}>
          <PlatformDownload platformName="Linux" icon="ubuntu" />
        </Col>
      </Row>
    </>
  );
}

const MakePlayingCardsInstructions = () => {
  return (
    <Container className="py-3">
      <h5 className="text-center">
        Nice work! There are three simple steps for turning your project into an
        order with <MakePlayingCardsLink />.
      </h5>
      <LocalFilesInstructions />
      <BigOL>
        <BigLI className="py-3">
          <h3>Download Your Project</h3>
          <p>
            An XML file is a snapshot of all the cards and image versions you
            selected. Head back to the <b>Export</b> menu and choose <b>XML</b>{" "}
            to download it. Our desktop tool reads this file and automatically
            turns it into an order with <MakePlayingCardsLink />.
          </p>
          <p>
            You also can <b>re-upload</b> your XML file and{" "}
            <b>continue editing it later</b>!
          </p>
        </BigLI>
        <BigLI className="py-3">
          <h3>Download the Desktop Tool</h3>
          <DesktopToolDownload />
        </BigLI>
        <BigLI className="py-3">
          <h3>Run the Desktop Tool</h3>
          <RunDesktopToolInstructions />
        </BigLI>
      </BigOL>
      <hr />
      <h5 className="text-center">
        And that&apos;s all there is to it!{" "}
        <i className="bi bi-rocket-takeoff" />
      </h5>
      <p className="text-center">
        If this software has brought you joy and you&apos;d like to throw a few
        bucks my way, you can find my tip jar here <i className="bi bi-heart" />
      </p>
      <Coffee />
    </Container>
  );
};

// TODO: verify this NotMPC ordering flow is accurate and up to date — steps
// below were derived from a one-time read of notmpc.com's site copy, not a
// manual walkthrough of their order process.
const NotMPCInstructions = () => {
  return (
    <Container className="py-3">
      <h5 className="text-center">
        Nice work! There are three simple steps for turning your project into an
        order with <NotMPCLink />.
      </h5>
      <p className="text-muted small text-center">
        Steps current as of July 2026 &mdash; confirm at <NotMPCLink /> before
        ordering.
      </p>
      <BigOL>
        <BigLI className="py-3">
          <h3>Export Your Card Images</h3>
          <p>
            Head back to the <b>Export</b> menu and choose <b>Card Images</b> to
            download all your card images to your computer. You&apos;ll upload
            these to NotMPC in the next step.
          </p>
        </BigLI>
        <BigLI className="py-3">
          <h3>Set Up Your Order on NotMPC</h3>
          <p>
            Head over to <NotMPCLink /> and choose your card size, then select
            your card stock, quantity and finishing options.
          </p>
        </BigLI>
        <BigLI className="py-3">
          <h3>Upload Your Images &amp; Checkout</h3>
          <p>
            Open NotMPC&apos;s online card maker and drag-and-drop your
            downloaded images onto the card fronts and backs. Preview your
            design, then add it to your cart and check out.
          </p>
        </BigLI>
      </BigOL>
      <hr />
      <h5 className="text-center">
        And that&apos;s all there is to it!{" "}
        <i className="bi bi-rocket-takeoff" />
      </h5>
    </Container>
  );
};

// TODO: verify this PringlePrints ordering flow is accurate and up to date —
// steps below (and the batch size / finish options) were derived from a
// one-time read of pringleprints.ca's site copy, not a manual walkthrough of
// their order process. Pricing and service area in particular may have
// changed since.
const PringlePrintsInstructions = () => {
  return (
    <Container className="py-3">
      <h5 className="text-center">
        Nice work! There are three simple steps for turning your project into an
        order with <PringlePrintsLink />.
      </h5>
      <p className="text-muted small text-center">
        Steps and pricing current as of July 2026 &mdash; confirm at{" "}
        <PringlePrintsLink /> before ordering.
      </p>
      <BigOL>
        <BigLI className="py-3">
          <h3>Prepare Your Print File</h3>
          <p>
            Head to the <b>Export</b> menu and choose <b>PDF</b> to generate a
            print-ready PDF or PNG of your project at <b>300 DPI or higher</b>.
          </p>
        </BigLI>
        <BigLI className="py-3">
          <h3>Choose Your Finish &amp; Batch Size</h3>
          <p>
            Head over to <PringlePrintsLink /> and pick a cardstock finish and a
            batch size for your order.
          </p>
        </BigLI>
        <BigLI className="py-3">
          <h3>Email Your Order</h3>
          <p>
            Send your file &mdash; or a shared link if it&apos;s large &mdash;
            along with your finish and batch size, using their order form or
            email. They&apos;ll confirm receipt and share a timeline and payment
            details.
          </p>
        </BigLI>
      </BigOL>
      <hr />
      <h5 className="text-center">
        And that&apos;s all there is to it!{" "}
        <i className="bi bi-rocket-takeoff" />
      </h5>
    </Container>
  );
};

const PrintshopHomePrintingAlert = () => (
  <Alert variant="info">
    Printing these files at home? Make sure your print dialog is set to{" "}
    <b>100% / Actual Size</b> rather than &quot;Fit to Page&quot;, and use{" "}
    <b>borderless</b> printing with <b>Expansion</b> set to its minimum. A
    scaling driver enlarges the whole sheet, which no page-layout setting in the
    app can compensate for.
  </Alert>
);

export function DisplayExportPrintshops() {
  const [show, setShow] = useState(false);
  return (
    <>
      <Dropdown.Item
        onClick={() => setShow(true)}
        data-testid="export-printshops-button"
      >
        <RightPaddedIcon bootstrapIconName="shop" /> Printshops
      </Dropdown.Item>
      <Modal show={show} onHide={() => setShow(false)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>Printshops</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <PrintshopHomePrintingAlert />
          <Tabs defaultActiveKey="pringleprints" id="printshop-tabs">
            <Tab
              eventKey="pringleprints"
              title={
                <>
                  <CanadaFlag /> PringlePrints
                </>
              }
            >
              <PringlePrintsInstructions />
            </Tab>
            <Tab
              eventKey="mpc"
              title={
                <>
                  <ChinaFlag /> MakePlayingCards
                </>
              }
            >
              <MakePlayingCardsInstructions />
            </Tab>
            <Tab
              eventKey="notmpc"
              title={
                <>
                  <USAFlag /> NotMPC
                </>
              }
            >
              <NotMPCInstructions />
            </Tab>
          </Tabs>
        </Modal.Body>
      </Modal>
    </>
  );
}
