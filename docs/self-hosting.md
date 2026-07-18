# Instance Admin Guide

This page is for someone standing up and operating their _own_ instance
of this project — not specific to how ProxyPrints.ca itself is hosted.
For this fork's own current configuration and exact commands, see the
repo's [`docs/infrastructure.md`](https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/docs/infrastructure.md)
and [`docs/troubleshooting.md`](https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/docs/troubleshooting.md)
— this page links out to those rather than duplicating them, since
operational detail changes faster than a wiki page should.

Migrated from the wiki's own `Instance-Admin-Guide` page (previously
hand-maintained there directly) — this file is now the source; the wiki
page (kept at the same name/URL, so nothing that links to it breaks)
regenerates from it. See [`documentation-process.md`](documentation-process.md).

## Architecture

- **Frontend**: a Next.js static export, deployable to any static host
  (GitHub Pages, Cloudflare Pages, etc.).
- **Backend**: Django + PostgreSQL + Elasticsearch, run via Docker
  Compose (`docker/docker-compose.prod.yml`). Use Docker Compose **v2**
  (`docker compose`, no hyphen) — v1 has a known fatal recreate bug.
- **Image serving**: a Cloudflare Worker + R2 bucket image CDN
  (`image-cdn/`), or point at your own image hosting.

## Bringing an instance up

1. Provide your own `docker/.env` with a `DJANGO_SECRET_KEY` and any
   other secrets the compose file references — never commit this file.
2. Provide a `MPCAutofill/drives.csv` describing your own catalog
   sources (Google Drive folders, local folders, etc.) — this file is
   gitignored by design; the catalog is only as good as the sources you
   list here.
3. `docker compose -f docker-compose.prod.yml up --build -d` from
   `docker/`. The entrypoint runs migrations and a cheap source-list
   sync before the API comes up; the first full catalog scan is
   scheduled asynchronously rather than blocking startup — see
   `docs/infrastructure.md`'s "Startup vs. scheduled catalog sync" for
   exactly what runs when.
4. Point your reverse proxy (nginx, in this fork's case) at the `django`
   container, and your frontend build's `NEXT_PUBLIC_BACKEND_URL` at
   your backend's public URL.

## Keeping it running

- Set a `restart` policy on every service, and consider an OS-level unit
  (systemd or equivalent) that brings the stack back up after a host
  reboot — a container restart policy alone doesn't cover every recovery
  path (e.g. a fully-removed container).
- If you recreate the backend container, restart your reverse proxy too
  — most reverse proxies resolve a backend container's address once at
  their own startup, not per-request, and will otherwise proxy to a
  now-stale address.
- Zero first-party telemetry ships with this fork by design (Sentry and
  Google Analytics were both fully removed upstream of this guide) — if
  you want your own instance's usage/error visibility, you'll need to
  add your own.

## Troubleshooting

Operational gotchas (CI quirks, container-restart footguns, and the
like) that come up repeatedly are tracked symptom-first in
[`docs/troubleshooting.md`](https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/docs/troubleshooting.md) in
the repo — check there before re-deriving a fix.
