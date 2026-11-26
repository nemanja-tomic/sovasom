"""Write runner-only transport files from Actions secrets; never echo payloads."""

import json
import os
from pathlib import Path

from backup import ssh_port

os.umask(0o077)
root = Path(os.environ["RUNNER_TEMP"])
required = [
    "DEPLOY_HOST",
    "DEPLOY_ROOT",
    "BACKUP_BUCKET",
    "BACKUP_PREFIX",
    "DEPLOY_SSH_KEY",
    "DEPLOY_KNOWN_HOSTS",
]
if not all(os.environ.get(key) for key in required):
    raise SystemExit("Missing deployment configuration")
(root / "deploy-key").write_text(os.environ["DEPLOY_SSH_KEY"])
(root / "deploy-hosts").write_text(os.environ["DEPLOY_KNOWN_HOSTS"] + "\n")
(root / "deploy.json").write_text(
    json.dumps(
        {
            "host": os.environ["DEPLOY_HOST"],
            "port": ssh_port(os.environ.get("DEPLOY_SSH_PORT", "22")),
            "directory": os.environ["DEPLOY_ROOT"],
            "bucket": os.environ["BACKUP_BUCKET"],
            "prefix": os.environ["BACKUP_PREFIX"],
            "known_hosts": str(root / "deploy-hosts"),
            "ssh_identity": str(root / "deploy-key"),
        }
    )
)
