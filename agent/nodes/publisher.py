import logging
from datetime import datetime, timedelta

from agent.state import AgentState
from db.models import ContentBatch, ContentBatchStatus, ContentDraft, ContentDraftStatus
from db.session import get_session
from services.telegram import send_batch_for_approval

logger = logging.getLogger(__name__)


async def publisher_node(state: AgentState) -> AgentState:
    logger.info("publisher_node start")
    try:
        async with get_session() as session:
            now = datetime.now()

            batch = ContentBatch(
                research_brief=state["research_brief"],
                content_plan=state["content_plan"],
                status=ContentBatchStatus.PENDING,
                scheduled_from=now,
                scheduled_to=now + timedelta(days=3),
            )
            session.add(batch)
            await session.flush()

            draft_records = []
            for draft in state["content_drafts"]:
                scheduled_at = draft["scheduled_at"]
                if isinstance(scheduled_at, str):
                    scheduled_at = datetime.fromisoformat(scheduled_at)

                record = ContentDraft(
                    batch_id=batch.id,
                    tweet_copy=draft["tweet_copy"],
                    scheduled_at=scheduled_at,
                    status=ContentDraftStatus.PENDING,
                )
                session.add(record)
                draft_records.append(record)

            await session.commit()

            await send_batch_for_approval(str(batch.id), draft_records)

        logger.info("publisher_node done batch_id=%s drafts=%d", batch.id, len(draft_records))
        return {**state, "batch_id": str(batch.id)}
    except Exception:
        logger.exception("publisher_node failed")
        raise
