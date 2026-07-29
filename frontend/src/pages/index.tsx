import Head from "next/head";
import Link from "next/link";
import React from "react";
import Button from "react-bootstrap/Button";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { ProjectName } from "@/common/constants";
import { ParticipationGraph } from "@/features/stats/ParticipationGraph";
import { DynamicLogo } from "@/features/ui/DynamicLogo";
import Footer from "@/features/ui/Footer";
import { HomepagePanel } from "@/features/ui/HomepagePanel";
import { ProjectContainer } from "@/features/ui/Layout";
import { useGetCatalogStatsQuery } from "@/store/api";
import {
  useAnyBackendConfigured,
  useProjectName,
} from "@/store/slices/backendSlice";

// Homepage front-page graph (Proposal F item 4, upgraded from a text strip to a real graph per
// the 2026-07-29 coordinator amendment - see ParticipationGraph.tsx's own module comment for the
// full reasoning). Renders nothing until the cache-only `1/catalogStats/` endpoint has a real,
// warmed blob (`generatedAt` non-null) - a cold-cache/zeroed skeleton would otherwise render a
// graph with an empty "cards ready to confirm" bar and zero contributor dots, which reads as
// "there is nothing to do here" rather than the intended "not computed yet" (the same
// cache-miss distinction pages/stats.tsx's own CatalogStatsBody makes).
function HomepageParticipationGraph() {
  const catalogStatsQuery = useGetCatalogStatsQuery();
  const stats = catalogStatsQuery.data;
  if (stats == null || stats.generatedAt == null) {
    return null;
  }
  return <ParticipationGraph participation={stats.participation} />;
}

function JumpIntoEditorButton() {
  const anyBackendConfigured = useAnyBackendConfigured();
  return (
    <Row className="justify-content-center">
      <Col xl={6} lg={6} md={8} sm={12} xs={12}>
        {anyBackendConfigured ? (
          <Link href="/editor" passHref legacyBehavior>
            <div className="d-grid gap-0">
              <Button>Jump into the project editor!</Button>
            </div>
          </Link>
        ) : (
          <p style={{ textAlign: "center" }}>
            Click the <b>Sources</b> button in the top-right to get started!
          </p>
        )}
      </Col>
    </Row>
  );
}

function ProjectOverview() {
  return (
    <>
      <Row>
        <Col lg={6} md={6} sm={12} xs={12}>
          <h1>Self-Service Card Printing for Tabletop Gaming</h1>
          <ul>
            <li>
              {ProjectName} is the easiest way to print professional-quality
              playtest cards for kitchen-table tabletop gaming.
            </li>
            <li>
              It&apos;s fully open-source software (licensed under GPL-3) and
              all of its features will always be free.
            </li>
          </ul>
        </Col>
        <Col lg={6} md={6} sm={12} xs={12}></Col>
      </Row>
      <br />
      <Row>
        <Col lg={6} md={6} sm={12} xs={12}></Col>
        <Col lg={6} md={6} sm={12} xs={12}>
          <h1>Community-Driven Card Image Databases</h1>
          <ul>
            <li>
              Choose your favourite renders and artworks made by your community
              to bling out your project!
            </li>
            <li>
              Use our rich project editor to fine-tune exactly how you&apos;d
              like it to turn out.
            </li>
            <li>
              Browse the cards that creators in your community have added to the
              site recently.
            </li>
          </ul>
        </Col>
      </Row>
      <br />
      <Row>
        <Col lg={6} md={6} sm={12} xs={12}>
          <h1>Order From the Print Shop of Your Choice</h1>
          <ul>
            <li>
              Export your finished project as a print-ready PDF, or hand it off
              to one of the print shops available on the site &mdash; whichever
              suits your project best.
            </li>
          </ul>
        </Col>
        <Col lg={6} md={6} sm={12} xs={12}></Col>
      </Row>
    </>
  );
}

export default function Index() {
  const projectName = useProjectName();
  return (
    <ProjectContainer>
      <Head>
        <title>{`${projectName}`}</title>
        <meta
          name="description"
          content="The easiest way to print professional-quality playtest cards for kitchen-table tabletop gaming."
        />
      </Head>
      <br />
      <DynamicLogo />
      <br />
      <JumpIntoEditorButton />
      <hr />
      <HomepagePanel />
      <HomepageParticipationGraph />
      <hr />
      <ProjectOverview />
      <Footer />
    </ProjectContainer>
  );
}
