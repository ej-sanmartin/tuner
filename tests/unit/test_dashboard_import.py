"""Dashboard CSV replaces matched estimates and leaves the rest."""

from tuner.dashboard.csv import (
    match_requests,
    parse_csv,
    reconcile_status,
    rematch,
    replace_snapshot,
)
from tuner.dashboard.fetch import (
    account_id,
    normalize_subject,
    sanitize_token,
)


def _turn(conn, turn_id, started):
    conn.execute(
        "INSERT INTO turns(id, session_id, seq, started_at, ended_at, "
        "prompt_preview, prompt_chars, outcome, source_path, source_line) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (turn_id, "s", 1, started, None, "p", 1, "completed", "f", 1))
    conn.execute(
        "INSERT INTO usage_events(id, session_id, turn_id, ts, model, "
        "input_tokens, output_tokens, cache_write_tokens, "
        "cache_read_tokens, measurement, confidence, source, method, "
        "source_path, source_line) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"u-{turn_id}", "s", turn_id, started, "m", 100, 0, 0, 0,
         "estimated", "low", "cursor_local_transcript", "cursor_bubbles_v1",
         "f", 1))


_HEADER = ("Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),"
           "Cache Read,Output Tokens,Total Tokens\n")


def _csv(date, total_in=10, cache=0, out=1):
    return (f'{_HEADER}"{date}","claude-sonnet-5-5-high",'
            f'"0","{total_in}","{cache}","{out}","0"\n')


def test_matched_row_hides_the_estimate(conn):
    _turn(conn, "cursor:s:turn:1", "2026-10-26T05:51:11.100Z")
    rows, skipped = parse_csv(_csv("2026-10-26T05:51:11.400Z"))
    assert skipped == 0
    match_requests(conn, rows)
    assert rows[0].turn_id == "cursor:s:turn:1"
    replace_snapshot(conn, rows)
    shown = conn.execute(
        "SELECT measurement, input_tokens, cache_read_tokens "
        "FROM usage_effective").fetchall()
    assert [(r["measurement"], r["input_tokens"]) for r in shown] == [
        ("measured", 10)]
    assert conn.execute(
        "SELECT COUNT(*) FROM usage_events").fetchone()[0] == 1


def test_far_request_stays_estimated_and_unmatched(conn):
    _turn(conn, "cursor:s:turn:1", "2026-10-26T05:51:11.000Z")
    rows, _ = parse_csv(_csv("2026-10-26T06:00:00.000Z", total_in=50))
    match_requests(conn, rows)
    replace_snapshot(conn, rows)
    assert rows[0].turn_id is None
    shown = conn.execute(
        "SELECT measurement FROM usage_effective").fetchall()
    assert [r["measurement"] for r in shown] == ["estimated"]
    st = reconcile_status(conn)
    assert st["status"] == "warn" and st["unmatched"] == 1


def test_closer_request_wins_the_turn(conn):
    _turn(conn, "cursor:s:turn:1", "2026-10-26T05:51:11.000Z")
    text = (_HEADER
            + '"2026-10-26T05:51:12.000Z","m","0","1","0","1","0"\n'
            + '"2026-10-26T05:51:11.200Z","m","0","2","0","1","0"\n')
    rows, _ = parse_csv(text)
    match_requests(conn, rows)
    matched = [r for r in rows if r.turn_id]
    assert len(matched) == 1 and matched[0].input_tokens == 2


def test_rematch_picks_up_a_turn_added_later(conn):
    rows, _ = parse_csv(_csv("2026-10-26T05:51:11.000Z"))
    match_requests(conn, rows)
    replace_snapshot(conn, rows)
    assert reconcile_status(conn)["matched"] == 0
    _turn(conn, "cursor:s:turn:1", "2026-10-26T05:51:11.200Z")
    assert rematch(conn) == 1
    assert reconcile_status(conn)["matched"] == 1


def test_bad_header_is_rejected():
    try:
        parse_csv("a,b\n1,2\n")
    except ValueError as exc:
        assert "token columns" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_redirect_is_refused():
    from tuner.commands.common import TunerError
    from tuner.dashboard.fetch import _NoRedirect
    try:
        _NoRedirect().redirect_request(
            None, None, 302, "found", {}, "https://evil.example")
    except TunerError as exc:
        assert "302" in str(exc) and "evil" not in str(exc)
    else:
        raise AssertionError("redirect was followed")


def test_subject_and_token_rules():
    assert normalize_subject("auth0|user_01ABC") == "user_01ABC"
    assert normalize_subject("google-oauth2|209") == "google-oauth2|209"
    assert normalize_subject("a|b|c") is None
    assert normalize_subject("ok ta|x") is None
    assert sanitize_token("not a jwt") is None
    good = "aaa.bbb.ccc"
    assert sanitize_token(f' "{good}" ') == good
    token = _jwt({"sub": "auth0|user_01ABC"})
    assert account_id(token) == "user_01ABC"


def _jwt(payload: dict) -> str:
    import base64
    import json
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()).decode().rstrip("=")
    return f"aaa.{body}.ccc"
