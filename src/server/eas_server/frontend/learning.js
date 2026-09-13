/* Readable learning provenance; proposals never execute from this view. */
const learningView = (() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const json = value => `<pre>${esc(JSON.stringify(value, null, 2))}</pre>`;
  const opened = new Set();
  let previous = "";
  const evidence = ids => [...new Set(ids || [])].map(id => `<a href="/api/jobs/${encodeURIComponent(id)}/episode" target="_blank" rel="noopener">${esc(id.slice(0,12))} ↗</a>`).join(" · ") || "No teaching episode (bundled package)";
  function render(status) {
    const container = document.getElementById("learning-content");
    const versions = status.registries.flatMap(r => r.versions || []);
    const reviews = status.queue.slice(0,30);
    const markup = `<p>Accepted work can teach reusable procedures. Every business operation still requires approval.</p>` +
      (versions.length ? `<div class="learning-versions">${versions.map(v => `<details data-learning-id="version-${esc(v.version)}"><summary><strong>${esc(v.title)}</strong> · ${v.active ? "Active" : "Available for rollback"} · ${v.steps.length ? "Workflow" : "Guidance"} · ${esc(v.version.slice(0,12))}</summary><p>${esc(v.description)}</p><p>${esc(v.steps.join(" → ") || "Natural-language guidance using individually approved tools")}</p><h4>Instructions</h4>${json(v.instructions || "Instructions are available through the skill read log.")}<p>Supporting files: ${esc((v.resources || []).join(", ") || "None")}</p><p>Teaching evidence: ${evidence(v.evidence_ids)}</p><button data-skill="${esc(v.skill_id)}" data-version="${v.active ? "" : esc(v.version)}">${v.active ? "Suspend" : "Activate this version"}</button></details>`).join("")}</div>` : "<p>No skills published by the edge yet.</p>") +
      `<h3>Learning reviews</h3>` + (reviews.length ? reviews.map(q => {
        const r = q.result || {}, changes = r.changes, checks = r.checks;
        return `<details data-learning-id="review-${esc(q.id)}"><summary><strong>${esc(q.trigger || (q.kind === "learn" ? "Accepted teaching" : q.kind.replaceAll("_"," ")))}</strong> · ${esc(r.status || q.status)}${r.model_mode ? ` · ${r.model_mode === "live" ? "Live model" : "Simulated model"}` : ""}</summary><p>${esc(r.reason || q.reason || "Waiting for edge maintenance")}</p><p>Evidence: ${evidence([q.job_id, ...(q.related_job_ids || [])].filter(Boolean))}</p>${r.version ? `<p>Version: ${esc(r.version)}<br>Previous: ${esc(r.previous || "New skill")}</p>` : ""}${changes ? `<h4>What changed</h4><p>Before: ${esc(changes.steps_before.join(" → ") || "Guidance / new package")}<br>After: ${esc(changes.steps_after.join(" → ") || "Guidance")}</p><p>Field labels: ${esc(changes.labels_before.join(", "))} → ${esc(changes.labels_after.join(", "))}</p><pre>${esc(changes.instructions_diff || "Instructions unchanged")}</pre><p>Supporting files changed: ${esc(changes.resources_changed.join(", ") || "None")}</p>` : ""}${checks ? `<h4>Runtime checks</h4><p>${esc(checks.suite)} · ${esc(checks.model_mode === "simulated" ? "Simulated behavioral checks" : "Contract checks; no model")}</p><ul>${checks.checks.map(c => `<li>${esc(c.case || `Amounts ${c.amount} / ${c.po_amount}; ${c.label}`)}: ${c.passed ? "passed" : "failed"}</li>`).join("")}</ul>${checks.behavioral_evaluation ? `<p>${esc(checks.behavioral_evaluation)}</p>` : ""}` : ""}${(r.recommendations || []).map(s => `<article class="learning-suggestion"><strong>Proposed ${esc(s.kind.replaceAll("_"," "))}</strong><p>${esc(s.reason)}</p><p>${esc(s.skill_ids.join(", "))}</p><p>Evidence: ${evidence(s.evidence_ids)}</p><small>This suggestion has not changed the active skills or permissions.</small></article>`).join("")}${r.input ? `<details><summary>Supporting observations and staff feedback</summary>${json({verification:r.input.verification,approved_actions:r.input.approved_actions,guidance:r.input.guidance,related:r.input.related})}</details>` : ""}${r.usage ? `<p class="hint">Learner usage: ${esc(r.usage.total_tokens || 0)} tokens · ${esc(r.prompt_version)}</p>` : ""}</details>`;
      }).join("") : "<p>No learning reviews yet.</p>") +
      `<details data-learning-id="history"><summary>Activation, suspension and rollback history</summary>${status.registries.flatMap(r => r.history || []).slice(-30).reverse().map(h => `<p>${esc(h.action.replaceAll("_"," "))} · ${esc(h.skill_id)} · ${esc(h.version?.slice(0,12) || "No active version")}</p>`).join("") || "<p>No changes yet.</p>"}</details>`;
    if (markup === previous) return;
    const scroll = container.scrollTop;
    container.innerHTML = markup;
    container.scrollTop = scroll;
    previous = markup;
    container.querySelectorAll("details[data-learning-id]").forEach(detail => {
      detail.open = opened.has(detail.dataset.learningId);
      detail.addEventListener("toggle", () => detail.open ? opened.add(detail.dataset.learningId) : opened.delete(detail.dataset.learningId));
    });
  }
  return {render};
})();
