"""Per-organisation API keys. Every org-scoped route must depend on `require_org`."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from travel_risk.config import get_settings
from travel_risk.db import get_session
from travel_risk.models import Organisation


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_api_key() -> str:
    return "tra_" + secrets.token_urlsafe(32)


def require_org(
    org_id: int,
    session: Annotated[Session, Depends(get_session)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> Organisation:
    """Resolve the caller's organisation from its key and insist it matches the path."""
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-API-Key")
    org = session.scalars(
        select(Organisation).where(Organisation.api_key_hash == hash_key(x_api_key))
    ).first()
    # 404, not 403, so a caller can't probe which org ids exist.
    if org is None or org.id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "organisation not found")
    return org


def require_operator(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().operator_api_key.get_secret_value()
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "operator key required")
