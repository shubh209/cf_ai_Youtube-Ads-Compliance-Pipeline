import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.auth.dependencies import require_reviewer
from src.auth.models import UserContext
from src.db.session import get_db
from src.services.review import submit_review

router = APIRouter(prefix="/audits", tags=["reviews"])


class ReviewRequest(BaseModel):
    decision: str
    notes: str | None = None


class ReviewSubmitResponse(BaseModel):
    audit_id: str
    final_status: str
    decision: str
    notes: str | None


@router.post("/{audit_id}/review", response_model=ReviewSubmitResponse)
def post_review(
    audit_id: uuid.UUID,
    body: ReviewRequest,
    user: UserContext = Depends(require_reviewer),
    db: Session = Depends(get_db),
):
    try:
        review = submit_review(
            db,
            audit_id=audit_id,
            user=user,
            decision=body.decision,
            notes=body.notes,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Audit not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit = review.audit
    return ReviewSubmitResponse(
        audit_id=str(audit.id),
        final_status=audit.final_status,
        decision=review.decision,
        notes=review.notes,
    )
