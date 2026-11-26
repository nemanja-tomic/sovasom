# Onboarding checklists

There are two onboarding paths: **developer setup** for each person/machine, and
**shared setup** for each deployment environment and GitHub repository. Shared
setup is usually performed once, then maintained as configuration changes. It is
repeated when creating a new environment or rebuilding retired infrastructure.

This page is the checklist; the linked guides contain the commands. Keep this
public copy unchecked. Track personal progress and actual deployment values in
private notes and ignored local configuration.

| Work | Who repeats it? |
| --- | --- |
| Personal IAM/GitHub access | Each developer |
| Tools, certificates and AWS profiles | Each developer on each machine/OS account |
| Ignored Terraform configuration and backend initialization | Each fresh checkout |
| Shared AWS resources, DNS and GitHub Actions variables | Designated operator, once per environment/repository |
| Login renewal, configuration changes and recovery exercises | Recurring work after onboarding |

For the first environment, the operator completes developer setup through AWS
identity verification, performs shared setup, then finishes connecting their
checkout to remote state. Everyone joining later uses the existing remote state.

## Developer onboarding

Owner: each developer. AWS-related steps apply to developers working on
infrastructure; local application development can run without production access.

- [ ] Obtain your own GitHub access and, for infrastructure work, an IAM user
  with MFA, CLI login permission and task-specific AWS permissions.
  [Access requirements](../infra/local-setup/README.md#1-get-access-and-clone-the-repository)
- [ ] Clone the repository using your own GitHub identity.
  [Clone instructions](../infra/local-setup/README.md#1-get-access-and-clone-the-repository)
- [ ] If your network requires a corporate CA, run the certificate setup script
  once and open a new terminal. Skip this on networks without TLS inspection.
  [Certificate setup](../infra/local-setup/README.md#2-save-corporate-certificates-in-zsh-when-required)
- [ ] Install Terraform and AWS CLI from their official instructions, and verify
  both commands resolve to permanent installations.
  [Tool installation](../infra/local-setup/README.md#3-install-terraform-and-aws-cli)
- [ ] Create your personal login and Terraform credential-process profiles in
  `~/.aws/config`, then authenticate with your own IAM user.
  [AWS profiles](../infra/local-setup/README.md#4-create-your-own-persistent-aws-profiles)
- [ ] Run the identity check and confirm it shows your user and the intended
  deployment account.
  [Profile selection](../infra/local-setup/README.md#5-select-the-named-profile-in-local-terraform-configuration)
- [ ] Obtain the environment's current configuration privately from its owner,
  including the OIDC provider ownership choice and exact subject.
- [ ] In this checkout, copy the Terraform example inputs/backend files and fill
  every placeholder in the ignored local copies. Set your local profile for
  both the provider and backend; retain existing files when already configured.
  [Local configuration](../infra/local-setup/README.md#5-select-the-named-profile-in-local-terraform-configuration)
- [ ] Once shared setup exists, initialize both roots against the existing S3
  backend and inspect their plans. A new developer joining an unchanged
  environment should see the existing resources and no proposed changes.
  [Join existing infrastructure](../infra/local-setup/README.md#foundation-already-exists-fresh-checkout)
- [ ] If developing the application, prepare the local `.env`, start Docker and
  run application setup; verify local sign-in.
  [Start locally](../README.md#start-locally)
- [ ] If using the repository's Codex MCP integrations, configure your own tokens
  and run the separate MCP onboarding command.
  [Developer integrations](../README.md#developer-onboarding)

**Complete when:** your tools and personal login work, your infrastructure
checkout uses the existing remote state, and any local application/integration
tools you need are running. Your personal setup reuses the shared resources.

## Shared onboarding

Owner: the designated infrastructure operator. Complete this once for a new
deployment environment/repository, using a machine prepared as above. Other
developers join the result through their own profiles.

- [ ] Choose the deployment account, existing public hosted zone, app hostname,
  host public address and resource prefix. Keep the actual values private.
  [Foundation inputs](../infra/README.md#bootstrap-the-retained-foundation)
- [ ] Make the infrastructure workflows available on the repository's `main`
  branch through the normal review/publishing process.
  [Workflow prerequisite](../infra/README.md#4-verify-the-github-workflow)
- [ ] Discover the account's existing GitHub OIDC provider. Reference it when
  present, or configure the foundation to create and own it when absent.
  [OIDC ownership](../infra/README.md#bootstrap-the-retained-foundation)
- [ ] Run the OIDC diagnostic workflow and put the exact observed subject in the
  private foundation inputs.
  [OIDC subject setup](../infra/README.md#bootstrap-the-retained-foundation)
- [ ] Fill the private foundation inputs, generate and review the initial plan,
  then apply it to create the retained storage and workflow identities.
  [Foundation bootstrap](../infra/README.md#bootstrap-the-retained-foundation)
- [ ] Migrate that initial state into the protected S3 backend. Verify the state
  lists the resources and a subsequent plan has no changes.
  [State migration](../infra/README.md#bootstrap-the-retained-foundation)
- [ ] Fill the private application inputs/backend configuration, initialize it,
  and create the DNS plan.
  [DNS plan](../infra/README.md#1-create-the-dns-plan)
- [ ] Review and apply the saved DNS plan. Terraform creates the new A record
  and records it in shared application state.
  [DNS apply](../infra/README.md#2-apply-the-dns-plan)
- [ ] Sign into GitHub CLI and run the provided configuration block. It reads
  local Terraform values and saves repository Actions variables for the team.
  [GitHub variable setup and purpose](../infra/README.md#3-give-github-actions-its-configuration)
- [ ] Run **Manage application infrastructure** on **main** with operation
  **plan**. Confirm successful OIDC authentication, state access and a no-change
  plan for the configuration just applied.
  [Workflow verification](../infra/README.md#4-verify-the-github-workflow)
- [ ] Verify storage protection, permissions, locking/version recovery and
  retained resources during teardown using isolated disposable resources.
  Keep deployment-specific evidence in private operator notes.
  [Operational verification](../infra/README.md#recovery-and-isolated-live-verification)
- [ ] Give the team a private handoff of the environment configuration, state
  locations, provider ownership choice and recovery instructions. Ensure
  independent operator access remains available outside the host and GitHub.
  [Recovery runbook](../infra/README.md#recovery-and-isolated-live-verification)

**Complete when:** shared infrastructure and DNS exist, GitHub can plan against
their remote state through OIDC, recovery checks have evidence, and another
authorized developer can join through their own IAM profile.

Continue with backup/restore and Mac mini application deployment work after this
AWS infrastructure setup.

## After onboarding

- Renew your personal AWS login when it expires; tooling/profile installation
  stays in place. [Login renewal](../infra/local-setup/README.md#5-select-the-named-profile-in-local-terraform-configuration)
- On another machine, repeat developer setup. In another checkout on the same
  machine, repeat only local configuration/backend initialization.
- Update your certificate block if the bundle path changes, and your saved
  credential-process command if the AWS executable path changes.
  [Certificate setup](../infra/local-setup/README.md#2-save-corporate-certificates-in-zsh-when-required),
  [AWS profiles](../infra/local-setup/README.md#4-create-your-own-persistent-aws-profiles)
- When shared settings change, review/apply the corresponding Terraform changes
  and update GitHub variables. [Shared workflow configuration](../infra/README.md#3-give-github-actions-its-configuration)
- Repeat recovery exercises and retain operator evidence privately.
  [Operational verification](../infra/README.md#recovery-and-isolated-live-verification)
