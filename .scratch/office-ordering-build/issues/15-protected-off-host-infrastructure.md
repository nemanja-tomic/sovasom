# 15: Establish protected off-host infrastructure

Status: ready-for-agent
Blocked by: None (can start immediately)
Parent: [Approved office-ordering specification](../../office-ordering/spec.md)

**What to build:** The operator can bootstrap protected AWS infrastructure, keep Terraform state recoverable off the mini and plan application teardown without losing retained storage.

- [ ] Create reproducible Terraform foundations for separate private S3 backup/state buckets in Frankfurt eu-central-1, encryption, public-access blocking, bucket/access policies, scoped IAM roles, OIDC trust and state version history. Use separate retained-foundation and disposable-application roots/states; application references retained infrastructure.
- [ ] Bootstrap using an authenticated operator session, establish native S3 locking with use_lockfile enabled, migrate initial state to the protected remote backend and document independent operator recovery. Keep Terraform state sensitive even when application secrets are excluded.
- [ ] Reuse/reference or deliberately import shared existing hosted zone and OIDC provider. Define the application DNS record using actual setup inputs. Scope GitHub trust to the real repository and intended trusted branch/environment subject; separate narrow infrastructure and backup workflow roles.
- [x] Normal application destroy retains foundation buckets and contents. Retained buckets use prevent_destroy enabled and force_destroy disabled; foundation destroy planning fails with guards present. Explain configuration-removal/direct-AWS deletion limits and explicit full retirement. Backup expiry continues after app teardown; preserve state history/current state independently.
- [ ] Keep secret payloads out of Terraform inputs/state and avoid ownership overlap with Compose/host automation or Caddy TLS keys. Resolve actual identifiers, repository access and provider pins as setup configuration; do not fabricate provisioned resources or credentials.
- [ ] Run format/validation and inspect plans, remote locking/version recovery, scoped role/bucket permissions and separate state ownership. Use disposable resources for live smoke tests, verify retained resources on application teardown and guard failure on foundation destroy plans, and record actual evidence. Never perform a production destructive verification.

## Implementation and verification context

Use the approved spec and its resolved decision provenance as authority. No product discovery is required. Use existing shared design-system and application test seams where available; add only the pieces this slice needs. All application behavior is server-authorized and PostgreSQL-backed; applicable tests use synthetic isolated data and never notify colleagues. Add component stories and focused units with behavior changes, and run the relevant full-stack Playwright workflows before completion. Record checks that cannot run. Operational slices record equivalent plan/smoke/recovery evidence on isolated resources. Do not alter the parent spec or resolved decision tickets as part of claiming/completing this ticket.


## Comments

### Implementation and manual apply handoff

Implemented separate retained-foundation/application Terraform roots, private encrypted/versioned storage, retained bucket guards, scoped OIDC roles, native state locking, DNS management, CI checks and recovery/onboarding documentation. Public examples contain placeholders; actual configuration and deployment verification belong in private local inputs and operator notes.

Automated validation includes Terraform schema checks and synthetic plans, local-state destroy protection, onboarding fixtures, public-example enforcement, linting and commit checks. The operator requested manual infrastructure application. Keep this ticket open until isolated live provisioning/recovery evidence is complete; do not apply infrastructure without a new operator request.

### Operator confirmation — 26 November 2026

The operator confirmed the following acceptance progress; these are operator
reports rather than new agent-executed checks. Deployment identifiers and detailed
evidence remain in private operator records.

- [x] Foundation state migrated to S3, followed by a no-change plan.
- [x] Saved DNS plan applied.
- [x] GitHub repository variables configured and the infrastructure plan workflow
  succeeded through OIDC.
- [x] Exercise application teardown on isolated disposable resources and verify
  retained storage/contents/state history survive; verify foundation destroy-plan
  protection there as well.
- [ ] Confirm independent recovery access and retain the operational evidence
  privately.

Live lock contention, state-version recovery and least-privilege permission checks
remain unconfirmed by this update. Their synthetic equivalents already pass.
The ticket remains open until the outstanding operational acceptance is evidenced.

### Agent-executed isolated teardown verification — 26 November 2026

Verified against a newly provisioned disposable foundation and temporary DNS
record, with separate local inputs and S3 state. Existing deployment DNS and
state object versions were compared before and after and remained unchanged.

- Application destroy planned and deleted only the temporary DNS record.
- Both retained buckets, all prior state versions, two synthetic canary object
  versions, lifecycle configuration and IAM roles survived application teardown.
  Canary versions were retrieved and compared byte-for-byte.
- An earlier application state version was retrieved after teardown and verified
  to have the same lineage, an earlier serial and the former DNS resource.
- A pending test apply held a native S3 lock; a competing Terraform plan was
  rejected. The pending apply was cancelled without applying its proposed change,
  and lock release was verified.
- S3 public-access blocks, encryption, ownership and versioning were checked
  against the actual disposable buckets. IAM principal-policy simulations
  verified the selected allowed/denied state/archive actions. These simulations
  are not a claim of real assumed-role service-call coverage.
- Foundation destroy planning rejected deletion of both protected buckets.
- After evidence capture, only the disposable foundation was explicitly retired;
  test buckets, versions and IAM roles were removed and DNS absence was verified.

Detailed command logs, inventories and reports remain under the ignored
`.scratch/private/` directory. Public records contain no deployment identifiers.
Timed lifecycle expiry and backup-format restoration were not tested here.
Independent recovery access/handoff remains for operator confirmation; the ticket
is not marked done by this verification.
