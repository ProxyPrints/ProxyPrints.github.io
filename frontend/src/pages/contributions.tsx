import { useRouter } from "next/router";
import { useEffect } from "react";

// /stats transform (2026-07-29, Proposal F, docs/features/catalog-stats.md) - /contributions is
// now /stats (ContributionsSummary/ContributionsPerSource were retired in favour of
// CatalogCompositionPanel.tsx, reading the same SourceContribution shape off the cached
// `catalogComposition` panel instead of a live GET 2/contributions/ query per request;
// ContributionGuidelines moved to features/stats/ContributionGuidelines.tsx unchanged). This
// route is now a plain client-side bounce forward to preserve old bookmarks/links, mirroring
// pages/display.tsx's own redirect-shell pattern for the same underlying reason (a Next static
// export on GitHub Pages has no server-side redirect config available to us). Query params and
// the URL fragment are forwarded byte-for-byte from window.location rather than reconstructed
// from router.query, since router.query never reflects the fragment - see
// pages/display.tsx/SharedDeckPage.tsx's own comment on the same point.
export default function ContributionsRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace(`/stats${window.location.search}${window.location.hash}`);
  }, [router]);
  return null;
}
