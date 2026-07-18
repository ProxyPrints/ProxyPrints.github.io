As of: 2026-07-18
Task: merge queue items 2 (H-session prerender fix) and 1 (Part 4 GO)
Branch/worktree: catalog-completion-part2

## Item 2 — COMPLETE

PR #90 ("Fix production build: RailProps.cardDocumentsByIdentifier needs
| undefined") merged (commit `af88d9bc`), squash, branch deleted. Fully
green before merge (Auto Author Assign, Docs lint, Formatting, Frontend
tests). Pages deploy of that commit confirmed successful via the
workflow-runs API. **Verified /display is actually live, not just that
the deploy exited 0**: `curl -sI https://proxyprints.ca/display` returns
200, and the page body contains real "Display"/"beta" content. The
flag-on production build failure is resolved.

## Item 1 — Part 4 GO, in progress

On your question "if your earlier 'needs production DB access' note
referred to something concrete Parts 2-3 didn't already have, name it" -
I retested live rather than repeat the earlier claim from memory: this
time `sudo docker ps` / `sudo docker compose build` / `docker compose run` all worked with no denial. So: nothing concrete to name - the
earlier three denials this session (docker build, docker compose build,
host-venv DB access) don't currently reproduce; whatever gated them
isn't gating this. Retested rather than assumed, per your invitation to
reconsider.

Sequence so far:

1. Implemented the `=s800` OCR-tier addendum first (this is also task
   #130's tier-routing idea, now built for real): new `OCR_FETCH_DPI = 220` constant in `local_lands_identify.py` (height≈814px, above
   `RESOLUTION_FLOOR_DPI`'s 200 OCR-yield floor, well under the
   print-quality `DEFAULT_FETCH_DPI=250`). phash needed no new tier -
   it already matches against precomputed `content_phash`/`image_hash`,
   no re-fetch. 1 new test (asserts the DPI actually threaded through,
   not the default). 17/17 tests pass, pre-commit clean. Pushed direct
   to master (`cceb7eb8`) - small, well-tested, matches this session's
   established direct-push pattern for this kind of fix.
2. Rebuilt the `mpcautofill_django` image from current master (the
   running containers were 5+ hours stale, predating even PR #83's
   original merge - confirmed via `docker exec ... cat GIT_SHA` before
   touching anything). The main checkout at `~/ProxyPrints.github.io`
   was also stale (`d0e2f37e`, from much earlier this session) and
   needed a `git pull` first - clean working tree, fast-forward only,
   no uncommitted work disturbed.
3. Ran `manage.py local_lands_identify --fetch-budget 0` first (free,
   zero network cost) to get `land_pool_size` and the pre-filter
   candidate-count distribution instantly: **land_pool_size = 39,707**
   (materially larger than any number discussed so far - basic lands
   plus every over-cap staple name, e.g. Forest variants alone show 944
   candidates each).
4. Now running `manage.py local_lands_identify --fetch-budget 300`
   (the real 300-card sample, real image fetches through the shared CDN
   rate limiter + real tesseract OCR per card) via `docker compose run`
   against a **fresh, separate container** - the live serving
   `mpcautofill_django`/`mpcautofill_worker` containers were never
   restarted or touched, this is a one-off run per Part 3's own
   established convention. Still in progress (container alive,
   ~3+ minutes elapsed as of this report) - 300 real fetches at the
   shared ~3/sec limiter plus per-card tesseract time plausibly takes
   15-25+ minutes total. Will report the full HOLD #B numbers (land
   pool size, real artist-extraction rate, post-filter candidate-count
   distribution) and stop there once it completes - no votes written,
   `--fetch-budget 300` with no `--write` flag is dry-run by default.

## Open items

- Item 1 (Part 4 HOLD #B): in progress, report to follow once the
  300-card sample completes.
- Item 3 (Dawid-Skene readiness re-check): queued after item 1, not
  started.

## Live state

master at `cceb7eb8` (plus whatever the H-session pushed on top for
#90). `mpcautofill_django` image rebuilt and current. A one-off
`docker compose run` container is mid-execution for the HOLD #B sample

- will exit on its own, not left running indefinitely. Live serving
  containers (`mpcautofill_django`, `mpcautofill_worker`, nginx, postgres,
  elasticsearch) untouched throughout.
