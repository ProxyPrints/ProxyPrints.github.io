import { useEffect, useState } from "react";

/**
 * Issue #266 (docs/proposals - the /display responsive layout spec's §4/§6 R2): the two rails'
 * `Offcanvas` inline-vs-drawer behaviour needs FOUR distinct tiers (phone/tablet/laptop/desktop),
 * but Offcanvas's own `responsive` prop only distinguishes "below breakpoint" vs. "at/above
 * breakpoint" for ONE breakpoint at a time. This hook is what lets the left rail pick "bottom"
 * (phone) vs. "start" (tablet) placement at runtime - both below its own `lg` inline threshold -
 * via `matchMedia` listeners, matching the spec's explicit "`placement` driven by a `matchMedia`
 * hook" instruction rather than a second CSS-only guess.
 */
export type ViewportTier = "phone" | "tablet" | "laptop" | "desktop";

// Bootstrap's own stock breakpoints (md=768, lg=992, xl=1200) - the same numbers Offcanvas's
// `responsive="lg"`/`responsive="xl"` props resolve to internally, so this hook's tier boundaries
// can never drift from the CSS breakpoints actually driving the rails' inline/drawer switch.
const PHONE_QUERY = "(max-width: 767.98px)";
const TABLET_QUERY = "(min-width: 768px) and (max-width: 991.98px)";
const LAPTOP_QUERY = "(min-width: 992px) and (max-width: 1199.98px)";

function resolveTier(): ViewportTier {
  if (typeof window === "undefined" || window.matchMedia == null) {
    // SSR (Next.js static export) has no viewport to measure yet - "desktop" matches
    // Layout.tsx's ContentMaxWidth ceiling (1200px) as the closest single guess, and gets
    // corrected on the client's very first render pass (useState's initializer below runs again
    // during hydration, where window IS available).
    return "desktop";
  }
  if (window.matchMedia(PHONE_QUERY).matches) {
    return "phone";
  }
  if (window.matchMedia(TABLET_QUERY).matches) {
    return "tablet";
  }
  if (window.matchMedia(LAPTOP_QUERY).matches) {
    return "laptop";
  }
  return "desktop";
}

export function useViewportTier(): ViewportTier {
  const [tier, setTier] = useState<ViewportTier>(resolveTier);

  useEffect(() => {
    if (typeof window === "undefined" || window.matchMedia == null) {
      return;
    }
    const queries = [PHONE_QUERY, TABLET_QUERY, LAPTOP_QUERY].map((query) =>
      window.matchMedia(query)
    );
    const update = () => setTier(resolveTier());
    queries.forEach((mql) => mql.addEventListener("change", update));
    // Re-resolve once on mount too - the SSR-time default above may be stale by the time this
    // effect runs (e.g. the window was resized between first paint and hydration completing).
    update();
    return () => {
      queries.forEach((mql) => mql.removeEventListener("change", update));
    };
  }, []);

  return tier;
}
