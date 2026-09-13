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
  source = new EventSource(`/api/jobs/${active}/stream`);
  source.onmessage = () => refresh();
}
function selectRequest(id) {
  if (active === id) return;
  active = id;
  selectedApproval = null;
  current = null;
  lastImage = "";
  connectStream();
}
const invoiceStages = {
  validate: "Validate",
  establish: "Open invoice",
  compare: "Compare PO",
  prepare: "Prepare draft",
  save: "Save",
  verify: "Verify",
  complete: "Complete",
  report: "Report",
  judge: "Classify",
};
let readable = invoiceStages;
function renderDetail(d) {
  current = d;
  const role = roles.find((r) => r.id === d.job.role_id);
  readable =
    !role || role.id === "invoice_correction"
      ? invoiceStages
      : Object.fromEntries(role.stages.map((s) => [s, s.replaceAll("_", " ")]));
  const j = d.job,
    pending = d.approvals.find(
      (a) => a.status === "pending" && !submitted.has(a.id),
    ),
    done = ["completed", "cancelled", "rejected", "failed", "denied"].includes(
      j.status,
    );
  $("empty").hidden = true;
  $("active-job").hidden = false;
  $("job-id").textContent = `${j.graph_version} / ${j.id.slice(0, 8)}`;
  $("job-title").textContent =
    `${j.role_name || "Invoice correction"} · ${j.record_id || j.invoice_id || "Conversation"}`;
  $("job-status").textContent = (done ? j.status : j.execution_state || j.status);

  $("cancel-job").disabled = done;
  $("takeover").disabled = done;
  $("takeover").textContent =
    d.lease.owner === "staff" ? "Release control" : "Take control";
  $("accept-job").hidden = j.status !== "completed" || j.accepted || ["conversation", "record_unavailable"].includes(j.result_kind);
  // The composer always addresses the persistent staff session, even while an older activity is inspected.
  $("conversation-label").textContent = "Your ongoing conversation · history is retained across context changes";
  $("skill-runs").innerHTML = Object.values(j.skill_runs || {}).map(run => `<p><strong>${esc(run.skill_id)}</strong> · ${esc(run.state.replaceAll("_"," "))} · step ${run.index + 1}<br><small>Version ${esc(run.version.slice(0,12))} · Run ${esc(run.run_id)}</small>${run.reason ? `<br>${esc(run.reason)}` : ""}</p>`).join("");
  $("job-error").textContent = j.error || "";
  const staffQuestion = d.conversation?.questions.find(q => q.status === "pending");
  $("staff-question").hidden = !staffQuestion || done;
  $("staff-question").textContent = staffQuestion ? `The assistant needs your answer: ${staffQuestion.question}` : "";
  $("message").placeholder = staffQuestion ? "Reply to the assistant’s question…" : "Add context or a review note…";
  $("message-form").hidden = done || j.conversation_id === conversationId;
  $("message").disabled = done;
  $("message-form").querySelector("button").disabled = done;
  const shownSteps=[...new Set([...j.completed,...(pending ? [pending.name] : [])])];
  $("progress").innerHTML = shownSteps.map(id=>[id,readable[id] || id.replaceAll("_"," ")])
    .map(
      ([id, label], i) =>
        `<div class="step ${j.completed.includes(id) ? "finished" : ""}"><span>${j.completed.includes(id) ? "✓" : i + 1}</span><small>${label}</small></div>`,
    )
    .join("");
  $("episode-link").href = `/api/jobs/${j.id}/episode`;
  const latestObs = [...d.events]
    .reverse()
    .find((e) => e.kind === "observation")?.data;
  let obs = pending?.observation || latestObs;
  if (obs?.screenshot && obs.screenshot !== lastImage) {
    $("screenshot").src = "/api/artifacts/" + obs.screenshot;
    lastImage = obs.screenshot;
  }
  $("screenshot-wrap").hidden = !obs?.screenshot;
  $("review-controls").hidden = !pending;
  $("waiting").hidden = !!pending;
  $("waiting").textContent = j.result_kind === "record_unavailable" ? j.record_lookup.message : j.result_kind === "conversation" ? "Continue in the conversation when you’re ready." : done
    ? j.accepted
      ? "Staff accepted the verified result."
      : j.status === "completed"
        ? "Outcome verified. Accept the work to make this episode available for improvement."
        : `Request ${j.status}.`
    : d.lease.owner === "staff"
      ? desktopAdapter === "browser"
        ? "You hold desktop control. Use the browser test workspace, then release control."
        : "You hold desktop control. Work in the application on the Windows machine, then release control."
      : "Worker is running or reconciling current state.";
  if (staffQuestion && !done) $("waiting").textContent = "Waiting for your answer in the request conversation.";
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
    $("review-title").textContent = "Live workspace";
    $("review-kind").textContent =
      j.model_mode === "simulated" ? "SIMULATED ASSISTANCE" : "LIVE MODEL";
    $("proposal-copy").innerHTML = "";
    $("target-circle").hidden = true;
  }
  const finishedInvocations = new Set(d.events.filter(e => e.kind === "action_result").map(e => e.data.invocation));
  const oldAssessment = $("assessment-operation").value;
  const finishedActions = [...new Map(d.events.filter(e => e.kind === "action_started" && finishedInvocations.has(e.data.invocation)).map(e => [e.data.invocation, e])).values()];
  $("assessment-operation").innerHTML = finishedActions.map(e => `<option value="${esc(e.data.invocation)}">${esc(readable[e.data.action.name] || e.data.action.name)} · ${new Date(e.at * 1000).toLocaleTimeString()}</option>`).join("");
  if (finishedActions.some(e => e.data.invocation === oldAssessment)) $("assessment-operation").value = oldAssessment;
  $("assessment-form").querySelector("button").disabled = !finishedActions.length;
  activityView.render(d);
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
$("accept-job").onclick = () =>
  action(() => api(`/api/jobs/${active}/accept`, {}));
$("takeover").onclick = () =>
  action(() =>
    api(
      `/api/jobs/${active}/${current.lease.owner === "staff" ? "release" : "takeover"}`,
      {},
    ),
  );
let draftMessage = null;
$("assessment-form").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    const job = active;
    const explanation = $("assessment-explanation").value;
    await api(`/api/jobs/${job}/assessments`, {invocation: $("assessment-operation").value, outcome: $("assessment-outcome").value, explanation});
    if (job === active && $("assessment-explanation").value === explanation) $("assessment-explanation").value = "";
  });
};
$("message-form").onsubmit = (e) => {
  e.preventDefault();
  action(async () => {
    const text = $("message").value;
    const replyTo = current?.conversation?.questions.find(q => q.status === "pending")?.question_id || null;
    if (!draftMessage || draftMessage.text !== text || draftMessage.reply_to !== replyTo || draftMessage.job !== active) {
      draftMessage = {job: active, text, reply_to: replyTo, message_id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`};
    }
    const {job, ...message} = draftMessage;
    await api(`/api/jobs/${job}/messages`, message);
    draftMessage = null;
    if (active === job && $("message").value === text) $("message").value = "";
  });
};
function selectView(view) {
  activeView = view;
  const metrics = view === "metrics";
  $("main-view").hidden = metrics;
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
      $("empty").hidden = false;
      $("active-job").hidden = true;
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
$("session-messages").onclick = event => {
  const button = event.target.closest("[data-request-activity]");
  if (!button) return;
  action(async () => {
    selectRequest(button.dataset.requestActivity);
    await refresh();
    $("main-view").scrollIntoView({behavior: "smooth", block: "start"});
  });
};
async function renderSession(session, jobs, selectedDetail) {
  const j = session.current;
  if (transcriptSession !== session.conversation_id) {
    transcriptSession = session.conversation_id;
    transcriptLimit = 20;
    transcriptMarkup = "";
    transcriptCache.clear();
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
    transcriptCache.set(selectedDetail.job.id, selectedDetail);
  }
  const missing = visible.filter(turn => !transcriptCache.has(turn.id) || !["completed", "cancelled", "rejected", "failed", "denied"].includes(transcriptCache.get(turn.id).job.status));
  // Fetch full public exchanges, not the last-reply summaries. Limit concurrent
  // reads and cache ended requests; active requests stay fresh while polling.
  for (let i=0; i<missing.length; i+=5) {
    const batch = await Promise.all(missing.slice(i,i+5).map(turn => api("/api/jobs/"+turn.id)));
    batch.forEach(data => transcriptCache.set(data.job.id, data));
  }
  const entries = visible.flatMap(turn => {
    const data = transcriptCache.get(turn.id);
    const created = data.events.find(event => event.kind === "job_created");
    return [{id: "request-"+turn.id, requestId: turn.id, at: turn.created_at, seq: created?.seq || 0, speaker: "staff", text: turn.task, record: turn.record_id},
      ...data.events.filter(event => ["staff_message", "assistant_message", "assistant_question"].includes(event.kind))
        .map(event => ({id: "event-"+event.seq, at: event.at, seq: event.seq, speaker: event.kind === "staff_message" ? "staff" : "agent", text: event.data.text || event.data.question || ""}))];
  }).sort((a,b) => a.at-b.at || a.seq-b.seq);
  const markup = entries.map(entry => {
    const date = new Date(entry.at*1000);
    return `<div class="chat-message ${entry.speaker}" data-message-id="${esc(entry.id)}"><div class="chat-message-meta"><strong>${entry.speaker === "staff" ? "Staff" : "Worker"}${entry.record ? ` · ${esc(entry.record)}` : ""}</strong><time datetime="${date.toISOString()}" title="${esc(date.toLocaleString())}">${esc(date.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}))}</time></div><p>${esc(entry.text)}</p>${entry.requestId ? `<button type="button" class="chat-activity-link" data-request-activity="${esc(entry.requestId)}">View activity</button>` : ""}</div>`;
  }).join("");
  const transcript = $("session-messages");
  if (markup !== transcriptMarkup) {
    const first = transcript.firstElementChild?.dataset.messageId;
    const oldHeight = transcript.scrollHeight, oldTop = transcript.scrollTop;
    const atBottom = oldHeight-transcript.clientHeight-oldTop < 48;
    const wasEmpty = !transcriptMarkup;
    transcript.innerHTML = markup;
    const prepended = first && first !== transcript.firstElementChild?.dataset.messageId;
    if (prepended) transcript.scrollTop = oldTop + transcript.scrollHeight-oldHeight;
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
$("activity-filter").onchange = refresh;
$("activity-search").oninput = refresh;
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
