# Automatic discovery and supervised execution

Users describe the work, not a request to create workflow code. The assigned worker checks for a known procedure. An unmatched request goes directly to Deep Agent assistance in the same job, with its existing department, record scope, and permissions.

Three reasons can initiate assistance:

1. **Missing procedure:** no installed procedure matches the request.
2. **Unfamiliar application state:** a dialog, label, or other condition has no tested recovery rule.
3. **Procedure failure:** an authorized operation fails unexpectedly, such as a broken selector or a code defect. The job records the operation, exception type, and mutation state for diagnosis.

Permission denial, cancellation, rejection, and failures of the authority service do not become permission to try another execution path. After an uncertain Save, both scripted and assistant paths inspect existing results; neither repeats Save merely because no confirmation arrived.

## What staff approve

The preview describes the business action, its target, arguments, expected outcome, and current evidence. API-backed work, accessibility actions, and mouse/keyboard actions use the same approval records. Model explanations supplement the registered operation description; they do not replace the actual arguments bound to approval.

For example, an invoice draft proposal identifies the company and invoice, the exact amount and explanation to enter, and that the result is a draft. A desktop click additionally marks the target on the current screenshot. Staff can approve, reject, or correct a tool's arguments. Changed evidence invalidates the previous decision.

Strict mode approves every executable workflow operation. Auto mode can execute known workflow operations without individual prompts. Deep Agent tools always need individual approval, including reads, in either selected mode.

## Current implementation

The Finance worker recognizes its existing invoice correction procedure conservatively. Other requests automatically enter supervised discovery. The assistant can inspect and navigate within the assigned invoice scope, report findings and limitations, and submit the report for a mandatory staff outcome decision. The report is part of the approval's exact arguments. Completing discovery never falls through into the invoice correction procedure or silently creates a draft.

Before the scripted comparison has verified business values, the current Finance assistant has read and navigation tools only. New tasks requiring other business mutations need suitable scoped capabilities and verification rules. This prototype does not manufacture those permissions or arbitrary API clients.

An accepted episode is evidence for reusable workflow code. The existing development command generates and tests a bounded field-label resolver improvement in an isolated checkout. General workflow-code generation from arbitrary discovery episodes remains to be implemented. Its trigger should be accumulated experience from normal work, with tests and developer review before installation—not a separate staff “create workflow” action, and not live self-modification.
