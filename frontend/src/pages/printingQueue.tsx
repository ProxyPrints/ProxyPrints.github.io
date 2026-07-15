import { useRouter } from "next/router";
import { useEffect } from "react";

// This page was renamed to whatsthat.tsx in the queue-redesign PR (2026-07-15). The site is
// a static export behind GitHub Pages/Cloudflare - no server-side redirect config is
// available to us there (unlike api.proxyprints.ca, which nginx fronts directly) - so an old
// bookmark/tab on this URL, or a Discord OAuth `next=` round-trip mid-flight through the
// rename, needs a real page here to bounce forward client-side rather than 404ing.
export default function PrintingQueueRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/whatsthat");
  }, [router]);
  return null;
}
