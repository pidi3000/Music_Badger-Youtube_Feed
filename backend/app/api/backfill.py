from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import DbSession, HttpClient, RequireAuth
from app.models import BackfillTask
from app.schemas import BackfillTaskOut
from app.services.backfill_service import process_task
from app.services.channel_service import channel_to_ref

router = APIRouter(prefix="/backfill-tasks", tags=["backfill"], dependencies=[RequireAuth])


def _to_out(task: BackfillTask) -> BackfillTaskOut:
    return BackfillTaskOut(
        id=task.id,
        channel=channel_to_ref(task.channel),
        status=task.status,
        fetched_count=task.fetched_count,
        target_min_count=task.target_min_count,
        target_after=task.target_after,
        oldest_fetched_published_at=task.oldest_fetched_published_at,
        last_error=task.last_error,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("", response_model=list[BackfillTaskOut])
async def list_backfill_tasks(
    session: DbSession, status_filter: str | None = Query(default=None, alias="status")
):
    query = select(BackfillTask).options(selectinload(BackfillTask.channel)).order_by(
        BackfillTask.created_at.desc()
    )
    if status_filter is not None:
        query = query.where(BackfillTask.status == status_filter)
    result = await session.execute(query)
    await session.commit()
    return [_to_out(t) for t in result.scalars()]


@router.post("/{task_id}/retry", response_model=BackfillTaskOut)
async def retry_backfill_task(task_id: int, session: DbSession, http_client: HttpClient):
    result = await session.execute(
        select(BackfillTask).options(selectinload(BackfillTask.channel)).where(BackfillTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="backfill task not found")
    if task.status != "failed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only failed tasks can be retried")

    task.status = "queued"
    task.last_error = None
    await session.commit()

    await process_task(session, http_client, task)
    await session.refresh(task, attribute_names=["channel"])
    return _to_out(task)
