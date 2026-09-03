import base64
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import selectinload

from app.deps import DbSession, RequireAuth
from app.models import Channel, ChannelTag, Upload
from app.schemas import ChannelRef, FeedPage, UploadOut, VideoType

router = APIRouter(prefix="/feed", tags=["feed"], dependencies=[RequireAuth])


def _encode_cursor(published_at: datetime, upload_id: int) -> str:
    raw = f"{published_at.isoformat()}|{upload_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        published_at_str, upload_id_str = raw.rsplit("|", 1)
        return datetime.fromisoformat(published_at_str), int(upload_id_str)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor") from exc


@router.get("", response_model=FeedPage)
async def get_feed(
    session: DbSession,
    tag_id: int | None = None,
    channel_id: int | None = None,
    video_type: VideoType | None = None,
    cursor: str | None = None,
    limit: int = 30,
):
    limit = max(1, min(limit, 100))

    query = select(Upload).options(selectinload(Upload.channel)).order_by(
        Upload.published_at.desc(), Upload.id.desc()
    )

    if tag_id is not None:
        query = query.join(Channel, Upload.channel_id == Channel.id).join(
            ChannelTag, ChannelTag.channel_id == Channel.id
        ).where(ChannelTag.tag_id == tag_id)
    if channel_id is not None:
        query = query.where(Upload.channel_id == channel_id)
    if video_type is not None:
        query = query.where(Upload.video_type == video_type)
    if cursor is not None:
        cursor_published_at, cursor_id = _decode_cursor(cursor)
        query = query.where(
            tuple_(Upload.published_at, Upload.id) < tuple_(cursor_published_at, cursor_id)
        )

    query = query.limit(limit + 1)
    result = await session.execute(query)
    uploads = list(result.scalars())

    total_uploads = (await session.execute(select(func.count(Upload.id)))).scalar_one()
    await session.commit()

    has_more = len(uploads) > limit
    uploads = uploads[:limit]

    items = [
        UploadOut(
            id=u.id,
            channel=ChannelRef(
                id=u.channel.id,
                title=u.channel.title,
                thumbnail_url=u.channel.thumbnail_url,
                youtube_channel_id=u.channel.youtube_channel_id,
                handle=u.channel.handle,
            ),
            youtube_video_id=u.youtube_video_id,
            title=u.title,
            published_at=u.published_at,
            thumbnail_url=u.thumbnail_url,
            fetched_via=u.fetched_via,
            video_type=u.video_type,
        )
        for u in uploads
    ]

    next_cursor = _encode_cursor(uploads[-1].published_at, uploads[-1].id) if has_more and uploads else None
    return FeedPage(items=items, next_cursor=next_cursor, total_uploads=total_uploads)
