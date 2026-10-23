"""Validate and normalise an analysis produced by an agent.

The agent's output is untrusted: it is schema-checked, bounded, stripped
of anything numeric the model must not invent (costs), and every
recommendation must cite evidence that exists in the evidence bundle.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime

from tuner import ANALYSIS_SCHEMA_VERSION
from tuner.analysis import INSTRUCTIONS_VERSION, evidence

KINDS = ("skill", "rule", "workflow", "prompt", "tooling", "model-choice",
         "none")
SCOPES = ("global", "project", "none")
LEVELS = ("low", "medium", "high")
MAX_TASKS, MAX_RECS, MAX_ITEMS, MAX_TEXT = 25, 15, 20, 2000
_MONEY = re.compile(r"(\$\s?\d|\b\d[\d,.]*\s?(usd|dollars?|eur|cents)\b)",
                    re.I)
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REF = re.compile(r"^[STP]\d+$")


class AnalysisError(ValueError):
    """The submitted analysis is invalid; `problems` lists every issue."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class _Ctx:
    """Collects problems while walking the document."""

    def __init__(self, refs: dict[str, set[str]]):
        self.refs, self.problems, self.warnings = refs, [], []

    def err(self, where: str, msg: str) -> None:
        self.problems.append(f"{where}: {msg}")

    def text(self, where: str, value, required: bool = False,
             limit: int = MAX_TEXT) -> str:
        """A bounded, control-char-free string without dollar amounts."""
        if value in (None, ""):
            if required:
                self.err(where, "required")
            return ""
        if not isinstance(value, str):
            self.err(where, "must be a string")
            return ""
        value = _CTRL.sub("", value).strip()[:limit]
        if _MONEY.search(value):
            self.err(where, "dollar amounts are not allowed; Tuner "
                     "computes cost deterministically")
        return value


def valid_refs(conn: sqlite3.Connection, usage: dict, selection: list[str]
               ) -> dict[str, set[str]]:
    """Evidence reference ids per task (S=signal, T=timeline, P=prompt)."""
    by_id = {t["id"]: t for t in usage["tasks"]}
    out: dict[str, set[str]] = {}
    for tid in selection:
        rec = by_id[tid]
        refs = {s["id"] for s in evidence.signals_for(conn, rec)}
        refs |= {f"T{i}" for i in range(len(rec.get("timeline", [])))}
        n_prompts = min(rec["turns"], evidence.MAX_PROMPTS)
        refs |= {f"P{i}" for i in range(1, n_prompts + 1)}
        out[tid] = refs
    return out


def _claims(ctx: _Ctx, where: str, items, task_id: str | None) -> list:
    """Classification/what-happened lists: strings or cited claims."""
    out = []
    for i, item in enumerate((items or [])[:MAX_ITEMS]):
        w = f"{where}[{i}]"
        if isinstance(item, str):
            out.append(ctx.text(w, item))
        elif isinstance(item, dict):
            refs = _refs(ctx, w, item.get("evidence"), task_id)
            out.append({"claim": ctx.text(f"{w}.claim", item.get("claim"),
                                          True), "evidence": refs})
        else:
            ctx.err(w, "must be a string or {claim, evidence}")
    return out


def _refs(ctx: _Ctx, where: str, refs, task_id: str | None) -> list[str]:
    """Check evidence refs exist for the task."""
    good = []
    for ref in refs or []:
        if not (isinstance(ref, str) and _REF.match(ref)):
            ctx.err(where, f"bad evidence ref {ref!r}")
        elif task_id and ref not in ctx.refs.get(task_id, set()):
            ctx.err(where, f"evidence {ref} not found in task bundle")
        else:
            good.append(ref)
    return good


def _task(ctx: _Ctx, i: int, raw: dict, selection: set[str]) -> dict | None:
    """One task analysis."""
    w = f"tasks[{i}]"
    tid = raw.get("task_id")
    if tid not in selection:
        ctx.err(w, f"unknown task_id {tid!r}")
        return None
    cls = raw.get("classification") or {}
    return {
        "task_id": tid,
        "objective": ctx.text(f"{w}.objective", raw.get("objective"), True),
        "summary": ctx.text(f"{w}.summary", raw.get("summary"), True),
        "what_happened": _claims(ctx, f"{w}.what_happened",
                                 raw.get("what_happened"), tid),
        "classification": {k: _claims(ctx, f"{w}.classification.{k}",
                                      cls.get(k), tid)
                           for k in ("productive_complexity",
                                     "avoidable_overhead",
                                     "insufficient_evidence")},
    }


def _rec(ctx: _Ctx, i: int, raw: dict, selection: set[str]) -> dict | None:
    """One recommendation (must cite evidence)."""
    w = f"recommendations[{i}]"
    ev = []
    for j, e in enumerate(raw.get("evidence") or []):
        tid = e.get("task_id") if isinstance(e, dict) else None
        if tid not in selection:
            ctx.err(f"{w}.evidence[{j}]", f"unknown task_id {tid!r}")
            continue
        ev.append({"task_id": tid,
                   "claim": ctx.text(f"{w}.evidence[{j}].claim",
                                     e.get("claim"), True),
                   "evidence": _refs(ctx, f"{w}.evidence[{j}]",
                                     e.get("refs"), tid)})
    if not any(e["evidence"] for e in ev):
        ctx.err(w, "needs at least one evidence entry with valid refs")
    kind, scope = raw.get("kind"), raw.get("scope", "none")
    conf = raw.get("confidence")
    for name, val, allowed in (("kind", kind, KINDS), ("scope", scope, SCOPES),
                               ("confidence", conf, LEVELS)):
        if val not in allowed:
            ctx.err(f"{w}.{name}", f"must be one of {allowed}")
    out = {"id": f"R{i + 1}", "kind": kind, "scope": scope,
           "confidence": conf, "evidence": ev,
           "title": ctx.text(f"{w}.title", raw.get("title"), True, 140)}
    for k in ("description", "expected_impact", "why_it_helps",
              "proposed_action"):
        out[k] = ctx.text(f"{w}.{k}", raw.get(k), k == "description")
    sc = raw.get("skill_change")
    if sc is not None:
        if kind != "skill" or not isinstance(sc, dict):
            ctx.err(w, "skill_change requires kind 'skill' and an object")
        else:
            out["skill_change"] = {
                "name": ctx.text(f"{w}.skill_change.name", sc.get("name"),
                                 True, 64),
                "content": str(sc.get("content", ""))[:20_000]}
    return out


def validate(raw, usage: dict, selection: list[str], snapshot_hash: str,
             key: str, refs: dict[str, set[str]], producer: dict
             ) -> tuple[dict, list[str]]:
    """Return (clean analysis, warnings) or raise AnalysisError."""
    if not isinstance(raw, dict):
        raise AnalysisError(["top level must be an object"])
    ctx, sel = _Ctx(refs), set(selection)
    if "cost" in raw or any(isinstance(t, dict) and "cost" in t
                            for t in raw.get("tasks") or []):
        ctx.warnings.append("ignored model-supplied cost fields")
    tasks = [t for i, r in enumerate((raw.get("tasks") or [])[:MAX_TASKS])
             if isinstance(r, dict) and (t := _task(ctx, i, r, sel))]
    recs = [r for i, x in enumerate(
        (raw.get("recommendations") or [])[:MAX_RECS])
        if isinstance(x, dict) and (r := _rec(ctx, i, x, sel))]
    by_id = {t["id"]: t for t in usage["tasks"]}
    for t in tasks:  # deterministic cost injection
        t["cost"] = by_id[t["task_id"]].get("cost")
    missing = sorted(sel - {t["task_id"] for t in tasks})
    if missing:
        ctx.warnings.append(f"no analysis for {len(missing)} selected "
                            "task(s)")
    if ctx.problems:
        raise AnalysisError(ctx.problems)
    limits = [ctx.text("limitations", x) for x in
              (raw.get("limitations") or [])[:MAX_ITEMS]]
    return ({
        "kind": "tuner.analysis", "schema_version": ANALYSIS_SCHEMA_VERSION,
        "instructions_version": INSTRUCTIONS_VERSION,
        "period": usage["period"]["id"], "snapshot_hash": snapshot_hash,
        "cache_key": key, "created_at": datetime.now(UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "produced_by": producer, "selection": selection,
        "coverage": {"selected": len(selection), "analyzed": len(tasks)},
        "tasks": tasks, "recommendations": recs, "limitations": limits,
    }, ctx.warnings)
