# User Guide

_Skeleton — sections below are planned, not all written yet._ Migrated
from the wiki's own `User-Guide` page (previously hand-maintained there
directly) — this file is now the source; the wiki page regenerates from
it. See [`documentation-process.md`](documentation-process.md).

## Searching for cards

How to search the catalog, read search results, and pick a printing for
a slot in your decklist.

The **Editor** page (the redesigned `/display` route - nav+footer redesign,
2026-07-22, renamed the nav link from "Display (beta)" to plain "Editor";
the classic `/editor` page is still reachable directly by URL but no longer
has a nav link of its own) search bar is dual-mode: an **Add / Browse**
toggle next to the input switches between adding cards to your project
(the usual decklist-line paste/search box) and browsing the whole
catalog without touching your project — browsing renders a grid of
matching cards you can add individually, and the center of the page
follows the same toggle, switching between your print sheet preview and
the browse results. The **+ Add Cards** dropdown next to the search box
covers the same Text / XML / CSV / URL import options available
elsewhere in the app.

## "What's That Card?" — helping identify printings

ProxyPrints crowdsources which real Magic printing a community-submitted
card image depicts, so search results and filters (Full Art, Borderless,
etc.) can be more precise. If you spot the vote queue while browsing,
here's what it's asking and why your input helps everyone's search
results.

The vote queue at **What's That Card?** presents each question as a
quiz-reveal hero: the card image in question sits in its own column on
a deep-blue hero field (with an animated starburst behind it) alongside
a title that pops into place word by word every time a new card is
shown, while the actual question — the candidate printings or attribute
chips to pick from — sits in a scrolling panel beside it. On a wide
screen that question panel scrolls on its own while the card stays put,
so you never lose sight of what you're being asked about; on a narrow
screen the card instead pins near the top of the screen while the
questions scroll underneath it.

## Exporting a print-ready PDF

How to arrange your chosen cards into pages, set bleed/DPI/paper size,
and export a PDF ready to print and cut.

The **Editor** page's Page Setup section defaults to Letter landscape,
3.175mm bleed, and a **Margin profile** picker (Borderless / Bordered /
Rear-feed) calibrated against an Epson ET-8500/8550 printer — Borderless
is the default and the only profile that fits full bleed on a 4-across
sheet; the other two trade some bleed for a printer-supported margin,
and the page warns (rather than silently shrinking your bleed value) if
your current bleed exceeds what the selected profile can fit.

The same section's **Card spacing (mm)** control sets the gutter between
cards independently on each axis — Horizontal (X) and Vertical (Y)
default to 0mm and 14.5mm respectively, so columns butt together for
strip-cutting while rows keep a gap that suits a die cutter. A
**Link**/**Linked** toggle next to it locks the two axes to move
together when you'd rather set one value for both.

Once your sheet is ready, the **Editor** page's Finish footer has two
equal-weight buttons: **Save Deck** (or **Sign in to Save**, if you're
not signed in) and **Print / Export →**, plus the existing **Export**
dropdown for lightweight XML/card-image/decklist exports and a small
cloud-download counter beside it (nav+footer redesign, 2026-07-22 - this
used to sit in the top navbar; it now lives next to the exports it counts,
here and again on the Print page). Your project is
also quietly backed up to this browser as you work — a small "Draft
backed up locally" note under the buttons confirms it — and pressing
**Print / Export →** while signed in with unsaved changes offers to save
your deck first, since the print/PDF step can use a lot of your
browser's memory and you don't want to lose your work if it struggles.

## Saving and re-using a project

Local-folder and Google Drive options for coming back to a project
later. If you're signed in and have saved decks already, the **Editor**
page's empty-project landing screen lists them directly so you can jump
back into one without a trip to **My Decks** first (**My Decks** itself
has no nav-bar link since the 2026-07-22 nav redesign - reach it from this
landing screen, the homepage's own CTA, or `/myDecks` directly).

## Saved decks, export, and the standalone decrypt tool

Signed in with Discord? The classic editor and the Editor page's Save
button persists your deck to your account, and the **My Decks** page lists
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
