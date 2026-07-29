"""
The HUMAN write path for `CardIllustrationVote` (issue #503, WTC phase C2; the model itself
landed in #524/#531 with only a machine writer and admin touching it). See `2/submitIllustrationVote/`
in `views.py` for the HTTP surface - this module is the transactional logic behind it, kept out
of `views.py` on purpose (the directive for this change; also matches the existing split between
`views.py`'s thin request/response glue and `printing_consensus.py`/`artist_consensus.py`'s own
reconciliation logic).

WHY ALL THREE WRITES LIVE HERE, IN ONE TRANSACTION, RATHER THAN AS THREE ENDPOINTS THE BROWSER
CALLS IN SEQUENCE (issue #503's C2 discussion, "open decision" section, option 2 - chosen over
option 1 "flag on the artist endpoint" and option 3 "client-side skip flag"):

1. TOCTOU. "Derive an artist vote only if no explicit one exists" is a read-then-write. Split
   across two HTTP requests, the voter can cast an explicit artist vote on another surface
   *in between* those two calls - producing exactly the silent overwrite the "only if absent"
   rule exists to prevent. One DB transaction closes that window; two independent requests
   cannot.

2. The browser cannot be trusted to know a group is 1:1. It renders a candidate grid from a
   payload that is already a snapshot the moment it arrives - reference data moves (an import
   runs, a new printing of the same artwork lands), so a group that was a singleton when the
   grid was drawn may not be a singleton when the voter actually taps it. If the browser decided
   "1:1, cast a printing vote" from its own stale copy, it would cast a full-weight HUMAN
   printing vote for what is, by write time, a non-singleton group - precisely the defect #526
   changed the MACHINE calculator (`local_illustration.py`) to stop committing. The 1:1 check
   here (`printings_for_card_and_illustration`) is therefore always re-run against LIVE data,
   inside the transaction, never trusted from the request body - the request carries only an
   `illustration_id`/`is_unknown` flag, never a printing list, so there is nothing stale to
   trust in the first place.

3. Consistency with #534, which made every purge-and-write pair in the ingestion pipeline
   atomic because a kill between delete and insert destroys votes. Three vote rows across three
   tables cast together in one transaction matches that posture; three independent HTTP calls
   from this one endpoint would regress from it at the one surface where a HUMAN, not a batch
   job, is the author - a partial failure here is a partial vote from one identity, not a
   resumable pipeline run.

#525 PARALLEL - WHY THIS RULE MUST NOT BE ENFORCED CLIENT-SIDE. #525 happened because
one-vote-per-card was enforced by the SUBMIT VIEW rather than the schema; a machine writer using
`bulk_create` walked straight past the view entirely, and one identity ended up holding several
mutually exclusive votes at once. Enforcing the "derive only if absent" rule in the browser
would reproduce that exact shape one layer up: a soundness rule that holds only while the
client behaves, with no server-side backstop. Putting the check here - the one server-side
function every caller of this endpoint goes through - is what keeps it real.

#483 - DELIBERATELY NOT ANSWERED HERE. Whose vote wins when an EXPLICIT artist vote already
exists is issue #483 (open, broader than this one surface: it covers every path that can
produce two artist votes of equal standing, not just this derived one). This module's rule -
"never override an existing vote, explicit or previously-derived" - is not a #483 answer by
implication: it prevents two votes of equal standing from ever coexisting in the first place, so
withhold/latest-wins/both-count all engage only for actual contradictions elsewhere, and this
surface needs no revision no matter how #483 is ruled on. If #483 changes this precedence, this
is the ONE function that needs to change - do not duplicate this check anywhere else.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction

from cardpicker.artist_consensus import resolve_and_persist_artist
from cardpicker.illustration_consensus import resolve_and_persist_illustration
from cardpicker.models import (
    CanonicalCard,
    Card,
    CardArtistVote,
    CardIllustrationVote,
    CardPrintingTag,
    VoteSource,
)
from cardpicker.printing_candidates import get_ranked_printing_candidates
from cardpicker.printing_consensus import resolve_and_persist_printing

# Distinct vote_surface for the CardArtistVote this endpoint derives (never the same value a
# human explicitly submitting through `post_submit_artist_vote` would send) - issue #503's C2
# amendment requires this "so the derivation stays auditable": a query on this value alone finds
# every derived-not-explicit artist vote, without inspecting anonymous_id shapes.
DERIVED_ARTIST_VOTE_SURFACE = "illustration_vote_derived_artist"

# THE ONLY SEPARATOR TESTED, AND WHY (issue #503, prod census over 2,523 CanonicalArtist rows):
#   ' & '   -> 219 rows (8.7%), ALL real combined credits - the separator this module tests.
#   ', '    ->  20 rows, ALL FALSE POSITIVES: Unfinity "age N" credits ("Aliya, age 5½",
#               "Mark Rosewater, Age 53¾") and Jr./Inc. suffixes ("Ken Meyer, Jr.",
#               "Bad Flip Productions, Inc."). A comma test would wrongly abstain on all 19 of
#               these that don't already contain ' & ' - do not add one.
#   ' with '->   1 row, also a false positive (a quoted nickname, not a second credited artist).
# Some combined credits contain BOTH ' & ' and a comma (e.g. "Anthony S. Waters & Edward P.
# Beard, Jr."), which is exactly why ' & ' must be checked FIRST and INDEPENDENTLY rather than
# folded into a generic multi-separator list - a comma-based rule evaluated on its own would
# still catch that row, but only by also catching the 19 false positives above.
_COMBINED_CREDIT_SEPARATOR = " & "


def artist_name_indicates_combined_credit(artist_name: str) -> bool:
    """
    True when `artist_name` (a `CanonicalArtist.name` string, verbatim from Scryfall - see
    `CanonicalCard.artist`, a single FK, and `mtg.py`'s importer which never splits this string)
    encodes more than one credited artist. `illustration_id -> artist` is functional, which is
    what makes deriving a `CardArtistVote` from an illustration sound in the first place; a
    combined credit breaks that one-to-one mapping, so the derivation must abstain rather than
    pick one of the credited artists (or the whole joined string) arbitrarily. See this module's
    docstring and `_COMBINED_CREDIT_SEPARATOR` above for why ' & ' is the only pattern tested.
    """
    return _COMBINED_CREDIT_SEPARATOR in artist_name


def printings_for_card_and_illustration(card: Card, illustration_id: uuid.UUID) -> list[CanonicalCard]:
    """
    THE LIVE 1:1 CHECK. Narrows `illustration_id` to the `CanonicalCard` printings that both
    (a) carry it (`CanonicalPrintingMetadata.illustration_id`, the same join
    `cardpicker.local_illustration.printings_for_illustration` uses) and (b) are actual
    candidates for THIS `card` right now (`get_ranked_printing_candidates(card, None)` - the
    same call `post_printing_candidates`/`post_artist_candidates` use to build the grid the
    voter is looking at). Scoping to (b) matters: `illustration_id` is a global Scryfall
    identifier, and without this scope a reused/coincidental id on an unrelated card name could
    leak in.

    Deliberately re-queried here rather than accepting a candidate list from the request body -
    see this module's own docstring, point 2: the request carries only an `illustration_id`, and
    this function is what makes the resulting narrowing reflect the database at THIS moment, not
    whatever the browser's candidate grid looked like when it was rendered.

    Returns a plain list (not a lazy queryset) - the caller needs `len()` for the 1:1 decision
    and, on the 1:1 branch, the single member itself; nothing here is large enough (bounded by
    `get_ranked_printing_candidates`'s own `CANDIDATE_RESULT_LIMIT`) to justify staying lazy.
    """
    candidates = get_ranked_printing_candidates(card, None)
    return [
        candidate
        for candidate in candidates
        if (metadata := getattr(candidate, "printing_metadata", None)) is not None
        and metadata.illustration_id == illustration_id
    ]


@dataclass(frozen=True)
class IllustrationVoteOutcome:
    """What `cast_illustration_vote` actually did, for the view to serialise into the response."""

    illustration_id: Optional[uuid.UUID]
    is_unknown: bool
    printing_vote_cast: bool
    resolved_printing: Optional[CanonicalCard]
    artist_vote_cast: bool
    # None when the artist channel wrote; otherwise "combined_credit" | "existing_explicit_vote"
    # | "no_printing_found" - see SubmitIllustrationVoteResponse's own docstring in
    # schema_types.py for what each means.
    artist_abstain_reason: Optional[str]


def cast_illustration_vote(
    *,
    card: Card,
    anonymous_id: str,
    illustration_id: Optional[uuid.UUID],
    is_unknown: bool,
    user: Optional[User],
    vote_surface: Optional[str],
) -> IllustrationVoteOutcome:
    """
    The one transactional entry point behind `2/submitIllustrationVote/`. Exactly one of
    `illustration_id`/`is_unknown` is meaningful (the caller - `views.post_submit_illustration_vote`
    - has already validated the XOR before calling in; this function trusts it, mirroring
    `CardIllustrationVote`'s own `cardillustrationvote_illustration_xor_unknown` CheckConstraint).

    Up to three writes happen here, in ONE `transaction.atomic()` block - see this module's own
    docstring for why all three must be atomic together rather than three separate endpoint calls:

    1. `CardIllustrationVote` - ALWAYS written, via `update_or_create(card=, anonymous_id=,
       defaults=...)`. Deliberately NOT the sibling endpoints' delete-then-create idiom: this
       model's `UniqueConstraint(fields=["card", "anonymous_id"])` carries no `condition=` (see
       the model's own docstring, issue #525) specifically so the DATABASE - not view
       convention - enforces one-illustration-opinion-per-identity-per-card. update_or_create
       keys on exactly that constraint, so a changed answer UPDATES the existing row (matching
       `local_illustration._purge_and_write_illustration_votes`'s own value-compare-then-update
       behaviour for the machine writer) rather than colliding with it.

    2. `CardPrintingTag` - ONLY when `printings_for_card_and_illustration` resolves to EXACTLY
       ONE live candidate printing. Reuses `post_submit_printing_tag`'s own delete-then-create
       semantics unchanged (that view's own docstring: "a person changing their mind updates
       their vote rather than erroring on the unique constraint"). At N>1 printings, nothing is
       written on this channel at all - `post_submit_printing_tag` itself deletes every prior
       vote for (card, anonymous_id) before creating one, so N sequential submissions here would
       leave exactly one arbitrary survivor holding full human weight; the endpoint has no way
       to express "one of these N", so it must not try.

    3. `CardArtistVote` - decoupled from outcome (2) above: `illustration_id -> artist` is
       functional regardless of how many PRINTINGS share the artwork (they all carry the same
       artist by construction), so the artist channel is attempted whenever
       `printings_for_card_and_illustration` returns at least one candidate, not only when it
       returns exactly one. Cast ONLY when:
         - the resolved artist's name does not indicate a combined credit
           (`artist_name_indicates_combined_credit`), and
         - no `CardArtistVote` already exists for (card, anonymous_id) - explicit OR a vote this
           same derivation cast on an earlier call. Checked with a plain `.exists()` query INSIDE
           this transaction (closing the TOCTOU window described in the module docstring), never
           by deleting first - an existing vote is left completely untouched, matching the
           "a derived vote never overrides an existing one" rule (see module docstring's #483
           section). `source=USER`, `anonymous_id` = the voter's own id (a UUID - see
           `frontend/src/common/cookies.ts`'s `getOrCreateAnonymousId` - so
           `models.calculator_family()` returns `None` and this reads as human, exactly like any
           other human-authored row), and `vote_surface=DERIVED_ARTIST_VOTE_SURFACE` (never the
           surface the illustration vote itself carried) so the derivation stays queryable/
           auditable on its own.

    Both consensus recomputations (`resolve_and_persist_printing`/`resolve_and_persist_artist`)
    run inside the same transaction, immediately after the write that made them stale - same
    placement as `post_submit_printing_tag`/`post_submit_artist_vote` - and are skipped entirely
    when the corresponding channel didn't write (nothing changed, nothing to recompute).
    """
    printing_vote_cast = False
    resolved_printing: Optional[CanonicalCard] = None
    artist_vote_cast = False
    artist_abstain_reason: Optional[str] = None

    with transaction.atomic():
        CardIllustrationVote.objects.update_or_create(
            card=card,
            anonymous_id=anonymous_id,
            defaults={
                "illustration_id": illustration_id,
                "is_unknown": is_unknown,
                "source": VoteSource.USER,
                "user": user,
                "confidence": None,
                "run_id": None,
                "vote_surface": vote_surface,
            },
        )
        # Recompute illustration consensus immediately, inside the same transaction, right after
        # the write that made it stale - the same placement the printing/artist channels below
        # already use for their own recomputations. UNCONDITIONAL, unlike those two: this is the
        # one write that ALWAYS happens here, so there is no "channel didn't write, nothing to
        # recompute" branch to take.
        #
        # This is also the propagation seam. `resolve_and_persist_illustration` tallies and writes
        # over `card`'s whole md5 identity group, so one human answer here can resolve - and
        # persist to - a byte-identical sibling that the machine calculator abstained on with
        # `no-candidate-match`. See `illustration_consensus`'s module docstring.
        resolve_and_persist_illustration(card)

        if not is_unknown and illustration_id is not None:
            matching_printings = printings_for_card_and_illustration(card, illustration_id)

            if len(matching_printings) == 1:
                printing = matching_printings[0]
                CardPrintingTag.objects.filter(card=card, anonymous_id=anonymous_id).delete()
                CardPrintingTag.objects.create(
                    card=card,
                    printing=printing,
                    is_no_match=False,
                    anonymous_id=anonymous_id,
                    source=VoteSource.USER,
                    user=user,
                    vote_surface=vote_surface,
                )
                resolve_and_persist_printing(card)
                printing_vote_cast = True
                resolved_printing = printing

            if matching_printings:
                artist = matching_printings[0].artist
                if artist_name_indicates_combined_credit(artist.name):
                    artist_abstain_reason = "combined_credit"
                elif CardArtistVote.objects.filter(card=card, anonymous_id=anonymous_id).exists():
                    artist_abstain_reason = "existing_explicit_vote"
                else:
                    CardArtistVote.objects.create(
                        card=card,
                        artist=artist,
                        is_unknown=False,
                        anonymous_id=anonymous_id,
                        source=VoteSource.USER,
                        user=user,
                        vote_surface=DERIVED_ARTIST_VOTE_SURFACE,
                    )
                    resolve_and_persist_artist(card)
                    artist_vote_cast = True
            else:
                artist_abstain_reason = "no_printing_found"
        # is_unknown=True: no artwork identity at all, so nothing is derivable on either the
        # printing or artist channel - the illustration vote above is the entire answer.

    return IllustrationVoteOutcome(
        illustration_id=illustration_id,
        is_unknown=is_unknown,
        printing_vote_cast=printing_vote_cast,
        resolved_printing=resolved_printing,
        artist_vote_cast=artist_vote_cast,
        artist_abstain_reason=artist_abstain_reason,
    )
