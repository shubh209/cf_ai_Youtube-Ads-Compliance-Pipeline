import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.routes.admin import router as admin_router
from src.api.routes.audits import router as audits_router
from src.api.routes.export import router as export_router
from src.api.routes.reviews import router as reviews_router
from src.api.telemetry import setup_telemetry
from src.auth.dependencies import get_current_user, require_audit_submitter
from src.auth.models import UserContext
from src.db.repository import get_current_policy_version, save_audit
from src.db.session import SessionLocal, get_db
from src.pipeline.workflow import app as compliance_graph
from src.middleware.rate_limit import RateLimitMiddleware
from src.services.export import DISCLAIMER

setup_telemetry()

logging.basicConfig(level=logging.INFO)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.monitor").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logger = logging.getLogger("api-server")


def _parse_allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["http://localhost:8000"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("AUTH_DISABLED", "false").lower() in ("1", "true", "yes"):
        db = SessionLocal()
        try:
            from src.auth.dependencies import ensure_default_team

            ensure_default_team(db)
        except Exception as exc:
            logger.warning("Startup bootstrap skipped (database unavailable): %s", exc)
        finally:
            db.close()
    yield


app = FastAPI(
    title="Brand Guardian AI API",
    description="Audits YouTube ad content against YouTube Ad Policies and FTC guidelines.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audits_router)
app.include_router(reviews_router)
app.include_router(admin_router)
app.include_router(export_router)


class AuditRequest(BaseModel):
    video_url: str


class ComplianceIssue(BaseModel):
    category: str
    severity: str
    description: str
    citation_source: str | None = None
    citation_excerpt: str | None = None
    chunk_id: str | None = None
    confidence: str | None = None


class AuditResponse(BaseModel):
    audit_id: str | None = None
    session_id: str
    video_id: str
    status: str
    final_status: str
    ai_status: str
    final_report: str
    ingestion_source: str | None = None
    compliance_results: List[ComplianceIssue]
    disclaimer: str = DISCLAIMER


class AuthMeResponse(BaseModel):
    user_id: str
    team_id: str
    email: str | None
    role: str


@app.post("/audit", response_model=AuditResponse)
async def audit_video(
    request: AuditRequest,
    user: UserContext = Depends(require_audit_submitter),
    db: Session = Depends(get_db),
):
    session_id = str(uuid.uuid4())
    video_id_short = f"vid_{session_id[:8]}"

    logger.info(
        "Audit request url=%s session=%s user=%s team=%s",
        request.video_url,
        session_id,
        user.user_id,
        user.team_id,
    )

    if "youtube.com" not in request.video_url and "youtu.be" not in request.video_url:
        raise HTTPException(status_code=400, detail="Only YouTube URLs are supported.")

    initial_inputs = {
        "video_url": request.video_url,
        "video_id": video_id_short,
        "compliance_results": [],
        "errors": [],
    }

    try:
        final_state = await compliance_graph.ainvoke(initial_inputs)
        ai_status = final_state.get("final_status", "UNKNOWN")
        compliance_results = final_state.get("compliance_results", [])
        ingestion_source = final_state.get("ingestion_source")

        policy_version = get_current_policy_version(db)
        policy_version_id = policy_version.id if policy_version else None

        audit_id = None
        try:
            audit = save_audit(
                db,
                team_id=user.team_id,
                user_id=user.user_id,
                session_id=session_id,
                video_url=request.video_url,
                video_id=final_state.get("video_id", video_id_short),
                ai_status=ai_status,
                final_report=final_state.get("final_report", "No report generated."),
                compliance_results=compliance_results,
                policy_version_id=policy_version_id,
                ingestion_source=ingestion_source,
                raw_response={
                    "compliance_results": compliance_results,
                    "final_status": ai_status,
                    "final_report": final_state.get("final_report"),
                    "ingestion_source": ingestion_source,
                },
            )
            audit_id = str(audit.id)
        except Exception as db_exc:
            logger.warning("Audit persistence skipped (database unavailable): %s", db_exc)

        return AuditResponse(
            audit_id=audit_id,
            session_id=session_id,
            video_id=audit.video_id,
            status=audit.final_status,
            final_status=audit.final_status,
            ai_status=audit.ai_status,
            final_report=audit.final_report,
            ingestion_source=audit.ingestion_source,
            compliance_results=compliance_results,
        )

    except Exception as exc:
        logger.error("Audit failed session=%s error=%s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {exc}") from exc


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Brand Guardian AI", "version": "3.0.0"}


@app.get("/auth/me", response_model=AuthMeResponse)
def auth_me(user: UserContext = Depends(get_current_user)):
    return AuthMeResponse(
        user_id=str(user.user_id),
        team_id=str(user.team_id),
        email=user.email,
        role=user.role.value,
    )


@app.get("/")
def serve_frontend():
    return FileResponse("frontend/index.html")


@app.get("/admin")
def serve_admin():
    return FileResponse("frontend/admin.html")
