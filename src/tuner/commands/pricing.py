"""`tuner pricing`: refresh/inspect rates and compute ad-hoc costs."""

from __future__ import annotations

from tuner.commands.common import TunerError, emit_json, load_config
from tuner.pricing import PriceBook, estimate_cost, litellm
from tuner.pricing.table import cache_file, overrides_file, save_cache


def register(sub) -> None:
    """Register the subcommand."""
    p = sub.add_parser("pricing", help="model pricing and cost math")
    s = p.add_subparsers(dest="action", required=True)
    r = s.add_parser("refresh", help="download the public LiteLLM price "
                     "list (Tuner's only network request; explicit only)")
    r.add_argument("--allow-network", action="store_true",
                   help="required while privacy.local_only is true")
    show = s.add_parser("show", help="show the rate for a model")
    show.add_argument("model")
    show.add_argument("--date")
    cost = s.add_parser("cost", help="deterministic cost for token counts")
    cost.add_argument("--model", required=True)
    for k in ("input", "output", "cache-read", "cache-write"):
        cost.add_argument(f"--{k}", type=int, default=0)
    cost.add_argument("--date")
    s.add_parser("info", help="pricing sources and override file path")
    p.set_defaults(func=run)


def run(args) -> int:
    """Dispatch pricing actions."""
    if args.action == "refresh":
        if load_config().privacy.local_only and not args.allow_network:
            raise TunerError("privacy.local_only is true; re-run with "
                             "--allow-network to fetch the public price "
                             "list (no usage data is sent)")
        try:
            table = litellm.convert(litellm.fetch())
        except OSError as exc:
            raise TunerError(f"could not fetch prices: {exc}") from exc
        print(f"saved {len(table['models'])} models -> "
              f"{save_cache(table)}")
        return 0
    book = PriceBook()
    if args.action == "info":
        emit_json({"meta": book.meta, "cache": str(cache_file()),
                   "overrides": str(overrides_file())})
    elif args.action == "show":
        rate = book.lookup(args.model, args.date)
        if rate is None:
            raise TunerError(f"no rate known for {args.model}")
        emit_json(rate.__dict__)
    else:
        row = {"model": args.model, "measurement": "estimated",
               "input_tokens": args.input, "output_tokens": args.output,
               "cache_read_tokens": args.cache_read,
               "cache_write_tokens": args.cache_write}
        emit_json(estimate_cost([row], book, args.date))
    return 0
