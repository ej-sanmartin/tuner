"""Placeholder scheduler for platforms not yet supported (Linux later)."""

from __future__ import annotations

from tuner.scheduler.base import Spec


class UnsupportedScheduler:
    """Reports that scheduling is not available on this platform."""

    def install(self, spec: Spec, argv: list[str]) -> str:
        """Scheduling is unavailable."""
        raise RuntimeError("scheduling is supported on macOS and Windows "
                           "only for now; run `tuner schedule run` from "
                           "cron/systemd instead")

    def uninstall(self) -> bool:
        """Nothing to remove."""
        return False

    def status(self) -> dict:
        """Not supported."""
        return {"supported": False, "installed": False}
