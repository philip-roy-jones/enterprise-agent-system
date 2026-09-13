/* Public decisions and execution evidence. Never model-private reasoning. */
const activityView = (() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const json = value => `<pre>${escape(JSON.stringify(value, null, 2))}</pre>`;
  const opened = new Set();
  let current = null, lastMarkup = "";
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
    action_started:"Approved operation started", action_result:"Operation result",
    model_step:"Model call", model_response:"Model response", assistant_message:"Agent explanation / answer",
    approval_requested:"Awaiting staff approval", staff_decision:"Staff decision",
    record_unavailable:"Record lookup stopped", tool_arguments_rejected:"Invalid proposal — nothing executed",
    observation:"Application observation", recovery_required:"Workflow needs help",
  };
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
    const d = event.data;
    let result = "";
    const invocation = d.invocation || d.run_id;
    if (invocation) result += `<p class="activity-id">Call / run: ${escape(invocation)}</p>`;
    if (d.description) result += `<p><strong>Registered purpose</strong> ${escape(d.description)}</p>`;
    if (d.expected) result += `<p><strong>Expected outcome</strong> ${escape(d.expected)}</p>`;
    if (event.kind === "assistant_message") result += `<p>${escape(d.text)}</p><p class="hint">${d.source ? escape(d.source) : "Public agent explanation; an explanation is not proof of execution."}</p>`;
    if (d.arguments) result += `<h4>Proposed arguments</h4>${json(d.arguments)}`;
    if (d.corrected_arguments) result += `<h4>Staff-corrected arguments</h4>${json(d.corrected_arguments)}`;
    if (d.action) result += `<h4>Executed arguments</h4>${json(d.action.arguments)}`;
    if (d.result) result += `<h4>Returned result</h4>${json(event.kind === "action_result" ? d.result.value || d.result : d.result)}`;
    if (d.public_summary?.length) result += `<h4>Public decision summary</h4><p>${escape(d.public_summary.join("\n"))}</p>`;
    const observation = event.kind === "observation" ? d : d.observation || d.result?.after || d.evidence;
    if (observation?.screenshot) result += `<a href="/api/artifacts/${encodeURIComponent(observation.screenshot)}" target="_blank" rel="noopener">Open recorded screenshot ↗</a>`;
    if (event.kind === "action_result") {
      const start = data.events.find(e => e.kind === "action_started" && e.data.invocation === d.invocation);
      if (start) result += `<p class="hint">Elapsed since operation start: ${Math.max(0, event.at-start.at).toFixed(2)} seconds</p>`;
    }
    return result + `<details class="activity-payload" data-event-id="payload-${event.seq}" ${opened.has("payload-"+event.seq) ? "open" : ""}><summary>Full event data</summary>${json(d)}</details>`;
  }
  function render(data) {
    const container = document.getElementById("timeline");
    if (current !== data.job.id) { current = data.job.id; opened.clear(); lastMarkup = ""; }
    const filter = document.getElementById("activity-filter").value;
    const search = document.getElementById("activity-search").value.trim().toLowerCase();
    const quiet = new Set(["context_window", "conversation_context", "operation_completed"]);
    const events = data.events.filter(e => !["assistant_message_delta", "assistant_stream_end"].includes(e.kind) && (filter === "all" ? !quiet.has(e.kind) : categories(e.kind) === filter) && (!search || JSON.stringify(e).toLowerCase().includes(search)));
    const calls = new Set(data.events.filter(e=>e.kind === "agent_tool_call").map(e=>e.data.invocation));
    if (!calls.size) data.approvals.filter(a=>a.kind === "tool").forEach(a=>calls.add(a.invocation));
    const steps = new Set(data.events.filter(e=>e.kind === "action_started" && e.data.invocation.includes(":skill:")).map(e=>e.data.invocation));
    document.getElementById("activity-counts").textContent = `${data.job.model_mode === "live" ? "Live model" : "Simulated model"} · ${data.job.model_calls} model calls · ${calls.size} recorded agent calls · ${steps.size} skill graph steps · ${events.length} events shown`;
    const markup = [...events].reverse().map(e => `<details class="activity-event activity-${categories(e.kind)}" data-event-id="${e.seq}" ${opened.has(String(e.seq)) ? "open" : ""}><summary><span><strong>${escape(names[e.kind] || e.kind.replaceAll("_", " "))}</strong><span class="activity-summary">${escape(summary(e))}</span></span><time datetime="${new Date(e.at*1000).toISOString()}">${escape(new Date(e.at*1000).toLocaleTimeString())}</time></summary><div class="activity-body">${details(e,data)}</div></details>`).join("") || '<p class="muted">No matching events.</p>';
    if (markup !== lastMarkup) {
      const top = container.scrollTop;
      container.innerHTML = markup;
      container.scrollTop = top;
      lastMarkup = markup;
      container.querySelectorAll("details[data-event-id]").forEach(detail => detail.addEventListener("toggle", () => {
        if (detail.open) opened.add(detail.dataset.eventId); else opened.delete(detail.dataset.eventId);
      }));
    }
  }
  return {render};
})();
