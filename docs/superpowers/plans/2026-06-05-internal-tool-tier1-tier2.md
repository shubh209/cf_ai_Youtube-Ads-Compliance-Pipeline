# Internal Tool Tier 1 + Tier 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a multi team internal compliance tool with Entra auth, Postgres audit history, hybrid ingestion, policy citations, human review, admin UI, exports, and tests.

**Architecture:** Extend FastAPI + LangGraph with three ingestion/audit nodes, Postgres as audit of record, Entra JWT middleware, vanilla JS split UI. See `docs/superpowers/specs/2026-06-05-internal-tool-tier1-tier2-design.md`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, LangGraph, Azure OpenAI, Azure AI Search, Azure Video Indexer, Azure Postgres, Microsoft Entra ID, vanilla JS/HTML.

**Locked assumptions:** Entra auth, hybrid captions/VI, Azure Postgres, split UI, defer notifications, multi team tenancy.

---

## File structure (new / modified)

```
backend/src/
  auth/
    entra.py              # JWT validation, role + team extraction
    dependencies.py       # FastAPI Depends(get_current_user)
    models.py             # UserContext, Role enum
  db/
    session.py            # SQLAlchemy engine + session
    models.py             # Team, User, Audit, Violation, Review, PolicyVersion
    repository.py         # AuditRepository
  services/
    video_indexer.py      # extend: captions + VI fallback
    ingestion.py          # HybridIngestion orchestrator
    policy_store.py       # search + get_chunk + current_version
    review.py             # human override logic
    export.py             # CSV + PDF exporters
  graph/
    nodes.py              # split enrich node; citations in auditor
    workflow.py           # 3-node graph + persist hook
    state.py              # add ingestion_source, policy_version, citations
  api/
    server.py             # auth middleware, new routes
    routes/
      audits.py
      reviews.py
      admin.py
      export.py
  middleware/
    rate_limit.py
admin.html                  # team audit log, policy status
index.html                  # sync copy + disclaimer + login redirect
tests/
  test_auth.py
  test_audit_persistence.py
  test_citations.py
  test_ingestion_hybrid.py
alembic/                    # migrations
CONTEXT.md                  # done
docs/adr/
  0001-entra-auth.md
  0002-hybrid-ingestion.md
  0003-postgres-audit-of-record.md
  0004-human-review-trail.md
```

---

## Vertical slices (execution order)

Each slice is demoable on its own. **Do not start Slice N until blockers merge.**

---

### Slice 1: Foundation + Postgres schema

**Blocked by:** None

**Files:**
- Create: `backend/src/db/session.py`, `backend/src/db/models.py`, `alembic.ini`, `alembic/versions/001_initial.py`
- Modify: `pyproject.toml` (activate sqlalchemy, psycopg2, alembic)
- Modify: `env.example` (`DATABASE_URL`)
- Create: `docs/adr/0003-postgres-audit-of-record.md`

**Tasks:**

- [ ] **Step 1:** Add Alembic and SQLAlchemy dependencies; run `alembic init`
- [ ] **Step 2:** Define models: `Team`, `User` (entra_oid, team_id, role), `PolicyVersion`, `Audit`, `AuditViolation`, `ReviewDecision`
- [ ] **Step 3:** Migration creates tables with indexes on `(team_id, created_at)` for audits
- [ ] **Step 4:** Add `get_db()` session dependency for FastAPI
- [ ] **Step 5:** Document Azure Postgres provisioning in README (burstable tier, firewall for Container Apps)

**Acceptance:**
- [ ] `alembic upgrade head` succeeds against Azure Postgres
- [ ] Tables exist; no app routes required yet

---

### Slice 2: Security baseline

**Blocked by:** None (parallel with Slice 1)

**Files:**
- Modify: `backend/src/api/server.py` (remove `/debug/env`, `/debug/vi-test`)
- Create: `backend/src/middleware/rate_limit.py`
- Modify: `env.example` (`ALLOWED_ORIGINS`)

**Tasks:**

- [ ] **Step 1:** Delete debug endpoints
- [ ] **Step 2:** Replace CORS `allow_origins=["*"]` with `ALLOWED_ORIGINS` env list
- [ ] **Step 3:** Add simple in memory rate limit per IP on `POST /audit` (e.g. 30/min pilot)

**Acceptance:**
- [ ] Debug routes return 404
- [ ] CORS rejects unknown origins

---

### Slice 3: Microsoft Entra authentication + RBAC

**Blocked by:** Slice 1 (User model)

**Files:**
- Create: `backend/src/auth/entra.py`, `backend/src/auth/dependencies.py`, `backend/src/auth/models.py`
- Create: `docs/adr/0001-entra-auth.md`
- Modify: `backend/src/api/server.py`
- Modify: `env.example` (Entra vars)
- Modify: `README.md` (app registration guide)

**Tasks:**

- [ ] **Step 1:** Register Entra app (SPA + API exposed scope); document tenant, client id, authority
- [ ] **Step 2:** Implement JWT validation (issuer, audience, expiry) via `python-jose` or `PyJWT` + JWKS
- [ ] **Step 3:** Map Entra groups or app roles → `admin` | `reviewer` | `read_only`
- [ ] **Step 4:** On first login, upsert `User` row linked to `Team` (team from group claim or default team)
- [ ] **Step 5:** Add `Depends(get_current_user)`; return 401/403 when missing or wrong role
- [ ] **Step 6:** Dev only flag `AUTH_DISABLED=true` for local pytest (never in production)

**Acceptance:**
- [ ] Unauthenticated `POST /audit` → 401
- [ ] Read only user cannot submit review override
- [ ] Admin can access admin routes

---

### Slice 4: Audit persistence

**Blocked by:** Slice 1, Slice 3

**Files:**
- Create: `backend/src/db/repository.py`
- Modify: `backend/src/graph/workflow.py` (post audit hook or node)
- Modify: `backend/src/api/server.py` or `routes/audits.py`
- Create: `tests/test_audit_persistence.py`

**Tasks:**

- [ ] **Step 1:** After LangGraph completes, persist `Audit` row: url, team_id, user_id, ai_status, raw json, policy_version
- [ ] **Step 2:** Persist child `AuditViolation` rows
- [ ] **Step 3:** Add `GET /audits` (team scoped, paginated) and `GET /audits/{id}`
- [ ] **Step 4:** Write pytest: authenticated audit creates DB row with correct team_id

**Acceptance:**
- [ ] Every successful audit appears in Postgres
- [ ] Team A cannot read Team B audits

---

### Slice 5: Policy citations in RAG output

**Blocked by:** Slice 1 (PolicyVersion)

**Files:**
- Modify: `backend/scripts/index_documents.py` (store chunk uuid, source, page in metadata)
- Create: `backend/src/services/policy_store.py`
- Modify: `backend/src/graph/nodes.py` (auditor prompt + response schema)
- Modify: `backend/src/graph/state.py`
- Create: `tests/test_citations.py`

**Tasks:**

- [ ] **Step 1:** Reindex PDFs with stable `chunk_id` in Azure Search metadata
- [ ] **Step 2:** Create `PolicyVersion` row on each index run (version string, indexed_at, chunk_count)
- [ ] **Step 3:** Extend violation schema: `citation_source`, `citation_excerpt`, `chunk_id`
- [ ] **Step 4:** LLM prompt requires citing chunk ids from retrieved context
- [ ] **Step 5:** pytest asserts every violation includes non empty citation fields

**Acceptance:**
- [ ] API response violations include policy excerpt reviewers can read

---

### Slice 6: Improved RAG (k=8)

**Blocked by:** Slice 5

**Files:**
- Modify: `backend/src/graph/nodes.py` (`similarity_search` k=8)
- Modify: `env.example` (`RAG_TOP_K=8`)

**Tasks:**

- [ ] **Step 1:** Change k from 3 to 8 via env default
- [ ] **Step 2:** If Azure Search semantic ranker available on index, enable in query
- [ ] **Step 3:** Log retrieved chunk ids for debugging in App Insights

**Acceptance:**
- [ ] Auditor retrieves 8 chunks unless env overrides
- [ ] Document TODO for dedicated reranker model if semantic ranker unavailable

---

### Slice 7: Hybrid ingestion (captions + VI fallback)

**Blocked by:** None for captions; VI fallback requires Azure VI env vars

**Files:**
- Create: `backend/src/services/ingestion.py`
- Modify: `backend/src/services/video_indexer.py` (add captions fetch via YouTube timedtext or Data API)
- Modify: `backend/src/graph/nodes.py` (new `enrich_content_node`)
- Modify: `backend/src/graph/workflow.py` (3 node graph)
- Create: `docs/adr/0002-hybrid-ingestion.md`
- Create: `tests/test_ingestion_hybrid.py`

**Tasks:**

- [ ] **Step 1:** Add `CaptionsAdapter`: fetch captions when available; set `ingestion_source=captions`
- [ ] **Step 2:** If no captions, call existing `VideoIndexerService` path; set `ingestion_source=video_indexer`
- [ ] **Step 3:** Merge metadata + transcript + ocr_text into state for auditor
- [ ] **Step 4:** Store `ingestion_source` on Audit row
- [ ] **Step 5:** pytest mocks: captions path vs fallback path selected correctly

**Acceptance:**
- [ ] Video with captions never calls VI
- [ ] Video without captions still produces audit via VI (or graceful fail with clear error)

---

### Slice 8: Human review workflow

**Blocked by:** Slice 4

**Files:**
- Create: `backend/src/services/review.py`
- Create: `backend/src/api/routes/reviews.py`
- Create: `docs/adr/0004-human-review-trail.md`
- Modify: `backend/src/db/models.py` if needed

**Tasks:**

- [ ] **Step 1:** Add `POST /audits/{id}/review` body: `{ decision: pass|fail, notes }`
- [ ] **Step 2:** Persist `ReviewDecision`; set `final_status`; never overwrite `ai_status`
- [ ] **Step 3:** Reviewer and Admin roles only
- [ ] **Step 4:** `GET /audits/{id}` returns ai_status, final_status, review history

**Acceptance:**
- [ ] Override visible in API and admin UI
- [ ] Read only users cannot post reviews

---

### Slice 9: Legal disclaimer + confidence

**Blocked by:** Slice 4

**Files:**
- Modify: `backend/src/api/server.py` (response wrapper)
- Modify: `index.html`

**Tasks:**

- [ ] **Step 1:** Add `disclaimer` field to all audit responses (static legal text)
- [ ] **Step 2:** Add optional `confidence` per violation if LLM returns it; else omit
- [ ] **Step 3:** Show disclaimer banner on audit UI

**Acceptance:**
- [ ] Every audit response includes disclaimer string

---

### Slice 10: Policy refresh (admin API)

**Blocked by:** Slice 5

**Files:**
- Create: `backend/src/api/routes/admin.py`
- Modify: `backend/scripts/index_documents.py` (callable function + version bump)

**Tasks:**

- [ ] **Step 1:** Admin only `POST /admin/policies/reindex` triggers index_documents logic
- [ ] **Step 2:** Accept uploaded PDF to `backend/data/` (or blob later); validate file type
- [ ] **Step 3:** Return new `policy_version` id and chunk count
- [ ] **Step 4:** `GET /admin/policies/versions` lists versions

**Acceptance:**
- [ ] Admin can reindex without SSH
- [ ] New audits reference latest policy version id

---

### Slice 11: Admin UI (vanilla JS)

**Blocked by:** Slice 4, Slice 8, Slice 10, Slice 3

**Files:**
- Create: `admin.html`
- Modify: `backend/src/api/server.py` (serve admin.html at `/admin`)
- Create: `backend/static/admin.js` (optional)

**Tasks:**

- [ ] **Step 1:** Entra login flow on admin page (MSAL.js browser auth)
- [ ] **Step 2:** Audit log table: url, ai_status, final_status, reviewer, date (team scoped)
- [ ] **Step 3:** Policy versions panel with reindex button (admin only)
- [ ] **Step 4:** Review modal: override AI decision with notes

**Acceptance:**
- [ ] Admin can browse team audits and submit review without curl

---

### Slice 12: Export CSV/PDF

**Blocked by:** Slice 4

**Files:**
- Create: `backend/src/services/export.py`
- Create: `backend/src/api/routes/export.py`

**Tasks:**

- [ ] **Step 1:** `GET /audits/{id}/export?format=csv` returns violations + citations + statuses
- [ ] **Step 2:** `format=pdf` uses reportlab or weasyprint for printable summary
- [ ] **Step 3:** Add Download button on index.html and admin.html

**Acceptance:**
- [ ] CSV opens in Excel with readable columns
- [ ] PDF includes disclaimer footer

---

### Slice 13: Frontend sync + audit UI auth

**Blocked by:** Slice 3, Slice 7

**Files:**
- Modify: `index.html` (remove stale VI copy; add MSAL login; show ingestion_source)

**Tasks:**

- [ ] **Step 1:** Replace hero/arch copy with YouTube Data API + captions/VI hybrid + RAG
- [ ] **Step 2:** Update pipeline animation steps to match real phases
- [ ] **Step 3:** Require login before audit submit
- [ ] **Step 4:** Display citations per violation in results panel

**Acceptance:**
- [ ] UI text matches backend behavior

---

### Slice 14: Automated test suite + CI

**Blocked by:** Slices 3–8 minimum

**Files:**
- Create: `tests/conftest.py` (test db, auth bypass fixture)
- Create: remaining test modules
- Modify: `.github/workflows/deploy.yml` (add pytest job before deploy)

**Tasks:**

- [ ] **Step 1:** pytest covers auth, persistence, citations, hybrid ingestion, review
- [ ] **Step 2:** CI runs tests on PR and main
- [ ] **Step 3:** Fail deploy if tests fail

**Acceptance:**
- [ ] `pytest` green locally and in GitHub Actions

---

### Slice 15: Team API keys (optional Tier 2)

**Blocked by:** Slice 3, Slice 4

**Files:**
- Create: `backend/src/db/models.py` addition `TeamApiKey`
- Modify: `backend/src/auth/dependencies.py` (accept API key header OR JWT)

**Tasks:**

- [ ] **Step 1:** Admin generates revocable key per team
- [ ] **Step 2:** Keys map to team + reviewer scope for automation integrations

**Acceptance:**
- [ ] CI/CD partner can call `/audit` with `X-API-Key` without browser login

---

## Suggested sprint grouping

| Sprint | Slices | Outcome |
|---|---|---|
| Sprint 1 | 1, 2, 3 | Secure app with login |
| Sprint 2 | 4, 5, 6, 9 | Trustworthy audits with citations |
| Sprint 3 | 7, 8, 13 | Full content + human review + honest UI |
| Sprint 4 | 10, 11, 12, 14, 15 | Admin ops, exports, tests, API keys |

---

## HITL checkpoints (require you)

1. **Entra app registration** — tenant admin or your Azure account
2. **Azure Postgres provisioning** — pick SKU, firewall rules
3. **Entra group → role mapping** — which group is Admin vs Reviewer
4. **Legal disclaimer text** — you or advisor must approve wording
5. **VI fallback acceptable latency** — may need async UX if >60s

---

## Self review (plan vs spec)

| Spec requirement | Slice |
|---|---|
| T1.1 Entra login | 3 |
| T1.2 Team RBAC | 3, 4 |
| T1.3 Audit persistence | 4 |
| T1.4 Citations | 5 |
| T1.5 Hybrid ingestion | 7 |
| T1.6 RAG k=8 | 6 |
| T1.7 Human review | 8 |
| T1.8 Disclaimer | 9 |
| T1.9 Security | 2 |
| T2.1 Policy refresh | 10 |
| T2.2 Admin UI | 11 |
| T2.3 Export | 12 |
| T2.4 API keys | 15 |
| T2.5 UI sync | 13 |
| T2.6 Tests | 14 |

**Gaps:** None identified. Notifications explicitly deferred.

---

## Execution handoff

**Plan saved to:** `docs/superpowers/plans/2026-06-05-internal-tool-tier1-tier2.md`

**Two execution options:**

1. **Subagent driven (recommended)** — one slice per agent session, review between slices
2. **Inline execution** — implement Sprint 1 in this session after you approve

**Which approach do you want after you approve this plan?**
