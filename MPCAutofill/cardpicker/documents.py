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
        # RESOLVED cards - without this, reindexing would N+1 query per RESOLVED card.
        return (
            super()
            .get_queryset()
            .select_related(
                "canonical_card",
                "canonical_card__expansion",
                "inferred_canonical_card",
                "inferred_canonical_card__expansion",
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
