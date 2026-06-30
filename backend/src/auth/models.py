import uuid
from dataclasses import dataclass

from backend.src.db.models import UserRole


@dataclass(frozen=True)
class UserContext:
    user_id: uuid.UUID
    team_id: uuid.UUID
    entra_oid: str
    email: str | None
    role: UserRole

    def can_submit_audit(self) -> bool:
        return self.role in (UserRole.admin, UserRole.reviewer)

    def can_review(self) -> bool:
        return self.role in (UserRole.admin, UserRole.reviewer)

    def is_admin(self) -> bool:
        return self.role == UserRole.admin
