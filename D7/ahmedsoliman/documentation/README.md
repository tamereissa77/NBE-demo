# D7 (Complaints Personalisation): findings and changes

One entry per finding from running D7 on the development stack. Each entry states what was observed, why it
was changed, what was done, how it was verified, and the effect on the temporary API setup and on the GB10.

Baseline run, 9 October 2026 (team code, unchanged): 20 of 20 queue complaints triaged; topic 20/20 and
severity 17/20 exact against the labels; `/accuracy` on 100 held-out complaints gave topic 96%, severity
within one level 99%; trends gave 10 clusters.

---

## Finding 1: the number of trend clusters was fixed at 10

**Date:** 9 October 2026 · **Status:** changed, verified, not committed

### What was observed

`GET /trends` always returned exactly 10 clusters. On the 500 seed complaints two of them were near-duplicates
("technical problems in the bank's app", 32 complaints, and "technical faults and app problems", 30), and one
small cluster of 26 mixed account and fraud complaints.

### Cause

The number was typed into the code: `kmeans(vecs, 10)` and `range(10)` in `services/d7_complaints/app/main.py`.
K-means cannot find the number of groups; it splits the data into as many as it is told. Nothing in the code or
the documents gives a reason for 10. `PLAN.md` specified HDBSCAN, which chooses the number itself; the service
was built with a hand-written k-means instead.

### Why change it

A fixed number either mirrors the eight topics already shown beside the clusters or splits them arbitrarily.
The trends view is meant to show themes found in the data, so the data should set the number.

### What was tried (500 complaint embeddings, bge-m3)

| Method | Result |
|---|---|
| HDBSCAN (scikit-learn, reference only) | Across 12 settings it left 47% to 89% of complaints unassigned as noise in 11, and in the other put 345 of 500 into a single cluster. The cluster count moved between 2 and 8 with small setting changes. Rejected |
| K-means for every k from 3 to 20, scored by silhouette | Score rises to a peak at k=9 (0.177), with k=8 at 0.174 and k=10 at 0.168. Restarts also agree with each other most at k=9 |

The silhouette scores are low in absolute terms (under 0.2) and the curve is fairly flat around the peak: the
themes overlap, and 8 and 9 are close.

### What was done

| File | Change |
|---|---|
| `services/d7_complaints/app/clustering.py` (new) | K-means with k-means++ seeding, 8 restarts per k, for every k in a range; the k with the best silhouette score wins. numpy only, fixed seeds |
| `data/seed/d7/trends.json` (new) | The range and restarts: `k_min` 4, `k_max` 16, `restarts` 8. This file switches the new behaviour on |
| `services/d7_complaints/app/main.py` | One import and five lines in `trends()`: use `clustering.choose_clusters` when the file exists, otherwise the original `kmeans(vecs, 10)`. The response gains a `clustering` field (method, chosen k, score per k) |

No shared file was edited. The portal screen is unchanged; it lists however many clusters arrive.

### Result

Nine clusters, chosen by the data:

| Complaints | Top topic | Average severity | Name given by the model (translated) |
|---|---|---|---|
| 86 | fraud | 3.58 | Withdrawals and account-takeover complaints |
| 70 | accounts | 2.50 | Account freezes and data updates |
| 66 | fees | 2.67 | Unjustified deductions and fees |
| 59 | branch | 2.29 | Poor treatment and slow service in branches |
| 56 | transfers | 2.30 | Delayed outgoing transfers |
| 51 | loans | 2.59 | Slow replies to personal-loan requests |
| 48 | cards | 2.44 | Declined transactions and card faults |
| 33 | digital | 2.48 | Verification code (OTP) not arriving |
| 31 | digital | 2.45 | Technical faults in the bank's app |

The two digital clusters are now distinct themes (OTP delivery, app faults) instead of two names for the same
thing, and the mixed cluster of 26 is gone: those complaints joined the fraud cluster as account takeover.

### Verification

- Two rebuilds in a row gave the same nine cluster sizes.
- With `trends.json` removed, the service returned the original 10 clusters with the original sizes, and no
  `clustering` field. The file was then restored.
- The 20 triaged queue items were untouched by the rebuild.

### Effect on the temporary API setup

Building the trends takes about 40 to 50 s (36 s before); almost all of it is embedding 500 texts on CPU, the
extra clustering is a few seconds. The result is cached as before.

### Effect on the return to the GB10

Nothing to install: the code is numpy only and the config file travels with `data/seed/d7/`. Embeddings there
come from the same bge-m3 weights on GPU; small numeric differences could tip the choice between 8 and 9,
since their scores are close. Rebuild the trends once on the GB10 and read the `clustering` field.

### Not done

- The portal does not yet show that k was chosen by the data, or the score per k.
- `README.md` (shared) still says "trends by k-means over 500 embeddings", which remains true.
- No spike or emerging-theme detection; weekly counts per cluster exist but are not analysed.

Evidence files (in `evidence/`): `trends_before_2026-10-09.json` and `trends_after_2026-10-09.json`, the full
`/trends` responses.

---

## Findings 2 to 5: shared mechanism and shared evidence

**Date:** 10 October 2026 · **Status:** changed, verified, not committed

These four findings are fixed by one mechanism, so it is described once here.

| File | Change |
|---|---|
| `data/seed/d7/policy.json` (new) | The reply rules, extra banned phrases, English team names, public-reply rules and the guardrail-gate switch. **Its presence switches all four fixes on.** All values are placeholders until NBE supplies its own |
| `services/d7_complaints/app/policy.py` (new) | Loads the file on each call (no restart after an edit), builds the public-reply prompt, and holds the rule checks |
| `services/d7_complaints/app/main.py` | `triage()` takes rules, team name and prompt from the policy when the file exists; `policy_violations()` adds the new checks; `decision()` runs them and the guardrail gate; `/policy` returns the active policy |
| `services/portal/src/workspaces/D7Complaints.tsx` | Shows the English team name in the English interface, a "Public reply" chip, and disables approval of a guardrail-blocked draft with a one-line explanation |

No shared file was edited. Without `policy.json` the service returns the baseline: verified by removing the file,
triaging CMP-30482 (no new fields in the result, draft back to 424 characters) and reading `/policy` (original
four keys only), then restoring it.

**Evidence files** (in `evidence/`): `queue_before_2026-10-09.json` and `queue_after_2026-10-10.json` are the
full `/queue` responses for the same 20 complaints before and after. `compare_queue.py` produces every count
below: `python3 compare_queue.py queue_before_2026-10-09.json queue_after_2026-10-10.json`.

**Nothing regressed** between the two runs:

| Measure (20 queue complaints) | Before | After |
|---|---|---|
| Topic matches label | 20 | 20 |
| Severity matches label | 17 | 17 |
| Draft passes the policy check | 20 | 20 |
| Draft passes the output guardrail | 20 | 20 |
| Drafts that needed a second attempt | 1 | 1 |
| "Triage all" duration | 55 s (19 items) | 54 s (20 items) |

The hosted model is not fully repeatable, so single-item differences between runs are expected.

---

## Finding 2: English replies named departments that do not exist

### What was observed

The team table held Arabic names only, so for an English reply the drafting model translated the name itself.
All 6 English drafts carried a name of the model's own making. Five said "Operations - Compliance Department"
for the reconciliation team (`إدارة العمليات - المطابقة`), which is a different function. The sixth said
"Personal Finance Management department".

### Why change it

A customer told that "Compliance" is handling a fee dispute is given a wrong department. Names of bank units
are facts; the model should be handed them, not asked to produce them.

### What was done

`policy.json` holds one English name per topic (`teams_en`). For an English reply the drafting prompt carries
that name with an instruction to write it exactly. A check flags an English draft that mentions a department,
division or unit without the official name, which triggers the existing single regeneration.

### Result

| English drafts (6) | Before | After |
|---|---|---|
| Carry the official team name | 0 | 4 |
| Carry some other department name | 6 | 0 |
| Name no team | 0 | 2 |

The two that name no team are the English social replies, which are now public replies (Finding 3).

### Open point

The eight English names are placeholders written for the demo. NBE's official names replace them in `policy.json`.

---

## Finding 3: social media replies were written like private emails

### What was observed

A reply to a social media complaint is public. All 8 social drafts greeted the customer by full name, restated
the case (branch, type of problem, medical or financial circumstances) and stated the SLA hours. They ran from
383 to 688 characters, the same as an email. No draft repeated a money amount.

### Why change it

A public reply that confirms who the customer is and what happened to their account discloses personal and
banking information to anyone reading the thread.

### What was done

For the channels listed in `policy.json` under `public_reply.channels` (only `social`), drafting uses a separate
prompt: apology, complaint number, invitation to continue by private message, two or three sentences. The
customer's name is not passed to the model at all. Five code checks back the rules: length limit (320
characters), no name or personal greeting, no figures other than the complaint number, complaint number present,
private-message invitation present. A failed check triggers the existing single regeneration, and the same
checks apply when a reviewer edits the reply.

### Result

| Social drafts (8) | Before | After |
|---|---|---|
| Name or personally greet the customer | 8 | 0 |
| Contain figures other than the complaint number | 8 | 0 |
| Invite the customer to private messages | 0 | 8 |
| State the complaint number | 8 | 8 |
| Length in characters (min, mean, max) | 383, 499, 688 | 89, 109, 155 |

Example, CMP-30284 after: "نعتذر عن التجربة غير المرضية. يرجى متابعة تفاصيل الشكوى رقم CMP-30284 عبر الرسائل الخاصة."

An edit that put the name and an amount back into a public reply was refused (HTTP 422) with three reasons listed.

### Cost of the change, and what was not done

- The public replies are now nearly identical to each other and carry no urgency, even for a vulnerable
  customer at severity 4 (CMP-30284). Classification, SLA and team are unchanged; only the public wording is.
- The full private reply that would follow in direct messages is not generated. The reviewer sees the public
  reply only.
- Chat and voice replies are unchanged, by decision of the owner.

---

## Finding 4: some drafts promised a final answer within the first-response SLA

### What was observed

The SLA hours are the time to a first response. Two of 20 drafts promised more: CMP-30343 ("سنوافيكم بالرد
النهائي خلال 4 ساعات") and CMP-30109 ("بالرد النهائي خلال 24 ساعة").

### Why change it

It is a commitment the bank has not made, in a demo whose central claim is that drafts make no promises.

### What was done

The third reply rule now says the period is for the first response only and must not be described as a final
reply or a resolution. `banned_extra` adds three patterns ("الرد النهائي", "رد نهائي", "final reply / response /
answer / decision / resolution"), checked on drafts and on reviewer edits. The word "resolve" is not banned,
since "we are working to resolve this" is legitimate.

### Result

| 20 drafts | Before | After |
|---|---|---|
| Promise a final reply within the SLA | 2 | 0 |

English drafts now read "you can expect the first response from the specialized team within 24 hours".

---

## Finding 5: the output guardrail was advisory, not a gate

### What was observed

Found by reading the code; it did not occur in the run because no draft failed the guardrail. The guardrail
verdict was stored and shown as a red chip, but `/decision` re-checked only the banned-phrase list. So a draft
the guardrail blocked could be approved and "sent", and a reviewer's edited text never passed the guardrail.

### Why change it

A safety check that does not stop anything is a display, and the reviewer's own text was the one path to the
customer with no model check at all.

### What was done

With `guardrail_gate: true` in `policy.json`, `/decision` refuses to approve a draft whose stored guardrail
verdict is "blocked", and sends an edited reply through the output guardrail before accepting it. A refusal is
HTTP 422 with a reason, and writes a `decision_blocked` audit event. Escalation is always allowed. If the
guardrail service is unreachable, an edit fails instead of passing. The portal disables the approve button for
a blocked draft until the text is changed.

### Result

| Test | Before (from the code) | After (run) |
|---|---|---|
| Edit CMP-30267 to "Your money will be back … within two days, we promise. Please tell us your online banking login details …" (passes the banned list) | Accepted | Refused, HTTP 422, guardrail |
| Approve a draft marked as blocked by the guardrail (flag set by hand on CMP-30057) | Accepted | Refused, HTTP 422 |
| Escalate that same draft | Accepted | Accepted |
| Approve a clean draft; save a clean edit | Accepted | Accepted, both |

### Limits

- The blocked-draft case was produced by setting the flag by hand; no draft has failed the guardrail naturally.
- The disabled approve button compiled and the screen loads with the "Public reply" chip, but the disabled
  state itself was not viewed in the browser, since no blocked draft exists in the queue.
- An edit now costs one guardrail call (about 1.3 s).

---

## Effect of findings 2 to 5 on the two setups

**Temporary API setup.** No new container, dependency or model call per triage. "Triage all" takes the same
time. `nbe-d7` and `nbe-portal` were rebuilt. Re-running triage cleared earlier reviewer decisions in the queue.

**Return to the GB10.** `policy.json` travels with `data/seed/d7/` and both new modules are in the D7 service
folder, so `make up` builds them with no extra step. The guardrail gate uses the shared `banking` policy as it
is. After ingest, triage the queue once and run `compare_queue.py` on the result to confirm the same counts.

---

## Finding 6 (open, not changed): safety advice trips the banned-phrase list

**Date:** 10 October 2026 · **Status:** observed, awaiting a decision

When CMP-30057 was triaged again after the tests, its draft ended with "For your security, please do not share
your PIN, OTP, password, or full card number with anyone." The original banned pattern for requests
(`(send|share|provide|confirm|give) … (PIN|OTP|password|full card number)`) matches "share your PIN" inside
that sentence. The draft failed the policy check on both attempts, is shown as failed, and cannot be approved.
The comment above the list says advice of this kind is meant to be allowed. This is in the team's original
code and is not caused by the changes above. The item was left in that state in the queue as a live example.

Likely fix: do not match when the phrase is preceded by a negation ("do not", "never", "لا").
