# federation-hash-tool

Standalone reference implementation of the `content_phash` recipe from
[ProxyPrints' public federation export spec](../docs/federation/public-export-v1.md)
(§2) — hash a folder of your own card images the exact same way ProxyPrints'
export does, so you can join your images against it without guessing at the
algorithm. MIT-licensed, dependency-free of this fork's own Django/database
stack (Pillow + imagehash only — nothing else required to compute a hash).

**Status**: this tool works standalone today. The export it's meant to join
against (`docs/federation/public-export-v1.md`) is itself still queued for
build — `--export-url` will have nothing real to point at until that ships.
Hashing your own folder (no `--export-url`) works right now.

## Install

```
pip install -r requirements.txt
```

(Just `Pillow` and `imagehash` for the tool itself; `pytest` is only needed
to run this directory's own test suite.)

## Usage

Hash every image in a folder:

```
python hash_my_cards.py ./my_scans/
```

```
a94fb36da358460d  Adanto the First Fort.png
b418d65e4c6f9195  Huntmaster of the Fells.jpg
```

Hash a folder _and_ join against a published export in one command:

```
python hash_my_cards.py ./my_scans/ --export-url https://cdn.proxyprints.ca/federation/export-full.jsonl
```

```
Adanto the First Fort.png: distance 0 -> znr#135 (3f8e6e02-...-uuid)
Huntmaster of the Fells.jpg: no match within distance <= 20
```

`--threshold N` overrides the default match distance (20 — the spec's own
empirically-tuned value, see the spec doc's "Distance semantics" section for
why it isn't the textbook "under 10" imagehash convention). `--json` emits
machine-readable output instead of the table above.

## What "hash the same way" actually means

Full detail lives in the spec doc; the short version — every step below is
required, not optional, for a hash to actually match ProxyPrints' own:

1. Classify the image as bleed-inclusive or trimmed by aspect ratio (most
   real card images are bleed-inclusive; a minority aren't, and skipping
   this step silently produces a different hash for those).
2. Crop to the art region only, using a fixed fraction of the full image —
   remapped first if the image was classified as trimmed in step 1.
3. `imagehash.phash(cropped_region, hash_size=8)`.
4. The hash's own string form (16 hex characters) — not any other
   encoding.

`hash_my_cards.py`'s `compute_content_phash()` is the single function that
does all four steps; it's been verified byte-for-byte identical against
ProxyPrints' own backend implementation (`cardpicker/local_phash.py` +
`local_fallback.py`) across bleed, trimmed, and ambiguous test images before
this tool shipped — not just "should be the same," actually checked.

## Verifying a signed export

Once the export is signed and published (queued separately from this tool —
see the spec doc's §3/§4), verify it with:

```
minisign -Vm export-full.jsonl -P <published-pubkey>
```

The real public key isn't published yet (signing is server-side, still
queued behind the export build itself) — this is the exact command you'll
need once it is; nothing else about the verification step is expected to
change.

## Tests

```
pip install -r requirements.txt
pytest tests/
```

## License

MIT — matching `acoreyj/proxies-at-home`, one of this tool's two named
target consumers (see the spec doc §6). This tooling exists specifically to
make consumption cheap for external permissively-licensed tools; the
**export data itself** is separately licensed under ODbL 1.0 (spec doc §5)
— a different decision about a different artifact. Using this tool to hash
your own images and join them against the export doesn't require anything
of your own code either way (see §5's "produced works" note).
