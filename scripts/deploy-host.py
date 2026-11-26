"""Host-side immutable release operations. Invoke through the serialized controller."""

import argparse
import base64
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command, **kwargs):
    return subprocess.run(command, check=True, stderr=subprocess.DEVNULL, **kwargs)


class Host:
    def __init__(self, root, release):
        if not re.fullmatch(r"[a-f0-9]{40}", release):
            raise ValueError("Invalid release")
        self.root = root.resolve()
        self.directory = self.root / "releases" / release
        self.release = release
        self.images = json.loads((self.directory / "release.json").read_text())
        for name in ("backend", "web"):
            if not re.fullmatch(r"ghcr.io/[a-z0-9_./-]+@sha256:[a-f0-9]{64}", self.images[name]):
                raise ValueError("Immutable GHCR digest required")
        self.env = {
            **os.environ,
            "BACKEND_IMAGE": self.images["backend"],
            "WEB_IMAGE": self.images["web"],
            "SECRET_DIRECTORY": str(self.root),
            "COMPOSE_FILE": str(self.directory / "compose.release.yaml"),
        }
        self.compose = [
            "docker",
            "compose",
            "--env-file",
            str(self.root / "runtime.env"),
            "--project-name",
            "office",
            "-f",
            self.env["COMPOSE_FILE"],
        ]

    def docker(self, *command, **kwargs):
        return run([*self.compose, *command], env=self.env, cwd=self.directory, **kwargs)

    def schema(self):
        return (
            self.docker(
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "office",
                "-d",
                "office",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "SELECT version_num FROM alembic_version ORDER BY version_num",
                stdout=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    def start(self):
        self.docker("up", "-d", "--wait", "--wait-timeout", "180", "--pull", "never")

    def pull(self, credentials):
        # Seed explicit inline auths, bypassing login's automatic native-helper selection.
        # No login is issued and no credsStore/credHelpers are inherited from Desktop.
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        transport = {**os.environ, "DOCKER_HOST": os.environ.get("DOCKER_HOST") or endpoint}
        transport.pop("DOCKER_CONTEXT", None)
        with tempfile.TemporaryDirectory(prefix="registry-", dir=self.root) as directory:
            config = Path(directory) / "config.json"
            auth = base64.b64encode(
                f"{credentials['username']}:{credentials['token']}".encode()
            ).decode()
            config.write_text(json.dumps({"auths": {"ghcr.io": {"auth": auth}}}))
            config.chmod(0o600)
            try:
                for image in self.images.values():
                    run(
                        [
                            "docker",
                            "--config",
                            directory,
                            "pull",
                            "--platform",
                            "linux/amd64",
                            image,
                        ],
                        stdout=subprocess.DEVNULL,
                        env=transport,
                    )
            finally:
                run(
                    ["docker", "--config", directory, "logout", "ghcr.io"],
                    stdout=subprocess.DEVNULL,
                    env=transport,
                )

    def backup(self, operation):
        return run(
            [
                sys.executable,
                str(self.directory / "scripts/backup-host.py"),
                operation,
                "--env-file",
                str(self.root / "runtime.env"),
            ],
            env={**self.env, "COMPOSE_PROJECT_NAME": "office"},
            cwd=self.directory,
        )

    def migrate(self):
        # Controller invokes this only after its own verified off-host upload/empty probe.
        bootstrap = self.root / "bootstrap.json"
        if bootstrap.exists():
            self.docker(
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "--pull",
                "never",
                "backend",
                "uv",
                "run",
                "--frozen",
                "--no-dev",
                "python",
                "-m",
                "office.setup",
                "--stdin",
                input=bootstrap.read_bytes(),
            )
            bootstrap.unlink()
        else:
            self.docker(
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "--pull",
                "never",
                "backend",
                "uv",
                "run",
                "--frozen",
                "--no-dev",
                "alembic",
                "upgrade",
                "head",
            )

    def activate(self):
        self.start()
        active = self.root / "active.json"
        if active.exists() and json.loads(active.read_text())["release"] != self.release:
            (self.root / "previous.json").write_bytes(active.read_bytes())
        record = {"release": self.release, "schema": self.schema()}
        temporary = self.root / "active.next"
        temporary.write_text(json.dumps(record))
        temporary.replace(active)
        link = self.root / "current.next"
        link.symlink_to(self.directory, target_is_directory=True)
        link.replace(self.root / "current")
        (self.root / "maintenance").unlink(missing_ok=True)

    def rotate_password(self, password):
        if len(password) < 32 or any(char in password for char in "\n\r\x00"):
            raise ValueError("Generated single-line password required")
        (self.root / "maintenance").touch()
        self.docker("stop", "web", "backend")
        staged = self.root / "database-password.next"
        if staged.exists():
            staged.chmod(0o600)
        staged.write_text(password)
        staged.chmod(0o444)
        # psql input and stderr are private: payload never appears in argv or logs.
        sql = "ALTER ROLE office PASSWORD '" + password.replace("'", "''") + "';\n"
        self.docker(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "office",
            "-d",
            "office",
            "-v",
            "ON_ERROR_STOP=1",
            input=sql.encode(),
            stdout=subprocess.DEVNULL,
        )
        staged.replace(self.root / "database-password")
        self.docker("up", "-d", "--wait", "--force-recreate", "--pull", "never")
        (self.root / "maintenance").unlink(missing_ok=True)

    def rollback(self):
        previous = json.loads((self.root / "previous.json").read_text())
        if self.schema() != previous["schema"]:
            raise ValueError("Schema changed; restore to an isolated DB or deploy forward")
        # Conservative compatibility: exact migration revision equality is required.
        Host(self.root, previous["release"]).activate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument(
        "operation",
        choices=[
            "pull",
            "stop",
            "probe",
            "backup",
            "migrate",
            "activate",
            "rollback",
            "schema",
            "recover",
            "rotate-password",
        ],
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        with (args.root / "host.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return perform(args)
    except OSError, ValueError, KeyError, subprocess.CalledProcessError:
        print(
            "Release operation failed; maintenance may remain active. No schema rollback "
            "was attempted.",
            file=sys.stderr,
        )
        return 1


def perform(args):
    try:
        if args.operation == "recover":
            # Recheck both maintenance and accepted release while holding the common lock.
            if (args.root / "maintenance").exists():
                return 0
            args.release = json.loads((args.root / "active.json").read_text())["release"]
        host = Host(args.root, args.release)
        match args.operation:
            case "pull":
                host.pull(json.load(sys.stdin))
            case "stop":
                active = host.root / "active.json"
                if active.exists() and json.loads(active.read_text())["release"] != host.release:
                    (host.root / "previous.json").write_bytes(active.read_bytes())
                (host.root / "maintenance").touch()
                host.docker("stop", "web", "backend")
            case "probe" | "backup":
                host.backup(args.operation)
            case "migrate":
                host.migrate()
            case "activate":
                host.activate()
            case "rollback":
                host.rollback()
            case "schema":
                print(host.schema())
            case "recover":
                host.start()
            case "rotate-password":
                host.rotate_password(json.load(sys.stdin)["password"])
        return 0
    except OSError, ValueError, KeyError, subprocess.CalledProcessError:
        print(
            "Release operation failed. Services may be stopped; inspect private evidence. "
            "No schema rollback was attempted.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
