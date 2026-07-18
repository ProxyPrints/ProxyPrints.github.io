# Extraction manifest: the vote system (printing / artist / tag consensus)

Companion to CLAUDE.md's "Upstreaming to chilli-axe/mpc-autofill" section,
which describes the general worktree/cherry-pick workflow (cut a branch from
`upstream/master`, cherry-pick specific commits, diff against `upstream/master`
before pushing). This document is the commit-level plan for one specific
feature: the whole printing/artist/tag weighted-vote system, from its first
commit through the federation-readiness stub and contested-review
generalization merged 2026-07-13 (PR #7,
`ProxyPrints/ProxyPrints.github.io`).

**Ground truth used to write this**: `git log`/`git show` against `master`
(post-merge, commit `87db3dd5`) and `upstream/master` (commit `3c717d2a`,
the fork point), run directly - not reconstructed from memory/prior session
notes. Every SHA below was verified to touch the file set it's credited
with.

## 1. Ordered commit list

Oldest first - this is the order they'd need to be cherry-picked in (later
commits depend on earlier ones' schema/module additions). Full 40-char SHAs
since short SHAs risk ambiguity a year from now.

| #   | SHA                                        | Summary                                                                                           | Role                                                                                                                                                                                                                         |
| --- | ------------------------------------------ | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `4b10e5bc1be64bab61ef31999fab65d23d24cd89` | Add printing-aware card tagging: consensus, sidecar metadata, Scryfall import                     | Stage 1 foundation - `CardPrintingTag`, `printing_consensus.py`, migration 0050                                                                                                                                              |
| 2   | `b0370a6937604eba63321f57fbdf4f1d1080dc17` | Printing-tags Stage 2 (backend): submission API + consensus persistence                           | migration 0051, `2/submitPrintingTag/` etc.                                                                                                                                                                                  |
| 3   | `14e9657826fed0772a4ac98612efea69ee347196` | Printing-tags Stage 2 (frontend): tagging UI + review queue                                       | new `printingQueue.tsx`, `PrintingTagPicker.tsx`, `PrintingTagQueue.tsx`                                                                                                                                                     |
| 4   | `0591392461a096158348343b077962494c9e110a` | Fix printing-candidate matching, rank by confidence, add hover preview                            | new `printing_candidates.py` - candidate search was broken without this                                                                                                                                                      |
| 5   | `a78f14d88ef3ea8c498509fb2b7c5fbeb8f562f8` | Rebrand printing-tag feature as "Who's That Planeswalker?"                                        | **fork flavor, see §3**                                                                                                                                                                                                      |
| 6   | `f4eaea145120f8d0d41a31fe7fe2e2cfa0cd2389` | Stage 3: real Tag taxonomy with fuzzy matching, set-code expansion hints                          | dependency for tag voting to have real `Tag` rows - see §4                                                                                                                                                                   |
| 7   | `118a1647453a89996bf2d491b9da03a1e6a2ed0e` | Redesign Who's That Planeswalker? into a single-card queue, contested-first                       | extracts `get_contested_card_ids`, orders the queue                                                                                                                                                                          |
| 8   | `73fe5bf0ede2f9cf1a4d25aca833d6397f1e41fa` | Fix mypy: add missing type parameter to get_contested_card_ids' QuerySet                          | trivial, 1 line                                                                                                                                                                                                              |
| 9   | `ca740e017b1167f2b2a34b95108b3d666eb8b689` | Fix mypy QuerySet generic + make "no match" a card-shaped first option                            | **entangled, see §2**                                                                                                                                                                                                        |
| 10  | `37ef2bcc179911b794a8666550bd0029235df53c` | Fix mypy for real: materialize get_contested_card_ids to a plain list                             | trivial, mypy-only                                                                                                                                                                                                           |
| 11  | `dbc8f237d99a48f8c9f77873e9552ac4881f64f6` | Replace striped background with a real starburst on the Planeswalker page                         | **fork-only styling, do not port, see §2/§3**                                                                                                                                                                                |
| 12  | `47022c02f066c0bb4dd2859dd06aef23884fea82` | "Who's That Pokemon?" styling for the Planeswalker queue                                          | **fork-only styling, do not port**                                                                                                                                                                                           |
| 13  | `c81a5f5a561b82959c7fb3dee780c56eb486a21e` | Replace the Planeswalker starburst with a real jagged explosion burst                             | **fork-only styling, do not port**                                                                                                                                                                                           |
| 14  | `836f98fb6c700d28d0824fa6ba9c28a71f9a085f` | Widen the starburst belly, full-bleed it, make it stick while scrolling, zoom candidates on hover | **fork-only styling, do not port**                                                                                                                                                                                           |
| 15  | `ed95609c100019fd84080d602101bd5e13babc8b` | Add artist + tag weighted voting following a printing "no match"                                  | **THE foundation commit**: introduces `AbstractWeightedVote`, refactors `CardPrintingTag` to inherit it, adds `CardArtistVote`/`CardTagVote`, `vote_consensus.py`, `artist_consensus.py`, `tag_consensus.py`, migration 0053 |
| 16  | `b1ab5b39b91732f5bbd9df4c0cf7994a38e3ab25` | Merge remote-tracking branch 'origin/semantic-card-attributes' into semantic-card-attributes      | **no-op, see §2** - diff against first parent is empty                                                                                                                                                                       |
| 17  | `202e486805456f5ec8b6b360d3a3657b82cbdfd1` | Add federation-readiness schema stub to the vote system                                           | Part 1 of this sprint: `VoteSource.FEDERATED`, `peer` field, `VOTE_FEDERATED_WEIGHT`, `is_ai`→`is_human_backed` rename, migration 0054, `docs/federation-v1.md`                                                              |
| 18  | `a37214d49645720b94fd0758c23d1925ffcec2a8` | Generalize contested-review to artist/tag votes, add unified vote queue                           | Part 2 backend: `contested_queryset()`, `Card.tag_vote_statuses`, `2/voteQueue/`, migration 0055                                                                                                                             |
| 19  | `37b99b73476e23dceb1e83277c68124dc5fb1927` | Add vote queue kind switcher, tag question, and the "wrong?" affordance                           | Part 2 frontend: tab switcher, `GenericVoteQueue.tsx`, `QueueTagQuestion.tsx`, `confidentlyKnownArtistName`                                                                                                                  |
| 20  | `2ca61601182e36743341286aab5ebc635aac7952` | Merge master into vote-review-and-federation-stub                                                 | **skip entirely for extraction, see §2** - reconciliation merge, no net-new vote logic                                                                                                                                       |
| 21  | `db7967322f99fb6c0734642625a4b34b488bf940` | Prettier formatting fix in federation-v1.md                                                       | trivial, doc formatting only                                                                                                                                                                                                 |

Not included: commits 11-14 above are listed because they touch
`PrintingTagQueue.tsx`/`printingQueue.tsx` and therefore affect what a
cherry-pick of later commits in that file will look like, but they are pure
fork theming with zero vote-logic content - see §3, do not cherry-pick them
onto an upstream branch under any circumstances. The later starburst
follow-ups that landed via the `2ca61601` merge (`b87d5401`, `d135d221`,
`8cdd8578`, `ed902a9e`, `c47b03a7`, `a6d727af` - "hover burst" refinements)
are the same category and are likewise excluded from the numbered list
above; they exist only because `master`'s parallel starburst-geometry work
touches the same file, not because they contain vote logic.

## 2. Clean cherry-pick vs. entangled, per commit

**Clean (cherry-pick as-is, in order, onto a fresh `upstream/master` branch)**:

- #1 `4b10e5bc` - new files only (`printing_consensus.py`,
  `printing_metadata_import.py`), additive migration. Verified: this is the
  actual Stage 1 foundation, self-contained.
- #2 `b0370a69` - new endpoints + migration, no shared-file entanglement
  found.
- #4 `05913924` - touches `views.py` and `PrintingTagPicker.tsx` only (not
  `PrintingTagQueue.tsx`, which is where the starburst entanglement lives) -
  confirmed clean by inspection, `PrintingTagPicker.tsx` has never had any
  starburst styling added to it.
- #6 `f4eaea14` - self-contained new files (`tag_alias_matching`,
  `seed_default_tags`), additive migration.
- #7 `118a1647` - touches `admin.py`, `printing_consensus.py`, `views.py`,
  `PrintingTagQueue.tsx`, `printingQueue.tsx`. The backend half is clean.
  The frontend half is **not** clean in isolation - see the general note on
  `PrintingTagQueue.tsx`/`printingQueue.tsx` below.
- #8, #10 (`73fe5bf0`, `37ef2bcc`) - single-line/single-hunk mypy fixes to
  `printing_consensus.py` only. Clean, but arguably not worth cherry-picking
  as separate commits upstream at all - fold their net effect
  (`get_contested_card_ids` returning `list[int]`) into whatever commit
  introduces that function for upstream instead of reproducing this fork's
  three-attempt mypy debugging history.
- #15 `ed95609c` - this is a large commit (41 files) but every hunk checked
  (`PrintingTagQueue.tsx`, `CardDetailedViewModal.tsx`,
  `PrintingTagPicker.tsx`) is logic-only - no starburst content. **However**:
  a direct `git cherry-pick` of this commit onto upstream will likely fail
  to apply cleanly on `PrintingTagQueue.tsx`, not because this commit's
  content is bad, but because by the time this commit was made, that file
  already contained several starburst commits' worth of context this
  commit's diff is patching around. Use `git cherry-pick -m` won't help
  here (no merge parents) - the fix is `git show ed95609c -- <file> | git apply --3way` against upstream's plain file, or just hand-apply the
  hunks (they're small and were verified above to be self-contained: a
  `votedThisCard` state variable, an `AttributeVotingPanel` import, and one
  conditional render block).
- #17 `202e4868`, #18 `a37214d4` - backend-only in their vote-system-critical
  parts (frontend touched is minimal/none - verify with `git show --stat`
  before assuming, but these were built as backend-first commits in this
  sprint). Migrations and Python modules only, should apply cleanly.
- #19 `37b99b73` - see the general `printingQueue.tsx` note below; the
  `ArtistVotePicker.tsx`/`AttributeVotingPanel.tsx`/`GenericVoteQueue.tsx`/
  `QueueTagQuestion.tsx` portions of this commit are clean (new files, no
  starburst).
- #21 `db796732` - trivial, skip or fold into whichever commit brings
  `federation-v1.md` upstream.

**Entangled - name the files, the entanglement, and the fix**:

- **#9 `ca740e01`** - files: `printing_consensus.py` (1-line mypy fix,
  unrelated), `PrintingTagPicker.tsx` + `PrintingTagQueue.tsx` (the "no
  match" tile redesign - genuine vote-system UI, not fork-flavor). The
  entanglement is a _bundling_ problem, not a content problem: one commit
  mixes a trivial type-fix with a real UI change. Recommended extraction:
  cherry-pick the UI hunks by hand (or split the commit into two before
  cherry-picking: `git rebase -i`, drop the mypy line into #8/#10's
  successor), don't reproduce the mypy line-item history verbatim upstream.
- **#16 `b1ab5b39`** - a merge commit whose diff against its first parent
  (`ed95609c`) is empty (verified: `git diff ed95609c b1ab5b39 --stat`
  produces no output). This merge only resolved a conflict in
  `PrintingTagQueue.spec.ts` between two pushes of the same branch from this
  fork's own workflow - it carries zero content relevant to upstream.
  **Skip entirely.**
- **#20 `2ca61601`** - the merge-master-into-branch reconciliation commit
  from this same sprint. Its net content (relative to `37b99b73`) is: (a)
  pulling in `master`'s parallel starburst/decklist/Keyrune/expansion_hint
  work (none of which is vote-system content), and (b) re-applying the
  Printings/Artists/Tags tab switcher on top of the newer, more-elaborate
  starburst-styled `printingQueue.tsx` that had landed on `master` in the
  meantime. There is no vote-logic content in this commit that isn't
  already present in `37b99b73`. **Skip entirely** - extract the tab
  switcher from `37b99b73`'s version of `printingQueue.tsx` instead, and
  hand-apply it to upstream's plain (non-starburst) page.

**Systemic issue, not a single commit**: `frontend/src/features/printingTags/ PrintingTagQueue.tsx` and `frontend/src/pages/printingQueue.tsx` are the
single biggest extraction cost in this whole feature. Across commits #7,
#9, #11-#14, #15, #19, and the merge #20, these two files interleave real
vote-queue logic (fetch/pagination/submit/candidate-ranking) with five
separate rounds of fork-only visual theming (striped → conic-gradient →
jagged-SVG-explosion starburst, sticky positioning, hover-zoom, a
"Who's That Pokemon?" reveal animation with its own keyframes and state).
**Do not attempt to cherry-pick this file's history commit-by-commit.**
Instead:

1. Start from upstream's current (nonexistent - `printingQueue.tsx` is a
   new page, see §4) or this fork's _pre-starburst_ state of these files
   (`14e96578`'s versions, before `dbc8f237` first touched them) as the
   structural template.
2. Layer in the logic-only diffs from #7, #9 (UI half only), #15, #18, #19
   by hand, verifying against the current (post-`2ca61601`) file content
   in this repo for the final intended behavior.
3. Drop every one of: `StarburstBackground`, `StarburstContent`,
   `BurstSvg`, `HoverBurst`, `useStarburstFrame`, `RevealWrapper`,
   `RevealOverlay`, `revealAnimation`, `useStickyTop`, `CardPanel`'s sticky
   positioning, and the import of `starburstShape.ts`. None of this is
   vote-system logic; all of it is fork-specific theming.
4. The result should look much closer to `14e96578`'s original plain
   version (heading + paragraph + queue component, no special background)
   plus the accumulated real logic changes, than to what's currently on
   this fork's `master`.

## 3. Fork-specific content that must not reach upstream

Checked every commit in §1 for: literal `ProxyPrints`/`proxyprints.ca`/
`PringlePrints` strings, and anything on CLAUDE.md's never-commit list
(secrets, `drives.csv`, `docker/.env` contents, Cloudflare/image-cdn
credentials). **None found** in any vote-system commit - this feature was
built without touching branding or secrets files. Specifically checked
`MPCAutofill/MPCAutofill/settings.py`'s diffs in commits #1, #2, #6, #17 (the ones that
add settings) against the file's existing `proxyprints.ca` CORS-origin
lines (`settings.py:128-129`, added independently, unrelated to this
feature) - confirmed no proximity/entanglement, these commits only append
new setting blocks elsewhere in the file.

Two things worth flagging even though they aren't hard violations:

- **#5 `a78f14d8`** ("Who's That Planeswalker?" rebrand) and the
  "Who's That Pokemon?" theming (#12, and the un-numbered hover-burst
  follow-ups) are _tonal_ fork flavor - playful gamification copy this fork
  chose, not anything ProxyPrints-branded by name, but also not something
  to assume upstream wants. Treat as optional: offer the plain
  "Tag Printings" / "Which printing is this?" copy (`14e96578`'s original
  wording, visible in `a78f14d8`'s diff as the "before" side) as the default
  upstream PR content, and mention the gamified version only if asked.
- The `docs/federation-v1.md` content itself (commit #17) was checked and
  contains no fork-specific references - it's written as a generic
  cross-instance spec. Safe to carry upstream as-is if the federation stub
  is proposed at all (see §4 on whether that's worth doing).

## 4. Semantic dependencies - does vote code assume fork-only features exist?

- **Printing-candidate DOM data attributes (`getPrintingCandidateDataAttributes`,
  `frontend/src/common/cardDom.ts`)**: introduced in commit
  `e2811ed5` (2026-07-11), which is **not** in the ordered list above because
  it's a separate, already-flagged-pending-upstream feature (see this
  repo's memory: "Pending upstream: DOM attrs"). But `PrintingTagPicker.tsx`
  and `PrintingTagQueue.tsx` call this function as of `e2811ed5` onward, and
  that call is present in the _current_ (post-merge) state of both files.
  **Real dependency**: the vote-system extraction branch either needs
  `e2811ed5` (and its prerequisite `91681e77`, `98561698`) cherry-picked
  first, or the `{...getPrintingCandidateDataAttributes(...)}` spread and
  its import need to be manually stripped from the extracted files. Verify
  which approach before cutting the branch - don't assume the DOM-attrs PR
  will have landed upstream by the time this one is cut.
- **Real `Tag` taxonomy (Stage 3, commit `f4eaea14`)**: `CardTagVote.tag` FKs
  to the pre-existing `Tag` model (which upstream already has - `Tag` dates
  back to migration `0034`, long before the fork). But without Stage 3's
  `seed_default_tags` command and real `Tag` rows, tag voting has nothing
  meaningful to vote on except the synthetic NSFW pseudo-tag. This isn't a
  hard code dependency (tag voting _works_ against any `Tag` rows that
  exist), but it's a **functional** dependency: upstream would need either
  Stage 3's taxonomy commit too, or their own equivalent seed data, for tag
  voting to be useful out of the box. Flag this explicitly in the upstream
  PR description rather than silently shipping a feature that appears to
  do nothing.
- **`CanonicalCard`/`CanonicalArtist`/`inferred_canonical_card`/
  `canonical_artist`**: verified upstream already has these (migrations
  0044-0049 are present in `upstream/master` as of this writing - they
  predate the fork point `3c717d2a`). **No gap here** - the vote system's
  dependency on canonical-card infrastructure is already satisfied
  upstream, nothing to extract or re-justify.
- **Keyrune icon flattening, decklist-import scraping, image-cdn URLs**:
  checked - no vote-system file (backend or frontend) imports from
  `common/keyrune.ts`, `common/generated/keyruneCodepoints.json`, the
  decklist `format_decklist_line()` path, or references
  `NEXT_PUBLIC_IMAGE_WORKER_URL`/`NEXT_PUBLIC_IMAGE_BUCKET_URL` directly.
  These are unrelated parallel features that happen to share `master`'s
  commit history; no semantic dependency found.
- **`getOrCreateAnonymousId` (`frontend/src/common/cookies.ts`)**: added
  _within_ commit `14e96578` itself (Stage 2 frontend), not a pre-existing
  dependency - no extraction concern, it travels with that commit.

## 5. Upstream has moved - re-check before cutting the branch

As of this writing (2026-07-13), `upstream/master` is still exactly at the
fork point (`3c717d2a`, merge-base with our `master` shows **0 commits**
upstream is ahead) - unchanged since a 2026-07-11 check. (That check is no
longer recorded in CLAUDE.md — CLAUDE.md is orientation-only and this kind
of point-in-time fact doesn't belong there; re-verify live rather than
chasing the old pointer.) This can change at any time between now and
whenever this manifest is actually acted on. **Before cutting the
extraction branch**:

```
git fetch upstream master
git merge-base upstream/master origin/master   # should still be 3c717d2a
git log 3c717d2a..upstream/master --oneline    # should be empty
```

If upstream has moved, re-verify every "clean cherry-pick" claim in §2
against the new tip specifically for the files this feature touches
(`models.py`, `views.py`, `urls.py`, `admin.py`,
`CardDetailedViewModal.tsx`, `Navbar.tsx` - `Navbar.tsx` in particular is
already known to have real fork/upstream drift unrelated to voting,
around the support-developer-modal/Patreon integration this fork removed,
so the one-line nav-link addition for the vote-review queue page will need
manual reapplication there regardless of how much else has moved).

Also re-confirm memory's standing note that upstreaming is currently
deprioritized (chilli-axe may drop Node.js) before investing further time
past this manifest.
