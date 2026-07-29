# What is actually in the `art:external-ip` ↔ `promo_types` delta?

**As of 2026-07-29.** Read-only investigation against production, the
already-downloaded `default_cards.json`, and one fresh fetch of the live
Scryfall Tagger `art_tags` bulk file. No pipeline code was changed, no
management command was run, and no row was written.

This answers the single open item PR #599 left as "the cheapest and most
decision-relevant thing left to do": its §4.5 measured that Scryfall
Tagger's `art:external-ip` reaches ~13,166 of our printings against
`promo_types`' 10,407 — **a delta of roughly 2,759 whose content was
explicitly _not established_.** The decision riding on it: does the
Scryfall Tagger dependency survive into the planned unified Scryfall
importer, or does the whole design collapse to one already-stored field?

---

## The answer in three sentences

The delta is **real and slightly larger than reported** — 2,820 printings
after reconciling the join paths, not 2,759 — and it is **not** a join
artifact. But **95.7% of it is not Universes Beyond**: 2,351 printings
(83.4%) are Dungeons & Dragons / Forgotten Realms, which Wizards owns and
never branded Universes Beyond, and a further 348 (12.3%) are Portal
Three Kingdoms and its reprints, drawn from a public-domain 14th-century
novel with no licence and no product line. Of the 121 printings that are
genuine third-party licensed IP, **39 are already marked in the very same
`promo_types` column** under the tokens `godzillaseries` and
`draculaseries`, leaving **at most 82 printings — 0.07% of the
catalogue — that no structured Scryfall field reaches at all**, and 21 of
those turn out to be art homages rather than licensed products.

**Recommendation: drop the Scryfall Tagger dependency.** It costs a
second bulk download and a second join to buy 61 genuinely-licensed
printings that `promo_types` misses, while itself missing 61 printings
that `promo_types` catches, and it drags 2,699 non-UB printings in with
them. §6 states what would falsify this.

---

## 1. Reconciling the two join paths first

PR #599 was explicit that its two figures came through different join
paths and that an apples-to-oranges delta is not a finding. So both
populations were recomputed over one universe — the 113,224
`CanonicalCard` rows — before differencing.

The Tagger side was reproduced from scratch: the live
`art-tags-20260729090120.jsonl.gz` (11,429 tag rows, the same file PR
#599 used) parses, the `external-ip` slug resolves to
`8b7d22d4-f840-471d-832e-27b5af6d1d63` with 56 direct children, its
transitive subtree closes over **2,799 tags** carrying **8,332 distinct
tagged `illustration_id` values**. Both figures match PR #599 exactly.

Those 8,332 illustrations were then joined to printings **twice**, once
each way:

| population                                     | how                                                                                            | result     |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------- | ---------- |
| `P` — `promo_types` contains `universesbeyond` | `CanonicalPrintingMetadata.promo_types__contains`                                              | **10,407** |
| `T_db` — Tagger, via the DB column             | intersect against `CanonicalPrintingMetadata.illustration_id` (112,431 non-null rows)          | **13,166** |
| `T_json` — Tagger, via the importer's own path | `build_illustration_index(default_cards.json)` → Scryfall card id → `CanonicalCard.identifier` | **13,168** |

**The two join paths agree to within 2 rows.** `T_db − T_json` is 0;
`T_json − T_db` is 2 — both back-face illustrations that
`default_cards.json` exposes under `card_faces[].illustration_id` and
that the DB cannot see because `CanonicalPrintingMetadata.face_illustrations`
is empty in production (PR #599 §4.1). Only 2 of the 8,332 tagged
illustrations map to no `default_cards.json` row at all.

**The delta survives reconciliation, and grows.** The original ~2,759 was
a plain subtraction, which silently assumed `P ⊆ T`. It is not:

```
T_db ∩ P   = 10,346
T_db − P   =  2,820   <- the delta this document characterises
P  − T_db  =     61   <- printings promo_types catches and the Tagger misses
```

So the honest delta is **2,820**, and there is a **second, opposite delta
of 61** that the subtraction hid entirely (§5). All figures below use
`T_db`, the DB path, because it is the one a unified importer would
actually read; the 2-row difference changes nothing.

**Not a join artifact.** The falsifying test for illustration_id
collision was run directly: of the 1,490 distinct illustrations behind
the 2,820 delta printings, **0** also appear on a printing that
`promo_types` flags. The delta is a clean set difference, consistent with
PR #599 §5.1's finding that UB-ness never crosses an illustration
boundary in our data.

---

## 2. What the delta consists of

Every one of the 2,820 delta rows was mapped to its IP family by walking
the Tagger hierarchy: for each of the 56 direct children of `external-ip`,
the child's own subtree was closed, giving each leaf tag an unambiguous
top-level family. **Every delta row resolved to exactly one family** — no
row was unclassifiable, and no row spanned two families.

| IP family (Tagger's own top-level child of `external-ip`)                | delta rows |
| ------------------------------------------------------------------------ | ---------: |
| `dungeons-and-dragons`                                                   |      2,351 |
| `romance-of-the-three-kingdoms`                                          |        348 |
| `godzillaverse`                                                          |         49 |
| `bram-stoker-s-dracula`                                                  |         31 |
| `my-little-pony`                                                         |         21 |
| `usagi-yojimbo`                                                          |          6 |
| `cowboy-bebop`                                                           |          5 |
| `duel-masters`                                                           |          2 |
| `transformers`                                                           |          2 |
| `fallout-universe`, `monopoly`, `nerf-darts`, `pusheen`, `robot-chicken` |     1 each |
| **total**                                                                |  **2,820** |

By expansion the same story: `clb` 702, `afr` 424, `hbg` 420, `pafr` 241,
`ptk` 180, `sld` 126, `afc` 126, `pclb` 104, `prm` 94, `plst` 87,
`me3` 68, then a long tail of 68 further sets. The single most productive
Tagger leaf tag in the whole delta is `abeir-toril` — the name of the
Forgotten Realms planet — with 1,861 of the 2,820 rows.

---

## 3. Classification

Categories were built from what the data actually showed, not chosen in
advance. Because the family mapping above is exact and unique per row,
**the whole 2,820 could be classified, not just the sample** — the
sample in §4 is a spot-check of that classification rather than the
basis for it.

| #   | category                                                                              |  rows | share |
| --- | ------------------------------------------------------------------------------------- | ----: | ----: |
| 1   | **D&D / Forgotten Realms — Wizards-owned crossover, never branded Universes Beyond**  | 2,351 | 83.4% |
| 2   | **Romance of the Three Kingdoms — public-domain source, not a licensed product**      |   348 | 12.3% |
| 3   | **Licensed third-party IP, already marked by a _different_ `promo_types` token**      |    39 |  1.4% |
| 4   | **Licensed third-party IP, marked only by `flavor_name`**                             |    24 |  0.9% |
| 5   | **Licensed or Hasbro-family crossover with no structured Scryfall marker at all**     |    37 |  1.3% |
| 6   | **Art that depicts licensed-looking subject matter without being a licensed product** |    21 |  0.7% |
| 7   | **Join artifacts (illustration_id collisions, shared art)**                           | **0** |    0% |

**Category 1 — D&D, 2,351 rows.** `afr`, `clb`, `hbg` and their promo,
token, commander and Alchemy siblings. Wizards owns Dungeons & Dragons,
so these shipped as ordinary Magic expansions; Scryfall's own
`is:universesbeyond` excludes them, and our stored `promo_types` correctly
does too. Verified upstream on three of them (§4): `clb` 212 Acolyte of
Bahamut, `afr` 155 Meteor Swarm and `plst` AFR-6 Cleric Class all return
`promo_types: null` from the live API — our copy is not stale, Scryfall
genuinely does not mark them. **A UI filter labelled "Universes Beyond"
that returned 2,351 Baldur's Gate cards would be wrong.**

**Seven of these are the false positive the brief anticipated.** `slx`
24–30 (Rashel Fist of Torm, Themberchaud, Evin Waterdeep Opportunist,
Jurin, Casal, Bohn, Mathise) are in the set **Universes Within** —
verified by live lookup, `set_name: "Universes Within"`,
`set_type: masters`, released 2025-04-25. Universes Within is by
definition the _non_-UB reskin, so these are unambiguous false positives
for a UB filter. Each has a unique `illustration_id` shared with no other
printing, so they are genuine Tagger taggings, not art reuse.

**Category 2 — Romance of the Three Kingdoms, 348 rows.** `ptk` Portal
Three Kingdoms (180) plus its reprints across `me3` (68), `td0` (15),
`pz2` (10), `brb` (9), `prm` (8), `c13` (7), `8ed` (4), `s99` (1) and 23
further sets. The source is a 14th-century Chinese novel in the public
domain: no licence, no crossover product, no UB branding. Verified
upstream on `ptk` 20 Shu Defender — `promo_types: null`,
`set_type: starter`, released 1999-05-01, twenty-four years before the
Universes Beyond brand existed.

**Category 3 — 39 rows already answerable from `promo_types`.** This is
the most consequential single finding after the D&D share. The Godzilla
series in Ikoria and the Dracula series in Crimson Vow **are** genuine
licensed third-party crossovers, and Scryfall **does** mark them in the
same column we already ingest — just under different tokens:

| token            | printings in the whole catalogue | all inside the delta? |
| ---------------- | -------------------------------: | --------------------- |
| `godzillaseries` |                               21 | yes, all 21           |
| `draculaseries`  |                               18 | yes, all 18           |

Verified upstream: `iko` 373 Void Beckoner returns
`promo_types: ["boxtopper","godzillaseries","boosterfun"]` and
`flavor_name: "Spacegodzilla, Death Corona"`; `vow` 343 Olivia, Crimson
Bride returns `promo_types: ["draculaseries","boosterfun"]` and
`flavor_name: "Sisters of the Undead"`. **These 39 need no Tagger — they
need two more strings in a filter predicate.**

**Category 4 — 24 rows marked only by `flavor_name`.** The Godzilla-series
promo reprints (18) carry no `promo_types` at all but do carry the
licensed name: `prm` 80921 Yidaro, Wandering Monster returns
`promo_types: null`, `flavor_name: "Godzilla, Doom Inevitable"`. Three
Dracula rows and three Usagi Yojimbo rows behave the same way
(`sld` 2381 Sunforger → `flavor_name: "The Grass-Cutting Sword"`).
`flavor_name` is a structured Scryfall field; it is **not** currently
parsed into `PrintingMetadataRow` (checked against PR #599's §4.1
inventory, which does not list it).

**Category 5 — 37 rows with no structured marker anywhere.** Enumerated
in full because the number is small enough to be exhaustive: My Little
Pony (21 — `ptg` 1–3 plus the `sld` Ponies drops and their basics),
Cowboy Bebop (5 — `pcbb` 1–5), Usagi Yojimbo (3 — verified: `sld` 7076
Big Score is illustrated by **Stan Sakai**, Usagi Yojimbo's creator),
Transformers (2 — `h17` 1 Grimlock, `ph18` 2 Optimus Prime), Duel Masters
(2 — `mb2` 558 Bolshack Dragon, `phtr` 3 Nira Hellkite Duelist), Fallout
(1 — `sld` 7097 Command Tower, flavour text _"Drive In, Fly Out!
—Red Rocket Slogan"_), Monopoly (1 — `ph23` 1 Mr. Monopoly), Nerf
(1 — `h17` 2 Nerf War), Robot Chicken (1 — `pcel` 6). Note the
concentration in HasCon, Heroes of the Realm and Secret Lair — Hasbro
family properties and one-off drops that predate or sit outside the
Universes Beyond brand. **This is the entire population the Tagger
dependency would exist to serve.**

**Category 6 — 21 rows of homage, not licence.** Twenty are basic lands:
`sld` 63–67 and `pana` 236–240 tagged `godzilla`/`mothra`, and `sld`
359–363 and `pana` 262–266 tagged `count-dracula`. Verified on three of
them — `sld` 63 Plains (Lars Grant-West), `sld` 66 Mountain (Grzegorz
Rutkowski) and `pana` 265 Mountain (Grzegorz Rutkowski) — all return
`promo_types: null`, no `flavor_name`, plain `Basic Land` type lines, no
licensed branding of any kind. The community tagged the artwork because
it _depicts_ a kaiju or a vampire. The twenty-first is `cmb1` 84
Soulmates, a Mystery Booster playtest card by Victoria Caña tagged
`pusheen`. The remaining 18 basics are contiguous collector numbers from
the same drops as the three verified ones; that they behave identically
is a structural argument, not an individually verified fact — **stated as
an inference, not established per row**.

**Category 7 — zero.** Measured directly, not assumed: see §1.

---

## 4. The sample

**Sampling method.** Stratified by IP family, then systematic within each
stratum. Rows were sorted by `(expansion code, collector number, name)`
and picked at evenly spaced indices `⌊(i+½)·n/k⌋` — sorting by expansion
first makes the spacing spread the picks across expansions rather than
clustering them. Allocation was deliberately **not** proportional: D&D was
given 20 of 51 rather than its proportional 42 so that every one of the
14 IP families got at least one row, including all seven singletons. The
consequence is that the sample's category mix (§4.1) intentionally
over-represents the small categories relative to the population; the
population counts in §3 are the deliverable, and they are exact rather
than sampled.

| #   | card                                       | set    | cn    | illustration_id (first 8) | Tagger tag(s)                 | `promo_types`                         | cat |
| --- | ------------------------------------------ | ------ | ----- | ------------------------- | ----------------------------- | ------------------------------------- | --- |
| 1   | Component Pouch                            | `afc`  | 59    | `89c5676f`                | abeir-toril                   | _(none)_                              | 1   |
| 2   | Arcane Investigator                        | `afr`  | 46    | `d632af43`                | abeir-toril                   | _(none)_                              | 1   |
| 3   | Meteor Swarm                               | `afr`  | 155   | `e3eb13e6`                | abeir-toril                   | _(none)_                              | 1   |
| 4   | Plains                                     | `afr`  | 263   | `d63ecf05`                | abeir-toril                   | _(none)_                              | 1   |
| 5   | Meteor Swarm                               | `afr`  | 380   | `e3eb13e6`                | abeir-toril                   | boosterfun                            | 1   |
| 6   | Sapphire Dragon // Psionic Pulse           | `clb`  | 94    | `6aa37d97`                | abeir-toril, sapphire-dragon  | _(none)_                              | 1   |
| 7   | Acolyte of Bahamut                         | `clb`  | 212   | `50d416c4`                | abeir-toril, bahamut-symbol   | _(none)_                              | 1   |
| 8   | Navigation Orb                             | `clb`  | 329   | `7294183f`                | abeir-toril                   | _(none)_                              | 1   |
| 9   | Moss Diamond                               | `clb`  | 448   | `674c9562`                | dungeons-and-dragons          | boosterfun                            | 1   |
| 10  | Kindred Discovery                          | `clb`  | 565   | `d5536061`                | abeir-toril                   | boosterfun                            | 1   |
| 11  | Venture Forth                              | `clb`  | 683   | `a501ae67`                | abeir-toril                   | _(none)_                              | 1   |
| 12  | Wyll of the Fey Pact                       | `hbg`  | 15g   | `94c21115`                | abeir-toril, wyll             | _(none)_                              | 1   |
| 13  | Priest of Ancient Lore                     | `hbg`  | 99    | `7d37ebd3`                | abeir-toril                   | _(none)_                              | 1   |
| 14  | Band Together                              | `hbg`  | 200   | `4b80eaad`                | abeir-toril, boo…             | _(none)_                              | 1   |
| 15  | Deadly Dispute                             | `p30a` | 29    | `abc48607`                | abeir-toril                   | datestamped                           | 1   |
| 16  | Orb of Dragonkind                          | `pafr` | 157a  | `199ccf63`                | abeir-toril                   | embossed, instore                     | 1   |
| 17  | Hive of the Eye Tyrant                     | `pafr` | 258s  | `cdae5081`                | abeir-toril                   | prerelease, datestamped               | 1   |
| 18  | Cleric Class                               | `plst` | AFR-6 | `5101c556`                | abeir-toril                   | _(none)_                              | 1   |
| 19  | Share the Spoils                           | `prm`  | 92744 | `127f5083`                | abeir-toril                   | _(none)_                              | 1   |
| 20  | Bloody Betrayal                            | `sld`  | 7102  | `5df1d173`                | ravenloft, tatyana            | sldbonus                              | 1   |
| 21  | Strategic Planning                         | `c13`  | 59    | `d4b74ed4`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 22  | Forced Retreat                             | `me3`  | 37    | `8b1b3853`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 23  | Swamp                                      | `me3`  | 223   | `7bdb31a5`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 24  | Shu Defender                               | `ptk`  | 20    | `2fd0077a`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 25  | Wu Spy                                     | `ptk`  | 63    | `2eac4cd6`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 26  | Desert Sandstorm                           | `ptk`  | 107   | `9a191d10`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 27  | Taoist Hermit                              | `ptk`  | 150   | `76c3f234`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 28  | Capture of Jingzhou                        | `sld`  | 2149  | `26d5abcc`                | romance-of-the-three-kingdoms | _(none)_                              | 2   |
| 29  | Void Beckoner                              | `iko`  | 373   | `7325f854`                | spacegodzilla                 | boxtopper, godzillaseries, boosterfun | 3   |
| 30  | Sprite Dragon                              | `iko`  | 382   | `1cd28d3e`                | dorat                         | boxtopper, godzillaseries, boosterfun | 3   |
| 31  | Forest                                     | `pana` | 240   | `ea87bafb`                | godzilla                      | _(none)_                              | 6   |
| 32  | Yidaro, Wandering Monster                  | `prm`  | 80921 | `9539747c`                | godzilla                      | _(none)_                              | 4   |
| 33  | Plains                                     | `sld`  | 63    | `84d1a5f2`                | godzilla, mothra              | _(none)_                              | 6   |
| 34  | Mountain                                   | `pana` | 265   | `baf083eb`                | count-dracula                 | _(none)_                              | 6   |
| 35  | Mountain                                   | `sld`  | 362   | `baf083eb`                | count-dracula                 | _(none)_                              | 6   |
| 36  | Henrika Domnathi // Henrika, Infernal Seer | `vow`  | 335   | `7ea5f6c8`                | brides-of-dracula             | draculaseries, boosterfun             | 3   |
| 37  | Olivia, Crimson Bride                      | `vow`  | 343   | `8548c399`                | brides-of-dracula             | draculaseries, boosterfun             | 3   |
| 38  | Discord, Lord of Disharmony                | `sld`  | 798   | `cbec4e68`                | discord-character             | sldbonus                              | 5   |
| 39  | Radiate                                    | `sld`  | 2536  | `54d24d90`                | rainbow-dash                  | _(none)_                              | 5   |
| 40  | Mountain                                   | `sld`  | 2543  | `ff612b56`                | pinkie-pie, rainbow-dash      | _(none)_                              | 5   |
| 41  | Felidar Retreat                            | `sld`  | 2378  | `be40b50f`                | katsuichi, miyamoto-usagi     | _(none)_                              | 4   |
| 42  | Sunforger                                  | `sld`  | 2381  | `40f9b263`                | usagi-yojimbo                 | _(none)_                              | 4   |
| 43  | Disdainful Stroke                          | `pcbb` | 2     | `11c94b70`                | cowboy-bebop                  | standardshowdown                      | 5   |
| 44  | Lightning Strike                           | `pcbb` | 4     | `a38033fc`                | cowboy-bebop                  | standardshowdown                      | 5   |
| 45  | Nira, Hellkite Duelist                     | `phtr` | 3     | `ee439f3b`                | duel-masters                  | _(none)_                              | 5   |
| 46  | Optimus Prime, Inspiring Leader            | `ph18` | 2     | `d6eeaf56`                | autobot-symbol, optimus-prime | _(none)_                              | 5   |
| 47  | Nerf War                                   | `h17`  | 2     | `618cabf4`                | nerf-darts                    | convention                            | 5   |
| 48  | Robot Chicken                              | `pcel` | 6     | `0a0924af`                | robot-chicken                 | event                                 | 5   |
| 49  | Mr. Monopoly, On the Go                    | `ph23` | 1     | `1eb82ce6`                | monopoly                      | _(none)_                              | 5   |
| 50  | Command Tower                              | `sld`  | 7097  | `696de3a3`                | fallout-universe              | sldbonus, boosterfun                  | 5   |
| 51  | Soulmates                                  | `cmb1` | 84    | `80bbc4f2`                | pusheen                       | playtest                              | 6   |

### 4.1 Sample category counts

| category                                | sample rows | population rows |
| --------------------------------------- | ----------: | --------------: |
| 1 — D&D / Forgotten Realms              |          20 |           2,351 |
| 2 — Romance of the Three Kingdoms       |           8 |             348 |
| 3 — licensed, other `promo_types` token |           4 |              39 |
| 4 — licensed, `flavor_name` only        |           3 |              24 |
| 5 — licensed, no structured marker      |          11 |              37 |
| 6 — depiction, not licence              |           5 |              21 |
| 7 — join artifact                       |           0 |               0 |
| **total**                               |      **51** |       **2,820** |

### 4.2 Spot-checks against live Scryfall

Twenty-one individual card lookups plus one `set:slx` search — tens of
requests, not thousands, and no iteration over the catalogue. Every
lookup confirmed our stored copy: **not one of the 21 carries
`universesbeyond` upstream either**, so the delta is genuine Scryfall
behaviour and not stale ingestion.

| card                                  | what was checked               | result                                                                               |
| ------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------ |
| `clb` 212 Acolyte of Bahamut          | is D&D marked UB upstream?     | `promo_types: null`, `set_type: draft_innovation` — no                               |
| `afr` 155 Meteor Swarm                | same                           | `promo_types: null`, `security_stamp: oval` — no                                     |
| `plst` AFR-6 Cleric Class             | reprint carries the marker?    | `promo_types: null` — no                                                             |
| `ptk` 20 Shu Defender                 | is Portal Three Kingdoms UB?   | `promo_types: null`, `set_type: starter`, released 1999 — no                         |
| `iko` 373 Void Beckoner               | is the Godzilla series marked? | `godzillaseries` + `flavor_name: Spacegodzilla, Death Corona` — yes, different token |
| `vow` 343 Olivia, Crimson Bride       | is the Dracula series marked?  | `draculaseries` + `flavor_name: Sisters of the Undead` — yes, different token        |
| `prm` 80921 Yidaro                    | Godzilla promo reprint         | `promo_types: null`, `flavor_name: Godzilla, Doom Inevitable` — `flavor_name` only   |
| `sld` 2381 Sunforger                  | Usagi Yojimbo drop             | `flavor_name: The Grass-Cutting Sword`                                               |
| `sld` 7076 Big Score                  | Usagi Yojimbo drop             | artist **Stan Sakai** — licensed, no marker                                          |
| `sld` 7097 Command Tower              | is it really Fallout?          | flavour _"Drive In, Fly Out! —Red Rocket Slogan"_ — yes, licensed, no marker         |
| `sld` 798 Discord, Lord of Disharmony | My Little Pony drop            | `promo_types: ["sldbonus"]` only                                                     |
| `pcbb` 2 Disdainful Stroke            | Cowboy Bebop drop              | `promo_types: ["standardshowdown"]` only                                             |
| `ph18` 2 Optimus Prime                | Transformers                   | `promo_types: null`, Heroes of the Realm                                             |
| `ph23` 1 Mr. Monopoly                 | Monopoly                       | `promo_types: null`, `set_type: funny`                                               |
| `mb2` 558 Bolshack Dragon             | Duel Masters                   | `promo_types: ["playtest"]`                                                          |
| `sld` 63 Plains                       | licensed Godzilla, or homage?  | plain `Basic Land`, Lars Grant-West, no marker — **homage**                          |
| `sld` 66 Mountain                     | same                           | plain `Basic Land`, Grzegorz Rutkowski — **homage**                                  |
| `sld` 359 Plains                      | licensed Dracula, or homage?   | plain `Basic Land`, Donato Giancola — **homage**                                     |
| `pana` 265 Mountain                   | same                           | plain `Basic Land`, Arena promo — **homage**                                         |
| `cmb1` 84 Soulmates                   | licensed Pusheen?              | `Enchantment — Aura`, Victoria Caña, `playtest` — **homage**                         |
| `slx` 24 Rashel, Fist of Torm         | is `slx` Universes Within?     | `set_name: "Universes Within"` — **confirmed false positive**                        |
| `set:slx` (search)                    | what is in the set?            | 30 cards; 24–30 are the 2025-04-25 in-universe reskins                               |

---

## 5. The delta nobody looked for: 61 printings the Tagger misses

The original subtraction assumed the Tagger population contains the
`promo_types` population. It does not. **61 printings carry
`promo_types: universesbeyond` and are invisible to `art:external-ip`:**

| expansion                                                  | rows |
| ---------------------------------------------------------- | ---: |
| `jtla` Avatar: The Last Airbender Jumpstart Front Cards    |   45 |
| `clu` Ravnica: Clue Edition                                |   15 |
| `ftla` Avatar: The Last Airbender Beginner Box Front Cards |    1 |

Two failure modes, both structural rather than incidental. The Avatar
rows are a **recency gap** — community tagging lags new releases, and a
signal that lags is a poor primary source for a product line that ships
new UB sets several times a year. The `clu` rows (Wrench, Knife, Dining
Room, Kitchen, Library…) are Clue-branded cards that Scryfall's own
product-line marker catches and the community subtree does not, even
though `clue` **is** one of the 56 direct children of `external-ip`.

The Tagger is therefore not a superset of `promo_types`. It is a
differently-shaped set that trades 61 misses for 121 genuine additions
and 2,699 non-UB rows.

---

## 6. The decision: does the Scryfall Tagger dependency earn its place?

**No. Recommend dropping it from the unified Scryfall importer.**

The number that decides it: **82**. That is how many printings in the
entire 113,224-row catalogue are genuine third-party licensed IP that no
structured Scryfall field reaches — categories 4 and 5 combined, 0.07% of
the catalogue. Every other row in the 2,820 is either not Universes
Beyond at all (2,699), already answerable from a column we ingest today
(39), or art homage (21). And 24 of the 82 are reachable from
`flavor_name`, a structured field on the same bulk row we already parse —
which leaves **37 printings, 0.03% of the catalogue**, as the entire
return on carrying a second bulk download, a second join, and a
community-maintained taxonomy whose top-level child list changes without
notice.

Against that, the costs are concrete: 2,351 D&D printings and 348 Portal
Three Kingdoms printings would be swept into a filter labelled "Universes
Beyond", 7 Universes _Within_ printings would be labelled as their own
opposite, 21 basic lands would be labelled licensed products, and 61
genuinely-UB printings would still be missed (§5).

**What to do instead, in ascending order of effort:**

1. **`promo_types` contains `universesbeyond`** — the existing signal,
   10,407 printings, already ingested. Unchanged from PR #599 §4.2.
2. **Add `godzillaseries` and `draculaseries` to the same predicate** —
   +39 printings, zero new ingestion, one line. Both tokens live in the
   column we already store and both are wholly contained in the delta.
3. **Optionally parse `flavor_name`** — +24 printings. This is a real
   ingestion change (the field is not in `PrintingMetadataRow` today) and
   it is a heuristic, not a marker: a non-null `flavor_name` means "this
   printing has an alternate licensed name", which is a strong but not
   definitional UB signal. Worth it only if someone wants the Godzilla
   promo reprints specifically.
4. **Leave the last 37 to the human channel.** `CardTagVote` on the
   `external-ip` `Tag` already resolves and already indexes to
   Elasticsearch (PR #599 §7.3b). Thirty-seven printings is well inside
   what human tagging handles, and it is exactly the kind of disputable,
   edge-case claim the vote system exists for.

**What would falsify this recommendation.** Any one of the following, and
each is checkable:

- **The owner wants D&D and Portal Three Kingdoms in the filter.** If
  "external IP" is read the way `reason_tags.py`'s own docstring reads it
  — _"art drawn from an external IP (crossover / licensed property)
  rather than original Magic art"_ — then Forgotten Realms art arguably
  qualifies even though Wizards owns it, and the Tagger becomes the only
  signal that supplies 2,699 of those rows. **This is a definitional
  ruling, not a measurement, and it inverts the recommendation
  completely.** It is the single question worth putting to the owner
  before anything is built.
- **The 37 grows.** It is 0.03% today. If Wizards keeps shipping
  unmarked one-off licensed drops at a rate that pushes this into the
  hundreds, the human channel stops being adequate.
- **`promo_types` stops being reliable upstream.** Only our stored copy
  plus 21 upstream spot-checks were measured; a systematic upstream audit
  was not performed and remains **not established**, exactly as PR #599
  left it.

---

## 7. Two stale docstrings, noted in passing

PR #599 §10 item 5 already established that `security_stamp` is not a
deterministic UB marker and that `views.py:2947` and `reason_tags.py:81`
are stale in naming it as the future authoritative signal. This
investigation adds a direct measurement rather than a new argument: across
the 2,820 delta printings the `security_stamp` distribution is
`null` 1,296 / `oval` 1,279 / `arena` 237 / `heart` 8 — **no triangle at
all**, and `oval` (the ordinary Magic stamp) is the modal value. Likewise
`set_type` spreads across 15 values led by `draft_innovation` 704,
`promo` 468 and `expansion` 462. Neither field separates this population.
No recommendation here depends on either; the two docstrings should be
corrected to name `promo_types`.

---

## 8. Every number, with its query

All DB figures via `docker exec mpcautofill_django python manage.py shell`,
read-only. No `.save()`, `.create()`, `.delete()`, `.update()` or `bulk_*`
was issued, and no management command was run — including
`import_external_ip_tags --dry-run`, which writes a `PilotRunLedger` row
before branching and was therefore treated as a write.

| finding                                   | how                                                                                   | result                                                                             |
| ----------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Tagger subtree                            | BFS from slug `external-ip` over `art-tags-20260729090120.jsonl.gz` (11,429 rows)     | 2,799 tags, 8,332 illustrations — matches PR #599                                  |
| `P`                                       | `CanonicalPrintingMetadata.objects.filter(promo_types__contains=['universesbeyond'])` | 10,407                                                                             |
| `T_db`                                    | intersect 8,332 illustrations against `illustration_id` (112,431 non-null)            | 13,166                                                                             |
| `T_json`                                  | `build_illustration_index(default_cards.json)` → `CanonicalCard.identifier`           | 13,168                                                                             |
| join-path agreement                       | `T_db − T_json` / `T_json − T_db`                                                     | 0 / 2 (both back-face)                                                             |
| illustrations with no `default_cards` row | index miss over the 8,332                                                             | 2                                                                                  |
| **the delta**                             | `T_db − P`                                                                            | **2,820**                                                                          |
| **the reverse delta**                     | `P − T_db`                                                                            | **61** (`jtla` 45, `clu` 15, `ftla` 1)                                             |
| intersection                              | `T_db ∩ P`                                                                            | 10,346                                                                             |
| join-artifact test                        | of the 1,490 delta illustrations, how many also sit on a `P` printing                 | **0**                                                                              |
| IP-family mapping                         | close each of the 56 `external-ip` children's own subtree; assign leaf → family       | every delta row → exactly 1 family; 0 unclassifiable                               |
| family counts                             | `Counter` over the 2,820                                                              | D&D 2,351; RotTK 348; godzilla 49; dracula 31; MLP 21; usagi 6; bebop 5; others ≤2 |
| `godzillaseries` / `draculaseries`        | `promo_types__contains` over the whole catalogue                                      | 21 / 18 — all inside the delta                                                     |
| `flavor_name`-only rows                   | `default_cards.json` enrichment of all 2,820                                          | 24                                                                                 |
| no-marker rows                            | same                                                                                  | 58 (37 licensed + 21 homage)                                                       |
| `security_stamp` over the delta           | same                                                                                  | null 1,296 / oval 1,279 / arena 237 / heart 8 — no triangle                        |
| `set_type` over the delta                 | same                                                                                  | 15 values, led by `draft_innovation` 704                                           |
| upstream spot-checks                      | 21 `GET /cards/<id>` + 1 `GET /cards/search?q=set:slx`                                | 0 of 21 carry `universesbeyond` upstream                                           |

**Not established**, stated as such rather than inferred:

1. **Whether "external IP" is meant to include Wizards-owned crossovers**
   (D&D) and public-domain sources (Romance of the Three Kingdoms). This
   is a definitional question for the owner, and it governs 2,699 of the
   2,820. §6 states plainly that a "yes" inverts the recommendation.
2. **Per-row verification of 18 of the 21 category-6 rows.** Three were
   verified upstream; the other 18 are contiguous basics from the same
   drops and are classified by structural extension.
3. **Whether `promo_types` is complete upstream.** Only our stored copy
   plus 21 spot-checks were measured — the same residual PR #599 left.
4. **Back-face artwork** beyond the 2 rows the join-path difference
   exposed, because `face_illustrations` is empty in production.
5. **Whether the 37 unmarked licensed printings are stable or growing.**
   A single snapshot was taken; no trend was measured.
