"""`tuner config`: show, get, set, or locate configuration."""

from __future__ import annotations

from tuner import config as cfgmod
from tuner import paths
from tuner.commands.common import TunerError, load_config


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("config", help="show or edit configuration")
    s = p.add_subparsers(dest="action")
    s.add_parser("show", help="print effective configuration")
    s.add_parser("path", help="print the config file path")
    g = s.add_parser("get", help="get one value (section.key)")
    g.add_argument("key")
    st = s.add_parser("set", help="set one value (section.key)")
    st.add_argument("key")
    st.add_argument("value")
    p.set_defaults(func=run)


def _split(key: str) -> tuple[str, str]:
    """Split 'section.key'."""
    if "." not in key:
        raise TunerError("use section.key, e.g. report.top_n")
    section, name = key.split(".", 1)
    return section, name


def run(args) -> int:
    """Dispatch config actions."""
    action = args.action or "show"
    if action == "path":
        print(paths.config_file())
    elif action == "show":
        cfg = load_config()
        for section, body in cfg.values.items():
            print(f"[{section}]")
            for k, v in body.items():
                print(f"{k} = {cfgmod._literal(v)}")
            print()
    elif action == "get":
        cfg = load_config()
        section, name = _split(args.key)
        try:
            print(cfgmod._literal(cfg.values[section][name]))
        except KeyError as exc:
            raise TunerError(f"unknown option {args.key}") from exc
    elif action == "set":
        section, name = _split(args.key)
        try:
            value = cfgmod.set_value(section, name, args.value)
        except cfgmod.ConfigError as exc:
            raise TunerError(str(exc)) from exc
        print(f"{args.key} = {cfgmod._literal(value)}")
    return 0
