# Cumulative learning validation

This record covers the accepted [agent-led learning plan](plans/agent-led-learning-plan.md). Native evaluations use GPT 5.6 Luna through OpenRouter on the Windows edge, with **explicitly simulated staff decisions**. DemoBooks is synthetic. Its application API is disabled; the harness uses the independent Windows desktop controller. Regression and admission tests use simulated models and application fixtures.

**The accepted prototype milestone is complete.** The final suite passed **214 tests in 422.08 seconds**, with one upstream deprecation warning. Clean server-only and harness-only installations passed. The published learning view rendered on desktop and mobile without JavaScript errors or horizontal overflow.

The [evidence artifact](evidence/cumulative-learning.json) retains **22 live runs: 16 verified outcomes and 6 failed or partial development attempts**, including two original reporting teaching/reuse records. This is the complete recorded development sequence, not a claim of a 100% model success rate. All recorded executed attempts had staff decisions; some actions remain unassessed.

## Teaching, reuse and rollback

| Case | Approvals | Model calls | Staff corrections | Recoveries |
| --- | ---: | ---: | ---: | ---: |
| Original reporting teaching; new skill | 5 | 5 | 0 | 0 |
| Reporting revision adds isolated classification | 6 | 7 | 0 | 0 |
| Final reporting revision reuse | 8 | 4 | 0 | 0 |
| Earlier arithmetic-only request; classification workflow declined | 5 | 5 | 0 | 0 |
| Correction teaching with renamed field and corrected amount | 14 | 6 | 1 | 1 |
| Correction reuse after restart, different record | 9 | 2 | 0 | 0 |
| Second correction teaching: classification/report plus verified draft | 17 | 6 | 0 | 0 |
| Combined learned correction on held-out record | 11 | 4 | 0 | 0 |
| Combined correction on earlier layout | 11 | 4 | 0 | 0 |
| Earlier correction version reused after rollback | 9 | 3 | 0 | 0 |
| Earlier reporting version reused after rollback | 7 | 3 | 0 | 0 |
| Guidance-only teaching from observed invoice total | 6 | 6 | 0 | 0 |
| Guidance-only reuse after restart on another record | 5 | 5 | 0 | 0 |

Reporting progressed from `4a6377eaa942` to `94cc0c2f6338`. Correction progressed from the seeded `dc1e65c0fcfb` to learned `686b88f94b28`, then accepted `684b1a09af9a`. The intermediate `eeabc62c0511` remains historical: its application effects were correct but its final narrative was not, and overall acceptance was revoked. The active guidance package is `f31effa043ff`, with no graph steps. Full hashes, teaching evidence, candidate diffs and check results are in the artifact.

Both older workflow versions completed new requests after rollback. The newer accepted versions were then restored. Six prior runs retained their original pinned versions across these changes. Correction and guidance reuse include recorded Windows process restarts; the reporting sequence also spans worker restarts and fresh conversations. Current application observations verified every reported amount and saved draft used for acceptance.

Counts are descriptive. Coordinator revisions changed during development, so this is not a controlled estimate of improvement caused solely by learning. The combined correction graph does demonstrate reuse of the shared validation/comparison operations: the teaching request used two workflows, and the derived package performs their combined work in one approved workflow with one Save.

## What is exercised

- A reporting procedure absent from the seeded catalog is derived from accepted operations, admitted independently, and reused across conversations and worker restarts.
- A second reporting revision adds an isolated judgment while retaining its arithmetic checks.
- A correction procedure learns an observed field label and a staff-corrected value representation, then adds classification/reporting before one verified draft save.
- Workflow completion returns to the agent so one request can use multiple procedures. A consolidated package preserves the approved operations and verifies at its end.
- Exact versions, dependencies, approval decisions, scoped judgment inputs, observations, corrections, failures and rollback are retained.
- Negative feedback triggers a bounded live maintenance review. Suggestions do not execute work, change permissions or activate a procedure from failed evidence.
- Guidance-only learning uses existing tools. Supporting text has a separate approved read; contract-only admission is explicitly distinguished from behavioral evaluation.

## Verification method

The [native evaluation driver](../tools/enterprise_dev/longitudinal_demo.py) creates a separate developer evaluation conversation for each case. It approves only the selected task family's effects, corrects proposed draft fields against the verified comparison when needed, and records these decisions as simulated. A report must match the native observed invoice and purchase-order totals and signed difference. A correction must show one unique saved draft with the requested record, purchase-order amount and request reference. A guidance answer must match the observed amount.

Later runs also check numerical claims in the final answer against that evidence. This is a bounded consistency check, not a general semantic correctness oracle. Application success and a correct final narrative are recorded separately when they disagree. Outcome acceptance occurs only after the driver's checks pass. Selected finished operations receive explicit simulated assessments; remaining operations stay labeled unassessed.

Held-out checks use `--no-learn`, so evaluation cases do not become teaching evidence. Each case uses a new name; the driver refuses to overwrite previous results. Summaries include model/prompt bindings, immutable skill versions, independent observations, approval coverage, corrections, recoveries, repeated mistakes, model calls/tokens and elapsed/waiting time. Raw local records remain under `runtime/agent-led-evaluation/longitudinal/`.

## Failures retained during development

The live sequence exposed and preserved several failures:

1. A model tried to select an already bound developer-fixture record. Execution denied it. Bound requests now omit the selection tool.
2. The model proposed integer cents as the text of a dollars field. The runtime blocked the mismatch before Save. A later simulated staff correction supplied the verified value; the learner retained the observed field handling.
3. A reporting sub-workflow prematurely finished a request that also required a correction. The coordinator no longer treats child completion as request completion or substitutes a fixed final answer. A regression exercises two child workflows and exactly one save.
4. After correct application execution, a model narrative misstated the totals. Overall acceptance was revoked and the active version was rolled back for the evaluation. Workflow returns and current context now disclose the verified totals and their units. The contradictory narrative remains evidence; it is not counted as a fully correct outcome.
5. Two model proposals mistyped long version hashes. Exact-version enforcement denied them. Model-facing tools now select a skill by ID; the runtime binds the full active or previously approved version before approval and retains it across retries. It does not accept a fuzzy hash match or silently change an approved version.

These failures matter: passing application checks is insufficient evidence that every explanation is correct. They also show why the learning process retains failures and why automatic package admission does not grant autonomous business execution.

## Scope

The accepted milestone is a bounded prototype mechanism, not measured enterprise reliability. The application adapter remains specific to DemoBooks, the executable vocabulary is installed by developers, and generated packages cannot execute arbitrary Python. Guidance checks cannot prove natural-language correctness. Staff approval, explicit outcome acceptance, history, suspension and rollback remain necessary. Model changes are recorded without an automatic historical replay campaign.
