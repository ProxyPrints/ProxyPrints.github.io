# Overview

**What this is**: ProxyPrints is a fork of
[chilli-axe/mpc-autofill](https://github.com/chilli-axe/mpc-autofill),
image-aggregation and print-automation software for tabletop card proxies
(Magic: The Gathering, specifically, on this fork). Frontend: a Next.js
static export deployed to GitHub Pages. Backend: Django + Elasticsearch +
Postgres, run as a separate service this fork operates independently of
upstream's own hosted instance.

**Relationship to upstream**: frontend and desktop-tool code stay close to
upstream's own architecture. This fork's independent work is concentrated
on the backend — a weighted-vote consensus system for crowd- and
machine-identification of exact card printings/artists/tags, a
Discord-OAuth moderation layer on top of it, and supporting infrastructure
(an image CDN, a local-file catalog source type) upstream doesn't have.
Some of that work is intended to go back upstream eventually — see
`infrastructure.md`'s "Upstreaming to chilli-axe/mpc-autofill" section and
`upstreaming/` for what's queued and how that process works. Until that
lands, a few outward-facing links (desktop-tool release channel, wiki)
still point at upstream's own, since this fork hasn't built or verified its
own equivalents yet — noted here so it isn't a silent surprise, not because
it's hidden elsewhere.

## The three systems

1. **Catalog + votes** — the card catalog itself (`Card`/`Source` models,
   Elasticsearch-backed search) plus the weighted-vote consensus system
   layered on it: printing tags, artist attribution, and general tags, each
   resolved from anonymous, machine, and moderator votes against
   source-weighted thresholds. See
   [`features/printing-tags.md`](features/printing-tags.md) and
   [`upstreaming/vote-system.md`](upstreaming/vote-system.md).
2. **Identification pipeline** — the methodology for turning an ambiguous,
   self-reported card name into one specific printing: OCR, perceptual-hash
   clustering, deductive backfill, and fallback engines, each contributing
   weighted votes into the consensus system above. The formal write-up of
   _why_ this is sound (false-accept bound, prior-art comparison, soundness
   mechanisms) is [`theory.md`](theory.md) — reviewed and approved by the
   owner, written for exactly this kind of external reader.
   [`features/catalog-completion-plan.md`](features/catalog-completion-plan.md)
   is the live, in-progress build log for this pipeline's current work.
3. **Print tooling** — the deck-building editor, XML/PDF/decklist export,
   and the print-shop hand-off pages (NotMPC, PringlePrints) that turn a
   finished project into an actual order. See
   [`features/pdf-generator.md`](features/pdf-generator.md),
   [`features/print-export-page.md`](features/print-export-page.md),
   [`features/google-drive-connect.md`](features/google-drive-connect.md),
   [`features/image-cdn.md`](features/image-cdn.md).

A fourth piece sits adjacent to all three rather than being its own system:
moderation (Discord OAuth login, a `Moderators` group gating sensitive-tag
approval and catalog cleanup) is built on top of the vote-consensus system
above it, not separate from it — see
[`features/moderation.md`](features/moderation.md).

## Where the formal methodology lives

[`theory.md`](theory.md) is the single most load-bearing doc for
understanding _why_ the identification pipeline's crowd- and
machine-derived consensus can be trusted. It's written to stand alone, with
minimal repo-internal jargon, specifically because it doubles as the
technical annex for [`federation-v1.md`](federation-v1.md)'s cross-instance
verdict-exchange pitch — the reason this page exists is that `theory.md` is
the link handed to a reader with no other context on this fork.

## Everything else

[`README.md`](README.md) indexes the rest of this directory by audience —
understanding the system, operating it, plans & proposals, and records.
