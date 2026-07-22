> Durable copy of the owner-ratified 2026-07-22 vote-weight scenario
> matrix, sourced verbatim from `/home/ubuntu/.claude/jobs/1901e529/tmp/vote-weight-matrix.md`
> (Tron-authored review artifact; implemented in PR #325). This is the
> raw decision record — for the narrative/formal-model view of what it
> changed and why, see [`../theory.md`](../theory.md)'s §4 (soundness
> mechanisms) and §7a (`g₅`), and [`../identification-pipeline.md`](../identification-pipeline.md)'s
> human-backed-gate paragraph. Reference only; not re-derived or updated
> after ratification — it is a point-in-time record of the ruling, not a
> living spec.

# Vote-weight scenario matrix — Tron, 2026-07-22, master @ 574d6e65

Status: OWNER-RATIFIED 2026-07-22 — all decision cells ruled per recommendation
(D1 no machine tipping of human contests; D2 promotion stays; D3 see scope note
below; D4 machine dissent never de-resolves; D5/S3 implicit = low-weight+cap
w=0.25 cap=1.0; D6 suggestedness excludes implicit; D7 supersede-per-identity
lifecycle; DF FEDERATED pinned at 1.0). Implemented in PR #325.

D3 SCOPE NOTE (owner-ratified 2026-07-22, second ruling): D3's final scope is
"no CONTESTED escalation," NOT "no queue entry." Machine-only dissent never
marks a pair CONTESTED, but the pair remains in the normal review queue as
UNRESOLVED — the question feed's supply of machine-suggested pairs for human
voting depends on exactly those entries. Sark's #325 implementation is the
ratified behavior.

```
TASK: Vote-weight scenario matrix for the shared consensus resolver
  (resolve_weighted_consensus). Repo ProxyPrints.github.io @ master
  574d6e65. Executable spec for owner ratification -> parameterized
  backend tests -> federation weight-semantics reference. No code
  changed; read-only review.

=== GROUND TRUTH (verified) ==========
Gate  MPCAutofill/cardpicker/vote_consensus.py:143
  winner.weight >= min_weight  AND  share >= min_share
  AND  winner.has_human_backed   (share = winner.weight/total_weight,
  :139-141; winner selected by max GROUP WEIGHT, :140).
Privileged sub-gate :144-145: if require_privileged and winner lacks an
  in-group privileged vote -> PENDING_PRIVILEGED (not the key).
Weights _SOURCE_WEIGHTS vote_consensus.py:15-21 resolved from settings:
  USER=1.0 (:16) ; ADMIN=5.0 (:17, PRINTING_TAG_ADMIN_WEIGHT
  settings.py:67) ; DEDUCTION=OCR=0.5 (:18-19, PRINTING_TAG_MACHINE_WEIGHT
  settings.py:70-72) ; FEDERATED=1.0 (:20, VOTE_FEDERATED_WEIGHT
  settings.py:80).
  *** DISCREPANCY vs brief: brief said FEDERATED=MACHINE_WEIGHT (0.5).
  Code default is 1.0 (settings.py:80). A federated vote is as heavy as
  a local USER toward quorum/share, only stopped by the human-backed
  gate. Every FEDERATED row below uses 1.0; if the owner intended 0.5
  that is itself DECISION F. ***
Human-backed set vote_consensus.py:38 = {DEDUCTION,OCR,FEDERATED};
  is_human_backed_source :41-42. FEDERATED is NOT human-backed despite
  weight 1.0.
Privileged uplift moderation.py:47-58: privileged vote weight =
  max(base, VOTE_PRIVILEGED_WEIGHT=5.0, settings.py:76).
Thresholds settings.py:65-66: min_weight=PRINTING_TAG_MIN_VOTES=2 ;
  min_share=PRINTING_TAG_MIN_SHARE=0.6. Same values on BOTH paths
  (printing_consensus.py:93-94 ; tag_consensus.py:69-70,235-236).
Path divergence:
  - PRINTING (printing_consensus.py:88-94) uses RAW _SOURCE_WEIGHTS
    [vote.source]; NO privileged uplift, NO require_privileged EVER.
  - TAG (tag_consensus.py:56-72) uses privileged_weight() (uplift) AND
    require_privileged=True for SENSITIVE tags (:71).
VoteSource models.py:643-647 = USER/ADMIN/DEDUCTION/OCR/FEDERATED.
  *** IMPLICIT DOES NOT EXIST. Any implicit row's "current code" column
  is N/A: _SOURCE_WEIGHTS[IMPLICIT] raises KeyError; the source cannot
  be constructed. ***
VotePolarity models.py:870-871: APPLY=1, NOT_APPLICABLE=-1.
Persisted-status divergence:
  - Printing (models.py:347-349): UNRESOLVED / RESOLVED / NO_MATCH.
    There is NO persisted CONTESTED for printing; resolver None -> always
    UNRESOLVED (resolve_and_persist_printing printing_consensus.py:139-152).
  - Tag (models.py:373-380): RESOLVED_APPLY / RESOLVED_REJECT /
    CONTESTED / UNRESOLVED / PENDING_APPROVAL. None splits CONTESTED
    (both polarities present) vs UNRESOLVED (one side) at
    tag_consensus.py:138.
De-resolution is real: resolve_and_persist re-runs from CURRENT votes
  with no hysteresis; None overwrites a prior RESOLVED to UNRESOLVED
  (printing_consensus.py:139-152; tag_consensus.py:123-141).

=== OUTCOME VOCABULARY ==============================================
APPLY = resolver returns winning key -> RESOLVED / RESOLVED_APPLY.
REJECT = winner is NO_MATCH / NOT_APPLICABLE -> NO_MATCH / RESOLVED_REJECT.
CONTEST = None + both outcomes present (tag persists CONTESTED; printing
  persists UNRESOLVED).  UNRES = None + one side / all-gate-fail.
PEND = PENDING_PRIVILEGED (sensitive tags only).
SYMMETRY NOTE: every APPLY row has an exact REJECT mirror obtained by
  relabelling the winning outcome as NO_MATCH / NOT_APPLICABLE; the
  math is outcome-agnostic (:131-141). REJECT twins are NOT duplicated
  below. Tie/dissent rows are self-mirrored.

=== IMPLICIT CANDIDATE FORMS (both under evaluation) ================
SHARE-ONLY: implicit contributes W_si to the SHARE weights only, 0 to
  QUORUM weight; is_human_backed=False, is_privileged=False. Requires
  TWO per-group accumulators (quorum_weight, share_weight). Open sub-
  parameters -> DECISIONS S1-S3 below.
LOW-WEIGHT+CAP: implicit weight w_lc each (illustrated w_lc=0.25),
  counts toward BOTH quorum and share, but per-(card,tag) implicit sum
  hard-capped at C < min_weight (illustrated C=1.5); is_human_backed
  =False. Below uses W_si=1.0, w_lc=0.25, C=1.5 for concreteness; the
  magnitudes are DECISIONS, not settled.

=== TABLE A: NON-IMPLICIT BASELINE (current code == intended) =======
(these validate the resolver + Stage D arithmetic; no implicit involved,
 so current==share-only==cap. Binding gate is the FIRST failing clause.)
# | votes in group                    | weight math      | share | outcome | binding gate
A1| 1 USER                            | 1.0              | 1.00  | UNRES   | min_weight (1<2)
A2| 2 USER same                       | 2.0              | 1.00  | APPLY   | all pass
A3| 3 USER same                       | 3.0              | 1.00  | APPLY   | all pass
A4| 1 ADMIN                           | 5.0              | 1.00  | APPLY   | admin override (5>=2)
A5| 1 ADMIN(A) vs 1 USER(B)           | 5 vs 1           | 0.83  | APPLY(A)| admin overrides dissent
A6| 1 USER(A) vs 1 USER(B)            | 1 vs 1           | 0.50  | CONTEST | min_weight & share both fail
A7| 2 USER(A) vs 1 USER(B)            | 2 vs 1           | 0.67  | APPLY(A)| all pass; dissent overridden
A8| 3 USER(A) vs 2 USER(B)            | 3 vs 2           | 0.60  | APPLY(A)| BOUNDARY: share==0.6 resolves (>=)
A9| 2 USER(A) vs 2 USER(B)            | 2 vs 2           | 0.50  | CONTEST | share (0.5<0.6); weight passes
A10|2 DEDUCTION same                  | 1.0              | 1.00  | UNRES   | min_weight(1<2) & human-backed
A11|100 DEDUCTION same                | 50.0             | 1.00  | UNRES   | human-backed (VOLUME NEVER WINS)
A12|4 DEDUCTION + 1 USER same         | 2.0+1.0=3.0      | 1.00  | APPLY   | all pass -> DECISION D1
A13|1 USER(A) vs 4 DEDUCTION(B)       | 1 vs 2.0         | .67(B)| UNRES   | human-backed on winner B fails
A14|(1USER+4DED)(A) vs 1 USER(B)      | 3.0 vs 1         | 0.75  | APPLY(A)| machine tips human contest -> D1
A19|1 FEDERATED                       | 1.0              | 1.00  | UNRES   | min_weight & human-backed
A20|2 FEDERATED same                  | 2.0              | 1.00  | UNRES   | human-backed (weight 2 clears!)-> DF
A21|1 FEDERATED + 1 USER same         | 2.0              | 1.00  | APPLY   | fed weight=USER weight -> DF

=== TABLE B: STAGE D (deduction pooling over ~23k+ existing votes) ==
(pre-validates the pass arithmetic; DECISION cells are the ones that
 CHANGE an existing human resolution.)
# | prior state -> add                        | after math          | outcome    | flag
B1| RESOLVED(2 USER,A) + add 3 DED agree(A)   | A=2+1.5=3.5, s=1.0  | APPLY(unch)| safe
B2| UNRES(1 USER,A) + add 3 DED agree(A)      | A=1+1.5=2.5, s=1.0  | APPLY(new!)| D2 (promotion)
B3| (1 USER,A) + 3 DED dissent(B)             | A=1 vs B=1.5, sB=.6 | UNRES      | B has no human; also floods
  |                                           |                     |            | CONTEST queue (tag path) -> D3
B4| RESOLVED(2 USER,A) + 3 DED dissent(B)     | A=2 s=2/3.5=.571    | UNRES(!!)  | D4 DE-RESOLUTION: 3 machine
  |                                           | B=1.5 sB=.429       |            | dissents drag human share <0.6
B5| RESOLVED(2 USER,A) + 1 DED dissent(B)     | A=2 s=2/2.5=0.80    | APPLY(unch)| threshold: de-res needs >1.33
  |                                           |                     |            | DED weight (>=3 DED votes)
B4 detail: with 23k+ DED votes landing, B4 is reachable at scale on any
  thin-margin 2-USER card. Printing path silently reverts RESOLVED->
  UNRESOLVED (no CONTESTED status exists to signal it). This is the
  single highest-impact Stage D arithmetic fact.

=== TABLE C: IMPLICIT (proposed; current code = N/A KeyError) =======
(W_si=1.0 share-only, w_lc=0.25/cap C=1.5. Column split shows exactly
 where the two forms DIVERGE = the owner's choice.)
# | votes in group                 | SHARE-ONLY outcome        | LOW-WT+CAP outcome | flag
C1| 10 IMPLICIT only, same         | UNRES (quorum 0; !human)  | UNRES (cap1.5<2;   | invariant holds
  |                                |                           | !human)            | BOTH forms
C2| 2 USER + 5 IMPLICIT same(A)    | APPLY (quorum A=2, s=1)   | APPLY (A=2+1.5=3.5)| already-resolved,
  |                                |                           |                    | no change
C3| 2 USER(A) vs 2 USER(B),        | APPLY(A) IF winner picked | CONTEST (A=2.75    | *** D-CORE ***
  | +3 IMPLICIT on A               | by share-wt: sA=5/7=.714  | s=2.75/4.75=.579   | share-only lets
  |                                | (implicit BREAKS human    | <0.6)              | implicit decide a
  |                                | tie); nondeterministic if |                    | real 2v2 human tie;
  |                                | picked by quorum-wt (2=2) |                    | cap form does not
C4| 2 USER(A) win, 3 IMPLICIT      | UNRES: sA=2/(2+3)=0.40    | APPLY(A): B capped | *** D-CORE ***
  | dissent(B)                     | <0.6 (implicit VETOES a   | 0.75, sA=2/2.75=   | share-only implicit
  |                                | valid human resolution    | 0.727 -> resolves  | can DENY quorum-
  |                                | despite 0 quorum weight)  |                    | valid human win;
  |                                |                           |                    | cap form can't
C5| (2USER+impl)(A) vs (1USER      | net of C3/C4 on each side | net of C3/C4       | symmetric combo;
  | +impl)(B)                      | (see note)                | (see note)         | not tabulated
C4 asymmetry: under share-only, implicit contributes 0 to QUORUM (can't
  help a side reach min_weight) but full W_si to SHARE DENOMINATOR (can
  push any winner's share <0.6). Net effect: implicit is a one-way VETO,
  never a promoter. Whether that asymmetry is desired is DECISION S2/D5.

=== TABLE D: TAG-SPECIFIC DIVERGENCES (only where semantics differ) =
# | scenario                                  | printing path      | tag path                | note
T1| SENSITIVE tag, crowd APPLY, no priv vote  | (no such gate)     | PEND (PENDING_APPROVAL) | tag only :71,:144
T2| SENSITIVE tag, moderator votes AGAINST    | (n/a)              | priv vote is in LOSING  | :119 in-group co-sign
  | crowd                                     |                    | group -> still PEND     |
T3| moderator vote (privileged uplift)        | NOT applied        | weight max(base,5)      | printing:90 vs mod:47-58
  |                                           | (printing:90 raw)  |                         |
T4| get_tag_net_polarity confidence fill      | (no analogue)      | base _SOURCE_WEIGHTS,   | :186-192; NO privileged
  |                                           |                    | NO gate, NO implicit    | uplift, NO min_share;
  |                                           |                    | awareness               | implicit would color
  |                                           |                    |                         | chip -> D6 (cond 6)
T5| resolver None                             | UNRESOLVED always  | CONTESTED vs UNRESOLVED  | printing loses the
  |                                           |                    | by polarity count :138  | contested signal
Tag net-polarity (T4): if IMPLICIT is added to _SOURCE_WEIGHTS at all,
  get_tag_net_polarity (:189) will FOLD implicit weight into the chip
  fill unless explicitly excluded -- directly contradicting prior
  condition 6 ("suggestedness excludes implicit"). -> DECISION D6.

=== TABLE E: RETRACTION MID-CONTEST (re-run from current votes) =====
# | scenario                                  | outcome            | note
R1| RESOLVED(2 USER) - 1 USER retracts        | UNRES (1<2)        | no hysteresis; intended
R2| RESOLVED(1 ADMIN) - admin retracts        | UNRES (no votes)   | intended
R3| implicit vote on losing side (C4) persists| stays UNRES until  | implicit lifecycle: are
  | after filter chips change                  | implicit removed   | implicit votes retracted/
  |                                            |                    | TTL'd? -> DECISION D7

=== DECISION CELLS (owner must ratify; each answerable) =============
D1 (A12/A14) Should ONE human vote "unlock" an unbounded machine
   (DEDUCTION/OCR) pile so machine weight then counts fully toward
   quorum AND can tip a human-vs-human contest? Current code: YES.
   RECOMMEND: acceptable for A12 (agreement) but cap machine weight's
   contribution to quorum at < min_weight per side so machine can never
   be the deciding weight over a dissenting human (mirrors the implicit
   cap philosophy). Ratify explicitly before Stage D lands.
D2 (B2) Should a DEDUCTION pool PROMOTE a single-human UNRESOLVED card
   to RESOLVED? Current+intended: YES. RECOMMEND: YES (this is Stage D's
   purpose) but only where deduction AGREES with the lone human; couple
   with D4.
D3 (B3) DEDUCTION dissent against a lone human yields UNRES and, on the
   tag path, CONTESTED -- flooding the review queue at 23k scale.
   RECOMMEND: suppress CONTESTED status when the only opposing weight is
   machine-derived (dissent that can never win shouldn't enqueue humans).
D4 (B4) *** HIGH IMPACT *** Should DEDUCTION dissent be able to DE-
   RESOLVE a human-resolved card by dragging its share below 0.6 (>=3
   DED votes flips a 2-USER RESOLVED to UNRESOLVED, silently on the
   printing path)? Current code: YES. RECOMMEND: NO -- exclude machine-
   derived weight from the SHARE DENOMINATOR when a human-backed winner
   already clears quorum, OR require machine dissent to itself be human-
   co-signed before it can lower a human winner's share. Must be ruled
   BEFORE the Stage D pass runs.
D5 / D-CORE (C3,C4) Choose the IMPLICIT form. Share-only lets implicit
   BREAK a genuine 2v2 human tie (C3) and VETO a quorum-valid human win
   (C4); low-weight+cap does neither. RECOMMEND: low-weight+cap, OR
   share-only with implicit share-weight ALSO capped per-(card,tag) so
   it can neither reach nor deny 0.6 alone. Do not ship uncapped share-
   only.
S1 (share-only) Winner SELECTION metric: quorum_weight or share_weight?
   If quorum_weight, C3's two human groups tie (2==2) -> nondeterministic
   winner (:140 max is arbitrary on ties). RECOMMEND: select by
   quorum_weight, break ties as CONTEST (never let dict order decide).
S2 (share-only) Does implicit count in the winner's share NUMERATOR, or
   only the DENOMINATOR? Numerator-inclusion makes implicit a promoter
   (C3 resolves); denominator-only makes it a pure diluter/veto (C4).
   RECOMMEND: if share-only is chosen at all, denominator-only + capped
   (implicit never promotes, only bounded dilution).
S3 Magnitude of W_si / w_lc / cap C. RECOMMEND: C strictly < min_weight
   with margin (e.g. C=1.0 against min_weight=2) and per-(card,tag),
   matching prior condition 8.
D6 (T4) Must get_tag_net_polarity (tag_consensus.py:189) EXCLUDE
   implicit weight from the confidence-fill, per prior condition 6?
   Current code would include it the moment IMPLICIT enters
   _SOURCE_WEIGHTS. RECOMMEND: YES exclude -- and add a test asserting
   net polarity is invariant to implicit votes.
D7 (R3) Implicit vote lifecycle: persistent, retractable, or TTL'd?
   Under share-only a stale losing-side implicit vote permanently denies
   share (C4) until removed. RECOMMEND: implicit votes expire / are
   superseded per (anon-id, card, tag); define before implementation.
DF (A20/A21) FEDERATED weight = 1.0 (settings.py:80), not 0.5. A single
   federated vote is as heavy as a local USER toward quorum and share
   (only the human-backed gate stops a federated-only pile). Is 1.0
   intended, or should federated match machine 0.5? RECOMMEND: confirm
   1.0 explicitly, or lower to 0.5 to match its non-human-backed status;
   either way pin it in the federation spec.

=== TEST-SPEC (for Sark; mechanical transfer) ======================
Parameterize against resolve_weighted_consensus directly (path-agnostic
core). One case = a list of VoteTuple inputs -> expected sentinel.
Signature (matches vote_consensus.py:45-65,94-96):

  MIN_W, MIN_S = 2, 0.6   # settings.py:65-66
  # VoteTuple(outcome_key, weight, is_human_backed, is_privileged=False)
  # weights: USER 1.0 / ADMIN 5.0 / DED,OCR 0.5 / FED 1.0  (:15-21)
  # human_backed: USER,ADMIN True ; DED,OCR,FED False        (:38)

  @pytest.mark.parametrize("case_id,votes,min_w,min_s,require_priv,expected", [
    ("A1",  [VT("X",1.0,True)],                                  2,0.6,False, None),
    ("A2",  [VT("X",1.0,True),VT("X",1.0,True)],                 2,0.6,False, "X"),
    ("A4",  [VT("X",5.0,True)],                                  2,0.6,False, "X"),
    ("A5",  [VT("X",5.0,True),VT("Y",1.0,True)],                 2,0.6,False, "X"),
    ("A8",  [VT("X",1.0,True)]*3+[VT("Y",1.0,True)]*2,           2,0.6,False, "X"),  # share==0.6
    ("A9",  [VT("X",1.0,True)]*2+[VT("Y",1.0,True)]*2,           2,0.6,False, None),
    ("A11", [VT("X",0.5,False)]*100,                             2,0.6,False, None), # human-backed
    ("A13", [VT("X",1.0,True),VT("Y",0.5,False),VT("Y",0.5,False),
             VT("Y",0.5,False),VT("Y",0.5,False)],               2,0.6,False, None),
    ("A20", [VT("X",1.0,False),VT("X",1.0,False)],               2,0.6,False, None), # FED weight2 gated
    ("B4",  [VT("X",1.0,True),VT("X",1.0,True),
             VT("Y",0.5,False),VT("Y",0.5,False),VT("Y",0.5,False)], 2,0.6,False, None), # de-res
    ("T1",  [VT(APPLY,1.0,True),VT(APPLY,1.0,True)],             2,0.6,True,  PENDING_PRIVILEGED),
    ("T1b", [VT(APPLY,1.0,True),VT(APPLY,1.0,True,True)],        2,0.6,True,  APPLY),
  ])
  def test_consensus(case_id,votes,min_w,min_s,require_priv,expected):
    assert resolve_weighted_consensus(votes,min_w,min_s,require_priv) is-or-== expected

IMPLICIT rows CANNOT be expressed against the current signature (no
implicit accumulator). They require the resolver's shape to grow a
second accumulator OR an is_implicit flag on VoteTuple. Provide Sark a
SEPARATE parametrization keyed to whichever form the owner picks (D5),
e.g. VT(outcome, quorum_wt, share_wt, human_backed) for share-only, or
VT + a per-group cap arg for cap form. Do NOT author implicit tests
until D5/S1-S3 are ruled -- their expected values are undefined today.
Wrapper-level tests (privileged uplift T3, tag CONTESTED-vs-UNRESOLVED
T5, net-polarity D6) go against tag_consensus/printing_consensus, not
the core, since those semantics live in the wrappers (:56-72, :138,
:186-192).

=== FEDERATION NOTE (peer consuming our verdicts must know) =========
1. human-backed is a FIRST-CLASS, EXPORTED bit, not derivable from
   source alone (vote_consensus.py:45-59 docstring is explicit): a
   federated vote's human-backed-ness is whatever the EXPORTING peer
   asserted. A peer importing our verdicts must carry our per-verdict
   human-backed flag, not re-infer it from "source==federated".
2. FEDERATED default weight is 1.0 and is_human_backed=False
   (settings.py:80, vote_consensus.py:38): incoming federated weight
   counts toward share/quorum but NEVER satisfies the human-backed gate
   alone -- the "suggestion" posture (docs/federation-v1.md
   FEDERATED_VOTE_GATE_MODE). A peer must not treat an imported
   federated verdict as human-backed. Resolve DF first.
3. Thresholds (min_weight=2, min_share=0.6) are LOCAL policy, not part
   of the verdict: a peer applies its OWN thresholds to imported vote
   tuples. Export raw weighted tuples + the human-backed/privileged
   bits, NOT our resolved key, if peers are to re-resolve under their
   own policy.
4. The privileged/PENDING_PRIVILEGED machinery is tag-path-only and
   SENSITIVE-only (tag_consensus.py:71); printing verdicts carry no
   privileged dimension. Federation export of printing verdicts must not
   claim a privileged field.
5. Whichever IMPLICIT form ships (D5) becomes an exported semantic: a
   peer must know whether an incoming "implicit" contribution affects
   quorum, share, or is capped -- otherwise cross-peer share arithmetic
   diverges. Pin the chosen form in docs/federation-v1.md before any
   importer exists.

VERIFICATION: all file:line claims read from working tree @ 574d6e65
(git log -1 confirmed HEAD). IMPLICIT absence confirmed (models.py:643-
647, grep). FEDERATED=1.0 confirmed settings.py:80 + vote_consensus.py:20.
Printing-path has-no-privileged confirmed printing_consensus.py:88-101.
All B-table arithmetic hand-computed against gate :143; recommend Sark
assert them as the regression floor before Stage D executes.
OPEN: D1-D7, S1-S3, DF are owner rulings, not review findings -- this
matrix is UNRESOLVED-pending-ratification by construction, which is its
purpose. No prod action authorized or implied by this document.
```
