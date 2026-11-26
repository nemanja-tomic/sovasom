# Backup and recovery

The weekly Sunday Actions job and manual `backup` operation use the foundation's
narrow backup OIDC role. No AWS key or decryption identity belongs on the mini.
The runner uses pinned SSH host keys, receives only age ciphertext, uploads a
unique archive, downloads the exact S3 version and compares SHA-256 before writing
a success record. Failed dumps, encryption, transport, upload or verification
fail the job and block migration. An unverified object is never a success record.
The manual `migrate` operation uses the same transfer path before invoking setup;
a proven empty database skips the archive. Unknown database state fails closed.

Host deployment is configured in ticket 17. Do not rely on this automation until
an actual verified SSH/S3 round trip and an isolated restore of that archive have
passed. The synthetic recovery workflow does not establish production readiness.

## Setup

1. Install the pinned tools in `.tool-versions` on the mini, including age 1.3.2
   from its [official release](https://github.com/FiloSottile/age/releases/tag/v1.3.2).
   Verify the downloaded release checksum. The Intel macOS archive SHA-256 is
   `1d1e4bc66e1427edad7739ae7616157de0e79db8b6d2a1497d7d9925fb06a539`.
   SSH's noninteractive PATH must find uv, Docker and age. Docker Desktop must be
   running and the configured user must have access to the Compose database.
2. Generate an age identity with trusted operator tooling. Save it independently
   in the password manager and verify recovery access before first backup. Put
   **only its public recipient** in ignored `backup-recipient.txt` in the host
   checkout. Retain every old identity until all matching current/noncurrent
   archives have actually expired. Rotation is changing the public recipient and
   retaining old private keys; it does not re-encrypt old archives.
3. Configure GitHub variables `BACKUP_ROLE_ARN`, `AWS_ACCOUNT_ID`,
   `BACKUP_BUCKET_NAME` from the existing foundation outputs. Set
   `BACKUP_SSH_HOST` (user@host), `BACKUP_SSH_PORT` (default 22), `BACKUP_DIRECTORY` (absolute checkout directory),
   and `BACKUP_PREFIX` (dedicated `archives/…/` namespace). Set secrets
   `BACKUP_SSH_KEY` and `BACKUP_KNOWN_HOSTS`. Obtain the host key through an
   independently verified channel; `ssh-keyscan` alone does not verify it.
   For a custom port, its known-hosts name must be `[hostname]:port`; local
   backup controller JSON accepts a separate `port` field (default 22).
   Use a dedicated least-privilege host account/key. No private age key is a
   GitHub secret. Never print rendered configuration or upload secret files.
4. Enable Actions failure notifications for the operator and test actual receipt
   by causing a disposable workflow failure. Weekly backup runs Sunday 04:17 UTC;
   a separate daily age check runs 05:47 UTC and fails after 192 hours (eight days).
   Success records and age are visible through `status`. Manually retry `backup`
   after correcting failures, then run `status` and confirm fresh success.
   Actions may delay or drop scheduled jobs; independently check the Actions
   history/last success weekly. No notification system can detect its own total
   scheduler outage without independent monitoring.
5. Back up the private operator recovery bundle from ticket 15 independently,
   including bucket/prefix, IAM/MFA recovery instructions, public recipient/key
   custody, source revision, runtime configuration and database credentials.
   Independent AWS operator access is required for mini-loss recovery.

For local controller use, copy `infra/backup-config.json.example` to an ignored
private path, fill it, restrict permissions to 0600, then run:

```sh
uv run --frozen python scripts/backup.py --config "$BACKUP_CONFIG" backup
uv run --frozen python scripts/backup.py --config "$BACKUP_CONFIG" status
uv run --frozen python scripts/backup.py --config "$BACKUP_CONFIG" migrate
```

Use `migrate` only on the intended checked-out release. Ticket 17 must select the
release and serialize all deployments using `office-host-maintenance`, the same
Actions concurrency group as backups. Quiesce application/worker writes before
migration and retain prior images. Setup rejects an existing/unknown database
without the internal `--backup-gated` flag. This flag is a controller protocol,
not proof that an operator performed a backup: never use it as a manual bypass.
The low-level `office.setup` module is not a deployment entry point. An image
rollback does not roll back schema changes.

## Isolated restore

Keep recovery private identities on the trusted recovery workstation, never
permanently on the mini. A local isolated Docker PostgreSQL server and compatible
source version are required. The host command works against a private Compose
project; its restore destination must start with `office_restore_` and must not
exist. It never drops, cleans or overwrites a database. A failure may leave a new
empty recovery database; choose another fresh name for retry and inspect before
explicitly removing only disposable resources.

1. With independent operator AWS access, list `archives/<namespace>/success/`
   and download the desired success JSON. It gives the archive key, exact
   VersionId and ciphertext SHA-256. Download that version using `aws s3api
   get-object --bucket "$BUCKET" --key "$ARCHIVE_KEY" --version-id "$VERSION"
   "$ARCHIVE"`. Compare its SHA-256 with the success record. Keep these inputs in
   private files, outside tracked docs and logs.
2. Start a fresh isolated Compose database, using a different
   `COMPOSE_PROJECT_NAME`, private `.env` and isolated ports. Restore with:

   ```sh
   uv run --frozen python scripts/backup-host.py restore \
     --env-file "$RECOVERY_ENV" --archive "$ARCHIVE" \
     --identity "$TEMP_IDENTITY" --database office_restore_drill
   ```

   Inject the identity only temporarily from the password manager. Use a private
   temporary directory (0700), identity mode 0600, no shell tracing and no CI
   artifacts. The command decrypts to a private temporary dump, validates its full
   contents and restores in one transaction. Dump and ciphertext staging files
   are removed on normal exit/failure. An OS crash/forced kill can leave temporary
   files: use an encrypted local filesystem (FileVault on macOS), exclude this
   staging directory from backup/indexing, inspect cleanup, and remove temporary
   identities after use. Deletion is not a secure erase guarantee on SSDs.
3. Point a separate application instance at the restored database. Sign in with
   the restored account; check display name, office access, administrator and
   menu-maintainer grants, reload and sign out. Do not initialize, migrate or
   reset the source database during the drill. Record elapsed restore time and
   application results in ignored private evidence. Remove only disposable test
   resources after review.

The weekly recovery point means approximately seven days of possible lost data,
possibly longer after delayed or missed jobs. The restoration objective is one
working day, conditional on a working host/replacement, network, access and keys.
It is an objective, not a demonstrated production guarantee.

## Retention and operational acceptance

Terraform expires current objects only under `archives/` after 30 days, deletes
noncurrent versions after one day, aborts incomplete multipart uploads and removes
expired delete markers. State is in another bucket without archive expiry.
Unique archive names avoid shortening a prior archive's retention by overwriting
it. Success records expire under the same rule. S3 expiration and cleanup are
[asynchronous](https://docs.aws.amazon.com/AmazonS3/latest/userguide/troubleshoot-lifecycle.html),
so 30 days is an eligibility policy, not an exact deletion deadline. Noncurrent
expiry is measured from the successor's creation, not original upload time.

Before relying on recovery, use a disposable namespace and keep private evidence:

- Read back the bucket lifecycle policy and confirm the `archives/` filter,
  30-day expiration, one-day noncurrent expiration and delete-marker rule.
- Upload synthetic versions to the same disposable key; list versions and
  retrieve both to prove versioning. After expiry eligibility plus S3 processing
  time, list versions/delete markers again to prove actual cleanup. A mock or
  immediate manual deletion cannot prove timed lifecycle execution. Do not change
  shared production lifecycle configuration to accelerate the test. A separate
  disposable bucket may use a shorter rule for a timed canary drill.
- Deny upload or interrupt backup in the disposable configuration; verify job
  failure, unchanged last success, blocked migration, notification receipt, stale
  age detection and successful manual retry.
- Download and restore a real encrypted S3 archive into the isolated database;
  verify the account in the application and record actual time. Repeat using
  independently accessible credentials/configuration as if the mini were lost.

`PYTHONPATH=backend uv run --frozen python scripts/verify-backup.py` runs a
synthetic PostgreSQL 19/age drill, then removes only its own
Compose volumes. It checks restored sign-in/access/grants, existing-target
refusal and corrupt ciphertext. It needs Docker, age and age-keygen. The separate
recovery CI workflow runs it with pinned tools on relevant pushes to `main`, weekly
on Monday at 06:37 UTC, and manually. Relevant changes cover backup/setup scripts,
migrations, Compose, Python dependencies/tool versions and the backup workflows.
New runs cancel superseded runs for the same ref. Every push to `main` runs the
full backend test suite in main CI, with its own disposable PostgreSQL service.
The recovery drill does not repeat that suite. Neither workflow requires pull
requests. SSH/S3 failure tests replace those external process boundaries; they
are not live OIDC, SSH, notification or timed S3 expiry evidence.

## Production release integration

For the Mac mini use [the release controller](mac-mini-deployment.md), rather than
`backup.py migrate`/`scripts/setup.py`. The release controller stops writes and
reuses `Transfer.backup` before running pinned-image migrations. The manual backup
workflow now offers backup/status only. Set `BACKUP_DIRECTORY` to the deployed
`<root>/current`; its nonsecret `.env` selects `compose.release.yaml`, the stable
`office` project and external secret paths. This keeps scheduled backups attached
to the same persistent database across release directories.
