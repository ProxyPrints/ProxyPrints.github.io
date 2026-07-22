import pycountry

DATE_FORMAT = "jS F, Y"
DEFAULT_LANGUAGE = pycountry.languages.get(alpha_2="EN")

NEW_CARDS_PAGE_SIZE = 12
NEW_CARDS_DAYS = 14
PRINTING_TAG_QUEUE_PAGE_SIZE = 24
EDITOR_SEARCH_MAX_QUERIES = 300
CARDS_PAGE_SIZE = 1000
EXPLORE_SEARCH_MAX_PAGE_SIZE = 100
REVIEW_CLUSTER_PAGE_SIZE = 24

MAX_SIZE_MB = 30
NSFW = "NSFW"

# docs/proposals/proposal-g-user-accounts-saved-decks.md decision 7 - a fixed FIFO ring size,
# deliberately NOT a setting (it's an implementation safety valve, not a user-facing quota).
SAVED_DECK_SNAPSHOT_RING_SIZE = 5

# Artist write-in autocomplete/vote (docs/features/printing-tags.md's write-in bullet). All
# implementation safety valves, not user-facing quotas - deliberately not `env()` settings, same
# reasoning as SAVED_DECK_SNAPSHOT_RING_SIZE above.
ARTIST_AUTOCOMPLETE_MIN_QUERY_LENGTH = 2
ARTIST_AUTOCOMPLETE_MAX_QUERY_LENGTH = 100
ARTIST_AUTOCOMPLETE_PAGE_SIZE = 10
ARTIST_WRITEIN_NAME_MAX_LENGTH = 100
