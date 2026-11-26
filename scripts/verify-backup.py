"""Disposable PostgreSQL/age recovery drill; no operator data."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from office.app import create_app
from office.config import Settings
from sqlalchemy import create_engine, text


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="office-backup-drill-") as directory:
        root = Path(directory)
        name = "office-recovery-" + uuid.uuid4().hex[:12]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = root / ".env"
        config.write_text(
            "DATABASE_PASSWORD=synthetic-recovery-only\n"
            "SITE_ADDRESS=localhost\nPUBLIC_ORIGIN=https://testserver\n"
        )
        config.chmod(0o600)
        override = root / "ports.json"
        override.write_text(
            json.dumps(
                {
                    "services": {"db": {"ports": [f"127.0.0.1:{port}:5432"]}},
                    "networks": {"data": {"internal": False}},
                }
            )
        )
        env = {
            **os.environ,
            "COMPOSE_PROJECT_NAME": name,
            "COMPOSE_FILE": str(Path("compose.yaml").resolve()) + os.pathsep + str(override),
            "DATABASE_URL": f"postgresql+psycopg://office:synthetic-recovery-only@127.0.0.1:{port}/office",
            "PYTHONPATH": str(Path("backend").resolve()),
        }

        def run(*args, **kwargs):
            return subprocess.run(args, env=env, check=True, **kwargs)

        try:
            probe = run(
                sys.executable,
                "scripts/backup-host.py",
                "probe",
                "--env-file",
                str(config),
                capture_output=True,
                text=True,
            )
            assert probe.stdout.strip() == "empty"
            engine = create_engine(env["DATABASE_URL"], connect_args={"connect_timeout": 2})
            for attempt in range(30):
                try:
                    with engine.connect() as connection:
                        connection.execute(text("SELECT 1"))
                    break
                except Exception:
                    if attempt == 29:
                        raise RuntimeError("Disposable PostgreSQL port is unreachable") from None
                    time.sleep(1)
            engine.dispose()
            run(
                sys.executable,
                "-m",
                "office.setup",
                "--stdin",
                input=json.dumps(
                    {
                        "email": "recovery@example.com",
                        "display_name": "Recovery colleague",
                        "password": "synthetic recovery password",
                    }
                ).encode(),
                stdout=subprocess.DEVNULL,
            )
            existing = run(
                sys.executable,
                "scripts/backup-host.py",
                "probe",
                "--env-file",
                str(config),
                capture_output=True,
                text=True,
            )
            assert existing.stdout.strip() == "existing"
            identity = root / "identity"
            run("age-keygen", "-o", str(identity), stderr=subprocess.DEVNULL)
            recipient = run(
                "age-keygen", "-y", str(identity), capture_output=True, text=True
            ).stdout.strip()
            archive = root / "archive.age"
            with archive.open("wb") as output:
                run(
                    sys.executable,
                    "scripts/backup-host.py",
                    "backup",
                    "--env-file",
                    str(config),
                    "--recipient",
                    recipient,
                    stdout=output,
                )
            restore = [
                sys.executable,
                "scripts/backup-host.py",
                "restore",
                "--env-file",
                str(config),
                "--archive",
                str(archive),
                "--identity",
                str(identity),
                "--database",
                "office_restore_drill",
            ]
            restore_started = time.monotonic()
            run(*restore)
            restore_seconds = time.monotonic() - restore_started
            # A second restore must refuse to overwrite its successful first result.
            refused = subprocess.run(restore, env=env, capture_output=True)
            assert refused.returncode != 0
            restored_url = env["DATABASE_URL"].removesuffix("/office") + "/office_restore_drill"
            with TestClient(
                create_app(Settings(_env_file=None, database_url=restored_url)),
                base_url="https://testserver",
            ) as client:
                token = client.get("/api/auth/csrf").json()["csrf_token"]
                login = client.post(
                    "/api/auth/login",
                    json={
                        "email": "recovery@example.com",
                        "password": "synthetic recovery password",
                    },
                    headers={"Origin": "https://testserver", "X-CSRF-Token": token},
                )
                assert login.status_code == 200
                account = login.json()["account"]
                assert account["display_name"] == "Recovery colleague"
                assert account["is_administrator"] and account["is_menu_maintainer"]
                assert client.get("/api/office/home").status_code == 200
            # Truncated ciphertext cannot create a successful new recovery database.
            archive.write_bytes(archive.read_bytes()[:-20])
            corrupt = subprocess.run(
                restore[:-1] + ["office_restore_corrupt"], env=env, capture_output=True
            )
            assert corrupt.returncode != 0
            print(
                f"Archive restore took {restore_seconds:.1f} seconds; "
                f"restore/sign-in/permissions and refusal checks passed in "
                f"{time.monotonic() - started:.1f} seconds.",
                flush=True,
            )
        finally:
            subprocess.run(
                ["docker", "compose", "--env-file", str(config), "down", "--volumes"],
                env=env,
                check=False,
                stdout=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()
