# 17: Deploy and recover the application on the Mac mini

Status: ready-for-agent
Blocked by: [16: Back up and restore application data](16-backup-and-restore.md)
Parent: [Approved office-ordering specification](../../office-ordering/spec.md)

**What to build:** Passing application changes reach the existing Intel macOS Mac mini through a repeatable secure release, with public HTTPS and verified operational recovery.

- [ ] GitHub-hosted Linux jobs run the current application’s unit/integration/Playwright checks and build immutable linux/amd64 images for GHCR. Serialize host-key-verified SSH deployments from passing main with a dedicated deployment identity. Pull/start pinned releases, check readiness/health and preserve recoverable previous images.
- [ ] Automate host/Compose configuration on existing macOS/Docker Desktop; verify supported hardware/OS/runtime, licensing applicability, resources, Compose and SSH Docker context. Caddy serves the built React SPA and same-origin API with persisted automatic Let’s Encrypt TLS. Verify existing DNS/static-IP mapping, inbound 80/443 and outbound push connectivity; keep PostgreSQL private and persistent.
- [ ] Gate existing-database migrations on ticket-16 backup/upload, run runtime bootstrap only as initial setup, and verify unchanged reruns. Test recoverable application rollback with explicit database compatibility rather than claiming image rollback reverses a migration. A first empty installation remains supported.
- [ ] Generate setup secrets on a trusted operator machine, retain originals in the password manager, and hold deployment copies in supported GitHub environment or repository secrets. Deliver minimum secrets through verified SSH into restricted files outside the checkout, mount only needed Compose secrets and explicitly configure backend file reads. Verify actual Desktop mount permissions; no payloads in source, image layers/build args, frontend, Terraform or logs.
- [ ] Use job-scoped GHCR credentials and verify private pulls, expiry and cleanup on success/failure, including Docker credential-helper/Keychain behavior. Do not assume temporary Docker config alone removes saved authentication. Use OIDC AWS roles; ordinary PR/test jobs receive synthetic values only.
- [ ] Verify coordinated secret rotation, including actual PostgreSQL role-password changes; remove one-time bootstrap inputs from runtime/GitHub after success. Keep backup recovery access/old identities independently available. Caddy retains local TLS keys and can reissue on replacement.
- [ ] Accept brief maintenance outages and manual cold-boot unlock/login, then automatically recover Docker Desktop/application services. Perform and record that sequence plus health, persistence, secret mounts, migration/initializer reruns, registry cleanup and existing browser workflows on an isolated deployment. Live account/domain/hardware details are setup inputs; record unperformed checks rather than claim success.

## Implementation and verification context

Use the approved spec and its resolved decision provenance as authority. No product discovery is required. Use existing shared design-system and application test seams where available; add only the pieces this slice needs. All application behavior is server-authorized and PostgreSQL-backed; applicable tests use synthetic isolated data and never notify colleagues. Add component stories and focused units with behavior changes, and run the relevant full-stack Playwright workflows before completion. Record checks that cannot run. Operational slices record equivalent plan/smoke/recovery evidence on isolated resources. Do not alter the parent spec or resolved decision tickets as part of claiming/completing this ticket.

## Comments

### Implementation — 26 November 2026

Implemented Linux test/E2E-gated digest image publication, serialized verified-SSH
release and host configuration workflows, private persistent production Compose,
explicit database secret-file reads, backup/upload-gated migrations, first-only
bootstrap, health activation, retained prior release/schema records, conservative
rollback refusal, real PostgreSQL role-password rotation and post-login recovery
that respects failed maintenance. See `docs/mac-mini-deployment.md` for setup,
recovery, secret custody and the private operational acceptance checklist.

Ticket 16 remains pending live acceptance; its backup gate is preserved. This
issue remains open for real Intel mini support/licensing, SSH/GHCR/Keychain, DNS/
public TLS/network, real S3 restore, password rotation and cold-boot evidence.
The current app has no worker or later ordering workflows; those deployment
acceptance checks must follow their implementations. No live outcomes are claimed.

Local verification passed: full backend suite (67 tests against disposable
PostgreSQL), Ruff, frontend formatting/lint/types, workflow YAML parsing, production
Compose configuration, backend/web image builds, real secret-file mounts,
initializer reruns and SPA/API readiness. Playwright MCP exercised synthetic
sign-in, persisted session after database/backend restart and sign-out. The local
certificate issuer was bypassed only in that isolated browser context; public TLS
is unverified. The full multi-browser CI suite is wired as a release prerequisite
and was not run locally. Standards and Spec reviews have no remaining blocking
findings after fixes and regression coverage. Private logs remain ignored.
