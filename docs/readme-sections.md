# README source regions

Not a standalone doc — feeds `readme.md`'s generated content via the
`readme` emit mode (`.github/scripts/publish_readme.py`), same pattern as
[`wiki-home-intro.md`](wiki-home-intro.md): read directly by a publish
script, not listed in
[`.github/wiki-publish-map.json`](../.github/wiki-publish-map.json)'s
page list, never wiki-published on its own. See
[`proposal-i-readme-pipeline.md`](proposals/proposal-i-readme-pipeline.md)
for the full design and the marker convention (`README-REGION`, distinct
from `DATA-EXTRACT` — that contract is table-only per
`proposal-i-docs-as-site-source.md` §3; these regions are prose).

Every link inside a marked region below is an absolute GitHub URL, never
a relative path — the region text is copied verbatim into `readme.md` at
the repo root, not linted in place. A relative path correct for this
file's own location (`docs/`) would resolve to something else entirely
once copied out to the root. See the header comment in
`publish_readme.py` for the full reasoning.

<!-- README-REGION: license -->

This project is licensed under the [GNU General Public License 3](https://www.gnu.org/licenses/gpl-3.0.en.html) — see [`LICENSE.md`](https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/LICENSE.md) for the full text. It is free to use, modify, and distribute.

<!-- END README-REGION -->

<!-- README-REGION: documentation-pointer -->

Full documentation lives on this repo's [Wiki](https://github.com/ProxyPrints/ProxyPrints.github.io/wiki), generated from [`docs/`](https://github.com/ProxyPrints/ProxyPrints.github.io/tree/master/docs).

<!-- END README-REGION -->

<!-- README-REGION: desktop-tool-pointer -->

ProxyPrints is web-only and does not build or distribute the desktop autofill client. For that tool, see the upstream project: [chilli-axe/mpc-autofill](https://github.com/chilli-axe/mpc-autofill).

<!-- END README-REGION -->
