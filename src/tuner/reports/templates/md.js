"use strict";
// Tiny, safe Markdown renderer for prompts. Builds DOM nodes with `h`
// (text nodes only, never innerHTML). Declarations only: this file is
// concatenated before report.js and relies on function hoisting.

function mdInline(text) {
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*\s][^*]*)\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  const out = [];
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] !== undefined) out.push(h("code", {}, m[1]));
    else if (m[2] !== undefined || m[3] !== undefined) out.push(h("strong", {}, mdInline(m[2] ?? m[3])));
    else if (m[4] !== undefined) out.push(h("em", {}, mdInline(m[4])));
    else if (/^https?:\/\//i.test(m[6])) {
      out.push(h("a", { href: m[6], target: "_blank", rel: "noopener noreferrer" }, m[5]));
    } else out.push(m[5]);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const MD_LI = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const MD_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const MD_HR = /^\s*([-*_])(\s*\1){2,}\s*$/;
const mdBlank = (s) => s === undefined || /^\s*$/.test(s);
const mdCells = (s) => s.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

function mdStarts(lines, i) {
  const ln = lines[i];
  return /^\s*(```|~~~)/.test(ln) || /^#{1,6}\s/.test(ln) || MD_LI.test(ln) || /^\s*>/.test(ln) ||
    MD_HR.test(ln) || (ln.includes("|") && MD_SEP.test(lines[i + 1] || ""));
}

function mdList(lines, i) {
  const first = lines[i].match(MD_LI), base = first[1].length;
  const list = h(/\d/.test(first[2]) ? "ol" : "ul", {});
  let li = null, sub = [];
  const flush = () => {
    if (li && sub.length) li.append(renderMd(sub.join("\n")));
    if (li) list.append(li);
    li = null; sub = [];
  };
  while (i < lines.length) {
    const ln = lines[i], m = ln.match(MD_LI);
    if (m && m[1].length <= base) {
      if (m[1].length < base) break;
      flush();
      li = h("li", {}, mdInline(m[3]));
    } else if (mdBlank(ln)) {
      const nx = lines[i + 1];
      if (mdBlank(nx) || !/^\s+\S/.test(nx) && !(MD_LI.test(nx) && nx.match(MD_LI)[1].length >= base)) break;
      sub.push("");
    } else if (li && /^\s+\S/.test(ln)) sub.push(ln.slice(Math.min(base, ln.search(/\S/))));
    else break;
    i++;
  }
  flush();
  return [list, i];
}

function mdTable(lines, i) {
  const head = mdCells(lines[i]), rows = [];
  i += 2;
  while (i < lines.length && lines[i].includes("|") && !mdBlank(lines[i])) rows.push(mdCells(lines[i++]));
  const tbl = h("table", {}, h("thead", {}, h("tr", {}, head.map((c) => h("th", {}, mdInline(c))))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, mdInline(c)))))));
  return [h("div", { class: "tbl" }, tbl), i];
}

function renderMd(src) {
  const lines = String(src || "").replace(/\r/g, "").split("\n"), out = h("div", { class: "md" });
  let i = 0, m;
  while (i < lines.length) {
    const ln = lines[i];
    if (mdBlank(ln)) { i++; continue; }
    if ((m = ln.match(/^\s*(```|~~~)/))) {
      const code = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith(m[1]); i++) code.push(lines[i]);
      i++;
      out.append(h("pre", { class: "code" }, code.join("\n")));
    } else if ((m = ln.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))) {
      out.append(h("div", { class: "mh mh" + Math.min(m[1].length, 4) }, mdInline(m[2])));
      i++;
    } else if (MD_HR.test(ln)) {
      out.append(h("hr", {}));
      i++;
    } else if (/^\s*>/.test(ln)) {
      const q = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) q.push(lines[i].replace(/^\s*>\s?/, ""));
      out.append(h("blockquote", {}, renderMd(q.join("\n"))));
    } else if (ln.includes("|") && MD_SEP.test(lines[i + 1] || "")) {
      const [node, next] = mdTable(lines, i);
      out.append(node); i = next;
    } else if (MD_LI.test(ln)) {
      const [node, next] = mdList(lines, i);
      out.append(node); i = next;
    } else {
      const para = [];
      for (; i < lines.length && !mdBlank(lines[i]) && (!para.length || !mdStarts(lines, i)); i++) {
        if (para.length) para.push(h("br", {}));
        para.push(mdInline(lines[i].trim()));
      }
      out.append(h("p", {}, para));
    }
  }
  return out;
}
