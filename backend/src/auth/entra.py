import logging
import os
import time
from typing import Any

import jwt
from jwt import PyJWKClient

logger = logging.getLogger("brand-guardian-auth")

_jwks_client: PyJWKClient | None = None
_jwks_client_created_at: float = 0.0
_JWKS_TTL_SECONDS = 3600


def _auth_disabled() -> bool:
    return os.getenv("AUTH_DISABLED", "false").lower() in ("1", "true", "yes")


def _tenant_id() -> str:
    tenant_id = os.getenv("ENTRA_TENANT_ID", "").strip()
    if not tenant_id and not _auth_disabled():
        raise RuntimeError("ENTRA_TENANT_ID is required when AUTH_DISABLED is false")
    return tenant_id


def _client_id() -> str:
    client_id = os.getenv("ENTRA_CLIENT_ID", "").strip()
    if not client_id and not _auth_disabled():
        raise RuntimeError("ENTRA_CLIENT_ID is required when AUTH_DISABLED is false")
    return client_id


def _authority() -> str:
    explicit = os.getenv("ENTRA_AUTHORITY", "").strip()
    if explicit:
        return explicit.rstrip("/")
    return f"https://login.microsoftonline.com/{_tenant_id()}/v2.0"


def _issuer() -> str:
    return f"{_authority()}/"


def _jwks_uri() -> str:
    return f"{_authority()}/discovery/v2.0/keys"


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_client_created_at
    now = time.time()
    if _jwks_client is None or (now - _jwks_client_created_at) > _JWKS_TTL_SECONDS:
        _jwks_client = PyJWKClient(_jwks_uri())
        _jwks_client_created_at = now
    return _jwks_client


def decode_entra_token(token: str) -> dict[str, Any]:
    if _auth_disabled():
        raise RuntimeError("decode_entra_token should not be called when AUTH_DISABLED is true")

    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    audience = os.getenv("ENTRA_API_AUDIENCE", _client_id()).strip() or _client_id()

    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=_issuer(),
        options={"require": ["exp", "iss", "aud", "sub"]},
    )


def extract_email(claims: dict[str, Any]) -> str | None:
    return claims.get("preferred_username") or claims.get("email") or claims.get("upn")


def extract_entra_oid(claims: dict[str, Any]) -> str:
    oid = claims.get("oid") or claims.get("sub")
    if not oid:
        raise ValueError("Token missing oid/sub claim")
    return str(oid)


def map_role_from_claims(claims: dict[str, Any]) -> str:
    roles = claims.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]

    admin_role = os.getenv("ENTRA_ADMIN_ROLE", "Admin")
    reviewer_role = os.getenv("ENTRA_REVIEWER_ROLE", "Reviewer")
    read_only_role = os.getenv("ENTRA_READ_ONLY_ROLE", "ReadOnly")

    normalized = {str(role) for role in roles}
    if admin_role in normalized:
        return "admin"
    if reviewer_role in normalized:
        return "reviewer"
    if read_only_role in normalized:
        return "read_only"

    default_role = os.getenv("ENTRA_DEFAULT_ROLE", "reviewer").strip().lower()
    if default_role not in ("admin", "reviewer", "read_only"):
        return "reviewer"
    return default_role


def validate_token_header(authorization: str | None) -> str:
    if not authorization:
        raise ValueError("Missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Authorization header must use Bearer scheme")
    token = parts[1].strip()
    if not token:
        raise ValueError("Bearer token is empty")
    return token
