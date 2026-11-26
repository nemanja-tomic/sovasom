"""Exercise the setup CLI against synthetic GitHub, Terraform and SSH tooling."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/configure-github.py"


@pytest.fixture
def operator(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands.jsonl"
    for name in ("gh", "terraform", "ssh-keygen", "age"):
        tool = binary / name
        tool.write_text(
            f"#!{sys.executable}\n"
            + """import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
payload=sys.stdin.read() if (name=='gh' and 'set' in args) or 'console' in args else ''
with open(os.environ['SETUP_LOG'],'a') as f:
 f.write(json.dumps({'tool':name,'args':args,'payload':payload})+'\\n')
if os.environ.get('FAIL_UPLOAD') and name=='gh' and 'secret' in args: sys.exit(1)
if name=='gh' and 'view' in args: print(os.environ.get('FAKE_REPO','fictional/office'))
if name=='ssh-keygen': print('synthetic public key match')
if name=='terraform':
 if 'console' in args:
  print(json.dumps(json.dumps({'AWS_ACCOUNT_ID':'111122223333','HOSTED_ZONE_ID':'ZFICTIONAL',
   'APP_HOSTNAME':'office.example.com','PUBLIC_IPV4':'192.0.2.1'})))
 else:
  print({'state_bucket_name':'fictional-state','backup_bucket_name':'fictional-backups',
   'infrastructure_role_arn':'arn:aws:iam::111122223333:role/fictional-infrastructure',
   'backup_role_arn':'arn:aws:iam::111122223333:role/fictional-backup'}[args[-1]])
"""
        )
        tool.chmod(0o700)
    key = tmp_path / "key"
    key.write_text("synthetic private key\nsecond line\n")
    hosts = tmp_path / "known_hosts"
    hosts.write_text("mini.example.com synthetic-host-key\n")
    setup = tmp_path / "setup.json"
    setup.write_text(
        json.dumps(
            {
                "hostname": "office.example.com",
                "database_password": "synthetic-database-password-32-characters",
                "backup_recipient": "age1" + "a" * 58,
                "bootstrap": {
                    "email": "admin@example.com",
                    "display_name": "Test administrator",
                    "password": "synthetic bootstrap password",
                },
            }
        )
    )
    # The script intentionally restricts saved configuration to ignored repo paths.
    import tempfile

    (REPO / ".scratch/private").mkdir(parents=True, exist_ok=True)
    directory = tempfile.TemporaryDirectory(dir=REPO / ".scratch/private")
    config = Path(directory.name) / "deployment.json"
    config.write_text(
        json.dumps(
            {
                "ssh_host": "deploy@mini.example.com",
                "deploy_root": "/Users/deploy/Library/Application Support/office",
                "ssh_identity": str(key),
                "known_hosts": str(hosts),
                "host_setup": str(setup),
            }
        )
    )

    def run(*args, interactive_input=None, **env):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--config",
                str(config),
                *([] if interactive_input is not None else ["--non-interactive"]),
                *args,
            ],
            capture_output=True,
            text=True,
            input=interactive_input,
            env={
                **os.environ,
                "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                "SETUP_LOG": str(log),
                **env,
            },
        )

    yield run, config, setup, log
    directory.cleanup()


def records(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_setup_uploads_complete_configuration_using_stdin_without_printing_payloads(operator):
    run, config, setup, log = operator
    result = run()
    assert result.returncode == 0, result.stderr
    uploads = [entry for entry in records(log) if "set" in entry["args"]]
    assert len(uploads) == 15  # Eight infrastructure + four host variables + three secrets.
    values = {entry["args"][2]: entry["payload"] for entry in uploads}
    assert values["BACKUP_DIRECTORY"] == "/Users/deploy/Library/Application Support/office/current"
    assert values["BACKUP_PREFIX"] == "archives/fictional-office/"
    assert values["BACKUP_SSH_KEY"] == "synthetic private key\nsecond line\n"
    assert json.loads(values["HOST_SETUP_JSON"]) == json.loads(setup.read_text())
    assert all("--body" not in entry["args"] for entry in uploads)
    assert "synthetic private key" not in result.stdout + result.stderr
    assert "synthetic-database-password" not in result.stdout + result.stderr + config.read_text()
    assert config.stat().st_mode & 0o777 == 0o600
    last_read = max(i for i, entry in enumerate(records(log)) if "set" not in entry["args"])
    first_write = min(i for i, entry in enumerate(records(log)) if "set" in entry["args"])
    assert last_read < first_write


def test_check_performs_no_remote_mutations(operator):
    run, config, setup, log = operator
    original = config.read_text()
    assert run("--check").returncode == 0
    assert config.read_text() == original
    assert not any("set" in entry["args"] for entry in records(log))


def test_invalid_host_input_blocks_all_uploads(operator):
    run, config, setup, log = operator
    payload = json.loads(setup.read_text())
    payload["hostname"] = "different.example.com"
    setup.write_text(json.dumps(payload))
    assert run().returncode != 0
    assert not any("set" in entry["args"] for entry in records(log))


def test_failed_upload_can_rerun_and_remove_bootstrap_from_github(operator):
    run, config, setup, log = operator
    failure = run(FAIL_UPLOAD="1")
    assert failure.returncode != 0
    assert "partially updated" in failure.stderr
    payload = json.loads(setup.read_text())
    del payload["bootstrap"]
    setup.write_text(json.dumps(payload))
    result = run()
    assert result.returncode == 0, result.stderr
    uploads = [
        entry for entry in records(log) if entry["args"][:3] == ["secret", "set", "HOST_SETUP_JSON"]
    ]
    assert "bootstrap" not in json.loads(uploads[-1]["payload"])


def test_private_backup_identity_is_never_uploaded(operator):
    run, config, setup, log = operator
    payload = json.loads(setup.read_text())
    payload["backup_recipient"] = "AGE-SECRET-KEY-SYNTHETIC"
    setup.write_text(json.dumps(payload))
    result = run()
    assert result.returncode != 0
    assert "AGE-SECRET-KEY-SYNTHETIC" not in result.stdout + result.stderr
    assert not any("set" in entry["args"] for entry in records(log))


def test_first_run_prompts_once_then_reuses_saved_settings(operator):
    run, config, setup, log = operator
    initial = json.loads(config.read_text())
    config.unlink()
    answers = "\n".join(
        [
            "deploy@mini.example.com",
            "",
            "",
            initial["ssh_identity"],
            initial["known_hosts"],
            str(setup),
            "",
        ]
    )
    result = run(interactive_input=answers)
    assert result.returncode == 0, result.stderr
    saved = json.loads(config.read_text())
    assert saved["deploy_root"] == "/Users/deploy/Library/Application Support/office"
    assert saved["backup_prefix"] == "archives/fictional-office/"
    assert run().returncode == 0


def test_dotted_repository_name_gets_a_valid_default_namespace(operator):
    run, config, setup, log = operator
    result = run(FAKE_REPO="fictional/office.app")
    assert result.returncode == 0, result.stderr
    uploads = [
        entry for entry in records(log) if entry["args"][:3] == ["variable", "set", "BACKUP_PREFIX"]
    ]
    assert uploads[0]["payload"] == "archives/fictional-office-app/"


def test_repository_inputs_must_be_untracked_and_ignored_before_uploads(operator):
    run, config, setup, log = operator
    values = json.loads(config.read_text())
    values["ssh_identity"] = str(REPO / "README.md")
    config.write_text(json.dumps(values))
    result = run()
    assert result.returncode != 0
    assert "untracked and gitignored" in result.stderr
    assert not any("set" in entry["args"] for entry in records(log))
