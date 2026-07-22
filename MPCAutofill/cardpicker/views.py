import base64
import binascii
import itertools
import json
import logging
import mimetypes
import re
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from random import sample
from typing import Any, Callable, Literal, Optional, TypeVar, Union, cast

import Levenshtein
import pycountry
from django_ratelimit.decorators import ratelimit
from elasticsearch_dsl.index import Index
from pydantic import ValidationError

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, When
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    JsonResponse,
)
from django.utils import dateformat, timezone
from django.views.decorators.csrf import csrf_exempt

from cardpicker.artist_consensus import UNKNOWN as ARTIST_UNKNOWN
from cardpicker.artist_consensus import (
    get_artist_vote_tally,
    get_contested_artist_card_ids,
    resolve_and_persist_artist,
    resolve_artist,
)
from cardpicker.constants import (
    ARTIST_AUTOCOMPLETE_MAX_QUERY_LENGTH,
    ARTIST_AUTOCOMPLETE_MIN_QUERY_LENGTH,
    ARTIST_AUTOCOMPLETE_PAGE_SIZE,
    ARTIST_WRITEIN_NAME_MAX_LENGTH,
    CARDS_PAGE_SIZE,
    DATE_FORMAT,
    DEFAULT_LANGUAGE,
    EDITOR_SEARCH_MAX_QUERIES,
    EXPLORE_SEARCH_MAX_PAGE_SIZE,
    NSFW,
    PRINTING_TAG_QUEUE_PAGE_SIZE,
    REVIEW_CLUSTER_PAGE_SIZE,
    SAVED_DECK_SNAPSHOT_RING_SIZE,
)
from cardpicker.documents import CardSearch
from cardpicker.integrations.integrations import get_configured_game_integration
from cardpicker.integrations.patreon import get_patreon_campaign_details, get_patrons
from cardpicker.models import (
    ArtistVoteStatus,
    CanonicalArtist,
    CanonicalCard,
    Card,
    CardArtistVote,
    CardPrintingTag,
    CardReport,
    CardTagVote,
    CardTypes,
    DFCPair,
    PrintingTagStatus,
    SavedDeck,
    SavedDeckKind,
    SavedDeckShare,
    Source,
    Tag,
    TagModerationClass,
    TagVoteStatus,
    UserCryptoProfile,
    VotePolarity,
    VoteSource,
    attach_suggested_filter_tags_overlay,
    suggested_printing_votes_prefetch,
    summarise_contributions,
)
from cardpicker.moderation import is_moderator
from cardpicker.printing_candidates import (
    CANDIDATE_QUERY_LIMIT,
    CANDIDATE_RESULT_LIMIT,
    get_ranked_printing_candidates,
)
from cardpicker.printing_consensus import (
    NO_MATCH,
    get_contested_card_ids,
    get_vote_tally,
    resolve_and_persist_printing,
    resolve_printing,
)
from cardpicker.question_feed import get_next_question_feed_item, get_remaining_estimate
from cardpicker.review_clusters import (
    ReviewCluster,
    compute_review_clusters,
    find_cluster,
    get_cached_review_clusters,
    invalidate_review_cluster_cache,
)
from cardpicker.schema_types import (
    ArtistAutocompleteRequest,
    ArtistAutocompleteResponse,
    ArtistAutocompleteResult,
    ArtistCandidatesRequest,
    ArtistCandidatesResponse,
    ArtistConsensusRequest,
    ArtistConsensusResponse,
    ArtistVoteTallyEntry,
    CardbacksRequest,
    CardbacksResponse,
)
from cardpicker.schema_types import Cards as SampleCards
from cardpicker.schema_types import (
    CardsRequest,
    CardsResponse,
    CastImplicitVoteRequest,
    ConfirmReviewClusterRequest,
    ConfirmReviewClusterResponse,
    ContributionsResponse,
    CreateDeckShareRequest,
    CreateDeckShareResponse,
    CryptoProfileResponse,
    DeckSharesResponse,
    DeckShareSummary,
    DeleteDeckRequest,
    DeleteDeckResponse,
    DFCPairsResponse,
    EditorSearchRequest,
    EditorSearchResponse,
    ErrorResponse,
    ExploreSearchRequest,
    ExploreSearchResponse,
    GetSharedDeckRequest,
    GetSharedDeckResponse,
    ImportSite,
    ImportSiteDecklistRequest,
    ImportSiteDecklistResponse,
    ImportSitesResponse,
    Info,
    InfoResponse,
    Language,
    LanguagesResponse,
    LoadDeckRequest,
    LoadDeckResponse,
    LoadDeckResponseKind,
    ModerationDriveCardsRequest,
    ModerationDriveCardsResponse,
    ModerationDriveItem,
    ModerationDrivesRequest,
    ModerationDrivesResponse,
    ModerationQueueItem,
    ModerationQueueRequest,
    ModerationQueueResponse,
    ModerationRemoveCardRequest,
    ModerationRemoveCardResponse,
    ModerationRemoveDriveRequest,
    ModerationRemoveDriveResponse,
    NewCardsFirstPage,
    NewCardsFirstPagesResponse,
    NewCardsPageResponse,
    OldEditorSearchRequest,
    OldEditorSearchResponse,
    Patreon,
    PatreonResponse,
    PrintingCandidatesRequest,
    PrintingCandidatesResponse,
    PrintingConsensusRequest,
    PrintingConsensusResponse,
    PrintingTagQueueResponse,
    QuestionFeedResponse,
    ReportCardRequest,
    ReportCardResponse,
    ResetSavedDecksRequest,
    ResetSavedDecksResponse,
    RetractImplicitVoteRequest,
    ReviewClusterDetailRequest,
    ReviewClusterDetailResponse,
    ReviewClusterListRequest,
    ReviewClusterListResponse,
    ReviewClusterMember,
    ReviewClusterSignal,
    ReviewClusterSignalType,
    ReviewClusterSummary,
    RevokeDeckShareRequest,
    RevokeDeckShareResponse,
    SampleCardsResponse,
    SaveCryptoProfileRequest,
    SaveCryptoProfileResponse,
    SavedDecksResponse,
    SavedDeckSummary,
    SaveDeckRequest,
    SaveDeckResponse,
    SearchEngineHealthResponse,
    SortBy,
    SourcesResponse,
    SubmitArtistVoteRequest,
    SubmitArtistWriteInVoteRequest,
    SubmitArtistWriteInVoteResponse,
    SubmitPrintingTagRequest,
    SubmitTagVoteRequest,
    TagConsensusEntry,
    TagConsensusRequest,
    TagConsensusResponse,
    TagsResponse,
    TagVoteTallyEntry,
    VoteQueueItem,
    VoteQueueRequest,
)
from cardpicker.schema_types import VoteQueueRequestKind as VoteQueueKind
from cardpicker.schema_types import VoteQueueResponse, VoteTallyEntry, WhoamiResponse
from cardpicker.search.operator_parser import parse_query
from cardpicker.search.sanitisation import fix_whitespace, to_searchable
from cardpicker.search.search_functions import (
    SearchExceptions,
    get_new_cards_paginator,
    get_search,
    ping_elasticsearch,
    retrieve_card_identifiers,
    retrieve_cardback_identifiers,
)
from cardpicker.security import (
    reject_untrusted_origin,
    require_authenticated,
    require_moderator,
)
from cardpicker.sensitive_tags import REPORT_REASON_TO_TAG_NAME
from cardpicker.sources.api import PathTraversalError, resolve_within_root
from cardpicker.sources.source_types import SourceTypeChoices
from cardpicker.tag_consensus import (
    get_pending_approval_queue_pairs,
    get_tag_net_polarity,
    get_tag_review_queue_pairs,
    get_tag_vote_tally,
    resolve_and_persist_tag_votes,
    resolve_tag,
)
from cardpicker.tags import Tags
from cardpicker.vote_consensus import _PendingPrivileged

logger = logging.getLogger(__name__)

# https://mypy.readthedocs.io/en/stable/generics.html#declaring-decorators
F = TypeVar("F", bound=Callable[..., Any])


class BadRequestException(Exception):
    pass


class ErrorWrappers:
    """
    View function decorators which gracefully handle exceptions and allow the exception message to be displayed
    to the user.
    """

    @staticmethod
    def to_json(func: F) -> F:
        def wrapper(*args: Any, **kwargs: Any) -> Union[F, HttpResponse]:
            try:
                return func(*args, **kwargs)
            except ValidationError as e:
                # send pydantic validation errors to client
                error = ErrorResponse(
                    name="Schema error/s",
                    message="See `errors` field for detailed breakdown.",
                    errors=[dict(item) for item in e.errors()],
                )
                return JsonResponse(error.model_dump(), status=400)
            except SearchExceptions.ElasticsearchOfflineException:
                error = ErrorResponse(name="Search engine is offline", message=None)
                return JsonResponse(error.model_dump(), status=500)
            except BadRequestException as bad_request_exception:
                error = ErrorResponse(name="Bad request", message=bad_request_exception.args[0])
                return JsonResponse(error.model_dump(), status=400)
            except Exception as e:
                logger.exception("Unhandled exception in view")
                error = ErrorResponse(name=f"Unhandled {e.__class__.__name__}", message=str(e.args[0]))
                return JsonResponse(error.model_dump(), status=500)

        return cast(F, wrapper)


@csrf_exempt
@ErrorWrappers.to_json
def post_editor_search(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    editor_search_request = EditorSearchRequest.model_validate(json.loads(request.body))
    if not ping_elasticsearch():
        raise SearchExceptions.ElasticsearchOfflineException()
    if not Index(CardSearch.Index.name).exists():
        raise SearchExceptions.IndexNotFoundException(CardSearch.__name__)

    if len(editor_search_request.queries) > EDITOR_SEARCH_MAX_QUERIES:
        raise BadRequestException(
            f"Invalid query count {len(editor_search_request.queries)}. "
            f"Must be less than or equal to {EDITOR_SEARCH_MAX_QUERIES}."
        )

    results: dict[str, list[str]] = {}
    degraded_queries: list[str] = []
    # Search-operator syntax (2026-07-22): additive and optional - a query with no `operator:`
    # tokens parses to (residual_text == query, filters == [], errors == []) and behaves byte-
    # identically to before this feature existed. `operator_errors` is only ever populated with
    # a hash_key whose query contained an unrecognised `operator:` token (e.g. `power:4`) - its
    # absence from the dict, or the dict being empty, means every query parsed cleanly.
    operator_errors: dict[str, list[str]] = {}
    for hash_key, search_query in editor_search_request.queries.items():
        if search_query.query is not None and hash_key not in results.keys():
            parsed = parse_query(search_query.query)
            if parsed.errors:
                operator_errors[hash_key] = [f"unsupported operator: {error.operator}" for error in parsed.errors]
            hits, degraded = retrieve_card_identifiers(
                search_settings=editor_search_request.searchSettings,
                query=parsed.residual_text,
                card_type=search_query.cardType,
                expansion_code=search_query.expansionCode,
                collector_number=search_query.collectorNumber,
                operator_filters=parsed.filters,
            )
            results[hash_key] = hits
            if degraded:
                degraded_queries.append(hash_key)
    return JsonResponse(
        EditorSearchResponse(
            results=results, degradedQueries=degraded_queries, operatorErrors=operator_errors
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def old_post_editor_search(request: HttpRequest) -> HttpResponse:
    # TODO: This endpoint is only kept for backwards compatibility
    # in case unofficial third-party clients depend on it.
    # It is not covered by automated tests and is subject to removal in the future.
    """
    Return the first page of search results for a given list of queries.
    Each query should be of the form {card name, card type}.
    This function should also accept a set of search settings in a standard format.
    Return a dictionary of search results of the following form:
    {(card name, card type): {"num_hits": num_hits, "hits": [list of Card identifiers]}
    and it's assumed that `hits` starts from the first hit.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    editor_search_request = OldEditorSearchRequest.model_validate(json.loads(request.body))
    if not ping_elasticsearch():
        raise SearchExceptions.ElasticsearchOfflineException()
    if not Index(CardSearch.Index.name).exists():
        raise SearchExceptions.IndexNotFoundException(CardSearch.__name__)

    if len(editor_search_request.queries) > EDITOR_SEARCH_MAX_QUERIES:
        raise BadRequestException(
            f"Invalid query count {len(editor_search_request.queries)}. "
            f"Must be less than or equal to {EDITOR_SEARCH_MAX_QUERIES}."
        )

    results: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for query, card_type in sorted({(item.query, item.cardType) for item in editor_search_request.queries}):
        if query is not None and results[query].get(card_type.value, None) is None:
            # legacy endpoint has no printing-filter fields on its request schema at all, so
            # `retrieve_card_identifiers` never gets an expansion_code/collector_number here and
            # `degraded` is always False - nothing to surface on this frozen response shape.
            hits, _degraded = retrieve_card_identifiers(
                query=query, card_type=card_type, search_settings=editor_search_request.searchSettings
            )
            results[query][card_type.value] = hits
    return JsonResponse(OldEditorSearchResponse(results=results).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def post_explore_search(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    explore_search_request = ExploreSearchRequest.model_validate(json.loads(request.body))
    if explore_search_request.pageStart < 0:
        raise BadRequestException(f"Invalid page start {explore_search_request.pageStart}. Must be greater than zero.")
    if not (0 < explore_search_request.pageSize <= EXPLORE_SEARCH_MAX_PAGE_SIZE):
        raise BadRequestException(
            f"Invalid page size {explore_search_request.pageSize}. Must be less than or equal to {EXPLORE_SEARCH_MAX_PAGE_SIZE}."
        )
    if not ping_elasticsearch():
        raise SearchExceptions.ElasticsearchOfflineException()
    if not Index(CardSearch.Index.name).exists():
        raise SearchExceptions.IndexNotFoundException(CardSearch.__name__)

    sort: dict[str, dict[str, str]] = {
        SortBy.nameAscending: {"searchq_keyword": {"order": "asc"}},
        SortBy.nameDescending: {"searchq_keyword": {"order": "desc"}},
        SortBy.dateCreatedAscending: {"date_created": {"order": "asc"}, "searchq_keyword": {"order": "asc"}},
        SortBy.dateCreatedDescending: {"date_created": {"order": "desc"}, "searchq_keyword": {"order": "asc"}},
        SortBy.dateModifiedAscending: {"date_modified": {"order": "asc"}, "searchq_keyword": {"order": "asc"}},
        SortBy.dateModifiedDescending: {"date_modified": {"order": "desc"}, "searchq_keyword": {"order": "asc"}},
    }[explore_search_request.sortBy]

    s = get_search(
        search_settings=explore_search_request.searchSettings,
        query=explore_search_request.query,
        card_types=explore_search_request.cardTypes,
    ).sort(sort)
    count = s.extra(track_total_hits=True).count()

    s_sliced = s[explore_search_request.pageStart : explore_search_request.pageStart + explore_search_request.pageSize]
    card_ids = [man.identifier for man in s_sliced.execute()]
    # TODO: the below code feels inefficient but is set up this way to ensure sorting from elasticsearch is respected.
    # `include_suggested_printing=True` + `suggested_printing_votes_prefetch()` together
    # populate `suggestedCanonicalCard` (Proposal H §4.4′, issue #184) with no extra query
    # per card - see that prefetch helper's own docstring.
    card_id_object_dict = {
        card.identifier: card.serialise(include_suggested_printing=True)
        for card in (
            Card.objects.select_related("source", "canonical_card")
            .prefetch_related(suggested_printing_votes_prefetch())
            .filter(identifier__in=card_ids)
        )
    }
    cards = [card_id_object_dict[card_id] for card_id in card_ids]
    return JsonResponse(ExploreSearchResponse(cards=cards, count=count).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def post_cards(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    cards_request = CardsRequest.model_validate(json.loads(request.body))
    if len(cards_request.cardIdentifiers) > CARDS_PAGE_SIZE:
        raise BadRequestException(
            f"Invalid card count {len(cards_request.cardIdentifiers)}. "
            f"Must be less than or equal to {CARDS_PAGE_SIZE}."
        )

    # `include_suggested_printing=True` + `suggested_printing_votes_prefetch()` together
    # populate `suggestedCanonicalCard` (Proposal H §4.4′, issue #184) with no extra query
    # per card - see that prefetch helper's own docstring. `attach_suggested_filter_tags_overlay()`
    # does the same for `suggestedFilterTagNames` (owner-ratified 2026-07-22 D6 vote-weight
    # matrix) - one `get_suggested_filter_tags_overlay()` call for the whole `cards` list below,
    # not one per card; this is the endpoint feeding the /display grid-selector candidate list
    # (`SelectVersionResults.tsx` via `cardDocumentsSlice`), which had zero producers of this
    # field until now.
    cards = list(
        Card.objects.select_related("source", "canonical_card")
        .prefetch_related(suggested_printing_votes_prefetch())
        .filter(identifier__in=cards_request.cardIdentifiers)
    )
    attach_suggested_filter_tags_overlay(cards)
    results = {
        card.identifier: card.serialise(include_suggested_printing=True, include_suggested_filter_tags=True)
        for card in cards
    }
    return JsonResponse(CardsResponse(results=results).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def get_sources(request: HttpRequest) -> HttpResponse:
    """
    Return a list of sources.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    results = {str(source.pk): source.serialise() for source in Source.objects.order_by("ordinal", "pk")}
    return JsonResponse(SourcesResponse(results=results).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def get_dfc_pairs(request: HttpRequest) -> HttpResponse:
    """
    Return a list of double-faced cards. The unedited names are returned and the frontend is expected to sanitise them.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    dfc_pairs = {x.front: x.back for x in DFCPair.objects.all()}
    return JsonResponse(DFCPairsResponse(dfcPairs=dfc_pairs).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def get_languages(request: HttpRequest) -> HttpResponse:
    """
    Return the list of all unique languages among cards in the database.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")
    return JsonResponse(
        LanguagesResponse(
            languages=sorted(
                [
                    Language(name=language.name, code=row[0].upper())
                    for row in Card.objects.order_by().values_list("language").distinct()
                    if (language := pycountry.languages.get(alpha_2=row[0])) is not None
                ],
                # sort like this so DEFAULT_LANGUAGE is first, then the rest of the languages are in alphabetical order
                key=lambda language: "-" if language.code == DEFAULT_LANGUAGE.alpha_2 else language.name,
            )
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def get_tags(request: HttpRequest) -> HttpResponse:
    """
    Return a list of all tags that cards can be tagged with.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")
    return JsonResponse(
        TagsResponse(
            tags=sorted([tag.serialise() for tag in Tags().tags.values() if tag.parent is None], key=lambda x: x.name)
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def post_cardbacks(request: HttpRequest) -> HttpResponse:
    """
    Return a list of cardbacks, possibly filtered by the user's search settings.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    cardbacks_request = CardbacksRequest.model_validate(json.loads(request.body))
    cardbacks = retrieve_cardback_identifiers(search_settings=cardbacks_request.searchSettings)
    return JsonResponse(CardbacksResponse(cardbacks=cardbacks).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def get_import_sites(request: HttpRequest) -> HttpResponse:
    """
    Return a list of import sites.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    game_integration = get_configured_game_integration()
    if game_integration is None:
        return JsonResponse(ImportSitesResponse(importSites=[]).model_dump())

    import_sites = [
        ImportSite(name=site.__name__, url=f"https://{site.get_host_names()[0]}")
        for site in game_integration.get_import_sites()
    ]
    return JsonResponse(ImportSitesResponse(importSites=import_sites).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def post_import_site_decklist(request: HttpRequest) -> HttpResponse:
    """
    Read the specified import site URL and process & return the associated decklist.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    game_integration = get_configured_game_integration()
    if game_integration is None:
        raise BadRequestException("No game integration is configured on this server.")

    import_site_decklist_request = ImportSiteDecklistRequest.model_validate(json.loads(request.body))
    try:
        decklist = game_integration.query_import_site(url=import_site_decklist_request.url)
        if decklist is None:
            raise BadRequestException("The specified decklist URL does not match any known import sites.")
        return JsonResponse(ImportSiteDecklistResponse(cards=decklist).model_dump())
    except ValueError as e:
        raise BadRequestException(str(e))


@csrf_exempt
@ErrorWrappers.to_json
def get_sample_cards(request: HttpRequest) -> HttpResponse:
    """
    Return a selection of cards you can query this database for.
    Used in the placeholder text of the Add Cards — Text component in the frontend.

    TODO: i don't know how to do this in a single query in the Django ORM :(
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    # sample some large number of identifiers from the database (while avoiding sampling NSFW cards)
    identifiers = {
        card_type: list(
            Card.objects.filter(~Q(tags__overlap=[NSFW]) & Q(card_type=card_type)).values_list("id", flat=True)[0:5000]
        )
        for card_type in CardTypes
    }

    # select a few of those identifiers at random
    selected_identifiers = [
        identifier
        for card_type in CardTypes
        for identifier in sample(
            identifiers[card_type], k=min(4 if card_type == CardTypes.CARD else 1, len(identifiers[card_type]))
        )
    ]

    # retrieve the full ORM objects for the selected identifiers and group by type
    cards = [
        card.serialise()
        for card in Card.objects.select_related("source", "canonical_card")
        .filter(pk__in=selected_identifiers)
        .order_by("card_type")
    ]
    cards_by_type = {
        card_type: list(grouped_cards_iterable)
        for card_type, grouped_cards_iterable in itertools.groupby(cards, key=lambda x: x.cardType)
    }

    sample_cards_response = SampleCardsResponse(
        cards=SampleCards(**({CardTypes.CARD: [], CardTypes.CARDBACK: [], CardTypes.TOKEN: []} | cards_by_type))
    )
    return JsonResponse(sample_cards_response.model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def get_contributions(request: HttpRequest) -> HttpResponse:
    """
    Return a summary of contributions to the database.
    Used by the Contributions page.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    sources, card_count_by_type, total_database_size = summarise_contributions()
    return JsonResponse(
        ContributionsResponse(
            sources=sources, cardCountByType=card_count_by_type, totalDatabaseSize=total_database_size
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def get_new_cards_first_pages(request: HttpRequest) -> HttpResponse:
    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    results: dict[str, NewCardsFirstPage] = {}
    for source in Source.objects.all():
        paginator = get_new_cards_paginator(source=source)
        if paginator.count > 0:
            results[source.key] = NewCardsFirstPage(
                source=source.serialise(),
                hits=paginator.count,
                pages=paginator.num_pages,
                cards=[card.serialise() for card in paginator.get_page(1).object_list],
            )
    return JsonResponse(NewCardsFirstPagesResponse(results=results).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def get_new_cards_page(request: HttpRequest) -> HttpResponse:
    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    source_key = request.GET.get("source")
    if not source_key:
        raise BadRequestException("Source not specified.")
    source_q = Source.objects.filter(key=source_key)

    if source_q.count() == 0:
        raise BadRequestException(f"Invalid source key {source_key} specified.")
    paginator = get_new_cards_paginator(source=source_q[0])

    page = request.GET.get("page")
    if page is None:
        raise BadRequestException("Page not specified.")
    try:
        page_int = int(page)
        if not (paginator.num_pages >= page_int > 0):
            raise BadRequestException(
                f"Invalid page {page_int} specified - must be between 1 and {paginator.num_pages} "
                f"for source {source_key}."
            )
        return JsonResponse(
            NewCardsPageResponse(cards=[card.serialise() for card in paginator.page(page).object_list]).model_dump()
        )
    except ValueError:
        raise BadRequestException("Invalid page specified.")


@csrf_exempt
@ErrorWrappers.to_json
def get_info(request: HttpRequest) -> HttpResponse:
    """
    Return a stack of metadata about the server for the frontend to display.
    It's expected that this route will be called once when the server is connected.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    return JsonResponse(
        InfoResponse(
            info=Info(
                name=settings.SITE_NAME,
                description=settings.DESCRIPTION,
                email=settings.TARGET_EMAIL,
                reddit=settings.REDDIT,
                discord=settings.DISCORD,
            )
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def get_patreon(request: HttpRequest) -> HttpResponse:
    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    campaign, tiers = get_patreon_campaign_details()
    members = get_patrons(campaign.id, tiers) if campaign is not None and tiers is not None else None

    return JsonResponse(
        PatreonResponse(
            patreon=Patreon(
                url=settings.PATREON_URL,
                members=members or [],
                tiers=tiers,
                campaign=campaign,
            )
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def get_search_engine_health(request: HttpRequest) -> HttpResponse:
    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    return JsonResponse(SearchEngineHealthResponse(online=ping_elasticsearch()).model_dump())


@csrf_exempt
def get_local_file_image(request: HttpRequest) -> HttpResponseBase:
    """
    Serve image bytes for a card whose source is of type `LOCAL_FILE`. This is a security-sensitive
    view: the `identifier` query parameter is treated as untrusted client input, and this function is
    responsible for ensuring that the file it ultimately reads is (a) actually catalogued in the
    database as belonging to a LOCAL_FILE source, and (b) still located within that source's
    currently-configured root directory - even if the path contains `../` segments, or is (or passes
    through) a symlink. Nothing outside of that root directory is ever served.
    """

    if request.method != "GET":
        return HttpResponse(status=405)

    identifier = request.GET.get("identifier")
    if not identifier:
        return HttpResponse("Missing 'identifier' query parameter.", status=400)

    try:
        card = Card.objects.select_related("source").get(
            identifier=identifier, source__source_type=SourceTypeChoices.LOCAL_FILE
        )
    except Card.DoesNotExist:
        return HttpResponse(status=404)

    try:
        resolved_path = resolve_within_root(root=Path(card.source.identifier), candidate=Path(card.identifier))
    except PathTraversalError:
        logger.warning(
            "Refusing to serve identifier %r for source %r: resolves outside of the source's root directory",
            identifier,
            card.source.key,
        )
        return HttpResponse(status=404)

    if not resolved_path.is_file():
        return HttpResponse(status=404)

    content_type, _ = mimetypes.guess_type(resolved_path.name)
    response = FileResponse(resolved_path.open("rb"), content_type=content_type or "application/octet-stream")
    response["Cache-Control"] = "public, max-age=3600"
    return response


def _get_card_or_400(identifier: str) -> Card:
    try:
        return Card.objects.get(identifier=identifier)
    except Card.DoesNotExist:
        raise BadRequestException(f"No card found with identifier {identifier!r}.")


def _get_source_or_400(source_id: int) -> Source:
    try:
        return Source.objects.get(pk=source_id)
    except Source.DoesNotExist:
        raise BadRequestException(f"No source found with id {source_id!r}.")


def _requesting_user(request: HttpRequest) -> Optional[User]:
    """
    The authenticated user behind a vote/report submission, or None for the (typical)
    anonymous case - recorded on the row *in addition to* the client-generated anonymous_id,
    never instead of it. See AbstractWeightedVote.user.
    """
    return request.user if isinstance(request.user, User) else None


@csrf_exempt
@ErrorWrappers.to_json
def get_printing_tag_queue(request: HttpRequest) -> HttpResponse:
    """
    A paginated list of cards that still need a human to tag their printing - i.e. haven't
    reached consensus (contested or no votes yet). Filters on the indexed
    `printing_tag_status` rather than recomputing consensus for every card, which is the
    whole reason that field exists. Contested cards (conflicting votes already cast) sort
    first - they're the highest-value cards for a human to weigh in on, and this is also
    what the "What's That Card?" queue page relies on to default to contested cards.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    cards = (
        Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED)
        .annotate(
            is_contested=Case(When(pk__in=get_contested_card_ids(), then=1), default=0, output_field=IntegerField())
        )
        .order_by("-is_contested", "-date_created", "name")
    )
    paginator: Paginator[Card] = Paginator(cards, PRINTING_TAG_QUEUE_PAGE_SIZE)

    page = request.GET.get("page", "1")
    try:
        page_int = int(page)
        if not (paginator.num_pages >= page_int > 0):
            raise BadRequestException(
                f"Invalid page {page_int} specified - must be between 1 and {paginator.num_pages}."
            )
    except ValueError:
        raise BadRequestException("Invalid page specified.")

    return JsonResponse(
        PrintingTagQueueResponse(
            hits=paginator.count,
            pages=paginator.num_pages,
            cards=[card.serialise() for card in paginator.page(page_int).object_list],
        ).model_dump()
    )


def _build_printing_consensus_response(
    card: Card, resolved: CanonicalCard | Literal["NO_MATCH"] | None
) -> PrintingConsensusResponse:
    return PrintingConsensusResponse(
        resolvedPrinting=resolved.serialise_as_printing_candidate() if isinstance(resolved, CanonicalCard) else None,
        isNoMatch=resolved == NO_MATCH,
        voteTally=[
            VoteTallyEntry(
                printing=entry["printing"].serialise_as_printing_candidate() if entry["printing"] else None,
                isNoMatch=entry["is_no_match"],
                count=entry["count"],
            )
            for entry in get_vote_tally(card)
        ],
    )


@csrf_exempt
@ErrorWrappers.to_json
def post_printing_candidates(request: HttpRequest) -> HttpResponse:
    """
    Return candidate printings for a card to be tagged against, ranked so the most likely
    correct match comes first - see `get_ranked_printing_candidates` for the ranking rules.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = PrintingCandidatesRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    candidates = get_ranked_printing_candidates(card, req.query)

    return JsonResponse(
        PrintingCandidatesResponse(
            results=[candidate.serialise_as_printing_candidate() for candidate in candidates]
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def post_printing_consensus(request: HttpRequest) -> HttpResponse:
    """
    Return the currently resolved printing-tag consensus for a card, plus a plain vote-count
    breakdown, so a voter can see what's already been said before confirming or disputing it.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = PrintingConsensusRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    return JsonResponse(_build_printing_consensus_response(card, resolve_printing(card)).model_dump())


def _printing_tag_rate_limit_key(group: str, request: HttpRequest) -> str:
    # `anonymousId` lives in the request body (see SubmitPrintingTagRequest), not a header -
    # `request.body` is safe to read here too; Django caches it, so the view re-reading it
    # afterwards to build `SubmitPrintingTagRequest` doesn't re-consume a stream.
    try:
        anonymous_id = json.loads(request.body).get("anonymousId")
    except (ValueError, AttributeError):
        anonymous_id = None
    return anonymous_id if anonymous_id else request.META.get("REMOTE_ADDR", "unknown")


def _printing_tag_rate_limit_rate(group: str, request: HttpRequest) -> str:
    # a plain string here would be bound once at import time, making the rate impossible to
    # override in tests (or via runtime settings changes) - a callable is re-evaluated per request.
    rate: str = settings.PRINTING_TAG_SUBMISSION_RATE
    return rate


@csrf_exempt
@reject_untrusted_origin  # sessions now authenticate these writes - see cardpicker.security
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_printing_tag_rate_limit_key, rate=_printing_tag_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_submit_printing_tag(request: HttpRequest) -> HttpResponse:
    """
    Submit a vote that a card depicts a specific printing (or definitively depicts none), from
    the client-generated anonymous ID in the request body (see frontend/src/common/anonymousId.ts
    - this is not a real Django session, which wouldn't round-trip cross-origin here anyway).
    Replaces any existing vote from the same (card, anonymous ID) pair - a person changing their
    mind updates their vote rather than erroring on the unique constraint - then immediately
    recomputes and persists the consensus for this card.

    Rate-limited per anonymous ID (IP as a fallback) via PRINTING_TAG_SUBMISSION_RATE. Note this
    currently relies on Django's default (in-process) cache, which is only correctly global across
    requests because this app is deployed as a single gunicorn worker process - revisit if that
    ever changes, since a per-worker cache would silently multiply the effective rate limit.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Rate limited", message="Too many printing tag submissions - please slow down."
            ).model_dump(),
            status=429,
        )

    req = SubmitPrintingTagRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)

    printing = None
    if not req.isNoMatch:
        if not req.printingIdentifier:
            raise BadRequestException("printingIdentifier is required unless isNoMatch is set.")
        try:
            printing = CanonicalCard.objects.get(identifier=req.printingIdentifier)
        except CanonicalCard.DoesNotExist:
            raise BadRequestException(f"No printing found with identifier {req.printingIdentifier!r}.")

    with transaction.atomic():
        CardPrintingTag.objects.filter(card=card, anonymous_id=req.anonymousId).delete()
        CardPrintingTag.objects.create(
            card=card,
            printing=printing,
            is_no_match=req.isNoMatch,
            anonymous_id=req.anonymousId,
            source=VoteSource.USER,
            user=_requesting_user(request),
            vote_surface=req.voteSurface,
        )
        resolved = resolve_and_persist_printing(card)

    return JsonResponse(_build_printing_consensus_response(card, resolved).model_dump())


def _build_artist_consensus_response(
    card: Card, resolved: CanonicalArtist | Literal["UNKNOWN"] | None
) -> ArtistConsensusResponse:
    return ArtistConsensusResponse(
        resolvedArtist=resolved.serialise() if isinstance(resolved, CanonicalArtist) else None,
        isUnknown=resolved == ARTIST_UNKNOWN,
        voteTally=[
            ArtistVoteTallyEntry(
                artist=entry["artist"].serialise() if entry["artist"] else None,
                isUnknown=entry["is_unknown"],
                count=entry["count"],
            )
            for entry in get_artist_vote_tally(card)
        ],
    )


@csrf_exempt
@ErrorWrappers.to_json
def post_artist_candidates(request: HttpRequest) -> HttpResponse:
    """
    Return candidate artists for a card to be tagged against. Two modes: by default, ranks by
    deduplicating the artists of `get_ranked_printing_candidates`'s own results (free ranking
    signal, no separate query needed, since those printings are already ranked by relevance to
    this card); if `query` is given, switches to a typeahead search over `CanonicalArtist.name`
    for when the right artist isn't among those candidates.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ArtistCandidatesRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)

    if req.query:
        words = to_searchable(req.query).split()
        artists_qs = CanonicalArtist.objects.all()
        for word in words:
            artists_qs = artists_qs.filter(name__icontains=word)
        normalised_query = to_searchable(req.query)
        artists = sorted(
            artists_qs[:CANDIDATE_QUERY_LIMIT],
            key=lambda artist: Levenshtein.ratio(normalised_query, to_searchable(artist.name)),
            reverse=True,
        )[:CANDIDATE_RESULT_LIMIT]
    else:
        seen_artist_ids: set[int] = set()
        artists = []
        for printing in get_ranked_printing_candidates(card, None):
            if printing.artist_id not in seen_artist_ids:
                seen_artist_ids.add(printing.artist_id)
                artists.append(printing.artist)

    return JsonResponse(ArtistCandidatesResponse(results=[artist.serialise() for artist in artists]).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def post_artist_consensus(request: HttpRequest) -> HttpResponse:
    """
    Return the currently resolved artist-vote consensus for a card, plus a plain vote-count
    breakdown - mirrors `post_printing_consensus`.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ArtistConsensusRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    return JsonResponse(_build_artist_consensus_response(card, resolve_artist(card)).model_dump())


@csrf_exempt
@reject_untrusted_origin  # sessions now authenticate these writes - see cardpicker.security
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_printing_tag_rate_limit_key, rate=_printing_tag_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_submit_artist_vote(request: HttpRequest) -> HttpResponse:
    """
    Submit a vote that a card was illustrated by a specific artist (or definitively by an
    unlisted/unknown artist). Same delete-then-create-then-recompute pattern as
    `post_submit_printing_tag` - one artist opinion per (card, anonymous ID) pair at a time,
    reusing the same rate-limit plumbing (it already reads `anonymousId` from the request body
    generically, nothing printing-specific about it despite the name).
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Rate limited", message="Too many artist vote submissions - please slow down."
            ).model_dump(),
            status=429,
        )

    req = SubmitArtistVoteRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)

    artist = None
    if not req.isUnknown:
        if not req.artistName:
            raise BadRequestException("artistName is required unless isUnknown is set.")
        try:
            artist = CanonicalArtist.objects.get(name=req.artistName)
        except CanonicalArtist.DoesNotExist:
            raise BadRequestException(f"No artist found with name {req.artistName!r}.")

    with transaction.atomic():
        CardArtistVote.objects.filter(card=card, anonymous_id=req.anonymousId).delete()
        CardArtistVote.objects.create(
            card=card,
            artist=artist,
            is_unknown=req.isUnknown,
            anonymous_id=req.anonymousId,
            source=VoteSource.USER,
            user=_requesting_user(request),
            vote_surface=req.voteSurface,
        )
        resolved = resolve_and_persist_artist(card)

    return JsonResponse(_build_artist_consensus_response(card, resolved).model_dump())


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_artist_text(raw: str) -> str:
    """
    Strip control characters, then collapse internal whitespace and trim (`fix_whitespace`,
    already used by the printing-name search path) - shared by the autocomplete query and the
    write-in free-text name below, so both reject the same class of junk input before it
    reaches the database. Deliberately NOT `to_searchable` (used by post_artist_candidates'
    own typeahead ranking): that also lowercases, strips punctuation/hyphens/digits and drops
    bracketed text, which is too aggressive for "the name a human actually typed" - a
    hyphenated or punctuated artist name should round-trip intact here.
    """
    return fix_whitespace(_CONTROL_CHAR_RE.sub("", raw))


def _artist_autocomplete_rate_limit_key(group: str, request: HttpRequest) -> str:
    # unauthenticated, read-only, no anonymousId in the request body (no vote is being cast) -
    # IP is the only signal available to key on, unlike the vote-submission endpoints below.
    return request.META.get("REMOTE_ADDR", "unknown")


def _artist_autocomplete_rate_limit_rate(group: str, request: HttpRequest) -> str:
    # a callable (not a plain string) for the same reason as _printing_tag_rate_limit_rate: a
    # plain string would be bound once at import time, making the rate impossible to override
    # in tests or via runtime settings changes.
    rate: str = settings.ARTIST_AUTOCOMPLETE_RATE
    return rate


@csrf_exempt
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_artist_autocomplete_rate_limit_key, rate=_artist_autocomplete_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_artist_autocomplete(request: HttpRequest) -> HttpResponse:
    """
    Typeahead search over ALL `CanonicalArtist` names (id + display name), for suggesting an
    existing artist during the write-in flow (`/whatsthat`'s artist question and `/display`'s
    Artist sidebar) - the PRIMARY normalization path: a voter picks an existing spelling
    whenever one exists, so a free-text write-in that duplicates a known artist (see
    `post_submit_artist_writein_vote` below) should be rare.

    Deliberately a separate endpoint from `post_artist_candidates`, not an extra mode on it:
    that endpoint is scoped to one card's ranked printing candidates and its typeahead mode
    returns bare names (no id, ranked by Levenshtein similarity, unbounded query length). This
    one is unscoped (no card `identifier` - searches the whole catalogue), returns an `id` per
    result (so the write-in cast endpoint can be called with an unambiguous `artistId` instead
    of round-tripping a display-name string), and matches prefix-first-then-substring rather
    than fuzzy similarity, which is the more predictable ordering for a live-typing dropdown.

    Matching is case-insensitive; `query` is control-character-stripped and whitespace-
    collapsed before matching (`_clean_artist_text`) and rejected outright (400) if, after that
    cleaning, it's shorter than `ARTIST_AUTOCOMPLETE_MIN_QUERY_LENGTH` - a 1-character query
    would match a large fraction of the artist table for no useful narrowing. The raw query is
    also capped at `ARTIST_AUTOCOMPLETE_MAX_QUERY_LENGTH` before cleaning, so a pathologically
    long string is rejected up front rather than processed. Django's ORM parameterizes
    `icontains`/`istartswith` and escapes `%`/`_` itself, so `query` never reaches the database
    as raw SQL or an ILIKE wildcard, regardless of what a caller sends.

    Unauthenticated-OK (`CanonicalArtist` names are already public, read-only catalogue data -
    no `reject_untrusted_origin`, matching every other read-only endpoint in this file, none of
    which consume a session), but rate-limited per-IP (`ARTIST_AUTOCOMPLETE_RATE`) since this is
    expected to fire on every keystroke of a live typeahead field, a much higher natural cadence
    than a deliberate vote submission - a separate, per-minute budget from
    `PRINTING_TAG_SUBMISSION_RATE`'s hourly one.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Rate limited", message="Too many artist search requests - please slow down."
            ).model_dump(),
            status=429,
        )

    req = ArtistAutocompleteRequest.model_validate(json.loads(request.body))
    if len(req.query) > ARTIST_AUTOCOMPLETE_MAX_QUERY_LENGTH:
        raise BadRequestException(f"query must be at most {ARTIST_AUTOCOMPLETE_MAX_QUERY_LENGTH} characters.")

    cleaned = _clean_artist_text(req.query)
    if len(cleaned) < ARTIST_AUTOCOMPLETE_MIN_QUERY_LENGTH:
        raise BadRequestException(f"query must be at least {ARTIST_AUTOCOMPLETE_MIN_QUERY_LENGTH} characters.")

    prefix_matches = list(
        CanonicalArtist.objects.filter(name__istartswith=cleaned).order_by("name")[:ARTIST_AUTOCOMPLETE_PAGE_SIZE]
    )
    results = prefix_matches
    remaining = ARTIST_AUTOCOMPLETE_PAGE_SIZE - len(prefix_matches)
    if remaining > 0:
        seen_ids = {artist.pk for artist in prefix_matches}
        substring_matches = list(
            CanonicalArtist.objects.filter(name__icontains=cleaned)
            .exclude(pk__in=seen_ids)
            .order_by("name")[:remaining]
        )
        results = prefix_matches + substring_matches

    return JsonResponse(
        ArtistAutocompleteResponse(
            results=[ArtistAutocompleteResult(id=artist.pk, name=artist.name) for artist in results]
        ).model_dump()
    )


def _resolve_or_create_writein_artist(
    artist_id: Optional[int], free_text: Optional[str]
) -> tuple[CanonicalArtist, bool]:
    """
    Resolves a write-in artist submission to a `CanonicalArtist` row, returning
    `(artist, created_new_row)`. Exactly one of `artist_id`/`free_text` is expected to be given -
    enforced by `post_submit_artist_writein_vote`'s own request validation, not here.

    `artist_id` (the autocomplete-pick path - the PRIMARY normalization path per the owner's
    write-in spec) is looked up directly, no normalization needed. `free_text` is cleaned
    (`_clean_artist_text`: control characters stripped, internal whitespace collapsed, trimmed)
    then matched CASE-INSENSITIVELY against existing `CanonicalArtist.name` values - a
    normalized exact match (e.g. submitting "rebecca guay") REUSES the existing row (e.g.
    "Rebecca Guay") rather than creating a twin; only a genuinely new normalized name creates a
    new row, stored with the submitter's own casing (there is no "correct" casing to infer for a
    name with zero prior signal in this catalogue).

    KNOWN LIMITATION (see this task's PR description and docs/features/printing-tags.md's
    write-in bullet): this reuses existing rows case-insensitively, but the Scryfall/MTG catalog
    sync path (`integrations/game/mtg.py`'s `artists_by_name` dict, built from
    `CanonicalArtist.objects.all()`) dedupes by EXACT, case-sensitive name match. A write-in
    stored with unconventional casing (e.g. "rebecca guay") that's later confirmed by an
    official Scryfall entry with different casing ("Rebecca Guay") will still produce a
    duplicate `CanonicalArtist` row at the next sync - deferred, not eliminated. Fixing that
    would mean changing the catalog sync integration itself, out of scope for this vote/
    consensus-side task; flagged rather than silently accepted or "fixed" with a casing-
    guessing heuristic that could itself mangle a legitimately-cased name.
    """
    if artist_id is not None:
        try:
            return CanonicalArtist.objects.get(pk=artist_id), False
        except CanonicalArtist.DoesNotExist:
            raise BadRequestException(f"No artist found with id {artist_id!r}.")

    assert free_text is not None
    cleaned = _clean_artist_text(free_text)
    if not cleaned:
        raise BadRequestException("freeText must contain a non-empty artist name.")
    if len(cleaned) > ARTIST_WRITEIN_NAME_MAX_LENGTH:
        raise BadRequestException(f"freeText must be at most {ARTIST_WRITEIN_NAME_MAX_LENGTH} characters.")

    existing = CanonicalArtist.objects.filter(name__iexact=cleaned).first()
    if existing is not None:
        return existing, False
    return CanonicalArtist.objects.create(name=cleaned), True


@csrf_exempt
@reject_untrusted_origin  # sessions now authenticate these writes - see cardpicker.security
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_printing_tag_rate_limit_key, rate=_printing_tag_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_submit_artist_writein_vote(request: HttpRequest) -> HttpResponse:
    """
    Submit an artist write-in vote: either an existing-artist pick from
    `post_artist_autocomplete` (`artistId` - the normal path, per the owner's spec) or free text
    naming an artist not in any candidate list (`freeText`). Resolves to a `CanonicalArtist` row
    (reusing an existing one case-insensitively, or creating a new one -
    `_resolve_or_create_writein_artist`), then casts a normal USER-source `CardArtistVote`
    through EXACTLY the same machinery as `post_submit_artist_vote` above - same weight, same
    consensus gates (`resolve_and_persist_artist`, `cardpicker.artist_consensus` - untouched by
    this feature), same rate budget (reuses `_printing_tag_rate_limit_key`/
    `_printing_tag_rate_limit_rate`, i.e. `PRINTING_TAG_SUBMISSION_RATE`, not a separate budget).
    Write-ins get no special treatment in consensus: a single typo can't resolve a card by
    itself, and junk dies as UNRESOLVED/CONTESTED per the standard gates, same as any other
    artist vote.

    Deliberately does NOT accept an `isUnknown` flag - that "definitively unlisted/unknown
    artist" path is still served by `post_submit_artist_vote` alone; this endpoint's whole
    reason to exist is suggesting an artist *by name*, and folding in a third, unrelated mode
    would blur that.

    No guard against an already-RESOLVED card's artist - mirrors `post_submit_artist_vote`/
    `post_submit_printing_tag`, neither of which gate on existing resolution status either; a
    vote is always accepted and folded into consensus (a resolved outcome can, in principle,
    flip if enough new votes disagree - the same behaviour as every other vote endpoint here).
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Rate limited", message="Too many artist vote submissions - please slow down."
            ).model_dump(),
            status=429,
        )

    req = SubmitArtistWriteInVoteRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)

    if (req.artistId is None) == (req.freeText is None):
        raise BadRequestException("Exactly one of artistId or freeText is required.")

    with transaction.atomic():
        artist, created_new_artist = _resolve_or_create_writein_artist(req.artistId, req.freeText)
        CardArtistVote.objects.filter(card=card, anonymous_id=req.anonymousId).delete()
        CardArtistVote.objects.create(
            card=card,
            artist=artist,
            is_unknown=False,
            anonymous_id=req.anonymousId,
            source=VoteSource.USER,
            user=_requesting_user(request),
            vote_surface=req.voteSurface,
        )
        resolved = resolve_and_persist_artist(card)

    consensus = _build_artist_consensus_response(card, resolved)
    return JsonResponse(
        SubmitArtistWriteInVoteResponse(
            isUnknown=consensus.isUnknown,
            voteTally=consensus.voteTally,
            resolvedArtist=consensus.resolvedArtist,
            castArtist=ArtistAutocompleteResult(id=artist.pk, name=artist.name),
            createdNewArtist=created_new_artist,
        ).model_dump()
    )


def _build_tag_consensus_entry(card: Card, tag: Tag) -> TagConsensusEntry:
    resolved = resolve_tag(card, tag)
    return TagConsensusEntry(
        tagName=tag.name,
        # a sensitive tag awaiting privileged approval reads as unresolved to the public
        # consensus surface - the pending state is a moderation-queue concern, not a voter one
        resolvedPolarity=None if isinstance(resolved, _PendingPrivileged) else resolved,
        netPolarity=get_tag_net_polarity(card, tag),
        tally=[
            TagVoteTallyEntry(polarity=entry["polarity"], count=entry["count"])
            for entry in get_tag_vote_tally(card, tag)
        ],
    )


@csrf_exempt
@ErrorWrappers.to_json
def post_tag_consensus(request: HttpRequest) -> HttpResponse:
    """
    Return the currently resolved tag-vote consensus for every seeded tag against a card, so a
    voter can see and toggle every tag's state in one call rather than fetching per-tag.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = TagConsensusRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    tags = Tag.objects.order_by("name")
    return JsonResponse(TagConsensusResponse(tags=[_build_tag_consensus_entry(card, tag) for tag in tags]).model_dump())


@csrf_exempt
@reject_untrusted_origin  # sessions now authenticate these writes - see cardpicker.security
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_printing_tag_rate_limit_key, rate=_printing_tag_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_submit_tag_vote(request: HttpRequest) -> HttpResponse:
    """
    Submit a vote on whether a specific tag applies to a card. Unlike printing/artist votes,
    this is `update_or_create` rather than delete-then-create: a card can carry independent,
    simultaneous votes across many different tags at once, so submitting a vote on one tag
    must not clear votes this same person has already cast on any other tag for this card.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Rate limited", message="Too many tag vote submissions - please slow down."
            ).model_dump(),
            status=429,
        )

    req = SubmitTagVoteRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    try:
        tag = Tag.objects.get(name=req.tagName)
    except Tag.DoesNotExist:
        raise BadRequestException(f"No tag found with name {req.tagName!r}.")
    if req.polarity not in (VotePolarity.APPLY, VotePolarity.NOT_APPLICABLE, RETRACT_POLARITY):
        raise BadRequestException(
            f"Invalid polarity {req.polarity!r} - must be 1 (apply), -1 (not applicable), or 0 (retract)."
        )

    _cast_tag_vote_and_resolve(
        card=card,
        tag=tag,
        anonymous_id=req.anonymousId,
        polarity=req.polarity,
        user=_requesting_user(request),
        vote_surface=req.voteSurface,
    )
    return JsonResponse(_build_tag_consensus_entry(card, tag).model_dump())


# Sentinel accepted by post_submit_tag_vote/_cast_tag_vote_and_resolve alongside the two real
# VotePolarity values - never persisted (VotePolarity.choices is unchanged), it means "delete
# my existing vote on this (card, tag) if I have one" - the untouched-with-no-votes state a
# tri-state attribute chip cycles back to. See docs/features/printing-tags.md's questionFeed
# section for why this didn't exist before the attribute-chip UI needed it: every prior tag
# voter (QueueTagQuestion, PrintingConfirmStrip, NoMatchReasonStrip) only ever asks apply-or-
# not-applicable, with no UI path back to "no opinion" once tapped.
RETRACT_POLARITY = 0


def _cast_tag_vote_and_resolve(
    card: Card, tag: Tag, anonymous_id: str, polarity: int, user: Optional[User], vote_surface: Optional[str] = None
) -> None:
    """
    The one write path for a tag vote - shared verbatim between `post_submit_tag_vote` and
    `post_report_card` (a report on a tag-mapped reason IS a tag vote plus an audit row), so
    the two entry points can never drift on how a vote lands or when consensus recomputes.
    `vote_surface` defaults to None for `post_report_card`'s call site - report-driven votes
    aren't a "surface" a person consciously chose to vote from in the same sense.
    """
    with transaction.atomic():
        if polarity == RETRACT_POLARITY:
            CardTagVote.objects.filter(card=card, tag=tag, anonymous_id=anonymous_id).delete()
        else:
            # `user` sits in defaults deliberately: the row reflects the *latest* submission
            # from this (card, tag, anonymous_id), so a later unauthenticated re-vote clears it.
            CardTagVote.objects.update_or_create(
                card=card,
                tag=tag,
                anonymous_id=anonymous_id,
                defaults={
                    "polarity": polarity,
                    "source": VoteSource.USER,
                    "user": user,
                    "vote_surface": vote_surface,
                },
            )
        resolve_and_persist_tag_votes(card)


# `AbstractWeightedVote.vote_surface` value stamped on every VoteSource.IMPLICIT vote - lets
# any future analysis distinguish these from every other source's surface values (see
# models.py's VoteSource.IMPLICIT docstring; "prior Tron condition 8" per the owner-ratified
# 2026-07-22 vote-weight scenario matrix).
IMPLICIT_VOTE_SURFACE = "display-editor-filter"

# Persisted tag-vote statuses an implicit vote must never be cast against (owner-ratified
# 2026-07-22 vote-weight scenario matrix, "write-side guards" / prior condition 8): a settled
# or in-flight-for-moderation pair shouldn't accept a low-weight nudge in either direction.
# Deliberately does NOT include CONTESTED/UNRESOLVED - an implicit vote on an already-contested
# or still-unresolved pair is exactly the ordinary case this feature exists to help settle.
_STATUSES_BLOCKING_IMPLICIT_VOTES = {
    TagVoteStatus.RESOLVED_APPLY,
    TagVoteStatus.RESOLVED_REJECT,
    TagVoteStatus.PENDING_APPROVAL,
}


def _cast_implicit_vote_and_resolve(card: Card, tag: Tag, anonymous_id: str) -> None:
    """
    Casts (or supersedes) one `VoteSource.IMPLICIT` vote for (card, tag, anonymous_id) - the
    /editor filter-chip signal fired when a person picks a candidate card while that tag's
    filter chip is active (docs/features/printing-tags.md's implicit-vote section). Silently a
    no-op (never an error - a guarded tag is an entirely normal case, not a client mistake) when:

      - `tag` is SENSITIVE (docs/features/moderation.md's approval queue is the only path for
        those; never a passive selection signal);
      - the pair's persisted `Card.tag_vote_statuses` entry is already
        RESOLVED_APPLY/RESOLVED_REJECT/PENDING_APPROVAL (`_STATUSES_BLOCKING_IMPLICIT_VOTES`);
      - an existing vote already occupies this exact (card, tag, anonymous_id) row and it is
        NOT itself an implicit vote. `CardTagVote`'s uniqueness constraint is keyed on
        (card, tag, anonymous_id) with no source dimension (models.py's `cardtagvote_unique_vote`
        - shared across every source), so an implicit vote may only ever create a fresh row or
        update a row that is ALREADY implicit ("supersede must not collide" - a later implicit
        pick by the same identity replaces the earlier one, never a real vote cast by that same
        identity). The check-then-write is done under `select_for_update()` (2026-07-22
        hardening, post-review) rather than a plain, unlocked `SELECT`: an unlocked read leaves a
        TOCTOU window where a real vote inserted by this same identity between the read and the
        `update_or_create` below would be silently clobbered to `IMPLICIT` - locking the existing
        row (when one exists) for the rest of this transaction serializes against any concurrent
        write to that same row, closing that window. (A genuinely brand-new row - no existing
        vote at all yet - has nothing to lock; a true simultaneous double-create race there is a
        narrower, pre-existing gap shared with every other `update_or_create`/`get_or_create` call
        site in this module, not introduced by this function.)

    Re-runs `resolve_and_persist_tag_votes` in the same transaction as the write, same as
    `_cast_tag_vote_and_resolve`.
    """
    if tag.moderation_class == TagModerationClass.SENSITIVE:
        return
    if card.tag_vote_statuses.get(tag.name) in _STATUSES_BLOCKING_IMPLICIT_VOTES:
        return
    with transaction.atomic():
        existing_source = (
            CardTagVote.objects.select_for_update()
            .filter(card=card, tag=tag, anonymous_id=anonymous_id)
            .values_list("source", flat=True)
            .first()
        )
        if existing_source is not None and existing_source != VoteSource.IMPLICIT:
            return
        CardTagVote.objects.update_or_create(
            card=card,
            tag=tag,
            anonymous_id=anonymous_id,
            defaults={
                "polarity": VotePolarity.APPLY,
                "source": VoteSource.IMPLICIT,
                "user": None,
                "vote_surface": IMPLICIT_VOTE_SURFACE,
            },
        )
        resolve_and_persist_tag_votes(card)


def _retract_implicit_vote_and_resolve(card: Card, tag: Tag, anonymous_id: str) -> None:
    """
    Withdraws a previously-cast implicit vote for (card, tag, anonymous_id) - the /editor
    filter-chip deselect path. The `source=VoteSource.IMPLICIT` filter is load-bearing: this
    must only ever delete a row that IS an implicit vote, never a real vote that happens to
    share the same (card, tag, anonymous_id) key - deselecting a chip must never destroy
    someone's deliberate vote. A no-op (no re-resolve) when there was nothing to delete.
    """
    with transaction.atomic():
        deleted, _ = CardTagVote.objects.filter(
            card=card, tag=tag, anonymous_id=anonymous_id, source=VoteSource.IMPLICIT
        ).delete()
        if deleted:
            resolve_and_persist_tag_votes(card)


def _implicit_vote_rate_limit_rate(group: str, request: HttpRequest) -> str:
    # separate, tighter budget from PRINTING_TAG_SUBMISSION_RATE - see that setting's own
    # comment; a callable (not a plain string) for the same override-ability reason as
    # `_printing_tag_rate_limit_rate`.
    rate: str = settings.PRINTING_TAG_IMPLICIT_SUBMISSION_RATE
    return rate


@csrf_exempt
@reject_untrusted_origin  # sessions now authenticate these writes - see cardpicker.security
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_printing_tag_rate_limit_key, rate=_implicit_vote_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_cast_implicit_vote(request: HttpRequest) -> HttpResponse:
    """
    Casts an implicit vote for every tag named in `tagNames` against the picked card - the
    /editor filter-chip signal fired when a person selects a candidate card while those chips
    are active (docs/features/printing-tags.md's implicit-vote section). Each tag is
    independently guarded (see `_cast_implicit_vote_and_resolve`) and an unknown tag name is
    silently skipped - an empty, partially-guarded, or entirely-guarded `tagNames` list is a
    harmless no-op, never an error, since a person picking a card with no filters active (or
    filters that happen to already be resolved/sensitive) is an entirely normal case.

    Rate-limited via the separate, tighter `PRINTING_TAG_IMPLICIT_SUBMISSION_RATE` budget - see
    that setting's own comment for why this doesn't share `PRINTING_TAG_SUBMISSION_RATE`.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Rate limited", message="Too many implicit vote submissions - please slow down."
            ).model_dump(),
            status=429,
        )

    req = CastImplicitVoteRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    tags_by_name = {tag.name: tag for tag in Tag.objects.filter(name__in=req.tagNames)}
    for tag_name in req.tagNames:
        tag = tags_by_name.get(tag_name)
        if tag is None:
            continue
        _cast_implicit_vote_and_resolve(card, tag, req.anonymousId)

    return JsonResponse(
        TagConsensusResponse(tags=[_build_tag_consensus_entry(card, tag) for tag in tags_by_name.values()]).model_dump()
    )


@csrf_exempt
@reject_untrusted_origin  # sessions now authenticate these writes - see cardpicker.security
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_printing_tag_rate_limit_key, rate=_implicit_vote_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_retract_implicit_vote(request: HttpRequest) -> HttpResponse:
    """
    Withdraws a single implicit vote - the /editor filter-chip deselect path. See
    `_retract_implicit_vote_and_resolve` for the guard that stops this from ever deleting a
    real vote instead.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Rate limited", message="Too many implicit vote submissions - please slow down."
            ).model_dump(),
            status=429,
        )

    req = RetractImplicitVoteRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    try:
        tag = Tag.objects.get(name=req.tagName)
    except Tag.DoesNotExist:
        raise BadRequestException(f"No tag found with name {req.tagName!r}.")

    _retract_implicit_vote_and_resolve(card, tag, req.anonymousId)
    return JsonResponse(_build_tag_consensus_entry(card, tag).model_dump())


def _card_report_rate_limit_rate(group: str, request: HttpRequest) -> str:
    # callable for the same reason as _printing_tag_rate_limit_rate: a plain string would be
    # bound at import time and impossible to override in tests
    rate: str = settings.CARD_REPORT_RATE
    return rate


@csrf_exempt
@reject_untrusted_origin
@ratelimit(  # type: ignore  # `django-ratelimit` does not implement decorator typing correctly
    key=_printing_tag_rate_limit_key, rate=_card_report_rate_limit_rate, method="POST", block=False
)
@ErrorWrappers.to_json
def post_report_card(request: HttpRequest) -> HttpResponse:
    """
    Report a card (the flag button on the card detail modal - see docs/features/moderation.md).
    Always writes a CardReport audit row; for reasons that map onto a sensitive tag
    (nsfw/low_quality/wrong_card - see sensitive_tags.REPORT_REASON_TO_TAG_NAME) it also casts
    a positive CardTagVote through the exact same write path as 2/submitTagVote/, inside one
    transaction. If the mapped tag hasn't been seeded yet (`seed_sensitive_tags` not run), the
    report still lands and the vote is skipped - same graceful degradation as the no-match
    reason strips. broken_image/other write the report row only.

    Rate limited per anonymous ID (IP fallback) via CARD_REPORT_RATE (default 10/day) - the
    vote only happens inside this view, so the one limit covers both effects. Same
    single-worker in-process-cache caveat as post_submit_printing_tag.
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    if getattr(request, "limited", False):
        return JsonResponse(
            ErrorResponse(
                name="Report limit reached",
                message="You've sent quite a few reports today - please try again tomorrow.",
            ).model_dump(),
            status=429,
        )

    req = ReportCardRequest.model_validate(json.loads(request.body))
    # the schema declares maxLength 280 but quicktype's generated pydantic model doesn't carry
    # constraints - enforce here so an oversized body 400s instead of erroring at the DB column
    if req.text is not None and len(req.text) > 280:
        raise BadRequestException("Report text must be at most 280 characters.")
    card = _get_card_or_400(req.identifier)
    user = _requesting_user(request)

    vote_cast = False
    with transaction.atomic():
        CardReport.objects.create(
            card=card, anonymous_id=req.anonymousId, user=user, reason=req.reason.value, text=req.text or ""
        )
        tag_name = REPORT_REASON_TO_TAG_NAME.get(req.reason.value)
        if tag_name is not None:
            tag = Tag.objects.filter(name=tag_name).first()
            if tag is not None:
                _cast_tag_vote_and_resolve(
                    card=card, tag=tag, anonymous_id=req.anonymousId, polarity=VotePolarity.APPLY, user=user
                )
                vote_cast = True
    return JsonResponse(ReportCardResponse(reported=True, voteCast=vote_cast).model_dump())


def _paginate(items: Any, page: int) -> Any:
    """Shared page-index validation for the vote queue, mirroring `get_printing_tag_queue`'s
    own inline validation (not reused directly - that view's validation lives inline, not as
    a separate helper, and duplicating six lines here is simpler than refactoring it out from
    under a view this task doesn't otherwise touch)."""
    paginator: Paginator[Any] = Paginator(items, PRINTING_TAG_QUEUE_PAGE_SIZE)
    if not (paginator.num_pages >= page > 0):
        raise BadRequestException(f"Invalid page {page} specified - must be between 1 and {paginator.num_pages}.")
    return paginator


@csrf_exempt
@ErrorWrappers.to_json
def post_vote_queue(request: HttpRequest) -> HttpResponse:
    """
    Generalizes the review queue across all three vote kinds via a `kind` request field - a
    new sibling endpoint (POST, unlike `2/printingTagQueue/`'s GET) rather than a mutation of
    that one, which stays completely untouched/reachable for anything still calling it.

    One queue item per card for `kind=printing`/`artist` (`tagName` always null, exactly
    `2/printingTagQueue/`'s existing shape plus that field) - printing mode's candidate
    set/ordering is byte-for-byte what `get_printing_tag_queue` already does (unresolved,
    contested-first). Artist mode is the same shape, generalized to also include `CONTESTED`
    (a status `PrintingTagStatus` has no equivalent for - printing's own contested cards are
    already tagged `UNRESOLVED`, distinguished only by the ordering annotation).

    For `kind=tag`, one item per (card, tag) pair - see `get_tag_review_queue_pairs` for the
    persisted-state candidate filter and the net-polarity-weight/card-interleave ordering.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = VoteQueueRequest.model_validate(json.loads(request.body))

    if req.kind == VoteQueueKind.tag:
        pairs = get_tag_review_queue_pairs()
        paginator = _paginate(pairs, req.page)
        page_pairs = paginator.page(req.page).object_list
        cards_by_id = {card.pk: card for card in Card.objects.filter(pk__in=[card_id for card_id, _ in page_pairs])}
        items = [
            VoteQueueItem(card=cards_by_id[card_id].serialise(), tagName=tag_name) for card_id, tag_name in page_pairs
        ]
    else:
        if req.kind == VoteQueueKind.printing:
            cards = Card.objects.filter(printing_tag_status=PrintingTagStatus.UNRESOLVED).annotate(
                is_contested=Case(When(pk__in=get_contested_card_ids(), then=1), default=0, output_field=IntegerField())
            )
        else:
            cards = Card.objects.filter(
                artist_vote_status__in=[ArtistVoteStatus.UNRESOLVED, ArtistVoteStatus.CONTESTED]
            ).annotate(
                is_contested=Case(
                    When(pk__in=get_contested_artist_card_ids(), then=1), default=0, output_field=IntegerField()
                )
            )
        cards = cards.order_by("-is_contested", "-date_created", "name")
        paginator = _paginate(cards, req.page)
        items = [VoteQueueItem(card=card.serialise(), tagName=None) for card in paginator.page(req.page).object_list]

    return JsonResponse(VoteQueueResponse(hits=paginator.count, pages=paginator.num_pages, items=items).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def get_question_feed(request: HttpRequest) -> HttpResponse:
    """
    The unified "What's That Card?" question feed (see cardpicker.question_feed and
    docs/features/printing-tags.md) - one question at a time rather than a paginated batch,
    since (unlike printingTagQueue/voteQueue) which question comes next depends on what this
    same voter has already answered, evaluated fresh on every call.
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")

    anonymous_id = request.GET.get("anonymousId")
    if not anonymous_id:
        raise BadRequestException("Missing required anonymousId query parameter.")

    item = get_next_question_feed_item(anonymous_id)
    remaining_estimate = get_remaining_estimate()
    return JsonResponse(QuestionFeedResponse(item=item, remainingEstimate=remaining_estimate).model_dump())


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_moderation_queue(request: HttpRequest) -> HttpResponse:
    """
    The moderator-only review queue (docs/features/moderation.md): (card, sensitive-tag)
    pairs whose status is pending_approval, most-reported first, each with its report count
    and up to three newest free-text excerpts from matching reports. Approve/Reject in the
    frontend cast the moderator's ordinary tag vote through 2/submitTagVote/ - this endpoint
    only serves the queue. 403 for anyone outside the Moderators group (the frontend hides
    the tab too, but hidden is not secured - this is the enforcement).
    """

    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ModerationQueueRequest.model_validate(json.loads(request.body))
    pairs = get_pending_approval_queue_pairs()
    paginator = _paginate(pairs, req.page)
    page_pairs = paginator.page(req.page).object_list

    page_card_ids = [card_id for card_id, _ in page_pairs]
    cards_by_id = {card.pk: card for card in Card.objects.filter(pk__in=page_card_ids)}
    tag_name_by_reason = REPORT_REASON_TO_TAG_NAME

    report_counts: dict[tuple[int, str], int] = {}
    for row in (
        CardReport.objects.filter(card_id__in=page_card_ids, reason__in=tag_name_by_reason)
        .values("card_id", "reason")
        .annotate(n=Count("id"))
    ):
        report_counts[(row["card_id"], tag_name_by_reason[row["reason"]])] = row["n"]

    excerpts: dict[tuple[int, str], list[str]] = defaultdict(list)
    excerpt_rows = (
        CardReport.objects.filter(card_id__in=page_card_ids, reason__in=tag_name_by_reason)
        .exclude(text="")
        .order_by("-created_at")
        .values("card_id", "reason", "text")
    )
    for excerpt_row in excerpt_rows:
        key = (excerpt_row["card_id"], tag_name_by_reason[excerpt_row["reason"]])
        if len(excerpts[key]) < 3:
            excerpts[key].append(excerpt_row["text"])

    items = [
        ModerationQueueItem(
            card=cards_by_id[card_id].serialise(),
            tagName=tag_name,
            reportCount=report_counts.get((card_id, tag_name), 0),
            reportExcerpts=excerpts.get((card_id, tag_name), []),
        )
        for card_id, tag_name in page_pairs
    ]
    return JsonResponse(
        ModerationQueueResponse(hits=paginator.count, pages=paginator.num_pages, items=items).model_dump()
    )


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_moderation_drives(request: HttpRequest) -> HttpResponse:
    """
    Moderator-only "recently added drives" list (Moderation > Drives tab -
    docs/features/moderation.md): every Source, newest-first, each with its card/cardback/
    token counts so a moderator can spot a bad or spammy drive at a glance and drill into
    removing individual cards or the whole thing via post_moderation_remove_card/_drive below.

    Ordered by `-pk` rather than a creation timestamp - Source has no date field of its own
    (one existed briefly in 2021 and was removed in favour of per-Card dates, see migration
    0004_auto_20210214_1126), and pk insertion order is a reliable enough proxy for "recently
    added" without introducing a new migration for a moderator-facing sort order.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ModerationDrivesRequest.model_validate(json.loads(request.body))
    sources = Source.objects.order_by("-pk").annotate(
        qty_cards=Count("card", filter=Q(card__card_type=CardTypes.CARD), distinct=True),
        qty_cardbacks=Count("card", filter=Q(card__card_type=CardTypes.CARDBACK), distinct=True),
        qty_tokens=Count("card", filter=Q(card__card_type=CardTypes.TOKEN), distinct=True),
    )
    paginator = _paginate(sources, req.page)
    items = [
        ModerationDriveItem(
            source=source.serialise(),
            qtyCards=source.qty_cards,
            qtyCardbacks=source.qty_cardbacks,
            qtyTokens=source.qty_tokens,
        )
        for source in paginator.page(req.page).object_list
    ]
    return JsonResponse(
        ModerationDrivesResponse(hits=paginator.count, pages=paginator.num_pages, items=items).model_dump()
    )


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_moderation_drive_cards(request: HttpRequest) -> HttpResponse:
    """
    Moderator-only card listing for a single drive (Moderation > Drives tab, drill-down from
    post_moderation_drives above) - the per-drive card/cardback/token counts on that list are
    just totals, this is where a moderator actually sees and picks individual cards to remove
    via post_moderation_remove_card.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ModerationDriveCardsRequest.model_validate(json.loads(request.body))
    source = _get_source_or_400(req.sourceId)
    cards = Card.objects.filter(source=source).order_by("name", "identifier")
    paginator = _paginate(cards, req.page)
    return JsonResponse(
        ModerationDriveCardsResponse(
            hits=paginator.count,
            pages=paginator.num_pages,
            source=source.serialise(),
            cards=[card.serialise() for card in paginator.page(req.page).object_list],
        ).model_dump()
    )


def _delete_card_from_index_safely(card: Card) -> None:
    """
    Mirrors `reindex_card_safely`'s error-swallow rationale (documents.py) but for removal -
    Postgres is authoritative for the delete; a failed Elasticsearch delete just leaves a
    stale doc that the next full reindex (`search_index --rebuild`) cleans up, so it must
    never block or partially-fail the moderator's actual delete action. Needs the live `Card`
    instance (not just its pk) to resolve the document, mirroring reindex_card_safely.
    """
    try:
        CardSearch().update([card], action="delete")
    except Exception:
        logger.exception("Failed to remove card %s from Elasticsearch after moderator deletion", card.identifier)


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_moderation_remove_card(request: HttpRequest) -> HttpResponse:
    """
    Permanently delete a single card (Moderation > Drives tab). Removes it from Elasticsearch
    before the Postgres delete (the ES document lookup needs the live Card instance), then
    deletes the row - irreversible, no soft-delete/undo, by design: this is a moderator-only
    action for spam/bad-content cleanup, not something voters trigger.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ModerationRemoveCardRequest.model_validate(json.loads(request.body))
    card = _get_card_or_400(req.identifier)
    _delete_card_from_index_safely(card)
    card.delete()
    return JsonResponse(ModerationRemoveCardResponse(removed=True).model_dump())


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_moderation_remove_drive(request: HttpRequest) -> HttpResponse:
    """
    Permanently delete an entire drive/source and every card it contributed (Moderation >
    Drives tab) - irreversible, same rationale as post_moderation_remove_card above. Bulk-
    removes from Elasticsearch by `source_pk` (CardSearch indexes this - see documents.py)
    before the Postgres delete, which cascades onto every Card row via Card.source's
    on_delete=CASCADE - one delete_by_query instead of one ES call per card, since a drive can
    carry thousands of cards.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ModerationRemoveDriveRequest.model_validate(json.loads(request.body))
    source = _get_source_or_400(req.sourceId)
    cards_removed = Card.objects.filter(source=source).count()
    try:
        CardSearch().search().filter("term", source_pk=str(source.pk)).delete()
    except Exception:
        logger.exception("Failed to bulk-remove source %s from Elasticsearch before deletion", source.pk)
    source.delete()
    return JsonResponse(ModerationRemoveDriveResponse(removed=True, cardsRemoved=cards_removed).model_dump())


def _serialise_review_cluster(cluster: ReviewCluster) -> ReviewClusterSummary:
    return ReviewClusterSummary(
        clusterId=cluster.cluster_id,
        size=cluster.size,
        signals=[
            ReviewClusterSignal(
                signalType=ReviewClusterSignalType(signal.signal_type),
                value=signal.value,
                memberCount=signal.member_count,
            )
            for signal in cluster.signals
        ],
        members=[
            ReviewClusterMember(identifier=m.identifier, name=m.name, smallThumbnailUrl=m.small_thumbnail_url)
            for m in cluster.members
        ],
    )


# Deterministic per-moderator anonymous_id (issue #262 item 2's "idempotent per (user, card)"
# ask) - reuses CardPrintingTag's EXISTING (card, anonymous_id) uniqueness/replace-on-resubmit
# machinery (see post_submit_printing_tag above) rather than inventing a second idempotency
# mechanism keyed on `user` directly. A stable, moderator-specific anonymous_id means a retried
# or repeated batch-confirm from the same moderator always replaces their own prior vote for
# that card rather than accumulating a second row - exactly "one human vote per card" scoped to
# THIS moderator, same as any other voter's anonymous_id scopes their own vote.
REVIEW_CLUSTER_CONFIRM_VOTE_SURFACE = "review_cluster_confirm"


def _review_cluster_confirm_anonymous_id(user: User) -> str:
    return f"review-cluster-confirm-{user.pk}"


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_review_cluster_list(request: HttpRequest) -> HttpResponse:
    """
    Moderator-only paginated listing of review-queue clusters (issue #262,
    docs/features/moderation.md), sorted by size descending (biggest batch-confirm payoff
    first) - see cardpicker.review_clusters for the clustering itself and its own cache/compute
    rationale. Only multi-card clusters are ever listed (a singleton carries no shared signal
    and isn't a useful batch-confirm target) - this endpoint's `hits`/`pages` are over that
    multi-card population, not the full review queue.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ReviewClusterListRequest.model_validate(json.loads(request.body))
    clusters = get_cached_review_clusters()
    paginator: Paginator[ReviewCluster] = Paginator(clusters, REVIEW_CLUSTER_PAGE_SIZE)
    if not (paginator.num_pages >= req.page > 0):
        raise BadRequestException(f"Invalid page {req.page} specified - must be between 1 and {paginator.num_pages}.")
    return JsonResponse(
        ReviewClusterListResponse(
            hits=paginator.count,
            pages=paginator.num_pages,
            items=[_serialise_review_cluster(c) for c in paginator.page(req.page).object_list],
        ).model_dump()
    )


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_review_cluster_detail(request: HttpRequest) -> HttpResponse:
    """
    Moderator-only single-cluster lookup (issue #262) - the drill-down from
    post_review_cluster_list a moderator lands on before batch-confirming. Served from the same
    cache the list endpoint uses (a few minutes of staleness here is harmless - the confirm
    action itself always re-validates against a fresh recompute, see
    post_confirm_review_cluster).
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ReviewClusterDetailRequest.model_validate(json.loads(request.body))
    cluster = find_cluster(get_cached_review_clusters(), req.clusterId)
    if cluster is None:
        raise BadRequestException(f"No review cluster found with id {req.clusterId!r}.")
    return JsonResponse(ReviewClusterDetailResponse(cluster=_serialise_review_cluster(cluster)).model_dump())


@csrf_exempt
@reject_untrusted_origin
@require_moderator
@ErrorWrappers.to_json
def post_confirm_review_cluster(request: HttpRequest) -> HttpResponse:
    """
    Moderator-only batch no-match confirmation (issue #262): casts the acting moderator's OWN
    human no-match vote (`CardPrintingTag(is_no_match=True, source=VoteSource.USER)`) for every
    card in `memberIdentifiers`, through the EXACT vote-casting path post_submit_printing_tag
    above already uses (same model, same fields, same resolve_and_persist_printing call) - no
    shortcut, no separate consensus rule for cluster-confirmed votes. Idempotent per (user,
    card) via a deterministic per-moderator anonymous_id (see
    _review_cluster_confirm_anonymous_id) rather than the client-generated one an ordinary vote
    carries - a retried or repeated confirm from the same moderator always replaces their own
    prior vote for that card, never accumulates a second one.

    `memberIdentifiers` is the frontend's own record of what the moderator actually saw and
    approved - NEVER re-expanded here to whatever the cluster currently contains. This view
    deliberately bypasses the list/detail endpoints' cache and recomputes clusters fresh
    (`compute_review_clusters()`) purely to validate that every submitted identifier is still a
    real member of the named cluster right now; a stale cache could otherwise let a moderator
    confirm a card that drifted out of the cluster (or that a concurrent action already
    resolved) without anyone noticing. Any identifier that isn't currently a member rejects the
    WHOLE request (400) rather than silently dropping it - the moderator's approval was of a
    specific set, not "whichever of these still qualify".
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    req = ConfirmReviewClusterRequest.model_validate(json.loads(request.body))
    if not req.memberIdentifiers:
        raise BadRequestException("memberIdentifiers must be a non-empty list.")

    fresh_clusters = compute_review_clusters()
    cluster = find_cluster(fresh_clusters, req.clusterId)
    if cluster is None:
        raise BadRequestException(
            f"No review cluster found with id {req.clusterId!r} - it may already be fully resolved."
        )

    current_member_identifiers = {m.identifier for m in cluster.members}
    # de-duplicate while preserving the caller's own submitted order, same convention as
    # elsewhere in this file where request-supplied ordering is echoed back verbatim.
    requested_identifiers = list(dict.fromkeys(req.memberIdentifiers))
    unknown_identifiers = [i for i in requested_identifiers if i not in current_member_identifiers]
    if unknown_identifiers:
        raise BadRequestException(
            f"The following identifiers are not currently members of cluster {req.clusterId!r} "
            f"(it may have changed since you last fetched it): {unknown_identifiers}. Refresh the "
            "cluster and try again."
        )

    moderator = _authenticated_user(request)
    anonymous_id = _review_cluster_confirm_anonymous_id(moderator)
    confirmed_identifiers: list[str] = []
    for identifier in requested_identifiers:
        card = _get_card_or_400(identifier)
        with transaction.atomic():
            CardPrintingTag.objects.filter(card=card, anonymous_id=anonymous_id).delete()
            CardPrintingTag.objects.create(
                card=card,
                printing=None,
                is_no_match=True,
                anonymous_id=anonymous_id,
                source=VoteSource.USER,
                user=moderator,
                vote_surface=REVIEW_CLUSTER_CONFIRM_VOTE_SURFACE,
            )
            resolve_and_persist_printing(card)
        confirmed_identifiers.append(identifier)

    invalidate_review_cluster_cache()
    logger.info(
        "Moderator %s batch-confirmed no-match for review cluster %s: %d card(s) - %s",
        moderator.username,
        req.clusterId,
        len(confirmed_identifiers),
        confirmed_identifiers,
    )

    return JsonResponse(
        ConfirmReviewClusterResponse(
            clusterId=req.clusterId, confirmedIdentifiers=confirmed_identifiers, votesCast=len(confirmed_identifiers)
        ).model_dump()
    )


@csrf_exempt
@ErrorWrappers.to_json
def get_whoami(request: HttpRequest) -> HttpResponse:
    """
    Report the requesting session's authentication state and roles, for the frontend's
    moderation UI gating (which is presentation only - the moderation endpoints enforce the
    Moderators group server-side regardless of what this reports). Anonymous voters never call
    this with a session, so for them it just reports the feature flags.

    Cross-origin callers must fetch with credentials:'include' or the session cookie is never
    attached and this always reports anonymous. Read-only (GET, no state change), so unlike the
    session-consuming POST views this needs no Origin check - the worst a cross-site caller
    could learn is their own login state, which CORS already restricts to allowlisted origins.

    `loginUrl`/`logoutUrl` are relative to this backend's root; the frontend prefixes its
    configured backend URL and appends `?next=<frontend URL>` to round-trip back (see
    accounts.adapter.FrontendRedirectAccountAdapter for what makes that redirect safe).
    """

    if request.method != "GET":
        raise BadRequestException("Expected GET request.")
    authenticated = request.user.is_authenticated
    return JsonResponse(
        WhoamiResponse(
            authenticated=authenticated,
            username=request.user.get_username() if authenticated else None,
            moderator=is_moderator(request.user),
            discordEnabled=settings.DISCORD_AUTH_ENABLED,
            loginUrl="/accounts/discord/login/" if settings.DISCORD_AUTH_ENABLED else None,
            logoutUrl="/accounts/logout/" if authenticated else None,
        ).model_dump()
    )


# region Saved decks (docs/proposals/proposal-g-user-accounts-saved-decks.md §3/§8)
#
# Every one of these endpoints treats `ciphertext`/nonces/`wrappedDek`/wrapped-master-key
# fields as opaque base64 strings - never decrypted, inspected, or searched server-side. That
# is the entire point of the §8 zero-knowledge amendment: this backend stores and returns
# bytes faithfully and enforces per-object ownership, nothing else.


def _b64_to_bytes_or_400(value: str, field_name: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise BadRequestException(f"{field_name!r} must be valid base64.")


def _bytes_to_b64(value: Union[bytes, memoryview]) -> str:
    return base64.b64encode(bytes(value)).decode("ascii")


def _authenticated_user(request: HttpRequest) -> User:
    """
    require_authenticated already 403s an anonymous request before the view body runs - this
    narrows request.user's type from Django's own `User | AnonymousUser` to plain `User` for
    every saved-decks view, rather than repeating an isinstance check in each one.
    """
    assert isinstance(request.user, User)
    return request.user


def _get_saved_deck_or_400(key: str) -> SavedDeck:
    try:
        return SavedDeck.objects.get(key=key)
    except (SavedDeck.DoesNotExist, DjangoValidationError, ValueError):
        raise BadRequestException(f"No saved deck found with key {key!r}.")


def _forbidden(message: str) -> HttpResponse:
    return JsonResponse(ErrorResponse(name="Forbidden", message=message).model_dump(), status=403)


def _prune_snapshot_ring(owner: User) -> None:
    """
    Keep only the SAVED_DECK_SNAPSHOT_RING_SIZE most-recently-created snapshot rows for `owner`
    - a fixed FIFO ring (decision 7), not a configurable quota. Called after every snapshot
    insert; a no-op once the ring is already at or under the limit.
    """
    keep_pks = list(
        SavedDeck.objects.filter(owner=owner, kind=SavedDeckKind.SNAPSHOT)
        .order_by("-created_at")
        .values_list("pk", flat=True)[:SAVED_DECK_SNAPSHOT_RING_SIZE]
    )
    SavedDeck.objects.filter(owner=owner, kind=SavedDeckKind.SNAPSHOT).exclude(pk__in=keep_pks).delete()


def _serialise_saved_deck(deck: SavedDeck) -> SavedDeckSummary:
    return SavedDeckSummary(
        key=str(deck.key),
        kind=LoadDeckResponseKind(deck.kind),
        ciphertext=_bytes_to_b64(deck.ciphertext),
        ciphertextNonce=_bytes_to_b64(deck.ciphertext_nonce),
        wrappedDek=_bytes_to_b64(deck.wrapped_dek),
        wrappedDekNonce=_bytes_to_b64(deck.wrapped_dek_nonce),
        createdAt=dateformat.format(deck.created_at, DATE_FORMAT),
        updatedAt=dateformat.format(deck.updated_at, DATE_FORMAT),
    )


@csrf_exempt
@require_authenticated
@ErrorWrappers.to_json
def get_saved_decks(request: HttpRequest) -> HttpResponse:
    """
    List every SavedDeck owned by the requesting user, newest-updated first. Returns full
    ciphertext per row (not just metadata) - since the deck's own title lives inside that
    ciphertext (§8), the client must decrypt each row to render a human-readable "My Decks"
    list; there is no server-visible name to return instead. Read-only (GET), so - like
    get_whoami - this needs no Origin check.
    """
    if request.method != "GET":
        raise BadRequestException("Expected GET request.")
    decks = SavedDeck.objects.filter(owner=_authenticated_user(request)).order_by("-updated_at")
    return JsonResponse(SavedDecksResponse(decks=[_serialise_saved_deck(deck) for deck in decks]).model_dump())


@csrf_exempt
@reject_untrusted_origin
@require_authenticated
@ErrorWrappers.to_json
def post_save_deck(request: HttpRequest) -> HttpResponse:
    """
    Upsert one SavedDeck. `key: null` creates; an existing `key` updates in place if owned by
    request.user, else 403. `kind` defaults to "deck"; a "snapshot" create skips
    SAVED_DECK_MAX_PER_USER's cap entirely and instead prunes the owner's snapshot rows down to
    the newest SAVED_DECK_SNAPSHOT_RING_SIZE afterwards (decision 7). There is no server-side
    name-uniqueness check - §8's Consequences section is explicit that this became a
    client-side-only concern once titles are encrypted.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")

    user = _authenticated_user(request)
    req = SaveDeckRequest.model_validate(json.loads(request.body))
    kind = SavedDeckKind(req.kind) if req.kind is not None else SavedDeckKind.DECK
    ciphertext = _b64_to_bytes_or_400(req.ciphertext, "ciphertext")
    ciphertext_nonce = _b64_to_bytes_or_400(req.ciphertextNonce, "ciphertextNonce")
    wrapped_dek = _b64_to_bytes_or_400(req.wrappedDek, "wrappedDek")
    wrapped_dek_nonce = _b64_to_bytes_or_400(req.wrappedDekNonce, "wrappedDekNonce")

    if req.key is not None:
        deck = _get_saved_deck_or_400(req.key)
        if deck.owner_id != user.id:
            return _forbidden("You do not own this saved deck.")
        deck.ciphertext = ciphertext
        deck.ciphertext_nonce = ciphertext_nonce
        deck.wrapped_dek = wrapped_dek
        deck.wrapped_dek_nonce = wrapped_dek_nonce
        deck.save(update_fields=["ciphertext", "ciphertext_nonce", "wrapped_dek", "wrapped_dek_nonce", "updated_at"])
        return JsonResponse(SaveDeckResponse(key=str(deck.key)).model_dump())

    if kind == SavedDeckKind.DECK:
        existing_deck_count = SavedDeck.objects.filter(owner=user, kind=SavedDeckKind.DECK).count()
        if existing_deck_count >= settings.SAVED_DECK_MAX_PER_USER:
            raise BadRequestException(
                f"You've reached the {settings.SAVED_DECK_MAX_PER_USER} saved deck limit - "
                f"delete an old one to save a new one."
            )

    deck = SavedDeck.objects.create(
        owner=user,
        kind=kind,
        ciphertext=ciphertext,
        ciphertext_nonce=ciphertext_nonce,
        wrapped_dek=wrapped_dek,
        wrapped_dek_nonce=wrapped_dek_nonce,
    )

    if kind == SavedDeckKind.SNAPSHOT:
        _prune_snapshot_ring(user)

    return JsonResponse(SaveDeckResponse(key=str(deck.key)).model_dump())


@csrf_exempt
@reject_untrusted_origin
@require_authenticated
@ErrorWrappers.to_json
def post_load_deck(request: HttpRequest) -> HttpResponse:
    """Fetch one SavedDeck's ciphertext by key. 403 if it belongs to someone else."""
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    req = LoadDeckRequest.model_validate(json.loads(request.body))
    deck = _get_saved_deck_or_400(req.key)
    if deck.owner_id != request.user.id:
        return _forbidden("You do not own this saved deck.")
    return JsonResponse(
        LoadDeckResponse(
            kind=LoadDeckResponseKind(deck.kind),
            ciphertext=_bytes_to_b64(deck.ciphertext),
            ciphertextNonce=_bytes_to_b64(deck.ciphertext_nonce),
            wrappedDek=_bytes_to_b64(deck.wrapped_dek),
            wrappedDekNonce=_bytes_to_b64(deck.wrapped_dek_nonce),
            createdAt=dateformat.format(deck.created_at, DATE_FORMAT),
            updatedAt=dateformat.format(deck.updated_at, DATE_FORMAT),
        ).model_dump()
    )


@csrf_exempt
@reject_untrusted_origin
@require_authenticated
@ErrorWrappers.to_json
def post_delete_deck(request: HttpRequest) -> HttpResponse:
    """Hard delete one SavedDeck by key. 403 if it belongs to someone else. No undo, by design
    - same precedent as moderationRemoveCard/moderationRemoveDrive."""
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    req = DeleteDeckRequest.model_validate(json.loads(request.body))
    deck = _get_saved_deck_or_400(req.key)
    if deck.owner_id != request.user.id:
        return _forbidden("You do not own this saved deck.")
    deck.delete()
    return JsonResponse(DeleteDeckResponse(deleted=True).model_dump())


@csrf_exempt
@require_authenticated
@ErrorWrappers.to_json
def get_crypto_profile(request: HttpRequest) -> HttpResponse:
    """
    Report the requesting user's zero-knowledge crypto parameters, or `exists: false` if none
    yet (the frontend's signal to run the first-save passphrase-creation flow). Read-only, so
    - like get_whoami/get_saved_decks - this needs no Origin check.
    """
    if request.method != "GET":
        raise BadRequestException("Expected GET request.")
    try:
        profile = UserCryptoProfile.objects.get(owner=_authenticated_user(request))
    except UserCryptoProfile.DoesNotExist:
        return JsonResponse(
            CryptoProfileResponse(
                exists=False,
                salt=None,
                kdfIterations=None,
                passphraseWrappedMasterKey=None,
                passphraseWrappedMasterKeyNonce=None,
                recoveryWrappedMasterKey=None,
                recoveryWrappedMasterKeyNonce=None,
            ).model_dump()
        )
    return JsonResponse(
        CryptoProfileResponse(
            exists=True,
            salt=_bytes_to_b64(profile.salt),
            kdfIterations=profile.kdf_iterations,
            passphraseWrappedMasterKey=_bytes_to_b64(profile.passphrase_wrapped_master_key),
            passphraseWrappedMasterKeyNonce=_bytes_to_b64(profile.passphrase_wrapped_master_key_nonce),
            recoveryWrappedMasterKey=_bytes_to_b64(profile.recovery_wrapped_master_key),
            recoveryWrappedMasterKeyNonce=_bytes_to_b64(profile.recovery_wrapped_master_key_nonce),
        ).model_dump()
    )


@csrf_exempt
@reject_untrusted_origin
@require_authenticated
@ErrorWrappers.to_json
def post_save_crypto_profile(request: HttpRequest) -> HttpResponse:
    """
    Create (first save) or replace (e.g. a passphrase change, which re-wraps the passphrase
    slot - see §8) the requesting user's crypto profile. Every field is opaque to the backend
    except kdfIterations, checked against SAVED_DECK_MIN_KDF_ITERATIONS as a defensive floor
    against a buggy/malicious client persisting a weak key derivation. A passphrase change only
    ever replaces this one row - deck ciphertext/wrapped-DEKs are never touched by it.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    req = SaveCryptoProfileRequest.model_validate(json.loads(request.body))
    if req.kdfIterations < settings.SAVED_DECK_MIN_KDF_ITERATIONS:
        raise BadRequestException(f"kdfIterations must be at least {settings.SAVED_DECK_MIN_KDF_ITERATIONS}.")
    UserCryptoProfile.objects.update_or_create(
        owner=_authenticated_user(request),
        defaults={
            "salt": _b64_to_bytes_or_400(req.salt, "salt"),
            "kdf_iterations": req.kdfIterations,
            "passphrase_wrapped_master_key": _b64_to_bytes_or_400(
                req.passphraseWrappedMasterKey, "passphraseWrappedMasterKey"
            ),
            "passphrase_wrapped_master_key_nonce": _b64_to_bytes_or_400(
                req.passphraseWrappedMasterKeyNonce, "passphraseWrappedMasterKeyNonce"
            ),
            "recovery_wrapped_master_key": _b64_to_bytes_or_400(
                req.recoveryWrappedMasterKey, "recoveryWrappedMasterKey"
            ),
            "recovery_wrapped_master_key_nonce": _b64_to_bytes_or_400(
                req.recoveryWrappedMasterKeyNonce, "recoveryWrappedMasterKeyNonce"
            ),
        },
    )
    return JsonResponse(SaveCryptoProfileResponse(saved=True).model_dump())


@csrf_exempt
@reject_untrusted_origin
@require_authenticated
@ErrorWrappers.to_json
def post_reset_saved_decks(request: HttpRequest) -> HttpResponse:
    """
    The data-destroying last resort (§8's "Account reset"): deletes every SavedDeck and the
    crypto profile for the requesting user, so a fresh passphrase/recovery-key pair can be
    created on the next save. Requires an explicit `confirm: true` - irreversible, and the
    frontend must have already shown the "this permanently deletes your N saved decks"
    confirmation before calling it. There is no admin-side or Discord-derived decryption/escrow
    path, by design (§8's "Explicitly rejected") - require_authenticated is the only gate,
    exactly as it is for every other saved-decks endpoint.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    user = _authenticated_user(request)
    req = ResetSavedDecksRequest.model_validate(json.loads(request.body))
    if not req.confirm:
        raise BadRequestException("Set confirm=true to proceed - this is a destructive, irreversible action.")
    with transaction.atomic():
        deleted_deck_count, _ = SavedDeck.objects.filter(owner=user).delete()
        UserCryptoProfile.objects.filter(owner=user).delete()
    return JsonResponse(ResetSavedDecksResponse(deletedDeckCount=deleted_deck_count).model_dump())


# endregion


# region Per-deck share links (docs/proposals/proposal-g-user-accounts-saved-decks.md's
# "PR-5, post-v1: per-deck share links")
#
# See cardpicker.models.SavedDeckShare's docstring for the frozen-snapshot deviation from the
# spec's literal prose, forced by the fact that post_save_deck (above) already mints a fresh DEK
# on every ordinary save, not just the first one. Every ciphertext/nonce/wrapped-key field below
# is exactly as opaque to this backend as the rest of the saved-decks surface - never decrypted,
# inspected, or searched server-side.


def _get_saved_deck_share_or_400(share_id: str) -> SavedDeckShare:
    try:
        return SavedDeckShare.objects.select_related("deck").get(id=share_id)
    except (SavedDeckShare.DoesNotExist, DjangoValidationError, ValueError):
        raise BadRequestException(f"No share found with id {share_id!r}.")


def _serialise_deck_share(share: SavedDeckShare) -> DeckShareSummary:
    return DeckShareSummary(
        shareId=str(share.id),
        deckKey=str(share.deck.key),
        createdAt=dateformat.format(share.created_at, DATE_FORMAT),
        expiresAt=dateformat.format(share.expires_at, DATE_FORMAT) if share.expires_at is not None else None,
    )


@csrf_exempt
@reject_untrusted_origin
@require_authenticated
@ErrorWrappers.to_json
def post_create_deck_share(request: HttpRequest) -> HttpResponse:
    """
    Create a share link for one of the requesting user's own decks (never a snapshot - sharing
    is a `kind=deck` concept only). The client has already unwrapped the deck's current DEK
    (via its own already-unlocked master key) and re-wrapped that same DEK under a fresh,
    client-generated `shareKey` that never reaches this server - `wrappedDek`/`wrappedDekNonce`
    below are that re-wrapping's result, opaque to us either way.

    This server copies the referenced deck's CURRENT ciphertext/nonce into the new
    SavedDeckShare row at this moment - a frozen snapshot, not a live reference (see
    SavedDeckShare's docstring for why this is required, not optional, given post_save_deck's
    existing fresh-DEK-per-save behaviour).
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    user = _authenticated_user(request)
    req = CreateDeckShareRequest.model_validate(json.loads(request.body))
    deck = _get_saved_deck_or_400(req.deckKey)
    if deck.owner_id != user.id:
        return _forbidden("You do not own this saved deck.")
    if deck.kind != SavedDeckKind.DECK:
        raise BadRequestException("Only named decks can be shared, not snapshots.")

    existing_share_count = SavedDeckShare.objects.filter(deck=deck).count()
    if existing_share_count >= settings.SAVED_DECK_SHARE_MAX_PER_DECK:
        raise BadRequestException(
            f"This deck already has the maximum of {settings.SAVED_DECK_SHARE_MAX_PER_DECK} active "
            f"shares - revoke an old one to create a new one."
        )

    expires_at = timezone.now() + timedelta(days=req.expiresInDays) if req.expiresInDays is not None else None
    share = SavedDeckShare.objects.create(
        deck=deck,
        ciphertext=deck.ciphertext,
        ciphertext_nonce=deck.ciphertext_nonce,
        wrapped_dek=_b64_to_bytes_or_400(req.wrappedDek, "wrappedDek"),
        wrapped_dek_nonce=_b64_to_bytes_or_400(req.wrappedDekNonce, "wrappedDekNonce"),
        expires_at=expires_at,
    )
    return JsonResponse(
        CreateDeckShareResponse(
            shareId=str(share.id),
            createdAt=dateformat.format(share.created_at, DATE_FORMAT),
        ).model_dump()
    )


@csrf_exempt
@require_authenticated
@ErrorWrappers.to_json
def get_deck_shares(request: HttpRequest) -> HttpResponse:
    """
    List every share the requesting user owns (across all of their decks) - shareId, which deck
    it belongs to, and its creation/expiry dates only, never ciphertext/wrapped-key material
    (that's only ever served to a recipient holding the actual shareId, via get_shared_deck).
    Read-only (GET), so - like get_saved_decks - this needs no Origin check. Includes shares
    already past their own expires_at (still visible/revocable, just no longer fetchable by a
    recipient - see get_shared_deck).
    """
    if request.method != "GET":
        raise BadRequestException("Expected GET request.")
    user = _authenticated_user(request)
    shares = SavedDeckShare.objects.filter(deck__owner=user).select_related("deck").order_by("-created_at")
    return JsonResponse(DeckSharesResponse(shares=[_serialise_deck_share(share) for share in shares]).model_dump())


@csrf_exempt
@reject_untrusted_origin
@require_authenticated
@ErrorWrappers.to_json
def post_revoke_deck_share(request: HttpRequest) -> HttpResponse:
    """
    Hard delete one share by shareId - 403 if it belongs to a deck the requesting user doesn't
    own. The link is dead for all future get_shared_deck fetches immediately. No undo, same
    precedent as post_delete_deck. The spec's "paranoid" rotate-on-revoke option is deliberately
    NOT a parameter here - rotating the live deck's own DEK only requires re-encrypting that
    deck's content under a fresh key, which is exactly what an ordinary post_save_deck call
    already does on every save (see cardpicker.models.SavedDeckShare's docstring) - the frontend
    orchestrates "revoke, then optionally re-save the deck" as two calls to already-existing
    endpoints rather than this one growing bespoke re-encryption logic it can't actually perform
    server-side anyway (the server never holds a deck's plaintext).
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    user = _authenticated_user(request)
    req = RevokeDeckShareRequest.model_validate(json.loads(request.body))
    share = _get_saved_deck_share_or_400(req.shareId)
    if share.deck.owner_id != user.id:
        return _forbidden("You do not own this share.")
    share.delete()
    return JsonResponse(RevokeDeckShareResponse(deleted=True).model_dump())


@csrf_exempt
@ErrorWrappers.to_json
def post_get_shared_deck(request: HttpRequest) -> HttpResponse:
    """
    The recipient-side fetch - deliberately UNAUTHENTICATED (no session/cookie involved at all,
    so no `credentials: "include"`, no CSRF token, and no Origin check: this is a public,
    read-only lookup by shareId alone, nothing here can be forged into a state change on
    anyone's behalf). Returns this share's own frozen ciphertext + its wrapped DEK; the
    recipient unwraps that DEK using the shareKey from their URL's fragment, which this request
    body never contains. A revoked (deleted) or expired share both look identical to the
    recipient: "No share found" (400) - see SavedDeckShare.is_expired.
    """
    if request.method != "POST":
        raise BadRequestException("Expected POST request.")
    req = GetSharedDeckRequest.model_validate(json.loads(request.body))
    share = _get_saved_deck_share_or_400(req.shareId)
    if share.is_expired():
        raise BadRequestException(f"No share found with id {req.shareId!r}.")
    return JsonResponse(
        GetSharedDeckResponse(
            ciphertext=_bytes_to_b64(share.ciphertext),
            ciphertextNonce=_bytes_to_b64(share.ciphertext_nonce),
            wrappedDek=_bytes_to_b64(share.wrapped_dek),
            wrappedDekNonce=_bytes_to_b64(share.wrapped_dek_nonce),
            createdAt=dateformat.format(share.created_at, DATE_FORMAT),
        ).model_dump()
    )


# endregion
