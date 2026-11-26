"""Operator CLI tests replace only the SSH and S3 process boundaries."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture
def transfer(tmp_path):
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    state = tmp_path / "s3"
    state.mkdir()
    # Synthetic SSH transport and S3 service: persist ciphertext across CLI invocations.
    for name, source in {
        "ssh": """import json, os, sys
from pathlib import Path
Path(os.environ['S3_TEST'], 'ssh.json').write_text(json.dumps(sys.argv[1:]))
if os.environ.get('FAIL_SSH'): sys.exit(1)
if 'probe' in sys.argv[-1]: print(os.environ.get('DB_STATE', 'existing'))
elif 'setup.py' in sys.argv[-1]:
 open(os.environ['S3_TEST'] + '/migrated', 'w').write('yes')
else: sys.stdout.buffer.write(b'age-encryption.org/v1\\nsynthetic ciphertext')
""",
        "aws": """import datetime, json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ['S3_TEST'])
a = sys.argv
if os.environ.get('FAIL_AWS'): sys.exit(1)
def flag(k): return a[a.index(k)+1]
if 'put-object' in a:
 key = flag('--key')
 shutil.copyfile(flag('--body'), root/key.replace('/', '_'))
 if key.endswith('.age'): shutil.copyfile(flag('--body'), root/'archive')
 (root/'key').write_text(flag('--key'))
 print(json.dumps({} if os.environ.get('NO_VERSION') else {'VersionId':'synthetic-version'}))
elif 'get-object' in a:
 shutil.copyfile(root/flag('--key').replace('/', '_'), a[-1])
 if os.environ.get('CORRUPT'): pathlib.Path(a[-1]).write_bytes(b'corrupt')
 print('{}')
elif 'list-objects-v2' in a:
 days = int(os.environ.get('AGE_DAYS','0'))
 date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
 contents = []
 for path in root.glob('*success*'):
  contents.append({'Key':path.name, 'LastModified':date.isoformat()})
 print(json.dumps({'Contents': contents}))
""",
    }.items():
        path = bin_path / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o700)
    config = tmp_path / "backup.json"
    config.write_text(
        json.dumps(
            {
                "host": "backup@mini.example.com",
                "directory": "/srv/office",
                "known_hosts": str(tmp_path / "known_hosts"),
                "ssh_identity": str(tmp_path / "ssh"),
                "bucket": "fictional-backups",
                "prefix": "archives/office/",
            }
        )
    )

    def run(operation="backup", **environment):
        return subprocess.run(
            [
                sys.executable,
                str(REPOSITORY / "scripts/backup.py"),
                "--config",
                str(config),
                operation,
            ],
            env={
                **os.environ,
                "PATH": str(bin_path) + os.pathsep + os.environ["PATH"],
                "S3_TEST": str(state),
                **environment,
            },
            capture_output=True,
            text=True,
        )

    return run, state


def test_verified_upload_records_success_and_freshness(transfer):
    run, state = transfer
    result = run()
    assert result.returncode == 0, result.stderr
    assert "Backup verified" in result.stdout
    assert (state / "archive").read_bytes().startswith(b"age-encryption.org/v1")
    status = run("status")
    assert status.returncode == 0, status.stderr
    assert "Last successful backup:" in status.stdout
    assert "age hours:" in status.stdout


@pytest.mark.parametrize("failure", ["FAIL_SSH", "FAIL_AWS", "CORRUPT", "NO_VERSION"])
def test_failed_backup_blocks_migration_and_can_be_retried(transfer, failure):
    run, state = transfer
    failed = run("migrate", **{failure: "1"})
    assert failed.returncode != 0
    assert not (state / "migrated").exists()
    assert not list(state.glob("*success*"))
    assert run("migrate").returncode == 0
    assert (state / "migrated").exists()


def test_freshness_reports_missing_and_stale_backups(transfer):
    run, _ = transfer
    assert run("status").returncode != 0
    assert run().returncode == 0
    assert run("status", AGE_DAYS="9").returncode != 0
    assert run().returncode == 0
    assert run("status").returncode == 0


def test_first_install_migrates_without_prior_archive(transfer):
    run, state = transfer
    result = run("migrate", DB_STATE="empty")
    assert result.returncode == 0, result.stderr
    assert (state / "migrated").exists()
    assert not (state / "archive").exists()


def test_unknown_database_state_never_authorizes_migration(transfer):
    run, state = transfer
    assert run("migrate", DB_STATE="unknown").returncode != 0
    assert not (state / "migrated").exists()


def test_failed_upload_does_not_replace_previous_success(transfer):
    run, state = transfer
    assert run().returncode == 0
    successes = list(state.glob("*success*"))
    assert len(successes) == 1
    previous = successes[0].read_bytes()
    assert run("migrate", CORRUPT="1").returncode != 0
    assert successes[0].read_bytes() == previous
    assert len(list(state.glob("*success*"))) == 1
    assert run("status").returncode == 0


def test_backup_uses_configured_ssh_port_without_changing_destination(transfer):
    run, state = transfer
    config = state.parent / "backup.json"
    values = json.loads(config.read_text())
    values["port"] = 2222
    config.write_text(json.dumps(values))
    assert run().returncode == 0
    arguments = json.loads((state / "ssh.json").read_text())
    assert arguments[arguments.index("-p") + 1] == "2222"
    assert "backup@mini.example.com" in arguments


@pytest.mark.parametrize("port", [0, 65536, "-oProxyCommand=bad", True])
def test_invalid_ssh_port_prevents_transport(transfer, port):
    run, state = transfer
    config = state.parent / "backup.json"
    values = json.loads(config.read_text())
    values["port"] = port
    config.write_text(json.dumps(values))
    assert run().returncode != 0
    assert not (state / "ssh.json").exists()
