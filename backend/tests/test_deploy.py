"""Release CLI behavior at the Docker process boundary (synthetic data only)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "host"
    release = root / "releases" / ("a" * 40)
    release.mkdir(parents=True)
    (release / "compose.release.yaml").write_text("services: {}")
    (release / "release.json").write_text(
        json.dumps(
            {
                "backend": "ghcr.io/fictional/office-backend@sha256:" + "1" * 64,
                "web": "ghcr.io/fictional/office-web@sha256:" + "2" * 64,
            }
        )
    )
    (root / "runtime.env").write_text("COMPOSE_PROJECT_NAME=office-release-test\n")
    (root / "database-password").write_text("synthetic-only")
    log = tmp_path / "commands"
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
with open(os.environ['COMMAND_LOG'], 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if 'FAIL_COMMAND' in os.environ and os.environ['FAIL_COMMAND'] in sys.argv: sys.exit(1)
if 'alembic_version' in ' '.join(sys.argv): print('0001_accounts')
if 'info' in sys.argv:
 print(json.dumps({'OSType':'linux','Architecture':'amd64','NCPU':4,'MemTotal':8589934592}))
"""
    )
    docker.chmod(0o700)

    def run(operation, payload="", **env):
        return subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts/deploy-host.py"),
                "--root",
                str(root),
                "--release",
                "a" * 40,
                operation,
            ],
            input=payload,
            env={
                **os.environ,
                "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                "COMMAND_LOG": str(log),
                **env,
            },
            capture_output=True,
            text=True,
        )

    return run, root, log


def test_pull_uses_ephemeral_credentials_and_cleans_up_on_failure(host):
    run, root, log = host
    result = run(
        "pull",
        json.dumps({"username": "synthetic", "token": "synthetic-token"}),
        FAIL_COMMAND="pull",
    )
    assert result.returncode != 0
    assert not list(root.glob("registry-*"))
    assert "synthetic-token" not in result.stdout + result.stderr + log.read_text()
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert any("logout" in command for command in commands)


def test_rollback_refuses_schema_mismatch_before_starting_old_images(host):
    run, root, log = host
    (root / "previous.json").write_text(json.dumps({"schema": "older", "release": "b" * 40}))
    result = run("rollback")
    assert result.returncode != 0
    assert not any('"up"' in line for line in log.read_text().splitlines())


def test_healthy_activation_retains_previous_and_clears_maintenance(host):
    run, root, log = host
    (root / "active.json").write_text(json.dumps({"release": "b" * 40, "schema": "0001_accounts"}))
    (root / "maintenance").touch()
    result = run("activate")
    assert result.returncode == 0, result.stderr
    assert json.loads((root / "previous.json").read_text())["release"] == "b" * 40
    assert not (root / "maintenance").exists()
    assert (root / "current").resolve().name == "a" * 40
    assert run("stop").returncode == 0
    result = run("activate")
    assert result.returncode == 0
    assert json.loads((root / "previous.json").read_text())["release"] == "b" * 40


def test_immutable_images_are_required_before_docker_is_called(host):
    run, root, log = host
    (root / "releases" / ("a" * 40) / "release.json").write_text(
        json.dumps(
            {"backend": "ghcr.io/fictional/office:latest", "web": "ghcr.io/fictional/web:latest"}
        )
    )
    assert run("activate").returncode != 0
    assert not log.exists()


def test_password_rotation_changes_role_before_recreating_services(host):
    run, root, log = host
    result = run(
        "rotate-password", json.dumps({"password": "synthetic-rotated-password-32-characters"})
    )
    assert result.returncode == 0, result.stderr
    assert (root / "database-password").read_text() == "synthetic-rotated-password-32-characters"
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert any("psql" in command for command in commands)
    assert any("--force-recreate" in command for command in commands)
    assert "synthetic-rotated-password" not in result.stdout + result.stderr + log.read_text()


@pytest.mark.parametrize("state", ["empty", "existing", "unknown"])
def test_controller_gates_migrations_on_known_empty_or_verified_upload(tmp_path, state):
    commands = tmp_path / "commands"
    for name, source in {
        "ssh": """import os,sys
with open(os.environ['COMMAND_LOG'],'a') as f: f.write(sys.argv[-1]+'\\n')
if sys.argv[-1].endswith(' probe'): print(os.environ['DB_STATE'])
if sys.argv[-1].endswith(' backup'):
 sys.stdout.buffer.write(b'age-encryption.org/v1\\nsynthetic ciphertext')
""",
        "aws": "import sys; sys.exit(1)\n",
    }.items():
        binary = tmp_path / name
        binary.write_text(f"#!{sys.executable}\n" + source)
        binary.chmod(0o700)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "host": "deploy@mini.example.com",
                "directory": "/srv/office",
                "bucket": "fictional-backups",
                "prefix": "archives/office/",
                "known_hosts": "/tmp/hosts",
                "ssh_identity": "/tmp/key",
            }
        )
    )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/deploy.py"),
            "--config",
            str(config),
            "--release",
            revision,
            "deploy",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "COMMAND_LOG": str(commands),
            "DB_STATE": state,
            "BACKEND_IMAGE": "ghcr.io/fictional/backend@sha256:" + "1" * 64,
            "WEB_IMAGE": "ghcr.io/fictional/web@sha256:" + "2" * 64,
            "REGISTRY_USER": "synthetic",
            "REGISTRY_TOKEN": "synthetic-token",
        },
    )
    operations = commands.read_text().splitlines()
    migrated = any(line.endswith(" migrate") for line in operations)
    assert migrated == (state == "empty"), result.stderr
    assert (result.returncode == 0) == (state == "empty")
    assert not any(line.endswith(" activate") for line in operations) or migrated


def test_recovery_rechecks_maintenance_under_the_host_lock(host):
    import fcntl
    import threading
    import time

    run, root, log = host
    (root / "active.json").write_text(json.dumps({"release": "a" * 40, "schema": "0001_accounts"}))
    results = []
    with (root / "host.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        thread = threading.Thread(target=lambda: results.append(run("recover")))
        thread.start()
        time.sleep(0.1)
        (root / "maintenance").touch()
        fcntl.flock(lock, fcntl.LOCK_UN)
    thread.join(timeout=10)
    assert results[0].returncode == 0
    assert not log.exists()


def test_unchanged_host_provisioning_preserves_readonly_password(host, tmp_path):
    run, root, log = host
    destination = root / "new-host"
    script = REPO / "scripts/provision-host.py"
    wrapper = (
        "import runpy; from unittest.mock import patch; "
        "a=patch('platform.system',return_value='Darwin');a.start();"
        "b=patch('platform.machine',return_value='x86_64');b.start();"
        f"runpy.run_path({str(script)!r},run_name='__main__')"
    )
    payload = json.dumps(
        {
            "hostname": "office.example.com",
            "database_password": "synthetic-only-password-32-characters",
            "backup_recipient": "synthetic",
        }
    )
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", wrapper, "--root", str(destination)],
            input=payload,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "HOME": str(tmp_path),
                "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                "COMMAND_LOG": str(log),
            },
        )
        assert result.returncode == 0, result.stderr
    assert (destination / "database-password").stat().st_mode & 0o777 == 0o444


def test_failed_role_rotation_can_be_retried_with_retained_input(host):
    run, root, log = host
    payload = json.dumps({"password": "synthetic-only-rotation-32-characters"})
    assert run("rotate-password", payload, FAIL_COMMAND="psql").returncode != 0
    assert (root / "maintenance").exists()
    result = run("rotate-password", payload)
    assert result.returncode == 0, result.stderr
    assert not (root / "maintenance").exists()


def test_compatible_rollback_starts_retained_release(host):
    import shutil

    run, root, log = host
    prior = root / "releases" / ("b" * 40)
    shutil.copytree(root / "releases" / ("a" * 40), prior)
    (root / "previous.json").write_text(
        json.dumps({"release": "b" * 40, "schema": "0001_accounts"})
    )
    result = run("rollback")
    assert result.returncode == 0, result.stderr
    assert json.loads((root / "active.json").read_text())["release"] == "b" * 40
    assert (root / "current").resolve() == prior


def test_runner_transport_preserves_custom_port(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/deploy-transport.py")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "DEPLOY_HOST": "deploy@mini.example.com",
            "DEPLOY_SSH_PORT": "2222",
            "DEPLOY_ROOT": "/srv/office",
            "BACKUP_BUCKET": "fictional-backups",
            "BACKUP_PREFIX": "archives/office/",
            "DEPLOY_SSH_KEY": "synthetic-private-key",
            "DEPLOY_KNOWN_HOSTS": "[mini.example.com]:2222 synthetic-public-key",
        },
    )
    assert result.returncode == 0, result.stderr
    config = json.loads((tmp_path / "deploy.json").read_text())
    assert config["port"] == "2222"
    assert config["host"] == "deploy@mini.example.com"
    assert "synthetic-private-key" not in result.stdout + result.stderr
