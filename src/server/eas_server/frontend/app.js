const $ = (id) => document.getElementById(id),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const submitted = new Set();
const streamedEvents = new Map();
const renderedBubbles = new Map();
let renderedSession = null, renderedJobs = [];
let chatDebug = localStorage.getItem("eas-chat-debug") === "true";
let roles = [];
let desktopAdapter = "browser";
let activeView = "jobs";
let active = null,
  selectedApproval = null,
  current = null,
  source = null,
  lastImage = "",
  refreshing = false;
function toast(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  setTimeout(() => ($("toast").hidden = true), 5000);
}
async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-EAS-CSRF": sessionStorage.getItem("eas-csrf") || "" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (r.status === 401) {
    sessionStorage.removeItem("eas-csrf");
    if (source) { source.close(); source = null; }
    // Clear cached private content immediately on logout or policy revocation.
    if (typeof transcriptCache !== "undefined") transcriptCache.clear();
    streamedEvents.clear();
    renderedBubbles.clear();
    activityView.reset();
    renderedSession = null;
    renderedJobs = [];
    $("chat-controls").hidden = true;
    $("review-panel").hidden = true;
    $("session-messages").replaceChildren();
    if (!$("login-dialog").open) $("login-dialog").showModal();
    throw Error("Connect to your workspace to continue.");
  }
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "object"
        ? data.detail.message
        : JSON.stringify(data.detail),
    );
  return data;
}
async function action(fn) {
  try {
    await fn();
    await refresh();
  } catch (e) {
    toast(e.message);
  }
}
let setupToken = null;
$("login-form").onsubmit = async (e) => {
  e.preventDefault();
  const button = $("login-submit");
  button.disabled = true;
  try {
    const credentials = {email: $("login-email").value, password: $("login-password").value};
    if (setupToken) {
      await api("/api/account/setup", {...credentials, token: setupToken});
      setupToken = null;
      $("login-password").value = "";
      $("login-password").autocomplete = "current-password";
      $("login-password").removeAttribute("minlength");
      button.textContent = "Sign in";
      $("login-explanation").textContent = "Password saved. Sign in with your email and password.";
      return;
    }
    const session = await api("/api/session", credentials);
    sessionStorage.setItem("eas-csrf", session.csrf);
    $("login-password").value = "";
    $("login-dialog").close();
    await loadIdentity();
    await refresh();
    connectStream();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
};
async function loadIdentity() {
  const me = await api("/api/me");
  if (me.csrf) sessionStorage.setItem("eas-csrf", me.csrf);
  $("signed-in-as").textContent = me.name;
  $("sign-out").hidden = false;
}
$("sign-out").onclick = async () => {
  await fetch("/api/session", {method: "DELETE", headers: {"X-EAS-CSRF": sessionStorage.getItem("eas-csrf") || ""}});
  sessionStorage.clear();
  location.reload();
};
function connectStream() {
  source?.close();
  source = null;
  if (!active) return;
  const requestId = active;
  const after = transcriptCache.get(requestId)?.events.at(-1)?.seq || 0;
  source = new EventSource(`/api/jobs/${requestId}/stream?after=${after}`);
  source.onmessage = message => {
    if (active !== requestId) return;
    const event = JSON.parse(message.data);
    streamedEvents.set(event.seq, event);
    const detail = transcriptCache.get(requestId);
    if (detail) cacheTranscript(detail);
    if ((chatDebug || ["assistant_message_delta", "assistant_message", "assistant_stream_end"].includes(event.kind)) && detail && renderedSession) {
      renderTranscript(renderedSession, renderedJobs);
      if (["assistant_message_delta", "assistant_stream_end"].includes(event.kind)) return;
    }
    refresh();
  };
}
function selectRequest(id) {
  if (active === id) return;
  active = id;
  streamedEvents.clear();
  selectedApproval = null;
  current = null;
  $("chat-controls").hidden = true;
  $("review-panel").hidden = true;
  lastImage = "";
  connectStream();
}
function renderDetail(d) {
  current = d;
  const j = d.job,
    pending = d.approvals.find(
      (a) => a.status === "pending" && !submitted.has(a.id),
    ),
    done = ["completed", "cancelled", "rejected", "failed", "denied"].includes(
      j.status,
    );
  $("chat-controls").hidden = done;
  $("cancel-job").disabled = done;
  $("takeover").disabled = done || d.lease.job_id !== j.id;
  $("takeover").textContent = d.lease.owner === "staff" ? "Release control" : "Take control";
  const latestObs = [...d.events]
    .reverse()
    .find((e) => e.kind === "observation")?.data;
  let obs = pending?.observation || latestObs;
  if (obs?.screenshot && obs.screenshot !== lastImage) {
    $("screenshot").src = "/api/artifacts/" + obs.screenshot;
    lastImage = obs.screenshot;
  }
  $("screenshot-wrap").hidden = !obs?.screenshot;
  $("review-panel").hidden = !pending;
  $("review-controls").hidden = !pending;
  if (pending) {
    $("review-title").textContent =
      pending.kind === "tool"
        ? "Agent requests your decision"
        : "Review next operation";
    $("review-kind").textContent =
      pending.kind === "tool" ? "STRICT · TOOL APPROVAL" : "NODE APPROVAL";
    $("proposal-copy").innerHTML =
      `<h3>${esc(pending.name.replaceAll("_", " "))}</h3><p>${esc(pending.description)}</p><div class="proposal-meta"><span>Target<strong>${esc(pending.inputs.department_id || "finance")} / ${esc(pending.inputs.record_id || pending.inputs.invoice_id)}</strong></span><span>Expected result<strong>${esc(pending.expected)}</strong></span></div>${pending.inputs.assistant_report ? `<p><strong>Requested outcome</strong><br>${esc(pending.inputs.request)}</p><p><strong>Assistant report</strong><br>${esc(pending.inputs.assistant_report)}</p>` : ""}`;
    const expected = pending.inputs.expected;
    if (pending.inputs.judgment) {
      const judgment = pending.inputs.judgment;
      const comparison = judgment.context.comparison;
      $("proposal-copy").innerHTML += `<p><strong>Independent model judgment</strong><br>Invoice: $${esc((comparison.invoice_amount / 100).toFixed(2))} · Purchase order: $${esc((comparison.purchase_order_amount / 100).toFixed(2))} · Difference: $${esc((comparison.difference / 100).toFixed(2))}<br>Model: ${esc(judgment.model)} · Prompt: ${esc(judgment.prompt_version)}</p><details><summary>Exact judgment inputs and prompt</summary><pre>${esc(JSON.stringify(judgment, null, 2))}</pre></details>`;
    }
    if (["prepare", "save", "save_draft"].includes(pending.name) && expected) {
      $("proposal-copy").innerHTML += `<p><strong>Correction amount:</strong> $${esc((expected.amount / 100).toFixed(2))}<br><strong>Explanation:</strong> ${esc(expected.note)}</p>`;
    }
    if (pending.name === "set_field") {
      $("proposal-copy").innerHTML += `<p><strong>Text to enter in ${esc(pending.arguments.field === "amount" ? "correction amount" : "correction explanation")}:</strong><br>${esc(pending.arguments.value)}</p>`;
    }
    if (pending.name === "share_screenshot") {
      const captured = d.events.filter(e => e.kind === "action_result").map(e => e.data.result?.value).find(v => v?.screenshot === pending.arguments.screenshot);
      if (captured) $("proposal-copy").innerHTML += renderScreenshot({...captured, ...pending.arguments});
    }
    if (pending.name === "ask_staff") $("proposal-copy").innerHTML += `<p><strong>Question:</strong> ${esc(pending.arguments.question)}</p>`;
    if (pending.name === "search_knowledge") $("proposal-copy").innerHTML += `<p><strong>Search for:</strong> ${esc(pending.arguments.query)}</p>`;
    if (selectedApproval?.id !== pending.id) {
      selectedApproval = pending;
      $("arguments").value = JSON.stringify(pending.arguments, null, 2);
      $("decision-note").value = "";
      drawTarget(pending.arguments, obs);
    }
    $("arguments").readOnly = pending.kind !== "tool";
    $("correct").hidden = pending.kind !== "tool";
    $("approve").textContent =
      pending.kind === "tool" ? "Approve tool call" : "Approve operation";
  } else {
    selectedApproval = null;
    $("review-title").textContent = "Review operation";
    $("review-kind").textContent =
      j.model_mode === "simulated" ? "SIMULATED ASSISTANCE" : "LIVE MODEL";
    $("proposal-copy").innerHTML = "";
    $("target-circle").hidden = true;
  }
}
function drawTarget(args, obs) {
  let t = obs.targets.find((t) => t.target === args.target);
  if (args.x != null) t = args;
  if (!t) {
    $("target-circle").hidden = true;
    return;
  }
  $("target-circle").hidden = false;
  $("target-circle").style.left = (t.x / obs.width) * 100 + "%";
  $("target-circle").style.top = (t.y / obs.height) * 100 + "%";
}
$("screenshot").onclick = (e) => {
  if (selectedApproval?.name !== "click") return;
  const r = e.target.getBoundingClientRect(),
    obs = selectedApproval.observation,
    args = {
      x: Math.round(((e.clientX - r.left) / r.width) * obs.width),
      y: Math.round(((e.clientY - r.top) / r.height) * obs.height),
    };
  $("arguments").value = JSON.stringify(args, null, 2);
  drawTarget(args, obs);
};
async function decide(decision) {
  if (!selectedApproval) return;
  const id = selectedApproval.id;
  for (const b of ["approve", "correct", "reject"]) $(b).disabled = true;
  try {
    await api(`/api/approvals/${id}`, {
      decision,
      explanation: $("decision-note").value,
      ...(decision === "correct"
        ? { arguments: JSON.parse($("arguments").value) }
        : {}),
    });
    submitted.add(id);
    selectedApproval = null;
    $("review-controls").hidden = true;
  } finally {
    for (const b of ["approve", "correct", "reject"]) $(b).disabled = false;
  }
}
$("approve").onclick = () => action(() => decide("approve"));
$("correct").onclick = () => action(() => decide("correct"));
$("reject").onclick = () => action(() => decide("reject"));
$("cancel-job").onclick = () =>
  action(() => api(`/api/jobs/${active}/cancel`, {}));
$("takeover").onclick = () =>
  action(() =>
    api(
      `/api/jobs/${active}/${current.lease.owner === "staff" ? "release" : "takeover"}`,
      {},
    ),
  );
function selectView(view) {
  activeView = view;
  const metrics = view === "metrics";
  $("chat-composer").hidden = metrics;
  $("learning-panel").hidden = metrics;
  $("metrics-view").hidden = !metrics;
  for (const name of ["jobs", "metrics"]) {
    const tab = $(name + "-tab");
    tab.classList.toggle("nav-active", name === view);
    if (name === view) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  $("page-eyebrow").textContent = metrics ? "EVALUATION" : "WORKER CONSOLE";
  $("page-title").textContent = metrics ? "Evaluation metrics" : "Work, with oversight.";
  $("page-description").textContent = metrics
    ? "Compare simulated and live runs. Results refresh automatically."
    : "Describe the outcome. Approve the work. Teach the next request.";
}
function metricValue(name, value) {
  if (value == null) return "—";
  if (name === "completion_rate") return (value * 100).toFixed(1) + "%";
  if (name === "execution_seconds") return value.toLocaleString(undefined, { maximumFractionDigits: 1 }) + " s";
  return value.toLocaleString();
}
async function refreshMetrics() {
  const m = await api("/api/metrics");
  $("metrics-view").innerHTML =
      `<section class="panel"><h2>Run results</h2><p class="muted">Simulated harness runs and live-model runs are reported separately.</p><table><thead><tr><th>Metric</th><th>Simulated</th><th>Live</th></tr></thead><tbody>${Object.keys(
        m.simulated,
      )
        .map(
          (k) =>
            `<tr><td>${esc(k.replaceAll("_", " "))}</td><td>${esc(metricValue(k, m.simulated[k]))}</td><td>${esc(metricValue(k, m.live[k]))}</td></tr>`,
        )
        .join("")}</tbody></table></section>`;
}
$("metrics-tab").onclick = () => action(async () => selectView("metrics"));
$("jobs-tab").onclick = () => action(async () => selectView("jobs"));
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    if (!roles.length) {
      roles = await api("/api/roles");
      $("chat-workspace").innerHTML = roles.map(r => `<option value="${esc(r.id)}">${esc(r.department_name)} · ${esc(r.name)}</option>`).join("");
    }
    if (!roles.length) return;
    const session = await api("/api/chat?role_id=" + encodeURIComponent($("chat-workspace").value));
    // Display only this authenticated conversation. Browser storage and the
    // all-request audit endpoint cannot select another identity's execution.
    const jobs = (await api("/api/jobs")).filter(j => j.conversation_id === session.conversation_id);
    const latest = session.current?.id || null;
    if (conversationId !== session.conversation_id || latestRequestId !== latest || !jobs.some(j => j.id === active)) {
      selectRequest(latest);
    }
    conversationId = session.conversation_id;
    latestRequestId = latest;
    let detail=null;
    if (active && jobs.some(j => j.id === active)) {
      detail=await api("/api/jobs/" + active);
      renderDetail(detail);
    } else {
      $("chat-controls").hidden = true;
      $("review-panel").hidden = true;
    }
    await renderSession(session, jobs, detail);
    const health = await api("/api/health");
    desktopAdapter = health.desktop_adapter;
    $("test-workspace").hidden = desktopAdapter !== "browser";
    $("model-label").textContent =
      health.model_mode === "simulated" ? "Simulated assistance" : "Live model";
    if (activeView === "metrics") await refreshMetrics();
    else await refreshLearning();
  } catch (e) {
    if (!$("login-dialog").open) toast(e.message);
  } finally {
    refreshing = false;
  }
}
$("chat-workspace").onchange = () => {
  selectRequest(null);
  conversationId = null;
  requestDraft = null;
  transcriptCache.clear();
  $("session-messages").replaceChildren();
  refresh();
};
let conversationId = null;
let latestRequestId = null;
localStorage.removeItem("active-job");
let requestDraft = null;
let transcriptSession = null;
let transcriptLimit = 20;
let transcriptMarkup = "";
const transcriptCache = new Map();
const accepting = new Set();
$("session-messages").addEventListener("click", event => {
  const button = event.target.closest("[data-accept-request]");
  if (!button || button.disabled) return;
  const id = button.dataset.acceptRequest;
  if (accepting.has(id)) return;
  accepting.add(id);
  button.disabled = true;
  action(async () => {
    try {
      await api(`/api/jobs/${encodeURIComponent(id)}/accept`, {});
      cacheTranscript(await api(`/api/jobs/${encodeURIComponent(id)}`));
      toast("Result accepted.");
    } finally {
      accepting.delete(id);
      button.disabled = false;
      renderCurrentTranscript();
    }
  });
});
$("earlier-messages").onclick = () => {
  transcriptLimit += 20;
  refresh();
};
$("chat-form").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    const task = $("chat-request").value.trim();
    if (!requestDraft || requestDraft.task !== task || requestDraft.conversation_id !== conversationId) {
      conversationId ||= crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
      const role = roles.find(r => r.id === $("chat-workspace").value);
      if (!role) throw Error("Select an authorized workspace");
      requestDraft = {task, department_id:role.department_id, role_id:role.id, conversation_id:conversationId,request_id:crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`};
    }
    const result = await api("/api/chat",requestDraft);
    const job = result.job;
    selectRequest(job.id);
    $("chat-request").value = "";
    requestDraft = null;
    connectStream();
  });
};
async function renderSession(session, jobs, selectedDetail) {
  const j = session.current;
  if (transcriptSession !== session.conversation_id) {
    transcriptSession = session.conversation_id;
    transcriptLimit = 20;
    transcriptMarkup = "";
    transcriptCache.clear();
    renderedBubbles.clear();
    activityView.reset();
    $("session-messages").replaceChildren();
  }
  const done = !j || ["completed", "cancelled", "rejected", "failed", "denied"].includes(j.status);
  $("chat-request").placeholder = done
    ? "Continue the conversation or describe your next task…"
    : "Reply, clarify, or give guidance. This does not approve an operation…";
  const history = jobs.filter(turn => turn.conversation_id === session.conversation_id)
    .sort((a,b) => a.created_at - b.created_at || a.id.localeCompare(b.id));
  const visible = history.slice(-transcriptLimit);
  $("earlier-messages").hidden = history.length <= visible.length;
  if (selectedDetail && visible.some(turn => turn.id === selectedDetail.job.id)) {
    cacheTranscript(selectedDetail);
  }
  const missing = visible.filter(turn => !transcriptCache.has(turn.id) || !["completed", "cancelled", "rejected", "failed", "denied"].includes(transcriptCache.get(turn.id).job.status));
  // Fetch full public exchanges, not the last-reply summaries. Limit concurrent
  // reads and cache ended requests; active requests stay fresh while polling.
  for (let i=0; i<missing.length; i+=5) {
    const batch = await Promise.all(missing.slice(i,i+5).map(turn => api("/api/jobs/"+turn.id)));
    batch.forEach(cacheTranscript);
  }
  renderedSession = session;
  renderedJobs = jobs;
  renderTranscript(session, jobs);
}
function cacheTranscript(data) {
  // A fetch can finish after newer SSE chunks arrive. Merge by server sequence
  // so reconnects and concurrent refreshes neither duplicate nor erase text.
  const events = new Map(data.events.map(event => [event.seq, event]));
  if (data.job.id === active) streamedEvents.forEach((event, seq) => events.set(seq, event));
  transcriptCache.set(data.job.id, {...data, events:[...events.values()].sort((a,b) => a.seq-b.seq)});
}
function outcomeNotice(job) {
  if (job.status === "completed") return !job.accepted && !["conversation", "record_unavailable"].includes(job.result_kind) ? "acceptance" : null;
  if (job.status === "cancelled") return "Work stopped.";
  if (["rejected", "denied"].includes(job.status)) return "This request was declined.";
  if (job.status === "failed") return "The worker couldn't finish this request. Reply in chat to discuss the next step.";
  if (job.error) return "The worker needs help to continue. Reply in chat or take control.";
  return null;
}
function renderTranscript(session, jobs) {
  const visible = jobs.filter(turn => turn.conversation_id === session.conversation_id)
    .sort((a,b) => a.created_at-b.created_at || a.id.localeCompare(b.id)).slice(-transcriptLimit);
  const entries = visible.flatMap(turn => {
    const data = transcriptCache.get(turn.id);
    if (!data) return [];
    const created = data.events.find(event => event.kind === "job_created");
    const shares = new Set(data.events.filter(e => e.kind === "action_started" && e.data.action?.name === "share_screenshot").map(e => e.data.invocation));
    const debug = chatDebug ? activityView.events(data).map(event => ({at:event.at, seq:event.seq, debug:event, detail:data})) : [];
    const messages = chatStream.events(data.events, data.job.status).filter(event => ["staff_message", "assistant_message", "assistant_question"].includes(event.kind) || (event.kind === "action_result" && shares.has(event.data.invocation)));
    const last = messages.at(-1) || data.events.at(-1) || {at:turn.created_at, seq:0};
    const notice = outcomeNotice(data.job);
    return [{id: "request-"+turn.id, requestId: turn.id, modelMode:turn.model_mode, at: turn.created_at, seq: created?.seq || 0, speaker: "staff", text: turn.task, record: turn.record_id}, ...debug,
      ...(chatDebug ? [{at:turn.created_at, seq:(created?.seq || 0) + 0.1, execution:data}] : []),
      ...messages.map(event => ({id: event.data.message_id && event.kind === "assistant_message" ? "reply-"+event.data.message_id : "event-"+event.seq, at: event.at, seq: event.seq, speaker: event.kind === "staff_message" ? "staff" : "agent", text: event.data.text || event.data.question || "", partial:event.partial, interrupted:event.interrupted, attachment: event.kind === "action_result" ? event.data.result?.value?.data : null})),
      ...(notice ? [{at:last.at, seq:last.seq + 0.5, requestId:turn.id, notice}] : [])];
  }).sort((a,b) => a.at-b.at || a.seq-b.seq);
  const markup = entries.map(entry => {
    if (entry.debug) return activityView.entry(entry.debug, entry.detail);
    if (entry.execution) return activityView.execution(entry.execution);
    if (entry.notice) return `<div class="chat-outcome" data-message-id="outcome-${esc(entry.requestId)}">${entry.notice === "acceptance" ? `<button type="button" class="primary" data-accept-request="${esc(entry.requestId)}" ${accepting.has(entry.requestId) ? "disabled" : ""}>Accept completed work</button>` : `<p>${esc(entry.notice)}</p>`}</div>`;
    const date = new Date(entry.at*1000);
    return `<div class="chat-message ${entry.speaker}${entry.partial && !entry.interrupted ? " streaming" : ""}" data-message-id="${esc(entry.id)}"><div class="chat-message-meta"><strong>${entry.speaker === "staff" ? "Staff" : "Worker"}${entry.record ? ` · ${esc(entry.record)}` : ""}</strong><time datetime="${date.toISOString()}" title="${esc(date.toLocaleString())}">${esc(date.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}))}</time></div><p>${esc(entry.text)}</p>${entry.partial ? `<small class="stream-status">${entry.interrupted ? "Response interrupted" : "Responding…"}</small>` : ""}${entry.attachment ? renderScreenshot(entry.attachment) : ""}${entry.requestId && chatDebug ? `<div class="chat-debug-request"><span>${entry.modelMode === "live" ? "Live model" : "Simulated model"}</span><a class="chat-activity-link" href="/api/jobs/${encodeURIComponent(entry.requestId)}/episode" target="_blank" rel="noopener">Export episode ↗</a></div>` : ""}</div>`;
  }).join("");
  const transcript = $("session-messages");
  if (markup !== transcriptMarkup) {
    const first = transcript.firstElementChild?.dataset.messageId;
    const oldHeight = transcript.scrollHeight, oldTop = transcript.scrollTop;
    const atBottom = oldHeight-transcript.clientHeight-oldTop < 48;
    const top = transcript.getBoundingClientRect().top;
    const anchor = [...transcript.children].find(node => node.getBoundingClientRect().bottom > top);
    const anchorId = anchor?.dataset.messageId, anchorTop = anchor?.getBoundingClientRect().top;
    const wasEmpty = !transcriptMarkup;
    const template = document.createElement("template");
    template.innerHTML = markup;
    const existing = new Map([...transcript.children].map(node => [node.dataset.messageId, node]));
    const fragment = document.createDocumentFragment(), nextBubbles = new Map();
    for (const node of [...template.content.children]) {
      const id = node.dataset.messageId, html = node.outerHTML;
      // Retain unchanged messages, enlarged screenshots and expanded debug rows.
      fragment.append(existing.has(id) && renderedBubbles.get(id) === html ? existing.get(id) : node);
      nextBubbles.set(id, html);
    }
    transcript.replaceChildren(fragment);
    activityView.bind(transcript);
    renderedBubbles.clear();
    nextBubbles.forEach((html,id) => renderedBubbles.set(id, html));
    const prepended = first && first !== transcript.firstElementChild?.dataset.messageId;
    const restoredAnchor = [...transcript.children].find(node => node.dataset.messageId === anchorId);
    if ((prepended || !atBottom) && restoredAnchor) transcript.scrollTop += restoredAnchor.getBoundingClientRect().top-anchorTop;
    else if (atBottom || wasEmpty) transcript.scrollTop = transcript.scrollHeight;
    else transcript.scrollTop = oldTop;
    transcriptMarkup = markup;
  }
  $("conversation-label").textContent = "One continuous conversation · Messages stay in chronological order";
}
async function refreshLearning() {
  const status = await api("/api/learning");
  learningView.render(status);
  document.querySelectorAll("[data-skill]").forEach(button => button.onclick=()=>action(()=>api(`/api/skills/${encodeURIComponent(button.dataset.skill)}/change`,{version:button.dataset.version || null})));
}
function renderCurrentTranscript() {
  if (renderedSession && renderedSession.conversation_id === conversationId) renderTranscript(renderedSession, renderedJobs);
}
function setChatDebug(enabled) {
  chatDebug = enabled;
  localStorage.setItem("eas-chat-debug", String(enabled));
  $("debug-mode").setAttribute("aria-pressed", String(enabled));
  $("session-messages").classList.toggle("debug-enabled", enabled);
  renderCurrentTranscript();
}
$("debug-mode").onclick = () => setChatDebug(!chatDebug);
setChatDebug(chatDebug);
async function start() {
  const setup = new URLSearchParams(location.hash.slice(1));
  if (setup.has("setup")) {
    setupToken = setup.get("setup");
    $("login-email").value = setup.get("email") || "";
    history.replaceState(null, "", location.pathname + location.search);
    $("login-password").autocomplete = "new-password";
    $("login-password").minLength = 15;
    $("login-submit").textContent = "Set password";
    $("login-explanation").textContent = "Choose a password of at least 15 characters. This setup link expires after one hour and can be used once.";
    $("login-dialog").showModal();
    return;
  }
  try { await loadIdentity(); } catch { return; }
  await refresh();
  connectStream();
}
start();
setInterval(refresh, 2500);
