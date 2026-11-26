"""Mini-side backup and isolated recovery. No AWS credentials or stored private identity."""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command, **kwargs):
    return subprocess.run(command, check=True, stderr=subprocess.DEVNULL, **kwargs)


def validate_dump(compose, archive):
    # Decode the entire dump, not merely its table of contents.
    with archive.open("rb") as source:
        run([*compose, "pg_restore", "--file=/dev/null"], stdin=source, stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "probe", "restore"])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--recipient", help="Public age recipient; defaults to backup-recipient.txt"
    )
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--database")
    args = parser.parse_args()
    os.umask(0o077)
    compose = ["docker", "compose", "--env-file", args.env_file, "exec", "-T", "db"]
    try:
        if args.operation == "probe":
            # The empty-install gate must work before the database service exists.
            run(
                ["docker", "compose", "--env-file", args.env_file, "up", "-d", "--wait", "db"],
                stdout=subprocess.DEVNULL,
            )
            result = run(
                [
                    *compose,
                    "psql",
                    "-U",
                    "office",
                    "-d",
                    "office",
                    "-At",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname NOT IN "
                    "('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' "
                    "AND c.relkind IN ('r','p')",
                ],
                stdout=subprocess.PIPE,
            )
            count = int(result.stdout.strip())
            print("existing" if count else "empty")
            return 0
        if args.operation == "restore":
            if not args.database or not re.fullmatch(
                r"office_restore_[a-z0-9_]{1,40}", args.database
            ):
                parser.error("Recovery requires a fresh office_restore_ database name.")
            if not args.identity or not args.archive:
                parser.error("Recovery requires --identity and --archive.")
        with tempfile.TemporaryDirectory(prefix="office-recovery-") as directory:
            raw = Path(directory) / "database.dump"
            if args.operation == "backup":
                recipient = args.recipient or Path("backup-recipient.txt").read_text().strip()
                with raw.open("wb") as output:
                    run(
                        [
                            *compose,
                            "pg_dump",
                            "-U",
                            "office",
                            "-d",
                            "office",
                            "--format=custom",
                            "--no-owner",
                            "--no-acl",
                        ],
                        stdout=output,
                    )
                validate_dump(compose, raw)
                run(["age", "--recipient", recipient, str(raw)], stdout=sys.stdout.buffer)
            else:
                with raw.open("wb") as output:
                    run(
                        ["age", "--decrypt", "--identity", str(args.identity), str(args.archive)],
                        stdout=output,
                    )
                validate_dump(compose, raw)
                # createdb fails if the name exists. Never clean, overwrite or drop anything.
                run(
                    [*compose, "createdb", "-U", "office", "--template=template0", args.database],
                    stdout=subprocess.DEVNULL,
                )
                with raw.open("rb") as source:
                    run(
                        [
                            *compose,
                            "pg_restore",
                            "-U",
                            "office",
                            "--dbname",
                            args.database,
                            "--exit-on-error",
                            "--single-transaction",
                            "--no-owner",
                            "--no-acl",
                        ],
                        stdin=source,
                        stdout=subprocess.DEVNULL,
                    )
                print(
                    "Archive restored into a fresh isolated database. Verify application sign-in."
                )
        return 0
    except OSError, ValueError, subprocess.CalledProcessError:
        print(
            "Host backup/recovery failed; check database, archive and key access. "
            "No existing database was overwritten.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
