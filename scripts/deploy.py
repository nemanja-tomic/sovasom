"""Actions controller: verified SSH, encrypted backup gate, immutable release activation."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from backup import BackupError, Transfer


class Deployment(Transfer):
    def __init__(self, config, release):
        super().__init__(config)
        if not re.fullmatch(r"[a-f0-9]{40}", release):
            raise ValueError("Invalid revision")
        self.release = release
        self.root = config["directory"]
        self.directory = f"{self.root}/releases/{release}"

    def command_text(self, operation):
        command = shlex.join(
            [
                "uv",
                "run",
                "--frozen",
                "python",
                "scripts/deploy-host.py",
                "--root",
                self.root,
                "--release",
                self.release,
                operation,
            ]
        )
        return f"cd {shlex.quote(self.directory)} && {command}"

    def command(self, operation, **kwargs):
        return self.remote(self.command_text(operation), **kwargs)

    def deploy(self):
        with tempfile.TemporaryDirectory(prefix="release-source-") as directory:
            archive = Path(directory) / "source.tar"
            with archive.open("wb") as stream:
                subprocess.run(["git", "archive", self.release], check=True, stdout=stream)
            prepare = shlex.join(["mkdir", "-p", self.directory])
            extract = shlex.join(["tar", "-xf", "-", "-C", self.directory])
            with archive.open("rb") as stream:
                # Host root is provisioned first, mode 0700. No secret traverses the archive.
                Transfer.remote(self, f"{prepare} && {extract}", stdin=stream)
        metadata = {"backend": os.environ["BACKEND_IMAGE"], "web": os.environ["WEB_IMAGE"]}
        store_metadata = (
            "import json,sys; from pathlib import Path; "
            "p=Path('release.json'); new=json.load(sys.stdin); "
            "old=json.loads(p.read_text()) if p.exists() else new; "
            "assert old == new, 'Revision already has different pinned images'; "
            "p.write_text(json.dumps(new))"
        )
        self.remote(
            f"cd {shlex.quote(self.directory)} && "
            + shlex.join(["uv", "run", "--frozen", "python", "-c", store_metadata]),
            input=json.dumps(metadata).encode(),
        )
        # Stable .env is nonsecret and makes ticket-16 backup commands select release Compose.
        configuration = (
            f"COMPOSE_FILE=compose.release.yaml\nCOMPOSE_PROJECT_NAME=office\n"
            f"BACKEND_IMAGE={metadata['backend']}\nWEB_IMAGE={metadata['web']}\n"
            f"SECRET_DIRECTORY='{self.root}'\n"
        )
        Transfer.remote(
            self,
            f"cat {shlex.quote(self.root + '/runtime.env')} > "
            f"{shlex.quote(self.directory + '/.env')} && cat >> "
            f"{shlex.quote(self.directory + '/.env')}",
            input=configuration.encode(),
        )
        Transfer.remote(
            self,
            shlex.join(
                [
                    "ln",
                    "-sf",
                    self.root + "/backup-recipient.txt",
                    self.directory + "/backup-recipient.txt",
                ]
            ),
        )
        self.command(
            "pull",
            input=json.dumps(
                {"username": os.environ["REGISTRY_USER"], "token": os.environ["REGISTRY_TOKEN"]}
            ).encode(),
        )
        # Stop writes before probing/backing up. Any failure leaves maintenance in effect.
        self.command("stop", stdout=subprocess.DEVNULL)
        probe = self.command("probe", stdout=subprocess.PIPE).stdout.strip()
        if probe == b"existing":
            self.backup("pre-migration", source_command=self.command_text("backup"))
        elif probe != b"empty":
            raise BackupError("Unknown database state; migration blocked")
        self.command("migrate")
        self.command("activate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("operation", choices=["deploy", "rollback"])
    args = parser.parse_args()
    os.umask(0o077)
    try:
        deployment = Deployment(json.loads(args.config.read_text()), args.release)
        if args.operation == "rollback":
            deployment.command("rollback")
        else:
            deployment.deploy()
        print("Release healthy; record public HTTPS/browser verification privately.")
        return 0
    except BackupError, OSError, ValueError, KeyError, subprocess.CalledProcessError:
        print(
            "Deployment failed; maintenance may remain active. Recover using the runbook. "
            "Database migrations were not reversed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
