As of: 2026-07-19
What this is: README-into-the-docs-pipeline — folds into Proposal I
(`docs/proposals/proposal-i-docs-as-site-source.md`, single-transform
architecture). **AUDIT ONLY, HOLD.** This doc is the deliverable requested:
a content merge map for `readme.md` plus a proposed post-review
architecture. **No restructuring has happened. `readme.md` is untouched.**
Content judgment (what's kept, what's cut, exact final wording) is the
owner's call — this doc proposes, it doesn't decide.

Note on filename casing: the actual file at the repo root is `readme.md`
(lowercase), not `README.md` — GitHub renders either casing as the repo's
front page, but every reference in this doc uses the real on-disk name.

## 0. Grounding: what `readme.md` actually contains today

Read in full before writing the map below — 35 lines, verified line by
line, not skimmed:

```
1-5:   "# MPC Autofill" header + upstream's own logo image
       (i.postimg-hosted at chilli-axe's own URL)
7:     Tagline: "MPC Autofill is image aggregation & print automation
       software..." (accurate in spirit, but names the WRONG project)
9-16:  Three CI badges (desktop-tool-ci, web-ci, cloudflare-workers-ci)
       + a releases-download-count badge + a "Buy Me A Coffee" button —
       ALL hardcoded to github.com/chilli-axe/mpc-autofill, not this repo
18:    "check the Releases tab" — links to chilli-axe/mpc-autofill's
       own Releases page
20-23: "# Sponsors" — SignPath.io free code-signing credit
25-30: "# Code Signing Policy" — committers/reviewers/approvers link to
       chilli-axe's own GitHub org and people list; a Privacy Policy
       link to mpcautofill.github.io/about (upstream's own hosted site,
       not proxyprints.ca); a boilerplate "no data transfer" sentence
32-34: "# Documentation" — points to chilli-axe/mpc-autofill's own wiki
```

**The headline finding**: this file has never been touched since the
fork. Every link, badge, and org reference in it points at
`chilli-axe/mpc-autofill` or `mpcautofill.github.io`, not this repo or
`proxyprints.ca`. There is no GPL-3 license notice anywhere in it (the
site's own `/about` page has one — see §2's non-negotiables), and no
sentence stating this repo IS a fork (it just silently presents itself
as chilli-axe's own project). This is not primarily a "which doc already
says this better" problem — it's a "this file describes the wrong
project" problem. The merge map below reflects that: there is very
little existing prose in `readme.md` worth preserving verbatim, and the
"(c) unique content with no docs/ home" bucket the task anticipated is
essentially empty for the same reason — almost nothing here is uniquely
true and worth keeping that doesn't already exist, better, elsewhere.

## 1. Content audit — the merge map

| readme.md section                                                                     | Verdict                                                                                                     | Reasoning + destination                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Header (title, logo, tagline)                                                         | **(a) Stale — remove**                                                                                      | Names the wrong project, uses upstream's own logo. Replace with ProxyPrints' own identity, seeded from `docs/wiki-home-intro.md` (see below) — already-written, already-committed, already used as the wiki Home page's own intro, and already correctly states the fork relationship in one paragraph.                                                                                                                                                                                                                                                                                                                                   |
| CI badges (3)                                                                         | **(a) Stale, but correctable, not just removable** — flagged as its own line item, not lumped with the rest | **Verified, not assumed**: `.github/workflows/desktop-tool-ci.yml`, `web-ci.yml`, and `cloudflare-workers-ci.yml` all exist in THIS repo with the exact same names the badges already reference — the badges aren't describing a nonexistent thing, they're just pointed at the wrong repo (`chilli-axe/mpc-autofill` instead of `ProxyPrints/ProxyPrints.github.io`). A mechanical URL swap, not a content judgment call — flagging it as ready-to-fix rather than a question for the owner.                                                                                                                                             |
| Releases-downloads badge + "check the Releases tab"                                   | **Open question — real gap, not just a stale link**                                                         | `desktop-tool-ci.yml` genuinely builds (and code-signs, see below) desktop-tool executables for this fork — but `list_releases` on `ProxyPrints/ProxyPrints.github.io` returns **zero releases**. This fork doesn't currently publish its own desktop-tool distributions anywhere. The badge/link currently sends a ProxyPrints user to chilli-axe's OWN releases, which may be the deliberate stopgap (the desktop-tool code is closer to upstream than the web stack is) or may be an oversight. Owner call, not resolved here.                                                                                                         |
| "Buy Me A Coffee" button                                                              | **(a) Stale — remove**                                                                                      | chilli-axe's personal donation link (`chilli.axe` username). Not fork-appropriate to carry over regardless of anything else; if the owner wants a donation link of their own, that's a new addition, not a merge.                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Sponsors (SignPath.io)                                                                | **Open question — genuinely NOT just stale, verify before deciding**                                        | Checked, not assumed: `desktop-tool-ci.yml` has a real, live step (`signpath/github-action-submit-signing-request@v2`) signing Windows executables with SignPath. If this fork has its own SignPath project/credentials (plausible, given the step is live in CI), the sponsorship credit is genuinely still owed and should stay — possibly with fork-specific wording. Flagging as a real judgment call the owner needs to make (confirm whether ProxyPrints has its own SignPath enrollment or is still riding on chilli-axe's), not something this audit can resolve by reading the repo alone.                                       |
| Code Signing Policy (committers/approvers/Privacy Policy link/data-transfer sentence) | **(a) Stale — remove or fully replace**                                                                     | Committers/Approvers/Members-team links point at `chilli-axe/mpc-autofill`'s and `mpcautofill`'s own GitHub org — this fork has no such team structure (a solo-maintainer repo, per everything else observed this session). The Privacy Policy link points at `mpcautofill.github.io/about`, upstream's own hosted site — this fork has its OWN Privacy Policy at `proxyprints.ca/about` (`frontend/src/pages/about.tsx`, already written, already live). If a real code-signing _policy_ (who can trigger a signed release) is worth stating for this fork, that's new content to write, not something to carry over from the wrong org. |
| Documentation → wiki link                                                             | **(a) Stale — replace, same shape**                                                                         | Points at `chilli-axe/mpc-autofill`'s own wiki. This fork has its own wiki (`ProxyPrints/ProxyPrints.github.io/wiki`), already generated from `docs/` by the existing pipeline (`docs/documentation-process.md`) — a one-line URL swap once the rest of the file is addressed, not a content question.                                                                                                                                                                                                                                                                                                                                    |

**What actually seeds the new content** (the "(c)" destination question,
answered rather than left open): `docs/wiki-home-intro.md` — already
exists, already committed, already the exact right length and register
for a README's own opening section. It correctly states the project
identity, the live site URL, the fork relationship, and what's original
vs. inherited, in one paragraph. No new doc needs to be seeded by
`readme.md`'s content, because `readme.md` currently has no unique,
accurate content that isn't already better-stated in `docs/` — the
"unique content, no docs/ home" bucket the task's audit framing
anticipated turned out empty on inspection, not skipped.

## 2. Architecture (post-review, NOT built here)

**Per the owner's framing**: `readme.md` becomes a GENERATED output of
the single Python transform (`.github/scripts/publish_wiki.py`/
`publish_site.py`, per `proposal-i-docs-as-site-source.md`'s
single-transform architecture) — a `readme` mode, alongside the existing
wiki and site modes, assembling from MARKED source regions in `docs/`.
Same marker mechanics as the extraction contract already specced there
(`<!-- DATA-EXTRACT: name -->` ... `<!-- END DATA-EXTRACT -->` — no new
vocabulary, per the instruction), applied to prose regions instead of
tables this time: a marked region in `docs/wiki-home-intro.md` (the
identity/lineage paragraph), a marked region wherever the license notice
canonically lives once that's decided (§3), and a marked region for a
short "documentation" pointer paragraph.

**Generated-and-committed, not generated-and-gitignored** — the one real
architectural difference from the wiki/site outputs, stated plainly since
it's a real divergence from the rest of Proposal I, not an oversight:
GitHub renders `readme.md` directly from the repo's default branch, so
the file has to actually exist, committed, at all times — there's no
build step or deploy pipeline standing between a commit and a reader
seeing it, unlike the wiki (published by a separate workflow) or the site
(built by `next build`). This means:

- The emit **writes `readme.md` directly** (not to a gitignored output
  dir like `frontend/generated-docs/`).
- **A CI parity check, not a build-time regenerate**, is the correctness
  gate — the same pattern this repo's docs pipeline already uses
  elsewhere (a check that fails if a generated artifact has drifted from
  what generating it fresh would produce, rather than trusting the commit
  is current). Concretely: a `docs-lint.yml`-style job that runs the
  `readme` emit into a scratch location and diffs it against the
  committed `readme.md`, failing the PR check if they differ — catching
  a hand-edit to `readme.md` that should have gone into a `docs/` source
  region instead, or a `docs/` source-region edit whose author forgot to
  regenerate.
- **Regenerating = running the emit and committing the result** — no
  different, mechanically, from editing any other committed file; the
  emit is the tool, not a runtime dependency.

**Not designed further here**: the exact CLI shape of the `readme` mode
(a flag on `publish_site.py`, or a third sibling script — same open
question §1 of `proposal-i-docs-as-site-source.md` already flagged and
resolved as "thin sibling" for the site mode; likely the same answer
applies here, not re-litigated in this HOLD doc), and the exact source
region layout beyond the three regions sketched above. Both are
implementation detail for the restructure PR, gated on this map's review.

## 3. Non-negotiables (must survive any restructure, verbatim-equivalent)

- **Upstream lineage attribution.** `docs/wiki-home-intro.md`'s own
  paragraph already states this correctly and is the proposed source
  region for it (§2) — "ProxyPrints is a fork of
  [mpc-autofill](https://github.com/chilli-axe/mpc-autofill) by
  **chilli_axe**... maintained independently." Whatever region ends up
  feeding the README's own identity section, it must carry this
  statement's substance, not just a bare "fork of X" link.
- **GPL-3 license notice.** Two things checked, not assumed: a real
  `LICENSE.md` (GPL-3.0 full text) sits at the repo root already, and
  `frontend/package.json` already declares `"license": "GPL-3.0-only"`.
  Neither is currently referenced from `readme.md` at all — the closest
  existing notice is the site's own `/about` page
  (`frontend/src/pages/about.tsx`: "licensed under the GNU General Public
  License 3... free to use, modify, and distribute"). The restructured
  README needs an explicit, plain statement of this (a short sentence +
  a link to `LICENSE.md`, matching `about.tsx`'s own phrasing register)
  — currently absent, this is a real gap being closed, not just a
  relocation of existing text.
- **Committed-artifact hygiene** (per `CLAUDE.md`'s existing rule):
  applies to whatever this audit's restructure touches — no literal
  secret values, no proprietary product names without an attached
  license, same standing rules as every other doc in this repo.

## 4. Audience fit

**README's own audience is repo visitors** — a mix of prospective
contributors (reading before opening a PR) and prospective self-hosting
operators (reading before standing up their own instance), per the
task's framing. Using PR-I-3's own proposed audience vocabulary (user /
contributor / operator / mixed — **PR-I-3 itself has not been started
yet as of this doc**; this audit anticipates that vocabulary rather than
depending on PR-I-3 already existing, and its own classification below
should fold into PR-I-3's routing table once that work happens, not
block on it):

- README's identity/lineage/license/documentation-pointer content (§1,
  §3) is **`contributor`/`operator`, mixed — never `user`**. This
  matches the task's own flag: "user-facing content the README
  currently carries likely belongs on the SITE, not the README." Checked
  against the actual content, not assumed: `readme.md` currently carries
  **zero end-user-facing content** (nothing about searching the catalog,
  building a print sheet, exporting a PDF) — the "user-facing content"
  the task anticipated finding turned out not to be there. Nothing needs
  moving to the site as a result of this specific audit; the flag is
  answered "checked, not applicable here," not skipped.
- This keeps README consistently `docs/README.md`'s own "repo visitor"
  register — closer in spirit to `docs/overview.md` (already
  `contributor`-audience, already site-targeted per
  `proposal-i-docs-as-site-source.md`'s own initial mapping) than to
  `docs/user-guide.md` (genuinely `user`-audience).

## Open items for owner review (blocking the restructure, not this audit)

1. Releases-downloads badge / "check the Releases tab": does this fork
   intend to publish its own desktop-tool releases, or deliberately
   defer to chilli-axe's for now?
2. Sponsors (SignPath.io): does ProxyPrints have its own SignPath
   enrollment (keep the credit, fork-specific wording) or is
   `desktop-tool-ci.yml`'s signing step still riding on chilli-axe's
   shared credential (different framing needed, or drop the section)?
3. Whether a real, fork-specific Code Signing Policy is worth writing at
   all, given this is presently a solo-maintainer repo with no
   committer/approver team structure to describe.
4. Exact final wording for the identity/lineage/license paragraphs —
   `docs/wiki-home-intro.md`'s existing text is proposed as the seed, not
   handed down as final.
5. `readme` mode's exact CLI shape and source-region layout (§2) — sketch
   only, not designed in full, pending this map's approval first.
