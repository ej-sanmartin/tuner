"""Regenerate the bundled pricing snapshot from LiteLLM (maintainers)."""

import json
import sys
from pathlib import Path

from tuner.pricing import litellm

OUT = (Path(__file__).parents[1] / "src/tuner/pricing/data"
       / "pricing_snapshot.json")


def main() -> int:
    """Fetch (or read a local file) and write the filtered snapshot."""
    raw = (json.loads(Path(sys.argv[1]).read_text())
           if len(sys.argv) > 1 else litellm.fetch())
    OUT.write_text(json.dumps(litellm.convert(raw), indent=1,
                              sort_keys=True) + "\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
