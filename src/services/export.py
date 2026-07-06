import csv
import io
import uuid

from sqlalchemy.orm import Session

from src.db.models import Audit
from src.db.repository import get_audit_for_team

DISCLAIMER = (
    "Decision support only. This audit does not constitute legal advice. "
    "A qualified reviewer must confirm findings before publishing ads."
)


def _get_audit_or_raise(db: Session, audit_id: uuid.UUID, team_id: uuid.UUID) -> Audit:
    audit = get_audit_for_team(db, audit_id, team_id)
    if audit is None:
        raise LookupError("Audit not found")
    return audit


def export_audit_csv(db: Session, audit_id: uuid.UUID, team_id: uuid.UUID) -> bytes:
    audit = _get_audit_or_raise(db, audit_id, team_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["audit_id", "video_url", "ai_status", "final_status", "ingestion_source"])
    writer.writerow([str(audit.id), audit.video_url, audit.ai_status, audit.final_status, audit.ingestion_source or ""])
    writer.writerow([])
    writer.writerow(["category", "severity", "description", "citation_source", "citation_excerpt", "chunk_id"])
    for violation in audit.violations:
        writer.writerow([
            violation.category,
            violation.severity,
            violation.description,
            violation.citation_source or "",
            violation.citation_excerpt or "",
            violation.chunk_id or "",
        ])
    writer.writerow([])
    writer.writerow(["disclaimer", DISCLAIMER])
    return buffer.getvalue().encode("utf-8")


def export_audit_pdf(db: Session, audit_id: uuid.UUID, team_id: uuid.UUID) -> bytes:
    audit = _get_audit_or_raise(db, audit_id, team_id)
    lines = [
        "Brand Guardian AI — Compliance Audit Report",
        f"Audit ID: {audit.id}",
        f"Video URL: {audit.video_url}",
        f"AI Status: {audit.ai_status}",
        f"Final Status: {audit.final_status}",
        f"Ingestion Source: {audit.ingestion_source or 'unknown'}",
        "",
        "Summary:",
        audit.final_report,
        "",
        "Violations:",
    ]
    if not audit.violations:
        lines.append("None")
    for idx, violation in enumerate(audit.violations, start=1):
        lines.extend([
            f"{idx}. [{violation.severity}] {violation.category}",
            violation.description,
            f"   Citation: {violation.citation_source or 'n/a'}",
            f"   Excerpt: {violation.citation_excerpt or 'n/a'}",
            "",
        ])
    lines.extend(["", DISCLAIMER])
    return "\n".join(lines).encode("utf-8")
