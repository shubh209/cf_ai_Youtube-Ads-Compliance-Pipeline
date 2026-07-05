"""New architecture: processing_status, audit_mode, platforms, violation platform."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_new_architecture"
down_revision: Union[str, None] = "002_team_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audits", sa.Column("processing_status", sa.String(32), nullable=True))
    op.add_column("audits", sa.Column("audit_mode", sa.String(8), nullable=True))
    op.add_column("audits", sa.Column("platforms", sa.Text(), nullable=True))
    op.create_index("ix_audits_processing_status", "audits", ["processing_status"])

    op.add_column("audit_violations", sa.Column("platform", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_violations", "platform")

    op.drop_index("ix_audits_processing_status", table_name="audits")
    op.drop_column("audits", "platforms")
    op.drop_column("audits", "audit_mode")
    op.drop_column("audits", "processing_status")
