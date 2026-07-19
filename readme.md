<!-- GENERATED FILE — do not edit directly.
     Assembled from marked regions in docs/ (see
     docs/proposals/proposal-i-readme-pipeline.md) by
     .github/scripts/publish_readme.py — edit the source region,
     then rerun that script and commit the result.
     GitHub hides this comment when rendering the file. -->

# ProxyPrints

**ProxyPrints** is a free card catalog and proxy-printing tool for
Magic: The Gathering, built for players who want to print custom or
proxy cards at home. Search a huge community-sourced catalog of card
images, arrange them into a print-ready sheet, and export a PDF sized
for your printer — no account, no paywall.

- **Live site**: [proxyprints.ca](https://proxyprints.ca/)
- **Source code**: this repository (frontend + backend)

ProxyPrints is a fork of
[mpc-autofill](https://github.com/chilli-axe/mpc-autofill) by
**chilli_axe** — the search catalog, the autofill/PDF pipeline, and the
original project design are their work. This fork adds its own catalog
sourcing, printing-identification tooling, and hosting, and is
maintained independently.

---

![web-ci](https://github.com/ProxyPrints/ProxyPrints.github.io/actions/workflows/web-ci.yml/badge.svg)
![cloudflare-workers-ci](https://github.com/ProxyPrints/ProxyPrints.github.io/actions/workflows/cloudflare-workers-ci.yml/badge.svg)

ProxyPrints is web-only and does not build or distribute the desktop autofill client. For that tool, see the upstream project: [chilli-axe/mpc-autofill](https://github.com/chilli-axe/mpc-autofill).

## License

This project is licensed under the [GNU General Public License 3](https://www.gnu.org/licenses/gpl-3.0.en.html) — see [`LICENSE.md`](https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/LICENSE.md) for the full text. It is free to use, modify, and distribute.

GPL-3.0. Complete corresponding source: this repository. Third-party-derived modules are listed in [`NOTICE`](https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/NOTICE).

## Documentation

Full documentation lives on this repo's [Wiki](https://github.com/ProxyPrints/ProxyPrints.github.io/wiki), generated from [`docs/`](https://github.com/ProxyPrints/ProxyPrints.github.io/tree/master/docs).
