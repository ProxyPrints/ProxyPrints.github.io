/**
 * Proposal F chart 7 - catalog composition by source. `catalogComposition` reuses the same
 * `SourceContribution` shape (and the same underlying `summarise_contributions()` aggregation)
 * the old /contributions page's live `GET 2/contributions/` query rendered - this panel is a
 * direct transform of that page's `ContributionsSummary`/`ContributionsPerSource`
 * (features/contributions/Contributions.tsx, now retired in favour of this cached panel), not a
 * redesign from scratch.
 */
import Link from "next/link";
import React from "react";

import { Card, Cardback, Token } from "@/common/constants";
import { CatalogComposition } from "@/common/schema_types";
import { AutofillTable } from "@/components/AutofillTable";
import { formatCount } from "@/features/stats/format";
import {
  BarRow,
  HorizontalBarChart,
} from "@/features/stats/HorizontalBarChart";

function formattedDatabaseSizeGB(totalDatabaseSize: number): string {
  return (
    Math.round((totalDatabaseSize / 1_000_000_000) * 100) / 100
  ).toLocaleString();
}

function cardCountByTypeRows(
  cardCountByType: CatalogComposition["cardCountByType"]
): BarRow[] {
  return [Card, Cardback, Token].map((cardType) => ({
    label: cardType,
    segments: [
      {
        key: cardType,
        label: cardType,
        value: cardCountByType[cardType] ?? 0,
      },
    ],
  }));
}

export function CatalogCompositionPanel({
  catalogComposition,
}: {
  catalogComposition: CatalogComposition;
}) {
  const totalImages = Object.values(catalogComposition.cardCountByType).reduce(
    (a, b) => a + b,
    0
  );

  return (
    <section data-testid="catalog-composition-panel" className="mb-5">
      <h2>Catalog composition</h2>
      <p>
        <b>{formatCount(totalImages)}</b> images, totalling{" "}
        <b>
          {formattedDatabaseSizeGB(catalogComposition.totalDatabaseSize)} GB
        </b>
        , from <b>{formatCount(catalogComposition.sources.length)}</b> sources.
      </p>
      <HorizontalBarChart
        title="Cards by type"
        bars={cardCountByTypeRows(catalogComposition.cardCountByType)}
        emptyMessage="No cards indexed yet."
      />
      {catalogComposition.sources.length > 0 && (
        <div className="mt-3">
          <AutofillTable
            headers={["Name", "Type", "Contribution"]}
            data={catalogComposition.sources.map((contribution) => [
              contribution.externalLink != null &&
              contribution.externalLink.length > 0 ? (
                <Link href={contribution.externalLink} target="_blank">
                  {contribution.name}
                </Link>
              ) : (
                contribution.name
              ),
              contribution.sourceType,
              <React.Fragment key={`${contribution.name}-description`}>
                <b>{contribution.qtyCards}</b> card
                {contribution.qtyCards != "1" && "s"},{" "}
                <b>{contribution.qtyCardbacks}</b> cardback
                {contribution.qtyCardbacks != "1" && "s"}, and{" "}
                <b>{contribution.qtyTokens}</b> token
                {contribution.qtyTokens != "1" && "s"}, at{" "}
                <b>{contribution.avgdpi} DPI</b> on average and a total size of{" "}
                <b>{contribution.size}</b>.
                {contribution.description.length > 0 && (
                  <>
                    <br />
                    <i>&quot;{contribution.description}&quot;</i>
                  </>
                )}
              </React.Fragment>,
            ])}
            hover={true}
            alignment={"left"}
            uniformWidth={false}
            variant="default"
          />
        </div>
      )}
    </section>
  );
}
