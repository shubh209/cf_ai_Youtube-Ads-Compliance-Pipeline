"""Initial schema for internal tool upgrade."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = postgresql.ENUM("admin", "reviewer", "read_only", name="user_role", create_type=True)


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    user_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entra_oid", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_users_entra_oid", "users", ["entra_oid"], unique=True)
    op.create_index("ix_users_team_id", "users", ["team_id"])

    op.create_table(
        "policy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_label", sa.String(length=128), nullable=False, unique=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("video_url", sa.Text(), nullable=False),
        sa.Column("video_id", sa.String(length=64), nullable=False),
        sa.Column("ai_status", sa.String(length=32), nullable=False),
        sa.Column("final_status", sa.String(length=32), nullable=False),
        sa.Column("final_report", sa.Text(), nullable=False, server_default=""),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policy_versions.id"), nullable=True),
        sa.Column("ingestion_source", sa.String(length=64), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audits_team_id", "audits", ["team_id"])
    op.create_index("ix_audits_user_id", "audits", ["user_id"])
    op.create_index("ix_audits_team_created", "audits", ["team_id", "created_at"])

    op.create_table(
        "audit_violations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("audits.id"), nullable=False),
        sa.Column("category", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("citation_source", sa.String(length=255), nullable=True),
        sa.Column("citation_excerpt", sa.Text(), nullable=True),
        sa.Column("chunk_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_audit_violations_audit_id", "audit_violations", ["audit_id"])

    op.create_table(
        "review_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("audits.id"), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_review_decisions_audit_id", "review_decisions", ["audit_id"])


def downgrade() -> None:
    op.drop_index("ix_review_decisions_audit_id", table_name="review_decisions")
    op.drop_table("review_decisions")
    op.drop_index("ix_audit_violations_audit_id", table_name="audit_violations")
    op.drop_table("audit_violations")
    op.drop_index("ix_audits_team_created", table_name="audits")
    op.drop_index("ix_audits_user_id", table_name="audits")
    op.drop_index("ix_audits_team_id", table_name="audits")
    op.drop_table("audits")
    op.drop_table("policy_versions")
    op.drop_index("ix_users_team_id", table_name="users")
    op.drop_index("ix_users_entra_oid", table_name="users")
    op.drop_table("users")
    op.drop_table("teams")
    user_role.drop(op.get_bind(), checkfirst=True)
