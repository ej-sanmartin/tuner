"""Download the Cursor dashboard usage CSV with the local session.

Reads `cursorAuth/accessToken` from Cursor's state DB (read-only) and
sends it only to cursor.com, as the `WorkosCursorSessionToken` cookie.
Redirects are refused so the cookie cannot follow to another host.
The token is never printed.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from tuner.collectors.cursor_paths import cursor_home, state_db_path
from tuner.commands.common import TunerError

URL = ("https://cursor.com/api/dashboard/"
       "export-usage-events-csv?strategy=tokens")
_REFERER = "https://www.cursor.com/settings"
_UA = ("Mozilla/5.0 (compatible; tuner) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_JWT = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the session cookie stays on cursor.com."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Do not follow. The caller reports the status."""
        raise TunerError(
            f"unexpected redirect (HTTP {code}) from the usage endpoint")


def sanitize_token(raw: str) -> str | None:
    """A JWT safe to put in a Cookie header, or None."""
    token = raw.strip().strip('"').strip()
    return token if _JWT.fullmatch(token) else None


def jwt_subject(jwt: str) -> str | None:
    """The `sub` claim, or None when the payload is not JSON."""
    payload = jwt.split(".")[1]
    pad = "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + pad))
    except (ValueError, json.JSONDecodeError):
        return None
    sub = data.get("sub") if isinstance(data, dict) else None
    return sub if isinstance(sub, str) else None


def _safe_part(part: str) -> bool:
    """True when a subject half cannot break a Cookie header."""
    if not part:
        return False
    return not any(c.isascii() and (ord(c) < 32 or c in ' ",;\\|')
                   for c in part)


def normalize_subject(subject: str) -> str | None:
    """Account id for the cookie: `user_XXX`, or a single-pipe subject."""
    tail = subject.rsplit("|", 1)[-1]
    if (tail.startswith("user_") and len(tail) > 5
            and tail.replace("_", "").isalnum()):
        return tail
    parts = subject.split("|")
    if len(parts) == 2 and all(_safe_part(p) for p in parts):
        return subject
    return None


def account_id(jwt: str, cli_config: Path | None = None) -> str | None:
    """Account id from the JWT, else `cli-config.json` authInfo.authId."""
    sub = jwt_subject(jwt)
    if sub and (got := normalize_subject(sub)):
        return got
    path = cli_config or (cursor_home() / "cli-config.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        auth = str((data.get("authInfo") or {}).get("authId") or "")
    except (OSError, ValueError, AttributeError):
        return None
    return normalize_subject(auth)


def read_access_token(path: Path | None = None) -> str | None:
    """JWT from the state DB, or None when Cursor is signed out."""
    path = path or state_db_path()
    if not path.exists():
        return None
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key=?",
                ("cursorAuth/accessToken",)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise TunerError(
            f"cannot read the Cursor state database: {exc}") from exc
    return sanitize_token(row[0]) if row else None


def fetch_csv(account: str, jwt: str, timeout: float = 30) -> str:
    """GET the usage CSV. Raises TunerError; never includes the token."""
    cookie = ("WorkosCursorSessionToken="
              f"{account.replace('|', '%7C')}%3A%3A{jwt}")
    req = urllib.request.Request(URL, headers={
        "Cookie": cookie, "Referer": _REFERER, "User-Agent": _UA,
        "Accept": "*/*"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except TunerError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise TunerError(
                "Cursor session expired; sign in to Cursor and retry"
            ) from exc
        raise TunerError(
            f"Cursor usage export returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TunerError(f"could not reach cursor.com: {exc.reason}") from exc


def download() -> str:
    """Fetch using the local session. Raises TunerError when it cannot."""
    import os
    jwt = sanitize_token(os.environ.get("CURSOR_TOKEN") or "") \
        or read_access_token()
    if not jwt:
        raise TunerError(
            "no Cursor session token (sign in to Cursor, or set "
            "CURSOR_TOKEN)")
    account = account_id(jwt)
    if not account:
        raise TunerError("could not read the Cursor account id from "
                         "the session token")
    return fetch_csv(account, jwt)
