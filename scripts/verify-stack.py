"""Run isolated, synthetic full-stack checks and always remove this test stack's volumes."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from dotenv import dotenv_values, set_key
from sqlalchemy import URL


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    with tempfile.TemporaryDirectory(prefix="office-tests-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        https_port = free_port()
        config = root / ".env"
        values = {
            "DATABASE_PASSWORD": "synthetic:p@ss/$word#${UNCHANGED}",
            "SITE_ADDRESS": "localhost",
            "PUBLIC_ORIGIN": f"https://localhost:{https_port}",
            "HTTP_PORT": str(free_port()),
            "HTTPS_PORT": str(https_port),
            "INITIAL_EMAIL": "colleague@example.com",
            "INITIAL_DISPLAY_NAME": "Test colleague",
            "INITIAL_PASSWORD": "synthetic password only",
        }
        for key, value in values.items():
            set_key(config, key, value)
        config.chmod(0o600)
        env = {
            **{key: value for key, value in os.environ.items() if key not in values},
            "COMPOSE_PROJECT_NAME": "office-test-" + uuid.uuid4().hex[:12],
            "COMPOSE_ENV_FILES": str(config),
            "E2E_BASE_URL": f"https://localhost:{https_port}",
            "OFFICE_TEST_STACK": "1",
            "TEST_DATABASE_URL": URL.create(
                "postgresql+psycopg",
                username="office",
                host="db",
                database="office",
                password=values["DATABASE_PASSWORD"],
            ).render_as_string(hide_password=False),
        }

        def run(*args, **kwargs):
            return subprocess.run(args, env=env, check=True, **kwargs)

        try:
            run(sys.executable, "scripts/setup.py", "--env-file", str(config), "--backup-gated")
            runtime = dotenv_values(config, interpolate=False)
            assert not any(key.startswith("INITIAL_") for key in runtime)
            assert runtime["DATABASE_PASSWORD"] == values["DATABASE_PASSWORD"]
            # Inspect the rendered service configuration without printing secret values.
            rendered = json.loads(
                run(
                    "docker",
                    "compose",
                    "config",
                    "--format",
                    "json",
                    capture_output=True,
                    text=True,
                ).stdout
            )
            for name, service in rendered["services"].items():
                environment = service.get("environment", {})
                assert not any(key.startswith("INITIAL_") for key in environment)
                if name == "web":
                    assert "DATABASE_PASSWORD" not in environment
                    assert "POSTGRES_PASSWORD" not in environment
            # Rerun with different inputs; browser login below proves original credentials survive.
            for key, value in {
                "INITIAL_EMAIL": "changed@example.com",
                "INITIAL_DISPLAY_NAME": "Changed",
                "INITIAL_PASSWORD": "changed synthetic password",
            }.items():
                set_key(config, key, value)
            run(sys.executable, "scripts/setup.py", "--env-file", str(config), "--backup-gated")
            assert not any(key.startswith("INITIAL_") for key in dotenv_values(config))
            run("docker", "compose", "--profile", "test", "run", "--build", "--rm", "backend-tests")
            run("npm", "run", "test:e2e", "--", "--grep-invert", "service restart", cwd="frontend")
            env["PERSISTED_SESSION_FILE"] = str(root / "browser-session")
            env["PERSISTENCE_PHASE"] = "save"
            run("npm", "run", "test:e2e", "--", "--grep", "service restart", cwd="frontend")
            # Persisted database/session storage must survive application and DB restart.
            run("docker", "compose", "restart", "db", "backend")
            run("docker", "compose", "up", "-d", "--wait", "backend", "web")
            env["PERSISTENCE_PHASE"] = "restore"
            run("npm", "run", "test:e2e", "--", "--grep", "service restart", cwd="frontend")
        finally:
            subprocess.run(
                ["docker", "compose", "--profile", "test", "down", "--volumes", "--remove-orphans"],
                env=env,
                check=False,
            )


if __name__ == "__main__":
    main()
