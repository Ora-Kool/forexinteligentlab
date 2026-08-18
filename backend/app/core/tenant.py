from contextvars import ContextVar

from sqlalchemy.orm import Query

SYSTEM_WORKSPACE_ID = 0

_workspace_id: ContextVar[int] = ContextVar("workspace_id", default=SYSTEM_WORKSPACE_ID)


def current_workspace_id() -> int:
    return _workspace_id.get()


def set_workspace_id(workspace_id: int | None) -> int:
    value = SYSTEM_WORKSPACE_ID if workspace_id is None else int(workspace_id)
    _workspace_id.set(value)
    return value


def research_ids() -> list[int]:
    workspace_id = current_workspace_id()
    if workspace_id == SYSTEM_WORKSPACE_ID:
        return [SYSTEM_WORKSPACE_ID]
    return [workspace_id, SYSTEM_WORKSPACE_ID]


def own(query: Query, model, workspace_id: int | None = None) -> Query:
    return query.filter(model.workspace_id == (current_workspace_id() if workspace_id is None else workspace_id))


def visible(query: Query, model) -> Query:
    return query.filter(model.workspace_id.in_(research_ids()))
