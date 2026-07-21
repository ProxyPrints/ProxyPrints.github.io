"""
Review-queue clustering (public issue #262): groups cards routed to the human review queue
(`CardScanLog(anonymous_id=local_calculate_verdicts.SLOW_PATH_ANONYMOUS_ID,
skip_reason=local_calculate_verdicts.SLOW_PATH_TO_REVIEW_REASON)`, see that module's docstring)
by CONSERVATIVE exact-match signals only, per issue #262's own read-only measurement comment
(2026-07-21): exact `Card.content_phash` union exact `ImageEvidence.symbol_phash` union exact
normalized legal-line text - "conservative grouping... collapses 16,928 cards -> 11,802
decisions (2,208 multi-card clusters covering 7,334 cards + 9,594 singletons)".

WHAT THIS DELIBERATELY DOES NOT DO: Hamming-distance/near-duplicate clustering. The same
measurement comment proved this fails - single-linkage union-find over near-duplicate edges
(Hamming <=4 on symbol_phash) welded a 1,582-card "cluster" whose true max pairwise distance was
32 (mean 15.6), and <=8 absorbed 47.6% of the population into one cluster. Only EXACT equality
on any of the three signals ever creates an edge here - union-find over exact edges is safe
(no false transitive chaining risk: two cards either share a literal identical value or they
don't, there's no threshold to creep). Cross-SIGNAL-TYPE transitivity (A-B via content_phash,
B-C via legal text, so A/B/C end up in one cluster despite A and C sharing nothing directly) is
intentional and is exactly how issue #262's own headline number was computed - it is only
same-signal NEAR-DUPLICATE chaining that's forbidden.

Cache/compute strategy (issue #262 item 1's own ask - "pick the simplest thing that answers a
paginated API in <2s at current scale and say what you chose"): compute-on-demand, cached whole
(the full cluster list, sorted, pre-serialised) via Django's default cache for
REVIEW_CLUSTER_CACHE_TTL_SECONDS, keyed by one fixed cache key. This is safe ONLY because the
app runs a single gunicorn worker with Django's default (per-process) LocMemCache backend - see
`MPCAutofill/MPCAutofill/settings.py` (no CACHES override) and
`docker/django/Dockerfile`'s gunicorn CMD (no --workers flag, so gunicorn's own default of 1
applies) - the same assumption `views.py`'s `_printing_tag_rate_limit_rate` docstring already
relies on for its own in-process rate-limit cache. At ~17k review-queue rows this recomputes in
a fraction of a second (two bulk queries + an O(n) union-find pass, no per-card query); it would
need revisiting (a real periodic-materialization table, or a shared cache backend) well before
200k rows if this ever becomes multi-worker - noted here rather than silently assumed away.
`post_confirm_review_cluster` (views.py) bypasses this cache entirely for its own membership
check (see that view's docstring) and invalidates it on a successful confirm, so a moderator's
next list/detail fetch never shows a card that was literally just confirmed - correctness over
cache-hit-rate for a low-QPS moderator write path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from django.core.cache import cache

from cardpicker.local_calculate_verdicts import (
    SLOW_PATH_ANONYMOUS_ID,
    SLOW_PATH_TO_REVIEW_REASON,
)
from cardpicker.models import (
    Card,
    CardScanLog,
    CardTypes,
    ImageEvidence,
    PrintingTagStatus,
)

# Guardrails on the normalized-legal-line-text signal (issue #262 measurement's own mandate -
# "top-15 groups include pure OCR noise like '4'"). Both must pass for normalized text to count
# as a grouping signal at all; a card whose legal-line OCR fails either check contributes no
# text-based edge (its content_phash/symbol_phash signals, if any, are unaffected).
MIN_NORMALIZED_TEXT_LENGTH = 12
MIN_ALNUM_DENSITY = 0.5

REVIEW_CLUSTER_CACHE_KEY = "review_clusters_v1"
REVIEW_CLUSTER_CACHE_TTL_SECONDS = 300

# The three signal types a cluster's `signals` list can report - order here is also the display
# order the API returns them in (content, then set-symbol, then text), not load-bearing for
# clustering itself (union-find doesn't care what order edges are added in).
SIGNAL_TYPE_CONTENT_PHASH = "content_phash"
SIGNAL_TYPE_SYMBOL_PHASH = "symbol_phash"
SIGNAL_TYPE_LEGAL_LINE_TEXT = "legal_line_text"


def normalize_legal_line_text(raw_text: str) -> Optional[str]:
    """
    Lowercase, alphanumeric-only normalization of an `ImageEvidence.legal_line_raw_text` reading,
    or `None` if it fails either guardrail (in which case this card contributes no text-based
    edge at all - never a degraded/short one). Two independent checks, both required:

    1. Minimum length (`MIN_NORMALIZED_TEXT_LENGTH`): rejects trivially short OCR noise like "4"
       outright (the measurement's own named example).
    2. Alphanumeric density (`MIN_ALNUM_DENSITY`): rejects a raw reading that's mostly punctuation/
       symbol noise with just enough scattered alphanumeric characters to clear the length bar by
       coincidence - computed against the raw text's own non-whitespace length (not the full
       string including newlines/spacing a real multi-line legal-line reading legitimately has),
       so a genuine legal line isn't penalised for line breaks.
    """
    if not raw_text:
        return None
    normalized = re.sub(r"[^a-z0-9]", "", raw_text.lower())
    if len(normalized) < MIN_NORMALIZED_TEXT_LENGTH:
        return None
    non_whitespace = re.sub(r"\s+", "", raw_text)
    if not non_whitespace:
        return None
    density = len(normalized) / len(non_whitespace)
    if density < MIN_ALNUM_DENSITY:
        return None
    return normalized


@dataclass(frozen=True)
class CardSignals:
    """One review-queue card's own three clustering signals, plus the display fields a cluster
    member summary needs - assembled once per card, never re-derived per edge."""

    card_id: int
    identifier: str
    name: str
    small_thumbnail_url: str
    content_phash: Optional[int]
    symbol_phash: Optional[int]
    legal_line_text: Optional[str]  # already normalized+guardrailed - see normalize_legal_line_text


@dataclass(frozen=True)
class ClusterSignal:
    signal_type: str
    value: str
    member_count: int


@dataclass(frozen=True)
class ReviewClusterMember:
    identifier: str
    name: str
    small_thumbnail_url: str


@dataclass(frozen=True)
class ReviewCluster:
    cluster_id: str  # the root member's own `identifier` - stable, opaque, never a raw DB pk
    size: int
    signals: list[ClusterSignal]
    members: list[ReviewClusterMember]


class _UnionFind:
    """Plain union-find (path compression + union by rank) over an arbitrary hashable key set -
    the only clustering primitive this module uses. Deliberately generic/tiny rather than reused
    from `cardpicker.local_clustering` (that module's own union-find is over a DIFFERENT relation
    - Hamming-proximity candidate narrowing for a distinct purpose - reusing it here would borrow
    its near-duplicate-threshold machinery this module explicitly must not use)."""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}

    def add(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: int) -> int:
        self.add(x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


def _review_queue_card_ids() -> list[int]:
    """Every card currently carrying the slow-path "to-review" routing marker (see this module's
    own docstring) - the population issue #262 asks to cluster. `.distinct()` since a card can
    accumulate more than one such row across re-runs (CardScanLog is append-only)."""
    return list(
        CardScanLog.objects.filter(anonymous_id=SLOW_PATH_ANONYMOUS_ID, skip_reason=SLOW_PATH_TO_REVIEW_REASON)
        .values_list("card_id", flat=True)
        .distinct()
    )


def _eligible_review_cards() -> "list[Card]":
    """Review-queue cards that are STILL unresolved (a card the batch-confirm action already
    pushed to a resolved consensus - NO_MATCH or a real match - naturally drops out of the next
    listing, whether that resolution happened through this feature or independently through the
    ordinary vote/tagging surfaces)."""
    return list(
        Card.objects.filter(
            pk__in=_review_queue_card_ids(),
            printing_tag_status=PrintingTagStatus.UNRESOLVED,
            card_type=CardTypes.CARD,
        ).select_related("source")
    )


def _current_evidence_by_card_id(cards: "list[Card]") -> dict[int, tuple[Optional[int], str]]:
    """Bulk-fetches each card's CURRENT `ImageEvidence` row (content_hash matching that card's
    own live content_phash - an evidence row from a prior image version is never trusted, same
    freshness rule `local_calculate_verdicts.py`'s own calculators apply) and returns
    {card_id: (symbol_phash, legal_line_raw_text)}. One query total, not one per card: ordered
    so the first row seen per card_id in iteration order is its most recent, then filtered in
    Python against that card's live content_phash."""
    card_ids = [c.pk for c in cards if c.content_phash is not None]
    if not card_ids:
        return {}
    live_content_phash_by_card_id = {c.pk: c.content_phash for c in cards if c.content_phash is not None}
    result: dict[int, tuple[Optional[int], str]] = {}
    rows = (
        ImageEvidence.objects.filter(card_id__in=card_ids)
        .values("card_id", "content_hash", "symbol_phash", "legal_line_raw_text")
        .order_by("card_id", "-updated_at")
    )
    for row in rows:
        card_id = row["card_id"]
        if card_id in result:
            continue  # already took this card's most-recent row - see the ordering above
        if row["content_hash"] != live_content_phash_by_card_id[card_id]:
            continue  # stale evidence for a since-changed image - never trusted
        result[card_id] = (row["symbol_phash"], row["legal_line_raw_text"] or "")
    return result


def _collect_card_signals() -> list[CardSignals]:
    cards = _eligible_review_cards()
    evidence_by_card_id = _current_evidence_by_card_id(cards)
    signals: list[CardSignals] = []
    for card in cards:
        symbol_phash, legal_line_raw_text = evidence_by_card_id.get(card.pk, (None, ""))
        signals.append(
            CardSignals(
                card_id=card.pk,
                identifier=card.identifier,
                name=card.name,
                small_thumbnail_url=card.get_small_thumbnail_url() or "",
                content_phash=card.content_phash,
                symbol_phash=symbol_phash,
                legal_line_text=normalize_legal_line_text(legal_line_raw_text),
            )
        )
    return signals


def _build_clusters(all_signals: list[CardSignals]) -> list[ReviewCluster]:
    """The actual union-find pass: exact-match groups on each of the three signals become union
    edges (first member of a group unioned with every other member - equivalent connectivity to
    full pairwise edges within that group, cheaper to build), then clusters of size >= 2 are
    assembled and each is asked, independently, which of its OWN members share which signal
    value(s) (a cluster's `signals` list) - this is computed straight from the already-assembled
    member set, not by re-consulting the global signal-group index, so it can never disagree with
    what's actually in the cluster."""
    uf = _UnionFind()
    by_card_id = {s.card_id: s for s in all_signals}
    for s in all_signals:
        uf.add(s.card_id)

    def _union_all_sharing(key_fn: Callable[[CardSignals], Optional[object]]) -> None:
        groups: dict[object, list[int]] = {}
        for s in all_signals:
            key = key_fn(s)
            if key is None:
                continue
            groups.setdefault(key, []).append(s.card_id)
        for card_ids in groups.values():
            if len(card_ids) < 2:
                continue
            first = card_ids[0]
            for other in card_ids[1:]:
                uf.union(first, other)

    _union_all_sharing(lambda s: s.content_phash)
    _union_all_sharing(lambda s: s.symbol_phash)
    _union_all_sharing(lambda s: s.legal_line_text)

    members_by_root: dict[int, list[int]] = {}
    for s in all_signals:
        root = uf.find(s.card_id)
        members_by_root.setdefault(root, []).append(s.card_id)

    clusters: list[ReviewCluster] = []
    for root, card_ids in members_by_root.items():
        if len(card_ids) < 2:
            continue  # singletons carry no shared signal and aren't useful batch-confirm targets
        member_signals = [by_card_id[cid] for cid in card_ids]
        cluster_signals = _describe_cluster_signals(member_signals)
        # deterministic ordering: lowest card_id first, both for a stable root/cluster_id and a
        # stable member display order across repeated (re-)computations of the same population.
        member_signals.sort(key=lambda s: s.card_id)
        clusters.append(
            ReviewCluster(
                cluster_id=member_signals[0].identifier,
                size=len(member_signals),
                signals=cluster_signals,
                members=[
                    ReviewClusterMember(identifier=s.identifier, name=s.name, small_thumbnail_url=s.small_thumbnail_url)
                    for s in member_signals
                ],
            )
        )

    clusters.sort(key=lambda c: (-c.size, c.cluster_id))
    return clusters


_SIGNAL_KEY_FNS: list[tuple[str, Callable[[CardSignals], Optional[object]]]] = [
    (SIGNAL_TYPE_CONTENT_PHASH, lambda s: s.content_phash),
    (SIGNAL_TYPE_SYMBOL_PHASH, lambda s: s.symbol_phash),
    (SIGNAL_TYPE_LEGAL_LINE_TEXT, lambda s: s.legal_line_text),
]


def _describe_cluster_signals(member_signals: list[CardSignals]) -> list[ClusterSignal]:
    result: list[ClusterSignal] = []
    for signal_type, key_fn in _SIGNAL_KEY_FNS:
        groups: dict[object, int] = {}
        for s in member_signals:
            key = key_fn(s)
            if key is None:
                continue
            groups[key] = groups.get(key, 0) + 1
        for value, count in groups.items():
            if count < 2:
                continue
            result.append(ClusterSignal(signal_type=signal_type, value=str(value), member_count=count))
    return result


def compute_review_clusters() -> list[ReviewCluster]:
    """Pure (no cache read/write) full recompute - used directly by
    `post_confirm_review_cluster`'s own membership check (see that view's docstring for why it
    deliberately never trusts the cache for that check) and by `get_cached_review_clusters` below
    on a cache miss."""
    return _build_clusters(_collect_card_signals())


def get_cached_review_clusters(force_refresh: bool = False) -> list[ReviewCluster]:
    """The list/detail read path's own entry point - cached for REVIEW_CLUSTER_CACHE_TTL_SECONDS
    (see this module's docstring for why an in-process cache is safe here). `force_refresh=True`
    recomputes and re-populates the cache unconditionally (used after a confirm action, so the
    next read never shows an already-confirmed card stale)."""
    if not force_refresh:
        cached = cache.get(REVIEW_CLUSTER_CACHE_KEY)
        if cached is not None:
            return cached
    clusters = compute_review_clusters()
    cache.set(REVIEW_CLUSTER_CACHE_KEY, clusters, REVIEW_CLUSTER_CACHE_TTL_SECONDS)
    return clusters


def invalidate_review_cluster_cache() -> None:
    cache.delete(REVIEW_CLUSTER_CACHE_KEY)


def find_cluster(clusters: list[ReviewCluster], cluster_id: str) -> Optional[ReviewCluster]:
    for cluster in clusters:
        if cluster.cluster_id == cluster_id:
            return cluster
    return None


__all__ = [
    "MIN_NORMALIZED_TEXT_LENGTH",
    "MIN_ALNUM_DENSITY",
    "REVIEW_CLUSTER_CACHE_KEY",
    "REVIEW_CLUSTER_CACHE_TTL_SECONDS",
    "SIGNAL_TYPE_CONTENT_PHASH",
    "SIGNAL_TYPE_SYMBOL_PHASH",
    "SIGNAL_TYPE_LEGAL_LINE_TEXT",
    "normalize_legal_line_text",
    "CardSignals",
    "ClusterSignal",
    "ReviewClusterMember",
    "ReviewCluster",
    "compute_review_clusters",
    "get_cached_review_clusters",
    "invalidate_review_cluster_cache",
    "find_cluster",
]
