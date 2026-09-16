/* Public decisions and execution evidence. Never model-private reasoning. */
const activityView = (() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const json = value => `<pre>${escape(JSON.stringify(value, null, 2))}</pre>`;
  const opened = new Set();
  const bound = new WeakSet();
  const categories = kind => {
    if (["assistant_message", "model_step", "model_response", "coordinator_configuration"].includes(kind)) return "decisions";
    if (["approval_requested", "staff_decision", "stale_proposal", "record_selected"].includes(kind)) return "approvals";
    if (/recovery|failure|rejected|unavailable|assistance|failed/.test(kind)) return "recovery";
    if (["agent_tool_call", "agent_tool_result", "action_started", "action_result", "operation_completed"].includes(kind)) return "tools";
    if (kind === "observation") return "evidence";
    return "session";
  };
  const names = {
    agent_tool_call:"Agent tool call", agent_tool_result:"Tool returned to agent",
    operation_authorized:"Server authorized operation", action_started:"Authorized operation started", action_result:"Operation result",
    model_step:"Model call", model_response:"Model response", assistant_message:"Agent explanation / answer",
    approval_requested:"Awaiting staff approval", staff_decision:"Staff decision",
    record_unavailable:"Record lookup stopped", tool_arguments_rejected:"Invalid proposal — nothing executed",
    observation:"Application observation", recovery_required:"Workflow needs help",
  };
  function debugData(event) {
    // Public response text already has a chat bubble. Keep the model call's
    // technical metadata without repeating that text in expanded details.
    if (event.kind === "model_response") {
      const {public_summary, ...metadata} = event.data;
      return metadata;
    }
    return event.data;
  }
  function summary(event) {
    const d = event.data;
    if (event.kind === "model_step") return `Call ${d.call} · ${d.available_tools.length} available tools · ${d.record_id || "No selected record"}`;
    if (event.kind === "model_response") return `Call ${d.call} · ${d.tokens} tokens · ${d.tool_calls.length} tool calls`;
    if (event.kind === "action_started") return `${d.action.name} · ${d.invocation.includes(":skill:") ? "internal skill graph step" : "direct operation"}`;
    if (event.kind === "action_result") return d.result.error || (d.result.value ? "Returned a typed result" : "Operation finished");
    if (event.kind === "agent_tool_call") return d.name === "run_skill" ? `run_skill → ${d.arguments.skill_id}` : d.name === "run_operation" ? `run_operation → ${d.arguments.operation}` : d.name;
    if (event.kind === "staff_decision") return `${d.decision.decision} · ${d.name}${d.decision.explanation ? " · " + d.decision.explanation : ""}`;
    if (event.kind === "observation") return `${d.state?.observation_source || (d.state?.request_scope ? "Request scope; no desktop access" : "Application state")} · ${d.targets?.length || 0} visible controls`;
    if (event.kind === "tool_arguments_rejected") return `${d.name}: ${d.errors.map(e => e.msg).join("; ")}`;
    return d.description || d.text || d.message || d.reason || d.name || d.operation || "";
  }
  function details(event, data) {
    const d = debugData(event);
    let result = "";
    const invocation = d.invocation || d.run_id;
    if (invocation) result += `<p class="activity-id">Call / run: ${escape(invocation)}</p>`;
    if (d.description) result += `<p><strong>Registered purpose</strong> ${escape(d.description)}</p>`;
    if (d.expected) result += `<p><strong>Expected outcome</strong> ${escape(d.expected)}</p>`;
    if (d.arguments) result += `<h4>Proposed arguments</h4>${json(d.arguments)}`;
    if (d.corrected_arguments) result += `<h4>Staff-corrected arguments</h4>${json(d.corrected_arguments)}`;
    if (d.action) result += `<h4>Executed arguments</h4>${json(d.action.arguments)}`;
    if (d.result) result += `<h4>Returned result</h4>${json(event.kind === "action_result" ? d.result.value || d.result : d.result)}`;
    const observation = event.kind === "observation" ? d : d.observation || d.result?.after || d.evidence;
    if (observation?.screenshot) result += `<a href="/api/artifacts/${encodeURIComponent(observation.screenshot)}" target="_blank" rel="noopener">Open recorded screenshot ↗</a>`;
    if (event.kind === "action_result") {
      const start = data.events.find(e => e.kind === "action_started" && e.data.invocation === d.invocation);
      if (start) result += `<p class="hint">Elapsed since operation start: ${Math.max(0, event.at-start.at).toFixed(2)} seconds</p>`;
    }
    return result + `<div class="activity-payload">${result ? "<h4>Full event data</h4>" : ""}${json(d)}</div>`;
  }
  function events(data) {
    const chat = new Set(["assistant_message", "assistant_message_delta", "assistant_stream_end", "staff_message", "assistant_question"]);
    const quiet = new Set(["context_window", "conversation_context", "operation_completed"]);
    return data.events.filter(e => !chat.has(e.kind) && !quiet.has(e.kind));
  }
  function entry(event, data) {
    return `<details class="chat-debug-event activity-event activity-${categories(event.kind)}" data-message-id="debug-${escape(data.job.id)}-${event.seq}" data-debug-request="${escape(data.job.id)}" data-event-id="${event.seq}"><summary><span><strong>${escape(names[event.kind] || event.kind.replaceAll("_", " "))}</strong><span class="activity-summary">${escape(summary(event))}</span></span><time datetime="${new Date(event.at*1000).toISOString()}">${escape(new Date(event.at*1000).toLocaleTimeString())}</time></summary><div class="activity-body">${details(event,data)}</div></details>`;
  }
  function execution(data) {
    const j = data.job;
    const status = ["completed", "cancelled", "rejected", "failed", "denied"].includes(j.status) ? j.status : j.execution_state || j.status;
    const metadata = {request_id:j.id, status:j.status, execution_state:j.execution_state, controller:j.controller, model_mode:j.model_mode, model_calls:j.model_calls, tokens:j.tokens, result_kind:j.result_kind, accepted:j.accepted, completed_steps:j.completed, skill_runs:j.skill_runs || {}, error:j.error || null};
    return `<details class="chat-debug-event activity-event" data-message-id="execution-${escape(j.id)}" data-event-id="execution-${escape(j.id)}"><summary><span><strong>Execution details</strong><span class="activity-summary">Latest status: ${escape(status)}</span></span></summary><div class="activity-body">${json(metadata)}</div></details>`;
  }
  function bind(container) {
    for (const detail of container.querySelectorAll("details[data-event-id]")) {
      if (bound.has(detail)) continue;
      bound.add(detail);
      detail.open = opened.has(detail.dataset.eventId);
      detail.addEventListener("toggle", () => {
        if (!detail.isConnected) return;
        if (detail.open) opened.add(detail.dataset.eventId);
        else opened.delete(detail.dataset.eventId);
      });
    }
  }
  return {events, entry, execution, bind, reset:() => opened.clear()};
})();
