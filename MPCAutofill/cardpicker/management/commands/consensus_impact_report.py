"""
Read-only impact audit for the owner-ratified 2026-07-22 vote-weight scenario matrix (D1/D2/D3/
D4 in `cardpicker.vote_consensus.resolve_weighted_consensus`'s own docstring). DRY-RUNS the
ratified resolver over every printing/artist/tag pair with at least one vote on record and
reports how many would change PERSISTED status if `resolve_and_persist_printing`/
`resolve_and_persist_artist`/`resolve_and_persist_tag_votes` were re-run today, broken down by
transition (e.g. "resolved->unresolved"), with up to `--sample-limit` (default 20) sample
identifiers per transition.

PERFORMS ZERO WRITES, by construction: every read below goes through the plain
`resolve_printing`/`resolve_artist`/`resolve_tag` functions, never their `_and_persist_*`
counterparts, and no `.save()`/`.update()`/`.delete()` call appears anywhere in this module.
This feeds the owner's decision on a later, SEPARATELY gated recompute against the live vote
pool (docs/features/catalog-completion-plan.md) - this command itself authorizes no such
recompute and must never be run against production without that separate, explicit go-ahead.

Not yet optimized for the ~28k-vote production scale mentioned in the matrix's own Table B
note: this walks one query per card/tag pair (mirroring `resolve_tag`/`resolve_printing`/
`resolve_artist`'s own existing per-instance query shape, not the batched `get_resolved_tag_
overlay`/`get_suggested_filter_tags_overlay` shape), since it's an infrequent, read-only audit
tool rather than a hot path. A batched rewrite is worth doing before running this against the
full production vote pool if that turns out to be too slow in practice - flagged as an open
item, not solved here.
"""

from collections import Counter, defaultdict
from typing import Any

from django.core.management.base import BaseCommand

from cardpicker.artist_consensus import UNKNOWN as ARTIST_UNKNOWN
from cardpicker.artist_consensus import resolve_artist
from cardpicker.models import (
    ArtistVoteStatus,
    Card,
    CardTagVote,
    PrintingTagStatus,
    Tag,
    TagVoteStatus,
    VotePolarity,
)
from cardpicker.moderation import get_moderator_user_ids
from cardpicker.printing_consensus import NO_MATCH, resolve_printing
from cardpicker.tag_consensus import resolve_tag
from cardpicker.vote_consensus import PENDING_PRIVILEGED, is_human_backed_source

DEFAULT_SAMPLE_LIMIT = 20


def _would_be_printing_status(card: Card) -> str:
    """Mirrors `printing_consensus.resolve_and_persist_printing`'s status mapping, without the
    write."""
    result = resolve_printing(card)
    if result is None:
        return PrintingTagStatus.UNRESOLVED
    if result == NO_MATCH:
        return PrintingTagStatus.NO_MATCH
    return PrintingTagStatus.RESOLVED


def _would_be_artist_status(card: Card) -> str:
    """Mirrors `artist_consensus.resolve_and_persist_artist`'s status mapping, without the
    write (including its own CONTESTED-vs-UNRESOLVED raw-outcome-count heuristic, unchanged by
    this matrix - decision D3 only touches the tag path, see `_would_be_tag_status` below)."""
    result = resolve_artist(card)
    if result is None:
        distinct_outcomes = {
            ARTIST_UNKNOWN if is_unknown else artist_id
            for is_unknown, artist_id in card.artist_votes.values_list("is_unknown", "artist_id")
        }
        return ArtistVoteStatus.CONTESTED if len(distinct_outcomes) > 1 else ArtistVoteStatus.UNRESOLVED
    if result == ARTIST_UNKNOWN:
        return ArtistVoteStatus.UNKNOWN
    return ArtistVoteStatus.RESOLVED


def _would_be_tag_status(card: Card, tag: Tag, moderator_ids: set[int]) -> str:
    """Mirrors `tag_consensus.resolve_and_persist_tag_votes`'s status mapping, without the
    write - including decision D3's fix: CONTESTED requires more than one polarity BACKED BY A
    HUMAN-BACKED VOTE, not merely more than one polarity voted at all."""
    resolved = resolve_tag(card, tag, moderator_ids=moderator_ids)
    if resolved is PENDING_PRIVILEGED:
        return TagVoteStatus.PENDING_APPROVAL
    if resolved == VotePolarity.APPLY:
        return TagVoteStatus.RESOLVED_APPLY
    if resolved == VotePolarity.NOT_APPLICABLE:
        return TagVoteStatus.RESOLVED_REJECT
    human_backed_polarities = {
        polarity
        for polarity, source in card.tag_votes.filter(tag=tag).values_list("polarity", "source")
        if is_human_backed_source(source)
    }
    return TagVoteStatus.CONTESTED if len(human_backed_polarities) > 1 else TagVoteStatus.UNRESOLVED


def compute_consensus_impact_report(sample_limit: int = DEFAULT_SAMPLE_LIMIT) -> dict[str, Any]:
    """
    Returns `{"printing": {"checked": int, "transitions": {"before->after": count}, "samples":
    {"before->after": [identifier, ...]}}, "artist": {...same shape...}, "tag": {"checked": int,
    "transitions": {...}, "samples": {"before->after": [(identifier, tag_name), ...]}}}`.

    "before" is the currently PERSISTED status (`card.printing_tag_status`/
    `card.artist_vote_status`/`card.tag_vote_statuses.get(tag.name)` - `None` for a tag pair
    with votes but no persisted entry yet, which shouldn't normally happen but is handled
    rather than crashing on it); "after" is what the ratified resolver would produce today. A
    card/pair absent from `transitions`/`samples` (i.e. before == after) is unaffected - the
    common case, expected to be the overwhelming majority.
    """
    report: dict[str, Any] = {
        "printing": {"checked": 0, "transitions": Counter(), "samples": defaultdict(list)},
        "artist": {"checked": 0, "transitions": Counter(), "samples": defaultdict(list)},
        "tag": {"checked": 0, "transitions": Counter(), "samples": defaultdict(list)},
    }

    printing_cards = Card.objects.filter(printing_tags__isnull=False).distinct().prefetch_related("printing_tags")
    for card in printing_cards:
        report["printing"]["checked"] += 1
        before = card.printing_tag_status
        after = _would_be_printing_status(card)
        if before != after:
            key = f"{before}->{after}"
            report["printing"]["transitions"][key] += 1
            if len(report["printing"]["samples"][key]) < sample_limit:
                report["printing"]["samples"][key].append(card.identifier)

    artist_cards = Card.objects.filter(artist_votes__isnull=False).distinct().prefetch_related("artist_votes")
    for card in artist_cards:
        report["artist"]["checked"] += 1
        before = card.artist_vote_status
        after = _would_be_artist_status(card)
        if before != after:
            key = f"{before}->{after}"
            report["artist"]["transitions"][key] += 1
            if len(report["artist"]["samples"][key]) < sample_limit:
                report["artist"]["samples"][key].append(card.identifier)

    moderator_ids = get_moderator_user_ids()
    tag_ids_by_card_id: dict[int, set[int]] = defaultdict(set)
    for card_id, tag_id in CardTagVote.objects.values_list("card_id", "tag_id").distinct():
        tag_ids_by_card_id[card_id].add(tag_id)

    if tag_ids_by_card_id:
        cards_by_id = {c.pk: c for c in Card.objects.filter(pk__in=tag_ids_by_card_id.keys())}
        all_tag_ids = {tag_id for tag_ids in tag_ids_by_card_id.values() for tag_id in tag_ids}
        tags_by_id = {t.pk: t for t in Tag.objects.filter(pk__in=all_tag_ids)}

        for card_id, tag_ids in tag_ids_by_card_id.items():
            tag_pair_card = cards_by_id.get(card_id)
            if tag_pair_card is None:
                continue
            for tag_id in tag_ids:
                tag = tags_by_id.get(tag_id)
                if tag is None:
                    continue
                report["tag"]["checked"] += 1
                before = tag_pair_card.tag_vote_statuses.get(tag.name)
                after = _would_be_tag_status(tag_pair_card, tag, moderator_ids)
                if before != after:
                    key = f"{before}->{after}"
                    report["tag"]["transitions"][key] += 1
                    if len(report["tag"]["samples"][key]) < sample_limit:
                        report["tag"]["samples"][key].append((tag_pair_card.identifier, tag.name))

    return report


class Command(BaseCommand):
    help = (
        "DRY-RUNS the owner-ratified 2026-07-22 vote-weight scenario matrix's consensus "
        "resolver over every printing/artist/tag pair with at least one vote on record, and "
        "reports how many would change PERSISTED status if re-resolved today, broken down by "
        "transition, with sample identifiers per transition. Performs ZERO writes - feeds the "
        "owner's decision on a later, separately-gated recompute; never run against production "
        "as an authorization to actually recompute anything."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--sample-limit",
            type=int,
            default=DEFAULT_SAMPLE_LIMIT,
            help="Max sample identifiers recorded per transition (default 20).",
        )

    def handle(self, *args: Any, **kwargs: Any) -> None:
        sample_limit = kwargs["sample_limit"]
        print(f"[DRY RUN] consensus_impact_report --sample-limit={sample_limit} - zero writes will occur.")

        report = compute_consensus_impact_report(sample_limit=sample_limit)

        for kind in ("printing", "artist", "tag"):
            section = report[kind]
            print(f"=== {kind} ({section['checked']} pair(s) checked) ===")
            if not section["transitions"]:
                print("  no transitions - dry run matches persisted state exactly.")
                continue
            for transition, count in sorted(section["transitions"].items(), key=lambda item: -item[1]):
                print(f"  {transition}: {count}")
                for sample in section["samples"][transition]:
                    print(f"    - {sample}")

        print("Dry run complete - zero writes performed.")
