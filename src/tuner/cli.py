"""Command-line entry point. Kept import-light so Cursor hooks stay fast."""

from __future__ import annotations

import argparse
import sys

COMMAND_MODULES = ("init", "doctor", "collect", "report", "analyze", "open",
                   "skills", "schedule", "config", "pricing", "upgrade",
                   "uninstall")


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level parser with all subcommands registered."""
    import importlib

    from tuner import __version__
    parser = argparse.ArgumentParser(
        prog="tuner",
        description="Understand your AI usage. Tune your agent workflows.")
    parser.add_argument("--version", action="version",
                        version=f"tuner {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for name in COMMAND_MODULES:
        mod = importlib.import_module(f"tuner.commands.{name}")
        mod.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "hook":  # hot path: no heavy imports
        from tuner.hook_spool import run_hook
        return run_hook(argv[1], sys.stdin.read())
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # user-facing errors, not tracebacks
        from tuner.commands.common import TunerError
        if isinstance(exc, TunerError):
            print(f"error: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
