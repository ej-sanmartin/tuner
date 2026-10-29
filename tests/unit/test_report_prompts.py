"""The task page re-reads the full prompt from the transcript."""

import json

from tuner.reports.usage_query import load_timeline


def test_timeline_includes_the_full_prompt(conn, tmp_path):
    body = "Add barriers in viewer/runs.py and stop after one patch."
    path = tmp_path / "chat.jsonl"
    path.write_text(json.dumps({
        "role": "user",
        "message": {"content": [{"type": "text", "text": body}]},
    }) + "\n", encoding="utf-8")
    conn.execute(
        "INSERT INTO turns(id, session_id, seq, started_at, ended_at, "
        "prompt_preview, prompt_chars, outcome, source_path, source_line) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("t1", "s", 0, None, None, "Add barriers", len(body), "completed",
         str(path), 1))
    conn.execute(
        "INSERT INTO tasks(id, session_id, title, started_at, ended_at, "
        "time_quality, boundary, confidence, evidence_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("task1", "s", "t", None, None, "measured", "new_prompt", "high",
         "{}"))
    conn.execute("INSERT INTO task_turns(task_id, turn_id) VALUES (?,?)",
                 ("task1", "t1"))
    items = [i for i in load_timeline(conn, "task1") if i["kind"] == "prompt"]
    assert items[0]["text"] == "Add barriers"
    assert items[0]["full"] == body


def test_html_bundles_every_script_template():
    """The page ships the markdown renderer and the task page script."""
    from tuner.reports.html import JS_FILES, render_html
    page = render_html({"overview": {}}, None, [])
    assert "function renderMd" in page and "function task(" in page
    assert JS_FILES[-1] == "report.js"
