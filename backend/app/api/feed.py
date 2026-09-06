import base64
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, case, func, select, tuple_
from sqlalchemy.orm import selectinload

from app.deps import DbSession, RequireAuth
from app.models import Channel, ChannelTag, Upload
from app.schemas import ChannelRef, FeedPage, UploadOut, VideoType

router = APIRouter(prefix="/feed", tags=["feed"], dependencies=[RequireAuth])

# 1 for a currently-active livestream, 0 for everything else — pinned to the
# top of the feed regardless of published_at (see get_feed's ORDER BY).
# Expressed as DESC alongside published_at/id (also DESC) so the keyset
# pagination trick below (a plain tuple "<" comparison) stays correct: it
# only works when every column in the tuple sorts the same direction.
_IS_ACTIVE_LIVE = case((and_(Upload.video_type == "live", Upload.live_status == "live"), 1), else_=0)


def _encode_cursor(is_active_live: int, published_at: datetime, upload_id: int) -> str:
    raw = f"{is_active_live}|{published_at.isoformat()}|{upload_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[int, datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        is_active_live_str, published_at_str, upload_id_str = raw.split("|", 2)
        return int(is_active_live_str), datetime.fromisoformat(published_at_str), int(upload_id_str)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor") from exc


def _apply_filters(query, tag_id: int | None, channel_id: int | None, video_type: VideoType | None):
    if tag_id is not None:
        query = query.join(Channel, Upload.channel_id == Channel.id).join(
            ChannelTag, ChannelTag.channel_id == Channel.id
        ).where(ChannelTag.tag_id == tag_id)
    if channel_id is not None:
        query = query.where(Upload.channel_id == channel_id)
    if video_type is not None:
        query = query.where(Upload.video_type == video_type)
    return query


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

    # total_uploads must reflect the same tag/channel/video_type filters as
    # the page itself (but never the cursor — that's pagination, not a
    # filter) so the frontend can show "how many uploads match the current
    # filters", not a constant unfiltered site-wide count.
    count_query = _apply_filters(select(func.count(Upload.id)), tag_id, channel_id, video_type)
    total_uploads = (await session.execute(count_query)).scalar_one()

    query = _apply_filters(
        select(Upload).options(selectinload(Upload.channel)).order_by(
            _IS_ACTIVE_LIVE.desc(), Upload.published_at.desc(), Upload.id.desc()
        ),
        tag_id,
        channel_id,
        video_type,
    )
    if cursor is not None:
        cursor_is_active_live, cursor_published_at, cursor_id = _decode_cursor(cursor)
        query = query.where(
            tuple_(_IS_ACTIVE_LIVE, Upload.published_at, Upload.id)
            < tuple_(cursor_is_active_live, cursor_published_at, cursor_id)
        )

    query = query.limit(limit + 1)
    result = await session.execute(query)
    uploads = list(result.scalars())
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
            video_type_verified=u.video_type_verified,
            duration_seconds=u.duration_seconds,
            live_status=u.live_status,
            scheduled_start_at=u.scheduled_start_at,
            live_started_at=u.live_started_at,
        )
        for u in uploads
    ]

    next_cursor = None
    if has_more and uploads:
        last = uploads[-1]
        is_active_live = 1 if last.video_type == "live" and last.live_status == "live" else 0
        next_cursor = _encode_cursor(is_active_live, last.published_at, last.id)
    return FeedPage(items=items, next_cursor=next_cursor, total_uploads=total_uploads)
