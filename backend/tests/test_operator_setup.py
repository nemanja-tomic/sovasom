import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


def test_failed_initializer_explains_input_error_without_a_python_traceback(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    executable = tmp_path / "docker"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if 'psql' in sys.argv: print('0')\n"
        "if 'run' in sys.argv[1:]:\n"
        " print('Setup failed: INITIAL_PASSWORD must contain 12 to 1024 characters.', "
        "file=sys.stderr)\n"
        " sys.exit(1)\n"
    )
    executable.chmod(0o700)
    config = tmp_path / ".env"
    config.write_text("DATABASE_PASSWORD='synthetic db password'\nINITIAL_PASSWORD='short123'\n")
    result = subprocess.run(
        [sys.executable, str(repository / "scripts/setup.py"), "--env-file", str(config)],
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "INITIAL_PASSWORD must contain 12 to 1024 characters" in result.stderr
    assert "Traceback" not in result.stderr
    assert "short123" not in result.stdout + result.stderr
    assert dotenv_values(config)["INITIAL_PASSWORD"] == "short123"


def test_initializer_explains_database_connection_failure_without_credentials():
    repository = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "office.setup", "--stdin"],
        env={
            **os.environ,
            "PYTHONPATH": str(repository / "backend"),
            "DATABASE_URL": "postgresql+psycopg://office:synthetic-secret@127.0.0.1:1/unused",
        },
        input="{}",
        cwd=repository,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Cannot connect to PostgreSQL" in result.stderr
    assert "DATABASE_PASSWORD" in result.stderr
    assert "synthetic-secret" not in result.stderr
    assert "Traceback" not in result.stderr


def test_existing_database_requires_verified_backup_gate(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "if 'psql' in sys.argv: print('1')\n"
        "if 'run' in sys.argv: raise SystemExit('migration must not run')\n"
    )
    docker.chmod(0o700)
    config = tmp_path / ".env"
    config.write_text("DATABASE_PASSWORD='synthetic-only'\n")
    result = subprocess.run(
        [sys.executable, str(repository / "scripts/setup.py"), "--env-file", str(config)],
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "backup.py" in result.stderr
    assert "migration must not run" not in result.stderr
