"""
The `external-ip` predicate: WHICH ARTWORK is drawn from an external intellectual property
(crossover / licensed property) rather than being original Magic art.

WHAT "EXTERNAL IP" MEANS HERE, AND WHAT IT DELIBERATELY DOES NOT MEAN. Owner ruling,
2026-07-29:

    "call the tag external IP then. we are not dropping it. it needs to hit those exact
     printings Of those cards. the catalog will have many more alt art that needs appropriate
     tagging. a printing of a card that is not art:external-ip but has been printed as
     art:external-ip needs to be differentiated in this."

That settles a definitional question two prior investigations left open. `external-ip` is the
ARTWORK-ORIGIN reading - `reason_tags.NO_MATCH_REASON_TAGS`' own description, "art drawn from
an external IP (crossover / licensed property) rather than original Magic art" - and NOT the
Wizards "Universes Beyond" product line. The consequences are concrete and were both measured
before this module was written (see docs/features/external-ip.md for the full arithmetic):

  * Dungeons & Dragons / Forgotten Realms art COUNTS (2,351 printings). Wizards owns D&D and
    never branded it Universes Beyond, so `promo_types` correctly omits it - but the artwork is
    still drawn from a property that is not Magic.
  * Portal Three Kingdoms art COUNTS (348 printings). Romance of the Three Kingdoms is a
    public-domain 14th-century novel with no licence and no product line - and it is still not
    original Magic art.
  * Universes WITHIN art does NOT count (7 printings) - it is the in-universe reskin, i.e.
    original Magic art commissioned to replace licensed art. It is the literal opposite of this
    tag, and the Scryfall Tagger flags it anyway. See EXTERNAL_IP_EXCLUSIONS.

A tag named `UB` would have to answer the opposite way on the first two. This one is named
`external-ip` precisely so it does not have to.

WHY THE GRAIN IS THE ILLUSTRATION AND NOT THE PRINTING. Owner ruling, 2026-07-29: "and I say
printing but it is an illustration thing really." The tagged entity is the ARTWORK; printings
inherit the tag by carrying that artwork. Three reasons, all measured against production:

  1. IT IS THE ONLY GRAIN THAT ANSWERS THE OWNER'S DIFFERENTIATION REQUIREMENT. 1,608 oracle
     groups in the live catalogue have BOTH an external-IP printing and an ordinary one -
     `sld` 7097 Command Tower (Fallout art) against 66 unflagged Command Towers is the shape.
     A card-grain tag gets every one of those 1,608 wrong in one direction or the other. An
     illustration-grain tag separates them with no ambiguity anywhere in the catalogue.
  2. IT COVERS MORE SURFACE FOR THE SAME DATA. 7,932 tagged illustrations reach 13,182
     printings - 1.662 printings per artwork, because 3,371 of them are reprinted.
  3. IT IS FUTURE-PROOF WITHOUT A RE-IMPORT. If a future set reprints the Fallout-art Command
     Tower, that printing carries the same `illustration_id` and inherits the tag the moment it
     is ingested - no re-derivation, no second pass over the Tagger feed, no decision to re-make.
     A per-printing boolean would have to be recomputed for every new printing forever.

THIS IS A DERIVED ATTRIBUTE, NOT A VOTE. An imported structured fact cannot be disputed by a
voter, and `vote_consensus.resolve_weighted_consensus` applies a hard `has_human_backed` gate
independent of the weight sum, so a machine-only vote channel returns `None` at ANY volume
(measured at n=1, 2, 4, 10 and 1,000 - PR #599 §2). Routing an imported fact through the vote
system therefore buys nothing and costs a channel that can never fire. The Scryfall side of
this tag is stored as `ExternalIpIllustration` rows and read directly.

THE HUMAN SIDE IS STILL A VOTE, AND IT IS A DIFFERENT POPULATION. This is a proxy catalogue:
230,770 user-uploaded images against 113,224 official printings. A custom image bearing
Warhammer art has no Scryfall printing and no Scryfall `illustration_id`, so no derived
predicate can reach it by construction - only a human can say. That channel is `CardTagVote`
-> `tag_consensus.resolve_and_persist_tag_votes` -> `Card.tags`, and it already works end to
end. BOTH channels write the SAME `Tag.name`, deliberately (see `reason_tags`' own comment on
that row), so `tag:external-ip` is ONE predicate over the whole catalogue rather than two names
that would fragment it permanently.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

from django.db.models import Q, QuerySet

from cardpicker.models import (
    CanonicalCard,
    CanonicalPrintingMetadata,
    Card,
    ExternalIpIllustration,
    IllustrationVoteStatus,
)

# Our own `Tag.name`. Tag.name is the immutable machine key (votes, `Card.tags`, federation
# interchange), so this string is a CONTRACT, not a label: renaming it is a data migration.
#
# DELIBERATELY THE SAME STRING AS THE `reason_tags.NO_MATCH_REASON_TAGS` ROW. Both channels -
# this derived Scryfall one and the human no-match reason strip - write into the same
# `Card.tags` array, which is what makes `tag:external-ip` a single search predicate over both
# the official-printing and the user-uploaded halves of the catalogue. `test_external_ip.py`
# pins the two against each other so they cannot drift.
#
# DUPLICATION NOTE (2026-07-29): PR #615 (`PrintingTagVote` retirement) introduces an
# `EXTERNAL_IP_TAG_NAME` in `reason_tags.py` for the same reason. Whichever lands second should
# delete its own copy and import the other's - they are pinned equal by test either way, so the
# duplication is inert until then, not a live drift risk.
EXTERNAL_IP_TAG_NAME = "external-ip"

# The Scryfall Tagger slug whose subtree defines the community's own artwork-origin taxonomy.
# Scryfall's tags documentation warns slugs may change; the BFS below fails LOUD rather than
# silently importing zero illustrations if it ever does.
EXTERNAL_IP_TAG_SLUG = "external-ip"

# The `CanonicalPrintingMetadata.promo_types` tokens that mark external IP in a column we
# ALREADY ingest. This is not a redundant second copy of the Tagger signal - it is the half of
# the union the Tagger misses (see the source arithmetic in docs/features/external-ip.md):
#
#   * `universesbeyond` - Wizards' product-line marker. 10,407 printings, 100% per-set recall on
#     every dedicated UB set. It catches 61 printings the Tagger does not, because community
#     tagging lags new releases (`jtla`/`ftla` Avatar, `clu` Ravnica: Clue Edition).
#   * `godzillaseries` (21 printings) and `draculaseries` (18) - genuine licensed third-party
#     crossovers that Scryfall marks in this same column under their own tokens rather than
#     under `universesbeyond`. Owner-ratified 2026-07-29: "godzillaseries and draculaseries is
#     an elegant solution that will help."
#
# HONEST ACCOUNTING OF WHAT THE LAST TWO TOKENS ACTUALLY ADD TODAY: zero. All 38 of their
# illustrations and all 39 of their printings are ALREADY inside the Tagger subtree (measured:
# `godzilla/dracula illustrations not already in tagger ∪ universesbeyond: 0`). They are carried
# as redundancy against Tagger drift - a community taxonomy whose top-level child list changes
# without notice - not as new coverage, and this comment exists so nobody later "discovers" that
# they contribute nothing and deletes them without knowing that was already known.
EXTERNAL_IP_PROMO_TYPES: tuple[str, ...] = ("universesbeyond", "godzillaseries", "draculaseries")


@dataclass(frozen=True)
class ExternalIpExclusion:
    """One deliberately-removed illustration, with the reason it is wrong. Never a bare filter."""

    illustration_id: uuid.UUID
    printings: str
    reason: str


# ---------------------------------------------------------------------------------------------
# EXCLUSION 1 - UNIVERSES WITHIN. Hard-excluded, not a judgement call.
#
# `slx` 24-30 are the set "Universes Within" (verified by live Scryfall lookup: `set_name`
# "Universes Within", released 2025-04-25). Universes Within is the IN-UNIVERSE RESKIN - Wizards
# commissioning ORIGINAL Magic art to replace licensed art on a mechanically identical card. It
# is the exact opposite of what this tag asserts, and the Scryfall Tagger flags all seven anyway
# (each is `inT`, none carries any `promo_types` marker - `["instore"]` only).
#
# EXCLUDABLE PRECISELY: each of the seven has its own `illustration_id`, shared with no other
# printing in the catalogue (measured: `UW illustrations also on any non-slx printing: {}`), so
# removing them removes exactly 7 printings and nothing else.
# ---------------------------------------------------------------------------------------------
EXTERNAL_IP_EXCLUSIONS: tuple[ExternalIpExclusion, ...] = (
    ExternalIpExclusion(
        uuid.UUID("a587dd2d-0549-44b7-87bd-530a0fa44816"), "slx 24 Rashel, Fist of Torm", "Universes Within reskin"
    ),
    ExternalIpExclusion(
        uuid.UUID("cac0151a-4613-4469-b741-aa441200dcc6"), "slx 25 Mathise, Surge Channeler", "Universes Within reskin"
    ),
    ExternalIpExclusion(
        uuid.UUID("8f16cf14-6cd9-474c-b3d4-5bc771ae1b2c"),
        "slx 26 Evin, Waterdeep Opportunist",
        "Universes Within reskin",
    ),
    ExternalIpExclusion(
        uuid.UUID("aea17449-d78d-45ae-85c3-f4e8011e55d3"),
        "slx 27 Jurin, Leading the Charge",
        "Universes Within reskin",
    ),
    ExternalIpExclusion(
        uuid.UUID("7a731981-b71a-4007-ad4a-2e8cbdba012c"), "slx 28 Themberchaud", "Universes Within reskin"
    ),
    ExternalIpExclusion(
        uuid.UUID("38835875-142b-47fb-9dc3-bb1ae2b269a5"),
        "slx 29 Casal, Lurkwood Pathfinder // Casal, Pathbreaker Owlbear",
        "Universes Within reskin",
    ),
    ExternalIpExclusion(
        uuid.UUID("ae8e3bec-fcb7-47a8-a19b-8ec8a8862c16"),
        "slx 30 Bohn, Beguiling Balladeer",
        "Universes Within reskin",
    ),
)

# ---------------------------------------------------------------------------------------------
# EXCLUSION 2 - HOMAGE ART. A JUDGEMENT CALL, FLAGGED FOR THE OWNER RATHER THAN DECIDED SILENTLY.
#
# 11 illustrations across 21 printings that the Tagger community tagged `godzilla`/`mothra`/
# `hedorah`/`rodan`/`count-dracula`/`bram-stoker-s-dracula`/`pusheen` because the art DEPICTS a
# kaiju or a vampire - not because the card is a licensed product. Twenty are basic lands
# (`sld` 63-67 and `pana` 236-240 for Godzilla; `sld` 359-363 and `pana` 262-266 for Dracula -
# note the `sld` and `pana` runs SHARE their artwork, which is why 21 printings collapse to 11
# illustrations at this grain), and the twenty-first is `cmb1` 84 Soulmates, a Mystery Booster
# playtest card. Verified by live lookup on five of them: plain `Basic Land` type lines, no
# `promo_types`, no `flavor_name`, no licensed branding of any kind.
#
# THE ARGUMENT EACH WAY, because this is genuinely arguable under the artwork-origin reading:
#   FOR EXCLUDING (this module's recommendation): the ruling's own words are "art drawn from an
#     external IP". Art that ALLUDES to Godzilla is not drawn FROM Godzilla - it is original
#     Magic art by a Magic artist (Lars Grant-West, Grzegorz Rutkowski, Donato Giancola,
#     Victoria Caña) commissioned for a Magic product, and no licence exists. If a user filters
#     `tag:external-ip` looking for licensed crossovers, a Rutkowski Mountain is a false hit.
#   FOR KEEPING: a user filtering `tag:external-ip` to find "cards that look like they come from
#     somewhere else" would arguably WANT the kaiju Mountain, and the Tagger community - whose
#     judgement this whole subtree rests on - decided it belonged.
#
# The switch below is the single line that decides it. It is a plain module constant rather than
# a Django setting on purpose: this is a taxonomy decision that should be visible in a diff and
# reviewable, not an environment knob that can differ silently between deployments.
# ---------------------------------------------------------------------------------------------
EXCLUDE_HOMAGE_ILLUSTRATIONS: bool = True

EXTERNAL_IP_HOMAGE_EXCLUSIONS: tuple[ExternalIpExclusion, ...] = (
    ExternalIpExclusion(
        uuid.UUID("84d1a5f2-ba0a-4507-9885-f3ee9c53b4ea"),
        "sld 63 Plains / pana 236 Plains",
        "homage: basic land depicting Godzilla/Mothra, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("8405a137-f18c-435e-8af6-c5657acbeeed"),
        "sld 64 Island / pana 237 Island",
        "homage: basic land depicting Godzilla, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("8da1313a-b43b-4039-8e8b-d0d5721c8037"),
        "sld 65 Swamp / pana 238 Swamp",
        "homage: basic land depicting Godzilla/Hedorah, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("7c36ba45-a86a-4760-b654-fae1b83b6fe8"),
        "sld 66 Mountain / pana 239 Mountain",
        "homage: basic land depicting Godzilla/Rodan, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("ea87bafb-d278-488d-9de4-6b3529e7b1cb"),
        "sld 67 Forest / pana 240 Forest",
        "homage: basic land depicting Godzilla, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("fc9e97c2-d841-4d30-af8b-c545ec03b089"),
        "sld 359 Plains / pana 262 Plains",
        "homage: basic land depicting Count Dracula, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("3fdf7908-fbfd-45bf-acec-76d84f82f319"),
        "sld 360 Island / pana 263 Island",
        "homage: basic land depicting Bram Stoker's Dracula, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("af331df1-f4b5-4da2-bf20-4fbf4d722dc4"),
        "sld 361 Swamp / pana 264 Swamp",
        "homage: basic land depicting Bram Stoker's Dracula, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("baf083eb-2ef1-4acc-b082-22781bcb183a"),
        "sld 362 Mountain / pana 265 Mountain",
        "homage: basic land depicting Count Dracula, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("75bd58f2-e446-4241-9826-6513dbc862ae"),
        "sld 363 Forest / pana 266 Forest",
        "homage: basic land depicting Count Dracula, not licensed art",
    ),
    ExternalIpExclusion(
        uuid.UUID("80bbc4f2-ad36-4144-8cd4-b4dcbf6ec825"),
        "cmb1 84 Soulmates",
        "homage: playtest card depicting Pusheen, not licensed art",
    ),
)


def excluded_illustration_ids(*, exclude_homages: Optional[bool] = None) -> dict[uuid.UUID, ExternalIpExclusion]:
    """
    The named exclusion list, as a lookup. `exclude_homages=None` means "use the module's own
    `EXCLUDE_HOMAGE_ILLUSTRATIONS` decision"; tests pass it explicitly so both sides of the open
    judgement call stay exercised regardless of which way the constant currently points.
    """
    if exclude_homages is None:
        exclude_homages = EXCLUDE_HOMAGE_ILLUSTRATIONS
    entries = list(EXTERNAL_IP_EXCLUSIONS) + (list(EXTERNAL_IP_HOMAGE_EXCLUSIONS) if exclude_homages else [])
    return {entry.illustration_id: entry for entry in entries}


# =============================================================================================
# SOURCE 1 - the Scryfall Tagger `art:external-ip` subtree.
# =============================================================================================


def _iter_tag_rows(tags_path: Path) -> Iterator[dict]:
    """
    Tolerant line reader over the Tagger `art_tags` bulk file, shared by both passes.
    Malformed rows are skipped rather than aborting the import - the same tolerance
    `printing_metadata_import._parse_rows` applies to the card bulk file.
    """
    from cardpicker.integrations.game import scryfall_bulk_data

    for line in scryfall_bulk_data.iter_json_lines(tags_path):
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(row, dict) and "id" in row and "slug" in row:
            yield row


def find_external_ip_subtree(tags_path: Path) -> tuple[set[str], int]:
    """
    Pass 1: BFS from the `external-ip` slug over `child_ids` to the full set of tag ids whose
    taggings count. BFS to fixpoint rather than one level down: the Tagger hierarchy may deepen
    (a child IP tag gaining its own children) and the closure is free once `child_ids` are in
    memory. Only LEAF tags carry direct taggings per Scryfall's own tags documentation, so a
    one-level traversal would silently under-collect the moment the taxonomy grows.

    Raises `RuntimeError` if the slug is absent. That is deliberate: Scryfall warns that Tagger
    slugs are not permanent identifiers, and a renamed slug must fail LOUD rather than quietly
    importing zero illustrations and reading as "nothing is external IP any more".

    Returns (subtree tag ids, total tag rows parsed).
    """
    slug_by_id: dict[str, str] = {}
    child_ids_by_id: dict[str, list[str]] = {}
    tags_seen = 0
    for row in _iter_tag_rows(tags_path):
        tags_seen += 1
        slug_by_id[row["id"]] = row["slug"]
        child_ids_by_id[row["id"]] = list(row.get("child_ids") or [])

    root_id = next((tag_id for tag_id, slug in slug_by_id.items() if slug == EXTERNAL_IP_TAG_SLUG), None)
    if root_id is None:
        raise RuntimeError(
            f"Tag slug {EXTERNAL_IP_TAG_SLUG!r} not found in {tags_path} ({tags_seen} tags parsed) - Scryfall's own "
            "tags documentation warns that Tagger slugs may change over time; check tagger.scryfall.com for the "
            "tag's current slug before re-running rather than treating an empty import as a real result."
        )

    subtree = {root_id}
    frontier = [root_id]
    while frontier:
        next_frontier = []
        for tag_id in frontier:
            for child_id in child_ids_by_id.get(tag_id, []):
                if child_id not in subtree:
                    subtree.add(child_id)
                    next_frontier.append(child_id)
        frontier = next_frontier
    return subtree, tags_seen


def collect_tagged_illustrations(tags_path: Path, subtree: set[str]) -> dict[uuid.UUID, set[str]]:
    """
    Pass 2: `{illustration_id: {tagger slug, ...}}` for every illustration tagged by any tag in
    the subtree. Kept separate from pass 1 so pass 1 never holds the (far larger) taggings
    payload in memory. The slugs are retained as PROVENANCE - "why is this artwork flagged" is
    the first question anyone reviewing a false positive asks, and re-deriving it means
    re-downloading and re-parsing the whole feed.
    """
    tagged: dict[uuid.UUID, set[str]] = {}
    for row in _iter_tag_rows(tags_path):
        if row["id"] not in subtree:
            continue
        for tagging in row.get("taggings") or []:
            raw = (tagging or {}).get("illustration_id")
            if not raw:
                continue
            try:
                illustration_id = uuid.UUID(str(raw))
            except (ValueError, AttributeError):
                continue
            tagged.setdefault(illustration_id, set()).add(row["slug"])
    return tagged


# =============================================================================================
# SOURCE 2 - `promo_types`, already ingested, read straight from the DB.
# =============================================================================================


def _promo_types_q() -> Q:
    """`promo_types` is a JSONField, so this is an OR of containment terms, not `__overlap`."""
    q = Q()
    for token in EXTERNAL_IP_PROMO_TYPES:
        q |= Q(promo_types__contains=[token])
    return q


def promo_type_illustration_ids() -> set[uuid.UUID]:
    """
    Every distinct `illustration_id` carried by a printing whose `promo_types` names one of
    `EXTERNAL_IP_PROMO_TYPES`. This is the LIFT of a printing-grain column to illustration grain,
    and it is not merely lossless - it is a net GAIN of 18 printings, measured. The Godzilla- and
    Dracula-series promo REPRINTS (`prm` 80921 Yidaro and 17 siblings) carry the licensed art but
    NO `promo_types` at all; they share their `illustration_id` with the marked `iko`/`vow`
    printing, so the lift reaches them and the column alone does not.

    Those 18 are also the only illustrations in the catalogue whose printings disagree about the
    `promo_types` predicate (18 of 50,828). Every one of them resolves in the direction of MORE
    coverage, never less, which is why the disagreement is a reason to prefer this grain rather
    than an obstacle to it.
    """
    return {
        row
        for row in CanonicalPrintingMetadata.objects.filter(_promo_types_q())
        .filter(illustration_id__isnull=False)
        .values_list("illustration_id", flat=True)
    }


def promo_type_printings_without_illustration() -> QuerySet[CanonicalPrintingMetadata]:
    """
    The printings this predicate CANNOT reach at illustration grain, because Scryfall gives them
    no `illustration_id` at all. Measured against production: 45 rows, all in `jtla` (Avatar: The
    Last Airbender Jumpstart Front Cards) - pack front cards that carry an `art_crop` image URL
    but no illustration identity. Every other `promo_types`-marked printing in the catalogue has
    one (`clu` 15/15, `ftla` 10/10, `universesbeyond` 10,362 of 10,407).

    STATED AS A REAL GAP IN THE MODEL, NOT PAPERED OVER: an artwork-keyed fact cannot be stored
    for an artwork with no key. These 45 are therefore flagged by a LIVE COLUMN TERM in
    `external_ip_printing_q()` rather than by an `ExternalIpIllustration` row, and they are the
    only printings in the catalogue for which the derived tag is not inherited-by-artwork. If
    Scryfall ever assigns those rows illustration ids, they join the normal path with no code
    change; until then the fallback is narrow, named, and countable.
    """
    return CanonicalPrintingMetadata.objects.filter(_promo_types_q()).filter(illustration_id__isnull=True)


# =============================================================================================
# THE UNION.
# =============================================================================================


@dataclass
class ExternalIpUnion:
    """The union's contents AND its arithmetic - counts are carried, never re-derived by a reader."""

    illustration_ids: set[uuid.UUID] = field(default_factory=set)
    tagger_slugs: dict[uuid.UUID, set[str]] = field(default_factory=dict)
    promo_illustration_ids: set[uuid.UUID] = field(default_factory=set)
    tagger_illustration_ids: set[uuid.UUID] = field(default_factory=set)
    excluded: dict[uuid.UUID, ExternalIpExclusion] = field(default_factory=dict)
    tags_seen: int = 0
    subtree_tag_count: int = 0
    tagger_illustrations_absent_from_catalogue: int = 0
    promo_printings_without_illustration: int = 0

    @property
    def tagger_only(self) -> set[uuid.UUID]:
        return self.tagger_illustration_ids - self.promo_illustration_ids

    @property
    def promo_only(self) -> set[uuid.UUID]:
        return self.promo_illustration_ids - self.tagger_illustration_ids

    @property
    def both(self) -> set[uuid.UUID]:
        return self.tagger_illustration_ids & self.promo_illustration_ids

    def sources_for(self, illustration_id: uuid.UUID) -> list[str]:
        sources = []
        if illustration_id in self.tagger_illustration_ids:
            sources.append("scryfall-tagger")
        if illustration_id in self.promo_illustration_ids:
            sources.append("promo-types")
        return sources


def build_external_ip_union(
    tags_path: Path,
    *,
    exclude_homages: Optional[bool] = None,
    restrict_to_catalogue: bool = True,
) -> ExternalIpUnion:
    """
    The whole predicate, in one function, at illustration grain.

        union = (Tagger `art:external-ip` subtree) ∪ (`promo_types` ∈ EXTERNAL_IP_PROMO_TYPES)
                minus the named exclusion list

    NEITHER SOURCE IS A SUPERSET OF THE OTHER, which is why this is a union and not a choice.
    Measured against production on 2026-07-29: 1,452 illustrations are Tagger-only, 16 are
    `promo_types`-only, 6,464 are in both. The `promo_types`-only side is not noise - it is the
    Avatar and Clue Edition releases the community has not tagged yet, and a signal that lags new
    releases cannot be the sole source for a property line that ships several sets a year.

    `restrict_to_catalogue=True` drops the 416 tagged illustrations that no printing in our
    catalogue carries. They are not errors (art-series-only illustrations, non-English-only
    printings), they are simply unreachable, and storing them would inflate every count with rows
    that can never match anything.
    """
    subtree, tags_seen = find_external_ip_subtree(tags_path)
    tagged = collect_tagged_illustrations(tags_path, subtree)

    union = ExternalIpUnion(tags_seen=tags_seen, subtree_tag_count=len(subtree))
    tagger_ids = set(tagged)
    if restrict_to_catalogue:
        catalogue = set(
            CanonicalPrintingMetadata.objects.filter(illustration_id__isnull=False)
            .values_list("illustration_id", flat=True)
            .distinct()
        )
        union.tagger_illustrations_absent_from_catalogue = len(tagger_ids - catalogue)
        tagger_ids &= catalogue

    union.tagger_illustration_ids = tagger_ids
    union.promo_illustration_ids = promo_type_illustration_ids()
    union.promo_printings_without_illustration = promo_type_printings_without_illustration().count()
    union.excluded = excluded_illustration_ids(exclude_homages=exclude_homages)

    union.illustration_ids = (union.tagger_illustration_ids | union.promo_illustration_ids) - set(union.excluded)
    union.tagger_slugs = {
        illustration_id: slugs for illustration_id, slugs in tagged.items() if illustration_id in union.illustration_ids
    }
    return union


# =============================================================================================
# READERS. Everything below reads the STORED union; none of it touches the Tagger feed.
# =============================================================================================


def external_ip_printing_q(prefix: str = "") -> Q:
    """
    The printing-grain read predicate, as a `Q` so it composes into any queryset that can reach
    `CanonicalPrintingMetadata`. `prefix` is the ORM path to that model from the queryset's own
    model (e.g. `"printing_metadata__"` from `CanonicalCard`).

    TWO TERMS, AND THE SECOND ONE IS NARROW ON PURPOSE:

      1. the printing's `illustration_id` has an `ExternalIpIllustration` row. This is the whole
         predicate for 13,182 of 13,227 printings, and it is the term that gives reprints their
         tag for free - a new printing of an already-flagged artwork matches on the day it is
         ingested, with no re-import.
      2. the printing has NO `illustration_id` AND its `promo_types` names one of our tokens.
         This exists ONLY for the 45 `jtla` rows Scryfall gives no illustration identity (see
         `promo_type_printings_without_illustration`). It is deliberately gated on
         `illustration_id IS NULL` so it can never become a second, silently-diverging source of
         truth for printings that DO have an artwork key - those are governed by term 1 and by
         the exclusion list, and a printing excluded at illustration grain must not sneak back in
         through its column.
    """
    stored = ExternalIpIllustration.objects.values("illustration_id")
    by_artwork = Q(**{f"{prefix}illustration_id__in": stored})

    promo_tokens = Q()
    for token in EXTERNAL_IP_PROMO_TYPES:
        promo_tokens |= Q(**{f"{prefix}promo_types__contains": [token]})
    no_artwork_key = Q(**{f"{prefix}illustration_id__isnull": True})

    return by_artwork | (no_artwork_key & promo_tokens)


def external_ip_printings() -> QuerySet[CanonicalCard]:
    """Every `CanonicalCard` (Scryfall printing) the derived predicate flags."""
    return CanonicalCard.objects.filter(external_ip_printing_q(prefix="printing_metadata__")).distinct()


def get_external_ip_card_overlay(card_ids: Iterable[int]) -> set[int]:
    """
    The card ids among `card_ids` that the DERIVED channel says depict external-IP artwork -
    `{card_id, ...}` rather than a polarity map, because a derived attribute has no NOT_APPLICABLE
    to express (absence IS the negative; see this module's docstring on why this is not a vote).

    TWO CARD -> ARTWORK BRIDGES, BOTH ILLUSTRATION-KEYED:

      1. `Card.canonical_card` - the CONFIRMED ingestion-time indexing match, populated on 19,484
         cards today. 3,833 of them reach an illustration in the union.
      2. `Card.inferred_illustration_id` - the illustration-consensus outcome from PR #573
         (merged as migration `0098_card_illustration_consensus_fields`), which pools byte-
         identical images by md5 identity group. This is the propagation path for the owner's
         "the catalog will have many more alt art that needs appropriate tagging": once a human
         or a calculator establishes which artwork an uploaded image depicts, that image inherits
         the artwork's external-IP status with no second vote and no second decision. It is
         currently zero-population (the field is on master but not yet on the deployed image), so
         this term contributes nothing today and costs one indexed lookup - it is here so the
         design does not FORECLOSE the propagation, exactly as instructed, not because it fires.

    Gated on `illustration_vote_status == RESOLVED` even though the field is documented as NULL
    for every other status: relying on a documented invariant that a future write path could
    break, when re-stating it costs one term, is the shape of bug this repo keeps a corrections
    log about.

    HUMAN VOTES ARE NOT CONSULTED HERE. `tag_consensus.resolve_and_persist_tag_votes` owns that
    channel and writes the same `Tag.name` into the same `Card.tags` array; the two are merged at
    the call site (`sources.update_database.bulk_sync_objects`), human last, so a resolved human
    NOT_APPLICABLE can always overrule a derived APPLY on a specific image.
    """
    card_ids = list(card_ids)
    if not card_ids:
        return set()
    stored = ExternalIpIllustration.objects.values("illustration_id")
    confirmed = Q(canonical_card__isnull=False) & external_ip_printing_q(prefix="canonical_card__printing_metadata__")
    inferred = Q(illustration_vote_status=IllustrationVoteStatus.RESOLVED) & Q(inferred_illustration_id__in=stored)
    return set(
        Card.objects.filter(pk__in=card_ids).filter(confirmed | inferred).values_list("pk", flat=True).distinct()
    )


def merge_external_ip_tag(tags: Iterable[str], applies: bool) -> list[str]:
    """
    The one place `EXTERNAL_IP_TAG_NAME` is added to or removed from a tag list, so the derived
    channel's merge rule lives once rather than at each call site.

    ASYMMETRIC ON PURPOSE: a derived APPLY adds the tag, but a derived non-match does NOT remove
    one that is already there. The derived channel only ever knows about official printings; a
    tag on a card it does not flag may have come from the human `CardTagVote` channel, which is
    authoritative for exactly the population this one cannot see (custom art with no Scryfall
    printing). Removing it would let a re-scan silently delete a human judgement - the failure
    `get_resolved_tag_overlay` was added to `bulk_sync_objects` to prevent in the first place.
    """
    merged = set(tags)
    if applies:
        merged.add(EXTERNAL_IP_TAG_NAME)
    return sorted(merged)


__all__ = [
    "EXTERNAL_IP_TAG_NAME",
    "EXTERNAL_IP_TAG_SLUG",
    "EXTERNAL_IP_PROMO_TYPES",
    "EXCLUDE_HOMAGE_ILLUSTRATIONS",
    "EXTERNAL_IP_EXCLUSIONS",
    "EXTERNAL_IP_HOMAGE_EXCLUSIONS",
    "ExternalIpExclusion",
    "ExternalIpUnion",
    "excluded_illustration_ids",
    "find_external_ip_subtree",
    "collect_tagged_illustrations",
    "promo_type_illustration_ids",
    "promo_type_printings_without_illustration",
    "build_external_ip_union",
    "external_ip_printing_q",
    "external_ip_printings",
    "get_external_ip_card_overlay",
    "merge_external_ip_tag",
]
