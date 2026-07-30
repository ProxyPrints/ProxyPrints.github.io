# Border-colour measurements — what each `border_color` actually measures (2026-07-29)

Read-only measurement pass. No writes, no management command, no migration, no
deploy. Production figures were read via
`docker exec mpcautofill_django python manage.py shell` on 2026-07-29. Pixel
figures were computed locally against 120 fetched images, cached on disk.

**Code measured.** `MPCAutofill/cardpicker/local_fallback.py` at `e6c6429a`
(`origin/master` at the time of writing). Every constant, band and statistic
below is that file's own — nothing was re-invented for this report.

**Why this exists.** `classify_border_color` classifies a card's border from
four thin pixel bands using five hardcoded thresholds. None of those thresholds
has a published measurement behind it, and `BORDER_COLOR_TO_TAG` covers only
`black`/`white`/`silver`/`borderless` — `gold` (1,373 printings) and `yellow`
(90 printings) are structurally unreachable. The owner asked for the actual
colour of a gold border, measured rather than estimated. Measuring it required
measuring the others, and measuring the others found a live defect that matters
considerably more than the gold feature.

---

## 0. Headline

**The four sample bands do not sample the card's border on the images
production actually classifies.** They sample the _bleed margin_ around it.
On a bleed-inclusive image — 217,740 of 220,579 `ImageEvidence` rows, 98.7% —
between 79% and 91% of each band's area lies outside the card entirely. Where a
proxy render pads its bleed with flat black (very common), the classifier reads
`RGB(0, 0, 0)` at a per-channel standard deviation of exactly `0.00` and returns
`"black"` with maximal apparent uniformity, **whatever colour the card's border
actually is**.

Measured against production's own labelled subset:

| true `border_color` |  rows | classified correctly |
| ------------------- | ----: | -------------------: |
| `black`             | 9,930 |               69.82% |
| `white`             |    34 |            **0.00%** |
| `silver`            |    18 |            **0.00%** |
| `borderless`        | 1,942 |               75.44% |
| `gold`              |     1 |    0.00% (abstained) |
| `yellow`            |     0 |              no data |

Separately, and independently of the band-placement defect,
**`_SILVER_BRIGHTNESS_RANGE = (140, 200)` does not contain the measured
brightness of a single silver border.** Eleven of twelve official silver
renders measure 82–129; the twelfth measures 207. The range has zero overlap
with the distribution it exists to select.

`_BLACK_MAX_BRIGHTNESS = 60` and `_WHITE_MIN_BRIGHTNESS = 210` both check out
against measurement, with headroom, and are not implicated.

---

## 1. Method

### 1a. The statistics are the code's own

`classify_border_color` crops four bands, converts each to RGB, and takes each
band's per-channel mean. It then computes, over the four band means:

- `brightness` = `(avg_r + avg_g + avg_b) / 3`
- `saturation` = `max(avg_r, avg_g, avg_b) - min(avg_r, avg_g, avg_b)`
- uniformity = mean over bands of `statistics.pstdev` of that band's **red
  channel only** — green and blue are computed per band and discarded

and applies this ladder, in order: not uniform → `"borderless"`; brightness
≤ 60 → `"black"`; brightness ≥ 210 → `"white"`; brightness in [140, 200] and
saturation ≤ 20 → `"silver"`; otherwise `None`.

The measurement harness
([`../data/2026-07-29-border-colour-measure.py`](../data/2026-07-29-border-colour-measure.py))
copies the band definitions, the geometry constants, `normalize_crop_box`,
`classify_bleed_edge` and that ladder verbatim. It records green and blue
standard deviations too, for diagnosis, but never feeds them into a verdict.

### 1b. Three band placements are measured, not one

Every image is measured three ways, because which one you use changes the
answer:

| placement    | what it is                                                                                                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `raw`        | `_BORDER_SAMPLE_BANDS` as literally written in the source                                                                                                                      |
| `production` | `normalize_crop_box(band, classify_bleed_edge(image))` — **what production actually samples**, and the only placement whose numbers decide a real `ImageEvidence.layout_class` |
| `cardspace`  | the same fractions read as fractions _of the trimmed card_, mapped forward into whatever coordinate space the image uses                                                       |

All headline figures below are the `production` placement. The other two are in
the CSV.

**The harness is production-equivalent, and this was verified rather than
assumed.** Of the 120 sampled catalogue/official images, 73 catalogue images
have a stored `ImageEvidence.layout_class` from a real pipeline run. The
harness's `production`-placement verdict matched the stored value on **73 of
73**, zero mismatches. The remaining 47 have no evidence row yet.

### 1c. Where the images came from

`CanonicalPrintingMetadata.art_crop_url` is the art crop and has no border. The
full card face is `CanonicalCard.medium_thumbnail_url`, which is Scryfall's
`normal` render (488×680, trimmed).

Production does **not** classify that image, and it does not classify
`Card.get_medium_thumbnail_url()` either — that is a
`drive.google.com/thumbnail` URL which letterboxes with black padding and would
corrupt any edge measurement. `image_evidence.extract_card_evidence` calls
`image_cdn_fetch.fetch_card_image`, which fetches
`{IMAGE_WORKER_URL}/images/google_drive/full/{identifier}.jpg?jpgQuality=100&dpi=250`
— the image CDN Worker's "full" tier, 680×925, bleed-inclusive. That is what
this report measures for the catalogue population.

Two populations are therefore reported separately throughout, and they are not
interchangeable:

- **official** — Scryfall `normal` renders. Establishes what each border colour
  _is_. Trimmed (aspect 0.7176 → `bleed_class = "trimmed"`).
- **catalogue** — the image CDN Worker "full" tier, i.e. the user-uploaded
  proxy scans and renders `classify_border_color` actually meets in production.
  Bleed-inclusive (aspect 0.7351 → `bleed_class = "bleed"`).

Fetching was serial with a 1-second delay and an on-disk cache; a re-run of the
harness makes no network calls at all. 120 images total.

### 1d. Sample sizes and how they were chosen

| population | colour          |      n | basis                                                                                                                                                                                                                                          |
| ---------- | --------------- | -----: | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| official   | each of the six |     12 | stratified: round-robin across the expansions that carry that border colour, ordered by expansion size then code, printings ordered by Scryfall id — deterministic, and spreads the sample across print runs rather than clustering in one set |
| catalogue  | `gold`          |  **1** | **full census** — one is all there is                                                                                                                                                                                                          |
| catalogue  | `silver`        | **31** | **full census**                                                                                                                                                                                                                                |
| catalogue  | `white`         | **64** | **full census**                                                                                                                                                                                                                                |
| catalogue  | `yellow`        |  **0** | **full census — the catalogue holds none**                                                                                                                                                                                                     |
| catalogue  | `black`         |     12 | evenly-spaced sample of 16,477                                                                                                                                                                                                                 |
| catalogue  | `borderless`    |     12 | evenly-spaced sample of 2,912                                                                                                                                                                                                                  |

Twelve per colour was chosen to see spread, not just a central value — the
owner asked for one sample, but a threshold needs a distribution. For the three
small catalogue populations a sample was pointless, so the whole population was
measured.

### 1e. What the catalogue does and does not contain

Of 230,706 catalogue `Card` rows, 19,485 carry a resolved link to a
`CanonicalCard` (confirmed index match or resolved printing vote). Broken down
by the matched printing's `border_color`:

| `border_color` | catalogue images |
| -------------- | ---------------: |
| `black`        |           16,477 |
| `borderless`   |            2,912 |
| `white`        |               64 |
| `silver`       |               31 |
| `gold`         |            **1** |
| `yellow`       |            **0** |

**The catalogue contains exactly one image matched to a gold-bordered printing
and none matched to a yellow-bordered printing.** The gold one is
`Li'l Giri Saves the Day [PSSC]`, a Google Drive token image from the "Sliver
of Slytherin Tokens" source, confirmed-matched to `pssc 6`. That is a real
finding about what a gold/yellow classifier would meet in production: as of
today, almost nothing.

---

## 2. The measurements

### 2a. Official Scryfall renders — production placement

Statistics are `min / median / max (mean ± population sd)` across the 12
samples of each colour.

| true colour  |   n | brightness                           | saturation            | mean std (R)       | classifier says            |
| ------------ | --: | ------------------------------------ | --------------------- | ------------------ | -------------------------- |
| `black`      |  12 | 0.0 / 16.2 / 34.7 (11.7 ± 10.9)      | 0.0 / 7.0 / 27.1      | 0.0 / 0.0 / 40.6   | `black`×11, `borderless`×1 |
| `white`      |  12 | 235.4 / 237.7 / 237.7 (236.9 ± 1.0)  | 1.0 / 1.9 / 2.9       | 0.8 / 0.8 / 1.9    | `white`×12                 |
| `silver`     |  12 | 82.3 / 121.9 / 207.0 (123.4 ± 28.3)  | 0.0 / 8.2 / 31.5      | 1.4 / 31.6 / 40.4  | `borderless`×7, `None`×5   |
| `gold`       |  12 | 127.7 / 127.9 / 199.6 (138.3 ± 21.1) | 50.9 / 89.9 / 98.5    | 4.5 / 6.9 / 29.0   | `None`×11, `borderless`×1  |
| `yellow`     |  12 | 152.7 / 152.7 / 152.7 (152.7 ± 0.0)  | 227.0 / 227.0 / 227.0 | 0.0 / 0.0 / 0.1    | `None`×12                  |
| `borderless` |  12 | 19.6 / 81.4 / 152.3 (83.5 ± 34.0)    | 2.2 / 19.7 / 58.4     | 11.4 / 40.1 / 59.3 | `borderless`×10, `black`×2 |

### 2b. Catalogue images (what production classifies) — production placement

| true colour  |   n | brightness                        | saturation         | mean std (R)       | classifier says                        |
| ------------ | --: | --------------------------------- | ------------------ | ------------------ | -------------------------------------- |
| `black`      |  12 | 0.0 / 0.0 / 85.1 (20.6 ± 32.3)    | 0.0 / 0.0 / 92.0   | 0.0 / 0.0 / 48.0   | `black`×9, `borderless`×3              |
| `white`      |  64 | 0.0 / 44.8 / 255.0 (52.3 ± 66.8)  | 0.0 / 5.4 / 85.7   | 0.0 / 11.3 / 57.4  | `black`×30, `borderless`×29, `white`×5 |
| `silver`     |  31 | 0.0 / 33.8 / 120.8 (44.0 ± 44.4)  | 0.0 / 9.0 / 70.2   | 0.0 / 22.4 / 56.0  | `borderless`×16, `black`×15            |
| `gold`       |   1 | 126.0                             | 90.0               | 0.9                | `None`                                 |
| `borderless` |  12 | 42.5 / 62.7 / 103.9 (67.5 ± 18.6) | 8.0 / 74.7 / 150.8 | 21.9 / 36.1 / 62.1 | `borderless`×12                        |

The five catalogue images that classify `white` are not white borders. Four are
`Food [SLD] (scan)` — scans on white paper, reading 247–249 — and one is
`Brain Freeze (Normal) [MB2]`, reading a flat 255.0. They are correct by
accident, on background rather than border.

### 2c. Per band, not just combined

A border is not necessarily uniform on all four edges, and these bands are not.
Values are the mean, across that colour's samples, of each band's own
statistics. `production` placement.

**Official renders (trimmed):**

| colour       | band   |     R |     G |     B | brightness | saturation | std (R) |
| ------------ | ------ | ----: | ----: | ----: | ---------: | ---------: | ------: |
| `black`      | left   |  15.8 |  12.6 |  10.6 |       13.0 |        5.2 |     4.3 |
| `black`      | right  |  17.1 |  10.8 |   8.4 |       12.1 |        8.8 |     5.8 |
| `black`      | top    |     — |     — |     — |          — |          — |       — |
| `black`      | bottom |  12.2 |   9.9 |   7.9 |       10.0 |        4.3 |     0.1 |
| `white`      | left   | 236.6 | 236.3 | 236.7 |      236.5 |        2.1 |     1.2 |
| `white`      | right  | 237.4 | 237.0 | 237.6 |      237.3 |        2.2 |     1.0 |
| `white`      | top    |     — |     — |     — |          — |          — |       — |
| `white`      | bottom | 236.9 | 236.7 | 237.3 |      237.0 |        2.1 |     1.4 |
| `silver`     | left   | 142.2 | 154.5 | 156.2 |      151.0 |       15.8 |    33.5 |
| `silver`     | right  | 144.4 | 152.8 | 157.2 |      151.5 |       13.2 |    33.2 |
| `silver`     | top    |     — |     — |     — |          — |          — |       — |
| `silver`     | bottom |  67.5 |  68.9 |  66.5 |       67.7 |        6.5 |     1.7 |
| `gold`       | left   | 175.2 | 148.6 |  90.8 |      138.2 |       84.4 |    11.2 |
| `gold`       | right  | 177.4 | 147.9 |  91.9 |      139.1 |       85.5 |     7.9 |
| `gold`       | top    |     — |     — |     — |          — |          — |       — |
| `gold`       | bottom | 177.2 | 146.5 |  88.9 |      137.5 |       88.3 |     9.5 |
| `yellow`     | left   | 246.0 | 193.0 |  19.0 |      152.7 |      227.0 |     0.0 |
| `yellow`     | right  | 246.0 | 193.0 |  19.0 |      152.7 |      227.0 |     0.0 |
| `yellow`     | top    |     — |     — |     — |          — |          — |       — |
| `yellow`     | bottom | 246.0 | 193.0 |  19.0 |      152.7 |      227.0 |     0.0 |
| `borderless` | left   | 112.9 | 116.1 | 111.8 |      113.6 |       27.5 |    53.3 |
| `borderless` | right  | 120.9 | 123.1 | 117.4 |      120.5 |       37.4 |    52.6 |
| `borderless` | top    |     — |     — |     — |          — |          — |       — |
| `borderless` | bottom |  20.0 |  15.2 |  13.6 |       16.3 |        8.3 |     1.3 |

The em-dashes on every `top` row are not missing data. **On a trimmed image the
top band is a zero-area crop and is silently discarded** — see §3b. Every
trimmed image in production is classified from three bands, never four.

**Catalogue images (bleed-inclusive):**

| colour       | band   |     R |     G |    B | brightness | saturation | std (R) |
| ------------ | ------ | ----: | ----: | ---: | ---------: | ---------: | ------: |
| `black`      | left   |  30.6 |  19.2 | 18.0 |       22.6 |       16.1 |    17.7 |
| `black`      | right  |  29.9 |  20.7 | 19.0 |       23.2 |       15.6 |    20.8 |
| `black`      | top    |  45.2 |  32.3 | 32.6 |       36.7 |       17.2 |     6.8 |
| `black`      | bottom |   0.0 |   0.0 |  0.0 |        0.0 |        0.0 |     0.0 |
| `white`      | left   |  57.2 |  58.5 | 55.3 |       57.0 |       15.0 |    24.7 |
| `white`      | right  |  60.8 |  62.7 | 56.5 |       60.0 |       17.9 |    25.5 |
| `white`      | top    |  68.6 |  73.8 | 74.9 |       72.4 |       25.4 |    12.7 |
| `white`      | bottom |  20.0 |  20.0 | 19.9 |       19.9 |        0.1 |     0.2 |
| `silver`     | left   |  50.8 |  52.5 | 56.8 |       53.4 |       20.0 |    30.3 |
| `silver`     | right  |  53.4 |  52.6 | 54.6 |       53.5 |       18.6 |    34.0 |
| `silver`     | top    |  57.0 |  69.8 | 80.4 |       69.0 |       29.4 |    15.9 |
| `silver`     | bottom |   0.0 |   0.0 |  0.0 |        0.0 |        0.0 |     0.0 |
| `gold`       | left   | 166.0 | 136.0 | 76.0 |      126.0 |       90.0 |     0.0 |
| `gold`       | right  | 165.9 | 136.0 | 76.1 |      126.0 |       89.8 |     3.7 |
| `gold`       | top    | 166.0 | 136.0 | 76.0 |      126.0 |       90.0 |     0.0 |
| `gold`       | bottom | 166.0 | 136.0 | 76.0 |      126.0 |       90.0 |     0.0 |
| `borderless` | left   | 120.4 |  85.2 | 58.4 |       88.0 |       83.1 |    61.7 |
| `borderless` | right  | 122.7 |  73.8 | 48.8 |       81.8 |       82.1 |    68.3 |
| `borderless` | top    | 135.7 |  92.0 | 54.6 |       94.1 |       98.1 |    36.5 |
| `borderless` | bottom |  10.7 |   2.7 |  5.2 |        6.2 |       12.5 |     0.6 |

Note the `bottom` column: `0.0` for `black` and `silver`, `19.9` for `white`,
`6.2` for `borderless`. The bottom band on a bleed-inclusive image is 91% bleed
margin and reads near-black almost regardless of the card. That single band
drags the four-band mean down for every colour.

### 2d. The gold border, measured

The question as asked. Official Scryfall renders, `production` placement, per
card:

| set    | card                             |     R |     G |     B | brightness | saturation | std (R) |
| ------ | -------------------------------- | ----: | ----: | ----: | ---------: | ---------: | ------: |
| `ptc`  | Eron the Relentless              | 168.0 | 137.6 |  78.1 |     127.88 |      89.87 |    6.86 |
| `wc02` | Forest                           | 168.0 | 137.6 |  78.1 |     127.88 |      89.87 |    6.86 |
| `wc03` | Goblin Warchief                  | 167.9 | 137.4 |  77.9 |     127.72 |      89.94 |    4.54 |
| `wc01` | Jan Tomcani Bio                  | 168.0 | 137.6 |  78.1 |     127.88 |      89.87 |    6.86 |
| `wc97` | Cloud Elemental                  | 168.0 | 137.6 |  78.1 |     127.88 |      89.87 |    6.86 |
| `wc00` | Priest of Titania                | 168.0 | 137.6 |  78.1 |     127.88 |      89.87 |    6.86 |
| `wc98` | Survival of the Fittest          | 168.0 | 137.6 |  78.1 |     127.88 |      89.87 |    6.86 |
| `wc99` | Sphere of Resistance             | 168.0 | 137.6 |  78.1 |     127.88 |      89.87 |    6.86 |
| `wc04` | Gabriel Nassif Bio               | 167.9 | 137.4 |  77.9 |     127.72 |      89.94 |    4.54 |
| `punk` | The Sphere                       | 193.7 | 158.3 |  95.2 |     149.07 |      98.55 |   15.14 |
| `pssc` | Finally! Left-Handed Magic Cards | 231.7 | 209.5 | 157.6 |     199.59 |      74.15 |   13.04 |
| `hho`  | Treasure                         | 182.0 | 166.8 | 131.1 |     159.97 |      50.89 |   28.97 |

**A gold border is `RGB(168, 138, 78)`.** Nine of twelve samples, drawn from
nine different expansions (`ptc`, `wc97`–`wc04`), agree to within 0.2 of a
level on every channel — Scryfall renders the World Championship / Pro Tour
Collector gold border from one template, so this is one measurement replicated,
not nine independent ones. The three outliers are non-World-Championship
oddities: an Unknown Event promo, a Secret Lair showcase, and a Happy Holidays
promo.

The single gold-bordered **catalogue** image measures `RGB(166.0, 136.0, 76.0)`
— brightness 126.00, saturation 90.00, std 0.93. That is 2 levels from the
official render on every channel. n=1, so this establishes only that one real
proxy's gold bleed reproduces the official gold closely; it does not establish
a tolerance.

### 2e. The yellow border, measured

| set   | card                        |     R |     G |    B | brightness | saturation | std (R) |
| ----- | --------------------------- | ----: | ----: | ---: | ---------: | ---------: | ------: |
| `dft` | Hazoret, Godseeker          | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Riverchurn Monument         | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Coalstoke Gearhulk          | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Mindspring Merfolk          | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Daretti, Rocketeer Engineer | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Webstrike Elite             | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Bulwark Ox                  | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Valor's Flagship            | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Marketback Walker           | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Gonti, Night Minister       | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Mimeoplasm, Revered One     | 246.0 | 193.0 | 19.0 |     152.67 |     227.00 |    0.00 |
| `dft` | Forest                      | 246.0 | 193.0 | 19.0 |     152.67 |     227.01 |    0.09 |

**A yellow border is `RGB(246, 193, 19)`.** Twelve different cards produce
values identical to two decimal places, at a within-band standard deviation of
`0.00`.

**That zero is a warning, not a result.** Read §4 before using it.

---

## 3. The defects

### 3a. DEFECT 1 — the bands sample the bleed margin, not the border

**Severity: live, affects the whole catalogue population.**

The module derives the bleed geometry from the same reference constants the
bands were supposedly tuned against: a 3.175 mm bleed on a 63×88 mm card means
the bleed margin occupies `_WIDTH_MARGIN_FRACTION = 0.04578` of the image width
per side and `_HEIGHT_MARGIN_FRACTION = 0.03365` of the height. Against
`_BORDER_SAMPLE_BANDS`:

| band   | band extent   | bleed margin extent | fraction of band inside the bleed |
| ------ | ------------- | ------------------- | --------------------------------: |
| left   | 0.030 – 0.050 | 0.00000 – 0.04578   |                         **78.9%** |
| right  | 0.950 – 0.970 | 0.95422 – 1.00000   |                         **78.9%** |
| top    | 0.020 – 0.035 | 0.00000 – 0.03365   |                         **91.0%** |
| bottom | 0.965 – 0.980 | 0.96635 – 1.00000   |                         **91.0%** |

The source comment asserts these boxes are "already implicitly calibrated" for
the bleed-inclusive convention. The arithmetic above says the opposite: they are
calibrated to sit _in the bleed_, and only read the border at all through the
9–21% of each band that spills onto the card.

This is invisible whenever the bleed continues the border colour — a
black-bordered proxy with a black bleed reads black, correctly, for the wrong
reason. It becomes visible the moment the two differ. Proxy renders very
commonly pad the bleed with flat black regardless of the card's border:

| population | colour       | images reading exactly `brightness = 0.00` **and** `std = 0.00` |
| ---------- | ------------ | --------------------------------------------------------------: |
| catalogue  | `black`      |                                                  8 / 12 (66.7%) |
| catalogue  | `white`      |                                             **24 / 64 (37.5%)** |
| catalogue  | `silver`     |                                             **12 / 31 (38.7%)** |
| catalogue  | `borderless` |                                                          0 / 12 |
| official   | `black`      |                                                  4 / 12 (33.3%) |
| official   | all others   |                                                               0 |

Those are cards the classifier calls `black` at a uniformity of exactly zero —
its strongest possible reading — on the strength of padding. `Icatian Store [5ED]`, `Birds of Paradise [7ED]`, `Seeker of Skybreak [7ED]` and
`Riding the Dilu Horse [PTK]` are all white-bordered printings whose catalogue
images read `RGB(0, 0, 0)` on all four bands.

The production cross-tab in §0 is the same defect counted at scale: 0% recall on
`white`, 0% on `silver`. The classifier does emit `white` 7,475 times and
`silver` 408 times across the 220,579 evidence rows, but not once on a card
whose true border is white or silver.

**Consequence for the tags.** `cast_border_attribute_vote` casts a
`CardTagVote` for every non-`None` reading, and `local_layout_class_cast` casts
from the stored `layout_class`. Wrong readings become votes.

### 3b. DEFECT 2 — the top band is a zero-area crop on every trimmed image

**Severity: live, 2,786 evidence rows (1.3%).**

`normalize_crop_box(band, "trimmed")` remaps the four bands. On a 488×680
Scryfall-shaped image:

| band   | remapped fractions               | pixel box           |  area |
| ------ | -------------------------------- | ------------------- | ----: |
| left   | (0.0, 0.12474, 0.00464, 0.87526) | (0, 84, 2, 595)     |  1022 |
| right  | (0.99536, 0.12474, 1.0, 0.87526) | (485, 84, 488, 595) |  1533 |
| top    | (0.11472, 0.0, 0.88528, 0.00145) | (55, 0, 432, **0**) | **0** |
| bottom | (0.11472, 0.99855, 0.88528, 1.0) | (55, 679, 432, 680) |   377 |

`0.00145 × 680 = 0.986`, and `int()` truncates it to 0. The crop has zero
height, `getdata()` returns empty, and `classify_border_color`'s
`if not pixels: continue` drops the band without comment. Every trimmed image is
classified from three bands.

This is not why trimmed images misclassify — they mostly do not; the remap
collapses the side bands onto the card's true outer edge and black/white read
correctly. It is a silent, undocumented loss of a quarter of the sample, and it
would bite anyone re-tuning the bands.

### 3c. DEFECT 3 — `_SILVER_BRIGHTNESS_RANGE = (140, 200)` selects nothing

**Severity: the silver branch is unreachable for real silver borders.**

Measured brightness of the twelve official silver-bordered renders, sorted:

`82.3, 105.8, 105.8, 108.8, 118.2, 119.2, 124.5, 124.5, 127.8, 127.8, 128.6, 207.0`

**Zero of twelve fall inside [140, 200].** Eleven sit _below_ the range's floor;
the twelfth (`Yule Ooze`, a Happy Holidays promo) sits above its ceiling.

The four samples whose four edges agree most closely — `Mise`, `Sheep`,
`Goblin Bowling Team`, `Goblin Mime`, all with saturation ≤ 2.9 — read 108.8,
127.8, 127.8 and 128.6. A flat Un-set silver border is a neutral mid-grey around
`RGB(128, 128, 128)`, not the 140–200 the constant assumes. The eight less
uniform samples sit lower still, because the bottom band drags them down: the
per-band table in §2c shows silver's left and right bands averaging 151.0 and
151.5 against a bottom band of 67.7.

`_SILVER_MAX_SATURATION = 20` is, by contrast, well chosen: measured silver
saturations are 0.0–31.5 with a median of 8.2, and the four flattest samples
(`Mise`, `Sheep`, `Goblin Bowling Team`, `Goblin Mime`) read 0.0–2.9.

Even with the brightness range corrected, `_BORDER_UNIFORMITY_STD_THRESHOLD = 18.0` intercepts 7 of the 12 first — many Un-cards are full-art or
irregularly-framed and their four edges genuinely disagree. Fixing the range is
necessary but not sufficient.

### 3d. What the existing thresholds get right

Stated as plainly as the defects, because they were also unmeasured and they
hold up:

- **`_BLACK_MAX_BRIGHTNESS = 60`** — measured black borders run 0.0–34.7
  (median 16.2). All twelve clear the threshold with 25 points of headroom.
  **Correct.** The one caution is in the other direction: two of twelve
  borderless samples read 19.6 and 39.8 and are captured as `black`. Lowering
  the ceiling to ~40 would exclude the 39.8 case while still admitting every
  measured black sample, but would do nothing for the 19.6 case. **No clean
  separating value exists in this data**, and n=12 is too small to set one; not
  established.
- **`_WHITE_MIN_BRIGHTNESS = 210`** — measured white borders run 235.4–237.7
  (mean 236.9, sd 1.0). All twelve clear it with 25 points of headroom.
  **Correct**, and the tightness of the measured cluster means it could be
  raised to ~225 if false positives from white backgrounds (see §2b) ever
  matter. Not recommended without evidence that they do.
- **`_BORDER_UNIFORMITY_STD_THRESHOLD = 18.0`** — sits inside a real gap for
  black and white (measured std 0.0–5.8 and 0.8–1.9 on the side bands) but
  inside the _distribution_ for silver and borderless. **Not established** as
  right or wrong; it is doing a different job than the colour thresholds and
  needs its own study.

---

## 4. Recommended thresholds for gold and yellow

Expressed in the statistics `classify_border_color` already computes, so they
drop in beside the existing constants.

### 4a. Are gold and yellow separable?

**Yes, by saturation. No, by brightness.**

| statistic  | gold (n=12)     | yellow (n=12) | separable?                                              |
| ---------- | --------------- | ------------- | ------------------------------------------------------- |
| brightness | 127.7 – 199.6   | 152.67        | **No** — yellow's single value sits inside gold's range |
| saturation | 50.9 – **98.6** | **227.0**     | **Yes** — a gap of 128.4 with nothing in it             |

Saturation alone cleanly separates them, and the owner's ruling that yellow gets
its own test is supported by the measurement rather than merely compatible with
it.

The nearest non-yellow saturation measured anywhere is `Chandra Nalaar [SLD]`, a
_borderless_ catalogue image at 150.8. A yellow rule must therefore clear 150.8,
not merely clear gold's 98.6.

### 4b. Proposed constants

```python
# gold: measured RGB(168, 138, 78) on 9 of 12 official renders (World
# Championship / Pro Tour Collector template); 3 non-WC outliers run brighter
# and less saturated. Range widened past the measured extremes on both ends.
_GOLD_BRIGHTNESS_RANGE = (110, 210)
_GOLD_SATURATION_RANGE = (40, 130)

# yellow: measured RGB(246, 193, 19), Aetherdrift First-Place Foil box toppers.
# Floor set at 180 to clear the brightest non-yellow saturation measured
# anywhere (150.8, a borderless Secret Lair), not merely to clear gold (98.6).
_YELLOW_BRIGHTNESS_RANGE = (120, 190)
_YELLOW_MIN_SATURATION = 180
```

Ordering matters: both branches must sit **after** the silver branch (silver's
saturation ceiling of 20 is far below gold's floor of 40, so they cannot
collide) and yellow must be tested **before** gold, since a `saturation ≥ 180`
reading would also satisfy `_GOLD_SATURATION_RANGE`'s upper bound if that bound
were ever raised.

### 4c. Why yellow's tolerance is wide despite zero measured variance

The measured yellow spread is `0.00`. A threshold fitted to that spread would be
fitted to a rendering template, not to a colour, and the evidence for that is
directly in the data: twelve different cards from twelve different collector
numbers produce byte-identical band means because Scryfall composites them all
from one frame asset.

Three compounding reasons for the wide range above:

1. **All 90 yellow printings are from one expansion** — Aetherdrift (`dft`),
   verified by grouping the full population by expansion. One set means one
   print run, one paper stock, one photographic pass. The measured spread is
   the spread _of a single print run_, not of the colour.
2. **All 90 carry the same treatment** — `promo_types = ["firstplacefoil", "boxtopper"]` on all 90, `frame = "2015"` on all 90, and an `inverted`
   `frame_effect` on all 90 (54 plain `inverted`, 25 `legendary + inverted`,
   8 `fullart + inverted`, 3 `enchantment + inverted`). The sample cannot
   distinguish "this is what yellow measures" from "this is what the Aetherdrift
   First-Place Foil treatment measures".
3. **Zero catalogue images exist to check against.** Every other colour has at
   least one real proxy scan to compare an official render to; yellow has none.
   The scanner cast, JPEG artifacts and resampling that a proxy scan introduces
   are entirely unmeasured for this colour. The one gold data point we do have
   shifted by 2 levels per channel; there is no basis for assuming yellow shifts
   less.

Hence brightness ±30 around the measured 152.67 rather than the ±0 the sample
would justify, and a saturation floor placed by the nearest _competing_
measurement rather than by yellow's own variance.

### 4d. The trap this recommendation deliberately avoids

`border_color = "yellow"` and `expansion = "dft"` are, today, a perfect 1:1
correlation in the catalogue. Nothing above keys on `dft`. A fixture or test
that selected yellow cards by set code would pass today for the wrong reason,
would silently stop testing yellow the day Wizards ships a second yellow-bordered
set, and would never fail if the colour measurement itself regressed. Yellow
samples are `dft` cards because `dft` cards are the only yellow cards that
exist — that is a property of the sample, and it must not become a property of
the threshold or of anything that tests it.

### 4e. Adding these constants will change nothing in production until §3a is fixed

Stated plainly so the sequencing is not lost: the catalogue holds **one** image
matched to a gold-bordered printing and **zero** matched to a yellow one. Even
if both were plentiful, the bands would sample their bleed margins. **The
band-placement defect must be fixed before a gold or yellow threshold can do any
work at all.**

---

## 5. What Scryfall's 90 `yellow` printings actually are

Looked up, not inferred from the name. All 90 rows, grouped:

- **Expansion:** Aetherdrift (`dft`), all 90, released 2025-02-14. No other set
  has a yellow-bordered printing.
- **Collector numbers:** 427–516 — above the set's main run, the usual position
  for a bonus sheet.
- **`promo_types`:** `["firstplacefoil", "boxtopper"]` on all 90.
- **`frame`:** `2015` on all 90.
- **`frame_effects`:** `inverted` on all 90 — 54 plain, 25 with `legendary`,
  8 with `fullart`, 3 with `enchantment`.
- **`full_art`:** 10 of 90.

They are the Aetherdrift **First-Place Foil box toppers**: a racing-trophy
treatment in which the card frame is inverted — black text box, black type line,
and a solid saturated yellow surround where a normal card has its black border.
Visual inspection of `Hazoret, Godseeker [dft 462]` confirms the yellow is the
card's outer border and the full frame surround, not a decorative accent.

This matters for weighting. Gold is a legacy oddity: World Championship decks,
`ptc`/`wc97`–`wc04`, cards nobody has printed since 2004. **Yellow is a current
treatment from a 2025 set, and users will upload proxies of it.** The catalogue
holding zero yellow images today is a statement about the catalogue's coverage,
not about demand.

---

## 6. Machine-readable data

- [`../data/2026-07-29-border-colour-measurements.csv`](../data/2026-07-29-border-colour-measurements.csv)
  — 576 rows, one per (image × placement). Every figure in this document is
  derivable from it: per-image and per-band R/G/B, brightness, saturation,
  R-channel standard deviation, pixel count, the image's own aspect ratio and
  `bleed_class`, the stored `prod_layout_class` where one exists, and the source
  URL.
- [`../data/2026-07-29-border-colour-measure.py`](../data/2026-07-29-border-colour-measure.py)
  — the harness. Caches every fetch; re-running it against a warm cache makes no
  network calls. A future threshold change can be re-derived from the CSV
  without re-measuring, or re-measured by re-running the harness against a new
  sample manifest.

Sample manifests were generated from production by the queries recorded in §1d
and §1e; they are not committed, because every field they carried is reproduced
in the CSV.

---

## 7. Open items

1. **Fix the band placement before anything else** (§3a). The bands need to be
   defined relative to the _card_, not the image, with the bleed margin mapped
   in for bleed-inclusive images — the inverse of what `normalize_crop_box`
   already does for trimmed ones. The `cardspace` placement in the CSV is a
   first attempt and is **not** a recommendation: at 3–5% of card width it lands
   past the border on the card frame (an MTG black border is roughly 1.5–2% of
   card width), and it classifies worse than `production` on both populations.
   The correct band is much thinner and much closer to the card edge. Setting it
   is a separate measurement job.
2. **Decide whether to re-run Stage C** once the placement is fixed. 220,579
   `ImageEvidence.layout_class` values and every attribute-chip vote derived
   from them were computed with the defective placement.
3. **Correct `_SILVER_BRIGHTNESS_RANGE`** (§3c). The measured distribution
   supports roughly (95, 145), but with n=12 and 7 of the 12 intercepted by the
   uniformity gate first, this should be re-measured after item 1 rather than
   set from this sample.
4. **Fix or document the degenerate top band** (§3b).
5. **Gold and yellow thresholds** (§4b) are ready to drop in, but see §4e — they
   will not do any work until item 1 lands.

---

## 8. Caveats

- The official population is Scryfall's own renders, which are composited from
  frame templates. Nine of the twelve gold samples and all twelve yellow samples
  are therefore one measurement replicated, not twelve independent ones. Sample
  counts overstate the evidence for those two colours specifically.
- The catalogue population is what production classifies, and the white/silver/
  gold figures are full censuses rather than samples. The black and borderless
  catalogue figures are 12-card samples of 16,477 and 2,912 and carry ordinary
  sampling error; the production cross-tab in §0 (n = 9,930 and 1,942) is the
  authority for those two.
- The difference between the two populations that a threshold's tolerance would
  have to absorb is **not established for gold** (one catalogue image, shifted 2
  levels per channel) and **not established at all for yellow** (zero catalogue
  images).
- Nothing here was written to production. No classifier code was changed.
