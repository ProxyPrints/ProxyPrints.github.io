# LOCAL_FILE source type

Real backend support for cataloguing cards from a local directory on the
server's disk, as a `Source` type alongside Google Drive. `LocalFile` in
`cardpicker/sources/source_types.py` was previously a stub (only
`get_identifier()` implemented) despite the DB schema/enum and
`Source.identifier`'s own field comment already anticipating it.

## How it works

- `Source.identifier` is a root directory path on disk. Folders/images are
  discovered by walking the filesystem (`os.scandir`) instead of an API
  call; image dimensions (needed for the DPI calculation Drive gets for
  free from `imageMediaMetadata.height`) are read locally via Pillow.
  Symlinked files _and_ directories are never followed/traversed during
  indexing — deliberately, to avoid both symlink cycles and a symlink
  escaping the source's root directory.
- Since the frontend only loads images by URL, a `get_local_file_image`
  view (`cardpicker/views.py`, routed at `2/localFileImage/`) serves image
  bytes back out. Treated as a real security surface: the `identifier`
  query param is untrusted input, so the view (a) looks up a real `Card`
  row scoped to `source__source_type == LOCAL_FILE`, then (b) independently
  re-resolves and validates the path stays inside that source's _currently
  configured_ root via `resolve_within_root` (`cardpicker/sources/api.py`)
  — covering `../` traversal and symlink escapes, and re-checked at serve
  time (not just trusted from indexing) in case a source's root was
  reconfigured after its images were catalogued.
- `LOCAL_FILE_SOURCE_BASE_URL` (Django setting, defaults to
  `http://localhost:8000`) builds the thumbnail URLs returned by
  `get_small_thumbnail_url`/`get_medium_thumbnail_url`, since those are
  static methods with no request object to introspect the server's own
  base URL.
- `update_database.py`'s indexing pipeline needed no changes — it already
  dispatches generically over `SourceType`. Re-scanning a single source
  works via `update_database --drive <key>` (flag name is a naming leftover
  from Drive-only days, works for any source type — help text updated to
  say so) or a new `rescan_sources` admin action on `Source`.

## Key files

- `cardpicker/sources/source_types.py` (`LocalFile`)
- `cardpicker/sources/api.py` (`resolve_within_root`)
- `cardpicker/views.py` (`get_local_file_image`)
- `cardpicker/tests/test_local_file_source.py`

## Status

17 new tests, fully self-contained against real `tmp_path` directories/
files — no network or credentials needed, unlike `GoogleDrive`'s own tests
(which hit a real external Drive folder and are part of the documented
"2 Google Drive creds" known CI failures; see [[../infrastructure.md]]).
