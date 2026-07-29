/**
 * Proposal F /stats page - the participation (call-to-action) panel. Not one of the numbered 7
 * charts - the "N cards resolved, here's how to help" strip the proposal's mock shows above the
 * fold, moved here as the top-of-page CTA per the owner's brief for this page ("we'll actually
 * transform the old contributors page into our stats page").
 *
 * DELIBERATELY NO PERCENTAGE, ANYWHERE ON THIS PANEL. Every number below is a raw count, straight
 * off `CatalogStatsResponse.participation` - see MPCAutofill/cardpicker/catalog_stats.py's
 * `compute_participation` docstring for the owner ruling this encodes (0.1% of a computed ratio
 * reads as "this project failed"; the backend emits both the numerator- and denominator-shaped
 * numbers precisely so the page can choose a framing that isn't that ratio). `confirmable` -
 * "cards a human could settle right now" - is the headline, not `total`.
 */
import Link from "next/link";
import React from "react";

import { Participation } from "@/common/schema_types";
import {
  BarRow,
  HorizontalBarChart,
} from "@/features/stats/HorizontalBarChart";
import { StatTile } from "@/features/stats/StatTile";

const HUMAN_VOTE_ROWS = (humanVotes: Participation["humanVotes"]): BarRow[] => [
  {
    label: "Printing tags",
    segments: [
      {
        key: "printingTag",
        label: "Printing tags",
        value: humanVotes.printingTag,
      },
    ],
  },
  {
    label: "Artist votes",
    segments: [
      { key: "artist", label: "Artist votes", value: humanVotes.artist },
    ],
  },
  {
    label: "Descriptor tags",
    segments: [{ key: "tag", label: "Descriptor tags", value: humanVotes.tag }],
  },
];

export function ParticipationPanel({
  participation,
}: {
  participation: Participation;
}) {
  return (
    <section data-testid="participation-panel" className="mb-5">
      <h2>Help settle the catalog</h2>
      <div className="d-flex align-items-baseline gap-2 flex-wrap">
        <StatTile
          testId="participation-confirmable"
          label="cards a human could settle right now"
          value={participation.confirmable.toLocaleString()}
          emphasize
        />
      </div>
      <p className="mt-2">
        <Link href="/whatsthat" className="btn btn-primary">
          Help confirm a card
        </Link>
      </p>
      <div className="d-flex flex-wrap gap-4 mt-4">
        <StatTile
          testId="participation-contested"
          label="contested (need more eyes to break a tie)"
          value={participation.contested.toLocaleString()}
        />
        <StatTile
          testId="participation-fresh"
          label="fresh (not yet looked at)"
          value={participation.fresh.toLocaleString()}
        />
        <StatTile
          testId="participation-total"
          label="cards in the catalog"
          value={participation.total.toLocaleString()}
        />
      </div>

      <h3 className="mt-4 h5">Who&apos;s doing the tagging work</h3>
      <div className="d-flex flex-wrap gap-4 mb-3">
        <StatTile
          testId="participation-distinct-voters"
          label="distinct human contributors"
          value={participation.distinctHumanVoters.toLocaleString()}
        />
        <StatTile
          testId="participation-human-votes-total"
          label="human confirmations logged in total"
          value={participation.humanVotes.total.toLocaleString()}
        />
      </div>
      <HorizontalBarChart
        title="Human confirmations by kind"
        bars={HUMAN_VOTE_ROWS(participation.humanVotes)}
        emptyMessage="No human confirmations logged yet."
      />

      <h3 className="mt-4 h5">Duplicate-art groups (by image checksum)</h3>
      <div className="d-flex flex-wrap gap-4">
        <StatTile
          testId="participation-md5-groups"
          label="groups with more than one card sharing an image"
          value={participation.md5Groups.groupsWithMultipleCards.toLocaleString()}
        />
        <StatTile
          testId="participation-md5-cards"
          label="cards in a multi-card group"
          value={participation.md5Groups.cardsInMultiCardGroups.toLocaleString()}
        />
        <StatTile
          testId="participation-md5-largest"
          label="largest group size"
          value={participation.md5Groups.largestGroupSize.toLocaleString()}
        />
      </div>
    </section>
  );
}
