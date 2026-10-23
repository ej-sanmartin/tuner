"""SQL aggregation of usage, tools, and events per task.

Subagent usage is attributed to the parent turn that spawned it through
`subagent_spawn` events; child sessions are never counted twice because
direct usage joins on turn ids while subagent usage joins on session ids.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

SUMS = ("SUM(u.input_tokens) AS input_tokens, "
        "SUM(u.output_tokens) AS output_tokens, "
        "SUM(u.cache_write_tokens) AS cache_write_tokens, "
        "SUM(u.cache_read_tokens) AS cache_read_tokens, COUNT(*) AS calls")
GROUP = "u.model, u.measurement, u.confidence, u.method, u.source"
COLS = "u.model, u.measurement, u.confidence, u.method, u.source"

# Maps a task's turns to subagent child sessions via spawn events.
CHILD_JOIN = (
    "JOIN events e ON e.turn_id = tt.turn_id AND e.kind='subagent_spawn' "
    "JOIN sessions c ON c.parent_id = e.session_id "
    "AND c.agent_ref = json_extract(e.data_json, '$.agent_ref')")


def _load_temp(conn: sqlite3.Connection, task_ids: list[str]) -> None:
    """Fill temp table _tt(task_id, turn_id) for the given tasks."""
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _tt("
                 "task_id TEXT, turn_id TEXT)")
    conn.execute("DELETE FROM _tt")
    for i in range(0, len(task_ids), 500):
        chunk = task_ids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"INSERT INTO _tt SELECT task_id, turn_id FROM "
                     f"task_turns WHERE task_id IN ({marks})", chunk)
    conn.execute("CREATE INDEX IF NOT EXISTS _tt_turn ON _tt(turn_id)")


def load_task_usage(conn: sqlite3.Connection, task_ids: list[str]
                    ) -> dict[str, list[dict]]:
    """Per-task usage rows grouped by model/quality, tagged by origin."""
    out: dict[str, list[dict]] = defaultdict(list)
    if not task_ids:
        return out
    _load_temp(conn, task_ids)
    queries = {
        "direct": (f"SELECT tt.task_id, {COLS}, {SUMS} FROM _tt tt JOIN "
                   f"usage_events u ON u.turn_id = tt.turn_id "
                   f"GROUP BY tt.task_id, {GROUP}"),
        "subagent": (f"SELECT tt.task_id, {COLS}, {SUMS}, "
                     f"COUNT(DISTINCT c.id) AS children FROM _tt tt "
                     f"{CHILD_JOIN} JOIN usage_events u "
                     f"ON u.session_id = c.id "
                     f"GROUP BY tt.task_id, {GROUP}"),
    }
    for via, sql in queries.items():
        for row in conn.execute(sql):
            d = dict(row)
            d["via"] = via
            out[d.pop("task_id")].append(d)
    return out


def load_task_tools(conn: sqlite3.Connection, task_ids: list[str]
                    ) -> dict[str, dict]:
    """Tool call counts, failures, and repeated targets per task."""
    out: dict[str, dict] = {t: {"by_name": {}, "total": 0, "failed": 0,
                                "unknown_status": 0, "repeated": []}
                            for t in task_ids}
    if not task_ids:
        return out
    _load_temp(conn, task_ids)
    base = ("SELECT tt.task_id, k.name, k.target, k.is_error FROM _tt tt "
            "JOIN tool_calls k ON k.turn_id = tt.turn_id UNION ALL "
            f"SELECT tt.task_id, k.name, k.target, k.is_error FROM _tt tt "
            f"{CHILD_JOIN} JOIN tool_calls k ON k.session_id = c.id")
    seen: dict[str, dict[tuple, int]] = defaultdict(
        lambda: defaultdict(int))
    for row in conn.execute(base):
        t = out[row["task_id"]]
        t["total"] += 1
        name = t["by_name"].setdefault(
            row["name"], {"count": 0, "failed": 0})
        name["count"] += 1
        if row["is_error"]:
            name["failed"] += 1
            t["failed"] += 1
        elif row["is_error"] is None:
            t["unknown_status"] += 1
        if row["target"]:
            seen[row["task_id"]][(row["name"], row["target"])] += 1
    for tid, counts in seen.items():
        rep = [{"tool": n, "target": tg, "count": c}
               for (n, tg), c in counts.items() if c >= 3]
        out[tid]["repeated"] = sorted(rep, key=lambda r: -r["count"])[:8]
    return out


def load_task_events(conn: sqlite3.Connection, task_ids: list[str]
                     ) -> dict[str, dict]:
    """Compaction and subagent counts per task."""
    out = {t: {"compactions": 0, "subagents": 0} for t in task_ids}
    if not task_ids:
        return out
    _load_temp(conn, task_ids)
    for row in conn.execute(
            "SELECT tt.task_id, e.kind, COUNT(*) n FROM _tt tt JOIN events e "
            "ON e.turn_id = tt.turn_id GROUP BY tt.task_id, e.kind"):
        key = {"compaction": "compactions",
               "subagent_spawn": "subagents"}.get(row["kind"])
        if key:
            out[row["task_id"]][key] += row["n"]
    return out


def load_timeline(conn: sqlite3.Connection, task_id: str, cap: int = 80
                  ) -> list[dict]:
    """Ordered activity timeline (turns, tools, events), capped."""
    items: list[dict] = []
    sql_turns = ("SELECT t.id, t.started_at ts, t.prompt_preview, t.outcome, "
                 "t.source_path, t.source_line FROM task_turns tt JOIN turns "
                 "t ON t.id = tt.turn_id WHERE tt.task_id=? ORDER BY t.seq")
    for r in conn.execute(sql_turns, (task_id,)):
        items.append({"kind": "prompt", "ts": r["ts"], "text": r[
            "prompt_preview"][:160], "outcome": r["outcome"],
            "ref": f"{r['source_path']}#L{r['source_line']}",
            "_ln": r["source_line"]})
    sql_tools = ("SELECT k.ts, k.name, k.target, k.is_error, k.source_path, "
                 "k.source_line FROM task_turns tt JOIN tool_calls k ON "
                 "k.turn_id = tt.turn_id WHERE tt.task_id=? "
                 "ORDER BY k.source_line")
    for r in conn.execute(sql_tools, (task_id,)):
        items.append({"kind": "tool", "ts": r["ts"], "name": r["name"],
                      "target": r["target"], "error": r["is_error"],
                      "ref": f"{r['source_path']}#L{r['source_line']}",
                      "_ln": r["source_line"]})
    items.sort(key=lambda i: i["_ln"])
    for item in items:
        item.pop("_ln")
    sql_ev = ("SELECT e.ts, e.kind, e.data_json FROM task_turns tt JOIN "
              "events e ON e.turn_id = tt.turn_id WHERE tt.task_id=?")
    for r in conn.execute(sql_ev, (task_id,)):
        items.append({"kind": r["kind"], "ts": r["ts"],
                      "data": r["data_json"][:200]})
    if len(items) > cap:
        head, tail = items[: cap // 2], items[-(cap // 2):]
        items = head + [{"kind": "gap", "omitted": len(items) - cap}] + tail
    return items
