# Mac mini releases and recovery

Release automation is implemented; operational acceptance is pending. Do not open
this installation to colleagues until ticket 16's real off-host restore and the
isolated checks below pass. The current application implements accounts only;
the durable notification worker and remaining workflows must be deployed and
accepted when those tickets land. This release does not invent a worker command.

## Establish the host

Use the existing Intel mini and macOS/Docker Desktop, never a self-hosted Actions
runner. Check the exact model, macOS support, free encrypted disk space, installed
Desktop version and organization licensing against the current
[Mac requirements](https://docs.docker.com/desktop/setup/install/mac-install/).
Record the actual versions and licensing decision privately; a successful Docker
probe cannot establish vendor OS support or licensing. Do not silently use an
unsupported old Desktop. The repo's `.tool-versions` pins CLI/Compose tooling;
install/verify those tools, uv, Python and age using the existing setup guidance.
Keep at least two CPUs/4 GiB assigned to Desktop plus disk headroom for database,
backups, builds and multiple releases; measure actual usage before acceptance.

Use a dedicated deployment macOS user owning the running Desktop context. Enable
Remote Login for that user, install only the dedicated public SSH key and restrict
network access appropriately. Docker access grants control of this user's
containers; this is a trusted deployment identity, not a sandbox. Preserve an
independent administrator recovery path. Obtain SSH host keys through an
independent trusted channel. Never substitute unverified `ssh-keyscan` output.
Check `docker context show`, `docker info`, `docker compose version`, `uv --version`
and `age --version` through **noninteractive SSH**, with the user logged in and
Desktop running. Ensure its PATH resolves the pinned tools. Create the private
absolute deployment root, mode 0700, owned by this user, outside any checkout.
Do not reuse a local development Compose installation's volumes.

Enable Docker Desktop's start-at-login setting, prevent unattended host sleep
while serving, and review power/network settings. FileVault remains enabled;
cold boot requires a human unlock/login. The host setup writes a per-user
LaunchAgent that retries the accepted release every 30 seconds after login.
Load it as that user with `launchctl bootstrap gui/$(id -u)
~/Library/LaunchAgents/com.office.recovery.plist` (one shell line). A `maintenance`
file suppresses recovery during deployments; do not remove it after a failed
migration without assessing the schema. Inspect launchctl status without logging
secret inputs. Initial source tools stay at `<root>/tools`; retain them for the
LaunchAgent. Provisioning must run on the target mini, not the operator laptop.

## Configuration and custody

Generate a random single-line database password (at least 32 characters), bootstrap
password and dedicated SSH identity on a trusted operator machine. Keep originals
in the password manager with independent recovery access. Keep actual host,
repository, account, DNS, configuration and evidence out of tracked files.
Use repository secrets where environment features are unavailable; protect main
and workflow administration. Test/PR jobs receive synthetic credentials only.

Configure repository variables `DEPLOY_ROOT`, `BACKUP_SSH_HOST` (user@host),
`BACKUP_BUCKET_NAME`, `BACKUP_PREFIX`, `BACKUP_ROLE_ARN`, `AWS_ACCOUNT_ID` as in
[backup recovery](backup-recovery.md). Set `BACKUP_DIRECTORY` to `<root>/current`.
The dedicated `BACKUP_SSH_KEY` is shared by serialized backup/release operations;
`BACKUP_KNOWN_HOSTS` pins the verified host identity. Restrict both to trusted jobs.
The backup AWS role uses OIDC, never a permanent AWS credential on the mini.

Set repository secret `HOST_SETUP_JSON` with keys `hostname`, `database_password`,
`backup_recipient` (public age recipient) and, **first setup only**, `bootstrap`
with `email`, `display_name`, `password`. Run **Configure existing Mac mini** from
main. It sends secret JSON on verified SSH stdin, separately from the source
archive, and writes files outside the checkout. After initialization succeeds,
remove `bootstrap` from this GitHub secret immediately and from temporary operator
files. Keep the password-manager recovery originals. The host deletes
`bootstrap.json` after successful initialization; later releases run migrations
only. Failed initialization retains its private input for an assessed retry.
Setup refuses a changed database password; editing the file alone cannot rotate
an existing PostgreSQL role.

The deployment directory is 0700. `runtime.env` and bootstrap inputs are 0600.
Only the database and backend mount `database-password`; the backend explicitly
reads `DATABASE_PASSWORD_FILE`. The source file is 0444 **inside the private 0700
directory**, allowing the unprivileged container UID to read a Desktop bind mount.
Compose file-secret ownership/mode overrides are not assumed to work. Verify actual
host traversal restrictions and container reads on the mini before acceptance.
Caddy mounts no application secrets. Never print `docker compose config`, settings,
secret JSON or rendered environment into public logs. PostgreSQL has no host port,
uses an internal network and retains its named volume across image changes.

## Release protocol

**Release to the Mac mini** runs on main and manually. Reusable Linux jobs run the
full backend/PostgreSQL suite, frontend format/lint/types/units/Storybook/visual
checks, and full-stack Playwright before publishing linux/amd64 GHCR images.
The deploy job checks main has not superseded its source revision. The shared
`office-host-maintenance` concurrency group serializes setup, backups and releases.
Do not run independent controllers concurrently outside Actions.

Builds use existing dependency pins; no credentials enter build arguments or image
layers. Images deploy by GHCR digest, never a mutable tag. Configure each private
GHCR package to grant this repository's Actions token read access. Pulling uses a
job-scoped `GITHUB_TOKEN` transmitted on SSH stdin. An explicit temporary Docker
config with inline auths bypasses `docker login`'s native helper auto-selection;
no Desktop config/helper is copied. Pulls retain the user's selected Docker socket
explicitly when changing config directories. Every normal success/failure invokes
`docker logout` and removes the directory. See
[Docker credential storage](https://docs.docker.com/reference/cli/docker/login/).
Forced process/host termination can leave a `registry-*` directory: inspect/remove
it privately after confirming no deployment is active. Tokens expire; this is not
a substitute for cleanup. Verify Keychain/default-helper state before and after
both successful and failed real private pulls, and prove an expired token fails.
Do not assume a synthetic CLI test establishes those outcomes.

Release sources and nonsecret image metadata live in `<root>/releases/<git-sha>`.
Writes stop before the database probe. Existing databases require this invocation's
encrypted backup, S3 upload, exact-version download and checksum verification.
Failure/unknown state leaves maintenance active and blocks migrations. A proven
empty database can initialize without an archive. Health-checked startup precedes
activation of `<root>/current`; `active.json` and `previous.json` record image source
and schema revision. Do not prune old images/releases/volumes automatically.
Retain at least the active and prior accepted release plus matching recovery inputs.

Caddy serves the built SPA and proxies same-origin `/api/*`. It persists certificates
and private keys in `caddy_data`, with configuration in `caddy_config`; configure
TCP 80/443 routing and verify existing DNS A/static-IP mapping (and any AAAA record)
from outside the LAN. Allow outbound ACME/registry/backup traffic and, when present,
Web Push provider HTTPS. Keep PostgreSQL/firewall port 5432 closed publicly.
Caddy uses its default automatic ACME issuer policy, including Let's Encrypt and
fallback; certificates renew automatically and a replacement can reissue using
DNS/network access. See [automatic HTTPS prerequisites](https://caddyserver.com/docs/automatic-https).

## Failure, rollback and rotation

A failed release leaves maintenance in effect. Inspect the fixed failure message
and private host state; no schema downgrade is automatic. From a trusted controller
with job-scoped credentials/configuration, run `scripts/deploy.py --config
"$DEPLOY_CONFIG" --release "$CANDIDATE_SHA" rollback` through `uv run --frozen`
(one shell line, serialized). The host refuses rollback if the database revision
is different from the retained previous release's recorded revision. Equal schema
is a conservative prerequisite, not proof of semantic compatibility: exercise
sign-in/access/data on an isolated copy before accepting that image pair. Images
must still be cached; pull pinned old digests privately if needed. A source SHA
whose image digests have changed is rejected; release new source to change its
images. If schema differs,
deploy a forward fix or restore the verified pre-migration archive into an isolated
new database and validate it before a deliberate cutover. Never overwrite the live
database or claim that reverting an image undoes its migration.

For database rotation, first back up/upload and stop concurrent jobs. Save both
old/new passwords in the manager and update the deployment copy in
`HOST_SETUP_JSON` as part of the same maintenance operation. Send JSON containing
`password` on verified SSH stdin to `scripts/deploy-host.py --root "$DEPLOY_ROOT"
--release "$ACTIVE_SHA" rotate-password` through `uv run --frozen` on the mini.
The command stops writes, stages the replacement outside source, executes actual
`ALTER ROLE`, replaces the mounted file and recreates services. On failure retain
both custody copies and `database-password.next`, assess which role credential is
active and retry deliberately; recovery stays suppressed. Verify authenticated
TCP connections reject the old password and accept the new one, and re-login via
the app. SSH rotation installs/test-connects the new key before revoking the old
key and replacing GitHub's copy. Future VAPID rotation must coordinate private/public
keys and existing browser subscriptions when that feature exists. Retain old age
private identities independently until all corresponding archives expire.

## Required private acceptance record

Use disposable isolated data/resources and never notify colleagues. Record actual
commands, times and results under ignored `.scratch/private/` or private custody:

- Host/OS/Desktop support, licensing, SSH context, resources, source permissions and
  real secret reads as the backend UID; unchanged setup/migration reruns preserve
  account/password/grants. Bootstrap input is gone from host and GitHub.
- Private GHCR successful/failed/expired pulls; no auth left in config/Keychain/helper;
  successful health startup; external HTTPS chain, redirects, SPA deep links and API.
- Ticket-16 real off-host archive restore and sign-in; denied upload prevents migration;
  first empty installation; schema-compatible image rollback and incompatible refusal.
- Real PostgreSQL role rotation, new credential login, old credential denial and
  retained independent backup/AWS/key recovery. No private identities on the mini.
- Manual cold power-off/boot, FileVault unlock/login, Desktop automatic startup,
  LaunchAgent recovery without a release job, health and persisted sign-in/data.
  Repeat normal restarts and verify failed maintenance does not auto-resume.
- Existing Playwright account workflows against the isolated deployment, plus all
  later workflows/worker reconciliation as they become available; outbound push
  connectivity and actual devices remain prerequisites for those future features.

No live mini, GHCR, SSH, DNS, AWS, Keychain, cold boot or worker acceptance is claimed
by repository tests. Keep ticket 17 open until the applicable checks are recorded.
