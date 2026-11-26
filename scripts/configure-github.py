"""Configure repository Actions variables and secrets from Terraform and private files."""

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
APPLICATION_INPUTS = (
    "AWS_ACCOUNT_ID=var.aws_account_id, HOSTED_ZONE_ID=var.hosted_zone_id, "
    "APP_HOSTNAME=var.app_hostname, PUBLIC_IPV4=var.public_ipv4"
)
FOUNDATION_OUTPUTS = {
    "TF_STATE_BUCKET": "state_bucket_name",
    "BACKUP_BUCKET_NAME": "backup_bucket_name",
    "INFRASTRUCTURE_ROLE_ARN": "infrastructure_role_arn",
    "BACKUP_ROLE_ARN": "backup_role_arn",
}


class ConfigurationError(Exception):
    pass


def run(*command, payload=None):
    try:
        return subprocess.run(
            command, input=payload, capture_output=True, text=True, check=True, cwd=REPOSITORY
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        # External diagnostics can contain private Terraform values or secret inputs.
        raise ConfigurationError(
            f"{command[0]} command failed; check local access/tooling."
        ) from None


def collect(config, key, prompt, non_interactive, default=""):
    value = config.get(key)
    if not value:
        if non_interactive:
            if not default:
                raise ConfigurationError(f"Missing configuration field: {key}")
            value = default
        else:
            suffix = f" [{default}]" if default else ""
            value = input(prompt + suffix + ": ").strip() or default
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\x00"):
        raise ConfigurationError(f"Invalid configuration field: {key}")
    config[key] = value
    return value


def secret_file(config, key, prompt, non_interactive, parent):
    value = collect(config, key, prompt, non_interactive)
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = parent / path
    path = path.resolve()
    if path.is_relative_to(REPOSITORY):
        try:
            run("git", "check-ignore", str(path))
        except ConfigurationError:
            raise ConfigurationError(
                f"Private input {key} inside the checkout must be untracked and gitignored."
            ) from None
    # Protect exported originals; store paths, never secret contents, in config.
    path.chmod(0o600)
    config[key] = str(path)
    content = path.read_text()
    if not content.strip():
        raise ConfigurationError(f"Empty private input: {key}")
    return path, content


def prepare(config, non_interactive, parent):
    repository = run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ConfigurationError("Cannot determine GitHub repository from this checkout.")
    encoded = run(
        "terraform",
        "-chdir=infra/application",
        "console",
        payload=f"jsonencode({{{APPLICATION_INPUTS}}})\n",
    )
    variables = json.loads(json.loads(encoded))
    for name, output in FOUNDATION_OUTPUTS.items():
        variables[name] = run("terraform", "-chdir=infra/foundation", "output", "-raw", output)
    if not re.fullmatch(r"\d{12}", variables["AWS_ACCOUNT_ID"]):
        raise ConfigurationError("Invalid Terraform AWS account ID.")
    ipaddress.IPv4Address(variables["PUBLIC_IPV4"])
    if not all(
        isinstance(value, str) and value.strip() and not value.startswith("REPLACE_WITH_")
        for value in variables.values()
    ):
        raise ConfigurationError("Terraform configuration must contain applied deployment values.")

    host = collect(config, "ssh_host", "Mini SSH destination (user@host)", non_interactive)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+", host):
        raise ConfigurationError("ssh_host must be user@host (standard SSH port 22).")
    username, hostname = host.split("@")
    root = collect(
        config,
        "deploy_root",
        "Private absolute directory on the mini",
        non_interactive,
        f"/Users/{username}/Library/Application Support/office",
    )
    if not root.startswith("/") or any(char in root for char in "'\r\n"):
        raise ConfigurationError("deploy_root must be an absolute path without single quotes.")
    root = root.rstrip("/")
    if not root:
        raise ConfigurationError("Do not use the filesystem root as deploy_root.")
    prefix = collect(
        config,
        "backup_prefix",
        "S3 archive namespace",
        non_interactive,
        "archives/" + re.sub(r"[^a-zA-Z0-9_-]", "-", repository) + "/",
    )
    if not re.fullmatch(r"archives/[a-zA-Z0-9/_-]+/", prefix):
        raise ConfigurationError(
            "backup_prefix must be a dedicated archives/ namespace ending in /."
        )
    identity, private_key = secret_file(
        config, "ssh_identity", "Deployment SSH private key file", non_interactive, parent
    )
    run("ssh-keygen", "-y", "-P", "", "-f", str(identity))
    hosts, _ = secret_file(
        config, "known_hosts", "Independently verified known_hosts file", non_interactive, parent
    )
    matching_hosts = run("ssh-keygen", "-F", hostname, "-f", str(hosts))
    known_hosts = (
        "\n".join(line for line in matching_hosts.splitlines() if line and not line.startswith("#"))
        + "\n"
    )
    if not known_hosts.strip():
        raise ConfigurationError("known_hosts has no entry for the deployment host.")
    _, setup_json = secret_file(
        config, "host_setup", "Host setup JSON file", non_interactive, parent
    )
    setup = json.loads(setup_json)
    if setup.get("hostname") != variables["APP_HOSTNAME"]:
        raise ConfigurationError(
            "Host setup hostname must match the Terraform application hostname."
        )
    password = setup.get("database_password", "")
    if (
        not isinstance(password, str)
        or len(password) < 32
        or any(c in password for c in "\r\n\x00")
    ):
        raise ConfigurationError(
            "Host setup requires a generated single-line database password (32+)."
        )
    if set(setup) - {"hostname", "database_password", "backup_recipient", "bootstrap"}:
        raise ConfigurationError(
            "Host setup contains unexpected fields; do not include recovery keys."
        )
    recipient = setup.get("backup_recipient", "")
    if not isinstance(recipient, str) or not re.fullmatch(r"age1[a-z0-9]{58}", recipient):
        raise ConfigurationError(
            "Host setup requires a public age-keygen recipient, not an identity."
        )
    run("age", "--armor", "--recipient", recipient, payload="")
    if "bootstrap" in setup:
        bootstrap = setup["bootstrap"]
        if (
            not isinstance(bootstrap, dict)
            or set(bootstrap) != {"email", "display_name", "password"}
            or not all(
                isinstance(bootstrap.get(key), str) and bootstrap[key].strip()
                for key in ("email", "display_name", "password")
            )
            or len(bootstrap["password"]) < 12
        ):
            raise ConfigurationError(
                "Bootstrap requires email, display_name and a 12+ character password."
            )
    variables.update(
        BACKUP_SSH_HOST=host,
        DEPLOY_ROOT=root,
        BACKUP_DIRECTORY=f"{root}/current",
        BACKUP_PREFIX=prefix,
    )
    secrets = {
        "BACKUP_SSH_KEY": private_key,
        "BACKUP_KNOWN_HOSTS": known_hosts,
        "HOST_SETUP_JSON": json.dumps(setup),
    }
    return repository, variables, secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=REPOSITORY / ".scratch/private/deployment.json"
    )
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="Validate inputs without GitHub writes"
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config_path = args.config.expanduser().resolve()
        # Only private ignored files may hold operator-specific deployment inputs.
        if not run("git", "check-ignore", str(config_path)):
            raise ConfigurationError("The configuration path must be ignored by git.")
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        if config_path.exists():
            config_path.chmod(0o600)
        repository, variables, secrets = prepare(config, args.non_interactive, config_path.parent)
        print(
            f"Validated {len(variables)} variables and {len(secrets)} secrets. No payloads printed."
        )
        if args.check:
            return 0
        config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        config_path.chmod(0o600)
        # Finish validation before remote mutation; failed uploads are safe to rerun.
        for kind, values in [("variable", variables), ("secret", secrets)]:
            for name, value in values.items():
                run("gh", kind, "set", name, "--repo", repository, payload=value)
                print(f"Updated {kind}: {name}")
        print(
            "GitHub configuration complete. Keep credential originals in your password manager. "
            "Remove bootstrap from the private setup JSON and rerun after initialization."
        )
        return 0
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        print(
            "GitHub may be partially updated if an upload failed; rerun to finish. "
            "No host setup or deployment was started.",
            file=sys.stderr,
        )
        return 1
    except OSError, ValueError, KeyError, TypeError, EOFError:
        print(
            "Configuration failed; verify Terraform/authentication and private input files. "
            "GitHub may be partially updated if an upload failed; rerun to finish. "
            "No host setup or deployment was started.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
