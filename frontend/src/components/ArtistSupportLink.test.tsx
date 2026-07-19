import { render, screen } from "@testing-library/react";
import React from "react";

import { ArtistSupportLink, buildArtistSupportURL } from "./ArtistSupportLink";

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

describe("ArtistSupportLink", () => {
  it("renders an external, deterministically-built link with the expected etiquette attributes", () => {
    render(
      <ArtistSupportLink artistName="Harold McNeill">
        Harold McNeill
      </ArtistSupportLink>
    );

    const link = screen.getByTestId("artist-support-link");
    expect(link).toHaveAttribute(
      "href",
      "https://www.mtgartistconnection.com/artist/Harold%20McNeill"
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("title", "via MTG Artist Connection");
    expect(link).toHaveTextContent("Harold McNeill");
  });
});
