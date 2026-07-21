# User Guide

_Skeleton — sections below are planned, not all written yet._ Migrated
from the wiki's own `User-Guide` page (previously hand-maintained there
directly) — this file is now the source; the wiki page regenerates from
it. See [`documentation-process.md`](documentation-process.md).

## Searching for cards

How to search the catalog, read search results, and pick a printing for
a slot in your decklist.

## "What's That Card?" — helping identify printings

ProxyPrints crowdsources which real Magic printing a community-submitted
card image depicts, so search results and filters (Full Art, Borderless,
etc.) can be more precise. If you spot the vote queue while browsing,
here's what it's asking and why your input helps everyone's search
results.

## Exporting a print-ready PDF

How to arrange your chosen cards into pages, set bleed/DPI/paper size,
and export a PDF ready to print and cut.

## Saving and re-using a project

Local-folder and Google Drive options for coming back to a project
later.

## Saved decks, export, and the standalone decrypt tool

Signed in with Discord? The editor and display page's Save button
persists your deck to your account, and the **My Decks** page lists
everything you've saved, decrypted right there in your browser — the
server only ever stores encrypted, opaque bytes it can't read.

My Decks also has **Export my decks** and **Import decks** buttons: export
bundles every saved deck into one downloadable file for backup or moving
between accounts/instances, and import decrypts a previously-exported
file (with your passphrase or recovery key) and adds its decks to your
current account. If this site ever goes away, your exported file is still
readable on its own — a small, dependency-free command-line tool
(`decrypt-saved-deck-export/` in the repo) decrypts it using nothing but
Node.js's built-in crypto, no ProxyPrints server or codebase required.

See [`features/saved-decks.md`](features/saved-decks.md) for the full
design (including the zero-knowledge encryption model and per-deck share
links).

---

_Have a question this page doesn't answer yet? Open an issue on the
repo, or check the
[wiki Home page](https://github.com/ProxyPrints/ProxyPrints.github.io/wiki)
for other resources._
