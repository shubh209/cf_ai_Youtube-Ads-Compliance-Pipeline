# Setup and Testing Guide (Tier 1 + Tier 2)

Complete this checklist after pulling the internal tool upgrade branch.

## 1. Azure PostgreSQL

```bash
# Create flexible server (example)
az postgres flexible-server create \
  --resource-group LLM-yt \
  --name brand-guardian-db \
  --location eastus \
  --admin-user bgadmin \
  --admin-password '<strong-password>' \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --version 16 \
  --storage-size 32
```

Set firewall to allow Azure services and your IP. Add to `.env`:

```env
DATABASE_URL=postgresql+psycopg2://bgadmin:<password>@brand-guardian-db.postgres.database.azure.com:5432/postgres?sslmode=require
```

Run migrations:

```bash
.venv/bin/python -m alembic upgrade head
```

Index policy PDFs (creates first PolicyVersion row):

```bash
.venv/bin/python backend/scripts/index_documents.py
```

## 2. Microsoft Entra ID

1. App registrations → New registration → single tenant
2. Expose an API → Application ID URI → add scope `access_as_user`
3. App roles: `Admin`, `Reviewer`, `ReadOnly`
4. Assign users/groups to roles under Enterprise applications
5. Add redirect URI for SPA if using MSAL later

`.env`:

```env
ENTRA_TENANT_ID=<tenant-id>
ENTRA_CLIENT_ID=<app-client-id>
ENTRA_API_AUDIENCE=api://<app-id-uri>
AUTH_DISABLED=false
ALLOWED_ORIGINS=http://localhost:8000,https://<your-container-app-url>
```

Local dev without Entra:

```env
AUTH_DISABLED=true
```

## 3. Run locally

```bash
cp env.example .env
# fill Azure OpenAI, Search, YouTube, DATABASE_URL
.venv/bin/python -m uvicorn backend.src.api.server:app --reload --host 0.0.0.0 --port 8000
```

Open:
- Audit UI: http://localhost:8000/
- Admin UI: http://localhost:8000/admin
- Swagger: http://localhost:8000/docs

## 4. Smoke tests

```bash
# Health
curl http://localhost:8000/health

# Auth (with AUTH_DISABLED=true)
curl http://localhost:8000/auth/me

# Audit (requires Azure OpenAI + Search + YouTube key)
curl -X POST http://localhost:8000/audit \
  -H "Content-Type: application/json" \
  -d '{"video_url":"https://youtu.be/dT7S75eYhcQ"}'

# List audits (after Postgres connected)
curl http://localhost:8000/audits

# Admin reindex (admin role required)
curl -X POST http://localhost:8000/admin/policies/reindex \
  -H "Authorization: Bearer <token>"
```

## 5. Automated tests

```bash
AUTH_DISABLED=true PYTHONPATH=. .venv/bin/pytest tests/ -v
```

## 6. New API surface

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/audit` | Run audit (auth required unless AUTH_DISABLED) |
| GET | `/audits` | Team audit history |
| GET | `/audits/{id}` | Audit detail + citations |
| POST | `/audits/{id}/review` | Human override |
| GET | `/audits/{id}/export?format=csv\|pdf` | Download report |
| GET | `/admin/policies/versions` | Policy versions |
| POST | `/admin/policies/reindex` | Reindex PDFs |
| POST | `/admin/api-keys` | Create team API key |
| GET | `/admin` | Admin HTML UI |

## 7. Optional: Video Indexer fallback

If captions are missing, set VI env vars from `env.example`. Fallback runs only when configured.

## 8. Deploy

Push to `main` — CI runs pytest then deploys to Azure Container Apps. Add new env vars to Container App configuration in Azure portal or GitHub secrets workflow.
