# AWS infrastructure and operator recovery

Start with the [onboarding checklists](../docs/onboarding-checklists.md).
This runbook is the detailed command reference for the shared-environment path.

Ticket 15 owns AWS storage, policies, workflow identities and the application DNS
record. The Mac mini, Docker, runtime `.env`, containers, database volumes and
Caddy certificate keys belong to host automation in ticket 17. Encrypted database
archive creation, monitoring and restore belong to ticket 16. No application
password, private encryption identity or SSH key goes into Terraform inputs.
Terraform state and plans remain sensitive even without those payloads.

## Ownership and access

| Root | Owns | Who may change it |
| --- | --- | --- |
| `foundation` | Private encrypted/versioned state and backup buckets, archive expiry, IAM roles/policies, optionally the GitHub OIDC provider | Independently authenticated operator |
| `application` | The app hostname's A record; references the retained backup bucket | Operator or main-branch infrastructure workflow role |

Both roots use Frankfurt (`eu-central-1`), Terraform 1.10 or newer within 1.x,
an exact AWS provider version and checked-in provider lockfiles. Run
`terraform init -lockfile=readonly` in CI.
Use only the default workspace. Application state is
`application/terraform.tfstate`; foundation state is
`foundation/terraform.tfstate` in a separate retained state bucket. Both backends
enable encryption and native S3 lockfiles. Foundation state has no expiration
rule. Neither GitHub role can read/write foundation state or alter retained
infrastructure. Backup access covers `archives/*` only and permits transfer,
not deletion. S3 lifecycle, owned by foundation, handles expiry after app teardown.

## Operator authentication

First complete [permanent local setup](local-setup/README.md): install the
tools from their official instructions, authenticate with your own MFA-protected
IAM user and configure the two AWS profiles in `~/.aws/config`. Local Terraform
inputs select the provider profile with `aws_profile`; local backend configuration
selects it with `profile`. Both example files use `sovasom-terraform`.
Renew your personal session and verify your identity:

```sh
aws login --profile sovasom-operator --region eu-central-1
aws --profile sovasom-terraform sts get-caller-identity
```

AWS CLI commands select the named profile explicitly. Terraform reads it from
the local inputs/backend configuration, so no shell environment file is needed.
CI leaves both profile settings unset and uses OIDC. Login grants no
infrastructure permissions by itself. Keep independently recoverable operator
access outside the mini and GitHub, with recovery instructions/MFA recovery and archive decryption identities
in the password manager. The local setup guide's corporate CA script persists
the certificate settings in `.zshrc`; new terminals load `AWS_CA_BUNDLE`
automatically for credential refresh.

If infrastructure already exists, use the onboarding guide's
[fresh-checkout procedure](local-setup/README.md#foundation-already-exists-fresh-checkout).
The bootstrap below is a one-time designated-operator operation, not a step for
every new developer.

## Bootstrap the retained foundation

The checked-in examples contain placeholders. Copy them to the ignored local
files and replace every `REPLACE_WITH_*` value with your own deployment inputs.
Use the same account, bucket and DNS settings consistently across both roots.
Keep those real values and your live verification notes outside version control.
Verify the account, existing public zone and OIDC providers using your profile:

```sh
aws --profile sovasom-terraform sts get-caller-identity
aws --profile sovasom-terraform route53 list-hosted-zones
aws --profile sovasom-terraform iam list-open-id-connect-providers
```

1. Check whether the account already has a GitHub OIDC provider for
   `token.actions.githubusercontent.com`. The default references it without
   taking ownership. If it is absent, set `create_github_oidc_provider = true`
   in your local inputs. Retain that choice in subsequent checkouts.
2. Publish the manual `Inspect trusted infrastructure OIDC subject` workflow
   through your repository's normal process and run it on `main`. Put its exact
   observed `sub` in your local foundation inputs. It prints only subject and
   audience, never the token. Subjects can contain immutable owner/repository IDs;
   keep them in local inputs and private evidence. AWS trust uses `StringEquals`
   for subject and STS audience. If choosing a protected GitHub environment, use
   it in the diagnostic/consuming jobs, restrict its branches and record its exact
   subject. Existing shared hosted zones/providers remain outside Terraform's
   ownership unless deliberately imported.
3. Start in a private operator checkout with no `foundation/backend.tf` yet:

```sh
umask 077
cp infra/foundation/terraform.tfvars.example infra/foundation/terraform.tfvars
# Replace every placeholder with local deployment inputs, including the exact OIDC subject.
terraform -chdir=infra/foundation init -lockfile=readonly
terraform -chdir=infra/foundation plan -out=bootstrap.tfplan
terraform -chdir=infra/foundation apply bootstrap.tfplan
```

Inspect the plan before applying: only the selected account's retained buckets,
two application-specific roles/policies and, if explicitly selected, OIDC
provider should be created. The operator session, not GitHub, bootstraps trust.
Terraform initially keeps local state so it can create its own backend bucket.
Retain an encrypted off-machine copy of this initial state until migration and
remote recovery verification finish. Local state/plan files must be private and
are gitignored; delete the bootstrap plan after use.

4. Migrate that **same existing state**, rather than starting a new empty state:

```sh
cp infra/foundation/backend.tfbackend.example infra/foundation/production.tfbackend
cp infra/foundation/backend.tf.example infra/foundation/backend.tf
terraform -chdir=infra/foundation init -migrate-state -backend-config=production.tfbackend -lockfile=readonly
terraform -chdir=infra/foundation state list
terraform -chdir=infra/foundation plan -detailed-exitcode
```

Confirm the migration prompt. The subsequent plan must have no changes (exit 0).
Verify both state objects' versioning and locking on disposable infrastructure
using the checks below. Once migrated, every fresh foundation checkout needs
`backend.tf` copied from the template before initialization. Never run foundation
apply with a fresh local backend against existing resources. Existing OIDC
providers and the hosted zone stay outside both states unless deliberately
imported; shared zone/provider replacement is never an application operation.

## Application DNS and GitHub Actions

This is a one-time setup for the shared production environment. Other developers
use the same DNS record and GitHub repository settings after authenticating with
their own IAM users. Complete the foundation apply and S3 state migration first.

### 1. Create the DNS plan

Terraform will create a new A record using `app_hostname` and `public_ipv4`
from your local application inputs, in the selected existing Route 53 zone. This setup assumes the A record does not exist; no import
command is needed. Terraform will track the new record in application state.

From the repository root, on the first application setup:

```sh
umask 077
cp infra/application/terraform.tfvars.example infra/application/terraform.tfvars
cp infra/application/backend.tfbackend.example infra/application/production.tfbackend
# Replace placeholders in both local files with your own deployment settings.
terraform -chdir=infra/application init -backend-config=production.tfbackend -lockfile=readonly
terraform -chdir=infra/application plan -out=dns.tfplan
```

If you already created `dns.tfplan`, continue with step 2; do not recopy your
local configuration files.

### 2. Apply the DNS plan

Display the saved plan. For the first setup, expect one resource to be created:
`aws_route53_record.application`, with your configured hostname and public IPv4,
type `A` and TTL 300 seconds.

```sh
terraform -chdir=infra/application show dns.tfplan
terraform -chdir=infra/application apply dns.tfplan
```

The second command creates the record and saves its identity in remote state.
The `-chdir` option makes both commands find `dns.tfplan` inside
`infra/application`. Afterward, this command displays the configured app URL:

```sh
terraform -chdir=infra/application output -raw application_origin
```

DNS now points at the Mac mini's public address. Serving the application over
HTTPS is completed by deployment ticket 17.

### 3. Give GitHub Actions its configuration

The `Manage application infrastructure` workflow runs on a GitHub-hosted machine.
It cannot read your gitignored `terraform.tfvars`, backend file or personal
`~/.aws/config`. Repository variables supply the configuration it needs to
connect to the same AWS resources. The workflow reads them as `${{ vars.NAME }}`.
OIDC supplies temporary AWS credentials; these variables contain identifiers and
addresses, not passwords or access keys.

Configure them **once for the repository**, not once per developer. Install
[GitHub CLI](https://cli.github.com/) and sign in with your own GitHub account
that can administer this repository's Actions variables:

```sh
gh auth login
```

Then run the block below from the repository root with Python 3 available.
It reads all values from your local Terraform inputs and applied foundation
outputs, and detects the repository from your current checkout. Nothing needs
to be copied from a public example or entered into this document. All reads
complete before the first GitHub variable is changed. Rerunning updates values.

```sh
python3 - <<'PYTHON'
import json
import subprocess


def read(*command):
    return subprocess.check_output(command, text=True).strip()


repository = read("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
expression = "jsonencode({AWS_ACCOUNT_ID=var.aws_account_id, HOSTED_ZONE_ID=var.hosted_zone_id, APP_HOSTNAME=var.app_hostname, PUBLIC_IPV4=var.public_ipv4})"
encoded = subprocess.check_output(
    ["terraform", "-chdir=infra/application", "console"], input=expression + "\n", text=True
)
values = json.loads(json.loads(encoded))
for variable, output in {
    "TF_STATE_BUCKET": "state_bucket_name",
    "BACKUP_BUCKET_NAME": "backup_bucket_name",
    "INFRASTRUCTURE_ROLE_ARN": "infrastructure_role_arn",
    "BACKUP_ROLE_ARN": "backup_role_arn",
}.items():
    values[variable] = read("terraform", "-chdir=infra/foundation", "output", "-raw", output)
for name, value in values.items():
    subprocess.run(
        ["gh", "variable", "set", name, "--repo", repository, "--body", value], check=True
    )
PYTHON
```

See the saved values in your GitHub repository under **Settings → Secrets and
variables → Actions → Variables → Repository variables**. For manual editing,
use **New repository variable**, enter the value from the matching local input
or Terraform output below, then select **Add variable**.

| Variable | Local source | Workflow purpose |
| --- | --- | --- |
| `AWS_ACCOUNT_ID` | Application input `aws_account_id` | Restricts authentication to the intended AWS account |
| `TF_STATE_BUCKET` | Foundation output `state_bucket_name` | Locates application state and its lock file |
| `BACKUP_BUCKET_NAME` | Foundation output `backup_bucket_name` | References retained backup storage |
| `INFRASTRUCTURE_ROLE_ARN` | Foundation output `infrastructure_role_arn` | Selects GitHub's OIDC infrastructure role |
| `BACKUP_ROLE_ARN` | Foundation output `backup_role_arn` | Prepares the backup workflow in ticket 16 |
| `HOSTED_ZONE_ID` | Application input `hosted_zone_id` | Selects the existing public zone |
| `APP_HOSTNAME` | Application input `app_hostname` | Sets the DNS record name |
| `PUBLIC_IPV4` | Application input `public_ipv4` | Sets the DNS destination |

These values are not passwords, but they still identify your deployment. Store
them in local ignored configuration and your own repository's Actions settings,
not in public examples, docs or fixtures.

The local apply in step 2 works independently of these repository variables.
They enable the subsequent GitHub workflow. Repeat their setup when the shared
environment's configuration changes.

### 4. Verify the GitHub workflow

The checked-in workflow files must be on the repository's `main` branch before
GitHub can run them. Once they are there:

1. Open your repository's **Actions** tab.
2. Select **Manage application infrastructure** in the left sidebar.
3. Select **Run workflow**, branch **main**, operation **plan**, then **Run workflow**.
4. Open the run and check **Plan current main**. After the successful local DNS
   apply, it should report no changes if the configuration still matches.

For later public-IP changes, update `PUBLIC_IPV4` and run the workflow with
operation **apply** to generate and apply its current plan. This workflow manages
the application infrastructure/DNS; application image deployment belongs to
ticket 17. It uses the narrow OIDC role and serialized, locked state operations.
Protect main/workflow administration: trusted main workflows with
`id-token: write` can request that branch's subject.

References: [GitHub repository variables](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables),
[GitHub CLI variable command](https://cli.github.com/manual/gh_variable_set),
[manual workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

## Recovery and isolated live verification

Run these on **new disposable roots/resources**, with a distinct `name`, backend
bucket and unused DNS name. Keep production tfvars/state out of that checkout.
The sandbox hostname must also be reflected in its role policy. Retain deployment-specific evidence (resource names, object/version IDs and
command results) in private operator notes. Keep public `verification.md` generic.
Never test production destruction or overwrite production state.

- Verify encryption, public-access block, ownership, versioning and TLS-only
  policies with `aws --profile sovasom-terraform s3api get-bucket-encryption`, `get-public-access-block`,
  `get-bucket-ownership-controls`, `get-bucket-versioning`, `get-bucket-policy`.
  Anonymous HTTP/HTTPS reads must fail. Inspect the two actual role policies and
  use IAM policy simulation/real assumed sessions to prove allowed archive/DNS
  operations and denied foundation-state reads, unrelated DNS writes and deletes.
- Exercise competing Terraform operations on the **same disposable state key**:
  hold the first operation's lock using an interactive apply, and run another
  plan with `-lock-timeout=5s`. It must fail to acquire the native S3 lock. Cancel
  the first operation normally and confirm its `.tflock` object disappears.
  Never force-unlock an active operation. Do not use `-lock=false`.
- Make two harmless disposable state updates; list versions with
  `aws --profile sovasom-terraform s3api list-object-versions --bucket BUCKET --prefix foundation/terraform.tfstate`.
  Download a known prior version to a private file with
  `aws --profile sovasom-terraform s3api get-object --bucket BUCKET --key foundation/terraform.tfstate --version-id VERSION recovered.tfstate`.
  Compare its lineage/resources using Terraform locally. For an actual state
  recovery, stop all writers, preserve the latest version, download/inspect the
  chosen good version and follow Terraform's state-push lineage/serial checks.
  Do not blindly use `state push -force`; reconcile cloud reality with a new
  plan before applying. Bucket policy denies state-version deletion but allows
  writing a new current version; it deliberately excludes lock objects.
- Upload only synthetic encrypted archive objects below `archives/` using the
  backup role. Verify upload/download round trip; state access, unrelated
  prefixes and archive deletion must fail. Lifecycle is 30 days for current
  archives and one day after supersession for noncurrent versions. Use unique
  timestamped keys and never overwrite an archive: supersession can shorten its
  retained version's lifetime. Expired markers and unfinished multipart uploads
  are cleaned up. S3 expiry is asynchronous and day-based; inspecting a policy
  is not proof that timed deletion occurred. Record elapsed/live expiry evidence
  when available; ticket 16 verifies backup completeness and retention behavior.
- Save foundation bucket/object/version inventories, plan and apply a disposable
  **application** destroy, then compare inventories. Only its A record should
  disappear. Both retained buckets, state history, archive contents, IAM roles
  and archive lifecycle remain. The application state object remains recoverable.
- A disposable `terraform -chdir=infra/foundation plan -destroy` must fail with
  `prevent_destroy` errors for the retained buckets. Do not remove the guards to
  make this check pass, and do not apply that plan. The offline test also proves
  this behavior with synthetic state, but does not establish live IAM behavior.

Keep a private recovery bundle in a password manager or encrypted storage that
you can access without the mini, GitHub Actions or the current checkout:

- [ ] Retain your own IAM sign-in details and MFA/recovery access independently.
  Keep credentials outside the bundle and repository.
- [ ] Save a source snapshot/revision, both roots' private `terraform.tfvars` and
  `production.tfbackend` files, and the foundation's active `backend.tf`. Include
  the account, state bucket/key locations and the existing OIDC provider's
  ownership choice. Exclude `.terraform`, session caches, application secrets and
  local state/plan files. Keep detailed operational evidence separately and privately.
- [ ] On a trusted workstation, follow the [local setup guide](local-setup/README.md)
  with your own IAM identity. Restore the bundle into a private directory and
  adjust only the personal profile names if necessary.
- [ ] Initialize each root against its **existing** backend using
  `init -reconfigure -backend-config=production.tfbackend -lockfile=readonly`.
  Do not repeat bootstrap or create new empty state. Inspect state resources,
  retrieve a versioned state object and run a no-change plan before any apply.
- [ ] Confirm the saved bundle is independently accessible. Refresh it when
  configuration, state locations, ownership or source revision changes.

No original host, GitHub deployment token or private key from the mini is required
for these infrastructure checks. Ticket 16 supplies the separate encrypted
database restore with a vault-held private identity. Preserve old decryption
identities until their archives expire.

## Teardown and full retirement

Normal teardown is an application-root destroy only; inspect the plan first.
It does not shut down the host stack, which ticket 17 owns. Archive expiry keeps
running after teardown. Foundation uses `prevent_destroy = true` and
`force_destroy = false`. These are Terraform configuration protections, not S3
Object Lock: removing the resource configuration/guards, changing policies or
authorized direct AWS deletion can bypass them. Independent account access is
therefore part of recovery, and state/version permissions must remain restricted.

Full retirement is a separate explicit operator procedure: stop writers/backup
jobs; retain required archives, decryption identities and a final encrypted state
export independently; review other consumers of the zone/OIDC provider; remove
only application-owned DNS/IAM; explicitly revise bucket-policy/deletion guards
in a reviewed change; only then remove every intended object version/delete
marker and delete buckets. Never automatically empty retained buckets. Shared
hosted zones/OIDC providers must remain if any other application uses them.

## Local verification

```sh
terraform fmt -check -recursive infra
terraform -chdir=infra/foundation init -backend=false -lockfile=readonly
terraform -chdir=infra/foundation validate
terraform -chdir=infra/foundation test
terraform -chdir=infra/application init -backend=false -lockfile=readonly
terraform -chdir=infra/application validate
terraform -chdir=infra/application test
uv run --frozen python infra/check_teardown.py --root foundation
uv run --frozen python infra/check_teardown.py --root application
uv run --frozen ruff check
```

The teardown checks copy only configuration and lockfiles into temporary local
directories, seed synthetic state, use fake credentials and disable AWS credential
probes. They never load real backends, tfvars or AWS profiles. They require each
root's provider to have been initialized first. They verify actual Terraform
destroy-plan behavior without making cloud calls. CI repeats these tests; live
checks above remain necessary before recording the operational slice complete.

Primary references: [S3 backend permissions and locking](https://developer.hashicorp.com/terraform/language/backend/s3),
[AWS/GitHub OIDC trust](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws),
[AWS CLI browser login](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html),
[S3 lifecycle and versioned objects](https://docs.aws.amazon.com/AmazonS3/latest/userguide/intro-lifecycle-rules.html).
