"""Match a Cursor dashboard usage CSV to local turns and store it.

One CSV row is one request. Reports read `usage_effective`, which shows
that row instead of the turn's estimates. The estimates stay in
`usage_events` so the error can be reported. A new import replaces the
previous snapshot. `rematch` re-runs after collect, because a re-parse
can change turn ids.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import sqlite3
import statistics
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime

from tuner.storage import repo

MATCH_S = 3.0
_COLS = ("Date", "Model", "Input (w/ Cache Write)",
         "Input (w/o Cache Write)", "Cache Read", "Output Tokens")
_TOKENS = ("input_tokens + output_tokens + cache_write_tokens + "
           "cache_read_tokens")


@dataclass
class Request:
    """One dashboard request, possibly matched to a turn."""

    id: str
    ts: str
    model: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    turn_id: str | None = None
    match_delta_s: float | None = None

    def total(self) -> int:
        """Sum of the four disjoint token columns."""
        return (self.input_tokens + self.cache_write_tokens
                + self.cache_read_tokens + self.output_tokens)


def _epoch(ts: str) -> float:
    """UTC epoch seconds for an ISO timestamp."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _num(cell: str) -> int:
    """Parse one token cell; blank is zero."""
    return int(cell.strip() or "0")


def parse_csv(text: str) -> tuple[list[Request], int]:
    """Parse dashboard CSV text into requests. Returns (rows, skipped).

    Columns are found by header name. Raises ValueError when the header
    is not a Cursor usage export. A row with a non-numeric cell is skipped.
    """
    reader = csv.DictReader(io.StringIO(text))
    names = reader.fieldnames or []
    if any(col not in names for col in _COLS):
        raise ValueError(
            "not a Cursor usage CSV (missing token columns)")
    rows: list[Request] = []
    skipped = 0
    for raw in reader:
        try:
            inp = _num(raw["Input (w/o Cache Write)"])
            cw = _num(raw["Input (w/ Cache Write)"])
            cr = _num(raw["Cache Read"])
            out = _num(raw["Output Tokens"])
            ts = raw["Date"].strip().strip('"')
            _epoch(ts)  # reject a row whose time will not match
        except (TypeError, ValueError):
            skipped += 1
            continue
        model = (raw.get("Model") or "").strip()
        key = f"{ts}|{model}|{inp}|{cw}|{cr}|{out}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        rows.append(Request(digest, ts, model, inp, cw, cr, out))
    return rows, skipped


def match_requests(conn: sqlite3.Connection, rows: list[Request]) -> None:
    """Set turn_id on each row from the nearest Cursor turn within MATCH_S.

    Each turn is used at most once. The closer request wins.
    """
    for row in rows:
        row.turn_id = None
        row.match_delta_s = None
    turns = [(_epoch(r["started_at"]), r["id"]) for r in conn.execute(
        "SELECT id, started_at FROM turns WHERE id LIKE 'cursor:%' "
        "AND started_at IS NOT NULL ORDER BY started_at")]
    times = [t[0] for t in turns]
    cands: list[tuple[float, int, str]] = []
    for i, row in enumerate(rows):
        when = _epoch(row.ts)
        lo = bisect_left(times, when - MATCH_S)
        hi = bisect_right(times, when + MATCH_S)
        for j in range(lo, hi):
            cands.append((abs(times[j] - when), i, turns[j][1]))
    used_rows: set[int] = set()
    used_turns: set[str] = set()
    for delta, i, turn_id in sorted(cands):
        if i in used_rows or turn_id in used_turns:
            continue
        used_rows.add(i)
        used_turns.add(turn_id)
        rows[i].turn_id = turn_id
        rows[i].match_delta_s = round(delta, 3)


def replace_snapshot(conn: sqlite3.Connection, rows: list[Request]) -> None:
    """Replace the stored dashboard snapshot with `rows`."""
    now = repo.now_iso()
    conn.execute("DELETE FROM dashboard_requests")
    conn.executemany(
        "INSERT INTO dashboard_requests(id, ts, model, input_tokens, "
        "cache_write_tokens, cache_read_tokens, output_tokens, turn_id, "
        "match_delta_s, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(r.id, r.ts, r.model, r.input_tokens, r.cache_write_tokens,
          r.cache_read_tokens, r.output_tokens, r.turn_id,
          r.match_delta_s, now) for r in rows])


def rematch(conn: sqlite3.Connection) -> int:
    """Re-link the stored snapshot to current turns. Returns match count."""
    rows = [Request(
        r["id"], r["ts"], r["model"], r["input_tokens"],
        r["cache_write_tokens"], r["cache_read_tokens"], r["output_tokens"])
        for r in conn.execute("SELECT * FROM dashboard_requests")]
    if not rows:
        return 0
    match_requests(conn, rows)
    conn.executemany(
        "UPDATE dashboard_requests SET turn_id=?, match_delta_s=? "
        "WHERE id=?",
        [(r.turn_id, r.match_delta_s, r.id) for r in rows])
    return sum(r.turn_id is not None for r in rows)


def reconcile_status(conn: sqlite3.Connection) -> dict:
    """Matched/unmatched counts and estimate error, for doctor."""
    n = conn.execute("SELECT COUNT(*) FROM dashboard_requests").fetchone()[0]
    if not n:
        return {"status": "warn", "matched": 0, "unmatched": 0,
                "detail": "no dashboard snapshot; Cursor totals are "
                "estimates. `tuner import cursor <file>` or "
                "`tuner import cursor --fetch`"}
    unmatched, utok = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM({_TOKENS}),0) FROM "
        "dashboard_requests WHERE turn_id IS NULL").fetchone()
    ratios = []
    for measured, estimated in conn.execute(
            f"SELECT ({_TOKENS}), (SELECT COALESCE(SUM({_TOKENS}),0) FROM "
            "usage_events u WHERE u.turn_id = d.turn_id AND "
            "u.measurement = 'estimated') FROM dashboard_requests d "
            "WHERE d.turn_id IS NOT NULL"):
        if measured and estimated:
            ratios.append(estimated / measured)
    matched = n - unmatched
    detail = f"{matched} matched, {unmatched} unmatched"
    if unmatched:
        detail += f" ({utok:,} tokens not in any task)"
    if ratios:
        within = sum(abs(math.log(r)) <= math.log(2) for r in ratios)
        detail += (f"; estimates are {statistics.median(ratios):.2f}x "
                   f"the dashboard (median), "
                   f"{within * 100 // len(ratios)}% within 2x")
    return {"status": "warn" if unmatched else "ok", "matched": matched,
            "unmatched": unmatched, "detail": detail}
