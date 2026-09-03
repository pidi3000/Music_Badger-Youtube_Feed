from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import DbSession, RequireAuth
from app.models import Tag
from app.schemas import TagCreate, TagOut, TagUpdate

router = APIRouter(prefix="/tags", tags=["tags"], dependencies=[RequireAuth])


async def _get_or_404(session: DbSession, tag_id: int) -> Tag:
    tag = await session.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tag not found")
    return tag


@router.get("", response_model=list[TagOut])
async def list_tags(session: DbSession):
    result = await session.execute(select(Tag).order_by(Tag.name))
    return list(result.scalars())


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(body: TagCreate, session: DbSession):
    tag = Tag(name=body.name, color=body.color)
    session.add(tag)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="a tag with that name already exists") from exc
    await session.refresh(tag)
    return tag


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(tag_id: int, body: TagUpdate, session: DbSession):
    tag = await _get_or_404(session, tag_id)
    if body.name is not None:
        tag.name = body.name
    if body.color is not None:
        tag.color = body.color
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="a tag with that name already exists") from exc
    await session.refresh(tag)
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: int, session: DbSession):
    tag = await _get_or_404(session, tag_id)
    await session.delete(tag)
    await session.commit()
