/**
 * Homepage landing panel (frontend-polish package, queued item 2) - a light-touch addition to
 * index.tsx, not a redesign of it. The brief was to "confess what the site is": beyond the
 * print-shop wrapper the page above this already describes, there's a whole community-driven
 * printing-identification game (/whatsthat) and client-side-encrypted deck storage (/myDecks) -
 * both real, shipped features that get no mention on the page a first-time visitor actually
 * lands on. Gated on useRemoteBackendConfigured (same condition Navbar.tsx uses for both its own
 * /whatsthat and My Decks links) - promoting a CTA to a route that would 404/no-op for a
 * Local-Folder-only visitor is worse than just not showing it.
 *
 * Catalog stats deliberately are NOT built here. A chart pipeline (server lane, post-Part-4) will
 * produce docs/assets/charts/catalog-coverage-strip.svg - this panel reserves a clearly marked
 * slot for that asset (see CatalogStatsSlot below) rather than standing up a parallel stats
 * widget from a live API call that the chart would then make redundant. Whoever wires the chart
 * in later replaces CatalogStatsSlot's placeholder body with an <img>/inline <svg> of that file -
 * the slot's own layout (full-width strip, card-styled border) is already shaped for it.
 */
import Image from "next/image";
import Link from "next/link";
import React from "react";
import Card from "react-bootstrap/Card";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";

import { useRemoteBackendConfigured } from "@/store/slices/backendSlice";

// Deliberately NOT the /whatsthat page's own #ff4719/starburst treatment - that's that page's
// own loud identity (see docs/features/printing-tags.md's visual-diagnosis history), and this
// panel lives on the site's normal Superhero-dark homepage. The whatsthat mark is used small,
// as a single accent on its own CTA card, not as a wholesale re-theme of this page.
function GameCard() {
  return (
    <Card bg="dark" text="light" className="h-100">
      <Card.Body className="d-flex flex-column">
        <div className="d-flex align-items-center gap-2 mb-2">
          <Image
            src="/whatsthat-mark.svg"
            alt=""
            width={28}
            height={28}
            style={{ height: 28, width: "auto" }}
          />
          <Card.Title className="mb-0">Play the identification game</Card.Title>
        </div>
        <Card.Text className="flex-grow-1">
          Think you know your Magic: the Gathering art? Help the community
          figure out which real-world printing, artist, or descriptor tag each
          card image actually depicts - one card at a time.
        </Card.Text>
        <Link href="/whatsthat" passHref legacyBehavior>
          <Card.Link
            as="a"
            className="btn btn-primary align-self-start"
            data-testid="homepage-panel-whatsthat-link"
          >
            What&apos;s That Card?
          </Card.Link>
        </Link>
      </Card.Body>
    </Card>
  );
}

function DecksCard() {
  return (
    <Card bg="dark" text="light" className="h-100">
      <Card.Body className="d-flex flex-column">
        <Card.Title>
          Your decks, encrypted so even we can&apos;t read them
        </Card.Title>
        <Card.Text className="flex-grow-1">
          Save your projects across devices with real client-side encryption -
          your decklists are encrypted before they ever leave your browser, and
          we genuinely have no way to read them. Sign in with Discord to get
          started.
        </Card.Text>
        <Link href="/myDecks" passHref legacyBehavior>
          <Card.Link
            as="a"
            className="btn btn-outline-light align-self-start"
            data-testid="homepage-panel-mydecks-link"
          >
            My Decks
          </Card.Link>
        </Link>
      </Card.Body>
    </Card>
  );
}

// Reserved for docs/assets/charts/catalog-coverage-strip.svg (chart pipeline, server lane,
// post-Part-4 - not built yet as of this panel). This placeholder's own job is just to hold the
// right shape/spacing in the page so the chart drops in later without a follow-up layout pass -
// it is NOT a stats widget of its own and deliberately fetches nothing.
function CatalogStatsSlot() {
  return (
    <div
      className="border border-secondary rounded p-4 text-center text-muted mt-3"
      style={{ borderStyle: "dashed" }}
      data-testid="homepage-panel-catalog-stats-slot"
    >
      Live catalog stats - coming soon
    </div>
  );
}

export function HomepagePanel() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  if (!remoteBackendConfigured) {
    return null;
  }
  return (
    <div data-testid="homepage-panel" className="my-4">
      <h2>Okay, what is this, really?</h2>
      <p className="text-muted">
        A print-shop wrapper is the front door, but the community built a lot
        more behind it - a printing-identification game that keeps the whole
        catalog honest, and a deck-saving system designed so even the people
        running the site can&apos;t see your lists.
      </p>
      <Row className="g-3">
        <Col md={6} sm={12}>
          <GameCard />
        </Col>
        <Col md={6} sm={12}>
          <DecksCard />
        </Col>
      </Row>
      <CatalogStatsSlot />
    </div>
  );
}
