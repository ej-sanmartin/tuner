"""Check that the built wheel and sdist ship the files Tuner needs.

Usage: python scripts/check_wheel.py [dist-dir]  (default: dist)
"""

import sys
import tarfile
import zipfile
from pathlib import Path

WHEEL_NEEDED = (
    "tuner/_agent_skills/tuner/SKILL.md",
    "tuner/reports/templates/report.html",
    "tuner/pricing/data/pricing_snapshot.json",
)
SDIST_NEEDED = ("agent-skills/tuner/SKILL.md", "README.md", "LICENSE")


def main(dist: Path) -> int:
    """Assert required files are in the wheel and sdist; return exit code."""
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"expected one wheel and one sdist in {dist}")
        return 1
    names = zipfile.ZipFile(wheels[0]).namelist()
    missing = [n for n in WHEEL_NEEDED if n not in names]
    with tarfile.open(sdists[0]) as tar:
        members = tar.getnames()
    missing += [n for n in SDIST_NEEDED
                if not any(m.endswith("/" + n) for m in members)]
    if missing:
        print("missing from distributions:", ", ".join(missing))
        return 1
    print("distributions ok:", wheels[0].name, sdists[0].name)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "dist")))
