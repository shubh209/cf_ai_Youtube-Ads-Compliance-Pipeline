import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from src.db.models import Audit, AuditViolation, PolicyVersion, ReviewDecision


def get_current_policy_version(db: Session) -> PolicyVersion | None:
    return (
        db.query(PolicyVersion)
        .filter(PolicyVersion.is_current.is_(True))
        .order_by(PolicyVersion.indexed_at.desc())
        .first()
    )


def save_audit(
    db: Session,
    *,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: str,
    video_url: str,
    video_id: str,
    ai_status: str,
    final_report: str,
    compliance_results: list[dict],
    policy_version_id: uuid.UUID | None,
    ingestion_source: str | None,
    raw_response: dict | None,
) -> Audit:
    audit = Audit(
        team_id=team_id,
        user_id=user_id,
        session_id=session_id,
        video_url=video_url,
        video_id=video_id,
        ai_status=ai_status,
        final_status=ai_status,
        final_report=final_report,
        policy_version_id=policy_version_id,
        ingestion_source=ingestion_source,
        raw_response=raw_response,
    )
    db.add(audit)
    db.flush()

    for item in compliance_results:
        db.add(
            AuditViolation(
                audit_id=audit.id,
                category=item.get("category", "Unknown"),
                severity=item.get("severity", "INFO"),
                description=item.get("description", ""),
                citation_source=item.get("citation_source"),
                citation_excerpt=item.get("citation_excerpt"),
                chunk_id=item.get("chunk_id"),
            )
        )

    db.commit()
    db.refresh(audit)
    return audit


def list_audits_for_team(
    db: Session,
    team_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Audit]:
    return (
        db.query(Audit)
        .filter(Audit.team_id == team_id)
        .order_by(Audit.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_audit_for_team(db: Session, audit_id: uuid.UUID, team_id: uuid.UUID) -> Audit | None:
    return (
        db.query(Audit)
        .filter(Audit.id == audit_id, Audit.team_id == team_id)
        .first()
    )


def update_processing_status(db: Session, audit_id: str, status: str) -> None:
    db.query(Audit).filter(Audit.session_id == audit_id).update({"processing_status": status})
    db.commit()


def apply_review_decision(
    db: Session,
    *,
    audit: Audit,
    reviewer_id: uuid.UUID,
    decision: str,
    notes: str | None,
) -> ReviewDecision:
    review = ReviewDecision(
        audit_id=audit.id,
        reviewer_id=reviewer_id,
        decision=decision.upper(),
        notes=notes,
    )
    audit.final_status = decision.upper()
    db.add(review)
    db.commit()
    db.refresh(review)
    db.refresh(audit)
    return review
