# Printing tags vs. illustration tags: what grain does "Universes Beyond" live at?

**As of 2026-07-29.** A decision document, not a ruling. Written because
the owner is reconsidering whether `PrintingTagVote` should exist at all:

> "it may have been a mistake to invent printing tags as scryfall tags
> are already that, just need illus tags to extend into human voting to
> be able to absorb the entire external IP logic I think"

and, on the original intent behind the model:

> "the thought process was to have art:external-ip scryfall id cards be
> tagged as UB (in interface) automatically (by just extending scryfall
> api), and then allowing users to tag alternate art cards that are UB so
> they can be filtered together in the interface"

"UB" = Universes Beyond, Wizards' branding for Magic cards using external
intellectual property (Lord of the Rings, Warhammer 40,000, Doctor Who,
Fallout, Final Fantasy, Marvel, Avatar, …). The user-facing goal is a
single filter that gathers all of them.

Every number below was measured read-only against the production database
(`docker exec mpcautofill_django python manage.py shell`) or by executing
the real consensus function. No pipeline code was changed. Queries are
quoted alongside their results in §9 so each figure can be re-derived.

---

**Owner rulings of 2026-07-29 are folded in and marked as such.** Three
arrived while this was being written and settle questions the
investigation had open; where a ruling and a measurement disagree, both
are recorded rather than one being quietly dropped (§8.6).

**Update, 2026-07-30 — open question 1 is CLOSED and EXECUTED.**
`PrintingTagVote` has been retired: PR #615 ("Retire `PrintingTagVote`:
the vote channel that had no resolver, no reader and no rows") is merged,
and the model, its consensus module, and its external-IP import command
no longer exist on `master`. Read §7.1 and open question 1 below as the
record of the reasoning that produced that decision, not as a live
proposal. The analysis is deliberately left as written — the code paths
and model names it names describe the tree as it stood on 2026-07-29,
before the retirement landed.

---

## 0. The principle this all turns on

Stated first because it decides everything below, and because it is the
opposite of a defect report.

**A machine-only vote channel can never resolve, at any volume. That is
the design, not a bug in it.** Owner ruling, 2026-07-29: _"that is the
entire theory in one sentence, we designed things like this on purpose."_

The consequence, stated as the constraint it is:

> **Any tag category that is expected to resolve from machine evidence
> alone is mis-specified by construction.** The correct design either
> routes it through human confirmation, or does not model it as a vote at
> all.

Votes exist for claims that can be _disputed_. A structured fact imported
from Scryfall cannot be disputed by a voter — there is nothing to
adjudicate — so modelling it as a vote buys nothing and costs a channel
that can never fire. This single sentence explains the whole of
`PrintingTagVote`'s history: it was built to carry an indisputable
imported fact through a mechanism designed for disputable claims.

The verification is in §2; the design's own weight math is untouched by
any recommendation here.

---

## 0.1 The smallest thing that delivers the UB filter

Answering the owner's framing directly — _"i am willing to not need the
printing tag. i am happy to reduce things to the minimum that gives us
our expected results. we don't need to reinvent the wheel everyday."_
(ruling, 2026-07-29).

**(a) Does the UB filter need a vote mechanism at all? For official
printings: no.**

`CanonicalPrintingMetadata.promo_types` already carries the Scryfall token
`universesbeyond` on 10,407 of 113,224 printings, at 100% per-set recall
(§4.2). It is deterministic, already ingested, and not disputable. It is a
**derived attribute**, and the minimum mechanism is a read — optionally
denormalised onto `Card.tags` so Elasticsearch can filter on it. **3,450
catalogue images already resolve to a UB printing today** through the
existing ingestion-time `Card.canonical_card` link, with no vote of any
kind. No new model, no new table, no threshold, no gate.

**(b) Where user-tagging is genuinely needed — card grain suffices; do not
build illustration grain for it.**

The owner's second case is users marking alternate-art cards as UB. Those
are custom/proxy images with no Scryfall printing and no Scryfall
`illustration_id` at all (§5.3) — so neither a printing-keyed nor an
illustration-keyed Scryfall-derived tag can reach them by construction.
The claim being made is about _this uploaded image_, and it is genuinely
disputable, so it is genuinely a vote.

**That channel already exists and works end to end**: `CardTagVote` →
`tag_consensus.resolve_and_persist_tag_votes` → `Card.tags` →
Elasticsearch. The no-match reason strip already routes to it. It shares a
`Tag.name` with the machine path by deliberate design
(`reason_tags.py`'s own stated rationale), so `tag:external-ip` is **one
predicate over both populations** — exactly the stated goal.

**Illustration grain would be correct but is not needed for this.** §5.1
searched for its counterexample and found none, so the grain instinct is
right; but a custom image's artwork has no illustration id to key on, so
the grain that is theoretically better cannot serve the case that
actually needs a human. Building it would be reinventing a wheel that
`CardTagVote` already turns.

**The minimum is therefore: one derived read for official printings, plus
the `CardTagVote` channel that already exists for everything else.** The
only thing standing between that and a working filter is that the
`external-ip` `Tag` **does not exist in production** (§3.4) — one command.

**(c) If `PrintingTagVote` goes, what is the migration? There isn't one.**

**0 rows. 0 human votes.** The census is in §3.1 and it is the reason this
is cheap: human votes are the one thing in this system that cannot be
re-derived, and there are none here. Nothing to migrate, nothing to
rescue, nothing that reads it. §8 is the full removal sketch; §8.3
confirms it triggers no PROTECTED CORE review.

---

## 0.2 The short version

Four findings, in descending order of consequence — then two more that
arrived late and are recorded below them.

1. **The catalogue already knows which printings are Universes Beyond,
   and no vote was involved.** `CanonicalPrintingMetadata.promo_types`
   already stores the Scryfall token `universesbeyond` on **10,407 of
   113,224 printings (9.19%)**, with **100% per-set recall on every
   dedicated UB set in the catalogue** and correct partial behaviour on
   mixed sets. This column has been populated all along. Nothing reads it
   for this purpose. (It answers the _product-line_ question completely;
   the _artwork-origin_ question is broader — §4.5.)

2. **`PrintingTagVote` is empty and unreadable.** **0 rows** in
   production, of any source, human or machine. It has **no consensus
   resolver anywhere in the codebase** — the module its own docstrings
   forward-reference, `printing_tag_consensus.py`, has never existed on
   any branch in the repo's history. Nothing reads this table except the
   Django admin. There are therefore **no human votes to migrate** and
   nothing that would break if it were removed.

3. **The original auto-tagging design was unreachable as built, and not
   for the arithmetic reason.** Verified by execution:
   `resolve_weighted_consensus` applies a hard `has_human_backed` gate
   _independent of the weight math_, so a machine-only vote set returns
   `None` at n=1, 2, 4, 10, and 1,000 (1,000 votes = 500.0 weight against
   a threshold of 2.0). Automatic Scryfall-derived tagging could never
   have produced a displayed tag on its own at **any** volume, at **any**
   threshold, at **any** grain. This is not a printing-tag defect — the
   same gate governs card tags, artist votes, and illustration votes. It
   is the invariant the whole project is built on, working correctly.

4. **The counterexample search for illustration grain came back empty.**
   Of **50,828** distinct stored `illustration_id` values, **0** appear on
   both a UB and a non-UB printing — despite **25,381** of them being
   reprinted across more than one printing and **20,542** spanning more
   than one set. UB-ness travels with the artwork, losslessly, in our own
   data. The owner's instinct about grain is **correct**.

So: the owner is right that Scryfall already supplies this, right that
UB-ness is an artwork property, and right that `PrintingTagVote` is not
earning its place. They are wrong about one thing — "just need illus tags
to extend into human voting" describes building something that does not
exist, not extending something that does (§6) — and the official-printing
half of the goal is answerable without any vote at all (§7).

A fifth finding, established late and worth its own line because it
changes a recommendation: **`art:external-ip` is materially broader than
`promo_types`.** The live Scryfall Tagger subtree closes over 8,332 tagged
illustrations, which intersect **~13,166** of our printings against
`promo_types`' 10,407 — a delta of roughly **2,759 printings** that the
product-line marker does not flag. That delta is not yet characterised
(§4.5), and characterising it is the cheapest next step available.

**Why the import never ran: established.** Not abandoned, not blocked,
not superseded — **forgotten**. It was an owner-ratified, explicitly
sequenced run-stage step on 2026-07-28 (step 4d of that day's
merge/deploy sequence, gated behind PRs #509→#511→#512). The session
pivoted to a Signal-daemon incident, the handoff that carried the
sequence was superseded for daemon state, and step 4d was never re-lifted
into any later handoff. Nothing could have reported the omission because
the calculator roster tether used a non-recursive glob and never scanned
`management/commands/`. **It would run successfully today** — every gate
was checked and passes (§8.6).

---

## 1. The disambiguation

Three vote models have confusingly adjacent names. This section is worth
publishing regardless of what is decided about any of them.

| model             | keyed by                                  | the claim a row makes                                                            | who writes                                                                                                   | who reads                                                                                                                         |
| ----------------- | ----------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `CardPrintingTag` | (`Card`, `CanonicalCard`, `anonymous_id`) | "this catalogue **image** depicts this Scryfall **printing**" (or `is_no_match`) | question feed, deckbuilder confirm, Stage D/E calculators, deductive backfill                                | `printing_consensus.resolve_printing` → `Card.printing_tag_status`, `Card.inferred_canonical_card`, Elasticsearch                 |
| `CardTagVote`     | (`Card`, `Tag`, `anonymous_id`)           | "this descriptor **tag** applies to this catalogue **image**"                    | no-match reason strip, report button, filename ingestion, OCR                                                | `tag_consensus.resolve_tag` / `resolve_and_persist_tag_votes` → `Card.tags` (**Elasticsearch-indexed**), `Card.tag_vote_statuses` |
| `PrintingTagVote` | (`CanonicalCard`, `Tag`, `anonymous_id`)  | "this descriptor **tag** applies to this Scryfall **printing**"                  | `POST 2/submitPrintingTagVote/` (no frontend caller exists); `manage.py import_external_ip_tags` (never run) | **nothing**                                                                                                                       |

`CardPrintingTag` answers _which printing is this?_ `PrintingTagVote`
answers _what is this printing like?_ They share four characters of prefix
and nothing else.

### 1.1 Which model do the named symbols actually govern?

Traced to call sites, not inferred from names. **None of the three govern
`PrintingTagVote`.**

- **`PRINTING_TAG_MIN_VOTES`** (`settings.py:65`, default `2`) is not a
  printing-tag setting at all. It is _the_ consensus threshold, passed as
  `min_weight` by every consensus path in the app:
  `printing_consensus.py:519` (`CardPrintingTag`), `tag_consensus.py:71`
  and `:338` (`CardTagVote`), `artist_consensus.py:54` (`CardArtistVote`),
  `question_feed.py:311`, `consensus_recompute.py:222`. PR #573 would add
  `ILLUSTRATION_MIN_VOTES` defaulting to it. It is **never** read on any
  `PrintingTagVote` path, because no such path exists. The name is a
  historical artefact of the printing-tag feature having been first.

- **`PRINTING_TAG_IMPLICIT_CAP`** (`settings.py:87`, default `1.0`) is read
  in exactly one place: `vote_consensus.py:502`, inside
  `resolve_weighted_consensus`. It therefore applies to every caller of
  that function and to nothing else. `PrintingTagVote` is not a caller.

- **`_split_new_printing_tag_votes`** (`local_calculate_verdicts.py:1156`)
  has the signature `(votes_batch: list[CardPrintingTag]) -> tuple[list[CardPrintingTag], int]`.
  It is a concurrent-dispatch collision guard for **`CardPrintingTag`**
  writes. It never touches `PrintingTagVote`. Its sibling
  `_purge_and_write_printing_tag_votes` (`:1258`) likewise takes
  `list[CardPrintingTag]`.

**Evidence.** `grep -rn "PrintingTagVote" --include=*.py MPCAutofill/ | grep -v /tests/` returns 30 lines across 8 files: `models.py` (the class),
`admin.py` (registration), `urls.py` + `views.py` (the submit endpoint),
`migrations/0088_printingtagvote.py`, `purge_machine_votes.py` (deleter),
`vote_write.py` (a docstring mention), and
`management/commands/import_external_ip_tags.py` (the writer). No
consensus module, no serialiser, no search path, no frontend.

---

## 2. Was the original auto-tagging design ever reachable?

**No — and the reason is stronger than the one that was suspected.**

The brief anticipated an arithmetic answer: machine votes weigh 0.5, the
threshold is 2.0, so four machine votes would be needed and only one
plausible machine caster exists per tag. That is true as far as it goes
(`PRINTING_TAG_MACHINE_WEIGHT = 0.5`; `import_external_ip_tags` is the
only machine writer, `anonymous_id="scryfall-tagger-v1"`, so exactly **one**
distinct machine identity could ever cast a given (printing, tag) vote).
But it understates the mechanism.

`resolve_weighted_consensus` (`vote_consensus.py:~540`) ends:

```python
if winner_weight >= min_weight and share >= min_share and winner["has_human_backed"]:
```

`has_human_backed` is a hard boolean gate, evaluated _independently_ of
the weight sum. `is_human_backed_source(VoteSource.DEDUCTION)` is `False`.
So no quantity of machine weight satisfies it.

**Verified by execution** against production code (pure function, no DB
writes):

```
machine-only votes n=1    -> None
machine-only votes n=2    -> None
machine-only votes n=4    -> None
machine-only votes n=10   -> None
machine-only votes n=1000 -> None      # 500.0 weight vs min_weight 2.0
1 human + 1 machine       -> None      # 1.5 < 2.0
1 human + 2 machine       -> 1         # 2.0 >= 2.0, human-backed -> resolves
```

The original intent — "have `art:external-ip` scryfall id cards be tagged
as UB **automatically**" — is therefore incompatible with the ratified
consensus design, **at every grain**. Re-grouping the same machine votes
onto illustrations instead of printings does not change this by one bit.
Any design that wants automatic Scryfall-derived tagging must route
around the vote system, not through it.

This is not a bug to fix. It is the invariant that makes the catalogue
trustworthy (the deductive backfill's own production run verified it at
scale: 0 of 28,112 machine votes ever resolved a card alone). The correct
conclusion is that **structured Scryfall facts are not votes and should
never have been modelled as votes.**

### 2.1 And in any case, nothing would have read the result

Even had the gate been cleared, `PrintingTagVote` has **no resolver**. The
submit endpoint says so in its own docstring
(`views.py:post_submit_printing_tag_vote`):

> "Per-printing consensus resolution is intentionally not triggered here.
> … The resolution function will be added when a pipeline consumer needs
> it (card serialisation / question feed expansion — see #437). Until
> then, votes land correctly but no resolution is computed or surfaced."

`import_external_ip_tags.py` (lines 29, 546) forward-references a module
`printing_tag_consensus.py` for that job. **That module does not exist and
never has** — not on disk, not in `git log --all` across 324 refs, not on
any of the 14 open PRs, and GitHub code search returns `total_count: 0`.
It is a phantom reference in two docstrings.

So the design was unreachable twice over: the votes could not resolve, and
had they resolved, nothing would have displayed the result.

---

## 3. The live data

Production, read-only, 2026-07-29.

### 3.1 `PrintingTagVote`

| measure                                 | value                                    |
| --------------------------------------- | ---------------------------------------- |
| total rows                              | **0**                                    |
| by `source`                             | _(empty)_                                |
| by `anonymous_id`                       | _(empty)_                                |
| by tag                                  | _(empty)_                                |
| **human votes**                         | **0**                                    |
| rows ever resolved into a displayed tag | **0** — structurally, no resolver exists |

**The single most important number in this document is that 0.** Human
votes are the one thing in this system that cannot be re-derived, which is
why the vote backup covers humans only. There are none here. Any
deprecation of `PrintingTagVote` therefore has **nothing to migrate**.

Corroborating: `PilotRunLedger` has **zero** entries for
`command="import_external_ip_tags"`. The command creates its ledger row
_before_ branching on dry-run, so even a dry run would have left a trace.
It has never been invoked in production.

### 3.2 The other vote families, for scale

| table                  | rows    | human (`source=user`) rows                         |
| ---------------------- | ------- | -------------------------------------------------- |
| `CardPrintingTag`      | 167,229 | not separately counted; see below                  |
| `CardTagVote`          | 223,999 | **106** (`ocr`: 223,893)                           |
| `CardIllustrationVote` | **3**   | **0** (all `deduction`, `stage-d-illustration-v1`) |
| `PrintingTagVote`      | **0**   | **0**                                              |

`CardTagVote`'s 106 human votes break down as: `custom-art` 80,
`Borderless` 5, `Modern Border` 4, `Black Border` 4, `Upscaled` 4,
`altered-frame` 4, `ai-art` 3, `AI-Generated` 1, `Full Art` 1. Note the
absence of `external-ip` — see §3.4.

### 3.3 Catalogue resolution state — the number that reframes everything

| `Card.printing_tag_status` | count   |
| -------------------------- | ------- |
| `unresolved`               | 230,744 |
| `no_match`                 | 22      |
| `resolved`                 | **4**   |

**4 of 230,770 catalogue images have a vote-resolved printing.** A tag
stored at printing grain and routed to images _via consensus_ therefore
reaches 4 cards. This is the practical ceiling on anything built on
`PrintingTagVote` today, independent of every other argument in this
document.

There is, however, a second and much larger Card → printing bridge that
does not involve votes at all: `Card.canonical_card`, the confirmed
ingestion-time indexing match, is populated on **19,475** cards (8.4% of
the catalogue). That link is what makes §4's recommendation viable now
rather than eventually.

### 3.4 The `external-ip` tag does not exist in production

`Tag.objects.count()` is **30**, and `external-ip` is not among them. Six
of the seven no-match reason tags are seeded (`custom-art`,
`altered-frame`, `upscaled`, `no-collector-line`, `non-english`,
`ai-art`); `external-ip` was added to `reason_tags.NO_MATCH_REASON_TAGS`
on 2026-07-28 and `manage.py seed_no_match_reason_tags` has not been
re-run since.

Two live consequences, both currently silent:

- `POST 2/submitPrintingTagVote/` does `Tag.objects.get(name=req.tagName)`
  and raises `BadRequestException` on miss. **No human can cast an
  external-ip printing tag vote today** even if a UI existed. (No frontend
  caller of `submitPrintingTagVote` exists anywhere in `frontend/src/`.)
- The human no-match-reason strip cannot record `external-ip` either, for
  the same reason — so the _card-grain_ human channel, which does work end
  to end, is also blocked on this one-line seeding run.

`import_external_ip_tags` itself is unaffected: it calls
`Tag.objects.get_or_create(name=EXTERNAL_IP_TAG_NAME)`.

---

## 4. What Scryfall already gives us, in our own stored data

The owner's claim — "scryfall tags are already that" — was tested against
what we store, not against the web.

### 4.1 Field inventory

Verified by live column introspection
(`connection.introspection.get_table_description`) cross-checked against
`models.py`; they agree exactly.

| Scryfall field            | status                           | where                                                 |
| ------------------------- | -------------------------------- | ----------------------------------------------------- |
| `promo_types`             | **stored**                       | `CanonicalPrintingMetadata.promo_types` (JSONField)   |
| `frame_effects`           | stored                           | `CanonicalPrintingMetadata.frame_effects`             |
| `frame`                   | stored                           | `CanonicalPrintingMetadata.frame`                     |
| `border_color`            | stored                           | `CanonicalPrintingMetadata.border_color`              |
| `illustration_id`         | stored                           | `CanonicalPrintingMetadata.illustration_id` (indexed) |
| per-face illustration ids | column exists, **empty in prod** | `CanonicalPrintingMetadata.face_illustrations`        |
| `oracle_id`               | stored, renamed                  | `CanonicalCard.canonical_id`                          |
| `set_type`                | **never parsed**                 | absent from `mtg.ExpansionRow`                        |
| `security_stamp`          | **never parsed**                 | absent from `PrintingMetadataRow`                     |
| `games`                   | never parsed                     | —                                                     |
| `artist_ids`              | never parsed                     | artists resolved by display name only                 |

`set_type` and `security_stamp` are both named aspirationally in
docstrings (`views.py:2947`, `reason_tags.py:81`) as the intended
authoritative UB signal. **Neither is stored, so neither can be measured**
— stated as "not established" rather than inferred.

### 4.2 Coverage of each stored candidate

**`promo_types` contains `universesbeyond`: 10,407 of 113,224 printings
(9.19%).** It is the single most common token in the column, ahead of
`boosterfun` (9,487). 68 distinct expansions carry it.

Validated against a hand-listed set of known UB set codes:

| set                                                                                                     | total printings | flagged | gap                                     |
| ------------------------------------------------------------------------------------------------------- | --------------- | ------- | --------------------------------------- |
| `who` Doctor Who                                                                                        | 1,178           | 1,178   | 0                                       |
| `pip` Fallout                                                                                           | 1,068           | 1,068   | 0                                       |
| `ltr` Tales of Middle-earth                                                                             | 856             | 856     | 0                                       |
| `40k` Warhammer 40,000                                                                                  | 617             | 617     | 0                                       |
| `fin` Final Fantasy                                                                                     | 599             | 599     | 0                                       |
| `msc`, `ltc`, `fic`, `msh`, `tla`, `tmt`, `tle`, `acr`, `spm`, `bot`, `hob`, `mar`, `rex`, `tmc`, `trc` | —               | —       | **all 0**                               |
| `sld` Secret Lair Drop                                                                                  | 2,597           | 700     | 1,897 — _correct_, mixed set            |
| `clu` Ravnica: Clue Edition                                                                             | 284             | 21      | 263 — _correct_, mixed set              |
| `unf` Unfinity                                                                                          | 639             | **0**   | _correct_ — `unf` is a joke set, not UB |

Recall is **100% on every dedicated UB set** (gap 0 on 21 of 23 probed
codes). The three non-zero gaps are all correct behaviour, not misses.
This is a per-printing marker that needs no hand-maintained set allowlist
and already handles mixed sets — strictly better than the set-code
approach the brief hypothesised.

The other stored fields are useless for this: `border_color`
(black/borderless/white/gold/silver/yellow), `frame`
(2015/2003/1997/1993/future), and `frame_effects` (legendary, inverted,
extendedart, showcase, …) contain no UB-adjacent value.

**No union is required for the product-line question. `promo_types` alone
is complete for it.** It is _not_ complete for the artwork-origin
question — see §4.5.

### 4.3 Is there a stored `art:external-ip` marker?

**No.** `Tag "external-ip"` does not exist (§3.4), `PrintingTagVote` is
empty, `Card.objects.filter(tags__contains=['external-ip'])` is 0, and
`CardTagVote.objects.filter(tag__name='external-ip')` is 0. The
`art:external-ip` import is fully implemented and has never run.

### 4.4 The two signals answer different questions

This matters and should not be collapsed. `promo_types=universesbeyond`
marks Wizards' **official product line**. Scryfall Tagger's
`art:external-ip` marks the **artwork's IP origin**.
`reason_tags.py:76-81` is explicit that our `external-ip` tag is
deliberately _not_ the product line, because a user-uploaded proxy
bearing Warhammer art is not a Wizards product but is unambiguously
external IP.

For **official printings**, `promo_types` is complete and free. For
**custom/proxy images with no Scryfall printing at all**, no Scryfall
field can help by construction — only a human can say. These are two
populations, and this repo is a proxy catalogue in which the second is
large.

Corroborating this split from the owner's own prior work: issue #437's
Phase-1 research comment (2026-07-27) already established that
`security_stamp` is **not** a deterministic UB marker (`stamp:triangle`
2,413 vs `is:universesbeyond` 4,415 on Scryfall's own search; LotR,
Avatar, Final Fantasy and Assassin's Creed carry oval or null stamps) and
that `promo_types` containing `universesbeyond` is the reproducible
signal. That research also concluded the Universes Within ↔ Universes
Beyond mapping is **not recoverable from bulk data at all**. This
document's §4.2 measurement independently reproduces the `promo_types`
half of that conclusion against our own stored copy.

### 4.5 How much broader is `art:external-ip`? — measured

The two signals have never been compared, so it was measured. The live
Scryfall Tagger `art_tags` bulk file
(`art-tags-20260729090120.jsonl.gz`, 11,429 tag rows) was fetched
read-only and parsed: the `external-ip` slug is present
(`8b7d22d4-…`, 56 direct children), its transitive subtree closes over
**2,799 tags** carrying **8,332 distinct tagged `illustration_id`
values**.

Intersected against our stored `CanonicalPrintingMetadata.illustration_id`,
those illustrations reach **~13,166 CanonicalCards**, against
`promo_types`' **10,407**.

**Delta: roughly 2,759 printings that `art:external-ip` flags and
`promo_types` does not — about 27% more.**

**Treat 13,166 as order-of-magnitude, not a dry-run result.** The
estimate joins through the DB's ingested `illustration_id` column; the
importer joins through `default_cards.json` on disk. The two should agree
closely but are not the same operation. **What the 2,759 actually
consists of is not established** — plausible populations include Secret
Lair crossovers outside the UB product line, playtest and promotional art,
and art-series cards, but no characterisation was performed. Do not
assume it is all genuine external IP, and do not assume it is all noise.

This delta is the whole of the case for the artwork-origin channel being
a distinct question rather than a redundant one. It is also the cheapest
thing left to measure (§10.3).

---

## 5. Which grain is the property actually at?

### 5.1 The counterexample search, stated and executed

The design under consideration says UB-ness is a property of the
**artwork**. The falsifying observation would be a single illustration
appearing on both a UB and a non-UB printing. It was searched for
explicitly:

```
distinct illustration_ids                                      50,828
illustration_ids on BOTH a UB and a non-UB printing                 0
illustration_ids appearing on more than one CanonicalCard       25,381
...of which span more than one expansion                        20,542
```

**Zero counterexamples**, and this is not a vacuous result: half the
illustrations in the catalogue are reprinted, and 20,542 of them cross set
boundaries, so the reprint machinery is very much exercised. It never
crosses this line.

The Universes Within reasoning holds up: a Universes Within reprint takes
the same mechanical card and gives it _different, non-UB artwork_ — a
different `illustration_id` — so it is correctly a separate row, not a
counterexample.

**Strength and limits of this result.** It is a property of our stored
data, not a proof about Scryfall in general. It covers the 112,431 rows
that have an `illustration_id`; the 793 without one are outside the test,
and `face_illustrations` being empty in production means back-face
artworks were not examined at all. What would falsify it: a UB set
reprinting an existing non-UB illustration, or a Universes Within
treatment that reuses the UB art rather than commissioning new art.

### 5.2 What this actually proves — and what it does not

Because UB-ness is constant across every printing of an illustration,
**both** grains are internally consistent. Printing grain is not _wrong_;
it is _redundant_, storing the same fact ~2.2× (113,224 printings /
50,828 illustrations). Illustration grain is more compact and cannot
contradict itself.

But compactness is not the deciding argument, because the fact is already
stored, once, per printing, in `promo_types` — for free, with no vote at
all. The redundancy costs nothing extra today.

### 5.3 The case neither grain serves

This is a proxy catalogue: 230,770 user-uploaded images against 113,224
official printings. **A custom card using external-IP art has no Scryfall
printing and no Scryfall `illustration_id`.** It cannot be reached from
either a printing-keyed or an illustration-keyed Scryfall-derived tag. The
only grain that can carry a claim about such an image is the image itself
— `Card` — and the only source of that claim is a human.

That is `CardTagVote`, which already exists, already resolves, already
persists to `Card.tags`, and is **already Elasticsearch-indexed**, so
`tag:external-ip` becomes a real search predicate the moment a vote
resolves. It is the only one of the three tag channels that works end to
end today.

---

## 6. Does an illustration tag vote exist, or must it be built?

**It must be built. It does not exist anywhere, on master or on any open
PR.**

The owner's phrasing — "just need illus tags to extend into human voting"
— describes extending something. There is nothing to extend.

What exists:

- **`CardIllustrationVote`** (`models.py:1086`, migration 0091, PRs
  #524/#531). Keyed **(Card, anonymous_id)**. The illustration is the
  _value_ of the vote, not the key. It carries `illustration_id` XOR
  `is_unknown`. It has **no `Tag` FK and no polarity**. It asserts
  _identity_ — "this image depicts artwork X" — never a descriptor.
  Production population: **3 rows**, all machine.
- **PR #573** (open, `mergeable=CLEAN`, all 9 checks green, **zero
  reviews**) adds `illustration_consensus.py`, `Card.inferred_illustration_id`
  (a plain `UUIDField`, deliberately not an FK), and
  `Card.illustration_vote_status`. It adds **no model, no table, no vote
  type, and no tag concept** — it is the missing _reader_ for
  `CardIllustrationVote`. It is illustration **identity**, exactly as the
  brief suspected.
- **No table in the schema is keyed by illustration.** Every
  `CreateModel` across migrations 0001–0097 was enumerated. The only
  illustration-bearing columns are attributes hanging off card- or
  printing-keyed rows. `CardIllustrationVote`'s own docstring states that
  `illustration_id` is deliberately not a foreign key and that no
  `CanonicalIllustration` table exists.

So "retire A, use B" is not the available choice. The available choice is
**"retire A, build B, and B's card-side consumption depends on an
unmerged PR."** Stated plainly, as instructed.

Building an illustration-grain tag vote would require, at minimum:

1. `IllustrationTagVote(AbstractWeightedVote)` — plain
   `illustration_id UUIDField(db_index=True)`, `tag FK`, `polarity`,
   `UniqueConstraint(illustration_id, tag, anonymous_id)` — plus migration.
2. `illustration_tag_consensus.py`, sibling of `tag_consensus.resolve_tag`,
   including the sensitive-tag privileged gate.
3. **A place to persist the resolved status.** This is the genuinely new
   problem. Every other channel denormalises onto a `Card` column. With no
   illustration-keyed row, an illustration-grain status has nowhere to
   live without either creating the illustration table the codebase has
   explicitly refused twice, or caching on `Card` — which reintroduces the
   fan-out the new grain existed to remove.
4. Write paths: a re-grained importer, a human surface, an endpoint, and
   registration in `vote_write` / `purge_machine_votes`.
5. A read path fanning illustration → Card, since every consumer surface
   is card-keyed. This is where PR #573 becomes a hard dependency:
   `Card.inferred_illustration_id` is the only Card → artwork bridge in
   the codebase, present or proposed.

One more thing worth stating before anyone builds it: the printing grain
was not an accident. `import_external_ip_tags`' docstring records it as a
**deliberate 2026-07-27 spec revision** ("PER-PRINTING DESIGN (revised
2026-07-27): votes target the Scryfall printing itself … rather than the
catalog images"). The importer _has_ illustration ids in hand and fans
them out to printings on purpose. Re-graining is reversing a ratified
decision, not filling a gap.

---

## 7. Recommendation

**Three separable claims. Do not treat them as one.**

### 7.1 Retire `PrintingTagVote` — recommended, and the owner is willing

Owner ruling, 2026-07-29: _"i am willing to not need the printing tag."_
The evidence supports taking that offer.

It has 0 rows, 0 human votes, no resolver, no reader, no frontend, and its
only machine writer has never run. It is not in the PROTECTED CORE list
(§8.3). Every argument for keeping it is an argument about a future
consumer that has never materialised in the ~1 month since PR #497
introduced it. If a per-printing descriptor vote is ever genuinely needed,
re-adding an empty table is cheap; carrying a phantom is not free — it
already produced two docstring references to a module that does not exist,
and it silently absorbed a fully-built import that nobody noticed had
never run.

**What would falsify this:** a consumer landing that needs per-printing
descriptor consensus specifically — one where the descriptor is a property
of _this printing_ and not of its artwork or its image. Candidates would
be printing-physical properties (foiling treatment, stamp type, promo
channel) rather than art properties. Note that every such property is also
already in `promo_types`/`frame_effects`, so this falsifier is narrow.

### 7.2 Do NOT build an illustration tag vote yet — recommended, on narrower grounds than expected

The grain is right — §5.1 searched for the counterexample and found none.
The objection is that **most of what it would compute is already stored**:
for official printings, `promo_types` gives a complete product-line answer
with no vote, no threshold, no gate, and no new table. Building a vote
channel to re-derive a fact we already have is the same category of
mistake as `PrintingTagVote` itself.

**The falsifier for this was stated, then partially found.** §4.5
measured it: `art:external-ip` reaches ~13,166 printings against
`promo_types`' 10,407, a delta of roughly 2,759. That is not nothing, and
it is exactly the population the owner's framing cares about — artwork
origin rather than product line. So the honest position is _narrower_
than "don't build":

- **Do not build an illustration-grain vote channel to carry the
  Scryfall-derived signal.** Machine votes cannot resolve (§2), so the
  channel would display nothing regardless of grain. A Scryfall-derived
  fact should be an _imported attribute_, not a vote — at whichever grain
  it is natural, which §5.1 says is the illustration.
- **Do characterise the 2,759 before deciding whether the `art_tags`
  fetch is worth carrying into the unified importer at all** (§8.7). If
  they are genuine external-IP art the product line misses, that is a real
  gap. If they are art-series and playtest noise, `promo_types` alone is
  the whole answer and the Tagger dependency can be dropped outright.
- **If it is worth carrying, carry it as an illustration-keyed
  _attribute_, not a vote.** §5.1 says the grain is the illustration; §0
  says an imported Scryfall fact is not a vote. Those compose into "an
  indexed column, not a channel."

**What would still falsify the recommendation entirely:** the 2,759
turning out to be substantially genuine external-IP art _and_ users
actually wanting to dispute it per-artwork — which would need an
illustration-keyed attribute plus a human override path, and would run
into the unsolved problem in §6 item 3 (a resolved illustration-grain
status has nowhere to live).

### 7.3 Serve the actual user-facing goal from what exists — recommended

The goal is "filter all UB cards together." Two paths, both available now:

**(a) Official printings, zero votes, zero new models.** A derived filter
over `Card.canonical_card.printing_metadata.promo_types`. **3,450 catalogue
images already resolve to a UB printing** through the existing
ingestion-time `canonical_card` link. That is 862× the entire vote
system's current resolved-printing output (4). Whether this is surfaced as
an Elasticsearch-indexed denormalised tag on `Card.tags` or as a live
join is an implementation choice, not a modelling one.

**(b) Custom/proxy images, human-only, channel already built.**
`CardTagVote` on the existing `external-ip` `Tag` — the no-match reason
strip already routes to it, `tag_consensus` already resolves it,
`Card.tags` is already ES-indexed. **This channel is blocked on one thing
only: `manage.py seed_no_match_reason_tags` has not been re-run since
2026-07-28, so the `external-ip` Tag does not exist in production.**

Paths (a) and (b) converge on the same `Tag.name` by design
(`reason_tags.py`'s own stated rationale), so `tag:external-ip` becomes
one predicate over both populations — which is precisely the owner's
stated goal, reached without any of the machinery under review.

### 7.4 Where the owner's instinct was wrong

Two places, both worth stating rather than smoothing over:

- **"scryfall tags are already that"** — true of `promo_types`, which we
  store. Not true of the Scryfall **Tagger** `art:external-ip` tag, which
  we do not store and would have to import. The owner's phrasing implies a
  marker already in hand; it isn't. What _is_ in hand is a different and,
  for the official-printing case, better signal.
- **"just need illus tags to extend into human voting"** — there is no
  illustration tag to extend. §6.

---

## 8. Migration sketch, if deprecation is chosen

### 8.1 Existing rows

**There are none.** 0 rows, 0 of them human. This is the entire migration.
No backfill, no export, no human-vote rescue. Had there been human rows
they would have had to be migrated to `CardTagVote` by fanning printing →
Card, with the fan-out ambiguity that implies; that problem does not arise.

### 8.2 What reads `PrintingTagVote` today and would break

Exhaustive, from the grep in §1.1:

| site                                                                                  | what breaks                             | fix                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `models.py:1256`                                                                      | the class                               | delete + a `DeleteModel` migration                                                                                                                                                   |
| `migrations/0088_printingtagvote.py`                                                  | nothing                                 | leave in history; add a new delete migration                                                                                                                                         |
| `admin.py:26,237-238`                                                                 | admin registration                      | delete `AdminPrintingTagVote`                                                                                                                                                        |
| `urls.py:37`, `views.py:82,2904-2990`                                                 | `POST 2/submitPrintingTagVote/`         | delete the endpoint + request model. **No frontend caller exists**, so this is not a breaking API change in practice                                                                 |
| `purge_machine_votes.py:74,237,313` (+ `printing_tag_votes_deleted` in `PurgeResult`) | the five-table enumeration becomes four | remove the queryset, the two `.delete()` calls, and the counter — **or** keep the counter field at 0 for output-shape stability. `test_purge_machine_votes.py:320-323` asserts on it |
| `vote_write.py:9,83-85`                                                               | docstring only                          | edit prose                                                                                                                                                                           |
| `import_external_ip_tags.py` (579 lines)                                              | the whole command                       | delete it, or re-point it. See §8.5                                                                                                                                                  |
| `docs/features/printing-tags.md:378-437`                                              | the External-IP import section          | rewrite                                                                                                                                                                              |
| `test_purge_machine_votes.py`, `test_vote_write.py`                                   | fixtures                                | update                                                                                                                                                                               |

Note that `verify_no_machine_only_resolutions` already explicitly excludes
`PrintingTagVote` (`purge_machine_votes.py:139`: "PrintingTagVote rows have
no persisted per-printing resolution status … so per-printing consensus is
not checked here"), so the gate needs no change.

### 8.3 PROTECTED CORE

**`PrintingTagVote` is not protected.**
`docs/upstreaming/license-provenance.md` §2 lists six modules plus the
federation/decrypt tools; `models.py` is **explicitly excluded** from
file-level protection, with a manual-review carve-out naming exactly four
classes: `VoteSource`, `AbstractWeightedVote`, `CanonicalPrintingMetadata`,
`CardPrintingTag`. `PrintingTagVote` is not among them.

`vote_consensus.py`, `printing_consensus.py`, and `tag_consensus.py` _are_
protected — but none of them reference `PrintingTagVote`, so a deprecation
touches no protected file. **No license-provenance review is triggered.**

### 8.4 `docs_lint.py` roster tethers

`check_calculator_roster_tether()` derives the calculator roster from
`*_ANONYMOUS_ID` declarations. On master it uses a **non-recursive**
`glob("*.py")` over `MPCAutofill/cardpicker` (see the comment at
`docs_lint.py:577`), so `management/commands/` is never scanned and
`SCRYFALL_TAGGER_ANONYMOUS_ID` has no roster entry today. A separate
in-flight PR (#588) is reported to fix that glob and add the roster row.
**Sequencing matters:** if #588 lands first, deleting the importer requires
removing the roster row it adds; if the deprecation lands first, #588's
glob fix will simply not find the identity. Either order works, but they
must not be done blind to each other. **This document changed nothing in
`docs_lint.py`.**

`check_skip_reason_roster_tether()` is unaffected — `import_external_ip_tags`
declares no `*_SKIP_REASON` constant.

### 8.5 The importer, specifically

`import_external_ip_tags.py` is 579 lines of complete, tested,
dry-run-defaulted code that has never executed. Three options:

- **Delete it** with the model. Its useful core —
  `find_external_ip_subtree`, `collect_illustration_ids`,
  `build_illustration_index` — is ~150 lines and reconstructible.
- **Re-point it** at `CardTagVote` (fanning printing → Card via
  `Card.canonical_card`). Note this does not make it useful: machine votes
  still cannot resolve (§2), so it would write rows that display nothing.
- **Keep it dormant** pending the §10.3 characterisation. Lowest-cost
  option if a decision on `art:external-ip` vs `promo_types` is wanted
  first. Its illustration-join core is the cheapest available tool for
  performing that characterisation.

**A live decision hiding inside it, independent of everything else:** the
negative pass (lines 363–401) votes `NOT_APPLICABLE` for _every_ confirmed
printing not in the positive set. A `--write` run today would insert on
the order of **13k `APPLY` rows plus ~100k `NOT_APPLICABLE` rows — roughly
113k rows in two `bulk_create`s**. That negative-pass volume was added
late in PR #497 and has never been exercised. Whether it is wanted is not
a settled question.

### 8.6 Why it never ran — owner ruling, plus the measured record

**Owner ruling, 2026-07-29 — this is the authoritative account and the
question is closed:** it was never rebuilt after Scryfall changed their
API process. Not abandoned on design grounds, not blocked on a decision.
**Obsolete by API drift.** The owner's direction is that the external-IP
import _"should be baked into our new unified Scryfall importer"_ rather
than continue to exist as a standalone command — see §8.7 for what that
importer would have to carry.

**The measured record is recorded alongside it, because it does not
perfectly match and suppressing that would be the exact failure mode this
repo keeps a correction log about.** The API drift in question is the
2026-07-20 bulk-data JSONL/gzip cutover. PR #555 (merged 2026-07-29T03:15Z)
subsequently repaired the bulk-data path, and this file was named in that
commit as _the one importer of three that had been hardened by hand and
kept working_ through the cutover. Verified independently: the current
live `art_tags` file parses, the `external-ip` slug is present, and every
gate in `handle()` passes today (below). So the command appears to be
functional _now_, whatever its state was when the drift stalled it.

The two accounts compose rather than conflict: **API drift stalled the
original attempt; the repair landed later; and the scheduled run of the
repaired command then fell out of the handoff chain.** The evidence for
that last step:

- It was **owner-ratified and explicitly scheduled**. The 2026-07-28
  decision record ratifies "external-ip import before bulk + standing
  pre-bulk Scryfall freshness/checksum step", and that day's handoff
  carries it as **step 4d** of an ordered merge/deploy sequence, gated
  behind PRs #509 → #511 → #512.
- **The step then stopped being carried forward.** That session pivoted to
  a Signal-daemon incident; the handoff holding the sequence was
  superseded for daemon state, and no later handoff or boot document
  restates step 4d. No document anywhere says "do not run it" or
  "descoped".
- **Nothing could have reported the omission.** `docs_lint.py`'s
  calculator roster tether used a non-recursive `glob("*.py")`, so
  `management/commands/` was never scanned and `scryfall-tagger-v1` was
  absent from the derived identity set, from
  `docs/pipeline-fidelity-gate.md`, and from the allowlist — dormant with
  nothing anywhere that would say so. It was found incidentally on
  2026-07-29 by a worker fixing that glob (PR #588, open).
- **It has been actively maintained four times since**, which is
  inconsistent with abandonment: PR #520 (purge wiring), #534
  (transactional purge+write — this is the app's only `printing_id`-keyed
  call site), #555 (Scryfall JSONL/gzip cutover, in which this file was
  noted as the one importer of three that had been hardened by hand and
  survived), and #570 (docstring re-scope of the zero-weight rule). None
  was a decision to run it.
- **A known-undone sibling follow-up corroborates "forgotten":** PR #497's
  open item 5 — the wiki Backend-commands row for
  `import_external_ip_tags` — is also still unchecked.
- **The design doubt post-dates the dormancy.** The owner's suspicion that
  the grain is wrong is dated 2026-07-29, a day _after_ the run was
  already missed. It is not the cause.

**Either way, the conclusion for the ruling is the same.** The
printing-grain design was **never tested against reality** — it has
produced zero rows and has never had a consumer. Nothing about its
dormancy is evidence for or against the grain. And per the owner's
assessment of the implementation itself — _"printingtag was half cooked by
the same model that introduced all these bugs this weekend"_ — the
existing code carries no accumulated design authority that a rebuild would
be discarding.

**Every prerequisite passes today**, checked read-only:
`find_stale_applied_migrations()` returns `[]`; the 620 MB
`default_cards.json` cache exists in the container; the `external-ip` slug
is present in the current live `art_tags` file; the Scryfall bulk-data
index returns 200 with the post-cutover `jsonl_download_uri` shape; the
deployed image contains both #497 and #555; the `Tag` is `get_or_create`d
so its absence is not a blocker.

_Not established:_ whether it was ever dry-run outside production (the
ledger covers this database only).

### 8.7 What the unified Scryfall importer must carry

Per the owner's direction that the external-IP import belongs inside the
new unified Scryfall importer rather than as a standalone command. This is
a specification of what to carry, not an implementation.

**Carry these — they are the parts that earned their place:**

1. **`promo_types` is already ingested; just read it.** `universesbeyond`
   on 10,407 of 113,224 printings, 100% per-set recall (§4.2). This needs
   no importer change at all — it is the existing
   `import_scryfall_printing_metadata` output. The gap is a _consumer_,
   not an ingestion step.
2. **The `art_tags` fetch, if §10.3's characterisation justifies it.** The
   reusable core is ~150 lines: `find_external_ip_subtree` (BFS from the
   `external-ip` slug over `child_ids`; only leaf tags carry taggings),
   `collect_illustration_ids`, and `build_illustration_index`. It fetches
   the `art_tags` bulk entry's `jsonl_download_uri` (~12 MB gzipped) and
   joins on `illustration_id`.
3. **Join and store at illustration grain, not printing grain.** §5.1
   found no counterexample: UB-ness is constant across every printing of
   an illustration. `CanonicalPrintingMetadata.illustration_id` is already
   stored and indexed. Fanning one artwork fact out to ~2.2 printings was
   the redundancy the printing-grain design introduced; the unified
   importer should not repeat it.
4. **Store it as an attribute, not as votes.** This is §0's principle
   applied: an imported Scryfall fact is not disputable, so it must not
   enter the vote system. Whatever column or sidecar it lands in, it
   should be readable directly, without a threshold or a resolver.
5. **`face_illustrations` needs populating** (§4.1) — the column and its
   partial index shipped in migration 0095 but production has 0 rows, so
   back-face artwork is currently unattributable. Any illustration-keyed
   join is incomplete until the metadata import is re-run.

**Do not carry these:**

- **The negative pass.** Voting `NOT_APPLICABLE` on every printing outside
  the positive set (~100k rows) exists only because the old design needed
  vote rows to express absence. An attribute expresses absence by being
  absent.
- **`source=DEDUCTION` / `anonymous_id="scryfall-tagger-v1"` / `run_id`
  stamping / `purge_machine_votes` integration.** All of it is vote-system
  plumbing for something that should not be a vote. It also means the
  identity drops off the calculator roster entirely, which is correct — it
  was never a calculator.
- **`security_stamp` as a UB signal.** The deferred "triangle → APPLY" path
  from PR #497 was already invalidated by the owner's own #437 Phase-1
  research (§4.4). It was never implemented; it should not be revived.

---

## 9. Every number, with its query

All run via `docker exec mpcautofill_django python manage.py shell -c "…"`,
read-only. No `.save()`, `.delete()`, `.create()`, `.update()`, or
`bulk_*` was issued at any point.

| finding                           | query                                                                                                                                                                                | result                                                                                                                          |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| PrintingTagVote empty             | `PrintingTagVote.objects.count()`                                                                                                                                                    | `0`                                                                                                                             |
| …by source / anon_id / tag        | `.values('source'/'anonymous_id'/'tag__name').annotate(n=Count('id'))`                                                                                                               | `[]`, `[]`, `[]`                                                                                                                |
| importer never ran                | `PilotRunLedger.objects.filter(command__icontains='external').values()`                                                                                                              | `[]`                                                                                                                            |
| CardPrintingTag total             | `CardPrintingTag.objects.count()`                                                                                                                                                    | `167229`                                                                                                                        |
| CardTagVote total / by source     | `CardTagVote.objects.count()`; `.values('source').annotate(n=Count('id'))`                                                                                                           | `223999`; `ocr` 223,893, `user` 106                                                                                             |
| CardTagVote human by tag          | `.filter(source=VoteSource.USER).values('tag__name').annotate(n=Count('id'))`                                                                                                        | custom-art 80, Borderless 5, Modern Border 4, Black Border 4, Upscaled 4, altered-frame 4, ai-art 3, AI-Generated 1, Full Art 1 |
| CardIllustrationVote              | `CardIllustrationVote.objects.count()`; `.values('source'/'anonymous_id').annotate(...)`                                                                                             | `3`; all `deduction` / `stage-d-illustration-v1`                                                                                |
| Card / CanonicalCard / CPM totals | `.objects.count()`                                                                                                                                                                   | 230,770 / 113,224 / 113,224                                                                                                     |
| printing_tag_status               | `Card.objects.values('printing_tag_status').annotate(n=Count('id'))`                                                                                                                 | unresolved 230,744; no_match 22; **resolved 4**                                                                                 |
| ingestion-time printing link      | `Card.objects.filter(canonical_card__isnull=False).count()`                                                                                                                          | `19475`                                                                                                                         |
| Tag census                        | `Tag.objects.count()`; `.values_list('name', flat=True)`                                                                                                                             | `30`; no `external-ip`                                                                                                          |
| external-ip absent                | `Tag.objects.filter(name__icontains='external')`                                                                                                                                     | `[]`                                                                                                                            |
| …and unused                       | `Card.objects.filter(tags__contains=['external-ip']).count()`; `CardTagVote.objects.filter(tag__name='external-ip').count()`                                                         | `0`; `0`                                                                                                                        |
| **UB signal**                     | `CanonicalPrintingMetadata.objects.filter(promo_types__contains=['universesbeyond']).count()`                                                                                        | **`10407`**                                                                                                                     |
| …by expansion                     | `CanonicalCard.objects.filter(printing_metadata__promo_types__contains=['universesbeyond']).values('expansion__code','expansion__name').annotate(n=Count('id')).order_by('-n')`      | 68 expansions; who 1178, pip 1068, msc 866, ltr 856, sld 700, 40k 617, fin 599, …                                               |
| per-set recall                    | `.values('expansion__code').annotate(total=Count('id'), flagged=Count('id', filter=Q(printing_metadata__promo_types__contains=['universesbeyond'])))` over a hand-listed UB code set | gap 0 on 21/23; sld and clu correctly partial; unf correctly 0                                                                  |
| promo_types token ranking         | `Counter` over `.values_list('promo_types')`                                                                                                                                         | `universesbeyond` 10,407 is rank 1; boosterfun 9,487; datestamped 4,057                                                         |
| Card-level UB reach               | `Card.objects.filter(canonical_card__printing_metadata__promo_types__contains=['universesbeyond']).count()`                                                                          | **`3450`**                                                                                                                      |
| border_color distribution         | `.values('border_color').annotate(n=Count('canonical_card'))`                                                                                                                        | black 99,974 / borderless 5,962 / white 5,159 / gold 1,373 / silver 666 / yellow 90 — no UB value                               |
| frame distribution                | `.values('frame').annotate(...)`                                                                                                                                                     | 2015 76,944 / 2003 18,084 / 1997 12,301 / 1993 5,653 / future 242 — no UB value                                                 |
| frame_effects tokens              | `Counter` over `.values_list('frame_effects')`                                                                                                                                       | legendary 11,537 / inverted 7,362 / extendedart 4,165 / showcase 3,074 / … — no UB value                                        |
| illustration coverage             | `.filter(illustration_id__isnull=False).count()` / `isnull=True`                                                                                                                     | 112,431 / 793                                                                                                                   |
| face_illustrations empty          | `.exclude(face_illustrations=[]).count()`                                                                                                                                            | **`0`** (column shipped, import not re-run)                                                                                     |
| **counterexample search**         | group `(illustration_id, promo_types, expansion__code)` over all rows with an `illustration_id`; count ids seen on both a UB and a non-UB printing                                   | **`0`** of 50,828                                                                                                               |
| …non-vacuity                      | same pass: ids on >1 CanonicalCard; ids spanning >1 expansion                                                                                                                        | 25,381; 20,542                                                                                                                  |
| consensus gate                    | executed `resolve_weighted_consensus` with machine-only `VoteTuple`s at n=1,2,4,10,1000                                                                                              | `None` at every n                                                                                                               |
| …and with a human                 | 1 human + 1 machine; 1 human + 2 machine                                                                                                                                             | `None`; resolves                                                                                                                |
| weights in force                  | `settings.PRINTING_TAG_*`; `vote_consensus._SOURCE_WEIGHTS`                                                                                                                          | MIN_VOTES 2, MIN_SHARE 0.6, MACHINE 0.5, IMPLICIT_CAP 1.0, ADMIN 5, USER 1.0                                                    |
| DEDUCTION not human-backed        | `is_human_backed_source(VoteSource.DEDUCTION)`                                                                                                                                       | `False`                                                                                                                         |
| art_tags subtree size             | parse of live `art-tags-20260729090120.jsonl.gz` (11,429 tag rows); BFS from slug `external-ip` (`8b7d22d4-…`, 56 direct children)                                                   | 2,799 tags, **8,332** distinct tagged `illustration_id`                                                                         |
| **art:external-ip reach**         | intersect those 8,332 against `CanonicalPrintingMetadata.illustration_id`                                                                                                            | **~13,166** CanonicalCards _(order-of-magnitude — joins through the DB column, not `default_cards.json` as the importer does)_  |
| **delta vs promo_types**          | 13,166 − 10,407                                                                                                                                                                      | **~2,759 printings**, content not characterised                                                                                 |
| importer never invoked            | distinct `PilotRunLedger.command` values (16)                                                                                                                                        | `import_external_ip_tags` absent; covers dry-runs, since `handle()` writes the ledger row before branching                      |
| importer prerequisites pass       | `find_stale_applied_migrations()`; `default_cards.json` stat; live bulk-data index; `external-ip` slug lookup                                                                        | `[]`; 620,779,264 bytes present; 200 + `jsonl_download_uri`; slug found                                                         |
| write-run scale                   | positive set vs `CanonicalCard` total (113,224)                                                                                                                                      | ~13k `APPLY` + ~100k `NOT_APPLICABLE`                                                                                           |

Static findings (grep / `git log --all` / `gh`):

- `PrintingTagVote` non-test references: 30 lines, 8 files, no consensus module.
- `printing_tag_consensus.py`: absent on disk, absent from `git log --all`
  (324 refs), absent from all 14 open PRs, GitHub code search
  `total_count: 0`.
- No frontend caller of `submitPrintingTagVote` in `frontend/src/`.
- PR #573: open, `MERGEABLE`/`CLEAN`, 9/9 checks green, **0 reviews**.
- `_split_new_printing_tag_votes` signature: `list[CardPrintingTag]`.

**Not established**, stated as such rather than inferred:

1. **What the ~2,759-printing delta between `art:external-ip` and
   `promo_types` actually consists of** (§4.5). The count is measured; its
   content is not. This is the single most decision-relevant gap left.
2. Whether Scryfall marks `universesbeyond` on every UB printing
   _upstream_. Only our stored copy was measured. The 100%-per-set table is
   strong circumstantial evidence, not an upstream audit.
3. Whether `master` branch protection requires an approving review, which
   would make #573's zero reviews its only blocker.
4. Back-face artwork behaviour in the §5.1 counterexample search, because
   `face_illustrations` is empty in production.
5. Whether `import_external_ip_tags` was ever dry-run outside production,
   and whether the owner ever consciously held the run. The _proximate_
   cause of the non-run **is** established (§8.6) — this is the residual.
6. The exact composition of `CardPrintingTag`'s 167,229 rows by source;
   only the total was taken, since the human-vote question that mattered
   was `PrintingTagVote`'s.

---

## 10. Open questions for the owner

Numbered and answerable. **Three questions this document opened have
already been ruled on (2026-07-29) and are recorded as closed at the end,
not re-asked.**

1. **Retire `PrintingTagVote`?** It has 0 rows, 0 human votes, no
   resolver, no reader, no frontend, and its only writer has never run.
   The owner has said they are willing; this asks for the go-ahead to
   dispatch it. Recommendation: yes. _(§7.1, §8)_ — **RULED YES and
   EXECUTED, 2026-07-30, PR #615. No longer open.**

2. **Seed the `external-ip` Tag in production?** One command,
   `manage.py seed_no_match_reason_tags`. Until it runs, the human
   card-grain channel — the one that actually works end to end — cannot
   record `external-ip` at all, and neither can any printing-tag endpoint.
   This is independent of every other decision here. Recommendation: yes,
   immediately. _(§3.4)_

3. **Characterise the ~2,759-printing delta.** The count is now measured
   (§4.5): `art:external-ip` reaches ~13,166 printings, `promo_types`
   10,407. What is _in_ that delta is unknown, and it decides whether the
   artwork-origin question is genuinely distinct from the product-line
   question. A sample of ~50 from the difference set would settle it in
   minutes, using the importer's existing illustration-join core. **This is
   the cheapest and most decision-relevant thing left to do.**
   Recommendation: do this before any build decision. _(§4.5, §7.2)_

4. **Surface UB from `promo_types` — denormalised tag or live join?**
   3,450 catalogue images already resolve to a UB printing today.
   Denormalising onto `Card.tags` gets Elasticsearch filtering for free
   and converges with the human channel on one predicate; a live join
   avoids a second source of truth. Recommendation: denormalise, because
   the human channel must share the predicate. _(§7.3)_

5. **Add `set_type` and `security_stamp` to ingestion?**
   Recommendation: **no, not for this purpose** — and this reverses what
   the codebase's own docstrings imply. `views.py:2947` and
   `reason_tags.py:81` both name `security_stamp` as the future
   authoritative UB signal, but the owner's own issue-#437 Phase-1
   research (2026-07-27) already established it is **not** deterministic
   (`stamp:triangle` 2,413 vs `is:universesbeyond` 4,415; LotR, Avatar,
   Final Fantasy and Assassin's Creed carry oval or null). Those two
   docstrings are stale and should be corrected to name `promo_types`.
   `set_type` is redundant given `promo_types` unless something unrelated
   wants it. _(§4.1, §4.4)_

6. **The negative pass: do we want ~100k `NOT_APPLICABLE` rows?** If
   `import_external_ip_tags` is ever run with `--write`, it votes
   `NOT_APPLICABLE` on every confirmed printing outside the positive set —
   roughly 13k `APPLY` plus ~100k negative rows into a table that today
   has none and that nothing reads. That volume was added late in PR #497
   and has never been exercised. Recommendation: strip the negative pass
   or gate it behind its own flag before any write run. _(§8.5)_

7. **Correct or remove the `printing_tag_consensus.py` references?** Two
   docstrings in `import_external_ip_tags.py` (lines 29, 546) direct
   readers to a module that has never existed on any branch. Whatever is
   decided about the model, this should not survive. _(§2.1)_

8. **PR #573 — merge, hold, or change?** It is clean and green with zero
   reviews. Nothing in this document depends on it _unless_ an
   illustration-grain tag channel is later built, in which case
   `Card.inferred_illustration_id` is the only Card → artwork bridge that
   exists. It is independently useful as the missing reader for
   `CardIllustrationVote` (3 rows today). _(§6)_

9. **Re-run `import_scryfall_printing_metadata` to populate
   `face_illustrations`?** The column and its partial index shipped in
   migration 0095; production has 0 populated rows. Anything depending on
   back-face artwork attribution is silently degraded until it runs — and
   it is the one gap in §5.1's counterexample search. _(§4.1, §5.1)_

10. **Sequencing against PR #588.** #588 (open) adds the roster row that
    records `scryfall-tagger-v1` as dormant. If `PrintingTagVote` is
    retired, that row must be removed again. Recommendation: let #588
    merge first — the roster fix is correct independent of this ruling,
    and a row that is later deleted is cheaper than a tether that silently
    misses the next dormant identity. _(§8.4)_

11. **Does the external-IP import survive into the unified Scryfall
    importer, or is it dropped entirely?** The owner's direction is that
    it should be baked in (§8.7). But item 3 may make it unnecessary: if
    the ~2,759 delta is noise, `promo_types` is the whole answer and the
    Tagger dependency — a second bulk download and a second join — buys
    nothing. Recommendation: make this conditional on item 3, not
    scheduled ahead of it. _(§8.7)_

---

### Already ruled on 2026-07-29 — recorded, not re-asked

- **Why the import never ran.** Never rebuilt after Scryfall changed their
  API process; it belongs in the new unified Scryfall importer. Closed.
  The measured record that does not perfectly match this account is
  preserved in §8.6 rather than dropped, and the two compose.
- **Whether the machine-only-cannot-resolve gate is a defect.** It is not:
  _"that is the entire theory in one sentence, we designed things like
  this on purpose."_ This document treats it as the governing constraint
  (§0), not as a finding against the vote system.
- **Whether the owner would accept dropping `PrintingTagVote`.** Yes,
  willing. Item 1 above asks only for the dispatch, not the principle.
