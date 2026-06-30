import logging
import os
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.src.auth.api_keys import authenticate_api_key
from backend.src.auth.entra import (
    decode_entra_token,
    extract_email,
    extract_entra_oid,
    map_role_from_claims,
    validate_token_header,
)
from backend.src.auth.models import UserContext
from backend.src.db.models import Team, User, UserRole
from backend.src.db.session import get_db

logger = logging.getLogger("brand-guardian-auth")
bearer_scheme = HTTPBearer(auto_error=False)


def _auth_disabled() -> bool:
    return os.getenv("AUTH_DISABLED", "false").lower() in ("1", "true", "yes")


def ensure_default_team(db: Session) -> Team:
    team_name = os.getenv("DEFAULT_TEAM_NAME", "Default Team").strip() or "Default Team"
    team = db.query(Team).filter(Team.name == team_name).one_or_none()
    if team is None:
        team = Team(name=team_name)
        db.add(team)
        db.commit()
        db.refresh(team)
        logger.info("Created default team: %s", team_name)
    return team


def _dev_user_context(db: Session) -> UserContext:
    team = ensure_default_team(db)
    dev_oid = os.getenv("DEV_ENTRA_OID", "local-dev-user")
    user = db.query(User).filter(User.entra_oid == dev_oid).one_or_none()
    if user is None:
        user = User(
            entra_oid=dev_oid,
            email=os.getenv("DEV_USER_EMAIL", "dev@localhost"),
            team_id=team.id,
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return UserContext(
        user_id=user.id,
        team_id=user.team_id,
        entra_oid=user.entra_oid,
        email=user.email,
        role=user.role,
    )


def _upsert_user(db: Session, entra_oid: str, email: str | None, role_name: str) -> UserContext:
    role = UserRole(role_name)
    user = db.query(User).filter(User.entra_oid == entra_oid).one_or_none()

    if user is None:
        team = ensure_default_team(db)
        user = User(entra_oid=entra_oid, email=email, team_id=team.id, role=role)
        db.add(user)
    else:
        user.email = email or user.email
        user.role = role

    db.commit()
    db.refresh(user)
    return UserContext(
        user_id=user.id,
        team_id=user.team_id,
        entra_oid=user.entra_oid,
        email=user.email,
        role=user.role,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> UserContext:
    if _auth_disabled():
        return _dev_user_context(db)

    if x_api_key:
        user = authenticate_api_key(db, x_api_key)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        return UserContext(
            user_id=user.id,
            team_id=user.team_id,
            entra_oid=user.entra_oid,
            email=user.email,
            role=user.role,
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token = validate_token_header(f"Bearer {credentials.credentials}")
        claims = decode_entra_token(token)
        entra_oid = extract_entra_oid(claims)
        email = extract_email(claims)
        role_name = map_role_from_claims(claims)
        return _upsert_user(db, entra_oid, email, role_name)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Authentication failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_audit_submitter(user: UserContext = Depends(get_current_user)) -> UserContext:
    if not user.can_submit_audit():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Read only users cannot submit audits",
        )
    return user


def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


def require_reviewer(user: UserContext = Depends(get_current_user)) -> UserContext:
    if not user.can_review():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer or admin role required",
        )
    return user
