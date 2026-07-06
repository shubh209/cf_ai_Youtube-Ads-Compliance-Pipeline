"""Phase 9: CI/CD hardening tests."""
from pathlib import Path

DEPLOY_YML = Path(".github/workflows/deploy.yml").read_text()
GITIGNORE = Path(".gitignore").read_text()
ENV_EXAMPLE = Path("env.example").read_text()

REQUIRED_ENV_KEYS = [
    "AZURE_COMM_CONNECTION_STRING",
    "EMAIL_SENDER",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "AZURE_STORAGE_QUEUE_NAME",
    "AZURE_STORAGE_CONTAINER",
    "AZURE_AI_VISION_ENDPOINT",
    "AZURE_AI_VISION_KEY",
    "AZURE_OPENAI_MINI_DEPLOYMENT",
    "UPLOAD_RATE_LIMIT_PER_HOUR",
    "RAG_MIN_SCORE",
    "FIRECRAWL_API_KEY",
    "POLICY_CACHE_CONTAINER",
    "RERANKER_MODEL",
]


def test_deploy_workflow_builds_api_image():
    assert "brand-guardian-api" in DEPLOY_YML


def test_deploy_workflow_builds_worker_image():
    assert "brand-guardian-worker" in DEPLOY_YML
    assert "Dockerfile.worker" in DEPLOY_YML


def test_dockerfile_worker_exists():
    assert Path("Dockerfile.worker").exists()


def test_gitignore_has_commitshow():
    assert ".commitshow" in GITIGNORE


def test_env_example_complete():
    missing = [k for k in REQUIRED_ENV_KEYS if k not in ENV_EXAMPLE]
    assert missing == [], f"Missing from env.example: {missing}"
