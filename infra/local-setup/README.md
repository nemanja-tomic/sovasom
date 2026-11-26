# Permanent local AWS and Terraform setup

Start with the [onboarding checklists](../../docs/onboarding-checklists.md).
This guide is the detailed command reference for the developer path.

Follow this guide on each developer's workstation. Each developer signs in with
their own IAM user in their deployment's AWS account; profile names are local labels,
so everyone can use the same labels without sharing identities or credentials.
Tools, AWS profiles and optional corporate certificates live outside the checkout
in permanent locations. AWS sessions remain temporary and require renewed login.

This guide covers macOS (Apple Silicon or Intel) and Linux (arm64 or x86_64).
Windows developers can follow the Linux steps inside WSL2. Installing tools and
authenticating do not provision infrastructure. Applying infrastructure is a
separate operator action in [the infrastructure runbook](../README.md).

## 1. Get access and clone the repository

An AWS administrator must give each developer:

- Their own non-root IAM console user in the deployment account, with MFA.
- The AWS-managed policy
  `arn:aws:iam::aws:policy/SignInLocalDevelopmentAccess` for CLI browser login.
- Task-specific permissions. Login permission alone does not grant S3, IAM or
  Route 53 access. Read/plan access and permission to change production are
  separate responsibilities. Foundation bootstrap needs an authorized operator
  who can create/configure the two S3 buckets, manage the application's two IAM
  roles/inline policies and create the GitHub OIDC provider if absent. DNS changes
  need access to the existing zone's app A record. State access needs read/write
  on the selected state key and read/write/delete on its `.tflock` object.

The GitHub workflow roles trust GitHub OIDC, not developer IAM users. Developers
use their own granted IAM permissions; do not alter those trust policies to
enable local login. Ordinary application development and synthetic infrastructure
tests can run without production AWS access.

Install Git and Bash with your OS tools first. On macOS, Git is available
through Apple's Command Line Tools (`xcode-select --install`). Clone using your
own GitHub access:

```sh
git clone https://github.com/YOUR_ORG/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
```

All repository commands below run from this checkout's root. Public Terraform
examples use `REPLACE_WITH_*` placeholders. Fill them only in the ignored local
files; account IDs, hostnames, IPs, buckets and OIDC IDs stay out of Git history.

## 2. Save corporate certificates in zsh, when required

If your network uses Zscaler or another TLS inspection proxy, obtain your
organization's PEM CA bundle from IT and keep it at a permanent path such as
`~/.certs/combined-ca.pem`. Developers without TLS inspection can skip this step.

Run this once from the repository root, using your own bundle path:

```sh
bash scripts/configure-corporate-ca.sh "$HOME/.certs/combined-ca.pem"
```

The script adds a managed block to `~/.zshrc` (or `$ZDOTDIR/.zshrc` when set).
It preserves unrelated configuration, dotfile symlinks and existing permissions.
Rerunning updates the block without duplicating it, so use the same command if
your bundle moves. It rejects missing/unreadable files and files without PEM
certificate markers; IT remains responsible for the actual certificate trust
chain. It writes only the bundle path, not certificate contents or credentials.

Open a new terminal after setup. Every subsequent zsh session loads the settings
automatically. To load them into the current terminal immediately:

```sh
source "${ZDOTDIR:-$HOME}/.zshrc"
```

The block configures `AWS_CA_BUNDLE` (AWS login, API calls and credential refresh),
`SSL_CERT_FILE` (Python and supported TLS clients), `CURL_CA_BUNDLE`,
`REQUESTS_CA_BUNDLE` and `NODE_EXTRA_CA_CERTS`. On macOS, also ensure the corporate
CA is trusted in Keychain using your IT procedure for clients such as Terraform.
TLS verification stays enabled. These settings apply to all tools launched from
zsh, including other projects. The script targets zsh; Bash users can supply
`"$HOME/.bashrc"` as its optional second argument and load that file instead.

## 3. Install Terraform and AWS CLI

Use the official instructions for your operating system and install the current
stable releases into permanent locations:

- [Install Terraform](https://developer.hashicorp.com/terraform/install).
- [Install or update AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

Follow the installer's PATH instructions, then open a new terminal and verify:

```sh
command -v terraform
terraform version
command -v aws
aws --version
```

Developer CLI versions are not pinned. Terraform must be 1.10 or newer within
1.x for native S3 locking; AWS CLI v2 must support `aws login` (introduced in
2.32.0). The AWS provider and its dependency lockfiles remain pinned independently
of the developer's CLI installation. CI records the Terraform version it tests.

## 4. Create your own persistent AWS profiles

If transitioning from the earlier temporary setup, clear `AWS_CONFIG_FILE` so
AWS uses your normal `~/.aws/config`. Clear static credential overrides in this
project shell as well; they could otherwise select another identity:

```sh
unset AWS_CONFIG_FILE AWS_SHARED_CREDENTIALS_FILE
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
unset AWS_PROFILE AWS_DEFAULT_PROFILE
umask 077
mkdir -p "$HOME/.aws"
chmod 700 "$HOME/.aws"
aws configure set region eu-central-1 --profile sovasom-operator
aws configure set output json --profile sovasom-operator
aws login --profile sovasom-operator --region eu-central-1
```

In the browser choose **your own IAM user** in the shared account and complete
MFA. The CLI writes your `login_session` to `~/.aws/config` and manages temporary
credentials in `~/.aws/login/cache`. Do not copy a teammate's `login_session`,
cache directory or access keys. You do not need to run `aws configure` to create
long-lived access keys. Installing optional agent integrations during login is
not required by this repository.

Configure a second profile so both Terraform's backend and AWS provider can use
the CLI's refreshable login through the standard credential-process interface:

```sh
aws configure set credential_process \
  "\"$(command -v aws)\" configure export-credentials --profile sovasom-operator --format process" \
  --profile sovasom-terraform
aws configure set region eu-central-1 --profile sovasom-terraform
aws configure set output json --profile sovasom-terraform
chmod 600 "$HOME/.aws/config"
```

The saved command points to the permanently installed `aws`, not a download
directory. It obtains credentials on demand; no credential output is saved in
the repository. If the executable's installed path changes, rerun this block.

## 5. Select the named profile in local Terraform configuration

Region and output format are already stored in `~/.aws/config` by step 4.
Select that profile explicitly for AWS CLI commands:

```sh
aws --profile sovasom-terraform sts get-caller-identity --query '{Account:Account,Arn:Arn}'
```

Verify the account matches your local `aws_account_id` input and the ARN belongs
to your own IAM user. Keep your other
projects' default AWS profile unchanged. No project shell settings file or
region/profile exports are needed. Certificate settings continue loading from
`.zshrc` automatically.

Terraform needs profile selection in two independent places:

| Local file, in each Terraform root | Setting | Used by |
| --- | --- | --- |
| `terraform.tfvars` | `aws_profile = "sovasom-terraform"` | AWS provider, for managed resources |
| `production.tfbackend` | `profile = "sovasom-terraform"` | S3 backend, for state and locking |

Set these values in each root's local files after copying the placeholder
examples using the fresh-checkout procedure below; for an existing checkout, add the settings to
its existing files without replacing the other inputs. These local files are
gitignored. Reinitialize an existing remote backend after changing its profile:

```sh
terraform -chdir=infra/foundation init -reconfigure -backend-config=production.tfbackend -lockfile=readonly
terraform -chdir=infra/application init -reconfigure -backend-config=production.tfbackend -lockfile=readonly
```

Use those reinitialization commands only after the foundation has been migrated
to S3. The initial local-to-S3 bootstrap uses `-migrate-state` in the runbook.
After initialization, ordinary `terraform plan` commands use the configured
profile without any shell setup. `umask 077` is applied before commands that
create private local files rather than stored as an AWS setting.

CI does not copy the developer example files. The provider's optional
`aws_profile` defaults to `null`, and the CI backend configuration omits
`profile`, so GitHub's OIDC credentials continue to work.

If you followed the earlier environment-file setup, remove its source command
from your workflow or shell startup file and clear the old overrides in your
current terminal:

```sh
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_REGION AWS_DEFAULT_REGION
```

Authentication remains temporary: repeat
`aws login --profile sovasom-operator` when the session expires. To sign out,
run `aws logout --profile sovasom-operator`.

## 6. Join existing infrastructure, or bootstrap it once

Ask the infrastructure owner whether foundation has already been bootstrapped.
Each developer needs their own tools/login, but the team shares **one production
foundation, one application state and one set of AWS resources**. Authentication
does not require rerunning bootstrap or creating another OIDC provider.

### Foundation already exists: fresh checkout

Get the current non-secret foundation inputs from its owner: exact OIDC subject
and the retained `create_github_oidc_provider` ownership choice. If the foundation
created the provider, keep that value `true` in subsequent checkouts. Changing it
to `false` would try to remove the managed provider. Keep application account,
zone, hostname, IP and bucket inputs aligned with the shared environment.

```sh
umask 077
cp infra/foundation/terraform.tfvars.example infra/foundation/terraform.tfvars
cp infra/foundation/backend.tfbackend.example infra/foundation/production.tfbackend
cp infra/foundation/backend.tf.example infra/foundation/backend.tf
# Fill all placeholders in the local inputs/backend file to match the existing foundation.
terraform -chdir=infra/foundation init -backend-config=production.tfbackend -lockfile=readonly
terraform -chdir=infra/foundation state list
terraform -chdir=infra/foundation plan

cp infra/application/terraform.tfvars.example infra/application/terraform.tfvars
cp infra/application/backend.tfbackend.example infra/application/production.tfbackend
# Fill all placeholders in both local files with your deployment settings.
terraform -chdir=infra/application init -backend-config=production.tfbackend -lockfile=readonly
terraform -chdir=infra/application plan
```

Run these once per fresh checkout, without overwriting existing local inputs.
The foundation backend file must be present **before** its first initialization
so the checkout joins existing state. Do not run a local-state bootstrap against
an environment that already exists. Use only the default Terraform workspace.
Coordinate production changes with the team; native S3 locking prevents concurrent
state writes but is not a substitute for coordinating competing plans.

### Foundation does not exist: designated operator only

Follow [Bootstrap the retained foundation](../README.md#bootstrap-the-retained-foundation)
for the initial local-state apply and immediate migration into protected S3.
Then follow the application DNS steps. Review each plan before applying it.
The remaining developers use the existing-infrastructure path above after the
operator has verified remote state. No commands in this onboarding guide apply
AWS changes automatically.

### Create application DNS and configure GitHub Actions

Continue with [Application DNS and GitHub Actions](../README.md#application-dns-and-github-actions)
in the infrastructure runbook. It assumes a new A record and gives the exact
plan/apply commands. If you already created `dns.tfplan`, start at
[step 2: apply the saved plan](../README.md#2-apply-the-dns-plan).

The next step configures GitHub once for the shared repository. Its copyable
command block reads the foundation's Terraform outputs and saves the required
Actions variables; it explains where each value comes from and what the workflow
uses it for. Other developers do not repeat this repository setup.

## Troubleshooting and verification

| Symptom | Check |
| --- | --- |
| Wrong executable/version | `command -v aws`, `aws --version`, `command -v terraform`, `terraform version`; check permanent PATH |
| Profile disappeared after reboot | Remove old temporary `AWS_CONFIG_FILE` settings; profiles should be in `~/.aws/config` |
| Wrong AWS identity | Check exported static keys/profile overrides, then log in with your own IAM user and rerun STS |
| Token or API TLS certificate error | Run the corporate CA script once and open a new terminal; its block includes `AWS_CA_BUNDLE` for refresh |
| Login succeeds but Terraform fails TLS | Verify corporate CA trust and `SSL_CERT_FILE`; keep certificate verification on |
| `AccessDenied` after successful login | Ask the AWS administrator for the specific operation/resource permission; login policy alone grants no infrastructure access |
| Session expired | Repeat `aws login --profile sovasom-operator --region eu-central-1` |
| Foundation plans to create everything unexpectedly | Check backend initialization/state ownership before proceeding; do not apply |

Use [local infrastructure verification](../README.md#local-verification) for
credential-free synthetic tests and the runbook's isolated live checks before
recording production readiness. Tool installation and login must be performed by each developer; syntax checks
do not prove their workstation has been installed or authenticated.

References: [AWS CLI installation](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html),
[AWS browser login and credential-process profiles](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html),
[AWS CA configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html),
[Terraform installation](https://developer.hashicorp.com/terraform/install).
