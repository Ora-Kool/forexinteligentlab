import inspect
from functools import wraps

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_token_payload
from app.core.tenant import SYSTEM_WORKSPACE_ID, set_workspace_id

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    subject: str
    workspace_id: int


def current_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    token: str | None = Query(default=None),
) -> Principal:
    settings = get_settings()
    x_saas_key = request.headers.get("x-saas-key")
    x_workspace_id = request.headers.get("x-workspace-id")
    if x_saas_key:
        if x_saas_key != settings.saas_api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid SaaS key")
        try:
            workspace_id = int(x_workspace_id) if x_workspace_id not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace")
        if workspace_id is None or workspace_id < 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace id required")
        set_workspace_id(workspace_id)
        return Principal(subject=f"workspace:{workspace_id}", workspace_id=workspace_id)

    raw = creds.credentials if creds else token
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token_payload(raw)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    workspace_id = int(payload.get("workspace_id") or SYSTEM_WORKSPACE_ID)
    set_workspace_id(workspace_id)
    return Principal(subject=str(payload["sub"]), workspace_id=workspace_id)


def current_username(principal: Principal = Depends(current_principal)) -> Principal:
    return principal


def with_tenant(endpoint):
    @wraps(endpoint)
    def wrapped(*args, **kwargs):
        for value in kwargs.values():
            if isinstance(value, Principal):
                set_workspace_id(value.workspace_id)
                break
        return endpoint(*args, **kwargs)

    wrapped.__signature__ = inspect.signature(endpoint)
    return wrapped


class TenantRouter(APIRouter):
    def add_api_route(self, path: str, endpoint, **kwargs):
        super().add_api_route(path, with_tenant(endpoint), **kwargs)


def require_agent_key(x_agent_key: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if not x_agent_key or x_agent_key != settings.agent_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent API key")
    set_workspace_id(SYSTEM_WORKSPACE_ID)
    return x_agent_key


def require_saas_key(request: Request) -> int:
    settings = get_settings()
    x_saas_key = request.headers.get("x-saas-key")
    x_workspace_id = request.headers.get("x-workspace-id")
    if not x_saas_key or x_saas_key != settings.saas_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid SaaS key")
    try:
        workspace_id = int(x_workspace_id) if x_workspace_id not in (None, "") else 0
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace")
    if workspace_id < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace id required")
    set_workspace_id(workspace_id)
    return workspace_id


DbSession = Session
