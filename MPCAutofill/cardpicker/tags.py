"""
Tags for cards.
"""

import re
from typing import Optional

import Levenshtein

from django.conf import settings

from cardpicker import models
from cardpicker.constants import NSFW
from cardpicker.search.sanitisation import to_searchable


class Tags:
    def __init__(self) -> None:
        self.tags = self.get_tags()
        self.canonical_cards = self.get_canonical_cards()
        self.canonical_artists = self.get_canonical_artists()
        self.expansion_codes = self.get_expansion_codes()
        self.tag_suggestions = self.get_tag_suggestions()

    @classmethod
    def get_tags(cls) -> dict[str, "models.Tag"]:
        return {
            tag.name.lower(): tag for tag in [models.Tag(name=NSFW, aliases=[], parent=None), *models.Tag.objects.all()]
        }

    @classmethod
    def get_canonical_cards(cls) -> dict[str, int]:
        return {
            f"{expansion_code.upper()} {collector_number}": pk
            for (expansion_code, collector_number, pk) in models.CanonicalCard.objects.values_list(
                "expansion__code", "collector_number", "pk"
            )
        }

    @classmethod
    def get_canonical_artists(cls) -> dict[str, int]:
        return {name: pk for (name, pk) in models.CanonicalArtist.objects.values_list("name", "pk")}

    @classmethod
    def get_expansion_codes(cls) -> set[str]:
        return {code.lower() for code in models.CanonicalExpansion.objects.values_list("code", flat=True)}

    @classmethod
    def get_tag_suggestions(cls) -> dict[str, "models.TagAliasSuggestion"]:
        return {suggestion.raw_text: suggestion for suggestion in models.TagAliasSuggestion.objects.all()}

    @classmethod
    def extract_tag_parts(cls, name: str) -> set[str]:
        tag_parts = re.findall(r"\(([^\(\)]+)\)|\[([^\[\]]+)\]", name)  # Get content of () and []
        return set(map(lambda x: x[0] if len(x[0]) != 0 else x[1], tag_parts))

    @classmethod
    def extract_collector_number(cls, name: str) -> tuple[str, str | None]:
        match = re.search(r"\s?\{([^{}]+)\}", name)
        if match is None:
            return name, None
        return name[: match.start()] + name[match.end() :], match.group(1)

    def match_canonical_card(self, raw_tags: set[str], collector_number: str | None) -> tuple[str, int] | None:
        tags = (
            raw_tags
            if collector_number is None
            # e.g. collector number is 100, tags are ["LEA", "M10"], we would match on ["LEA 100", "M10 100"]
            else {f"{raw_tag} {collector_number}" for raw_tag in raw_tags}
        )
        matched_tags = {tag for tag in tags if tag in self.canonical_cards.keys()}
        if len(matched_tags) == 1:
            tag = matched_tags.pop()
            return tag, self.canonical_cards[tag]
        elif len(matched_tags) > 1:
            # multiple matches, ambiguous -> no match
            return None
        else:
            return None

    def match_canonical_artist(self, raw_tags: set[str]) -> tuple[str, int] | None:
        matched_tags = {raw_tag for raw_tag in raw_tags if raw_tag in self.canonical_artists.keys()}
        if len(matched_tags) == 1:
            tag = matched_tags.pop()
            return tag, self.canonical_artists[tag]
        elif len(matched_tags) > 1:
            # multiple matches, ambiguous -> no match
            return None
        else:
            return None

    def match_tag_fuzzy(self, raw_tag: str) -> Optional[tuple["models.Tag", float]]:
        """
        Best-effort Levenshtein match of `raw_tag` against every known Tag's name and
        aliases (both sides normalised with the same `to_searchable` used for the main
        card search, so punctuation/case differences don't affect the score). Returns
        the best match if it clears `TAG_MATCH_LOW_CONFIDENCE_THRESHOLD`, else `None`.
        """
        normalised_raw_tag = to_searchable(raw_tag)
        if not normalised_raw_tag:
            return None

        best_tag: Optional[models.Tag] = None
        best_score = 0.0
        for tag in self.tags.values():
            if tag.pk is None:
                # e.g. the synthetic NSFW pseudo-tag - never persisted, so it can't be
                # promoted to a real alias or referenced by a suggestion's FK
                continue
            for candidate in [tag.name, *tag.aliases]:
                score = Levenshtein.ratio(normalised_raw_tag, to_searchable(candidate))
                if score > best_score:
                    best_score = score
                    best_tag = tag

        if best_tag is not None and best_score >= settings.TAG_MATCH_LOW_CONFIDENCE_THRESHOLD:
            return best_tag, best_score
        return None

    def _upsert_tag_suggestion(self, raw_tag: str, tag: "models.Tag", confidence: float, status: str) -> None:
        existing = self.tag_suggestions.get(raw_tag)
        if existing is not None:
            existing.occurrence_count += 1
            existing.confidence = confidence
            existing.suggested_tag = tag
            if (
                existing.status == models.TagSuggestionStatus.PENDING
                and status == models.TagSuggestionStatus.AUTO_ACCEPTED
            ):
                existing.status = status
            existing.save()
        else:
            self.tag_suggestions[raw_tag] = models.TagAliasSuggestion.objects.create(
                raw_text=raw_tag, suggested_tag=tag, confidence=confidence, occurrence_count=1, status=status
            )

    def resolve_fuzzy_tag(self, raw_tag: str) -> Optional["models.Tag"]:
        """
        For a bracketed token that didn't exactly match a known Tag name/alias, tries a
        fuzzy match. A high-confidence match is auto-promoted to a real alias on the
        matched Tag immediately, so this (and every future occurrence of the same raw
        text, this run or any later one) hits the fast exact-match path instead; a
        lower-confidence match is recorded as a pending suggestion for admin review
        rather than being applied. A raw text a human has already rejected is never
        resurrected.
        """
        existing = self.tag_suggestions.get(raw_tag)
        if existing is not None and existing.status == models.TagSuggestionStatus.REJECTED:
            return None

        fuzzy_match = self.match_tag_fuzzy(raw_tag)
        if fuzzy_match is None:
            return None
        candidate_tag, confidence = fuzzy_match

        if confidence >= settings.TAG_MATCH_HIGH_CONFIDENCE_THRESHOLD:
            if raw_tag not in candidate_tag.aliases:
                candidate_tag.aliases = [*candidate_tag.aliases, raw_tag]
                candidate_tag.save(update_fields=["aliases"])
            self._upsert_tag_suggestion(raw_tag, candidate_tag, confidence, models.TagSuggestionStatus.AUTO_ACCEPTED)
            return candidate_tag

        self._upsert_tag_suggestion(raw_tag, candidate_tag, confidence, models.TagSuggestionStatus.PENDING)
        return None

    @classmethod
    def remove_tag_from_name(cls, name: str, tag: str) -> str:
        name_with_no_tags = name  # mutated below
        escaped_raw_tag = re.escape(tag)
        while True:
            match = re.search(
                rf"\(.*({escaped_raw_tag},? *).*.*?\)|\[.*({escaped_raw_tag},? *).*.*?\]", name_with_no_tags
            )
            if match is None or not any(match.groups()):
                break
            for i, group in enumerate(match.groups()):
                if group is not None:
                    start, end = match.start(i + 1), match.end(i + 1)
                    if start > 0 and end > 0:
                        name_with_no_tags = name_with_no_tags[0:start] + name_with_no_tags[end:]
        return name_with_no_tags

    def extract(self, name: Optional[str]) -> tuple[str, set[str], int | None, int | None, str | None]:
        """
        This function unpacks a folder or image name which contains a name component and some number of tags
        into its constituents. Also returns the PKs of matched CanonicalCard and CanonicalArtist records
        (nullable), and a lowercase CanonicalExpansion code "hint" (nullable) extracted from a lone set-code
        bracket token with no accompanying collector number (i.e. one that didn't resolve a CanonicalCard
        outright) - a soft signal for ranking printing-tag candidates, not a semantic tag.
        Tags are wrapped in either [square brackets] or (parentheses), and any combination of [] and () can be used
        within a single name.
        """

        if not name:
            return "", set(), None, None, None

        tag_set: set[str] = set()
        # tags will be removed from this name below
        name_with_no_tags, collector_number = self.extract_collector_number(name=name)
        raw_tags = {y for tag_part in self.extract_tag_parts(name) for y in [x.strip() for x in tag_part.split(",")]}

        canonical_card_pk: int | None = None
        canonical_artist_pk: int | None = None

        canonical_card_match = self.match_canonical_card(raw_tags=raw_tags, collector_number=collector_number)
        if canonical_card_match:
            canonical_card_tag, canonical_card_pk = canonical_card_match
            name_with_no_tags = self.remove_tag_from_name(name_with_no_tags, canonical_card_tag)
        else:
            canonical_artist_match = self.match_canonical_artist(raw_tags=raw_tags)
            if canonical_artist_match:
                canonical_artist_tag, canonical_artist_pk = canonical_artist_match
                name_with_no_tags = self.remove_tag_from_name(name_with_no_tags, canonical_artist_tag)

        expansion_hint: str | None = None
        if canonical_card_pk is None:
            for raw_tag in raw_tags:
                if raw_tag.lower() in self.expansion_codes:
                    expansion_hint = raw_tag.lower()
                    name_with_no_tags = self.remove_tag_from_name(name_with_no_tags, raw_tag)
                    break

        for raw_tag in raw_tags:
            lowercase_tag = raw_tag.lower()

            # identify if this is a valid tag. if it is, add the tag's name to the set
            tag_object: Optional[models.Tag] = None
            if lowercase_tag in self.tags.keys():
                tag_object = self.tags[lowercase_tag]
            else:
                for tag in self.tags.values():
                    if lowercase_tag in [alias.lower() for alias in tag.aliases]:
                        tag_object = tag
                        break
            if tag_object is None:
                tag_object = self.resolve_fuzzy_tag(raw_tag)
            if tag_object is None:
                continue
            tag_set.add(tag_object.name)

            # `tag_object` also implies all of its parents
            current_tag = tag_object
            while current_tag.parent is not None:
                tag_set.add(current_tag.parent.name)
                current_tag = current_tag.parent

            # this is a little ugly. remove all instances of `raw_tag` inside () or [] in the name.
            name_with_no_tags = self.remove_tag_from_name(name_with_no_tags, raw_tag)

        artifacts: list[tuple[str, str]] = [  # remove these extra bits from the name
            ("( )", ""),
            ("()", ""),
            ("[ ]", ""),
            ("[]", ""),
            ("[, ", "["),
            (", ]", "]"),
            ("(, ", "("),
            (", )", ")"),
        ]
        for artifact, replacement in artifacts:
            name_with_no_tags = name_with_no_tags.replace(artifact, replacement)
        return name_with_no_tags, tag_set, canonical_card_pk, canonical_artist_pk, expansion_hint


__all__ = ["Tags"]
