"""
Synthetic MTGAC-bulk-export-shaped fixtures for cardpicker.artist_external_links tests.

DELIBERATELY SYNTHETIC - every artist name, URL, domain, location, and email below is invented,
none of it is copied from any real MTGAC export. **This is NOT a licensing question** - MTGAC's
operator has granted permission to distribute their data (owner email correspondence, 2026-07-29;
that's the entire reason they stood the bulk endpoint up for this project in the first place), so
there is no licensing barrier to committing their compilation.

**The reason these stay synthetic is third-party personal data, which sits outside anything MTGAC
is able to license on the affected individuals' behalf.** The real export contains personal email
addresses belonging to real artists, mis-filed into `twitter`/`website` link fields
(`_clean_url_value` in cardpicker/artist_external_links.py drops these at runtime - correct
production behaviour). MTGAC can grant rights to their own compilation; they cannot consent, on an
artist's behalf, to that artist's personal email address being republished, permanently and
searchably, in a public repository. That's third-party personal data, not MTGAC's to license away
- the same reasoning applies more weakly to the rest of each record's content, but the emails are
the clear line. (What's still genuinely open with MTGAC, separately: name aliases/variants and a
per-record last-updated/export-version field - not the licence.)

Synthetic fixtures are also better engineering independent of any of the above: stable across
MTGAC re-exports, minimal, and each hazard shape below is exercised DELIBERATELY (one fixture per
hazard, named for what it tests) rather than incidentally wherever it happened to occur in a
2,389-record real export.

These fixtures reproduce the real export's *shapes* only (a boolean-string masquerading as a
link, a scheme-less URL, an email filed in the wrong field, an affiliate query parameter, ...),
verified against the real sample during development but never copied from it. Do not "improve"
these with real names/URLs/emails from a live export - real personal email addresses specifically
must never land in this file, regardless of MTGAC's own permission to distribute the rest of
their data.
"""

from typing import Any, Optional


def raw_record(
    name: str,
    *,
    website: Optional[str] = None,
    pageUrl: Optional[str] = None,
    location: Optional[str] = None,
    links: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Builds one MTGAC-bulk-export-shaped raw record, matching the real shape: `name`/`pageUrl`/
    `location`/`website` are top-level, everything else lives under `links`."""
    return {
        "name": name,
        "pageUrl": pageUrl,
        "location": location,
        "website": website,
        "links": links or {},
    }


# A fully "clean" record: every allowlisted field populated with a well-formed URL, an affiliate
# parameter on omalink, and a true signature-service flag - the happy path.
CLEAN_RECORD = raw_record(
    "Aurelia Thistledown",
    website="https://aureliathistledown.example/",
    pageUrl="https://www.mtgartistconnection.example/artist/Aurelia%20Thistledown",
    location="Testland",
    links={
        "instagram": "https://www.instagram.example/aureliathistledown/",
        "twitter": "https://twitter.example/AureliaThistle",
        "facebook": "https://www.facebook.example/aureliathistledown/",
        "youtube": "https://www.youtube.example/@aureliathistledown",
        "bluesky": "https://bsky.example/profile/aureliathistledown.example",
        "patreon": "https://www.patreon.example/aureliathistledown",
        "artstation": "https://www.artstation.example/aureliathistledown",
        "inprnt": "https://www.inprnt.example/gallery/aureliathistledown/",
        "mountainmage": "https://mountainmagesigs.example/products/aurelia-thistledown",
        "omalink": "https://original-art.example/collections/aurelia-thistledown?rfsn=1234567.89abcd",
        "markssignatureservice": "true",
    },
)

# `markssignatureservice` literal "false", `mountainmage` literal "false" ("not offered", not a
# URL) - the boolean-string-masquerading-as-a-link hazard on two different fields at once.
BOOLEAN_FLAG_RECORD = raw_record(
    "Barnaby Quill",
    website="https://barnabyquill.example/",
    links={
        "mountainmage": "false",
        "markssignatureservice": "false",
    },
)

# Email address filed in `twitter` (excluded field regardless, but the hazard is real) - clean
# website still present.
EMAIL_IN_TWITTER_RECORD = raw_record(
    "Cassian Vex",
    website="https://cassianvex.example/",
    links={"twitter": "someone@example.invalid"},
)

# Email address filed in `website` itself - the allowlist's #1 priority field, so this one DOES
# affect the rendered links list (that slot is simply omitted, not fallen-through).
EMAIL_IN_WEBSITE_RECORD = raw_record(
    "Dorothea Wynn",
    website="info@example.invalid",
    links={"artstation": "https://www.artstation.example/dorotheawynn"},
)

# Scheme-less URLs on both `website` and `artstation`.
SCHEME_LESS_RECORD = raw_record(
    "Ezra Fenwick",
    website="ezrafenwick.example",
    links={"artstation": "artstation.example/ezrafenwick"},
)

# Leading/trailing whitespace, including an embedded newline (seen for real on one upstream
# `inprnt` value).
WHITESPACE_RECORD = raw_record(
    "Fiora Nightshade",
    website="https://fioranightshade.example/",
    links={"inprnt": "  https://www.inprnt.example/gallery/fiora  \n"},
)

# Bare non-URL text in `artstation` (an artist's own name, typo'd into the wrong field).
BARE_TEXT_RECORD = raw_record(
    "Gideon Marrow",
    website="https://gideonmarrow.example/",
    links={"artstation": "Gideon Marrow"},
)

# All 5 allowlisted fields populated - priority order / 5-cap verification.
FULL_ALLOWLIST_RECORD = raw_record(
    "Helia Sunstrike",
    website="https://heliasunstrike.example/",
    links={
        "artstation": "https://www.artstation.example/heliasunstrike",
        "inprnt": "https://www.inprnt.example/gallery/heliasunstrike/",
        "mountainmage": "https://mountainmagesigs.example/products/helia-sunstrike",
        "omalink": "https://original-art.example/collections/helia-sunstrike?rfsn=7654321.abcdef",
        "instagram": "https://www.instagram.example/heliasunstrike/",
    },
)

# No name at all - must be skipped when building a blob, never crash the whole batch.
MISSING_NAME_RECORD = raw_record("", website="https://example.invalid/")

# Scheme-ful handle-style URL in `website` (e.g. `https://www.example.com/@some.handle`, the
# YouTube/TikTok/Bluesky @handle shape - a real value of this exact shape was confirmed in the
# export during this fixture's own investigation, not reproduced here, per this file's own
# synthetic-only policy above). This value has an "@" followed by a segment containing a "." -
# everything `_EMAIL_RE` checks for - so it must survive ONLY because the scheme check runs
# first and short-circuits the email test entirely; a regression here silently drops a good URL
# as if it were an email (the bug this fixture was added to catch).
HANDLE_URL_RECORD = raw_record(
    "Imogen Thackeray",
    website="https://www.example.com/@some.handle",
)
