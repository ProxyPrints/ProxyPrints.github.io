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

| Attribute              | Source                               | Notes                |
| ---------------------- | ------------------------------------ | -------------------- |
| `data-card-name`       | the card's name                      |                      |
| `data-card-identifier` | the card's image identifier          | (the drive image id) |
| `data-source-key`      | the card's source key                |                      |
| `data-card-dpi`        | the card's DPI                       |                      |
| `data-card-type`       | `"card"`, `"cardback"`, or `"token"` |                      |

If a card isn't yet resolved (e.g. still loading, or no card selected for a
slot), the attributes are omitted entirely rather than emitted with an empty
value.

## `mpc:card-selected` event

When the user confirms an art selection for a card slot (via the prev/next
controls or the grid selector), the slot's root element dispatches a
bubbling, composed `CustomEvent` named `mpc:card-selected`:

```js
document.addEventListener("mpc:card-selected", (event) => {
  console.log(event.detail);
  // { name, identifier, sourceKey, dpi, cardType }
});
```

`event.detail` mirrors the same underlying fields as the data attributes
above (camelCased): `name`, `identifier`, `sourceKey`, `dpi`, `cardType`.
Any field that isn't available is omitted from `detail` rather than included
with an empty value.

## Forward compatibility

This surface is additive-only: future changes may introduce further
attributes (for example, the card's resolved printing set/collector number)
or further fields on the event detail, but won't repurpose or remove the
ones documented here without a deliberate, documented break.
