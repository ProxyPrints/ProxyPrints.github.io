# DOM API

The frontend exposes a small set of stable, machine-readable DOM hooks on
rendered cards, intended for client-side tooling, testing selectors, and
accessibility. This is not a public/versioned API in the semver sense, but
it's meant to be relied upon.

**Stability: best-effort, semver-ish.** Existing attributes and event fields
won't be renamed or removed without a deliberate, documented change. New
attributes/fields may be added at any time (see "Forward compatibility"
below) — don't assume the set documented here is exhaustive.

## Data attributes

Every element that renders an individual card (the project editor's card
slots, the art-selection grid selector, and the card detail modal) carries
the following `data-*` attributes on its root element, sourced from the same
card data already available to the frontend:

| Attribute                    | Source                                          | Notes                                    |
| ---------------------------- | ----------------------------------------------- | ---------------------------------------- |
| `data-card-name`             | the card's name                                 |                                          |
| `data-card-identifier`       | the card's image identifier                     | (the drive image id)                     |
| `data-source-key`            | the card's source key                           |                                          |
| `data-card-dpi`              | the card's DPI                                  |                                          |
| `data-card-type`             | `"card"`, `"cardback"`, or `"token"`            |                                          |
| `data-card-set-code`         | the card's resolved printing's set code         | only present once a printing is resolved |
| `data-card-collector-number` | the card's resolved printing's collector number | only present once a printing is resolved |

If a card isn't yet resolved (e.g. still loading, or no card selected for a
slot), the attributes are omitted entirely rather than emitted with an empty
value. The same applies to `data-card-set-code`/`data-card-collector-number`
specifically when the card has a resolved image but no printing match yet.

## Printing-candidate buttons

The printing-tag review queue ("What's That Card?", the standalone
queue page) and the printing-tag picker embedded in the card detail modal
both render a grid of Scryfall printing candidates for the user to vote on.
Each candidate's button element carries a subset of the same attributes:

| Attribute                    | Source                                      |
| ---------------------------- | ------------------------------------------- |
| `data-card-name`             | the name of the card currently being tagged |
| `data-card-identifier`       | this candidate printing's identifier        |
| `data-card-set-code`         | this candidate printing's set code          |
| `data-card-collector-number` | this candidate printing's collector number  |

**This is a different kind of hit than a normal card slot.** `data-card-name`
names the card being tagged, while `data-card-identifier`/
`data-card-set-code`/`data-card-collector-number` describe one candidate
printing being offered as a possible match — client tooling should not
assume the candidate described by those three attributes actually depicts
the card named in `data-card-name`; that's exactly the open question the
user is being asked to resolve by voting. The "No match" button in either
UI carries no candidate-derived attributes at all, since it isn't a
printing candidate.

## `mpc:card-selected` event

When the user confirms an art selection for a card slot (via the prev/next
controls or the grid selector), the slot's root element dispatches a
bubbling, composed `CustomEvent` named `mpc:card-selected`:

```js
document.addEventListener("mpc:card-selected", (event) => {
  console.log(event.detail);
  // { name, identifier, sourceKey, dpi, cardType, setCode, collectorNumber }
});
```

`event.detail` mirrors the same underlying fields as the data attributes
above (camelCased): `name`, `identifier`, `sourceKey`, `dpi`, `cardType`,
`setCode`, `collectorNumber`. Any field that isn't available is omitted from
`detail` rather than included with an empty value.

## Forward compatibility

This surface is additive-only: future changes may introduce further
attributes or further fields on the event detail, but won't repurpose or
remove the ones documented here without a deliberate, documented break.
