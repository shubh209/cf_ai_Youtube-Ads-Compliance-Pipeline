import uuid

from sqlalchemy.orm import Session

from backend.src.auth.models import UserContext
from backend.src.db.repository import apply_review_decision, get_audit_for_team


def submit_review(
    db: Session,
    *,
    audit_id: uuid.UUID,
    user: UserContext,
    decision: str,
    notes: str | None,
):
    if decision.upper() not in ("PASS", "FAIL"):
        raise ValueError("decision must be PASS or FAIL")

    audit = get_audit_for_team(db, audit_id, user.team_id)
    if audit is None:
        raise LookupError("Audit not found")

    return apply_review_decision(
        db,
        audit=audit,
        reviewer_id=user.user_id,
        decision=decision,
        notes=notes,
    )
