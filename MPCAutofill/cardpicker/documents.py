import logging

from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer

from django.db.models import QuerySet

from cardpicker.models import Card

logger = logging.getLogger(__name__)

# custom elasticsearch analysers are configured here to add the `asciifolding` filter, which handles accents:
# https://www.elastic.co/guide/en/elasticsearch/reference/7.17/analysis-asciifolding-tokenfilter.html
# https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis-standard-analyzer.html
precise_analyser = analyzer("precise_analyser", tokenizer="keyword", filter=["apostrophe", "lowercase", "asciifolding"])
fuzzy_analyser = analyzer("fuzzy_analyser", tokenizer="standard", filter=["apostrophe", "lowercase", "asciifolding"])


@registry.register_document
class CardSearch(Document):
    source_pk = fields.TextField(attr="get_source_pk", analyzer="keyword")
    searchq_fuzzy = fields.TextField(attr="searchq", analyzer=fuzzy_analyser)
    searchq_precise = fields.TextField(attr="searchq", analyzer=precise_analyser)
    searchq_keyword = fields.KeywordField(attr="searchq")
    card_type = fields.KeywordField()
    date_created = fields.DateField()
    date_modified = fields.DateField()
    language = fields.TextField(analyzer=precise_analyser)  # case insensitivity is one less thing which can go wrong
    tags = fields.KeywordField()  # all elasticsearch fields support arrays by default
    expansion_code = fields.KeywordField(attr="get_expansion_code")
    collector_number = fields.KeywordField(attr="get_collector_number")
    # Search-operator syntax (2026-07-22) fields below - see cardpicker.search.operator_parser
    # and cardpicker.search.search_functions' operator-filter wiring for the consumer side.
    # `artist`/`artist_text` both derive from the same `get_indexed_artist_name` model method -
    # mirrors this Document's own pre-existing searchq_fuzzy/searchq_precise/searchq_keyword
    # three-fields-one-attr pattern above. `artist` (untouched casing) is the exact/keyword
    # form; `artist_text` runs the same `fuzzy_analyser` used for card names so `artist:guay`
    # matches a token inside "Rebecca Guay" case-insensitively.
    artist = fields.KeywordField(attr="get_indexed_artist_name")
    artist_text = fields.TextField(attr="get_indexed_artist_name", analyzer=fuzzy_analyser)
    # `border_color`/`frame` are lowercased at the source (`Card.get_border_color`/`get_frame`)
    # rather than via an ES normalizer, so a plain KeywordField is already case-insensitive -
    # same "handle casing in Python, not in the mapping" choice `get_expansion_code` already
    # made with its own `.upper()`.
    border_color = fields.KeywordField(attr="get_border_color")
    frame = fields.KeywordField(attr="get_frame")
    # Indexed per the mapping-additions spec but not yet wired to a search operator - reserved
    # for a future `showcase:`/`extendedart:`-style operator or for `fullArtOnly`/`borderlessOnly`
    # to eventually read from the index instead of their existing live ResolvedPrinting lookup
    # (cardpicker.printing_consensus.get_resolved_printings) - that lookup is untouched here.
    frame_effects = fields.KeywordField(attr="get_frame_effects")
    full_art = fields.BooleanField(attr="get_full_art")

    class Index:
        # name of the elasticsearch index
        name = "cards"
        # see Elasticsearch Indices API reference for available settings
        settings = {"number_of_shards": 5, "number_of_replicas": 0}

    class Django:
        model = Card
        fields = ["identifier", "priority", "dpi", "size"]

    def get_queryset(self) -> QuerySet[Card]:
        # https://django-elasticsearch-dsl.readthedocs.io/en/latest/fields.html#handle-relationship-with-nestedfield-objectfield
        # `inferred_canonical_card` is eager-loaded alongside `canonical_card` because
        # `get_expansion_code`/`get_collector_number` (below) now fall back to it for
        # RESOLVED cards - without this, reindexing would N+1 query per RESOLVED card. The
        # `__artist`/`__printing_metadata`/`canonical_artist`/`inferred_canonical_artist` legs
        # added 2026-07-22 exist for the same reason, now that `get_indexed_artist_name` and
        # `_get_indexed_printing_metadata` (models.py) walk those same relations per card.
        return (
            super()
            .get_queryset()
            .select_related(
                "canonical_card",
                "canonical_card__expansion",
                "canonical_card__artist",
                "canonical_card__printing_metadata",
                "canonical_artist",
                "inferred_canonical_card",
                "inferred_canonical_card__expansion",
                "inferred_canonical_card__artist",
                "inferred_canonical_card__printing_metadata",
                "inferred_canonical_artist",
            )
        )


def reindex_card_safely(card: Card) -> None:
    """
    Pushes `card`'s current state into the Elasticsearch index, catching and logging any
    failure rather than raising. Postgres is the source of truth for vote/consensus state -
    by the time this runs, that write has already committed - so a search-index hiccup (ES
    down, a transient connection error, etc.) must never break vote submission or roll back
    a DB write that already succeeded. Shared by every vote-consensus module that needs to
    push a single card's change into the index immediately, rather than waiting for the next
    scheduled `update_database` re-scan or a manual `search_index --rebuild`.
    """
    try:
        CardSearch().update([card], action="index")
    except Exception:
        logger.exception("Failed to reindex card %s into Elasticsearch after a vote-consensus update", card.identifier)
