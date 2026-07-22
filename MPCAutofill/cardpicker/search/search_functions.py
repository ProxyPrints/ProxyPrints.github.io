import datetime as dt
import threading
from typing import Any, Callable, TypeVar, cast

import pycountry
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError as ElasticConnectionError
from elasticsearch_dsl.query import Bool, Match, Range, Terms

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.utils import timezone

from cardpicker.constants import NEW_CARDS_DAYS, NEW_CARDS_PAGE_SIZE
from cardpicker.documents import CardSearch
from cardpicker.models import Card, CardTypes, Source
from cardpicker.printing_consensus import ResolvedPrinting, get_resolved_printings
from cardpicker.schema_types import CardType, SearchSettings
from cardpicker.search.operator_parser import ParsedOperator
from cardpicker.search.sanitisation import to_searchable

thread_local = threading.local()  # Should only be called once per thread

# https://mypy.readthedocs.io/en/stable/generics.html#declaring-decorators
F = TypeVar("F", bound=Callable[..., Any])


class SearchExceptions:
    class ElasticsearchOfflineException(Exception):
        def __init__(self) -> None:
            self.message = "The search engine is offline."
            super().__init__(self.message)

    class IndexNotFoundException(Exception):
        def __init__(self, index: str) -> None:
            self.message = (
                f"The search index {index} does not exist. Usually, this happens because the database "
                f"is in the middle of updating - check back in a few minutes!"
            )
            super().__init__(self.message)

    class ConnectionTimedOutException(Exception):
        def __init__(self) -> None:
            self.message = "Unable to connect to the search engine (timed out)."
            super().__init__(self.message)


def get_elasticsearch_connection() -> Elasticsearch:
    if (es := getattr(thread_local, "elasticsearch", None)) is None:
        es = Elasticsearch([settings.ELASTICSEARCH_HOST], port=settings.ELASTICSEARCH_PORT)
    return es


def ping_elasticsearch() -> bool:
    return get_elasticsearch_connection().ping()


def elastic_connection(func: F) -> F:
    """
    Small function wrapper which makes elasticsearch's connection error more readable.
    """

    def wrapper(*args: Any, **kwargs: dict[str, Any]) -> F:
        try:
            return func(*args, **kwargs)
        except ElasticConnectionError:
            raise SearchExceptions.ConnectionTimedOutException

    return cast(F, wrapper)


def get_source_order(search_settings: SearchSettings) -> dict[int, int]:
    return {pk: i for i, (pk, _) in enumerate(search_settings.sourceSettings.sources) if isinstance(pk, int)}


def get_enabled_source_pks(search_settings: SearchSettings) -> list[int]:
    return [pk for (pk, enabled) in search_settings.sourceSettings.sources if isinstance(pk, int) and enabled is True]


def get_enabled_languages(search_settings: SearchSettings) -> list[str]:
    return [
        parsed_language.alpha_2
        for language in search_settings.filterSettings.languages
        if (parsed_language := pycountry.languages.get(alpha_2=language)) is not None
    ]


def get_scaled_maximum_size(search_settings: SearchSettings) -> int:
    return search_settings.filterSettings.maximumSize * 1_000_000


_OPERATOR_TO_ES_FIELD = {
    "border": "border_color",
    "frame": "frame",
    "tag": "tags",
    "set": "expansion_code",
    "lang": "language",
}


def _apply_operator_filter(s: CardSearch, parsed_filter: ParsedOperator) -> CardSearch:
    """
    Compiles one parsed search-operator token (`cardpicker.search.operator_parser.ParsedOperator`)
    into an additional, independent `.filter()` call on `s` - deliberately never merged into
    `search_settings.filterSettings`'s own request-global tag/language lists (those are shared
    across every query in an `/editorSearch` batch; mutating them here would leak one query
    line's typed operator into every other query line in the same request). Because every
    `.filter()` call on an elasticsearch_dsl `Search` already ANDs with every other one (this is
    exactly how the pre-existing dpi/size/source_pk/card_type filters below already compose),
    this reuses the SAME ES fields the existing structured-filter mechanisms target
    (tag*s*/expansion_code/language) without needing to reuse their exact Python plumbing -
    `tag:`/`set:`/`lang:` land on the identical field `includesTags`/`expansion_code`/
    `languages` would, they just arrive via their own filter clause. A blank operator value
    (e.g. a bare `artist:""`) is a no-op rather than an accidental empty-string term match.
    """
    value = parsed_filter.value
    if not value:
        return s

    if parsed_filter.operator == "artist":
        # `.filter()`, not `.query()` - this must compose with every other constraint via AND
        # the same way the rest of this function's filters do, and must never affect relevance
        # scoring (that's the free-text `searchq_fuzzy`/`searchq_precise` match's job alone).
        artist_match = Match(artist_text={"query": value, "operator": "AND"})
        return s.filter(Bool(must_not=artist_match)) if parsed_filter.negated else s.filter(artist_match)

    es_field = _OPERATOR_TO_ES_FIELD.get(parsed_filter.operator)
    if es_field is None:
        # unreachable for a `ParsedOperator` produced by `operator_parser.parse_query` - it only
        # ever emits operators from its own known-alias table - but fails safe (no-op) rather
        # than raising, so a future operator added to the parser without a matching wiring entry
        # here degrades to "filter silently not applied" instead of a 500.
        return s

    if parsed_filter.operator == "set":
        # matches `expansion_code`'s own pre-existing `.upper()` term-filter convention above.
        term_value = value.upper()
    elif es_field in ("border_color", "frame", "language"):
        # these three fields are lowercased at index time (Card.get_border_color/get_frame) or
        # via `language`'s pre-existing `precise_analyser`/`get_enabled_languages` convention -
        # lowercasing the query value here is what makes `BORDER:Black`/`Lang:EN` match.
        term_value = value.lower()
    else:
        term_value = value

    if parsed_filter.negated:
        return s.filter(Bool(must_not=Terms(**{es_field: [term_value]})))
    return s.filter(Bool(should=Terms(**{es_field: [term_value]}), minimum_should_match=1))


def get_search(
    search_settings: SearchSettings,
    query: str | None,
    card_types: list[CardType],
    expansion_code: str | None = None,
    collector_number: str | None = None,
    operator_filters: list[ParsedOperator] | None = None,
) -> CardSearch:
    """
    This is the core search function for MPC Autofill - queries Elasticsearch for `self` given `search_settings`
    and returns the list of corresponding `Card` identifiers.
    Expects that the search index exists. Since this function is called many times, it makes sense to check this
    once at the call site rather than in the body of this function.
    """

    # set up search - match the query and use the AND operator
    s = (
        CardSearch.search()
        .filter(
            Bool(
                should=Terms(source_pk=get_enabled_source_pks(search_settings=search_settings)),
                minimum_should_match=1,
            )
        )
        .filter(
            Range(
                dpi={
                    "gte": search_settings.filterSettings.minimumDPI,
                    "lte": search_settings.filterSettings.maximumDPI,
                }
            )
        )
        .filter(Range(size={"lte": get_scaled_maximum_size(search_settings=search_settings)}))
        .source(fields=["identifier", "source_pk", "searchq"])
    )
    if query:
        query_parsed = to_searchable(query)
        if search_settings.searchTypeSettings.fuzzySearch:
            match = Match(searchq_fuzzy={"query": query_parsed, "operator": "AND"})
        else:
            match = Match(searchq_precise={"query": query_parsed, "operator": "AND"})
        s = s.query(match)
    if card_types:
        s = s.filter(
            Bool(
                should=Terms(card_type=[card_type.value for card_type in card_types]),
                minimum_should_match=1,
            )
        )
    if expansion_code:
        s = s.filter("term", expansion_code=expansion_code.upper())
    if collector_number:
        s = s.filter("term", collector_number=collector_number)
    if search_settings.filterSettings.languages:
        s = s.filter(
            Bool(
                should=Terms(language=get_enabled_languages(search_settings=search_settings)),
                minimum_should_match=1,
            )
        )
    if search_settings.filterSettings.includesTags:
        s = s.filter(Bool(should=Terms(tags=search_settings.filterSettings.includesTags), minimum_should_match=1))
    if search_settings.filterSettings.excludesTags:
        s = s.filter(Bool(must_not=Terms(tags=search_settings.filterSettings.excludesTags)))
    for parsed_filter in operator_filters or []:
        s = _apply_operator_filter(s, parsed_filter)
    return s


def _passes_resolved_attribute_filters(
    resolved: dict[str, ResolvedPrinting], search_settings: SearchSettings, identifier: str
) -> bool:
    """
    Cards absent from `resolved` (i.e. not printing_tag_status == RESOLVED) are never excluded
    here - they're unknowns, not mismatches, and the opt-in "Full art"/"Borderless" filters
    must only ever exclude a card whose community-resolved printing actively fails the check.
    """
    printing = resolved.get(identifier)
    if printing is None:
        return True
    if search_settings.filterSettings.fullArtOnly and not printing.full_art:
        return False
    if search_settings.filterSettings.borderlessOnly and printing.border_color != "borderless":
        return False
    return True


def _resolved_printing_match_tier(
    resolved: dict[str, ResolvedPrinting],
    expansion_code: str | None,
    collector_number: str | None,
    identifier: str,
) -> int:
    """
    Stable-sort key used to prefer, within an already-fetched result set, cards whose
    community-resolved printing (printing_tag_status == RESOLVED) matches the set/collector
    number carried by the decklist line being searched: exact set+collector match (0) > set-
    only match (1) > everything else, including all UNRESOLVED/NO_MATCH cards (2, i.e.
    unaffected - today's order, unchanged). This only re-orders cards that already survived
    `get_search`'s own (pre-existing, unrelated) expansion_code/collector_number term filter -
    it can never resurface a card that filter already excluded.
    """
    printing = resolved.get(identifier)
    if printing is None:
        return 2
    if expansion_code and printing.expansion_code == expansion_code.upper():
        if collector_number and printing.collector_number == collector_number:
            return 0
        return 1
    return 2


def _retrieve_card_identifiers_once(
    search_settings: SearchSettings,
    query: str,
    card_type: CardType,
    expansion_code: str | None,
    collector_number: str | None,
    operator_filters: list[ParsedOperator] | None = None,
) -> list[str]:
    hits_iterable = (
        get_search(
            search_settings=search_settings,
            query=query,
            card_types=[card_type],
            expansion_code=expansion_code,
            collector_number=collector_number,
            operator_filters=operator_filters,
        )
        .sort({"priority": {"order": "desc"}})
        .params(preserve_order=True)
        .scan()
    )
    source_order = get_source_order(search_settings=search_settings)
    identifiers = [
        result.identifier for result in sorted(hits_iterable, key=lambda result: source_order[result.source_pk])
    ]

    filters_active = search_settings.filterSettings.fullArtOnly or search_settings.filterSettings.borderlessOnly
    rerank_active = bool(expansion_code or collector_number)
    if filters_active or rerank_active:
        # single shared lookup - re-rank and filter must not each fetch their own copy
        resolved = get_resolved_printings(identifiers)

        if filters_active:
            identifiers = [
                identifier
                for identifier in identifiers
                if _passes_resolved_attribute_filters(resolved, search_settings, identifier)
            ]

        if rerank_active:
            identifiers = sorted(
                identifiers,
                key=lambda identifier: _resolved_printing_match_tier(
                    resolved, expansion_code, collector_number, identifier
                ),
            )

    return identifiers


@elastic_connection
def retrieve_card_identifiers(
    search_settings: SearchSettings,
    query: str,
    card_type: CardType,
    expansion_code: str | None = None,
    collector_number: str | None = None,
    operator_filters: list[ParsedOperator] | None = None,
) -> tuple[list[str], bool]:
    """
    Returns `(identifiers, degraded)`. `degraded` is True only when a printing-specific search
    (`expansion_code` and/or `collector_number` supplied) found zero hits under that filter and
    this function retried without it - e.g. a decklist paste carrying a specific set + collector
    number for a printing nobody's uploaded an image for yet, even though the card exists under
    other printings. Exact-match behaviour when hits DO exist under the filter is completely
    unchanged by this - this is a zero-hit fallback only, never a boost/re-rank weakening (see
    `_resolved_printing_match_tier`'s own docstring, which this doesn't touch). `operator_filters`
    (parsed `artist:`/`border:`/`frame:`/`tag:`/`set:`/`lang:` tokens - see
    `cardpicker.search.operator_parser`) are carried through unchanged into BOTH the primary and
    the degraded-retry search - the degraded retry only ever drops the expansion_code/
    collector_number term filter, never a user-typed operator.
    """
    identifiers = _retrieve_card_identifiers_once(
        search_settings, query, card_type, expansion_code, collector_number, operator_filters
    )
    degraded = False
    if not identifiers and (expansion_code or collector_number):
        identifiers = _retrieve_card_identifiers_once(search_settings, query, card_type, None, None, operator_filters)
        degraded = True
    return identifiers, degraded


def retrieve_cardback_identifiers(search_settings: SearchSettings) -> list[str]:
    """
    Retrieve the IDs of all cardbacks in the database, possibly filtered by search settings.
    """

    cardbacks: list[str]
    order_by = ["-priority", "source__ordinal", "source__name", "name"]
    if search_settings.searchTypeSettings.filterCardbacks:
        # afaik, `~Q(pk__in=[])` is the best way to have an always-true filter
        language_filter = (
            Q(language__in=[lang.upper() for lang in get_enabled_languages(search_settings)])
            if search_settings.filterSettings.languages
            else ~Q(pk__in=[])
        )
        includes_tag_filter = (
            (
                Q(tags__contains=search_settings.filterSettings.includesTags)
                | Q(tags__contained_by=search_settings.filterSettings.includesTags)
            )
            if search_settings.filterSettings.includesTags
            else ~Q(pk__in=[])
        )
        excludes_tag_filter = (
            ~Q(tags__overlap=search_settings.filterSettings.excludesTags)
            if search_settings.filterSettings.excludesTags
            else ~Q(pk__in=[])
        )
        source_order = get_source_order(search_settings=search_settings)
        hits_iterable = Card.objects.filter(
            language_filter,
            includes_tag_filter,
            excludes_tag_filter,
            card_type=CardTypes.CARDBACK,
            source__pk__in=get_enabled_source_pks(search_settings=search_settings),
            dpi__gte=search_settings.filterSettings.minimumDPI,
            dpi__lte=search_settings.filterSettings.maximumDPI,
            size__lte=get_scaled_maximum_size(search_settings=search_settings),
        ).order_by(*order_by)
        hits = sorted(hits_iterable, key=lambda card: source_order[card.source.pk])
        cardbacks = [card.identifier for card in hits]
    else:
        cardbacks = [card.identifier for card in Card.objects.filter(card_type=CardTypes.CARDBACK).order_by(*order_by)]
    return cardbacks


def get_new_cards_paginator(source: Source) -> Paginator[QuerySet[Card]]:
    now = timezone.now()
    cards = Card.objects.filter(
        source=source, date_created__lt=now, date_created__gte=now - dt.timedelta(days=NEW_CARDS_DAYS)
    ).order_by("-date_created", "name")
    return Paginator(cards, NEW_CARDS_PAGE_SIZE)  # type: ignore  # TODO: `_SupportsPagination`


__all__ = [
    "SearchExceptions",
    "get_elasticsearch_connection",
    "ping_elasticsearch",
    "elastic_connection",
    "get_search",
    "retrieve_card_identifiers",
    "retrieve_cardback_identifiers",
    "get_new_cards_paginator",
]
