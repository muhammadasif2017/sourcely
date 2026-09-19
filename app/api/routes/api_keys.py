"""API key routes: create, list and revoke. Admins and the owner, signed in, only."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.auth import MemberDep, require
from app.api.deps import DbDep
from app.core.errors import AppError
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyList, ApiKeyOut
from app.services import api_keys

router = APIRouter(tags=["api keys"])


@router.post(
    "/workspaces/{workspace_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_api_key(body: ApiKeyCreate, member: MemberDep, db: DbDep) -> ApiKeyCreated:
    """Create a key. The full key is in this response only; store it now."""
    require(member, "manage")
    if member.user_id is None:
        raise AppError(status.HTTP_403_FORBIDDEN, "Only a signed-in admin can create API keys")
    created = api_keys.create_key(db, member.workspace_id, body.name, member.user_id)
    return ApiKeyCreated(
        id=created.row.id,
        name=created.row.name,
        prefix=created.row.prefix,
        key=created.key,
        created_at=created.row.created_at,
    )


@router.get("/workspaces/{workspace_id}/api-keys", response_model=ApiKeyList)
def list_api_keys(member: MemberDep, db: DbDep) -> ApiKeyList:
    """The workspace's keys, revoked ones included, without their secrets."""
    require(member, "manage")
    return ApiKeyList(
        api_keys=[
            ApiKeyOut.model_validate(row, from_attributes=True)
            for row in api_keys.list_keys(db, member.workspace_id)
        ]
    )


@router.delete(
    "/workspaces/{workspace_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_api_key(key_id: uuid.UUID, member: MemberDep, db: DbDep) -> Response:
    """Revoke a key. It stops working immediately."""
    require(member, "manage")
    if not api_keys.revoke_key(db, member.workspace_id, key_id):
        raise AppError(status.HTTP_404_NOT_FOUND, "API key not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
