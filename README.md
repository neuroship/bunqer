<p align="center">
  <h1 align="center">bunqer</h1>
  <p align="center">
    Self-hosted accounting and financial management for bunq bank users.
    <br />
    Sync transactions, categorize expenses, generate invoices — all from your own infrastructure.
  </p>
</p>

---

## About

bunqer connects to your [bunq](https://www.bunq.com) bank account and gives you a clean, self-hosted interface to manage your finances. It's built for freelancers, small businesses, and anyone who wants full control over their financial data without relying on third-party SaaS platforms.

### Features

- **Bank sync** — connect your bunq account and automatically pull transactions in real-time via SSE
- **Transaction management** — search, filter, sort, and tag transactions with inline editing
- **Auto-categorization** — define rule-based conditions to automatically categorize incoming transactions
- **Invoicing** — create invoices, manage clients, generate PDFs, and track payment status
- **Analytics** — visualize your financial data with interactive charts
- **Passkey authentication** — passwordless login via WebAuthn/FIDO2 alongside traditional auth
- **Company settings** — upload your logo and customize invoice details
- **Rule import/export** — back up and share categorization rules as JSON
- **Dark theme** — designed for comfortable extended use

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic |
| Frontend | Svelte 5, Tailwind CSS, FlyonUI, Chart.js |
| Database | PostgreSQL 16 |
| Auth | JWT + WebAuthn passkeys |
| Bank API | bunq SDK |
| Package Mgmt | uv (Python), npm (JS) |
| Task Runner | go-task |
| Infrastructure | Docker Compose |

## Prerequisites

- [Python 3.13+](https://www.python.org/)
- [Node.js 18+](https://nodejs.org/)
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [go-task](https://taskfile.dev/) — task runner
- [direnv](https://direnv.net/) — automatic environment variable loading from `.envrc`
- [Docker](https://www.docker.com/) and Docker Compose
- A [bunq](https://www.bunq.com) account with an API key

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/neuroship/bunqer.git
cd bunqer

# 2. Copy environment config
cp .env.example .env

# 3. Generate a password hash and add it to .env
task auth:hash-password

# 4. Add your bunq API key to .env
#    Get it from the bunq app: Profile → Security → API keys

# 5. Install dependencies
task install

# 6. Start PostgreSQL
task infra:up

# 7. Run the development servers
task dev:api   # terminal 1 — API on :8000
task dev:ui    # terminal 2 — UI on :5173
```

Open [http://localhost:5173](http://localhost:5173) and log in with the credentials you configured.

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/vibe_accountant

# API Server
API_HOST=0.0.0.0
API_PORT=8000

# Bunq Integration
BUNQ_API_KEY=your-bunq-api-key-here
BUNQ_ENVIRONMENT=PRODUCTION

# Frontend
VITE_API_URL=http://localhost:8000

# Authentication
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=your-bcrypt-hash-here

# WebAuthn / Passkeys (optional, defaults work for localhost)
# WEBAUTHN_RP_ID=yourdomain.com
# WEBAUTHN_ORIGIN=https://yourdomain.com
```

## Development

### Available Tasks

```bash
task                    # List all available tasks
task install            # Install all dependencies
task dev                # Run API + UI concurrently
task dev:api            # Run API server with hot reload
task dev:ui             # Run UI dev server
task build              # Build UI for production
task lint               # Run linters
task infra:up           # Start PostgreSQL via Docker
task auth:hash-password # Generate a bcrypt password hash
```

### Database

```bash
task db:migrate                  # Run pending migrations
task db:rollback                 # Undo last migration
task db:revision -- "add users"  # Create new migration
task db:reset                    # Drop and re-migrate
```

## Project Structure

```
bunqer/
├── api/                        # FastAPI backend
│   ├── src/vibe_accountant/
│   │   ├── main.py             # App entry, middleware, routes
│   │   ├── config.py           # Settings from environment
│   │   ├── auth.py             # JWT + password auth
│   │   ├── bunq_client.py      # bunq API integration
│   │   ├── models/             # SQLAlchemy models + Pydantic schemas
│   │   ├── routes/             # API endpoints
│   │   └── services/           # Business logic
│   ├── alembic/                # Database migrations
│   └── pyproject.toml
├── ui/                         # Svelte 5 frontend
│   ├── src/
│   │   ├── App.svelte          # Root component
│   │   └── lib/
│   │       ├── api.js          # API client
│   │       ├── components/     # Reusable UI components
│   │       └── pages/          # Route pages
│   └── package.json
├── docker-compose.yml          # PostgreSQL service
├── Taskfile.yml                # Task automation
├── .env.example                # Environment template
└── LICENSE
```

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a pull request.

In short:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run linters (`task lint`)
5. Commit with a clear message
6. Open a pull request against `main`

## Security

If you discover a security vulnerability, please report it responsibly. See [SECURITY.md](SECURITY.md) for details.

### Deployment Hardening

Before running bunqer in production, review the following checklist:

**Secrets & credentials**

- Set `JWT_SECRET_KEY` explicitly in `.env` — do not rely on the auto-generated default, as it changes on every restart and invalidates all active sessions.
- Use a strong, unique `AUTH_PASSWORD_HASH`. Generate it with `task auth:hash-password`.
- Never commit `.env` to version control. The `.gitignore` already excludes it.
- Change the default PostgreSQL password in `docker-compose.yml` (default is `postgres`).

**bunq configuration files**

- `BUNQ_CONF_DIR` stores serialized API contexts that grant full access to your bunq account. Protect this directory:
  ```bash
  chmod 700 "$BUNQ_CONF_DIR"
  ```
- Store `BUNQ_CONF_DIR` outside the application directory and any web-accessible paths.
- Back up bunq conf files securely — they are equivalent to API keys.

**Network & transport**

- Always terminate TLS before the application (e.g., via a reverse proxy like nginx or Caddy).
- Restrict `FRONTEND_URL` to the exact origin you serve from — CORS is configured from this value.
- Do not expose the API port (8000) directly to the internet; place it behind a reverse proxy.

**Rate limiting**

- Add rate limiting on `/auth/login` and `/auth/hash-password` to prevent brute-force attacks. This can be done at the reverse proxy level (e.g., nginx `limit_req`) or with a FastAPI middleware.

**Security headers**

- Configure your reverse proxy to add the following response headers:
  ```
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Strict-Transport-Security: max-age=63072000; includeSubDomains
  Content-Security-Policy: default-src 'self'
  Referrer-Policy: strict-origin-when-cross-origin
  ```

**Logging**

- Review log output to ensure no sensitive data (API keys, tokens, passwords) appears in logs.
- In production, set log level to `WARNING` or `ERROR` to reduce information exposure.
- Route logs to a secure, access-controlled logging system.

**Database**

- Use a dedicated PostgreSQL user with limited privileges instead of the `postgres` superuser.
- Enable SSL for database connections in production.
- Run regular backups and test restores.

**Docker**

- Run containers as a non-root user.
- Pin image versions in `docker-compose.yml` to avoid unexpected updates.
- Scan images for vulnerabilities with `docker scout` or `trivy`.

## License

bunqer is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE) with an additional attribution requirement.

**You are free to:**
- Use bunqer for personal and commercial purposes
- Modify and distribute the source code

**Under the following conditions:**
- Any derivative work or product built on bunqer must also be open-sourced under the same license
- You must give appropriate credit and prominently mention **bunqer** in any derivative work

See the [LICENSE](LICENSE) file for the full terms.

## Disclaimer

This software is provided "as is", without warranty of any kind, express or implied. bunqer connects to real bank accounts and handles financial data. By using this software, you accept full responsibility for its configuration, deployment, and operation. The authors and contributors are not liable for any financial loss, data breach, or other damages arising from the use of this software. Use at your own risk.

---

<p align="center">
  Built by Neuroship.
</p>
