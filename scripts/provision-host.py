"""Run on the intended mini over verified SSH; JSON setup inputs arrive on stdin."""

import argparse
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve()
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise ValueError("This installation targets an Intel macOS mini")
    # Execute through SSH as the same logged-in user that owns Docker Desktop.
    subprocess.run(["docker", "compose", "version"], check=True, stdout=subprocess.DEVNULL)
    info = json.loads(subprocess.check_output(["docker", "info", "--format", "{{json .}}"]))
    if info["OSType"] != "linux" or info["Architecture"] not in {"x86_64", "amd64"}:
        raise ValueError("Linux amd64 Desktop context required")
    if info["NCPU"] < 2 or info["MemTotal"] < 4 * 1024**3:
        raise ValueError("Allocate at least two CPUs and 4 GiB to Desktop")
    values = json.load(sys.stdin)
    hostname = values["hostname"]
    if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", hostname):
        raise ValueError("Public hostname required")
    password = values["database_password"]
    if len(password) < 32 or "\n" in password:
        raise ValueError("Use a generated single-line password of at least 32 characters")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    secret = root / "database-password"
    if secret.exists() and secret.read_text() != password:
        raise ValueError("Use coordinated role-password rotation; setup cannot reset PostgreSQL")
    if not secret.exists():
        secret.write_text(password)
    # Directory restricts host traversal; container UID 10001 must read the bind mount.
    secret.chmod(0o444)
    (root / "runtime.env").write_text(
        f"SITE_ADDRESS={hostname}\nPUBLIC_ORIGIN=https://{hostname}\n"
    )
    if "bootstrap" in values and not (root / "active.json").exists():
        (root / "bootstrap.json").write_text(json.dumps(values["bootstrap"]))
    (root / "backup-recipient.txt").write_text(values["backup_recipient"])
    # Recovery waits for Desktop's user login item and retries every 30 seconds.
    executable = str(Path(sys.executable).resolve())
    helper = Path(__file__).with_name("recover-host.py").resolve()
    destination = Path.home() / "Library/LaunchAgents/com.office.recovery.plist"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.office.recovery",
                "RunAtLoad": True,
                "StartInterval": 30,
                "ProgramArguments": [executable, str(helper), "--root", str(root)],
                "EnvironmentVariables": {"PATH": os.environ["PATH"]},
            }
        )
    )
    print("Configuration written. Load the LaunchAgent; complete private acceptance evidence.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(
            "Host setup failed; verify compatibility, Desktop context and private inputs.",
            file=sys.stderr,
        )
        sys.exit(1)
