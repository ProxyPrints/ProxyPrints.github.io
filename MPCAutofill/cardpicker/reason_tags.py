"""
The "why no match?" reason-code taxonomy - shown as a follow-up strip in the printing-tag
queue after a human casts an explicit "No match" printing vote (see
docs/features/printing-tags.md, "no-match reason tags"). Kept in its own module and its own
management command (mirroring cardpicker.default_tags/seed_default_tags exactly) rather than
a data migration: a data migration would run automatically at DB-setup time (including the
test database), unconditionally seeding these rows into every fresh DB - which breaks every
test that asserts on the *complete* set of `Tag` rows (e.g. test_views.py::TestGetTags, which
documents that a fresh DB has zero real Tag rows besides the synthetic never-persisted "NSFW"
pseudo-tag - see cardpicker.tags). A manual, idempotent command avoids that coupling, exactly
like the existing descriptor taxonomy already does.

These tag names are a federation interchange contract (see docs/features/printing-tags.md)
- other instances that consume our vote export are expected to recognise these exact strings.
Renaming any of them is a breaking data migration, not a refactor.

WTC phase B (2026-07-28): the seven tags below actually answer two DIFFERENT questions, not
one, and the frontend (`NoMatchReasonStrip.tsx`'s exported `NO_MATCH_REASON_TAG_GROUPS`, the
single source of truth for this split on that side) now presents them as two labelled groups
instead of one flat chip wall. Documented here too so backend and frontend agree on the
partition without either side re-deriving it from the other:

- "not-official-printing": `altered-frame`, `upscaled`, `no-collector-line`, `non-english` -
  the artwork is genuine, the physical card is not. The artwork question stays ANSWERABLE for
  these cards.
- "not-official-art": `custom-art`, `ai-art`, `external-ip` - the artwork itself isn't from
  any official card. The artwork question is UNANSWERABLE for these cards.

That partition is exhaustive over this taxonomy - every tag below belongs to exactly one
side. A future addition to `NO_MATCH_REASON_TAGS` must also be added to exactly one side of
`NO_MATCH_REASON_TAG_GROUPS` in `NoMatchReasonStrip.tsx`, or it silently falls out of the UI
grouping (a frontend test asserts the union/no-overlap invariant, but nothing here enforces
it from the backend side). This module makes NO routing decision on the partition itself -
phase C (illustration funnel: not-official-*printing* cards stay in it, not-official-*art*
cards drop out) is the only consumer of it as a routing signal.

Deliberately a separate, lowercase-kebab-case taxonomy from `cardpicker.default_tags`'s Title
Case DEFAULT_TAGS (which parses filename bracket content at upload time, e.g. "Upscaled",
"Custom", "AI-Generated"). `upscaled`/`custom-art`/`ai-art` below cover near-identical
concepts to those but are cast by a human as the *reason* they picked "no match" in the
printing-tag queue, not inferred from a filename - kept as distinct rows rather than reusing
the existing tags so the two vote populations (upload-time inference vs. human no-match
reasoning) don't get silently merged into one consensus.
"""

from cardpicker.models import Tag

# (name, description, display_name). `description` is documentation only (no DB column for
# it - see Tag.display_name's help_text); `display_name` is real, seeded presentation text
# the frontend looks up dynamically (useTagDisplayName) rather than hardcoding, so this list
# is the single source of truth for both the machine key and its human label.
#
# Axis inline below (see the module docstring's "WTC phase B" section for the full
# rationale) - not a schema change, just a reading aid: which of the two questions
# (not-official-printing vs. not-official-art) each row answers.
# Our own `Tag.name` for the external-IP no-match reason, exported as a named constant because it
# is a convergence contract, not just a row in the list below: any machine channel that ever
# derives external-IP-ness from Scryfall data must write THIS string. It previously lived in
# `management/commands/import_external_ip_tags.py` (the Scryfall Tagger import), which was retired
# on 2026-07-29 along with `PrintingTagVote`; the constant outlived it deliberately so the contract
# survives the code that used to honour it. `test_reason_tags` pins it against the list below.
EXTERNAL_IP_TAG_NAME = "external-ip"

NO_MATCH_REASON_TAGS: list[tuple[str, str, str]] = [
    # axis: not-official-art
    ("custom-art", "Original or alternate artwork - does not depict a real printing", "Custom art"),
    # axis: not-official-printing
    ("altered-frame", "Real printing's art in a modified frame", "Altered frame"),
    # axis: not-official-printing
    ("upscaled", "AI-upscaled version of an official image", "Upscaled"),
    # axis: not-official-art
    ("ai-art", "AI-generated artwork", "AI art"),
    # axis: not-official-printing
    ("no-collector-line", "No legible collector line on the card face", "No collector line"),
    # axis: not-official-printing
    ("non-english", "Non-English printing", "Non-English"),
    # axis: not-official-art (see the dedicated comment on this tag below for its own,
    # unrelated "why this exact string" rationale)
    # EXTERNAL_IP_TAG_NAME (defined above) used to live in
    # management/commands/import_external_ip_tags.py, which owned the machine half of this tag;
    # that command and its `PrintingTagVote` target were retired on 2026-07-29 and the constant
    # moved here, to the module that owns the surviving (human) channel. The convergence rule it
    # encodes is unchanged and still binding on whatever rebuilds the machine half: both channels
    # write into the same card.tags array, so one shared name makes `tag:external-ip` a single
    # predicate over the whole catalog rather than two names that would permanently fragment it.
    # Deliberately NOT named
    # after the official Wizards "Universes Beyond" product line: that name covers OFFICIAL
    # Magic printings, so a custom proxy bearing e.g. Warhammer or Lord of the Rings art isn't
    # one of those - it's non-official art drawn from an external IP. There is no
    # "external-ip"-negation counterpart tag here either - that would be an official
    # product-line distinction (that Wizards line vs. everything else), which issue #505 will
    # resolve authoritatively from `set_type`/`security_stamp` at the PRINTING level, not as a
    # human-cast no-match reason.
    (
        EXTERNAL_IP_TAG_NAME,
        "Art is drawn from an external IP (crossover / licensed property) rather than original Magic art",
        "External IP",
    ),
]


def seed_no_match_reason_tags() -> dict[str, int]:
    """
    Idempotent - safe to re-run. Creates any tag that doesn't exist yet (display_name set at
    creation), and backfills display_name on an already-existing tag only if it's still null
    - never overwrites a manually-edited display_name (see Tag.display_name's help_text:
    "freely editable").
    """

    created = 0
    updated = 0
    for name, _description, display_name in NO_MATCH_REASON_TAGS:
        tag, was_created = Tag.objects.get_or_create(name=name, defaults={"aliases": [], "display_name": display_name})
        if was_created:
            created += 1
            continue
        if tag.display_name is None:
            tag.display_name = display_name
            tag.save(update_fields=["display_name"])
            updated += 1
    return {"created": created, "updated": updated}


__all__ = ["seed_no_match_reason_tags", "NO_MATCH_REASON_TAGS"]
