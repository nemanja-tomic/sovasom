"""Actions-side encrypted archive transfer, freshness check and migration gate."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path


class BackupError(Exception):
    pass


def run(command, **kwargs):
    try:
        return subprocess.run(command, check=True, stderr=subprocess.DEVNULL, **kwargs)
    except OSError, subprocess.CalledProcessError:
        raise BackupError("External backup operation failed; migration is blocked.") from None


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ssh_port(value=22):
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,5}", text) or not 1 <= int(text) <= 65535:
        raise ValueError("SSH port must be an integer from 1 to 65535.")
    return str(int(text))


class Transfer:
    def __init__(self, config):
        self.config = config
        self.bucket = config["bucket"]
        self.prefix = config["prefix"]
        if not re.fullmatch(r"archives/[a-zA-Z0-9/_-]+/", self.prefix):
            raise BackupError("Use a dedicated archives/ namespace ending in /.")
        if not re.fullmatch(r"[a-zA-Z0-9_.@-]+", config["host"]):
            raise BackupError("Invalid SSH destination.")
        self.ssh = [
            "ssh",
            "-T",
            "-p",
            ssh_port(config.get("port", 22)),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "ConnectTimeout=30",
            "-o",
            f"UserKnownHostsFile={config['known_hosts']}",
            "-i",
            config["ssh_identity"],
            config["host"],
        ]

    def remote(self, command, **kwargs):
        directory = shlex.quote(self.config["directory"])
        return run([*self.ssh, f"cd {directory} && {command}"], **kwargs)

    def aws(self, operation, *arguments):
        result = run(
            ["aws", "--output", "json", "s3api", operation, "--bucket", self.bucket, *arguments],
            stdout=subprocess.PIPE,
        )
        return json.loads(result.stdout)

    def backup(self, kind, source_command="uv run --frozen python scripts/backup-host.py backup"):
        with tempfile.TemporaryDirectory(prefix="office-ciphertext-") as directory:
            root = Path(directory)
            archive = root / "archive.age"
            with archive.open("wb") as output:
                self.remote(source_command, stdout=output)
            with archive.open("rb") as source:
                header = source.read(32)
            if archive.stat().st_size < 32 or not header.startswith(b"age-encryption.org/v1\n"):
                raise BackupError("Missing or invalid encrypted archive.")
            checksum = digest(archive)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            name = f"{stamp}-{uuid.uuid4().hex}"
            key = f"{self.prefix}{kind}/{name}.dump.age"
            uploaded = self.aws(
                "put-object",
                "--key",
                key,
                "--body",
                str(archive),
                "--metadata",
                json.dumps({"sha256": checksum}),
                "--checksum-algorithm",
                "SHA256",
            )
            version = uploaded.get("VersionId")
            if not version:
                raise BackupError("Backup bucket must have versioning enabled.")
            received = root / "received.age"
            # Read the exact uploaded version; a successful PUT alone is insufficient.
            self.aws("get-object", "--key", key, "--version-id", version, str(received))
            if digest(received) != checksum:
                raise BackupError("Uploaded archive failed checksum verification.")
            marker = root / "success.json"
            marker.write_text(
                json.dumps(
                    {
                        "archive": key,
                        "version": version,
                        "sha256": checksum,
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                )
            )
            self.aws(
                "put-object",
                "--key",
                f"{self.prefix}success/{name}.json",
                "--body",
                str(marker),
                "--checksum-algorithm",
                "SHA256",
            )
        print("Backup verified; success recorded off-host.")

    def status(self, max_age_hours):
        objects = self.aws("list-objects-v2", "--prefix", f"{self.prefix}success/")
        # AWS CLI auto-pagination merges Contents; do not use --max-items.
        contents = objects.get("Contents", [])
        if not contents:
            raise BackupError("No successful backup recorded; retry the manual backup workflow.")
        latest = max(contents, key=lambda item: item["LastModified"])
        modified = datetime.fromisoformat(latest["LastModified"].replace("Z", "+00:00"))
        age = (datetime.now(UTC) - modified).total_seconds() / 3600
        print(f"Last successful backup: {modified.isoformat()}; age hours: {age:.1f}")
        if age > max_age_hours or age < -1:
            raise BackupError("Backup is stale; retry the manual backup workflow.")

    def migrate(self):
        probe = self.remote(
            "uv run --frozen python scripts/backup-host.py probe", stdout=subprocess.PIPE
        ).stdout.strip()
        if probe == b"existing":
            self.backup("pre-migration")
        elif probe != b"empty":
            raise BackupError("Database state unknown; migration is blocked.")
        # Only reached after this invocation verifies its own upload, or proves an empty DB.
        self.remote("uv run --frozen python scripts/setup.py --backup-gated", stdout=sys.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("operation", choices=["backup", "status", "migrate"])
    parser.add_argument("--max-age-hours", type=float, default=192)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        transfer = Transfer(json.loads(args.config.read_text()))
        if args.operation == "status":
            transfer.status(args.max_age_hours)
        elif args.operation == "migrate":
            transfer.migrate()
        else:
            transfer.backup("weekly")
            transfer.status(args.max_age_hours)
    except BackupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError, ValueError, KeyError:
        print(
            "Backup/recovery operation failed. Check access, archive integrity and freshness; "
            "manual retry is available. No migration was authorized by a failed backup.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
