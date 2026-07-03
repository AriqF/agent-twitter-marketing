import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ContentBatch, ContentBatchStatus, ContentDraft, ContentDraftStatus


def compute_batch_status(
    draft_statuses: list[ContentDraftStatus],
) -> ContentBatchStatus:
    if not draft_statuses:
        return ContentBatchStatus.PENDING

    if all(s == ContentDraftStatus.REJECTED for s in draft_statuses):
        return ContentBatchStatus.CANCELLED

    terminal = {ContentDraftStatus.COMPLETED, ContentDraftStatus.REJECTED}
    if all(s in terminal for s in draft_statuses):
        if any(s == ContentDraftStatus.COMPLETED for s in draft_statuses):
            return ContentBatchStatus.COMPLETED
        return ContentBatchStatus.CANCELLED

    has_pending_review = any(
        s in (ContentDraftStatus.PENDING, ContentDraftStatus.REVISED)
        for s in draft_statuses
    )
    has_approved_or_completed = any(
        s in (ContentDraftStatus.APPROVED, ContentDraftStatus.COMPLETED)
        for s in draft_statuses
    )

    if has_pending_review:
        if has_approved_or_completed:
            return ContentBatchStatus.PARTIALLY_APPROVED
        if all(s == ContentDraftStatus.PENDING for s in draft_statuses):
            return ContentBatchStatus.PENDING
        return ContentBatchStatus.IN_REVIEW

    if any(s == ContentDraftStatus.APPROVED for s in draft_statuses):
        return ContentBatchStatus.ACTIVE

    return ContentBatchStatus.IN_REVIEW


async def sync_batch_status(
    batch_id: uuid.UUID, session: AsyncSession
) -> ContentBatchStatus:
    batch = await session.get(ContentBatch, batch_id)
    if batch is None:
        raise ValueError(f"ContentBatch {batch_id} not found")

    result = await session.execute(
        select(ContentDraft.status).where(ContentDraft.batch_id == batch_id)
    )
    draft_statuses = list(result.scalars().all())
    new_status = compute_batch_status(draft_statuses)

    if batch.status != new_status:
        batch.status = new_status

    return new_status
