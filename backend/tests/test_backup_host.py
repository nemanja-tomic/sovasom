"""Host CLI safety checks, without access to an operator database."""

import os
import subprocess
import sys
from pathlib import Path

HOST = Path(__file__).resolve().parents[2] / "scripts/backup-host.py"


def test_restore_rejects_existing_or_nonisolated_database_before_reading_archive():
    result = subprocess.run(
        [
            sys.executable,
            str(HOST),
            "restore",
            "--archive",
            "/missing",
            "--identity",
            "/missing",
            "--database",
            "office",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "office_restore_" in result.stderr


def test_failed_dump_does_not_emit_a_partial_ciphertext(tmp_path):
    docker = tmp_path / "docker"
    docker.write_text(f'#!{sys.executable}\nimport sys\nsys.stdout.write("partial")\nsys.exit(1)\n')
    docker.chmod(0o700)
    result = subprocess.run(
        [sys.executable, str(HOST), "backup", "--recipient", "age1synthetic"],
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
    )
    assert result.returncode != 0
    assert result.stdout == b""
    assert b"partial" not in result.stderr
