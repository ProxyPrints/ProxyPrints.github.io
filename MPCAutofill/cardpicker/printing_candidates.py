from typing import Iterable, Optional

import Levenshtein

from django.db.models import F, Q, QuerySet

from cardpicker.models import CanonicalCard, Card
from cardpicker.search.sanitisation import to_searchable

CANDIDATE_QUERY_LIMIT = 200
CANDIDATE_RESULT_LIMIT = 50


def find_candidates_by_name(query: str) -> "QuerySet[CanonicalCard]":
    """
    Finds `CanonicalCard` rows whose name contains every word in `query`, matched
    independently rather than as one contiguous substring, so punctuation differences
    between the query and the stored name (which `to_searchable` strips from `query`
    but not from the stored `CanonicalCard.name` being matched against) don't prevent
    an otherwise-correct match.
    """
    words = to_searchable(query).split()
    if not words:
        return CanonicalCard.objects.none()
    filters = Q()
    for word in words:
        filters &= Q(name__icontains=word)
    return CanonicalCard.objects.select_related("expansion", "artist", "printing_metadata").filter(filters)


def rank_candidates_by_confidence(candidates: Iterable[CanonicalCard], query: str) -> list[CanonicalCard]:
    """
    Orders candidates by Levenshtein similarity of their name to `query` (both passed
    through the same `to_searchable` normalisation already used for the main card
    search, so punctuation differences don't affect the score), highest confidence
    first - so the printing a voter is actually looking for surfaces at the top of the
    list instead of in whatever order the database happened to return rows.
    """
    normalised_query = to_searchable(query)
    return sorted(
        candidates,
        key=lambda candidate: Levenshtein.ratio(normalised_query, to_searchable(candidate.name)),
        reverse=True,
    )


def get_ranked_printing_candidates(card: Card, query: Optional[str]) -> list[CanonicalCard]:
    """
    Returns candidate printings for `card` to be tagged against, ranked so the most
    likely correct match comes first:
      - if the card already has a linked/inferred printing and no explicit `query` was
        given, every printing of that same underlying Magic card (same `canonical_id`)
        is returned. A text-similarity "confidence" score isn't meaningful here, since
        every candidate is already known to be the same card - just a different
        printing - so these are ordered by most recent printing first instead;
      - otherwise, candidates are found by matching every word of the query (or, absent
        an explicit query, the card's own `searchq`) against `CanonicalCard.name`, and
        ranked by Levenshtein similarity to that query, highest confidence first.
    """
    linked = card.canonical_card or card.inferred_canonical_card
    if linked is not None and not query:
        return list(
            CanonicalCard.objects.select_related("expansion", "artist", "printing_metadata")
            .filter(canonical_id=linked.canonical_id)
            .order_by(F("printing_metadata__released_at").desc(nulls_last=True))
        )

    effective_query = query or card.searchq
    candidates = find_candidates_by_name(effective_query)[:CANDIDATE_QUERY_LIMIT]
    return rank_candidates_by_confidence(candidates, effective_query)[:CANDIDATE_RESULT_LIMIT]
