"use strict";
// All data is rendered through textContent / createTextNode only.
const D = JSON.parse(document.getElementById("tuner-data").textContent);
const U = D.usage, A = D.analysis, S = D.skills || [];
const app = document.getElementById("app");

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k === "onclick") e.addEventListener("click", v);
    else if (v !== null && v !== undefined) e.setAttribute(k, String(v));
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined || k === false) continue;
    e.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return e;
}
const fmt = (n) => {
  n = Number(n || 0);
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
};
const money = (c) => !c ? "n/a" : (c.complete ? "" : "≥ ") + "$" + c.usd.toFixed(2);
const pct = (x) => (x * 100).toFixed(1) + "%";
const day = (s) => (s || "").slice(0, 10);
const pill = (text, cls) => h("span", { class: "pill " + (cls || "") }, text);
const qpill = (q) => pill(q.measurement + " · " + q.confidence, q.measurement);
const CATS = [["input_tokens", "input", "--c-in"], ["output_tokens", "output", "--c-out"],
  ["cache_write_tokens", "cache write", "--c-cw"], ["cache_read_tokens", "cache read", "--c-cr"]];

function bar(t) {
  const total = t.total || 1;
  return h("div", { class: "bar", title: CATS.map(([k, l]) => l + " " + fmt(t[k])).join(" · ") },
    CATS.map(([k, , c]) => h("i", { style: `width:${(t[k] / total) * 100}%;background:var(${c})` })));
}
const legend = () => h("div", { class: "legend" },
  CATS.map(([, l, c]) => h("span", {}, h("b", { style: `background:var(${c})` }), l)));
const stat = (v, l) => h("div", { class: "stat" }, h("div", { class: "v" }, v), h("div", { class: "l" }, l));
function table(head, rows) {
  return h("table", {}, h("thead", {}, h("tr", {}, head.map(([t, c]) => h("th", { class: c || "" }, t)))),
    h("tbody", {}, rows));
}

function overview() {
  const o = U.overview, p = U.period, q = o.quality;
  const el = h("div", {}, h("h1", {}, "Usage overview"),
    h("div", { class: "muted" }, `${day(p.start)} → ${day(p.end)} (${p.timezone}${p.partial ? ", in progress" : ""}) · generated ${U.generated_at}`),
    h("div", { class: "stats" },
      stat(fmt(o.tokens.total), "total tokens"),
      stat(money(o.cost), "est. API-equivalent cost"),
      stat(o.counts.agents, "agents"), stat(o.counts.sessions, "sessions"),
      stat(o.counts.tasks, "tasks"), stat(o.counts.repositories, "repositories")),
    h("div", {}, bar(o.tokens), legend()),
    h("p", {}, "Data quality: ", qpill(q), " ", `${fmt(q.measured_tokens)} measured, ${fmt(q.estimated_tokens)} estimated tokens.`));
  if (o.cost && !o.cost.complete) el.append(h("div", { class: "notice" }, "Cost is incomplete: some models have no known rate."));
  if (o.cost) el.append(h("p", { class: "muted" }, "Cost notes: " + (o.cost.limitations || []).join("; ") + "."));
  el.append(h("h2", {}, "By agent"), table([["Agent"], ["Tasks", "n"], ["Tokens", "n"], ["Quality"]],
    o.by_agent.map((a) => h("tr", {}, h("td", {}, a.agent), h("td", { class: "n" }, a.tasks),
      h("td", { class: "n" }, fmt(a.total)), h("td", {}, pill(a.measurement, a.measurement))))));
  el.append(h("h2", {}, "By model"), table([["Model"], ["Input", "n hide"], ["Output", "n hide"], ["Cache w", "n hide"], ["Cache r", "n hide"], ["Total", "n"], ["Quality"]],
    o.by_model.map((m) => h("tr", {}, h("td", {}, m.model || "unknown"),
      ...CATS.map(([k]) => h("td", { class: "n hide" }, fmt(m[k]))), h("td", { class: "n" }, fmt(m.total)),
      h("td", {}, pill(m.measurement, m.measurement))))));
  el.append(h("h2", {}, "Data quality and coverage"), quality());
  return el;
}

function quality() {
  const d = U.data_quality, r = d.reconciliation, el = h("div", {});
  d.coverage_gaps.forEach((g) => el.append(h("div", { class: "notice" }, g.message)));
  el.append(h("p", {}, "Reconciliation: ", pill(r.reconciled ? "task totals match session totals" : "unattributed usage present", r.reconciled ? "measured" : "mixed"), ` session total ${fmt(r.session_total)}, attributed ${fmt(r.attributed)}, unattributed ${fmt(r.unattributed)}, unlinked subagent sessions ${r.unlinked_subagent_sessions}.`));
  if (d.collection_errors.length) {
    el.append(h("h3", {}, "Collection issues"), h("ul", { class: "tight" },
      d.collection_errors.map((e) => h("li", {}, `${e.message} (${e.files} file${e.files === 1 ? "" : "s"})`))));
  }
  return el;
}

let topN = null;
function tasks() {
  topN = topN ?? Math.min(U.selection.top_n, U.tasks.length);
  const body = h("tbody", {});
  const ctl = h("div", { class: "ctl" }, "Show top ",
    h("input", { type: "number", min: 1, max: U.tasks.length, value: topN }), ` of ${U.tasks.length} detailed tasks`);
  const input = ctl.querySelector("input");
  const render = () => {
    body.replaceChildren(...U.tasks.slice(0, topN).map(taskRow));
  };
  input.addEventListener("input", () => {
    topN = Math.max(1, Math.min(U.tasks.length, parseInt(input.value || "1", 10)));
    render();
  });
  render();
  return h("div", {}, h("h1", {}, "Expensive tasks"),
    h("div", { class: "muted" }, "Ranked by total tokens. Estimated tokens are a relative effort proxy; compare across agents with care."),
    ctl, h("table", {}, h("thead", {}, h("tr", {}, ["#", "Task", "Agent / repo", "Model", "Tokens", "Total", "Cost", "Share", "Quality"]
      .map((t, i) => h("th", { class: i >= 5 && i < 8 ? "n" : (i === 3 ? "hide" : "") }, t)))), body), legend());
}
function taskRow(t) {
  const models = t.models.map((m) => m.model || "unknown").join(", ");
  return h("tr", { class: "click", onclick: () => { location.hash = "#/task/" + encodeURIComponent(t.id); } },
    h("td", {}, t.rank), h("td", {}, t.title, A && taskAnalysis(t.id) ? " " : "", A && taskAnalysis(t.id) ? pill("analyzed") : null),
    h("td", {}, t.agent, h("div", { class: "muted" }, t.repo || "")), h("td", { class: "hide mono" }, models),
    h("td", {}, bar(t.tokens)), h("td", { class: "n" }, fmt(t.tokens.total)),
    h("td", { class: "n" }, money(t.cost)), h("td", { class: "n" }, pct(t.share_of_total)), h("td", {}, qpill(t.quality)));
}

const taskAnalysis = (id) => A && (A.tasks || []).find((a) => a.task_id === id);
const list = (items) => h("ul", { class: "tight" }, (items || []).map((x) => h("li", {}, typeof x === "string" ? x : (x.claim || JSON.stringify(x)), x && x.evidence && x.evidence.length ? h("span", { class: "muted mono" }, "  [" + x.evidence.join(", ") + "]") : null)));

function task(id) {
  const t = U.tasks.find((x) => x.id === id);
  if (!t) return h("p", {}, "Task not found in this report.");
  const a = taskAnalysis(id), el = h("div", {},
    h("a", { class: "back", href: "#/tasks" }, "← Expensive tasks"), h("h1", {}, t.title),
    h("div", { class: "muted" }, `${t.agent} · ${t.repo || "unknown repo"} · ${t.models.map((m) => m.model || "unknown").join(", ")} · ${day(t.started_at) || "date approximate"} · outcome ${t.outcome}`),
    h("div", { class: "stats" }, stat(fmt(t.tokens.total), "tokens"), stat(money(t.cost), "est. cost"),
      stat(pct(t.share_of_total), "of period usage"), stat(t.tools.total, "tool calls"), stat(t.tools.failed, "failed calls"),
      stat(t.subagents.count, "subagents"), stat(t.compactions, "compactions")),
    h("div", {}, bar(t.tokens), legend()),
    h("p", {}, "Quality: ", qpill(t.quality), " ", t.quality.estimate_methods.join(", ")));
  if (t.quality.known_gaps.length) el.append(h("div", { class: "notice" }, "Known gaps in this estimate: " + t.quality.known_gaps.join(", ")));
  if (t.cost) el.append(h("p", { class: "muted" }, t.cost.limitations.join("; ") + "."));
  el.append(h("h2", {}, "Analysis"), a ? analysis(a) : h("p", { class: "muted" }, "Not analyzed yet. Run /tuner in Cursor or Claude Code, or `tuner analyze`."));
  el.append(h("h2", {}, "Subagents"), subagents(t));
  el.append(h("h2", {}, "Tool activity"), toolTable(t.tools));
  el.append(h("h2", {}, "Activity timeline"), timeline(t.timeline));
  el.append(h("h2", {}, "Sources"), h("ul", { class: "tight mono" }, t.sources.map((s) => h("li", {}, s.path))),
    h("p", { class: "muted" }, "Starts a workflow with one prompt. " + (t.grouping.continues
      ? `Likely continues an earlier task (${t.grouping.continues.rule.replace("_", " ")}, ${t.grouping.continues.gap_minutes == null ? "unknown" : Math.round(t.grouping.continues.gap_minutes)} min gap).` : "No earlier task linked.")));
  return el;
}
function analysis(a) {
  const c = a.classification || {};
  return h("div", { class: "panel" }, h("p", {}, h("strong", {}, "Objective: "), a.objective || "—"), h("p", {}, a.summary || ""),
    a.what_happened ? [h("h3", {}, "What happened"), list(a.what_happened)] : null,
    h("h3", {}, "Productive complexity"), list(c.productive_complexity),
    h("h3", {}, "Potentially avoidable overhead"), list(c.avoidable_overhead),
    h("h3", {}, "Insufficient evidence"), list(c.insufficient_evidence));
}
function subagents(t) {
  const s = t.subagents;
  if (!s.count) return h("p", { class: "muted" }, "No subagents were started by this task.");
  const rows = s.items.map((n) => h("tr", {}, h("td", {}, (n.type ? n.type + ": " : "") + (n.description || n.agent_ref || "subagent")),
    h("td", { class: "hide mono" }, n.models.join(", ")), h("td", { class: "n" }, fmt(n.tokens.total)),
    h("td", { class: "n" }, n.tools.total), h("td", { class: "n" }, n.tools.failed), h("td", {}, n.linked ? qpill(n.quality) : "not found")));
  return h("div", {}, h("p", { class: "muted" }, `${fmt(s.own_tokens)} tokens by the agent itself, ${fmt(s.tokens)} by ${s.count} subagent(s).`),
    table([["Subagent"], ["Model", "hide"], ["Tokens", "n"], ["Tools", "n"], ["Failed", "n"], ["Quality"]], rows),
    s.omitted ? h("p", { class: "muted" }, `${s.omitted} smaller subagent(s) not shown.`) : null);
}
function toolTable(t) {
  const rows = Object.entries(t.by_name).sort((x, y) => y[1].count - x[1].count).slice(0, 12)
    .map(([n, v]) => h("tr", {}, h("td", { class: "mono" }, n), h("td", { class: "n" }, v.count), h("td", { class: "n" }, v.failed)));
  const el = h("div", {}, table([["Tool"], ["Calls", "n"], ["Failed", "n"]], rows));
  if (t.unknown_status) el.append(h("p", { class: "muted" }, `${t.unknown_status} call(s) have unknown success status.`));
  if (t.repeated.length) el.append(h("h3", {}, "Repeated targets (3+ times)"), list(t.repeated.map((r) => `${r.tool} ×${r.count}: ${r.target}`)));
  return el;
}
function timeline(items) {
  return h("ul", { class: "tl" }, (items || []).map((i) => {
    if (i.kind === "gap") return h("li", { class: "gap" }, `… ${i.omitted} more events omitted …`);
    if (i.kind === "prompt") return h("li", { class: "prompt" }, "Prompt: " + i.text);
    if (i.kind === "system") return h("li", { class: "gap" }, "System message: " + i.text.replace("_", " "));
    if (i.kind === "tool") return h("li", { class: i.error ? "err" : "" }, `${i.name}${i.target ? " " : ""}`, h("span", { class: "mono" }, i.target || ""), i.error ? " — failed" : "");
    return h("li", {}, i.kind);
  }));
}

function recs() {
  const el = h("div", {}, h("h1", {}, "Recommendations"));
  const rs = (A && A.recommendations) || [];
  if (!A) return el.appendChild(h("p", { class: "muted" }, "No analysis for this report yet. Run /tuner in Cursor or Claude Code (or `tuner analyze`) to generate evidence-backed recommendations.")), el;
  if (!rs.length) el.append(h("p", {}, "The analysis found no change worth recommending."));
  rs.forEach((r) => el.append(h("div", { class: "panel" },
    h("strong", {}, r.title), " ", pill(r.kind), " ", pill(r.scope === "none" ? "no destination" : r.scope), " ", pill("confidence " + r.confidence), " ", pill(r.status || "proposed"),
    h("p", {}, r.description), h("p", {}, h("strong", {}, "Expected impact: "), r.expected_impact || "—"),
    h("p", {}, h("strong", {}, "Why it may help: "), r.why_it_helps || "—"), h("p", {}, h("strong", {}, "Proposed action: "), r.proposed_action || "—"),
    r.evidence && r.evidence.length ? [h("h3", {}, "Evidence"), list(r.evidence)] : null,
    r.destination ? h("p", { class: "muted mono" }, "Destination: " + r.destination) : null,
    r.change_id && r.status === "proposed" ? h("p", { class: "mono" }, "Apply: tuner skills apply " + r.change_id) : null,
    r.note ? h("p", { class: "muted" }, "Note: " + r.note) : null,
    r.diff ? [h("h3", {}, "Diff preview"), diffPre(r.diff)] : null)));
  (A.limitations || []).forEach((l) => el.append(h("p", { class: "muted" }, "Limitation: " + l)));
  return el;
}
function diffPre(text) {
  return h("pre", {}, text.split("\n").map((ln) => h("div", { class: ln.startsWith("+") ? "add" : ln.startsWith("-") ? "del" : "" }, ln || " ")));
}

function skills() {
  const el = h("div", {}, h("h1", {}, "Skill history"));
  if (!S.length) return el.appendChild(h("p", { class: "muted" }, "No skill proposals or changes recorded yet.")), el;
  el.append(table([["Date"], ["Skill"], ["Action"], ["Scope"], ["Status"], ["Effect"], ["Rollback"]], S.map((s) => h("tr", {},
    h("td", {}, day(s.created_at)), h("td", { class: "mono" }, s.skill_name), h("td", {}, s.action), h("td", {}, s.scope),
    h("td", {}, pill(s.status)), h("td", {}, s.effectiveness ? s.effectiveness.verdict + " — " + s.effectiveness.note : "not evaluated"),
    h("td", { class: "mono" }, s.status === "applied" ? "tuner skills rollback " + s.id : "—")))));
  return el;
}

const routes = { overview, tasks, recs, skills };
function route() {
  const parts = (location.hash || "#/overview").slice(2).split("/");
  const name = parts[0] in routes || parts[0] === "task" ? parts[0] : "overview";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === (name === "task" ? "tasks" : name)));
  app.replaceChildren(name === "task" ? task(decodeURIComponent(parts.slice(1).join("/"))) : routes[name]());
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
route();
