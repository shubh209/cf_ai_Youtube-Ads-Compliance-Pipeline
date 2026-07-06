import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.auth.models import UserContext
from src.db.repository import get_audit_for_team, list_audits_for_team
from src.db.session import get_db

router = APIRouter(prefix="/audits", tags=["audits"])


class ViolationResponse(BaseModel):
    category: str
    severity: str
    description: str
    citation_source: str | None = None
    citation_excerpt: str | None = None
    chunk_id: str | None = None


class ReviewResponse(BaseModel):
    decision: str
    notes: str | None
    created_at: datetime


class AuditDetailResponse(BaseModel):
    id: str
    session_id: str
    video_url: str
    video_id: str
    ai_status: str
    final_status: str
    final_report: str
    ingestion_source: str | None
    policy_version_id: str | None
    created_at: datetime
    violations: list[ViolationResponse]
    reviews: list[ReviewResponse]


class AuditListItem(BaseModel):
    id: str
    session_id: str
    video_url: str
    ai_status: str
    final_status: str
    ingestion_source: str | None
    created_at: datetime


@router.get("", response_model=list[AuditListItem])
def list_audits(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audits = list_audits_for_team(db, user.team_id, limit=limit, offset=offset)
    return [
        AuditListItem(
            id=str(a.id),
            session_id=a.session_id,
            video_url=a.video_url,
            ai_status=a.ai_status,
            final_status=a.final_status,
            ingestion_source=a.ingestion_source,
            created_at=a.created_at,
        )
        for a in audits
    ]


@router.get("/{audit_id}", response_model=AuditDetailResponse)
def get_audit(
    audit_id: uuid.UUID,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit = get_audit_for_team(db, audit_id, user.team_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    return AuditDetailResponse(
        id=str(audit.id),
        session_id=audit.session_id,
        video_url=audit.video_url,
        video_id=audit.video_id,
        ai_status=audit.ai_status,
        final_status=audit.final_status,
        final_report=audit.final_report,
        ingestion_source=audit.ingestion_source,
        policy_version_id=str(audit.policy_version_id) if audit.policy_version_id else None,
        created_at=audit.created_at,
        violations=[
            ViolationResponse(
                category=v.category,
                severity=v.severity,
                description=v.description,
                citation_source=v.citation_source,
                citation_excerpt=v.citation_excerpt,
                chunk_id=v.chunk_id,
            )
            for v in audit.violations
        ],
        reviews=[
            ReviewResponse(decision=r.decision, notes=r.notes, created_at=r.created_at)
            for r in audit.reviews
        ],
    )
