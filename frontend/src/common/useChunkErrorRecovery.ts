import { useRouter } from "next/router";
import { useEffect } from "react";

import {
  isChunkLoadError,
  reloadOnceForChunkError,
} from "@/common/chunkErrorRecovery";

/**
 * Installs the chunk-load-error recovery listeners for the lifetime of the app shell - see
 * chunkErrorRecovery.ts's module comment for why this is needed. Covers both routed transitions
 * (next/link client-side navigation, via router's own `routeChangeError` event) and any other
 * dynamic import failure (a plain global error/unhandledrejection listener).
 */
export function useChunkErrorRecovery(): void {
  const router = useRouter();

  useEffect(() => {
    const onWindowError = (event: ErrorEvent) => {
      if (isChunkLoadError(event.error ?? event.message)) {
        reloadOnceForChunkError();
      }
    };
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      if (isChunkLoadError(event.reason)) {
        reloadOnceForChunkError();
      }
    };
    // Next.js marks a routeChangeError with `cancelled: true` when a navigation is superseded by
    // another one before it finishes - a normal, frequent occurrence (e.g. clicking a second nav
    // link before the first page loads), not a failure to recover from.
    const onRouteChangeError = (err: unknown) => {
      if ((err as { cancelled?: boolean })?.cancelled) {
        return;
      }
      if (isChunkLoadError(err)) {
        reloadOnceForChunkError();
      }
    };

    window.addEventListener("error", onWindowError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    router.events.on("routeChangeError", onRouteChangeError);
    return () => {
      window.removeEventListener("error", onWindowError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
      router.events.off("routeChangeError", onRouteChangeError);
    };
  }, [router]);
}
