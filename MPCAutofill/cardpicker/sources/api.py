import datetime as dt
import functools
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pycountry
import ratelimit
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from oauth2client.service_account import ServiceAccountCredentials

from cardpicker.search import sanitisation
from cardpicker.tags import Tags

thread_local = threading.local()  # Should only be called once per thread


def extract_language(name: str) -> tuple[Optional[pycountry.Languages], str]:
    results = re.compile(r"^(?:\{(.+)\} )?(.*?)$").search(name)
    assert results is not None
    language_code, remainder_of_name = results.groups()
    language = pycountry.languages.get(alpha_2=language_code) if language_code else None
    return (language, remainder_of_name)


@dataclass
class Folder:
    id: str
    name: str
    parent: Optional["Folder"]

    @functools.cached_property
    def top_level_folder(self) -> "Folder":
        if self.parent is None:
            return self
        return self.parent.top_level_folder

    def get_full_path(self, tags: Tags) -> str:
        _, name, _ = self.unpack_name(tags=tags)
        if self.parent is None:
            return name
        return f"{self.parent.get_full_path(tags=tags)} / {name}"

    def unpack_name(self, tags: Tags) -> tuple[Optional[pycountry.Languages], str, set[str]]:
        """
        The folder's name is unpacked according to the below schema. For example, consider `{EN} Cards [NSFW]`:
             {EN}              Cards         [NSFW]
        └─ language ──┘ └─ folder name ──┘ └─ tags ──┘
        """

        language, name = extract_language(self.name)
        name_with_no_tags, extracted_tags, _, _, _, _ = tags.extract(name)
        return language, sanitisation.fix_whitespace(name_with_no_tags), extracted_tags

    def get_language(self, tags: Tags) -> Optional[pycountry.Languages]:
        language, _, _ = self.unpack_name(tags=tags)
        if self.parent is None:
            return language
        return language if language is not None else self.parent.get_language(tags=tags)

    def get_tags(self, tags: Tags) -> set[str]:
        _, _, extracted_tags = self.unpack_name(tags=tags)
        if self.parent is None:
            return extracted_tags
        return self.parent.get_tags(tags=tags) | extracted_tags


@dataclass
class Image:
    id: str
    name: str
    size: int
    created_time: dt.datetime
    modified_time: dt.datetime
    height: int
    folder: Folder
    # issue #473 PR-1: the source's own listing checksum for this file, when the listing carries
    # one at all (Google Drive's `md5Checksum` field - see `GoogleDrive.get_all_images_inside_
    # folder`). Optional with a `None` default so every existing positional/keyword call site
    # that predates this field keeps working unchanged; `LocalFile.get_all_images_inside_folder`
    # never sets this (no Drive-side checksum exists for a local file), which is the intended
    # "stays null" behaviour for that source type per the issue's owner ruling.
    md5_checksum: Optional[str] = None
    # owner-approved addition, 2026-07-25 evening (issue #473 PR-1 comment thread): the same
    # listing's `sha256Checksum` field, when the listing carries one - same "None default, every
    # pre-existing call site keeps working, LocalFile never sets it" shape as md5_checksum above.
    # See `Card.sha256_checksum`'s own docstring in `cardpicker.models` for why this exists
    # alongside md5 rather than replacing it (the binding md5+sha256 evidence-transfer pairing
    # rule for PR-2).
    sha256_checksum: Optional[str] = None

    def unpack_name(
        self, tags: Tags
    ) -> tuple[pycountry.Languages, str, set[str], str, int | None, int | None, str | None, str, str | None]:
        """
        The image's name is unpacked according to the below schema. For example, consider `{EN} Opt [NSFW].png`:
             {EN}             opt          [NSFW]   .      png
        └─ language ──┘ └─ card name ──┘ └─ tags ──┘ └─ extension ──┘

        Also returns `name_with_no_language` (issue #946's `Card.raw_name` - the filename component
        `tags.extract()` is actually called with, before any tag/collector-number stripping) and the
        `Tags.extract_collector_number()` match it produced (`Card.parsed_collector_number`), so both
        survive past this call instead of being lost the moment extraction discards its own working state.
        """

        assert self.name, "File name is empty string"
        assert "." in self.name, "File name has no extension"
        name_with_no_extension, extension = self.name.rsplit(".", 1)
        language, name_with_no_language = extract_language(name_with_no_extension)
        (
            name_with_no_tags,
            extracted_tags,
            canonical_card_pk,
            canonical_artist_pk,
            expansion_hint,
            parsed_collector_number,
        ) = tags.extract(name_with_no_language)
        final_name = sanitisation.fix_whitespace(name_with_no_tags)
        return (
            language or self.folder.get_language(tags=tags),
            final_name,
            extracted_tags | self.folder.get_tags(tags=tags),
            extension,
            canonical_card_pk,
            canonical_artist_pk,
            expansion_hint,
            name_with_no_language,
            parsed_collector_number,
        )


# region google drive API
# Google Drive API usage limits reference: https://developers.google.com/drive/api/guides/limits


# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly", "https://www.googleapis.com/auth/drive.readonly"]

SERVICE_ACC_FILENAME = "client_secrets.json"


def find_or_create_google_drive_service() -> Resource:
    if (service := getattr(thread_local, "google_drive_service", None)) is None:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            str(Path(os.path.abspath(__file__)).parent.parent.parent / SERVICE_ACC_FILENAME), scopes=SCOPES
        )
        service = build("drive", "v3", credentials=creds)
        thread_local.google_drive_service = service
    return service


@ratelimit.sleep_and_retry  # type: ignore  # `ratelimit` does not implement decorator typing correctly
@ratelimit.limits(calls=20_000, period=100)  # type: ignore  # `ratelimit` does not implement decorator typing correctly
def execute_google_drive_api_call(service: Resource) -> Optional[dict[str, Any]]:
    try:
        return service.execute()
    except HttpError:
        return {}


# endregion

# region local file
# Local filesystem source support: a `Source` of this type has its `identifier` field set to a root
# directory path on disk, which is recursively crawled for images in the same way a Google Drive folder is.

LOCAL_FILE_ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}


class PathTraversalError(Exception):
    """Raised when a path resolves outside of the root directory it's expected to stay within."""


def resolve_within_root(root: Path, candidate: Path) -> Path:
    """
    Resolve `candidate` (following any symlinks) and verify that it lies within `root` (also resolved).
    Raises `PathTraversalError` if `candidate` would escape `root` - e.g. via `../` segments in the
    path, or a symlink that points outside of it. This is the single choke point responsible for
    ensuring that local-file-backed images are never served from outside of their source's configured
    root directory, so callers must not bypass it when resolving a path supplied by a client.
    """

    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise PathTraversalError(f"{candidate} resolves to a path outside of root directory {root}")
    return resolved_candidate


# endregion

__all__ = [
    "Image",
    "Folder",
    "find_or_create_google_drive_service",
    "execute_google_drive_api_call",
    "LOCAL_FILE_ALLOWED_IMAGE_EXTENSIONS",
    "PathTraversalError",
    "resolve_within_root",
]
