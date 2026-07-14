# Brand Guardian AI — Agent Context

Read this file first. Do not make any changes until you understand the current state and have confirmed the task with the user.

---

## What this project is

A pre-publication video ad compliance scanner. Users submit a YouTube URL or upload a video file. The system extracts transcript and on-screen text, checks it against live-fetched platform policies (YouTube, Meta, TikTok, Facebook, X, FTC), and returns a structured violation report with exact policy citations before the ad is submitted to any platform.

The core product insight: existing tools check ad copy text. No tool checks the actual video content (spoken claims + on-screen text) before submission. That gap is what this solves.

---

## Current state (as of last session)

**Pipeline status: RETRIEVAL FIXED — GPT-4o rate limit is current bottleneck**

- Health endpoint: responding at `https://brand-guardian-api.wonderfulbay-f06178ea.eastus.azurecontainerapps.io/health`
- Retrieval: working. Root cause of zero-violation output was `AZURE_SEARCH_INDEX_NAME="compliance-docs"` in `.env` — the rebuilt index is named `brand-compliance-rules`. Fixed locally and in Container App (`az containerapp update --set-env-vars`).
- Audit endpoint: fails with `429 rate_limit_exceeded` on GPT-4o (brand-guardian-openai, eastus2). Current quota is 10K TPM — too low for a full audit call. Needs quota increase in Azure OpenAI Studio before end-to-end audits can run.
- Phase 10 subtasks 10.1–10.4 complete: URL list expanded to 35, EXTRACTION_SCHEMA validated, fetcher switched from scrape to extract, indexing chunks structured JSON per-rule. Reindex against live Azure index not yet run — awaiting user confirmation (costs ~1,050 Firecrawl credits).

**What is working:**
- 4-stage audit pipeline (claim extraction → retrieval → GPT-4o reasoning → synthesis)
- Per-claim retrieval with query expansion (`_expand_claim` rewrites to policy terminology)
- Chain-of-thought system prompt
- Risk level output (HIGH/MEDIUM/LOW) per violation
- Azure Container Apps deployment (GHCR images)
- Neon PostgreSQL with all migrations applied (003_new_architecture)
- Azure AI Search index `brand-compliance-rules` — 122 chunks, retrieval confirmed working locally
- Policy sources: 35 leaf-level URLs across YouTube (15), Meta (8), TikTok (5), X (5), FTC (2)
- Async admin reindex endpoint (returns 202, runs in background)
- Firecrawl structured extraction with blob cache fallback (switched from scrape to extract)
- Semantic hybrid search with fallback (`semantic_hybrid_search_with_score` → `similarity_search_with_score`)

**What is NOT working / not yet built:**
- GPT-4o TPM quota too low (10K TPM on brand-guardian-openai). Raise to ≥50K in Azure OpenAI Studio to unblock end-to-end audits.
- Live reindex with new structured extraction not yet run (needs user confirmation — ~1,050 Firecrawl credits for 35 URLs)
- Pre-upload video mode (worker + Azure Storage Queue) — code exists, worker Container App not created in Azure yet
- Email delivery (code exists, Azure Communication Services resource not created)
- Frontend auth flow (no MSAL / API key entry UI)
- Langfuse observability (configured in code, not tested end-to-end)

---

## Before you do anything

1. **Read the task the user gave you.** Identify which category it falls into (see Task Categories below).
2. **Check current state.** Run `git status` and `PYTHONPATH=. uv run pytest tests/ -q` before touching code.
3. **Ask before building.** If the task is ambiguous, ask one focused question. Do not assume.
4. **Use relevant skills.** Check available skills before writing code from scratch.
5. **If you find yourself doing the same thing repeatedly**, stop and suggest creating a skill for it.

---

## Task categories

When the user gives you a task, identify its category first. Each category has a preferred approach.

**Category: Bug fix / pipeline not working**
→ Diagnose root cause before touching code. Use `/diagnose` skill. State the problem, why it exists, how important it is to fix. Get confirmation before fixing.

**Category: New feature / implementation**
→ Check `IMPLEMENTATION_PLAN.md` first. If the feature is already planned, follow the subtask structure. Run `python3 scripts/gate.py <phase>` to verify. Write tests alongside code. No new abstractions unless asked.

**Category: Architecture / design decision**
→ Do not implement immediately. Present options with tradeoffs. Ask the questions listed in `IMPLEMENTATION_PLAN.md` → "Assumptions to clear" pattern. Add decisions to plan before coding.

**Category: Configuration / deployment**
→ Check Azure resources first with `az` CLI before making changes. State what you are about to change and get confirmation. Never update production env vars without user confirmation.

**Category: Research / analysis**
→ Use internet search tools. Cite sources. Distinguish what exists in the codebase from what you're inferring.

**Category: Writing / documentation**
→ Match the style of existing docs. No markdown headers unless explicitly asked. No em dashes. No AI fluff.

---

## Available skills

Skills are in `~/.kiro/skills/`. Use them — they are there for a reason.

**Active by default (check session):**
- `ponytail` — lazy senior dev mode. Minimum code. No unrequested abstractions. Deletion over addition. Always active on this project unless user says "stop ponytail".
- `production-audit` — scan shipped code for production-readiness gaps. Run after completing a phase.

**Engineering:**
- `diagnose` — structured debugging loop for hard bugs. Use before touching broken code.
- `tdd` — red-green-refactor. Use when adding new features with tests.
- `zoom-out` — get broader context when unfamiliar with a section.
- `improve-codebase-architecture` — find deepening opportunities. Use before architecture decisions.
- `grill-with-docs` — stress-test a plan against existing domain model.
- `grill-me` — interview the user to clarify a plan before building.
- `to-issues` — break a plan into independently-grabbable issues.
- `prototype` — build throwaway prototype to flesh out design before committing.
- `triage` — triage issues through a state machine.

**Productivity:**
- `caveman` — ultra-compressed responses. Use when user wants short answers.
- `handoff` — compact session into handoff doc for next agent.
- `grill-me` — relentlessly question the user's plan until clear.

**Misc:**
- `setup-pre-commit` — add Husky/lint-staged hooks.
- `git-guardrails-claude-code` — block dangerous git commands.
- `prompt-master` — generate optimized prompts for any AI tool (LLMs, Cursor, Midjourney, coding agents). Use when asked to write, fix, or improve a prompt for a specific tool.

**When to suggest a new skill:** if you catch yourself writing the same prompt pattern, debugging loop, or boilerplate sequence more than twice in a session, stop and suggest `/write-a-skill` to the user.

---

## Key files and their purpose

| File/Folder | Purpose |
|---|---|
| `IMPLEMENTATION_PLAN.md` | Full phase-by-phase build plan with task checklists, gate checks, and future scope |
| `INTERVIEW_QA.md` | Technical Q&A about every decision in this project — grounded in real code |
| `CONTEXT.md` | Domain glossary, entity relationships, terminology |
| `scripts/gate.py` | Quality gate runner. Run `python3 scripts/gate.py <phase>` after completing a phase |
| `src/pipeline/nodes.py` | Core 4-stage audit pipeline: claim extraction → retrieval → reasoning → synthesis |
| `src/services/policy_store.py` | Vector store singleton, retrieval, score filtering |
| `src/services/policy_fetcher.py` | Firecrawl structured extract with blob cache fallback |
| `src/services/policy_sources.py` | Registry of 35 leaf-level policy URLs (YT=15, Meta=8, TikTok=5, X=5, FTC=2) |
| `src/services/policy_indexing.py` | Chunking, wipe-and-replace reindex logic |
| `src/api/server.py` | FastAPI app, /audit and /audit/upload endpoints |
| `src/api/routes/admin.py` | Async reindex endpoint, API key management |
| `src/worker/` | Async video processing worker (queue polling, Whisper, OCR) |
| `data/` | Fallback policy PDFs (used if all Firecrawl fetches fail) |
| `tests/` | 57 tests. Must pass before any commit. |
| `docs/adr/` | Architecture decision records for major choices |

---

## Decisions already made — do not re-propose these

- **No Redis** for rate limiting (in-memory is sufficient at current scale)
- **No Kafka / RabbitMQ / Service Bus** (Azure Storage Queue is sufficient)
- **No sentence-transformers in the API image** (3GB PyTorch bloat, fallback to vector score order)
- **No headroom-ai in production** (local dev tool only, removed from pyproject.toml)
- **No streamlit** (replaced by index.html frontend)
- **No Docker Compose** (single Container App per service)
- **No microservices** (monolith deployed twice: API + Worker)
- **No binary quantization / ONNX** until scale justifies it
- **No Graph RAG** until golden dataset exists to measure improvement
- **No LLM provider interface abstraction** until second provider is needed
- **Wipe-and-replace** on reindex (not versioned namespacing — see FS-6 in plan for future upgrade path)
- **Firecrawl /extract not /scrape** (switched in Phase 10 — extract returns structured JSON with `what_is_prohibited` items; costs ~30 credits/URL vs 1 for scrape; upgrade path: batch_scrape + GPT-4o-mini if credit cost is prohibitive)
- **GPT-4o at temperature 0.1** with chain-of-thought reasoning
- **Azure data residency required** — no DeepSeek, no Together.ai, no Groq

---

## Azure resources

| Resource | Type | Purpose |
|---|---|---|
| `brand-guardian-openai` (eastus2) | Azure OpenAI | GPT-4o + text-embedding-3-small — active endpoint |
| `shubh-llm-api-project` (eastus) | Azure OpenAI | text-embedding-3-small only — do NOT use for chat |
| `shubh-llm-ai-search` (centralus) | Azure AI Search Free | Vector store, index: `brand-compliance-rules` |
| `shubhllmproject` | Storage Account | Blob cache (policy-cache/), uploads, queue (audit-jobs) |
| `brand-guardian-api` | Container App | API server, scale-to-zero |
| `managedEnvironment-LLMyt-a71c` | Container Apps env | Shared environment |
| Neon PostgreSQL | Serverless Postgres | Audit history, users, teams, violations |

Container App URL: `https://brand-guardian-api.wonderfulbay-f06178ea.eastus.azurecontainerapps.io`

---

## Coding constraints

- `PYTHONPATH=.` required for all local test and script runs
- After every `fs_write` or `str_replace`, verify with `grep` before moving on
- Never use heredocs in `execute_bash` (they hang)
- Run `PYTHONPATH=. uv run pytest tests/ -q` before every commit
- Max retries on any task: 4. If stuck after 4 attempts, stop and explain the problem to the user.
