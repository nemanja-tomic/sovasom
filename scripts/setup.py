"""Prepare an office from .env and remove its initial-account entries after success."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values, unset_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--backup-gated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    path = args.env_file.resolve()
    if not path.is_file():
        parser.error("Environment file not found. Copy .env.example to .env and set credentials.")
    path.chmod(0o600)
    values = {
        key: value
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }
    runtime = {**values, **os.environ}
    initial_keys = ("INITIAL_EMAIL", "INITIAL_DISPLAY_NAME", "INITIAL_PASSWORD")
    payload = json.dumps(
        {
            "email": runtime.get("INITIAL_EMAIL", ""),
            "display_name": runtime.get("INITIAL_DISPLAY_NAME", ""),
            "password": runtime.get("INITIAL_PASSWORD", ""),
        }
    ).encode()
    # Only the short-lived initializer receives bootstrap values, on stdin.
    runtime = {key: value for key, value in runtime.items() if key not in initial_keys}

    def compose(*command, **kwargs):
        try:
            subprocess.run(
                ["docker", "compose", "--env-file", str(path), *command],
                env=runtime,
                check=True,
                **kwargs,
            )
        except subprocess.CalledProcessError as error:
            # The failed command already reported its cause; preserve its status.
            raise SystemExit(error.returncode) from None

    compose("build", "backend", "web")
    compose("up", "-d", "--wait", "db")
    if not args.backup_gated:
        probe = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("backup-host.py")),
                "probe",
                "--env-file",
                str(path),
            ],
            env=runtime,
            capture_output=True,
            text=True,
        )
        if probe.returncode or probe.stdout.strip() != "empty":
            print(
                "Existing or unknown database: use scripts/backup.py migrate from the "
                "Actions controller to verify an off-host backup before migrations.",
                file=sys.stderr,
            )
            raise SystemExit(1)
    compose(
        "run",
        "--rm",
        "-T",
        "--no-deps",
        "backend",
        "uv",
        "run",
        "--frozen",
        "--no-dev",
        "python",
        "-m",
        "office.setup",
        "--stdin",
        input=payload,
    )
    for key in initial_keys:
        if key in values:
            unset_key(path, key)
    compose("up", "-d", "--wait", "backend", "web")


if __name__ == "__main__":
    main()
