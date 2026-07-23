import { useRouter } from "next/router";
import { useEffect } from "react";

// Proposal H switchover (2026-07-23, issues #231/#272, following up on nav-redesign PR #313) -
// /display used to host the unified editor+sheet page; it now lives at /editor (see
// pages/editor.tsx), so this route is a plain client-side bounce forward to preserve old
// bookmarks/links, mirroring pages/printingQueue.tsx's own redirect-shell pattern for the same
// underlying reason (a Next static export on GitHub Pages has no server-side redirect config
// available to us). Query params and the URL fragment are forwarded byte-for-byte from
// window.location rather than reconstructed from router.query, since router.query never
// reflects the fragment - see SharedDeckPage.tsx's own comment on the same point. Deck state
// itself lives in the client-side Redux store, not the URL, so nothing deck-specific needs
// forwarding beyond whatever query/hash the visitor already had.
export default function DisplayRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace(`/editor${window.location.search}${window.location.hash}`);
  }, [router]);
  return null;
}
