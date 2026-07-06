import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.auth.api_keys import generate_api_key, revoke_api_key
from src.auth.dependencies import require_admin
from src.auth.models import UserContext
from src.db.models import PolicyVersion, TeamApiKey
from src.db.session import get_db
from src.services.policy_indexing import run_policy_index

router = APIRouter(prefix="/admin", tags=["admin"])


class PolicyVersionResponse(BaseModel):
    id: str
    version_label: str
    chunk_count: int
    is_current: bool


class ReindexResponse(BaseModel):
    version_label: str
    chunk_count: int
    policy_version_id: str | None


class ApiKeyCreateRequest(BaseModel):
    name: str


class ApiKeyCreateResponse(BaseModel):
    id: str
    name: str
    api_key: str
    key_prefix: str


class ApiKeyListItem(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_active: bool


@router.get("/policies/versions", response_model=list[PolicyVersionResponse])
def list_policy_versions(
    user: UserContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    versions = db.query(PolicyVersion).order_by(PolicyVersion.indexed_at.desc()).limit(20).all()
    return [
        PolicyVersionResponse(
            id=str(v.id),
            version_label=v.version_label,
            chunk_count=v.chunk_count,
            is_current=v.is_current,
        )
        for v in versions
    ]


@router.post("/policies/reindex", response_model=ReindexResponse)
def reindex_policies(
    user: UserContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        result = run_policy_index(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reindex failed: {exc}") from exc

    return ReindexResponse(
        version_label=result["version_label"],
        chunk_count=result["chunk_count"],
        policy_version_id=result.get("policy_version_id"),
    )


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
def create_api_key(
    body: ApiKeyCreateRequest,
    user: UserContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    raw_key, record = generate_api_key(db, user.team_id, body.name)
    return ApiKeyCreateResponse(
        id=str(record.id),
        name=record.name,
        api_key=raw_key,
        key_prefix=record.key_prefix,
    )


@router.get("/api-keys", response_model=list[ApiKeyListItem])
def list_api_keys(
    user: UserContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    keys = (
        db.query(TeamApiKey)
        .filter(TeamApiKey.team_id == user.team_id)
        .order_by(TeamApiKey.created_at.desc())
        .all()
    )
    return [
        ApiKeyListItem(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            is_active=k.is_active,
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}")
def revoke_team_api_key(
    key_id: uuid.UUID,
    user: UserContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not revoke_api_key(db, key_id, user.team_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked"}
