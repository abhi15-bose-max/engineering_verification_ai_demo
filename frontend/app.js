const API = "/api";

const state = {
  models: [],
  domains: [],
  selectedModels: new Set(),
  selectedDomain: null,
  activeRunIds: {},   // model_id -> run_id
  pollTimer: null,
};

const el = (id) => document.getElementById(id);

// ---------- Boot ----------

async function boot() {
  const [modelsRes, domainsRes] = await Promise.all([
    fetch(`${API}/models`).then((r) => r.json()),
    fetch(`${API}/domains`).then((r) => r.json()),
  ]);
  state.models = modelsRes.models;
  state.domains = domainsRes.domains;
  renderModelChips();
  renderDomainChips();
  wireStaticControls();
}

function renderModelChips() {
  const row = el("model-chips");
  row.innerHTML = "";
  state.models.forEach((m) => {
    const chip = document.createElement("button");
    chip.className = "chip" + (m.available ? "" : " chip-disabled");
    chip.type = "button";
    chip.textContent = m.name;
    if (!m.available) {
      const note = document.createElement("span");
      note.className = "chip-note";
      note.textContent = "no key";
      chip.appendChild(note);
      chip.disabled = true;
    } else {
      chip.addEventListener("click", () => toggleModel(m.id, chip));
    }
    chip.dataset.modelId = m.id;
    row.appendChild(chip);
  });
}

function toggleModel(modelId, chipEl) {
  if (state.selectedModels.has(modelId)) {
    state.selectedModels.delete(modelId);
    chipEl.classList.remove("selected");
  } else {
    if (state.selectedModels.size >= 2) return; // demo supports up to 2 for comparison
    state.selectedModels.add(modelId);
    chipEl.classList.add("selected");
  }
}

function renderDomainChips() {
  const row = el("domain-chips");
  row.innerHTML = "";
  state.domains.forEach((d) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.type = "button";
    chip.textContent = domainLabel(d.id);
    chip.dataset.domainId = d.id;
    chip.addEventListener("click", () => selectDomain(d.id, chip));
    row.appendChild(chip);
  });
}

function domainLabel(id) {
  return { rtl: "RTL Engineering", ode: "Differential Equation", logic: "Formal Logic" }[id] || id;
}

function selectDomain(domainId, chipEl) {
  state.selectedDomain = domainId;
  document.querySelectorAll("#domain-chips .chip").forEach((c) => c.classList.remove("selected"));
  chipEl.classList.add("selected");
  const domain = state.domains.find((d) => d.id === domainId);
  el("verifier-readout").innerHTML =
    `<span class="verifier-domain">${domainLabel(domainId)}</span> resolves to <strong>${domain.verifier}</strong>`;
}

function wireStaticControls() {
  el("load-example-btn").addEventListener("click", () => {
    if (!state.selectedDomain) {
      showSetupError("Choose a domain first, then load its example.");
      return;
    }
    const domain = state.domains.find((d) => d.id === state.selectedDomain);
    el("task-input").value = domain.example_task;
  });

  el("run-btn").addEventListener("click", startRun);
  el("new-run-btn").addEventListener("click", resetToSetup);
  el("new-run-btn-2").addEventListener("click", resetToSetup);
}

function showSetupError(message) {
  const box = el("setup-error");
  box.textContent = message;
  box.hidden = false;
}

function hideSetupError() {
  el("setup-error").hidden = true;
}

// ---------- Run lifecycle ----------

async function startRun() {
  hideSetupError();
  const task = el("task-input").value.trim();
  const maxAttempts = parseInt(el("max-attempts").value, 10);

  if (state.selectedModels.size === 0) return showSetupError("Select at least one model.");
  if (!state.selectedDomain) return showSetupError("Select an engineering domain.");
  if (!task) return showSetupError("Enter a task or specification.");

  el("run-btn").disabled = true;
  const modelIds = [...state.selectedModels];

  try {
    const runIds = {};
    for (const modelId of modelIds) {
      const res = await fetch(`${API}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain: state.selectedDomain, model: modelId, task, max_attempts: maxAttempts }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Failed to start run.");
      runIds[modelId] = body.run_id;
    }
    state.activeRunIds = runIds;
    showPipelineView(modelIds);
    pollRuns(modelIds);
  } catch (err) {
    showSetupError(err.message);
    el("run-btn").disabled = false;
  }
}

function showPipelineView(modelIds) {
  el("setup-view").hidden = true;
  el("result-view").hidden = true;
  el("pipeline-view").hidden = false;
  el("pipeline-title").textContent =
    modelIds.length > 1 ? "Running on both models…" : "Running…";

  const columns = el("pipeline-columns");
  columns.innerHTML = "";
  STAGES.forEach((s) => {
    const div = document.createElement("div");
    div.className = "stage";
    div.dataset.stage = s.key;
    div.innerHTML = `<div class="stage-label">${s.label}</div>`;
    columns.appendChild(div);
  });

  const log = document.createElement("div");
  log.className = "attempt-log";
  log.id = "attempt-log";
  el("pipeline-view").appendChild(log);
}

const STAGES = [
  { key: "generate", label: "Generate" },
  { key: "verify", label: "Verify" },
  { key: "diagnose", label: "Diagnose" },
  { key: "repair", label: "Repair" },
  { key: "re-verify", label: "Re-verify" },
];

function setStage(activeKey, status) {
  document.querySelectorAll("#pipeline-columns .stage").forEach((node) => {
    node.classList.remove("active", "done", "failed");
    const idx = STAGES.findIndex((s) => s.key === node.dataset.stage);
    const activeIdx = STAGES.findIndex((s) => s.key === activeKey);
    if (idx < activeIdx) node.classList.add("done");
    if (idx === activeIdx) {
      node.classList.add(status === "failed" ? "failed" : "active");
    }
  });
}

function logLine(text) {
  const log = el("attempt-log");
  if (!log) return;
  const line = document.createElement("div");
  line.textContent = text;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function pollRuns(modelIds) {
  clearInterval(state.pollTimer);
  const seenEvents = {};
  modelIds.forEach((m) => (seenEvents[m] = 0));

  state.pollTimer = setInterval(async () => {
    let allDone = true;
    for (const modelId of modelIds) {
      const runId = state.activeRunIds[modelId];
      const info = await fetch(`${API}/runs/${runId}`).then((r) => r.json());

      const events = info.events || [];
      for (let i = seenEvents[modelId]; i < events.length; i++) {
        describeEvent(modelId, events[i]);
      }
      seenEvents[modelId] = events.length;

      if (info.status !== "done" && info.status !== "error") allDone = false;
    }
    if (allDone) {
      clearInterval(state.pollTimer);
      await showResults(modelIds);
    }
  }, 900);
}

function describeEvent(modelId, event) {
  const prefix = state.activeRunIds && Object.keys(state.activeRunIds).length > 1 ? `[${modelLabel(modelId)}] ` : "";
  if (event.type === "stage") {
    setStage(event.stage, "active");
    logLine(`${prefix}attempt ${event.attempt} — ${event.stage}`);
  } else if (event.type === "verification_result") {
    logLine(`${prefix}attempt ${event.attempt} — verification: ${event.status}${event.failure_class ? " (" + event.failure_class + ")" : ""}`);
  } else if (event.type === "final") {
    logLine(`${prefix}final status: ${event.status} after ${event.attempts} attempt(s)`);
  } else if (event.type === "error") {
    logLine(`${prefix}error: ${event.message}`);
  }
}

function modelLabel(modelId) {
  const m = state.models.find((x) => x.id === modelId);
  return m ? m.name : modelId;
}

// ---------- Results ----------

async function showResults(modelIds) {
  const trajectories = {};
  for (const modelId of modelIds) {
    const runId = state.activeRunIds[modelId];
    trajectories[modelId] = await fetch(`${API}/runs/${runId}/trajectory`).then((r) => r.json());
  }

  el("pipeline-view").hidden = true;
  el("result-view").hidden = false;
  el("run-btn").disabled = false;

  const anyVerified = modelIds.some((m) => trajectories[m].final_status === "VERIFIED");
  const allVerified = modelIds.every((m) => trajectories[m].final_status === "VERIFIED");
  const badge = el("status-badge");
  badge.className = "status-badge " + (allVerified ? "pass" : anyVerified ? "pass" : "fail");
  badge.textContent = allVerified ? "VERIFIED" : anyVerified ? "PARTIALLY VERIFIED" : "NOT VERIFIED";

  const columns = el("result-columns");
  columns.className = "result-columns" + (modelIds.length > 1 ? " two-up" : "");
  columns.innerHTML = "";
  modelIds.forEach((modelId) => columns.appendChild(renderResultCard(modelId, trajectories[modelId])));

  const compareBlock = el("comparison-block");
  if (modelIds.length > 1) {
    const runIdParam = modelIds.map((m) => state.activeRunIds[m]).join(",");
    const cmp = await fetch(`${API}/compare?run_ids=${runIdParam}`).then((r) => r.json());
    renderComparisonTable(cmp.rows, modelIds);
    compareBlock.hidden = false;
  } else {
    compareBlock.hidden = true;
  }
}

function renderResultCard(modelId, trajectory) {
  const wrap = document.createElement("div");

  const header = document.createElement("div");
  header.className = "result-card-header";
  header.style.background = "transparent";
  header.style.border = "none";
  header.style.padding = "0 0 12px 0";
  header.innerHTML = `<span>${modelLabel(modelId)}</span><span style="color:${trajectory.final_status === "VERIFIED" ? "var(--pass)" : "var(--fail)"}">${trajectory.final_status}</span>`;
  wrap.appendChild(header);

  const div1 = document.createElement("div");
  div1.className = "section-title";
  div1.textContent = "Final artifact";
  wrap.appendChild(div1);

  const artifactCard = document.createElement("div");
  artifactCard.className = "result-card";
  const pre = document.createElement("pre");
  pre.className = "code-block";
  pre.textContent = trajectory.final_candidate || trajectory.error || "(no artifact produced)";
  artifactCard.appendChild(pre);
  wrap.appendChild(artifactCard);

  const div2 = document.createElement("div");
  div2.className = "section-title";
  div2.textContent = "Verification evidence";
  wrap.appendChild(div2);

  const lastAttempt = trajectory.attempts[trajectory.attempts.length - 1];
  wrap.appendChild(renderEvidence(trajectory.domain, lastAttempt ? lastAttempt.verification : null));

  const div3 = document.createElement("div");
  div3.className = "section-title";
  div3.textContent = "Trajectory";
  wrap.appendChild(div3);
  wrap.appendChild(renderTrajectory(trajectory));

  return wrap;
}

function renderEvidence(domain, verification) {
  const card = document.createElement("div");
  card.className = "result-card";
  const list = document.createElement("div");
  list.className = "evidence-list";
  if (!verification) {
    list.textContent = "No verification data.";
    card.appendChild(list);
    return card;
  }

  const rows = [];
  const ev = verification.evidence || {};

  if (domain === "rtl") {
    rows.push(["Verilator", ev.verilator ? "PASS" : (verification.failure_class ? "FAIL" : "—")]);
    if (ev.synthesis) {
      rows.push(["Yosys", ev.synthesis.status || "PASS"]);
      if (ev.synthesis.top_module) rows.push(["Top module", ev.synthesis.top_module]);
      const stats = ev.synthesis.statistics || {};
      if (stats.cells != null) rows.push(["Cells", stats.cells]);
      if (stats.wires != null) rows.push(["Wires", stats.wires]);
    } else if (ev.failed_stage) {
      rows.push(["Failed stage", ev.failed_stage]);
    }
  } else if (domain === "ode") {
    rows.push(["Equation residual", ev.equation_residual ?? "—"]);
    (ev.condition_checks || []).forEach((c) => rows.push([c.condition, c.status]));
    if (ev.domain_issues && ev.domain_issues.length) rows.push(["Domain issues", ev.domain_issues.join("; ")]);
  } else if (domain === "logic") {
    rows.push(["Result", ev.result || "—"]);
    if (ev.assignment) rows.push(["Assignment", JSON.stringify(ev.assignment)]);
    if (ev.witness) rows.push(["Witness", JSON.stringify(ev.witness)]);
  }

  if (verification.status !== "PASS") {
    rows.push(["Failure class", verification.failure_class || "unknown"]);
  }

  if (!rows.length) {
    list.textContent = "No structured evidence returned.";
  } else {
    rows.forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "evidence-row";
      const isPass = String(v).toUpperCase() === "PASS";
      const isFail = String(v).toUpperCase() === "FAIL";
      row.innerHTML = `<span class="evidence-key">${k}</span><span class="evidence-val ${isPass ? "pass" : isFail ? "fail" : ""}">${escapeHtml(String(v))}</span>`;
      list.appendChild(row);
    });
  }
  card.appendChild(list);
  return card;
}

function renderTrajectory(trajectory) {
  const wrap = document.createElement("div");
  wrap.className = "trajectory";
  trajectory.attempts.forEach((attempt) => {
    const item = document.createElement("div");
    item.className = "trajectory-item";
    const passed = attempt.verification.status === "PASS";

    const header = document.createElement("div");
    header.className = "trajectory-item-header";
    header.innerHTML = `
      <span class="trajectory-dot ${passed ? "pass" : "fail"}"></span>
      <span class="trajectory-item-title">Attempt ${attempt.attempt_id}</span>
      <span class="trajectory-item-sub">${passed ? "verified" : (attempt.verification.failure_class || "failed")}</span>
    `;
    header.addEventListener("click", () => item.classList.toggle("expanded"));
    item.appendChild(header);

    const body = document.createElement("div");
    body.className = "trajectory-item-body";
    body.innerHTML = `
      <h4>Candidate</h4>
      <pre class="code-block" style="border-radius:6px;">${escapeHtml(attempt.candidate || "")}</pre>
      <h4>Verifier diagnostics</h4>
      <pre class="code-block" style="border-radius:6px;">${escapeHtml(attempt.verification.diagnostics || "(none)")}</pre>
      ${attempt.repair_feedback ? `<h4>Repair feedback used</h4><pre class="code-block" style="border-radius:6px;">${escapeHtml(attempt.repair_feedback)}</pre>` : ""}
    `;
    item.appendChild(body);
    wrap.appendChild(item);
  });
  return wrap;
}

function renderComparisonTable(rows, modelIds) {
  const table = el("compare-table");
  const cols = rows.map((_, i) => modelLabel(modelIds[i]));
  const metricRows = [
    ["Final result", (r) => (r.final_success ? '<span class="yes">✓</span>' : '<span class="no">✕</span>')],
    ["First pass", (r) => (r.first_pass_success ? '<span class="yes">✓</span>' : '<span class="no">✕</span>')],
    ["Attempts", (r) => r.attempts],
    ["Repair success", (r) => (r.repair_success ? '<span class="yes">✓</span>' : "—")],
    ["Latency (ms)", (r) => r.total_latency_ms],
  ];
  let html = `<tr><th></th>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  metricRows.forEach(([label, fn]) => {
    html += `<tr><td>${label}</td>${rows.map((r) => `<td class="center">${fn(r)}</td>`).join("")}</tr>`;
  });
  table.innerHTML = html;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function resetToSetup() {
  clearInterval(state.pollTimer);
  el("result-view").hidden = true;
  el("pipeline-view").hidden = true;
  el("setup-view").hidden = false;
  el("run-btn").disabled = false;
}

boot();
