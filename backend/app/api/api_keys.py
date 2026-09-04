from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import DbSession, RequireAuth
from app.encryption import encrypt
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyOut, ApiKeyUpdate

router = APIRouter(prefix="/api-keys", tags=["api-keys"], dependencies=[RequireAuth])


async def _get_or_404(session: DbSession, key_id: int) -> ApiKey:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return key


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(session: DbSession):
    result = await session.execute(select(ApiKey).order_by(ApiKey.label))
    return list(result.scalars())


@router.post("", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED)
async def create_api_key(body: ApiKeyCreate, session: DbSession):
    key = ApiKey(label=body.label, key_value_encrypted=encrypt(body.key_value))
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key


@router.patch("/{key_id}", response_model=ApiKeyOut)
async def update_api_key(key_id: int, body: ApiKeyUpdate, session: DbSession):
    key = await _get_or_404(session, key_id)
    if body.label is not None:
        key.label = body.label
    if body.status is not None:
        key.status = body.status
        if body.status == "active":
            key.quota_resets_at = None
    await session.commit()
    await session.refresh(key)
    return key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(key_id: int, session: DbSession):
    key = await _get_or_404(session, key_id)
    await session.delete(key)
    await session.commit()
