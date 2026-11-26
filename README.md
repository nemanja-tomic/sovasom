# Out & About

A private office home for coffee and bakery trips. This first slice supports runtime office setup, sign-in, persistent sessions and sign-out. Run announcement arrives in a later slice.

The modular FastAPI application lives in `backend/office` (accounts/access first), with SQLAlchemy and schema-only Alembic migrations. `frontend/src/design-system` owns Postcard Club tokens and accessible primitives; React 19/Vite builds the SPA. Caddy serves the build and the same-origin `/api` proxy. PostgreSQL has persistent storage and no published port. A worker will use the backend image when durable work is introduced.

## Onboarding

**Start with the [onboarding checklists](docs/onboarding-checklists.md).**
They guide new developers through personal setup and operators through shared
environment setup, linking to the detailed commands below and in the infrastructure
guides. Use the checklist to choose your path and track progress privately.

## Start locally

Start Docker Desktop (or Docker Engine with Compose on Linux), then from the repository root:

```sh
cp .env.example .env
chmod 600 .env
```

Edit `.env` and set `DATABASE_PASSWORD`, `INITIAL_EMAIL`, `INITIAL_DISPLAY_NAME` and `INITIAL_PASSWORD` (12–1024 characters). The example already supplies local HTTPS addresses and ports. Use single quotes around literal passwords, especially values containing `$`, `#`, spaces or URL punctuation; the backend constructs and escapes the database connection URL automatically. Do not use shell variable substitutions inside `.env` values. Existing exported environment variables override file values.

Run one preparation command:

```sh
uv run --frozen python scripts/setup.py
```

Open **https://localhost:8443**, accept Caddy's local development certificate (or trust its local CA), and sign in with your initial credentials. Node and Python run inside the application images; the host setup command needs uv and Docker. Install pinned development tools from `.tool-versions` / `.nvmrc` when working on source. Dependency versions and verification sources are recorded in [version sources](docs/dependency-versions.md).

Setup reads `.env` automatically, builds the images, starts PostgreSQL, applies migrations, and atomically creates the initial account, membership, administrator and menu-maintainer grants. After initialization succeeds, it removes the three `INITIAL_*` entries from `.env`, retains runtime configuration, and starts the application. Failed initialization keeps those entries for retry. Reruns leave existing credentials and permissions unchanged, even if new initial values are supplied. Bootstrap is not a recovery/reset command; explicit recovery is delivered by ticket 03.

Later, from the repository root:

```sh
docker compose stop
docker compose up -d
```

Data and Caddy keys persist across restarts and `docker compose down`. Keep volumes when stopping an office installation.

## Deploy with .env

All environments use the same `.env` format. For deployment set `SITE_ADDRESS` to the public hostname, `PUBLIC_ORIGIN` to its HTTPS origin, `HTTP_PORT=80` and `HTTPS_PORT=443`. Caddy manages public certificates when the hostname resolves to the host and inbound 80/443 are reachable. Keep the environment file private, outside source control, and retain a recoverable copy in your password manager. Environment values are accessible to the host's Docker administrators; the file is never included in images or frontend builds.

You can keep the deployment file outside the checkout:

```sh
uv run --frozen python scripts/setup.py --env-file /absolute/private/path/.env.production
docker compose --env-file /absolute/private/path/.env.production up -d
```

Setup restricts the selected file to mode `0600`. Compose explicitly passes the database password only to PostgreSQL and FastAPI. Bootstrap values are sent to the short-lived initializer on stdin and never stored in container configuration. Caddy receives only its hostname. PostgreSQL has no published port.

Existing installations using the old secret-file layout should copy their **existing database password** into `DATABASE_PASSWORD` in the environment file before recreating containers. Changing this value alone does not rotate an initialized PostgreSQL role's password. Reuse the same Compose project name and volumes to retain the database. Backups and controlled upgrades remain part of the later operational tickets.

AWS storage, Terraform bootstrap, GitHub OIDC, DNS and independent operator recovery
are documented in [the infrastructure runbook](infra/README.md). The retained
foundation and disposable application use separate states; application teardown
preserves backup storage and Terraform state history.

## Codex MCP setup

For the optional developer integrations, fill in `GITHUB_PAT_TOKEN` and `POSTMAN_API_KEY` in your private `.env`, then run:

```sh
uv run --frozen python scripts/onboard.py
```

This installs the two exports in one managed block in your `.zshrc`. Rerunning updates that block without duplicating it. Open a new terminal before launching Codex CLI. Application setup remains the separate command above. See [MCP setup](docs/mcp.md) for details.

## Verify changes

```sh
uv run --frozen ruff check
cd frontend
npm run format:check
npm run lint
npm run check-types
npm test
npm run build-storybook
npx playwright install chromium firefox webkit
npm run test:storybook
cd ..
uv run --frozen python scripts/verify-stack.py
```

The last command builds an independently named Compose stack, uses only synthetic credentials and a private temporary `.env` file, runs backend units/integration against new PostgreSQL databases, and runs UI flows in desktop Chromium/Firefox/WebKit and a 390px phone viewport. It verifies changed bootstrap reruns, cookie protection, authorization, CSRF denial, persisted login after reload, expired/revoked sessions, sign-out and persistence through database/application restart. Cleanup removes only that test project's containers and volumes. Direct session mutations in Playwright are gated by this isolated harness; production exposes no test endpoints. CI runs the same commands on Linux with frozen lockfiles.

For focused backend work, set `TEST_DATABASE_URL` to a disposable PostgreSQL server on which the test user can create databases, then run `uv run --frozen pytest backend/tests/test_auth.py`. Each test creates and drops a uniquely named database; it never resets the configured database. Run all backend tests with `uv run --frozen pytest`.

Visual baselines use the pinned Linux browser image to keep fonts/rendering consistent with CI:

```sh
docker run --rm --ipc=host -e STORYBOOK_STATIC=1 -e CI=1 \
  -v "$PWD:/work" -w /work/frontend \
  mcr.microsoft.com/playwright:v1.65.1-noble \
  node node_modules/@playwright/test/cli.js test --config playwright.components.config.ts
```

Use `--grep @visual --update-snapshots` only for deliberate visual changes, and inspect every changed image before committing. Component interaction tests also run locally with `npm run test:storybook`. Every production component has stories, including pending, rejected, offline and access-loss states. Pre-commit blocks on frontend Prettier/ESLint/project type checking and backend Ruff.

Existing-database migrations must use the verified off-host backup controller.
See [backup and recovery](docs/backup-recovery.md) for setup, manual retry,
freshness checks, the migration gate and isolated restore instructions.
