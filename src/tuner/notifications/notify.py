"""Cross-platform local notifications.

Text is passed to the OS as arguments or environment variables (never
interpolated into scripts) so report titles cannot inject commands.
macOS banners cannot carry a click action; `tuner open` opens the report.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

_WIN_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager,
 Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument,
 ContentType = WindowsRuntime] | Out-Null
$t = [System.Security.SecurityElement]::Escape($env:TUNER_TITLE)
$m = [System.Security.SecurityElement]::Escape($env:TUNER_MSG)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'>" +
  "<text>$t</text><text>$m</text></binding></visual></toast>")
$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}' +
  '\WindowsPowerShell\v1.0\powershell.exe'
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::
  CreateToastNotifier($id).Show($toast)
"""


def _clip(text: str, limit: int) -> str:
    """Strip control characters and truncate."""
    clean = "".join(c for c in text if c.isprintable())
    return clean[:limit]


def notify(title: str, message: str) -> bool:
    """Show a notification; returns True if the OS accepted it."""
    title, message = _clip(title, 80), _clip(message, 240)
    try:
        if sys.platform == "darwin":
            cmd = ["osascript", "-e", "on run argv",
                   "-e", "display notification (item 2 of argv) "
                         "with title (item 1 of argv)",
                   "-e", "end run", title, message]
            return subprocess.run(cmd, timeout=10, capture_output=True,
                                  check=False).returncode == 0
        if sys.platform == "win32":
            env = {**os.environ, "TUNER_TITLE": title, "TUNER_MSG": message}
            cmd = ["powershell", "-NoProfile", "-NonInteractive",
                   "-WindowStyle", "Hidden", "-Command", _WIN_SCRIPT]
            return subprocess.run(cmd, env=env, timeout=20,
                                  capture_output=True,
                                  check=False).returncode == 0
        exe = shutil.which("notify-send")
        if exe:
            return subprocess.run([exe, title, message], timeout=10,
                                  check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    return False
