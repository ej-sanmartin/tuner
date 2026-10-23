"""Windows Task Scheduler integration (schtasks + Task XML).

The XML sets StartWhenAvailable so a missed run executes as soon as the
PC is back, a logon trigger for catch-up after the PC was off, and an
hourly repetition as a fallback ping (`schedule run` is idempotent).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from tuner import paths
from tuner.scheduler.base import CHECK_INTERVAL_S, Spec

TASK = "Tuner\\Report"
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday"]


def render_xml(spec: Spec, argv: list[str]) -> str:
    """Build Task Scheduler XML for the given schedule."""
    start = f"2026-01-01T{spec.hour:02d}:{spec.minute:02d}:00"
    if spec.period == "weekly":
        sched = (f"<ScheduleByWeek><DaysOfWeek><{DAYS[spec.weekday]}/>"
                 "</DaysOfWeek><WeeksInterval>1</WeeksInterval>"
                 "</ScheduleByWeek>")
    elif spec.period == "monthly":
        sched = (f"<ScheduleByMonth><DaysOfMonth><Day>{spec.day_of_month}"
                 "</Day></DaysOfMonth><Months><January/><February/><March/>"
                 "<April/><May/><June/><July/><August/><September/>"
                 "<October/><November/><December/></Months>"
                 "</ScheduleByMonth>")
    else:
        sched = ("<ScheduleByDay><DaysInterval>1</DaysInterval>"
                 "</ScheduleByDay>")
    interval = f"PT{CHECK_INTERVAL_S // 3600}H"
    args = " ".join(f'"{a}"' if " " in a else a
                    for a in [*argv[1:], "schedule", "run"])
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4"
  xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Tuner usage reports</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      {sched}
    </CalendarTrigger>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Repetition><Interval>{interval}</Interval></Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(argv[0])}</Command>
      <Arguments>{escape(args)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    """Run schtasks, capturing output (skipped under TUNER_FAKE_HOME)."""
    if os.environ.get("TUNER_FAKE_HOME"):  # tests must not touch the OS
        marker = paths.data_dir() / "fake-schtasks-installed"
        if args[0] == "/Create":
            paths.ensure_private_dir(marker.parent)
            marker.write_text("1", encoding="utf-8")
        elif args[0] == "/Delete":
            ok = marker.exists()
            marker.unlink(missing_ok=True)
            return subprocess.CompletedProcess(args, 0 if ok else 1, "", "")
        elif args[0] == "/Query":
            return subprocess.CompletedProcess(
                args, 0 if marker.exists() else 1, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    return subprocess.run(["schtasks", *args], capture_output=True,
                          text=True, check=False)


class WindowsScheduler:
    """Manage the Tuner scheduled task."""

    def install(self, spec: Spec, argv: list[str]) -> str:
        """Register (or replace) the scheduled task."""
        xml = render_xml(spec, argv)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tuner-task.xml"
            path.write_bytes(xml.encode("utf-16"))
            res = _schtasks("/Create", "/TN", TASK, "/XML", str(path), "/F")
        if res.returncode != 0:
            raise RuntimeError(f"schtasks failed: {res.stderr.strip()}")
        return TASK

    def uninstall(self) -> bool:
        """Delete the task if present."""
        return _schtasks("/Delete", "/TN", TASK, "/F").returncode == 0

    def status(self) -> dict:
        """Registered state."""
        res = _schtasks("/Query", "/TN", TASK)
        return {"supported": True, "installed": res.returncode == 0,
                "task": TASK}
