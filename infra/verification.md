# Infrastructure verification evidence

Public evidence records reproducible checks without operator account IDs,
hostnames, IP addresses, bucket/role names, user identities or OIDC subject IDs.
Keep deployment-specific discovery, plans and live recovery results in private
operator notes alongside the ignored local configuration.

## Automated checks

- Foundation mock plans cover retained/private/encrypted/versioned storage,
  archive lifecycle, TLS-only policy, scoped workflow roles and exact OIDC trust.
- PR and wildcard OIDC subjects are rejected.
- Application mock plans cover DNS creation and invalid address/zone inputs.
- Destroy plans against synthetic local state reject foundation bucket deletion
  and restrict application deletion to the application's DNS record.
- Corporate CA onboarding tests use disposable shell profiles.
- Terraform example checks reject deployment strings in public input templates.

Run the commands in the infrastructure runbook to reproduce these checks.
Synthetic tests establish configuration behavior; actual IAM, locking, recovery,
retention and deployment checks require isolated live resources and private
operator evidence. Infrastructure must be applied only at the operator's request.

## Isolated live teardown verification

An operator-authorized disposable AWS stack was created and retired for this
check. Detailed evidence is retained privately under the ignored
`.scratch/private/` directory.

- Application teardown deleted only its temporary DNS record; retained storage,
  prior state history, synthetic object versions, lifecycle configuration and
  workflow identities survived.
- Both synthetic object versions were retrieved byte-for-byte. An earlier state
  version was retrieved with matching lineage and an earlier serial.
- A native S3 lock blocked a competing Terraform operation and was released on
  cancellation of the first operation, without applying its proposed change.
- Actual S3 protection settings were checked. IAM allow/deny checks used policy
  simulations; real assumed-role service calls were not exercised by this test.
- Foundation destroy planning failed for both protected buckets.
- The disposable resources were explicitly retired after verification. Existing
  deployment DNS and state versions were unchanged throughout the test.

This check establishes teardown retention, not timed archive expiry or database
backup restoration.

## Independent infrastructure recovery verification

The operator confirmed that IAM sign-in details and MFA/recovery access are
available independently of the mini and GitHub Actions.

- A private source/configuration bundle was used to initialize both existing S3
  backends in fresh directories with a fresh provider cache. GitHub credentials
  were removed from the verification process environment.
- Both roots listed existing resources and produced no-change plans. A versioned
  state object from each backend was downloaded and its lineage/serial matched
  Terraform's current state. No infrastructure changes were applied.
- The first foundation plan exposed a private input mismatch: OIDC provider
  creation was disabled while that root owned the existing provider. Its
  destruction guard blocked removal. Only the private ownership flag was
  corrected before the successful repeat.
- The private bundle contains source, setup inputs, backend locations, recovery
  instructions and a verification summary. Its checksum and private-file
  permissions were checked; credentials, session caches, provider caches and
  state/plan files are excluded.

This was a fresh-directory test on the operator workstation, using its existing
personal IAM session; a second physical machine and a new interactive login were
not tested. The operator confirmed that the bundle was saved in independently
accessible private storage, completing the infrastructure recovery handoff.
