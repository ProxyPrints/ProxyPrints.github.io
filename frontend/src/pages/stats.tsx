/**
 * /stats - public catalog/moderation transparency page (Proposal F,
 * docs/proposals/proposal-f-public-stats-page.md; backend PR #556,
 * docs/features/catalog-stats.md). Reads the cache-only `GET 1/catalogStats/` endpoint
 * (`useGetCatalogStatsQuery`) - five of the proposal's seven charts plus the `participation`
 * call-to-action panel this pass (charts 1/resolutionProgress and 5/hashCoverage are deliberately
 * deferred on the backend, see that module's own docstring).
 *
 * THIS IS A TRANSFORM OF THE OLD /contributions PAGE, NOT A NEW PARALLEL PAGE - the owner's own
 * words: "we'll actually transform the old contributors page into our stats page and put it back
 * in the top nav." `catalogComposition` (CatalogCompositionPanel.tsx) is the direct successor to
 * the old page's `ContributionsSummary`/`ContributionsPerSource` (same `SourceContribution` data,
 * now off the hourly cache instead of a live `GET 2/contributions/` query per request), and
 * `ContributionGuidelines` is preserved verbatim underneath it. `pages/contributions.tsx` is now a
 * redirect shell to here (see that file's own comment) - old bookmarks/links still work.
 *
 * CACHE-MISS HANDLING: the endpoint is cache-only and returns a fully-shaped, all-zero blob with
 * `generatedAt: null` on a miss (cold cache, or the "shared" backend not configured) - it never
 * 500s. `generatedAt === null` is treated as "not computed yet" here, NEVER as "zero is the real
 * answer" - rendering the zeroed panels as if they were real data would misrepresent an
 * infrastructure gap as an empty catalog. `generatedAt` (once non-null) is always shown so a
 * reader can judge freshness for themselves (the cache is warmed hourly, no live aggregation ever
 * happens on this request path).
 */
import Head from "next/head";
import React from "react";

import { ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { Spinner } from "@/components/Spinner";
import { CatalogCompositionPanel } from "@/features/stats/CatalogCompositionPanel";
import { ContributionGuidelines } from "@/features/stats/ContributionGuidelines";
import { ContributionsOverTimePanel } from "@/features/stats/ContributionsOverTimePanel";
import { formatGeneratedAt } from "@/features/stats/format";
import { ParticipationPanel } from "@/features/stats/ParticipationPanel";
import { RunHistoryPanel } from "@/features/stats/RunHistoryPanel";
import { SkipBreakdownPanel } from "@/features/stats/SkipBreakdownPanel";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import { useGetCatalogStatsQuery } from "@/store/api";
import {
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

function NotComputedYet() {
  return (
    <div data-testid="stats-not-computed-yet" className="text-center my-5 py-5">
      <h2>The stats cache hasn&apos;t been computed yet</h2>
      <p className="text-muted">
        This page reads from an hourly cache, and it hasn&apos;t run on this
        instance yet - check back soon. This is not the same as &quot;the
        catalog is empty&quot;.
      </p>
    </div>
  );
}

// Exported (unlike the equivalent pre-transform ContributionsOrDefault) so Jest can exercise the
// no-backend/loading/cache-miss/populated state machine directly without also mounting
// ProjectContainer's useNavbarHeight (ResizeObserver/MutationObserver) machinery - see
// features/stats/StatsPage.test.tsx. That test lives under src/features/, NOT src/pages/ -
// Next.js compiles every file under src/pages/ into the app's routable/client bundle, and a
// test file there would drag in src/mocks/server.ts (the msw NODE server, needs `async_hooks`)
// and break `next build` (confirmed: this broke CI on this branch's first push - "Module not
// found: Can't resolve 'async_hooks'" - before the test was relocated here).
export function CatalogStatsBody() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  const catalogStatsQuery = useGetCatalogStatsQuery();

  if (!remoteBackendConfigured) {
    return <NoBackendDefault requirement="remote" />;
  }
  if (catalogStatsQuery.isFetching && catalogStatsQuery.data == null) {
    return <Spinner />;
  }
  const stats = catalogStatsQuery.data;
  if (stats == null || stats.generatedAt == null) {
    return <NotComputedYet />;
  }

  return (
    <>
      <p className="text-muted" data-testid="stats-generated-at">
        Generated {formatGeneratedAt(stats.generatedAt)}
      </p>
      <ParticipationPanel participation={stats.participation} />
      <CatalogCompositionPanel catalogComposition={stats.catalogComposition} />
      <ContributionsOverTimePanel
        contributionsOverTime={stats.contributionsOverTime}
      />
      <SkipBreakdownPanel skipBreakdown={stats.skipBreakdown} />
      <RunHistoryPanel recent={stats.runHistory.recent} />
      <hr />
      <ContributionGuidelines />
      <br />
      <Footer />
    </>
  );
}

export default function Stats() {
  const projectName = useProjectName();
  return (
    <ProjectContainer>
      <Head>
        <title>{`${projectName} Stats`}</title>
        <meta
          name="description"
          content={`Catalog and moderation transparency stats for ${ProjectName} - zero visitor tracking, every number here is server-side catalog/moderation state.`}
        />
      </Head>
      <h1>Catalog stats</h1>
      <p className="text-muted">
        Zero visitor tracking &mdash; every number below is catalog/moderation
        state, nothing about you.
      </p>
      <CatalogStatsBody />
    </ProjectContainer>
  );
}
