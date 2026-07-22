import { useEffect, useState } from "react";

import { NavbarHeight } from "@/common/constants";

/**
 * Real, measured height of the fixed navbar (`nav.navbar`, rendered by Navbar.tsx), replacing
 * the hardcoded `NavbarHeight` constant for consumers whose own positioning math breaks when the
 * real navbar is taller than that guess (issue #250 - confirmed via
 * `docs/troubleshooting.md`'s own `boundingBox()` measurement: 64px real vs the constant's 50px
 * in the fully-authenticated, every-backend-feature-enabled state, and up to 88px once the
 * crowded left-hand `Nav` wraps to a second line). `NavbarHeight` itself is left untouched here
 * (still the SSR/pre-mount fallback below, and still what every OTHER heightDelta consumer -
 * Explore.tsx, ProjectEditor.tsx, FinishedMyProject.tsx - uses directly) - this hook is an
 * additive, opt-in replacement for the specific call sites confirmed broken by a real navbar/
 * content collision (Layout.tsx's `ContentContainer`, QuestionFeed.tsx's hero grid), not a
 * blanket swap-out of the constant everywhere; #250 stays open for that broader decision.
 *
 * A plain `ResizeObserver` on the actual DOM node (found by the same `nav.navbar` selector
 * `docs/troubleshooting.md` already uses to confirm this bug) rather than global state - the
 * navbar is a single, always-mounted element and every consumer just needs its current height,
 * so there's no real state to coordinate between components. `Navbar.tsx` itself renders inside
 * `DisableSSR` (client-only), so this hook has nothing to observe until after that first client
 * paint - a `MutationObserver` on `document.body` catches the node appearing, then hands off to
 * `ResizeObserver` for every height change after that (nav wrapping to a second line on
 * window resize, or a conditionally-rendered link appearing once an async `whoami`/backend-
 * config query resolves).
 */
export function useNavbarHeight(): number {
  const [height, setHeight] = useState<number>(NavbarHeight);

  useEffect(() => {
    let resizeObserver: ResizeObserver | null = null;

    const observeNavbar = (nav: Element) => {
      resizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (entry != null) {
          setHeight(entry.contentRect.height);
        }
      });
      resizeObserver.observe(nav);
      // Capture the current height immediately too - ResizeObserver's callback fires async on
      // the next frame, and we'd rather start with a real measurement than the fallback for
      // however long that takes.
      setHeight(nav.getBoundingClientRect().height);
    };

    const existingNavbar = document.querySelector("nav.navbar");
    if (existingNavbar != null) {
      observeNavbar(existingNavbar);
      return () => resizeObserver?.disconnect();
    }

    // DisableSSR mounts the navbar a tick after this component's own first client render -
    // watch for it to appear, then switch to ResizeObserver as above.
    const mutationObserver = new MutationObserver(() => {
      const nav = document.querySelector("nav.navbar");
      if (nav != null) {
        mutationObserver.disconnect();
        observeNavbar(nav);
      }
    });
    mutationObserver.observe(document.body, { childList: true, subtree: true });

    return () => {
      mutationObserver.disconnect();
      resizeObserver?.disconnect();
    };
  }, []);

  return height;
}
