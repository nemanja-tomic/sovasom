"""Post-login recovery; do not restart services deliberately stopped during maintenance."""

import argparse
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
if (args.root / "active.json").exists() and not (args.root / "maintenance").exists():
    release = json.loads((args.root / "active.json").read_text())["release"]
    script = args.root / "releases" / release / "scripts/deploy-host.py"
    subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "python",
            str(script),
            "--root",
            str(args.root),
            "--release",
            release,
            "recover",
        ],
        cwd=script.parents[1],
        check=True,
    )
