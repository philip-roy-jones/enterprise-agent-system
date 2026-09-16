/* Employee lifecycle and mentoring use the same conversation surface. */
const workforceView = {
  employees: [], choices: [], demo: null, markup: "",
  scope() {
    return this.choices.find(choice => choice.key === $("chat-workspace").value);
  },
  async refresh() {
    this.employees = (await api("/api/employees")).filter(e => e.id === agentPages.employeeId);
    this.choices = this.employees.flatMap(employee => employee.profiles.map(profile => ({
      key: `${employee.id}/${profile.role_id}/${profile.company_id}`,
      employee, ...profile, employee_id: employee.id,
    })));
    const channels = await api("/api/channels");
    this.choices.push(...channels.flatMap(channel => {
      const employee = this.employees.find(e => e.id === channel.employee_id);
      return employee ? [{...channel, employee, key:`discord/${channel.channel_id}`}]: [];
    }));
    const options = this.choices.map(c => `<option value="${esc(c.key)}">${esc(c.channel_id ? "#"+c.name+" · Discord" : "Private chat · "+c.department_id+" · "+c.company_id)}</option>`).join("");
    if (options !== this.markup) {
      const previous = $("chat-workspace").value || new URLSearchParams(location.search).get("conversation");
      $("chat-workspace").innerHTML = options;
      if (this.choices.some(c => c.key === previous)) $("chat-workspace").value = previous;
      this.markup = options;
    }
    $("conversation-picker").hidden = this.choices.length < 2;
    agentPages.channels(this.choices);
    const selected = this.scope();
    $("employee-management").hidden = !selected?.employee.can_supervise;
    $("employee-status").textContent = selected ? `${selected.employee.state} · ${selected.employee.state === "active" ? "Works autonomously within assigned permissions" : selected.employee.state === "shadowing" ? "Observes only during a demonstration you start" : "Execution and observation stopped"}` : "No authorized digital employees";
    $("chat-request").disabled = !!selected?.channel_id && selected.employee.state !== "shadowing" || !selected || selected.employee.state === "paused" || (selected.employee.state === "shadowing" && !selected.employee.can_supervise);
    document.querySelector("#chat-form button").disabled = $("chat-request").disabled;
    this.demo = selected?.employee.can_supervise ? await api(`/api/employees/${encodeURIComponent(selected.employee_id)}/demonstration`) : null;
    if (selected?.channel_id && this.demo?.job.conversation_id !== selected.conversation_id) this.demo = null;
    $("finish-demonstration").hidden = selected?.employee.state !== "shadowing" || this.demo?.job.status !== "shadowing";
    return selected;
  },
  render() {
    const c = this.scope();
    if (!c || c.employee.state === "active") return false;
    selectRequest(null);
    $("chat-controls").hidden = true;
    $("earlier-messages").hidden = true;
    const demo = this.demo;
    let markup = "";
    if (demo) {
      markup = demo.events.map(event => {
        const data = event.data;
        let text = "", who = c.employee.name, staff = false;
        if (event.kind === "shadow_started") { text = data.task; who = "Mentor"; staff = true; }
        if (event.kind === "mentor_message" || event.kind === "mentor_outcome") { text = data.text; who = "Mentor"; staff = true; }
        if (event.kind === "shadow_notes") { text = [data.observation, data.question].filter(Boolean).join("\n\n"); who = c.employee.name + (data.model_mode === "simulated" ? " · simulated observer" : ""); }
        if (event.kind === "shadow_unavailable") { text = data.message; who = "Observation status"; }
        if (text) return `<article class="session-message ${staff ? "staff" : "assistant"}"><strong>${esc(who)}</strong><div class="message-text">${esc(text).replaceAll("\n", "<br>")}</div></article>`;
        if (chatDebug && event.kind === "shadow_observation") return `<details class="activity-event"><summary>Desktop sample · ${new Date(event.at*1000).toLocaleTimeString()}</summary>${data.screenshot ? `<img class="shadow-sample" src="/api/artifacts/${encodeURIComponent(data.screenshot)}" alt="Sampled mentor desktop" loading="lazy">` : ""}<pre>${esc(JSON.stringify(data.state, null, 2))}</pre></details>`;
        return "";
      }).join("");
    }
    const node = $("session-messages");
    if (node.dataset.shadowMarkup !== markup) {
      const bottom = node.scrollHeight-node.scrollTop-node.clientHeight < 80;
      node.innerHTML = markup;
      node.dataset.shadowMarkup = markup;
      if (bottom) node.scrollTop = node.scrollHeight;
    }
    $("chat-request").placeholder = demo?.job.status === "shadowing" ? "Explain what you're doing or answer the employee's question…" : "Describe the task to demonstrate on this employee's desktop…";
    document.querySelector("#chat-form button").textContent = demo?.job.status === "shadowing" ? "Send" : "Start demonstration";
    $("conversation-label").textContent = demo?.job.status === "shadowing" ? `Observing desktop · ${demo.job.shadow_frames}/180 samples · ${demo.job.shadow_reviews}/12 model observations` : demo?.job.status === "completed" ? "Demonstration ended. Guidance is reviewed in the background; the employee remains in shadowing." : "Starting shares sampled desktop screenshots with the observer model for up to 30 minutes. No clicks or typing by the employee.";
    return true;
  },
  async send(task) {
    const c = this.scope();
    if (!c || c.employee.state === "paused") throw Error("Select an available digital employee");
    if (c.employee.state !== "shadowing") return false;
    if (this.demo?.job.status === "shadowing") await api(`/api/demonstrations/${this.demo.job.id}/messages`, {text:task});
    else await api(`/api/employees/${encodeURIComponent(c.employee_id)}/demonstrations`, {role_id:c.role_id, company_id:c.company_id, channel_id:c.channel_id || null, task});
    return true;
  },
};
