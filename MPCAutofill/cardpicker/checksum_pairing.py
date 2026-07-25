"""
Shared md5/sha256 tolerant-read helper (issue #473 PR-2, folded with issue #472 per the
owner-approved fold - see `evidence_transfer.py`'s own module docstring for the full evidence-
transfer design this is a small supporting piece of).

`Card.sha256_checksum` is being added by a SIBLING PR (owner-approved 2026-07-25 addition to
issue #473, binding for evidence transfer's own pairing rule) on the SAME stacked base this
branch was cut from (`md5-checksum-substrate`) - it is not guaranteed to exist on `Card` yet at
any given moment this branch is built/tested against that base. Every reader of a card's own
sha256 in this PR's own code goes through `card_sha256_checksum` below rather than a direct
`card.sha256_checksum` attribute access, so the tolerance lives in exactly one place instead of
being re-derived (or, worse, forgotten) at each call site. Once the sibling PR lands the field for
real, this function's behavior is unchanged - `getattr` returns the real value instead of falling
through to the "field doesn't exist" default, with no code change required here.
"""

from typing import Optional

from cardpicker.models import Card


def card_sha256_checksum(card: Card) -> Optional[str]:
    """
    Tolerant read of `Card.sha256_checksum` - `None` whether the field is genuinely NULL for this
    card or the field doesn't exist on the model at all yet (see module docstring). Callers that
    need to distinguish "known absent" from "not yet knowable" don't exist yet in this codebase;
    every current caller (`evidence_transfer.py`'s pairing check, `image_evidence.py`'s stamping)
    treats both identically - "no sha256 to check/stamp" - which is the correct behavior for both:
    the pairing rule's own "whenever BOTH are non-null" carve-out already skips the check entirely
    the moment either side comes back `None` here, and stamping a `None` is just "nothing to
    stamp yet", not a lost value in either case (assuming the field module docstring below hasn't
    landed here yet, no sha256 has ever been enrolled on any Card).
    """
    return getattr(card, "sha256_checksum", None)


__all__ = ["card_sha256_checksum"]
