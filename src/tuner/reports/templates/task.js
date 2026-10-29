// Task detail page. Declarations and constants only: concatenated
// before report.js, whose helpers (h, fmt, pill, ...) exist by first call.

function taskAnalysis(id) {
  return A && (A.tasks || []).find((a) => a.task_id === id);
}

function evidence(x) {
  const ev = x && x.evidence;
  return ev && ev.length ? h("span", { class: "evs" }, ev.map((e) => h("span", { class: "ev" }, e))) : null;
}
function list(items) {
  return h("ul", { class: "tight" }, (items || []).map((x) =>
    h("li", {}, typeof x === "string" ? x : (x.claim || JSON.stringify(x)), " ", evidence(x))));
}

function task(id) {
  const t = U.tasks.find((x) => x.id === id);
  if (!t) return h("p", {}, "Task not found in this report.");
  const a = taskAnalysis(id), q = t.quality;
  const models = [...new Set(t.models.map((m) => m.model || "unknown"))].join(", ");
  const notes = [q.estimate_methods.length ? "Sources: " + q.estimate_methods.join(", ") : "",
    q.known_gaps.length ? "Known gaps: " + q.known_gaps.join(", ") : "",
    t.cost ? t.cost.limitations.join("; ") : ""].filter(Boolean);
  const failed = t.tools.failed ? ` · ${t.tools.failed} failed` : "";
  const el = h("div", {}, h("a", { class: "back", href: "#/tasks" }, "← Expensive tasks"),
    h("h1", { title: t.title }, cleanTitle(t.title, 90)),
    h("div", { class: "sub" }, [t.agent, t.repo || "unknown repo", models,
      day(t.started_at) || "date approximate"].join(" · "), pill("outcome " + t.outcome),
      t.grouping.continues ? pill("continues earlier task") : null),
    h("div", { class: "stats" }, stat(fmt(t.tokens.total), "tokens"), stat(money(t.cost), "est. cost"),
      stat(pct(t.share_of_total), "of period"), stat(t.tools.total, "tool calls" + failed),
      stat(t.subagents.count, "subagents"), stat(t.compactions, "compactions")),
    h("div", {}, bar(t.tokens), legend(t.tokens)),
    h("div", { class: "qline" }, qpill(q)),
    notes.length ? fold("Estimate notes", h("ul", { class: "tight" }, notes.map((n) => h("li", {}, n)))) : null);
  el.append(h("h2", {}, "Prompts"), promptList(t));
  el.append(h("h2", {}, "Analysis"), a ? analysis(a)
    : h("p", { class: "muted" }, "Not analyzed yet. Run /tuner in Cursor or Claude Code, or `tuner analyze`."));
  if (t.subagents.count) el.append(h("h2", {}, "Subagents"), subagents(t));
  el.append(h("h2", {}, "Tool activity"), toolTable(t.tools));
  el.append(fold(`Activity timeline (${(t.timeline || []).length} events)`, timeline(t.timeline)),
    fold(`Sources (${t.sources.length})`, h("ul", { class: "tight mono" },
      t.sources.map((s) => h("li", {}, s.path)))));
  return el;
}

function analysis(a) {
  const c = a.classification || {};
  const col = (cls, title, items) => h("div", { class: "col " + cls }, h("h3", {}, title),
    items && items.length ? list(items) : h("p", { class: "muted" }, "None"));
  return h("div", { class: "card" },
    h("p", { class: "lead" }, a.objective || "—"), a.summary ? h("p", { class: "muted" }, a.summary) : null,
    a.what_happened && a.what_happened.length ? [h("h3", {}, "What happened"), list(a.what_happened)] : null,
    h("div", { class: "cols" }, col("ok", "Productive", c.productive_complexity),
      col("warn", "Avoidable overhead", c.avoidable_overhead),
      col("dim", "Unclear", c.insufficient_evidence)));
}

function subagents(t) {
  const s = t.subagents;
  const rows = s.items.map((n) => h("tr", {},
    h("td", {}, (n.type ? n.type + ": " : "") + (n.description || n.agent_ref || "subagent")),
    h("td", { class: "hide mono" }, n.models.join(", ")), h("td", { class: "n" }, fmt(n.tokens.total)),
    h("td", { class: "n" }, n.tools.total), h("td", { class: "n" }, n.tools.failed),
    h("td", {}, n.linked ? qpill(n.quality) : "not found")));
  return h("div", {}, h("p", { class: "muted" },
    `${fmt(s.own_tokens)} by the agent itself, ${fmt(s.tokens)} by ${s.count} subagent(s).`),
    table([["Subagent"], ["Model", "hide"], ["Tokens", "n"], ["Tools", "n"], ["Failed", "n"], ["Quality"]], rows),
    s.omitted ? h("p", { class: "muted" }, `${s.omitted} smaller subagent(s) not shown.`) : null);
}

function toolTable(t) {
  const rows = Object.entries(t.by_name).sort((x, y) => y[1].count - x[1].count).slice(0, 12)
    .map(([n, v]) => h("tr", {}, h("td", { class: "mono" }, n), h("td", { class: "n" }, v.count),
      h("td", { class: "n" }, v.failed || "")));
  const el = h("div", {}, table([["Tool"], ["Calls", "n"], ["Failed", "n"]], rows));
  if (t.unknown_status) el.append(h("p", { class: "muted" }, `${t.unknown_status} call(s) have unknown status.`));
  if (t.repeated.length) {
    el.append(h("h3", {}, "Repeated targets (3+ times)"),
      list(t.repeated.map((r) => `${r.tool} ×${r.count}: ${r.target}`)));
  }
  return el;
}

// Prompt text is clipped in the middle by the collector with this marker.
const OMITTED = /\n\[\.\.\. (\d+) chars omitted \.\.\.\]\n/;
function promptMd(body) {
  const parts = body.split(OMITTED);
  if (parts.length < 3) return renderMd(body);
  return h("div", {}, renderMd(parts[0]), h("div", { class: "omit" }, `${parts[1]} characters omitted`),
    renderMd(parts[2]));
}
function promptCard(p, n, total) {
  const body = p.full || p.text || "";
  const long = body.length > 700 || body.split("\n").length > 16;
  const view = h("div", { class: "pbody" + (long ? " clamp" : "") });
  let raw = false;
  const draw = () => view.replaceChildren(raw ? h("pre", {}, body) : promptMd(body));
  const rawBtn = h("button", { class: "btn", onclick: () => {
    raw = !raw; rawBtn.textContent = raw ? "Formatted" : "Raw"; draw();
  } }, "Raw");
  const more = h("button", { class: "btn", onclick: () => {
    const open = view.classList.toggle("clamp");
    more.textContent = open ? "Show all" : "Show less";
  } }, "Show all");
  draw();
  const head = cleanTitle(body.split("\n").find((l) => l.trim()) || "", 100) || "(empty)";
  return h("details", { class: "prompt", open: n === 0 },
    h("summary", {}, total > 1 ? h("span", { class: "pn" }, "Prompt " + (n + 1)) : null, head),
    h("div", { class: "ptools" }, h("span", { class: "muted" }, fmt(body.length) + " chars"),
      h("span", { class: "grow" }), rawBtn, long ? more : null), view);
}
function promptList(t) {
  const ps = (t.timeline || []).filter((i) => i.kind === "prompt");
  if (!ps.length) return h("p", { class: "muted" }, "No prompt text for this task.");
  return h("div", {}, ps.map((p, n) => promptCard(p, n, ps.length)));
}

function timeline(items) {
  return h("ul", { class: "tl" }, (items || []).map((i) => {
    if (i.kind === "gap") return h("li", { class: "gap" }, `… ${i.omitted} more events omitted …`);
    if (i.kind === "prompt") return h("li", { class: "prompt" }, "Prompt: " + i.text);
    if (i.kind === "system") return h("li", { class: "gap" }, "System message: " + i.text.replace("_", " "));
    if (i.kind === "tool") {
      return h("li", { class: i.error ? "err" : "" }, i.name + (i.target ? " " : ""),
        h("span", { class: "mono" }, i.target || ""), i.error ? " — failed" : "");
    }
    return h("li", {}, i.kind);
  }));
}
