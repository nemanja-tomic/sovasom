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
backup restoration. Independent recovery access remains an operator handoff item.
