import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.src.auth.dependencies import get_current_user
from backend.src.auth.models import UserContext
from backend.src.db.session import get_db
from backend.src.services.export import export_audit_csv, export_audit_pdf

router = APIRouter(prefix="/audits", tags=["export"])


@router.get("/{audit_id}/export")
def export_audit(
    audit_id: uuid.UUID,
    format: str = "csv",
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if format == "csv":
            content = export_audit_csv(db, audit_id, user.team_id)
            media_type = "text/csv"
            filename = f"audit-{audit_id}.csv"
        elif format == "pdf":
            content = export_audit_pdf(db, audit_id, user.team_id)
            media_type = "application/pdf"
            filename = f"audit-{audit_id}.pdf"
        else:
            raise HTTPException(status_code=400, detail="format must be csv or pdf")
    except LookupError:
        raise HTTPException(status_code=404, detail="Audit not found") from None

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
