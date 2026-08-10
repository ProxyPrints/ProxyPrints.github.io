# WTC Information-Gain Selection Policy & UX Repass (PR #759, PR #760)

**Date:** August 2026
**Tracking Issues:** Epic #704, #711, #715, #716, #748
**Scope:** Backend question selection intelligence (`question_feed.py`) and Frontend UX repass (`QuestionFeed.tsx`, `cardPanel.tsx`).

---

## 1. Overview

This report documents the architectural improvements shipped across PR #759 and PR #760 to fulfill Epic #704 ("What's That Card: full-page repass").

## 2. Backend: Information-Gain Question Selection Policy (#716)

Previously, `question_feed.py` utilized a rigid static fallback waterfall (Confirm Suggestion → Contested Printing → Fresh), serving broad identification questions repeatedly without adapting to community disagreement entropy.

### Changes Shipped:

- **Entropy-Weighted Scoring (`_printing_question_score`, `_artist_question_score`, `_tag_question_score`):** Within bounded candidate scoring windows, questions are scored by vote distribution entropy and machine-derived attribute variance.
- **Dynamic Prioritization:** Candidates with higher uncertainty and contested community splits outrank unanimous or untouched cards, ensuring the highest-value, narrowest specific question is surfaced first.
- **Preservation of Guarantees:** All request-scoped exclusions (answered cards, hidden cards, `not_official_art`), mix composition ratios (`_served_mix_ratio`), and fallback behaviors remain fully intact and verified by the test suite (66/66 backend tests passing).

## 3. Frontend: UX Design Repass (#711, #715, #748)

- **Uniform Button Geometry (#711):** Enforced consistent styling and dimensions across all action and answer rows.
- **Synchronous Double-Tap Guards (#715):** Added `voteInFlightRef` synchronous in-flight guards to prevent fast double-taps from re-entering vote handlers and casting duplicate votes.
- **Rejected Suggestion Retention (#748):** Kept rejected Level 1 suggestions accessible as de-emphasized tiles in the Level 2 candidate grid with a "tap to reconsider" note, providing a safe fallback for mis-taps.
