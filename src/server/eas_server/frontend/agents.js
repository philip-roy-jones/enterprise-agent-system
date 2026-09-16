/* Developer inventory and stable, linkable agent pages. */
const agentPages = {
  employeeId: location.pathname.startsWith("/agents/") ? decodeURIComponent(location.pathname.slice(8)) : null,
  view: location.pathname === "/metrics" ? "metrics" : location.pathname.startsWith("/agents/") ? "agent" : "directory",
  agent: null, directoryMarkup: "", detailsMarkup: "",
  state(employee) {
    return !employee.registered ? "Unregistered" : !employee.enabled ? "Disabled" : ({active:"Active", shadowing:"Shadowing", paused:"Paused"}[employee.state] || "Unknown");
  },
  init() {
    $("jobs-tab").classList.toggle("nav-active", this.view !== "metrics");
    $("metrics-tab").classList.toggle("nav-active", this.view === "metrics");
    $(this.view === "metrics" ? "metrics-tab" : "jobs-tab").setAttribute("aria-current", "page");
    $("agent-directory").hidden = this.view !== "directory";
    $("agent-back").hidden = this.view !== "agent";
    $("page-eyebrow").textContent = "DEVELOPER CONSOLE";
    $("page-title").textContent = this.view === "metrics" ? "Evaluation metrics" : this.view === "agent" ? "Agent" : "Agents";
    $("page-description").textContent = this.view === "directory" ? "Inspect registered edge agents and open their debug pages." : this.view === "metrics" ? "Compare simulated and live runs." : "";
    document.title = `Enterprise Agent System · ${$("page-title").textContent}`;
  },
  clear() {
    this.agent = null;
    this.directoryMarkup = this.detailsMarkup = "";
    $("agent-grid").replaceChildren();
    $("agent-details-content").replaceChildren();
    $("agent-details").hidden = true;
    $("agent-channels").replaceChildren();
    $("chat-composer").hidden = $("learning-panel").hidden = true;
    $("agent-unavailable").hidden = true;
    $("agent-conversation-unavailable").hidden = true;
    $("page-description").textContent = "";
    $("page-title").textContent = this.view === "agent" ? "Agent" : "Agents";
    document.title = "Enterprise Agent System · Developer console";
    resetConversation();
  },
  async load() {
    let data;
    try {
      data = await api(this.employeeId ? `/api/dev/agents/${encodeURIComponent(this.employeeId)}` : "/api/dev/agents");
    } catch (error) {
      this.clear();
      if (error.status === 403 || error.status === 404) {
        $("agent-directory").hidden = true;
        $("agent-unavailable").hidden = false;
        $("agent-unavailable-title").textContent = error.status === 403 ? "Developer access required" : "Agent not found";
        $("agent-unavailable-message").textContent = error.status === 403 ? "This console requires the agent inventory permission. It does not change staff access to conversations or controls." : "This agent is not in the registered inventory.";
        return false;
      }
      throw error;
    }
    $("agent-unavailable").hidden = true;
    if (!this.employeeId) {
      $("agent-directory").hidden = false;
      const markup = data.map(employee => {
        const state = this.state(employee);
        const departments = [...new Set(employee.profiles.map(p=>p.department_id))].join(" · ");
        const companies = [...new Set(employee.profiles.map(p=>p.company_id))].join(" · ");
        return `<a class="agent-card" href="/agents/${encodeURIComponent(employee.id)}"><div class="agent-card-top"><span class="agent-icon" aria-hidden="true">◫</span><span class="agent-state ${state.toLowerCase()}">${esc(state)}</span></div><h2>${esc(employee.name)}</h2><p class="agent-id">${esc(employee.id)}</p><p class="agent-departments">${esc(departments || "No registered scope")}${companies ? ` <span class="muted">/ ${esc(companies)}</span>` : ""}</p><span class="agent-card-link">Open debug page <span aria-hidden="true">↗</span></span></a>`;
      }).join("");
      if (markup !== this.directoryMarkup) { $("agent-grid").innerHTML = markup; this.directoryMarkup = markup; }
      $("agent-count").textContent = `${data.length} ${data.length === 1 ? "agent" : "agents"}`;
      $("no-agents").hidden = data.length > 0;
      return false;
    }
    this.agent = data;
    $("page-title").textContent = data.name;
    $("page-description").textContent = `${data.id} · ${this.state(data)}`;
    document.title = `${data.name} · Enterprise Agent System`;
    $("agent-details").hidden = false;
    const markup = `<dl class="agent-facts"><div><dt>Agent ID</dt><dd>${esc(data.id)}</dd></div><div><dt>Lifecycle</dt><dd>${esc(this.state(data))}</dd></div><div><dt>Policy revision</dt><dd>${esc(data.revision)}</dd></div></dl><h3>Service identities</h3><ul class="agent-services">${data.services.map(s=>`<li><strong>${esc(s.kind)}</strong><span>${esc(s.id)}</span><span class="muted">${s.enabled ? "Enabled" : "Disabled"}</span></li>`).join("") || "<li>No registered service identities.</li>"}</ul><h3>Registered scopes</h3><ul class="agent-scopes">${data.profiles.map(p=>`<li><strong>${esc(p.department_id)} / ${esc(p.role_id)}</strong><span>${esc(p.organization_id)} · ${esc(p.company_id)} · ${esc(p.capabilities.join(", ") || "No capabilities")}</span></li>`).join("") || "<li>No registered scope.</li>"}</ul>`;
    if (markup !== this.detailsMarkup) { $("agent-details-content").innerHTML = markup; this.detailsMarkup = markup; }
    return true;
  },
  channels(choices) {
    const links = choices.filter(c=>c.channel_id).map(c=>`<a class="agent-channel" href="https://discord.com/channels/${encodeURIComponent(c.communication.guild_id)}/${encodeURIComponent(c.channel_id)}" target="_blank" rel="noopener noreferrer">#${esc(c.name)} <span aria-hidden="true">↗</span></a>`).join("");
    $("agent-channels").innerHTML = links;
    $("agent-channels").hidden = !links;
  },
};
