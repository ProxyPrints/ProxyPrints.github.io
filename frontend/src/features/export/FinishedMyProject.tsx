import styled from "@emotion/styled";
import dynamic from "next/dynamic";
import React, { useState } from "react";
import Alert from "react-bootstrap/Alert";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Container from "react-bootstrap/Container";
import Modal from "react-bootstrap/Modal";
import Row from "react-bootstrap/Row";
import Tab from "react-bootstrap/Tab";

import {
  NavbarHeight,
  NavPillButtonHeight,
  NavUnderlineButtonHeight,
} from "@/common/constants";
import { useAppDispatch, useAppSelector } from "@/common/types";
import { Coffee } from "@/components/Coffee";
import { RightPaddedIcon } from "@/components/icon";
import { MakePlayingCardsLink } from "@/components/MakePlayingCardsLink";
import { NavBanner, NavBannerItem } from "@/components/NavBanner";
import { NotMPCLink } from "@/components/NotMPCLink";
import { OverflowCol } from "@/components/OverflowCol";
import { PringlePrintsLink } from "@/components/PringlePrintsLink";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { useLocalFilesDirectoryHandle } from "@/features/clientSearch/clientSearchHooks";
import { useDownloadDesktopTool } from "@/features/download/downloadDesktopTool";
import { useDownloadXML } from "@/features/download/downloadXML";
import { useProjectName } from "@/store/slices/backendSlice";
import { showModal } from "@/store/slices/modalsSlice";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";

import { MobileStatus } from "../mobile/MobileStatus";

const PDFGenerator = dynamic(
  () => import("../pdf/PDFGenerator").then((mod) => mod.PDFGenerator),
  { ssr: false }
);

interface ExitModal {
  show: boolean;
  handleClose: {
    (): void;
    (event: React.MouseEvent<HTMLButtonElement, MouseEvent>): void;
  };
}

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
  const { clientSearchService } = useClientSearchContext();
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
  const { clientSearchService } = useClientSearchContext();
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
        sit back and watch the magic happen. Check out our wiki{" "}
        <a
          href="https://github.com/chilli-axe/mpc-autofill/wiki/Desktop-Tool"
          target="_blank"
        >
          here
        </a>{" "}
        for more detailed instructions.
      </p>
    </>
  );
};

function ProjectDownload() {
  const downloadXML = useDownloadXML();
  const projectName = useProjectName();
  return (
    <>
      <p>
        An XML file is a snapshot of all the cards and image versions you
        selected. Our desktop tool reads this file and automatically turns it
        into an order with <MakePlayingCardsLink />.
      </p>
      <p>
        You also can <b>re-upload</b> your XML file to {projectName} and{" "}
        <b>continue editing it later</b>!
      </p>
      <Row>
        <Col md={{ span: 8, offset: 2 }} sm={12}>
          <DownloadButton onClick={downloadXML}>
            <DownloadButtonLink>
              <h1 className="bi bi-file-code"></h1>
              <h4>Download Project as XML</h4>
            </DownloadButtonLink>
          </DownloadButton>
        </Col>
      </Row>
    </>
  );
}

type Platform = "windows" | "macos-intel" | "macos-arm" | "linux";

function PlatformDownload({
  platform,
  platformName,
  icon,
}: {
  platform: Platform;
  platformName: string;
  icon: string;
}) {
  const assetURL = `https://download.mpcautofill.com/?platform=${platform}`;
  const downloadDesktopTool = useDownloadDesktopTool();
  return (
    <>
      <DownloadButton>
        <DownloadButtonLink
          onClick={() =>
            downloadDesktopTool(new URL(assetURL), `autofill-${platform}.zip`)
          }
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
        Download the desktop tool for your platform. If you&apos;d rather
        download the source code instead, you can find it{" "}
        <a
          href="https://github.com/chilli-axe/mpc-autofill/tree/master/desktop-tool/"
          target="_blank"
        >
          here
        </a>
        !
      </p>
      <Row gap={2}>
        <Col sm={3}>
          <PlatformDownload
            platformName="Windows"
            platform="windows"
            icon="windows"
          />
        </Col>
        <Col sm={3}>
          <PlatformDownload
            platformName="macOS — Intel"
            platform="macos-intel"
            icon="apple"
          />
        </Col>
        <Col sm={3}>
          <PlatformDownload
            platformName="macOS — ARM"
            platform="macos-arm"
            icon="apple"
          />
        </Col>
        <Col sm={3}>
          <PlatformDownload
            platformName="Linux"
            platform="linux"
            icon="ubuntu"
          />
        </Col>
      </Row>
      <Alert variant="info" className="text-center">
        <b>Having trouble with the above buttons?</b> Grab it directly from
        GitHub{" "}
        <a
          href="https://github.com/chilli-axe/mpc-autofill/releases/latest/"
          target="_blank"
        >
          here
        </a>
        !
      </Alert>
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
          <ProjectDownload />
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
      <BigOL>
        <BigLI className="py-3">
          <h3>Prepare Your Print File</h3>
          <p>
            Head to the <b>PDF</b> tab and generate a print-ready PDF or PNG of
            your project at <b>300 DPI or higher</b>.
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

type FinishedMyProjectExportType = "mpc" | "notmpc" | "pringleprints" | "pdf";

export function FinishedMyProject() {
  const [key, setKey] = useState<FinishedMyProjectExportType>("mpc");
  const navBannerItems: Array<NavBannerItem<FinishedMyProjectExportType>> = [
    { key: "mpc", label: "MakePlayingCards", bootstrapIconName: "bag-check" },
    { key: "notmpc", label: "NotMPC", bootstrapIconName: "box-seam" },
    {
      key: "pringleprints",
      label: "PringlePrints",
      bootstrapIconName: "geo-alt",
    },
    { key: "pdf", label: "PDF", bootstrapIconName: "file-pdf" },
  ];
  return (
    <Tab.Container
      activeKey={key}
      onSelect={(k) => {
        if (k) setKey(k as FinishedMyProjectExportType);
      }}
    >
      <NavBanner items={navBannerItems} variant="underline" />
      <OverflowCol
        heightDelta={
          NavPillButtonHeight + NavUnderlineButtonHeight + NavbarHeight
        }
      >
        <Tab.Content>
          <Tab.Pane eventKey="mpc">
            <MakePlayingCardsInstructions />
          </Tab.Pane>
          <Tab.Pane eventKey="notmpc">
            <NotMPCInstructions />
          </Tab.Pane>
          <Tab.Pane eventKey="pringleprints">
            <PringlePrintsInstructions />
          </Tab.Pane>
          <Tab.Pane eventKey="pdf" mountOnEnter>
            <PDFGenerator
              heightDelta={
                NavPillButtonHeight + NavUnderlineButtonHeight + NavbarHeight
              }
            />
          </Tab.Pane>
        </Tab.Content>
      </OverflowCol>
    </Tab.Container>
  );
}
