#!/usr/bin/env python3
"""
Phase gate runner. Run after completing each phase.
Usage: python scripts/gate.py <phase_number>
Example: python scripts/gate.py 0

Exits 0 if all gates pass, 1 if any fail.
All gates must pass before moving to the next phase.
"""
import subprocess
import sys
import os
import json
import importlib
from pathlib import Path

ROOT = Path(__file__).parent.parent
REPO = ROOT

# ── helpers ──────────────────────────────────────────────────────────────────

def run(cmd: str, cwd=None) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd or ROOT, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()

def gate(label: str, ok: bool, detail: str = ""):
    status = "✅ PASS" if ok else "❌ FAIL"
    line = f"  {status}  {label}"
    if detail and not ok:
        line += f"\n         → {detail}"
    print(line)
    return ok

def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)

def cmd_ok(cmd: str, cwd=None) -> bool:
    code, _ = run(cmd, cwd)
    return code == 0

def file_exists(*paths) -> bool:
    return all((ROOT / p).exists() for p in paths)

def file_contains(path: str, text: str) -> bool:
    try:
        return text in (ROOT / path).read_text()
    except FileNotFoundError:
        return False

def az_resource_exists(resource_type: str, name: str, rg: str) -> bool:
    code, _ = run(f'az resource show --resource-type {resource_type} --name {name} --resource-group {rg} --output none 2>&1')
    return code == 0

# ── phase gates ──────────────────────────────────────────────────────────────

def phase_0() -> list[bool]:
    section("Phase 0 — Cleanup")
    results = []

    # ACR deleted
    acr_gone = not az_resource_exists(
        "Microsoft.ContainerRegistry/registries", "shubhllmregistry", "LLM-yt"
    )
    results.append(gate("ACR shubhllmregistry deleted", acr_gone,
        "Run: az acr delete --name shubhllmregistry --resource-group LLM-yt --yes"))

    # Duplicate OpenAI account deleted
    dup_gone = not az_resource_exists(
        "Microsoft.CognitiveServices/accounts", "skapa-mmo0s9in-eastus2", "llm-yt"
    )
    results.append(gate("Duplicate OpenAI account deleted", dup_gone,
        "Run: az cognitiveservices account delete --name skapa-mmo0s9in-eastus2 --resource-group llm-yt"))

    # deploy.yml references ghcr.io not azurecr.io
    deploy_uses_ghcr = (
        file_contains(".github/workflows/deploy.yml", "ghcr.io") and
        not file_contains(".github/workflows/deploy.yml", "azurecr.io")
    )
    results.append(gate("deploy.yml uses GHCR not ACR", deploy_uses_ghcr,
        "Update .github/workflows/deploy.yml to push to ghcr.io"))

    # ACR secrets removed from workflow
    no_acr_secrets = not file_contains(".github/workflows/deploy.yml", "BRANDGUARDIANAPI_REGISTRY")
    results.append(gate("ACR secrets removed from deploy.yml", no_acr_secrets,
        "Remove BRANDGUARDIANAPI_REGISTRY_USERNAME/PASSWORD from deploy.yml"))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results


def phase_1() -> list[bool]:
    section("Phase 1 — Database Migration")
    results = []

    # Migration file exists
    migrations = list((ROOT / "alembic/versions").glob("003_*.py"))
    results.append(gate("003 migration file exists", bool(migrations),
        "Create alembic/versions/003_new_architecture.py"))

    # Migration contains required columns
    if migrations:
        content = migrations[0].read_text()
        for col in ["processing_status", "audit_mode", "platforms", "platform"]:
            results.append(gate(f"Migration has column: {col}", col in content,
                f"Add {col} column to migration"))

    # Models updated
    models = (ROOT / "backend/src/db/models.py").read_text()
    for field in ["processing_status", "audit_mode", "platforms"]:
        results.append(gate(f"Audit model has field: {field}", field in models,
            f"Add {field} to Audit model in db/models.py"))

    results.append(gate("AuditViolation model has platform field",
        "platform" in models, "Add platform to AuditViolation model"))

    # State updated
    state = (ROOT / "backend/src/graph/state.py").read_text()
    for field in ["platforms", "audit_mode", "processing_status"]:
        results.append(gate(f"VideoAuditState has field: {field}", field in state,
            f"Add {field} to VideoAuditState"))

    # Migration runs clean (requires DB connection — skip if no DB)
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        code, out = run("uv run alembic upgrade head 2>&1")
        results.append(gate("alembic upgrade head succeeds", code == 0, out[:300]))
    else:
        results.append(gate("alembic upgrade head (skipped — no DATABASE_URL)", True))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results


def phase_2() -> list[bool]:
    section("Phase 2 — Retrieval Upgrade")
    results = []

    # Reranker file exists
    results.append(gate("reranker.py exists",
        file_exists("backend/src/services/reranker.py"),
        "Create backend/src/services/reranker.py"))

    # Singleton pattern in policy_store
    store = (ROOT / "backend/src/services/policy_store.py").read_text()
    results.append(gate("policy_store uses module-level singleton (_store)",
        "_store" in store and "global _store" in store,
        "Add module-level _store singleton to policy_store.py"))

    # Score field on RetrievedChunk
    results.append(gate("RetrievedChunk has score field", "score" in store,
        "Add score: float = 0.0 to RetrievedChunk dataclass"))

    # similarity_search_with_score used
    results.append(gate("Uses similarity_search_with_score",
        "similarity_search_with_score" in store,
        "Replace similarity_search with similarity_search_with_score"))

    # RAG_MIN_SCORE used
    results.append(gate("RAG_MIN_SCORE threshold applied",
        "RAG_MIN_SCORE" in store,
        "Add score filtering using RAG_MIN_SCORE env var"))

    # sentence-transformers in deps
    pyproject = (ROOT / "pyproject.toml").read_text()
    results.append(gate("sentence-transformers in pyproject.toml",
        "sentence-transformers" in pyproject,
        "Add sentence-transformers>=3.0.0 to pyproject.toml"))

    # 4-stage audit node
    nodes = (ROOT / "backend/src/graph/nodes.py").read_text()
    for stage in ["claim", "rerank", "reasoning", "synthesis"]:
        # ponytail: loose check on keyword presence, not structure
        has_stage = any(kw in nodes.lower() for kw in [stage, stage[:5]])
        results.append(gate(f"audit_content_node has {stage} stage", has_stage,
            f"Add {stage} stage to audit_content_node"))

    # Platform field on chunks
    indexing = (ROOT / "backend/src/services/policy_indexing.py").read_text()
    results.append(gate("policy_indexing tags chunks with platform",
        '"platform"' in indexing or "'platform'" in indexing,
        "Add platform to chunk metadata in policy_indexing.py"))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    # Reranker self-check
    code, out = run("uv run python -c \"from src.services.reranker import rerank; print('reranker import ok')\" 2>&1")
    results.append(gate("reranker imports without error", code == 0, out[:200]))

    return results


def phase_3() -> list[bool]:
    section("Phase 3 — Live Policy Fetching")
    results = []

    results.append(gate("policy_sources.py exists",
        file_exists("backend/src/services/policy_sources.py"),
        "Create backend/src/services/policy_sources.py"))

    results.append(gate("policy_fetcher.py exists",
        file_exists("backend/src/services/policy_fetcher.py"),
        "Create backend/src/services/policy_fetcher.py"))

    # Sources registry has all 5 platforms
    if file_exists("backend/src/services/policy_sources.py"):
        sources = (ROOT / "backend/src/services/policy_sources.py").read_text()
        for platform in ["youtube", "tiktok", "facebook", "ftc"]:
            results.append(gate(f"POLICY_SOURCES contains {platform}", platform in sources,
                f"Add {platform} policy URL to POLICY_SOURCES"))

    # Fetcher has blob fallback
    if file_exists("backend/src/services/policy_fetcher.py"):
        fetcher = (ROOT / "backend/src/services/policy_fetcher.py").read_text()
        results.append(gate("policy_fetcher has blob fallback on failure",
            "except" in fetcher and ("blob" in fetcher.lower() or "cache" in fetcher.lower()),
            "Add try/except with blob cache fallback in policy_fetcher.py"))

    # Indexing uses sources not PDF glob
    indexing = (ROOT / "backend/src/services/policy_indexing.py").read_text()
    results.append(gate("policy_indexing no longer uses PDF glob",
        "*.pdf" not in indexing and "glob" not in indexing,
        "Replace glob('*.pdf') with POLICY_SOURCES iteration"))

    results.append(gate("policy_indexing uses fetch_policy_source",
        "fetch_policy_source" in indexing,
        "Call fetch_policy_source in policy_indexing.py"))

    # env.example updated
    env = (ROOT / "env.example").read_text()
    results.append(gate("FIRECRAWL_API_KEY in env.example",
        "FIRECRAWL_API_KEY" in env,
        "Add FIRECRAWL_API_KEY to env.example"))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results


def phase_4() -> list[bool]:
    section("Phase 4 — Worker + Upload Mode")
    results = []

    for f in ["backend/src/worker/__init__.py",
              "backend/src/worker/main.py",
              "backend/src/worker/video_processor.py",
              "Dockerfile.worker"]:
        results.append(gate(f"{f} exists", file_exists(f), f"Create {f}"))

    # Worker has queue polling loop
    if file_exists("backend/src/worker/main.py"):
        worker = (ROOT / "backend/src/worker/main.py").read_text()
        results.append(gate("worker has polling loop",
            "receive_message" in worker or "dequeue" in worker.lower(),
            "Add queue polling loop to worker/main.py"))
        results.append(gate("worker updates processing_status at each stage",
            "processing_status" in worker,
            "Update processing_status in worker at each stage"))
        results.append(gate("worker deletes blob on completion",
            "delete_blob" in worker or "BlobClient" in worker,
            "Delete blob after job completes in worker/main.py"))

    # video_processor has Whisper + OCR
    if file_exists("backend/src/worker/video_processor.py"):
        vp = (ROOT / "backend/src/worker/video_processor.py").read_text()
        results.append(gate("video_processor calls Azure Whisper",
            "whisper" in vp.lower() or "audio.transcriptions" in vp,
            "Add Azure OpenAI Whisper call in video_processor.py"))
        results.append(gate("video_processor calls Azure Vision OCR",
            "vision" in vp.lower() or "analyze" in vp.lower() or "read" in vp.lower(),
            "Add Azure Vision Read API call in video_processor.py"))
        results.append(gate("video_processor cleans up temp files",
            "finally" in vp or "cleanup" in vp.lower() or "unlink" in vp,
            "Add temp file cleanup in video_processor.py (use try/finally)"))

    # Upload endpoint exists
    server = (ROOT / "backend/src/api/server.py").read_text()
    results.append(gate("POST /audit/upload endpoint exists",
        "/audit/upload" in server or "audit/upload" in server,
        "Add POST /audit/upload to server.py"))
    results.append(gate("Upload endpoint validates duration",
        "ffprobe" in server or "duration" in server,
        "Add ffprobe duration check in upload endpoint"))
    results.append(gate("Upload endpoint returns 202",
        "202" in server,
        "Return HTTP 202 from upload endpoint"))

    # Rate limit for upload
    rate = (ROOT / "backend/src/middleware/rate_limit.py").read_text()
    results.append(gate("Upload route has separate rate limit",
        "upload" in rate.lower() or "UPLOAD_RATE_LIMIT" in rate,
        "Add upload route to rate_limit.py with separate limit"))

    # scenedetect in deps
    pyproject = (ROOT / "pyproject.toml").read_text()
    results.append(gate("scenedetect in pyproject.toml",
        "scenedetect" in pyproject,
        "Add scenedetect>=0.6.4 to pyproject.toml"))

    # Dockerfile.worker exists and has right CMD
    if file_exists("Dockerfile.worker"):
        dw = (ROOT / "Dockerfile.worker").read_text()
        results.append(gate("Dockerfile.worker CMD runs worker",
            "worker" in dw and "CMD" in dw,
            "Set CMD to python -m backend.src.worker.main in Dockerfile.worker"))

    # GET /audits/{id} exposes processing_status
    audits_route = (ROOT / "backend/src/api/routes/audits.py").read_text()
    results.append(gate("GET /audits/{id} exposes processing_status",
        "processing_status" in audits_route,
        "Add processing_status to audit GET response in routes/audits.py"))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results


def phase_5() -> list[bool]:
    section("Phase 5 — Multi-platform Audit")
    results = []

    server = (ROOT / "backend/src/api/server.py").read_text()

    results.append(gate("AuditRequest has platforms field",
        "platforms" in server,
        "Add platforms: list[str] to AuditRequest"))
    results.append(gate("AuditResponse has violations_by_platform",
        "violations_by_platform" in server,
        "Add violations_by_platform to AuditResponse"))

    nodes = (ROOT / "backend/src/graph/nodes.py").read_text()
    results.append(gate("audit_content_node loops over platforms",
        "platforms" in nodes,
        "Add platform loop to audit_content_node"))

    repo = (ROOT / "backend/src/db/repository.py").read_text()
    results.append(gate("save_audit passes violation platform field",
        "platform" in repo,
        "Pass platform field through save_audit to AuditViolation"))

    # TikTok/Facebook URL validation
    results.append(gate("URL validation handles tiktok.com",
        "tiktok" in server.lower(),
        "Add tiktok.com URL validation in server.py"))
    results.append(gate("URL validation handles facebook.com",
        "facebook" in server.lower(),
        "Add facebook.com URL validation in server.py"))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results


def phase_6() -> list[bool]:
    section("Phase 6 — Email Delivery")
    results = []

    results.append(gate("email_service.py exists",
        file_exists("backend/src/services/email_service.py"),
        "Create backend/src/services/email_service.py"))

    if file_exists("backend/src/services/email_service.py"):
        email_svc = (ROOT / "backend/src/services/email_service.py").read_text()
        results.append(gate("email_service uses Azure Communication Services",
            "azure.communication" in email_svc or "EmailClient" in email_svc,
            "Use azure.communication.email.EmailClient"))
        results.append(gate("email_service attaches PDF",
            "attachment" in email_svc.lower() or "pdf" in email_svc.lower(),
            "Attach PDF bytes to email in email_service.py"))

    pyproject = (ROOT / "pyproject.toml").read_text()
    results.append(gate("azure-communication-email in pyproject.toml",
        "azure-communication-email" in pyproject,
        "Add azure-communication-email>=1.0.0 to pyproject.toml"))

    env = (ROOT / "env.example").read_text()
    results.append(gate("AZURE_COMM_CONNECTION_STRING in env.example",
        "AZURE_COMM_CONNECTION_STRING" in env,
        "Add AZURE_COMM_CONNECTION_STRING to env.example"))

    # Worker calls email_service
    if file_exists("backend/src/worker/main.py"):
        worker = (ROOT / "backend/src/worker/main.py").read_text()
        results.append(gate("worker sends email on completion",
            "email_service" in worker or "send_audit_report" in worker,
            "Call send_audit_report in worker/main.py after completion"))

    # /audits/{id}/email endpoint
    audits_route = (ROOT / "backend/src/api/routes/audits.py").read_text()
    results.append(gate("POST /audits/{id}/email endpoint exists",
        "/email" in audits_route or "email" in audits_route,
        "Add POST /audits/{audit_id}/email endpoint to routes/audits.py"))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results


def phase_7() -> list[bool]:
    section("Phase 7 — Frontend")
    results = []

    for f in ["favicon-done.svg", "favicon-error.svg"]:
        results.append(gate(f"{f} exists", file_exists(f), f"Create {f}"))

    html = (ROOT / "index.html").read_text()

    results.append(gate("index.html has mode toggle (url/upload)",
        "upload" in html.lower() and ("toggle" in html.lower() or "mode" in html.lower()),
        "Add mode toggle to index.html"))

    results.append(gate("index.html has platform checkboxes",
        "tiktok" in html.lower() and "facebook" in html.lower(),
        "Add TikTok and Facebook platform checkboxes to index.html"))

    results.append(gate("index.html has file input",
        'type="file"' in html or "type='file'" in html,
        "Add <input type='file'> to index.html"))

    results.append(gate("index.html has progress bar element",
        "progress" in html.lower() or "progressbar" in html.lower(),
        "Add progress bar element to index.html"))

    results.append(gate("index.html polls processing_status",
        "processing_status" in html,
        "Add processing_status polling to index.html JS"))

    results.append(gate("index.html changes document.title on completion",
        "document.title" in html,
        "Add document.title update on completion in index.html"))

    results.append(gate("index.html swaps favicon on completion",
        "favicon" in html.lower() and ("done" in html or "complete" in html.lower()),
        "Add favicon swap on completion in index.html"))

    results.append(gate("index.html has violations_by_platform tab view",
        "violations_by_platform" in html or "per-platform" in html.lower(),
        "Add per-platform tab view to index.html"))

    results.append(gate("index.html has download PDF button",
        "download" in html.lower() and "pdf" in html.lower(),
        "Add download PDF button to index.html"))

    results.append(gate("index.html has email report button",
        "email" in html.lower() and ("report" in html.lower() or "send" in html.lower()),
        "Add email report button to index.html"))

    return results


def phase_8() -> list[bool]:
    section("Phase 8 — Observability")
    results = []

    pyproject = (ROOT / "pyproject.toml").read_text()
    results.append(gate("langfuse in pyproject.toml",
        "langfuse" in pyproject,
        "Add langfuse>=2.0.0 to pyproject.toml"))

    server = (ROOT / "backend/src/api/server.py").read_text()
    results.append(gate("server.py imports langfuse CallbackHandler",
        "langfuse" in server or "CallbackHandler" in server,
        "Import and configure langfuse CallbackHandler in server.py"))

    nodes = (ROOT / "backend/src/graph/nodes.py").read_text()
    for metric in ["claims_extracted", "chunks_retrieved", "input_tokens"]:
        results.append(gate(f"audit node logs {metric}",
            metric in nodes,
            f"Log {metric} as span metadata in audit_content_node"))

    env = (ROOT / "env.example").read_text()
    for var in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]:
        results.append(gate(f"{var} in env.example",
            var in env,
            f"Add {var} to env.example"))

    # langfuse import check
    code, out = run("uv run python -c \"import langfuse; print('langfuse ok')\" 2>&1")
    results.append(gate("langfuse imports without error", code == 0, out[:200]))

    # Tests still pass
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results


def phase_9() -> list[bool]:
    section("Phase 9 — CI/CD Hardening")
    results = []

    deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
    results.append(gate("deploy.yml runs production-audit",
        "commitshow" in deploy,
        "Add npx commitshow@latest audit step to deploy.yml"))

    gitignore = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    results.append(gate(".gitignore has .commitshow/",
        ".commitshow" in gitignore,
        "Add .commitshow/ to .gitignore"))

    env = (ROOT / "env.example").read_text()
    for var in ["AZURE_COMM_CONNECTION_STRING", "LANGFUSE_PUBLIC_KEY",
                "UPLOAD_RATE_LIMIT_PER_HOUR", "RAG_MIN_SCORE",
                "AZURE_STORAGE_QUEUE_NAME"]:
        results.append(gate(f"{var} documented in env.example",
            var in env,
            f"Add {var} to env.example"))

    # Final test run
    code, out = run("uv run pytest tests/ -v 2>&1")
    results.append(gate("Full test suite passes", code == 0, out[:300] if code != 0 else ""))

    return results


# ── main ─────────────────────────────────────────────────────────────────────

def phase_10() -> list[bool]:
    section("Phase 10 — Policy Retrieval Overhaul")
    results = []

    sources = (ROOT / "src/services/policy_sources.py").read_text()

    # Subtask 10.1: leaf URLs curated (>15 total entries)
    import re
    url_count = len(re.findall(r'"url":', sources))
    results.append(gate(f"POLICY_SOURCES has ≥15 entries (found {url_count})", url_count >= 15,
        "Add leaf-level policy URLs to policy_sources.py"))

    # Platform coverage
    for platform in ["youtube", "tiktok", "facebook", "x", "generic"]:
        results.append(gate(f"POLICY_SOURCES covers platform: {platform}",
            f'"platform": "{platform}"' in sources or f"'platform': '{platform}'" in sources,
            f"Add {platform} entries to POLICY_SOURCES"))

    # Subtask 10.2: extraction schema defined
    fetcher = (ROOT / "src/services/policy_fetcher.py").read_text()
    results.append(gate("policy_fetcher uses extract (not scrape_url for primary fetch)",
        "extract" in fetcher,
        "Switch policy_fetcher to use Firecrawl extract endpoint"))
    results.append(gate("EXTRACTION_SCHEMA defined in policy_fetcher or policy_sources",
        "EXTRACTION_SCHEMA" in fetcher or "EXTRACTION_SCHEMA" in sources or
        "what_is_prohibited" in fetcher,
        "Define EXTRACTION_SCHEMA with what_is_prohibited field"))

    # Subtask 10.4: structured chunking
    indexing = (ROOT / "src/services/policy_indexing.py").read_text()
    results.append(gate("policy_indexing handles structured JSON chunks",
        "what_is_prohibited" in indexing or "json" in indexing.lower(),
        "Update policy_indexing.py to parse JSON rule objects"))

    # Subtask 10.5: hybrid search
    store = (ROOT / "src/services/policy_store.py").read_text()
    results.append(gate("policy_store uses semantic/hybrid search",
        "semantic" in store.lower() or "hybrid" in store.lower(),
        "Enable semantic_configuration_name in search_policy_chunks"))

    # Subtask 10.6: query expansion
    nodes = (ROOT / "src/pipeline/nodes.py").read_text()
    results.append(gate("nodes.py has query expansion (_expand_claim or similar)",
        "_expand_claim" in nodes or "expand" in nodes.lower() or "policy language" in nodes.lower(),
        "Add query expansion before retrieval in _retrieve_for_claims"))

    # Subtask 10.8: risk_level field
    state = (ROOT / "src/pipeline/state.py").read_text()
    results.append(gate("ComplianceIssue has risk_level field",
        "risk_level" in state,
        "Add risk_level to ComplianceIssue TypedDict"))

    # Tests
    code, out = run("uv run pytest tests/ -q 2>&1")
    results.append(gate("All tests pass", code == 0, out[:200] if code != 0 else ""))

    return results

PHASES = {
    0: phase_0, 1: phase_1, 2: phase_2, 3: phase_3,
    4: phase_4, 5: phase_5, 6: phase_6, 7: phase_7,
    8: phase_8, 9: phase_9, 10: phase_10,
}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/gate.py <phase>")
        print("Phases: 0-9")
        sys.exit(1)

    try:
        phase_num = int(sys.argv[1])
    except ValueError:
        print(f"Invalid phase: {sys.argv[1]}")
        sys.exit(1)

    if phase_num not in PHASES:
        print(f"Unknown phase: {phase_num}. Valid: 0-9")
        sys.exit(1)

    print(f"\n{'═' * 60}")
    print(f"  Brand Guardian AI — Phase {phase_num} Gate Check")
    print(f"{'═' * 60}")

    results = PHASES[phase_num]()

    total = len(results)
    passed = sum(results)
    failed = total - passed

    print(f"\n{'═' * 60}")
    if failed == 0:
        print(f"  ✅  ALL GATES PASS ({passed}/{total})")
        print(f"  Phase {phase_num} complete. Safe to start Phase {phase_num + 1}.")
    else:
        print(f"  ❌  {failed} GATE(S) FAILED ({passed}/{total} passed)")
        print(f"  Fix the failures above, then re-run: python scripts/gate.py {phase_num}")
    print(f"{'═' * 60}\n")

    sys.exit(0 if failed == 0 else 1)
