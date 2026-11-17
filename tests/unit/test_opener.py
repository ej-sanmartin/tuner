"""`tuner open` follows the report written most recently."""

from tuner.reports.opener import latest_report_dir


def _insert(conn, period_id, end, generated, status, directory):
    """Insert one report_periods row."""
    conn.execute(
        "INSERT INTO report_periods(period_id, period_start, period_end, "
        "top_n, status, generated_at, usage_hash, report_dir) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (period_id, "2026-11-01T00:00:00Z", end, 3, status,
         generated, "h", str(directory)))


def test_custom_window_beats_older_complete_week(conn, tmp_path):
    """A partial --since report is what open shows after it is built."""
    weekly = tmp_path / "weekly"
    custom = tmp_path / "custom"
    _insert(conn, "2026-W46", "2026-11-16T23:00:00Z",
            "2026-11-16T23:00:00Z", "complete", weekly)
    _insert(conn, "custom-20261110-20261117", "2026-11-17T21:00:00Z",
            "2026-11-17T21:42:00Z", "partial", custom)
    assert latest_report_dir(conn) == custom


def test_regenerated_older_week_is_latest(conn, tmp_path):
    """Last write wins, even when its period ended earlier."""
    current = tmp_path / "current"
    rebuilt = tmp_path / "rebuilt"
    _insert(conn, "2026-W46", "2026-11-16T23:00:00Z",
            "2026-11-16T23:00:00Z", "complete", current)
    _insert(conn, "2026-W45", "2026-11-09T23:00:00Z",
            "2026-11-17T12:00:00Z", "complete", rebuilt)
    assert latest_report_dir(conn) == rebuilt
