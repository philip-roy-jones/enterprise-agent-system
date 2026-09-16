# Conversation learning and screenshots

> Current execution policy: [digital employees](plans/digital-employees.md) use shadowing / active / paused. Active work uses server authorization without per-operation staff approval. Historical Strict-policy descriptions below remain as background where noted.

Staff teach by chatting. The frontend no longer has an operation assessment form or an idle Live workspace card. The operation review panel appears when an approval is pending, retaining the exact proposed inputs and the ability to correct a click target.

## Conversation review

Each ended conversational request schedules one durable review, including guidance received while that request was active. The server deduplicates scheduling; the edge caches completed maintenance results for retry recovery. Reviews run while the worker is idle, in the existing isolated learner process. The server does not run a model. The foreground agent has no learning-reporting tool or instruction to flag conversations for review; ordinary replies and existing action receipts are sufficient input. Missing installed capabilities can become internal suggestions from the background review without a development-handoff announcement in chat.

The reviewer receives the new staff messages, bounded recent work from the same person and conversation, and up to six accessible skill packages. Organization, department, role, company and desktop boundaries are preserved. Package access still checks the source staff member's evidence audience.

The model can identify corrections, preferences, new information, reported problems, or ambiguous feedback. Each signal must quote an actual new staff message. A reference to an earlier operation must identify a finished operation in the supplied history. Ambiguity remains explicit; the reviewer cannot invent an operation connection. Routine chat can produce no change.

Clear reusable teaching can produce an instructions-only skill or revise an existing skill's instructions and text resources. Existing executable steps, field bindings, scope, version compatibility and prior evidence references must remain intact. New executable behavior still requires the accepted-work learning path, available through operator/evaluation tooling. The chat UI has no completion-acceptance button; ordinary conversation review does not depend on it. Historical human acceptance remains distinct from model-inferred feedback. Runtime-owned admission checks and immutable package versioning govern activation, and the server requires the completed admission record before distributing chat-taught packages. Staff can inspect changes in the learning view and suspend or roll back a version.

The `chat_feedback` audit record retains the source message, quoted text, inferred classification and any target request/operation. Its attribution is `model_inferred_from_staff_chat`. It does not become an `action_assessment`, approve an operation, accept work, or assert that an application result was independently verified. A reported problem without a clear reusable correction can be recorded without producing a skill. Contract validation of prose is not proof of its behavioral correctness.

Reviews are bounded, and the model can miss or misunderstand a correction. They are not a complete continuous-learning guarantee. Review failures remain visible in the durable maintenance queue.

## Screenshots in chat

`capture_screen` reads the entire Windows virtual desktop, including other visible windows and monitors, without activating DemoBooks. It needs current server authority and the desktop lease, but no invoice selection. The authenticated Windows controller must run in an interactive desktop session. The browser fixture captures its test viewport and labels it accordingly. The API-only Ubuntu Marketing worker has no desktop capture tool.

The model sees the captured image. Durable context stores its artifact reference; image bytes are loaded only at the provider boundary. The newest capture in the current request is included, avoiding repeated image copies in checkpoints and premature context rotation from base64 text.

`share_screenshot` proposes a caption and optional rectangles, circles, arrows or text labels. A simple request to see the screen defaults to a plain screenshot; the agent adds drawings only when they help explain something or staff requests them. Coordinates are normalized to the full image. Annotations are bounded typed data rendered by trusted frontend code; the model cannot supply HTML, SVG or executable drawing scripts. Active employees use server authorization for capture and sharing; historical staff approvals retain their original provenance.

Only a completed capture from the same request can be shared or retrieved by the planner. The server checks the assigned worker, current staff authorization and artifact ownership. Chat renders the completed share receipt, not an unverified model message. Attachments show the capture time and remain chronological with the rest of the conversation. They are historical evidence, not live application state or authorization to click.

The Application Mediator experiment has been removed. Existing filtered captures retain their original `mediated_application` label so old evidence is not misrepresented as a full desktop screenshot. Current captures use the native desktop controller directly.

## Verification

Simulated model/staff tests cover conversation review deduplication, source quotes, private audiences, text-only skill admission, package publication, screenshot approval and replay, cross-worker image denial, and image delivery without base64 checkpoint storage. The Windows controller also builds as a self-contained Windows x64 application. Live validation results are recorded separately from these fixtures in [the evidence record](evidence/chat-learning-and-screenshots.json).

The regression suite covers 249 distinct tests, passed across independent file groups and focused reruns. Initial failures included two obsolete frontend/queue assumptions, which were corrected, and a restart test that correctly refused a changed coordinator prompt while source edits were still underway; that test passed with the source held stable. Python lint/format checks, frontend syntax checks, and independent server/harness installation checks also passed.

Actual OpenRouter `openai/gpt-5.6-luna` runs, with synthetic staff messages and simulated approval decisions, verified:

- A Marketing presentation correction automatically revised an existing skill without querying the application or asking for an assessment. A later campaign report read that released version and used the requested currency labels and two-decimal percentage.
- The Windows worker captured the full 1280 × 800 desktop without an invoice selection and shared an arrow-annotated attachment. Desktop and mobile browser checks verified image loading, enlargement, chronology and the absence of idle workspace/assessment forms.
- The API-only Marketing worker explained its missing screenshot capability without a foreground reporting call. The independent background reviewer recorded a suggestion with valid evidence.

Early screenshot runs exposed a remote artifact lookup error and an attempted reference to a previous request's capture. The lookup was fixed; stale captures now return a recoverable tool error before a sharing approval is created. Early background suggestions with incorrect source references were rejected; the reviewer instructions now distinguish current message IDs from episode IDs. Those failed proposals did not activate skills. These demonstrations verify particular cases, not that every future correction or model response will be correct.
