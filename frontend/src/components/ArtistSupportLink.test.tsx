import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { Provider } from "react-redux";

import { localBackend, noBackend } from "@/common/test-constants";
import {
  artistExternalLinksDivergentSlug,
  artistExternalLinksFullRow,
  artistExternalLinksInstagramOnly,
  artistExternalLinksNotFound,
  artistExternalLinksOneLink,
  ArtistExternalLinksTestArtists,
  artistExternalLinksWithSignatureBadge,
  artistExternalLinksZeroLinks,
} from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { setupStore } from "@/store/store";

import { ArtistSupportLink, buildArtistSupportURL } from "./ArtistSupportLink";

function renderApplet(
  artistName: string,
  backend = localBackend,
  defaultExpanded = false
) {
  const store = setupStore({ backend });
  render(
    <Provider store={store}>
      <ArtistSupportLink
        artistName={artistName}
        defaultExpanded={defaultExpanded}
      />
    </Provider>
  );
}

// Issue #709 - the applet defaults to collapsed (a single line: the page-link + a disclosure
// toggle); this expands it so tests can assert on the commerce links/badge/credit it reveals.
function expandApplet() {
  fireEvent.click(screen.getByTestId("artist-support-toggle"));
}

describe("buildArtistSupportURL", () => {
  it("URL-encodes the artist name into an MTG Artist Connection artist-page URL", () => {
    expect(buildArtistSupportURL("Harold McNeill")).toBe(
      "https://www.mtgartistconnection.com/artist/Harold%20McNeill"
    );
  });

  it("encodes characters beyond spaces (e.g. an ampersand) too", () => {
    expect(buildArtistSupportURL("Rob & Christian Alzmann")).toBe(
      "https://www.mtgartistconnection.com/artist/Rob%20%26%20Christian%20Alzmann"
    );
  });
});

describe("ArtistSupportLink applet", () => {
  it("never renders as an empty box: the MTGAC page link is present before any network response resolves, collapsed to a single line by default", () => {
    // no server.use(...) at all - the request is in flight (or, with noBackend below, never
    // even fires) - the applet's base shape must already be there, not a spinner/empty state.
    renderApplet("Harold McNeill");

    expect(screen.getByTestId("artist-support-applet")).toBeInTheDocument();
    expect(screen.getByTestId("artist-support-link")).toHaveAttribute(
      "href",
      buildArtistSupportURL("Harold McNeill")
    );
    expect(screen.getByTestId("artist-support-toggle")).toBeInTheDocument();
    expect(
      screen.queryByTestId("artist-support-credit")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("artist-support-commerce-links")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("artist-support-signature-badge")
    ).not.toBeInTheDocument();
  });

  it("expanding the collapsed applet reveals the credit line, even with nothing else to show", () => {
    renderApplet("Harold McNeill");

    expandApplet();

    expect(screen.getByTestId("artist-support-credit")).toHaveTextContent(
      "MTG Artist Connection"
    );
  });

  it("collapsing again after expanding hides the credit line without unmounting the applet", () => {
    renderApplet("Harold McNeill");

    expandApplet();
    expect(screen.getByTestId("artist-support-credit")).toBeInTheDocument();

    expandApplet();
    expect(
      screen.queryByTestId("artist-support-credit")
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("artist-support-applet")).toBeInTheDocument();
  });

  it("defaultExpanded starts the applet open, with the credit line visible without any interaction (the /editor rail's usage)", () => {
    renderApplet("Harold McNeill", localBackend, true);

    expect(screen.getByTestId("artist-support-credit")).toBeInTheDocument();
  });

  it("with no remote backend configured, still renders the fallback link and makes no request at all", () => {
    // No server.use(...) either - if a request were made, MSW's onUnhandledRequest: "error"
    // config would fail this test, so a clean pass here IS the "no request" assertion.
    renderApplet("Harold McNeill", noBackend);

    expect(screen.getByTestId("artist-support-link")).toHaveAttribute(
      "href",
      buildArtistSupportURL("Harold McNeill")
    );

    expandApplet();
    expect(screen.getByTestId("artist-support-credit")).toBeInTheDocument();
  });

  it("cache-miss/not-indexed response falls back to the deterministic URL, never a broken or empty state", async () => {
    server.use(artistExternalLinksNotFound);
    renderApplet("Harold McNeill");

    await waitFor(() =>
      expect(screen.getByTestId("artist-support-link")).toHaveAttribute(
        "href",
        buildArtistSupportURL("Harold McNeill")
      )
    );
    expandApplet();
    expect(
      screen.queryByTestId("artist-support-commerce-links")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("artist-support-signature-badge")
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("artist-support-credit")).toBeInTheDocument();
  });

  it("zero commerce links (found: true): still renders the MTGAC page link and (once expanded) the credit, no commerce buttons, no empty box", async () => {
    server.use(artistExternalLinksZeroLinks);
    renderApplet(ArtistExternalLinksTestArtists.zeroLinks);

    await waitFor(() =>
      expect(screen.getByTestId("artist-support-link")).toHaveAttribute(
        "href",
        `https://www.mtgartistconnection.example/artist/${encodeURIComponent(
          ArtistExternalLinksTestArtists.zeroLinks
        )}`
      )
    );
    expandApplet();
    expect(
      screen.queryByTestId("artist-support-commerce-links")
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("artist-support-credit")).toBeInTheDocument();
  });

  it("pageUrl is preferred over the constructed URL when the response is found, even when they genuinely disagree (the 8.2% divergence case)", async () => {
    server.use(artistExternalLinksDivergentSlug);
    renderApplet(ArtistExternalLinksTestArtists.divergentSlug);

    const constructedURL = buildArtistSupportURL(
      ArtistExternalLinksTestArtists.divergentSlug
    );
    const mtgacPageUrl =
      "https://www.mtgartistconnection.example/artist/Aurelien%20D%20Vasseur";
    // sanity-check the fixture itself actually diverges, so this test would fail loudly if the
    // fixture were ever "fixed" to coincidentally match - the whole point is that they disagree.
    expect(mtgacPageUrl).not.toEqual(constructedURL);

    await waitFor(() =>
      expect(screen.getByTestId("artist-support-link")).toHaveAttribute(
        "href",
        mtgacPageUrl
      )
    );
    expect(screen.getByTestId("artist-support-link")).not.toHaveAttribute(
      "href",
      constructedURL
    );
  });

  it("exactly one commerce link renders one stretched button, reachable via the expand toggle", async () => {
    server.use(artistExternalLinksOneLink);
    renderApplet(ArtistExternalLinksTestArtists.oneLink);

    await waitFor(() =>
      expect(screen.getByTestId("artist-support-toggle")).toBeInTheDocument()
    );
    expandApplet();

    const links = await screen.findAllByTestId("artist-support-commerce-link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      "https://cormacwindemere.example/"
    );
    expect(links[0]).toHaveClass("w-100");
  });

  it("full row (5 commerce links) renders in the fixed priority order, capped at 5", async () => {
    server.use(artistExternalLinksFullRow);
    renderApplet(ArtistExternalLinksTestArtists.fullRow);
    expandApplet();

    const links = await screen.findAllByTestId("artist-support-commerce-link");
    expect(links).toHaveLength(5);
    expect(links.map((link) => link.getAttribute("data-link-type"))).toEqual([
      "website",
      "artstation",
      "inprnt",
      "mountainmage",
      "omalink",
    ]);
  });

  it("an artist whose only link is instagram surfaces it (the 157-artist rescue scenario)", async () => {
    server.use(artistExternalLinksInstagramOnly);
    renderApplet(ArtistExternalLinksTestArtists.instagramOnly);
    expandApplet();

    const links = await screen.findAllByTestId("artist-support-commerce-link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("data-link-type", "instagram");
    expect(links[0]).toHaveTextContent("Instagram");
  });

  it("the Mark's Signature Service flag renders as a badge, never as a link", async () => {
    server.use(artistExternalLinksWithSignatureBadge);
    renderApplet(ArtistExternalLinksTestArtists.signatureService);
    expandApplet();

    const badge = await screen.findByTestId("artist-support-signature-badge");
    expect(badge.tagName).toBe("SPAN");
    expect(badge).not.toHaveAttribute("href");
    expect(badge).toHaveTextContent("Mark's Signature Service");
    // the badge must never be counted as (or rendered inside) a commerce link button
    const commerceLinks = screen.getAllByTestId("artist-support-commerce-link");
    for (const link of commerceLinks) {
      expect(link).not.toHaveAttribute(
        "data-link-type",
        "markssignatureservice"
      );
    }
  });

  it("the MTG Artist Connection credit is always reachable and links to their homepage", async () => {
    server.use(artistExternalLinksOneLink);
    renderApplet(ArtistExternalLinksTestArtists.oneLink);
    expandApplet();

    const credit = await screen.findByTestId("artist-support-credit");
    expect(credit).toHaveTextContent("MTG Artist Connection");
    const creditLink = credit.querySelector("a");
    expect(creditLink).toHaveAttribute(
      "href",
      "https://www.mtgartistconnection.com/"
    );
  });

  it("every rendered link/button carries the external-link etiquette attributes", async () => {
    server.use(artistExternalLinksOneLink);
    renderApplet(ArtistExternalLinksTestArtists.oneLink);

    const primaryLink = screen.getByTestId("artist-support-link");
    expect(primaryLink).toHaveAttribute("target", "_blank");
    expect(primaryLink).toHaveAttribute("rel", "noopener noreferrer");

    expandApplet();
    const commerceLink = await screen.findByTestId(
      "artist-support-commerce-link"
    );
    expect(commerceLink).toHaveAttribute("target", "_blank");
    expect(commerceLink).toHaveAttribute("rel", "noopener noreferrer");
  });
});
