```
TASK: Upstream-readiness audit — report-relay convention adopted +
standing status recap. Branches: `claude/upstream-readiness-audit-cvq14g`
(346e91a4), `upstream-feat-local-file-source` (93874645), `report-relay`
(this commit). No PR opened anywhere; nothing touches
`chilli-axe/mpc-autofill`.

WHAT SHIPPED:
1. Relayed the prior Phase-2 report verbatim to
   `docs/reports/2026-07-18-upstream-readiness.md` on `report-relay`
   (commit 75fc26d4), recovering the courier-lost delivery.
2. Adopted the report-relay convention for the rest of this session and
   added it to CLAUDE.md's "Reporting convention" section (commit
   64c7b04f, one sentence, as specified): reports commit verbatim to
   `docs/reports/<date>-<task>.md` on `report-relay`; chat carries only
   branch + path + one-line summary.
3. No new substantive audit/extraction work this turn — recapping
   standing state below since "proceed" had no new concrete instruction
   attached and everything queued is explicitly gated on an external
   answer (see Open items).

DEVIATIONS from spec: none. (Note for the record, not a deviation: I
initially pushed back on relaying reports without their bodies also
appearing in chat, since the "courier loss" framing didn't hold up
technically on its own. Proceeded once the actual mechanism — a
master/orchestrating session consuming `report-relay` rather than chat
scrollback — was explained; the full content is preserved in git either
way, so this isn't a transparency reduction, just a different reader.)

VERIFICATION: `git fetch origin report-relay
claude/upstream-readiness-audit-cvq14g upstream-feat-local-file-source
master` confirms all three branches are exactly where left them; no
other session has pushed conflicting commits to `report-relay` since the
last push. No code changes this turn to verify beyond the two doc
commits already pushed.

OPEN ITEMS / DECISIONS NEEDED (recap, unchanged from the last full
report):
1. Owner: before `upstream-feat-local-file-source` is actually sent,
   re-run its test suite against real Postgres+ES (8 of 15 test cases
   couldn't run in this sandbox — see the draft PR doc's "Extraction
   notes" for exactly which and why).
2. Owner: Card DOM API and the dead-image/error-states pairing
   (readiness-audit.md's Tier 1 #1, #4, #5) are queued next but
   explicitly gated on the maintainer's answer about dropping the
   Node.js frontend — no further Phase-2 branches will be cut until
   that answer lands, per the prior decision. Nothing for me to do here
   until then; flagging so "proceed" isn't read as license to skip that
   gate.

LIVE STATE: `report-relay` at commit (this one, appended after
64c7b04f). `claude/upstream-readiness-audit-cvq14g` at `346e91a4`,
`upstream-feat-local-file-source` at `93874645` — both unchanged, both
already pushed, both awaiting the owner. No PR open anywhere. Session
holding on the frontend-direction gate.
```
