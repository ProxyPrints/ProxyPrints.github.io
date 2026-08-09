# WTC Design Repass: Intent, Cohesion, and Contextual HUD Architecture

**Date:** August 2026
**Status:** Active Governing Standard (Epic #704)
**Target Surface:** `frontend/src/features/questionFeed/` (`QuestionFeed.tsx`, `QuestionFeedPanel.tsx`, `attributeChips/`, `ArtistSupportLink.tsx`)

---

## 1. Governing Philosophy & Design Intent

The "What's That Card" (WTC) interface is not a collection of static panels; it is an intelligent, context-aware HUD designed to narrow uncertainty step-by-step with ruthless focus.

Past iterations suffered from patchwork scaling, horizontal bloat, and mismatched component dimensions. This design repass establishes strict architectural rules to unify the surface around a single design intent: **naturally centering the user's vision on the immediate comparison and question while contextually surfacing or pruning supporting information.**

---

## 2. Core Architectural Rules

### Rule 1: Uniform Button Geometry (#711)

- All primary decision and action buttons (Yes, No, Not Sure, Skip, custom action triggers) must share identical sizing, padding, corner radii, and typography metrics.
- Eliminate oversized hero modifiers that distort visual hierarchy or create unintended asymmetry in the action row.

### Rule 2: Zero-Latency Interaction (#715)

- Eliminate all click/tap dead zones and multi-click registration bugs.
- Ensure touch and mouse pointer events propagate cleanly without event swallowing, state batching races, or missing touch-action handlers.

### Rule 3: Normalized Image Proportions (#746)

- All visual assets (reference cards, Scryfall art renders, illustration tiles) must render at normalized, proportional scales.
- Eliminate tiny default thumbnails and mismatched bounding boxes so every visual comparison has balanced weight.

### Rule 4: Compact Attribute Chips & Multi-Line Flow

- Attribute chips must occupy minimal horizontal space, flowing compactly across multiple lines with clear group boundaries.
- Reclaim whitespace wasted by dimmed or padded rows.

### Rule 5: Context-Dependent Disqualification (Dynamic HUD)

- Mirror the logic of deeper-level question grids: **anything that contradicts the user's vote or current context is automatically disqualified and hidden.**
- Elements appear and disappear contextually based on active selection state, reducing cognitive load and visual noise.

### Rule 6: Universal MTGAC Artist Attribution

- The MTGAC artist disclosure link (`ArtistSupportLink`) must render consistently and cleanly under **both** illustration renders and Scryfall card renders.

---

## 3. Implementation Roadmap

| Item        | Focus Area                                                | Status |
| ----------- | --------------------------------------------------------- | ------ |
| **#711**    | Uniform button sizing across all answer rows              | Queued |
| **#715**    | Root-cause single/double click event handling             | Queued |
| **#746**    | Normalized image bounding boxes & proportions             | Queued |
| **Chips**   | Compact multi-line attribute chip layout & spacing        | Queued |
| **Pruning** | Context-dependent attribute/candidate disqualification    | Queued |
| **MTGAC**   | Universal rendering under illustration & Scryfall renders | Queued |
