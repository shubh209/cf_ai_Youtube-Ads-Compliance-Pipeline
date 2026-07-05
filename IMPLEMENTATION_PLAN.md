# Brand Guardian AI — Implementation Plan

> Execute phases in order. Each phase is independently shippable and testable before the next starts.
> Skills active: **ponytail** (full) · **production-audit**

## How to use this plan

Every phase ends with a gate check. **Do not start the next phase until the gate passes.**

```bash
python scripts/gate.py <phase_number>
# Example: python scripts/gate.py 0
# Exits 0 (all pass) or 1 (failures listed with fix instructions).
# Fix → re-run → move forward.
```

The gate script checks file existence, structural correctness, imports, and runs the full test suite automatically. Manual verification steps (live Azure resources, end-to-end smoke tests) are listed inside each phase — do those after the gate passes.

---

## Phase 0 — Cleanup
**Est: 30 min | Risk: zero | Saves: $5.50/month**

### Tasks

- [ ] **0.1** Delete Azure Container Registry
  ```bash
  az acr delete --name shubhllmregistry --resource-group LLM-yt --yes
  ```

- [ ] **0.2** Delete duplicate OpenAI account
  ```bash
  az cognitiveservices account delete --name skapa-mmo0s9in-eastus2 --resource-group llm-yt
  ```

- [ ] **0.3** Switch `deploy.yml` from ACR to GHCR
  - Replace `azure/container-apps-deploy-action@v2` with explicit build → push → deploy
  - Uses `GITHUB_TOKEN` (automatic) — no new secrets needed for push
  - Add `GHCR_TOKEN` secret (PAT with `write:packages`) for Container Apps pull auth

- [ ] **0.4** Register GHCR credentials on Container App (one-time)
  ```bash
  az containerapp registry set \
    --name brand-guardian-api --resource-group LLM-yt \
    --server ghcr.io --username shubh209 --password-secret ghcr-token
  ```

- [ ] **0.5** Remove old ACR secrets from GitHub repo settings
  - Delete: `BRANDGUARDIANAPI_REGISTRY_USERNAME`, `BRANDGUARDIANAPI_REGISTRY_PASSWORD`, `REGISTRY_NAME`

### Files changed
- `.github/workflows/deploy.yml`

### Verification
Push a commit to main. Confirm CI builds and deploys from `ghcr.io/shubh209/brand-guardian-api`.
`az containerapp show --name brand-guardian-api --resource-group LLM-yt --query "properties.template.containers[0].image"`

---

## Phase 1 — Database Migration
**Est: 1 hour | Risk: low (all nullable, no backfill)**

### Tasks

- [ ] **1.1** Create `alembic/versions/003_new_architecture.py`
  - Add to `audits` table:
    - `processing_status VARCHAR(32) NULL` — pending/transcribing/extracting_text/auditing/completed/failed
    - `audit_mode VARCHAR(8) NULL` — url/file
    - `platforms TEXT NULL` — comma-separated e.g. "youtube,tiktok"
  - Add to `audit_violations` table:
    - `platform VARCHAR(32) NULL` — which platform this violation applies to
  - Add index: `ix_audits_processing_status` on `(processing_status)` for worker polling

- [ ] **1.2** Update `backend/src/db/models.py`
  - Add 4 new columns to `Audit` and `AuditViolation` SQLAlchemy models

- [ ] **1.3** Update `backend/src/graph/state.py`
  - Add `platforms: List[str]`, `audit_mode: str`, `processing_status: str` to `VideoAuditState`

- [ ] **1.4** Run migration
  ```bash
  uv run alembic upgrade head
  ```

### Files changed
- `alembic/versions/003_new_architecture.py` *(new)*
- `backend/src/db/models.py`
- `backend/src/graph/state.py`

### Verification
`alembic upgrade head` runs clean. All existing tests pass: `pytest tests/ -v`

---

## Phase 2 — Retrieval Upgrade
**Est: 2 days | Biggest quality improvement in the pipeline**

### Tasks

- [ ] **2.1** Vector store singleton in `backend/src/services/policy_store.py`
  - Move `get_vector_store()` to module-level lazy-init `_store: AzureSearch | None = None`
  - Add `score: float = 0.0` and `platform: str | None = None` fields to `RetrievedChunk`
  - Switch `similarity_search` → `similarity_search_with_score`
  - Filter chunks below `RAG_MIN_SCORE` env var (default `0.45`)

- [ ] **2.2** Create `backend/src/services/reranker.py` *(new)*
  - Load `cross-encoder/ms-marco-MiniLM-L-6-v2` at module level (ponytail: single instance)
  - `rerank(query, chunks, top_n=5) -> list[RetrievedChunk]`
  - Attach cross-encoder score back onto each chunk

- [ ] **2.3** Rewrite `audit_content_node` in `backend/src/graph/nodes.py` — 4 stages
  - **Stage 1** — Claim extraction via GPT-4o-mini (temp 0.1)
    - Prompt: extract `[{claim, type, timestamp}]` from transcript + OCR
    - Types: health_claim, pricing_claim, disclosure, product_claim, general
  - **Stage 2** — Per-claim retrieval + rerank
    - Embed each claim text (not full transcript)
    - Retrieve k=20 per claim with platform filter
    - Rerank → top 5 per claim
    - Deduplicate chunks by `chunk_id` across all claims
    - Attach retrieval confidence (top chunk score) per claim
  - **Stage 3** — Policy reasoning via GPT-4o (temp 0.1)
    - Receives deduped chunks + structured claim list + confidence scores
    - Returns `[{violation, severity, rule_cited, chunk_id, platform, confidence, reasoning}]`
  - **Stage 4** — Report synthesis via GPT-4o-mini
    - Receives violations list → PASS/FAIL + summary

- [ ] **2.4** Add `sentence-transformers>=3.0.0` to `pyproject.toml`

- [ ] **2.5** Tag existing chunks with platform metadata
  - `policy_indexing.py`: add `platform` to chunk metadata when uploading to Azure AI Search
  - Re-index current PDFs to add platform tags (run `python backend/scripts/index_documents.py`)

### Files changed
- `backend/src/services/policy_store.py`
- `backend/src/services/reranker.py` *(new)*
- `backend/src/graph/nodes.py`
- `pyproject.toml`
- `backend/src/services/policy_indexing.py`

### Verification
- All existing tests pass
- Submit 2–3 test URLs. Check App Insights: `chunks_retrieved` should drop, `input_tokens` to GPT-4o should drop ~40%
- Manual spot-check: violations should cite more relevant rules than before

---

## Phase 3 — Live Policy Fetching
**Est: 1 day | Replaces static PDFs with live pages + blob fallback**

### Tasks

- [ ] **3.1** Create `backend/src/services/policy_sources.py` *(new)*
  ```python
  POLICY_SOURCES = [
    {"id": "youtube-ads",     "platform": "youtube",  "url": "...", "name": "YouTube Ad Policies"},
    {"id": "youtube-afcg",    "platform": "youtube",  "url": "...", "name": "YouTube Advertiser-Friendly Guidelines"},
    {"id": "ftc-endorsement", "platform": "generic",  "url": "...", "name": "FTC Endorsement Guides"},
    {"id": "tiktok-ads",      "platform": "tiktok",   "url": "...", "name": "TikTok Advertising Policies"},
    {"id": "meta-ads",        "platform": "facebook", "url": "...", "name": "Meta Advertising Standards"},
  ]
  ```

- [ ] **3.2** Create `backend/src/services/policy_fetcher.py` *(new)*
  - `fetch_policy_source(source) -> str`
  - Try Firecrawl scrape (`firecrawl-py` already installed)
  - On success: write to blob `policy-cache/{source_id}.json` with `{url, fetched_at, content}`
  - On failure: read from blob cache (fallback to last successful fetch)
  - Uses existing `shubhllmproject` storage account

- [ ] **3.3** Rewrite `backend/src/services/policy_indexing.py`
  - Replace `glob("*.pdf")` with iterate `POLICY_SOURCES` + `fetch_policy_source`
  - Chunk markdown text with same 1000/200 splitter
  - Tag each chunk: `{chunk_id, source, platform, fetched_at}`
  - Same `PolicyVersion` DB record pattern

- [ ] **3.4** Update `backend/src/api/routes/admin.py`
  - Add optional `?platforms=youtube,tiktok` query param to `POST /admin/policies/reindex`

- [ ] **3.5** Create weekly scheduled job in Azure
  ```bash
  az containerapp job create \
    --name policy-refresh-job \
    --resource-group LLM-yt \
    --environment managedEnvironment-LLMyt-a71c \
    --trigger-type Schedule \
    --cron-expression "0 3 * * 1" \
    --image ghcr.io/shubh209/brand-guardian-worker:latest \
    --command "python -m backend.scripts.index_documents"
  ```

### Files changed
- `backend/src/services/policy_sources.py` *(new)*
- `backend/src/services/policy_fetcher.py` *(new)*
- `backend/src/services/policy_indexing.py`
- `backend/src/api/routes/admin.py`

### Verification
- `python backend/scripts/index_documents.py` runs without error
- Blob container `policy-cache/` shows 5 JSON files in Azure Portal
- Each file has `fetched_at` timestamp and non-empty `content`
- Azure AI Search chunks have `platform` metadata field

---

## Phase 4 — Pre-upload Mode: Worker + Async Pipeline
**Est: 2 days | New capability: file upload → async processing**

### Tasks

- [ ] **4.1** Create `Dockerfile.worker` *(new)*
  - Same base as `Dockerfile`
  - Additional apt packages: `ffmpeg` (already in Dockerfile), `libgl1` (for PySceneDetect)
  - CMD: `python -m backend.src.worker.main`

- [ ] **4.2** Add `scenedetect>=0.6.4` to `pyproject.toml`

- [ ] **4.3** Create `backend/src/worker/video_processor.py` *(new)*
  - `transcribe(blob_path) -> TranscriptResult`
    - Download blob to temp file
    - Call Azure OpenAI Whisper API (`client.audio.transcriptions.create`)
    - Returns `{text, segments: [{start, end, text}]}`
  - `extract_ocr(video_path) -> list[OcrFrame]`
    - PySceneDetect → list of scene start timestamps
    - ffmpeg extract one JPEG per scene → Azure AI Vision Read API
    - Returns `[{timestamp, texts: [str]}]`
  - Clean up temp files on exit regardless of success/failure

- [ ] **4.4** Create `backend/src/worker/main.py` *(new)*
  - Queue polling loop (5s sleep when empty)
  - Visibility timeout: 600s (10 min)
  - Calls `video_processor` functions
  - Updates `processing_status` at each stage via `repository.update_processing_status()`
  - Calls `audit_content_node` (reused unchanged)
  - Deletes blob + queue message on success
  - On failure: updates `processing_status = "failed"`, deletes queue message, deletes blob

- [ ] **4.5** Add `update_processing_status()` to `backend/src/db/repository.py`
  - Single-column UPDATE on `Audit.processing_status` by `audit_id`

- [ ] **4.6** Add `POST /audit/upload` to `backend/src/api/server.py`
  - Accept: `multipart/form-data` — `file`, `platforms[]`, `email` (optional)
  - Validate: file size ≤ 500MB
  - Validate duration: `ffprobe -v error -show_entries format=duration` → reject > 60s
  - Upload blob to `uploads/{audit_id}.{ext}` in `shubhllmproject`
  - Enqueue to `audit-jobs` queue: `{audit_id, blob_url, platforms, email}`
  - Insert `Audit` row: `processing_status="pending"`, `audit_mode="file"`, `platforms=...`
  - Return `202 {"audit_id": "..."}`
  - Rate limit: `UPLOAD_RATE_LIMIT_PER_HOUR` env var, default `10` (separate from URL limit)

- [ ] **4.7** Extend `GET /audits/{audit_id}` response
  - `backend/src/api/routes/audits.py` — add `processing_status`, `audit_mode`, `platforms` to response schema

- [ ] **4.8** Update `backend/src/middleware/rate_limit.py`
  - Add `POST /audit/upload` to rate-limited paths with its own bucket and limit

- [ ] **4.9** Create worker Container App in Azure
  ```bash
  az containerapp create \
    --name brand-guardian-worker \
    --resource-group LLM-yt \
    --environment managedEnvironment-LLMyt-a71c \
    --image ghcr.io/shubh209/brand-guardian-worker:latest \
    --min-replicas 0 --max-replicas 3 \
    --registry-server ghcr.io \
    --registry-username shubh209 \
    --registry-password-secret ghcr-token
  ```
  Set same env vars as API container.

- [ ] **4.10** Add worker build + deploy to `deploy.yml`
  - Second job: build `Dockerfile.worker` → push as `brand-guardian-worker:latest` → `az containerapp update`

### Files changed
- `Dockerfile.worker` *(new)*
- `backend/src/worker/__init__.py` *(new, empty)*
- `backend/src/worker/main.py` *(new)*
- `backend/src/worker/video_processor.py` *(new)*
- `backend/src/db/repository.py`
- `backend/src/api/server.py`
- `backend/src/api/routes/audits.py`
- `backend/src/middleware/rate_limit.py`
- `pyproject.toml`
- `.github/workflows/deploy.yml`

### Verification
```bash
# Upload test
curl -X POST http://localhost:8000/audit/upload \
  -F "file=@test-ad.mp4" \
  -F "platforms=youtube" \
  -H "X-API-Key: bg_..."

# Poll until completed
curl http://localhost:8000/audits/{audit_id}
# Watch processing_status advance: pending → transcribing → extracting_text → auditing → completed
```
- Blob deleted after completion
- Audit result in Postgres with violations

---

## Phase 5 — Multi-platform Audit
**Est: 1 day | Wire platform selection end-to-end**

### Tasks

- [ ] **5.1** Update `AuditRequest` in `backend/src/api/server.py`
  - Add `platforms: list[str] = ["youtube"]`
  - Validate: must be subset of `["youtube", "tiktok", "facebook"]`, min 1

- [ ] **5.2** Update `AuditResponse`
  - Add `platforms: list[str]`
  - Add `violations_by_platform: dict[str, list[ComplianceIssue]]`

- [ ] **5.3** Platform loop in `audit_content_node`
  - For each platform in `state["platforms"]`, run Stages 2–3 with platform filter
  - Each violation gets `platform` tag
  - `final_status = FAIL` if any platform returns violations
  - Merge all violations into `compliance_results`; also build `violations_by_platform` dict

- [ ] **5.4** Pass `platform` through `save_audit` → `AuditViolation.platform` column

- [ ] **5.5** Update URL validation in `backend/src/api/server.py`
  - For `platform=tiktok`: accept `tiktok.com` URLs
  - For `platform=facebook`: accept `facebook.com` or `fb.watch` URLs
  - For `platform=youtube`: existing check unchanged
  - Multi-platform: validate URL matches at least one selected platform

### Files changed
- `backend/src/api/server.py`
- `backend/src/graph/nodes.py`
- `backend/src/db/repository.py`

### Verification
`POST /audit` with `platforms: ["youtube", "tiktok"]`
→ Response has both `violations_by_platform.youtube` and `violations_by_platform.tiktok`
→ `audit_violations` table rows have `platform` column populated

---

## Phase 6 — Email Delivery
**Est: 0.5 day**

### Tasks

- [ ] **6.1** Create Azure Communication Services resource (one-time)
  ```bash
  az communication create \
    --name brand-guardian-comms \
    --resource-group LLM-yt \
    --data-location UnitedStates
  ```
  Add connection string to `.env` as `AZURE_COMM_CONNECTION_STRING`

- [ ] **6.2** Add `azure-communication-email>=1.0.0` to `pyproject.toml`

- [ ] **6.3** Create `backend/src/services/email_service.py` *(new)*
  - `send_audit_report(to_email, audit_id, pdf_bytes) -> None`
  - Uses `azure.communication.email.EmailClient`
  - Attaches PDF as base64 encoded attachment
  - Subject: `"Brand Guardian Audit Report — {audit_id[:8]}"`

- [ ] **6.4** Call from worker on completion
  - `backend/src/worker/main.py`: after `processing_status = "completed"`, if `email` in job payload:
    - Call `export_audit_pdf(audit_id, db)` (existing function in `export.py`)
    - Call `send_audit_report(email, audit_id, pdf_bytes)`

- [ ] **6.5** Add `POST /audits/{audit_id}/email` endpoint
  - `backend/src/api/routes/audits.py`
  - For users who didn't provide email at submission time
  - Accepts `{email: str}`, generates PDF, sends immediately
  - Auth: same `require_reviewer` guard

### Files changed
- `backend/src/services/email_service.py` *(new)*
- `backend/src/worker/main.py`
- `backend/src/api/routes/audits.py`
- `pyproject.toml`
- `env.example`

### Verification
Submit upload with real email address. Confirm email arrives with PDF attached within 5 minutes of job completion.

---

## Phase 7 — Frontend: Live Progress + Multi-platform UI
**Est: 2 days | "Feels live" progress + dual report view**

### Tasks

- [ ] **7.1** Add three favicon SVGs to repo root
  - `favicon.svg` — default (existing or neutral)
  - `favicon-done.svg` — green shield (audit complete)
  - `favicon-error.svg` — red shield (audit failed)

- [ ] **7.2** Mode toggle in `index.html`
  - Two-state toggle: "YouTube URL" / "Upload Video"
  - Shows/hides the relevant input section
  - Platform checkboxes: YouTube ☑ TikTok ☐ Facebook ☐ (at least one required, client-side validation)

- [ ] **7.3** Upload form
  - `<input type="file" accept="video/*">` with max size hint
  - Optional email input field
  - Client-side duration check via `<video>` element's `duration` property before upload (reject > 60s with helpful message)

- [ ] **7.4** Upload progress + polling progress bar
  - 0–20%: HTTP upload progress via `XMLHttpRequest.upload.onprogress`
  - 20–100%: driven by `processing_status` from polling
    ```javascript
    const STATUS_PROGRESS = {
      pending: 20, transcribing: 35, extracting_text: 55,
      auditing: 75, completed: 100, failed: 0
    };
    ```
  - CSS: `transition: width 0.8s ease` — smooth between polling ticks, never jumps
  - Poll interval: 5 seconds via `setInterval`
  - Stage label shown below bar: "Transcribing audio…" / "Reading on-screen text…" / "Auditing against policy…"

- [ ] **7.5** Tab title + favicon swap
  ```javascript
  function setTabState(state) {
    const link = document.querySelector("link[rel~='icon']");
    if (state === 'completed') {
      document.title = "✅ Audit Complete — Brand Guardian";
      link.href = "/favicon-done.svg";
    } else if (state === 'failed') {
      document.title = "❌ Audit Failed — Brand Guardian";
      link.href = "/favicon-error.svg";
    } else if (state !== 'idle') {
      document.title = "⏳ Auditing… — Brand Guardian";
    }
  }
  ```

- [ ] **7.6** Dual report view
  - Results section: "All Platforms" tab (merged, existing layout) + one tab per selected platform
  - Tab switching: pure CSS + `display` toggle, no library
  - Per-platform tab only shows if that platform has violations

- [ ] **7.7** Export buttons
  - "Download PDF" button → `GET /export/{audit_id}/pdf` (already exists)
  - "Email Report" button → prompts for email if not already submitted, calls `POST /audits/{audit_id}/email`

### Files changed
- `index.html`
- `favicon-done.svg` *(new)*
- `favicon-error.svg` *(new)*

### Verification
- Upload a video, watch bar advance in real time with stage labels
- Switch to a different browser tab mid-processing, confirm tab title changes to ✅ on completion
- Confirm favicon changes colour
- Select YouTube + TikTok, confirm dual tabs appear in results
- Download PDF — confirm it opens
- Send email — confirm it arrives

---

## Phase 8 — Observability
**Est: 0.5 day**

### Tasks

- [ ] **8.1** Add `langfuse>=2.0.0` to `pyproject.toml`

- [ ] **8.2** Add Langfuse callback to `backend/src/api/server.py`
  ```python
  from langfuse.callback import CallbackHandler
  langfuse_handler = CallbackHandler(
      public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
      secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
      host="https://cloud.langfuse.com"
  )
  # Pass to compliance_graph.ainvoke():
  config = {"callbacks": [langfuse_handler]}
  ```

- [ ] **8.3** Add span metadata in `audit_content_node`
  - Log to span: `claims_extracted`, `chunks_retrieved`, `chunks_after_rerank`, `input_tokens`, `output_tokens`, `retrieval_confidence_max`, `retrieval_confidence_min`

- [ ] **8.4** Add Langfuse spans to worker stages in `backend/src/worker/main.py`
  - Wrap transcription, OCR, and audit as named spans

- [ ] **8.5** Add env vars to `env.example`
  - `LANGFUSE_PUBLIC_KEY=`
  - `LANGFUSE_SECRET_KEY=`

### Files changed
- `backend/src/api/server.py`
- `backend/src/graph/nodes.py`
- `backend/src/worker/main.py`
- `pyproject.toml`
- `env.example`

### Verification
Submit one URL audit and one file upload audit.
Open Langfuse Cloud → confirm both traces appear with all stages, latency per stage, token counts.

---

## Phase 9 — CI/CD Hardening + Production Audit
**Est: 0.5 day**

### Tasks

- [ ] **9.1** Add production-audit step to `deploy.yml`
  ```yaml
  - name: Production audit
    run: npx commitshow@latest audit github.com/shubh209/Youtube-Ads-Compliance-Pipeline --json --source=production-audit-skill > .commitshow/audit.json 2>&1
    continue-on-error: true
  - name: Show audit score
    run: cat .commitshow/audit.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"Score: {d['score']['total']}/100 · {d['score']['band']}\")"
  ```

- [ ] **9.2** Add `.commitshow/` to `.gitignore`

- [ ] **9.3** Final env.example audit — confirm all new env vars documented
  - `AZURE_COMM_CONNECTION_STRING`
  - `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`
  - `UPLOAD_RATE_LIMIT_PER_HOUR`
  - `RAG_MIN_SCORE`
  - `AZURE_STORAGE_QUEUE_NAME` (default: `audit-jobs`)

### Files changed
- `.github/workflows/deploy.yml`
- `.gitignore`
- `env.example`

### Verification
`npx commitshow@latest audit github.com/shubh209/Youtube-Ads-Compliance-Pipeline --json`
Review score and top concerns before marking complete.

---

## File Map

| File | Phase | Type |
|---|---|---|
| `.github/workflows/deploy.yml` | 0, 4, 9 | Modified |
| `backend/src/services/policy_store.py` | 2 | Modified |
| `backend/src/services/reranker.py` | 2 | **New** |
| `backend/src/services/policy_sources.py` | 3 | **New** |
| `backend/src/services/policy_fetcher.py` | 3 | **New** |
| `backend/src/services/policy_indexing.py` | 3 | Modified |
| `backend/src/services/email_service.py` | 6 | **New** |
| `backend/src/graph/nodes.py` | 2, 5 | Modified |
| `backend/src/graph/state.py` | 1 | Modified |
| `backend/src/worker/__init__.py` | 4 | **New** |
| `backend/src/worker/main.py` | 4, 6, 8 | **New** |
| `backend/src/worker/video_processor.py` | 4 | **New** |
| `backend/src/db/models.py` | 1 | Modified |
| `backend/src/db/repository.py` | 1, 4, 5 | Modified |
| `backend/src/api/server.py` | 4, 5, 8 | Modified |
| `backend/src/api/routes/audits.py` | 4, 6 | Modified |
| `backend/src/api/routes/admin.py` | 3 | Modified |
| `backend/src/middleware/rate_limit.py` | 4 | Modified |
| `alembic/versions/003_new_architecture.py` | 1 | **New** |
| `Dockerfile.worker` | 4 | **New** |
| `index.html` | 7 | Modified |
| `favicon-done.svg` | 7 | **New** |
| `favicon-error.svg` | 7 | **New** |
| `pyproject.toml` | 2, 4, 6, 8 | Modified |
| `env.example` | 3, 6, 8, 9 | Modified |

**New files: 12 · Modified files: 13 · Deleted: 0**

---

## New Dependencies

```toml
sentence-transformers>=3.0.0    # Phase 2 — cross-encoder reranking
scenedetect>=0.6.4              # Phase 4 — video scene detection
azure-communication-email>=1.0.0 # Phase 6 — email delivery
langfuse>=2.0.0                 # Phase 8 — LLM tracing
```

---

## New Azure Resources

| Resource | Phase | Command |
|---|---|---|
| Worker Container App `brand-guardian-worker` | 4 | `az containerapp create ...` |
| Policy refresh scheduled job `policy-refresh-job` | 3 | `az containerapp job create ...` |
| Azure Communication Services `brand-guardian-comms` | 6 | `az communication create ...` |

---

## Execution Order

```
Phase 0 → Phase 1 → Phase 2 → Phase 3
                                  ↓
                  Phase 4 ← (needs platform tags from Phase 3)
                      ↓
                  Phase 5 → Phase 6 → Phase 7 → Phase 8 → Phase 9
```

Phases 2 and 3 touch different files and can be parallelised if needed.

---

## Total Estimate

| Phase | Work |
|---|---|
| 0 — Cleanup | 30 min |
| 1 — DB migration | 1 hr |
| 2 — Retrieval upgrade | 2 days |
| 3 — Live policy fetching | 1 day |
| 4 — Worker + upload | 2 days |
| 5 — Multi-platform | 1 day |
| 6 — Email | 0.5 day |
| 7 — Frontend | 2 days |
| 8 — Observability | 0.5 day |
| 9 — CI/CD | 0.5 day |
| **Total** | **~10.5 days** |
