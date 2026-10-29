// All data is rendered through text nodes only (see `h`); never innerHTML.
const D = JSON.parse(document.getElementById("tuner-data").textContent);
const U = D.usage, A = D.analysis, S = D.skills || [];
const app = document.getElementById("app");

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k === "onclick") e.addEventListener("click", v);
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const k of kids.flat(Infinity)) {
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
// Task titles are raw prompt text: drop markdown marks, cut at a word.
function cleanTitle(s, n = 80) {
  s = String(s || "").replace(/^[\s#>*\-`]+/, "").replace(/[*`]/g, "").replace(/\s+/g, " ").trim();
  if (s.length <= n) return s || "Untitled task";
  return s.slice(0, n).replace(/\s+\S*$/, "") + "…";
}
const pill = (text, cls) => h("span", { class: "pill " + (cls || "") }, text);
const qpill = (q) => pill(q.measurement + " · " + q.confidence, q.measurement);
const CATS = [["input_tokens", "input", "--c-in"], ["output_tokens", "output", "--c-out"],
  ["cache_write_tokens", "cache write", "--c-cw"], ["cache_read_tokens", "cache read", "--c-cr"]];

function bar(t) {
  const total = t.total || 1;
  return h("div", { class: "bar", title: CATS.map(([k, l]) => l + " " + fmt(t[k])).join(" · ") },
    CATS.map(([k, , c]) => h("i", { style: `width:${(t[k] / total) * 100}%;background:var(${c})` })));
}
// Legend; with token totals it also shows each category's size.
const legend = (t) => h("div", { class: "legend" }, CATS.map(([k, l, c]) =>
  h("span", {}, h("b", { style: `background:var(${c})` }), l, t ? h("em", {}, fmt(t[k])) : null)));
const stat = (v, l) => h("div", { class: "stat" }, h("div", { class: "v" }, v), h("div", { class: "l" }, l));
function table(head, rows) {
  return h("div", { class: "tbl" }, h("table", {},
    h("thead", {}, h("tr", {}, head.map(([t, c]) => h("th", { class: c || "" }, t)))), h("tbody", {}, rows)));
}
// Collapsed-by-default section for secondary detail.
const fold = (title, ...body) => h("details", { class: "fold" }, h("summary", {}, title), h("div", {}, body));

function overview() {
  const o = U.overview, p = U.period, q = o.quality;
  const el = h("div", {}, h("h1", {}, "Usage overview"),
    h("div", { class: "sub" }, `${day(p.start)} → ${day(p.end)}`, p.partial ? pill("in progress") : null,
      h("span", { class: "muted", title: p.timezone }, "generated " + U.generated_at.slice(0, 16).replace("T", " ") + " UTC")),
    h("div", { class: "stats" },
      stat(fmt(o.tokens.total), "total tokens"), stat(money(o.cost), "est. API-equivalent cost"),
      stat(o.counts.tasks, "tasks"), stat(o.counts.sessions, "sessions"), stat(o.counts.repositories, "repositories")),
    h("div", {}, bar(o.tokens), legend(o.tokens)),
    h("div", { class: "qline" }, qpill(q), `${fmt(q.measured_tokens)} measured · ${fmt(q.estimated_tokens)} estimated`));
  if (o.cost && !o.cost.complete) el.append(h("div", { class: "notice" }, "Cost is a lower bound: some models have no known rate."));
  if (o.cost) el.append(fold("About these numbers", h("ul", { class: "tight" }, (o.cost.limitations || []).map((l) => h("li", {}, l)))));
  el.append(h("h2", {}, "By agent"), table([["Agent"], ["Tasks", "n"], ["Tokens", "n"], ["Quality"]],
    o.by_agent.map((a) => h("tr", {}, h("td", {}, a.agent), h("td", { class: "n" }, a.tasks),
      h("td", { class: "n" }, fmt(a.total)), h("td", {}, pill(a.measurement, a.measurement))))));
  el.append(h("h2", {}, "By model"), table([["Model"], ["Input", "n hide"], ["Output", "n hide"], ["Cache w", "n hide"], ["Cache r", "n hide"], ["Total", "n"], ["Quality"]],
    o.by_model.map((m) => h("tr", {}, h("td", {}, m.model || "unknown"),
      ...CATS.map(([k]) => h("td", { class: "n hide" }, fmt(m[k]))), h("td", { class: "n" }, fmt(m.total)),
      h("td", {}, pill(m.measurement, m.measurement))))));
  el.append(quality());
  return el;
}

function quality() {
  const d = U.data_quality, r = d.reconciliation, el = h("div", {});
  d.coverage_gaps.forEach((g) => el.append(h("div", { class: "notice" }, g.message)));
  el.append(h("p", {}, pill(r.reconciled ? "task totals match session totals" : "unattributed usage present", r.reconciled ? "measured" : "mixed"),
    h("span", { class: "muted" }, ` session ${fmt(r.session_total)} · attributed ${fmt(r.attributed)} · unattributed ${fmt(r.unattributed)} · unlinked subagent sessions ${r.unlinked_subagent_sessions}`)));
  if (d.collection_errors.length) {
    el.append(h("h3", {}, "Collection issues"), h("ul", { class: "tight" },
      d.collection_errors.map((e) => h("li", {}, `${e.message} (${e.files} file${e.files === 1 ? "" : "s"})`))));
  }
  return fold("Data quality and coverage", el);
}

let topN = null;
function tasks() {
  topN = topN ?? Math.min(U.selection.top_n, U.tasks.length);
  const ctl = h("div", { class: "ctl" }, "Show top ",
    h("input", { type: "number", min: 1, max: U.tasks.length, value: topN }), ` of ${U.tasks.length} tasks`);
  const head = [["#"], ["Task"], ["Tokens", "hide"], ["Total", "n"], ["Cost", "n"], ["Share", "n hide"], ["Quality", "hide"]];
  const tbl = table(head, []), body = tbl.querySelector("tbody");
  const render = () => body.replaceChildren(...U.tasks.slice(0, topN).map(taskRow));
  ctl.querySelector("input").addEventListener("input", (ev) => {
    topN = Math.max(1, Math.min(U.tasks.length, parseInt(ev.target.value || "1", 10)));
    render();
  });
  render();
  return h("div", {}, h("h1", {}, "Expensive tasks"),
    h("div", { class: "sub muted" }, "Ranked by tokens. Estimated counts are a relative proxy."), ctl, tbl, legend());
}
function taskRow(t) {
  return h("tr", { class: "click", onclick: () => { location.hash = "#/task/" + encodeURIComponent(t.id); } },
    h("td", { class: "muted" }, t.rank),
    h("td", { class: "t" }, h("div", { class: "ttl" }, cleanTitle(t.title)),
      h("div", { class: "muted" }, [t.agent, t.repo].filter(Boolean).join(" · "), " ",
        taskAnalysis(t.id) ? pill("analyzed", "ok") : null)),
    h("td", { class: "hide" }, bar(t.tokens)), h("td", { class: "n" }, fmt(t.tokens.total)),
    h("td", { class: "n" }, money(t.cost)), h("td", { class: "n hide" }, pct(t.share_of_total)),
    h("td", { class: "hide" }, qpill(t.quality)));
}

const kv = (label, text) => text ? h("div", { class: "kv" }, h("span", {}, label), h("p", {}, text)) : null;
function recs() {
  const el = h("div", {}, h("h1", {}, "Recommendations"));
  const rs = (A && A.recommendations) || [];
  if (!A) return el.appendChild(h("p", { class: "muted" }, "No analysis yet. Run /tuner in Cursor or Claude Code (or `tuner analyze`).")), el;
  if (!rs.length) el.append(h("p", { class: "muted" }, "The analysis found no change worth recommending."));
  rs.forEach((r) => el.append(h("div", { class: "card rec" },
    h("div", { class: "rec-h" }, h("strong", {}, r.title), h("span", { class: "pills" }, pill(r.kind),
      pill(r.scope === "none" ? "no destination" : r.scope), pill(r.confidence + " confidence"), pill(r.status || "proposed"))),
    h("p", {}, r.description), kv("Impact", r.expected_impact), kv("Why", r.why_it_helps), kv("Action", r.proposed_action),
    r.evidence && r.evidence.length ? fold("Evidence", list(r.evidence)) : null,
    r.destination ? h("p", { class: "muted mono" }, "Destination: " + r.destination) : null,
    r.change_id && r.status === "proposed" ? h("p", { class: "mono" }, "Apply: tuner skills apply " + r.change_id) : null,
    r.note ? h("p", { class: "muted" }, "Note: " + r.note) : null,
    r.diff ? fold("Diff preview", diffPre(r.diff)) : null)));
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
