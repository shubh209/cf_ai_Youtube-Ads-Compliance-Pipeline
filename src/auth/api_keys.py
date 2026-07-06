import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.db.models import TeamApiKey, User, UserRole


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key(db: Session, team_id: uuid.UUID, name: str) -> tuple[str, TeamApiKey]:
    raw_key = f"bg_{secrets.token_urlsafe(32)}"
    record = TeamApiKey(
        team_id=team_id,
        name=name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return raw_key, record


def revoke_api_key(db: Session, key_id: uuid.UUID, team_id: uuid.UUID) -> bool:
    record = (
        db.query(TeamApiKey)
        .filter(TeamApiKey.id == key_id, TeamApiKey.team_id == team_id, TeamApiKey.is_active.is_(True))
        .one_or_none()
    )
    if record is None:
        return False
    record.is_active = False
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return True


def authenticate_api_key(db: Session, raw_key: str) -> User | None:
    if not raw_key.startswith("bg_"):
        return None
    key_hash = hash_api_key(raw_key)
    record = (
        db.query(TeamApiKey)
        .filter(TeamApiKey.key_hash == key_hash, TeamApiKey.is_active.is_(True))
        .one_or_none()
    )
    if record is None:
        return None
    service_user = (
        db.query(User)
        .filter(User.team_id == record.team_id, User.entra_oid == f"api-key-{record.id}")
        .one_or_none()
    )
    if service_user is None:
        service_user = User(
            entra_oid=f"api-key-{record.id}",
            email=f"apikey+{record.key_prefix}@internal.local",
            team_id=record.team_id,
            role=UserRole.reviewer,
        )
        db.add(service_user)
        db.commit()
        db.refresh(service_user)
    return service_user
