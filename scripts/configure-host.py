"""Transport setup inputs from GitHub secrets via pinned SSH, never via source archive."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from backup import Transfer

os.umask(0o077)
try:
    transfer = Transfer(json.loads(Path(sys.argv[1]).read_text()))
    directory = transfer.config["directory"] + "/tools"
    with tempfile.TemporaryFile() as archive:
        subprocess.run(["git", "archive", "HEAD"], stdout=archive, check=True)
        archive.seek(0)
        transfer.remote(
            f"umask 077; mkdir -p {shlex.quote(directory)} && "
            f"tar -xf - -C {shlex.quote(directory)}",
            stdin=archive,
        )
    command = shlex.join(
        [
            "uv",
            "run",
            "--frozen",
            "python",
            "scripts/provision-host.py",
            "--root",
            transfer.config["directory"],
        ]
    )
    transfer.remote(
        f"cd {shlex.quote(directory)} && {command}", input=os.environ["SETUP_JSON"].encode()
    )
except Exception:
    print(
        "Host configuration failed; inspect private setup inputs and SSH access.", file=sys.stderr
    )
    sys.exit(1)
