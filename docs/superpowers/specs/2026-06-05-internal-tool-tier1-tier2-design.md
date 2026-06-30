# Internal Tool Upgrade — Tier 1 + Tier 2 Design

**Status:** Draft for approval (assumptions locked 2026-06-05)

**Goal:** Evolve the portfolio compliance pipeline into a multi team internal tool companies could pilot, without claiming production customers yet.

---

## Locked assumptions (developer confirmed)

| Decision | Choice |
|---|---|
| Authentication | Microsoft Entra ID (Azure AD) |
| Content ingestion | Hybrid: YouTube captions first, Azure Video Indexer fallback |
| Database | Azure Database for PostgreSQL |
| UI | Split: keep `index.html` for audits; add vanilla JS admin section |
| Notifications | Deferred (email/Slack not in this scope) |
| Tenancy | Multi team within one company (team scoped data) |

---

## Target architecture

```
                    ┌─────────────────────────────────────┐
                    │  Microsoft Entra ID (login + roles) │
                    └─────────────────┬───────────────────┘
                                      │
     index.html (audit UI) ───────────┼────────── admin.html (policy, teams, logs)
                                      │
                              FastAPI + RBAC middleware
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
    Azure PostgreSQL            LangGraph pipeline           Azure AI Search
    (teams, audits,             Indexer → Enrich → Auditor   (policy chunks +
     reviews, citations)       captions / VI fallback        version metadata)
          │                           │
          └───────────────────────────┴── Azure OpenAI (GPT-4o + embeddings)
```

### LangGraph workflow (new)

```
[START] → index_metadata (YouTube Data API)
        → enrich_content (captions OR Azure VI)
        → audit_content (RAG k=8 + citations)
        → persist_audit (Postgres)
        → [END]
```

---

## Tier 1 deliverables

| # | Deliverable | Acceptance |
|---|---|---|
| T1.1 | Microsoft Entra login | Unauthenticated users cannot call `/audit`; roles enforced |
| T1.2 | Team scoped RBAC | Admin / Reviewer / Read-only; audits filtered by `team_id` |
| T1.3 | Audit persistence | Every run stored with user, team, url, timestamps, policy version |
| T1.4 | Policy citations | Each violation includes source doc, chunk id, excerpt |
| T1.5 | Hybrid ingestion | Captions used when present; VI fallback when missing |
| T1.6 | Improved RAG | k increased from 3 to 8; optional semantic rerank if tier supports |
| T1.7 | Human review | Reviewer can override AI status with notes; `final_status` computed |
| T1.8 | Legal disclaimer | API + UI show decision support notice, not legal advice |
| T1.9 | Security baseline | Remove debug routes; restrict CORS; basic rate limiting |

---

## Tier 2 deliverables (notifications excluded)

| # | Deliverable | Acceptance |
|---|---|---|
| T2.1 | Policy refresh | Admin uploads/reindexes PDFs; audits record `policy_version` |
| T2.2 | Admin UI | Vanilla JS pages: audit log, policy status, team list (read only v1) |
| T2.3 | Export | Download audit as CSV or PDF |
| T2.4 | API keys per team | Service accounts for integrations (optional layer on Entra) |
| T2.5 | Frontend sync | `index.html` reflects actual pipeline (no stale Video Indexer copy) |
| T2.6 | Automated tests | pytest for auth, audit persistence, citation shape, ingestion fallback |

---

## Module seams (architecture deepening)

| Module | Interface | Adapters |
|---|---|---|
| **AuthProvider** | validate token, return user + team + role | EntraJWTAuthProvider |
| **AuditRepository** | save/load/list audits by team | PostgresAuditRepository |
| **IngestionPipeline** | given url → IngestionResult | MetadataAdapter, CaptionsAdapter, VideoIndexerAdapter |
| **PolicyStore** | search rules, get chunk by id, current version | AzureSearchPolicyStore |
| **ReviewService** | apply human override | PostgresReviewService |
| **AuditExporter** | audit id → CSV/PDF bytes | CsvExporter, PdfExporter |

---

## ADR candidates (to write during implementation)

1. **ADR-0001:** Microsoft Entra as sole auth provider for internal pilot
2. **ADR-0002:** Hybrid ingestion strategy (captions before Video Indexer)
3. **ADR-0003:** Azure Postgres for audit of record; Azure Search for policy vectors only
4. **ADR-0004:** Human review overrides AI but never deletes AI output (audit trail)

---

## Out of scope (explicit)

- Slack/email notifications
- Multi tenant SaaS billing
- Instagram / X platform support
- Full React admin rebuild
- Production accuracy SLA or eval harness (recommended follow up)

---

## Azure resources to provision

- App Registration (Entra ID) with redirect URIs for Container Apps URL
- Azure Database for PostgreSQL Flexible Server
- Existing: Container Apps, ACR, OpenAI, AI Search, Video Indexer (fallback)
- New env vars: `DATABASE_URL`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `ENTRA_AUTHORITY`, `ALLOWED_ORIGINS`

---

## Risks

| Risk | Mitigation |
|---|---|
| Entra setup complexity | Document app registration steps in README; local dev uses optional auth bypass flag (dev only) |
| VI fallback slow on free tier | Async job queue or "processing" status for VI path (Phase 1.5 if needed) |
| Azure Postgres cost | Burstable tier for pilot; connection pooling via SQLAlchemy |
| Stale UI during split build | Slice 12 dedicated to copy sync |

---

## Approval checklist

- [ ] Developer approves locked assumptions
- [ ] Developer approves vertical slice order (implementation plan)
- [ ] Developer confirms Azure Entra app registration access
- [ ] Developer confirms Azure Postgres provisioning access
