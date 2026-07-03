import logging
import uuid

import pytz
from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.graph import agent_graph
from agent.reply.responder import process_reply_candidates
from agent.reply.scanner import scan_for_reply_candidates
from config import BATCH_CYCLE_DAYS, REPLY_TIMES, TIMEZONE
from services.alerts import notify_owner, run_guarded

logger = logging.getLogger(__name__)


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


async def _batch_cycle_impl():
    from agent.state import AgentState

    initial_state: AgentState = {
        "research_brief": {},
        "content_plan": [],
        "content_drafts": [],
        "batch_id": None,
        "approval_status": None,
        "error": None,
    }
    result = await agent_graph.ainvoke(initial_state)
    logger.info("batch_cycle done batch_id=%s", result.get("batch_id"))
    return result


async def run_agent_graph():
    return await run_guarded("batch_cycle", _batch_cycle_impl())


async def _reply_cycle_impl() -> dict:
    scan_result = await scan_for_reply_candidates()
    await process_reply_candidates()
    logger.info(
        "reply_cycle done scanned=%s new=%s",
        scan_result.get("scanned"),
        scan_result.get("new_count", 0),
    )
    return scan_result


async def run_reply_cycle() -> dict | None:
    return await run_guarded("reply_cycle", _reply_cycle_impl())


def _on_job_error(event) -> None:
    if event.exception:
        logger.exception("Job %s failed", event.job_id, exc_info=event.exception)


def setup_scheduler() -> AsyncIOScheduler:
    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)

    scheduler.add_job(
        run_agent_graph,
        trigger=IntervalTrigger(days=BATCH_CYCLE_DAYS),
        id="batch_cycle",
        name="Content Batch Cycle",
        replace_existing=True,
    )

    for time_str in REPLY_TIMES:
        hour, minute = map(int, time_str.strip().split(":"))
        scheduler.add_job(
            run_reply_cycle,
            trigger=CronTrigger(hour=hour, minute=minute),
            id=f"reply_{time_str}",
            name=f"Reply Cycle {time_str}",
            replace_existing=True,
        )

    scheduler.add_job(
        run_publish_approved,
        trigger=CronTrigger(minute="*/15 "),
        id="publish_approved",
        name="Publish Approved Content",
        replace_existing=True,
    )

    return scheduler


async def run_publish_approved():
    async def _impl():
        logger.info("publish_approved start")
        draft_stats = await publish_approved_drafts()
        reply_stats = await publish_approved_replies()
        logger.info(
            "publish_approved done drafts=%s/%s replies=%s/%s",
            draft_stats["success"],
            draft_stats["total"],
            reply_stats["success"],
            reply_stats["total"],
        )
        failed_drafts = draft_stats["failed"]
        failed_replies = reply_stats["failed"]
        if failed_drafts or failed_replies:
            parts = []
            if failed_drafts:
                ids = ", ".join(str(i) for i in failed_drafts[:5])
                suffix = "..." if len(failed_drafts) > 5 else ""
                parts.append(
                    f"Draft: {len(failed_drafts)}/{draft_stats['total']} gagal (ids: {ids}{suffix})"
                )
            if failed_replies:
                ids = ", ".join(str(i) for i in failed_replies[:5])
                suffix = "..." if len(failed_replies) > 5 else ""
                parts.append(
                    f"Reply: {len(failed_replies)}/{reply_stats['total']} gagal (ids: {ids}{suffix})"
                )
            await notify_owner("⚠️ Publish partial gagal\n" + "\n".join(parts))

    await run_guarded("publish_approved", _impl())


async def publish_draft_by_id(draft_id: uuid.UUID | str) -> dict:
    from db.models import ContentDraft, ContentDraftStatus, PostLog, PostLogStatus
    from db.session import get_session
    from services.batch_status import sync_batch_status
    from services.twitter import post_tweet

    draft_uuid = _coerce_uuid(draft_id)

    async with get_session() as session:
        draft = await session.get(ContentDraft, draft_uuid)
        if draft is None:
            raise ValueError("Draft tidak ditemukan.")

        draft_status = draft.status.value if draft.status else "none"
        if draft.status != ContentDraftStatus.APPROVED:
            raise ValueError(
                f"Draft status saat ini `{draft_status}`. Hanya status `approved` yang bisa dipublish."
            )

        try:
            tweet_id = await post_tweet(text=draft.tweet_copy)
        except Exception:
            session.add(
                PostLog(
                    draft_id=draft.id,
                    twitter_post_id="",
                    status=PostLogStatus.FAILED,
                )
            )
            await session.commit()
            logger.exception("Failed to publish draft by id draft_id=%s", draft.id)
            raise

        session.add(
            PostLog(
                draft_id=draft.id,
                twitter_post_id=tweet_id,
                status=PostLogStatus.SUCCESS,
            )
        )
        draft.status = ContentDraftStatus.COMPLETED
        await sync_batch_status(draft.batch_id, session)
        await session.commit()

    return {
        "id": str(draft_uuid),
        "twitter_post_id": tweet_id,
        "status": ContentDraftStatus.COMPLETED.value,
    }


async def publish_reply_by_id(candidate_id: uuid.UUID | str) -> dict:
    from datetime import datetime

    from db.models import ReplyCandidate, ReplyCandidateStatus
    from db.session import get_session
    from services.twitter import post_reply

    candidate_uuid = _coerce_uuid(candidate_id)

    async with get_session() as session:
        candidate = await session.get(ReplyCandidate, candidate_uuid)
        if candidate is None:
            raise ValueError("Reply candidate tidak ditemukan.")

        candidate_status = candidate.status.value if candidate.status else "none"
        if candidate.status != ReplyCandidateStatus.APPROVED:
            raise ValueError(
                f"Reply candidate status saat ini `{candidate_status}`. Hanya status `approved` yang bisa dipublish."
            )
        if candidate.replied_at is not None:
            raise ValueError("Reply candidate ini sudah pernah dipublish.")
        if not candidate.reply_text:
            raise ValueError("Reply candidate belum memiliki reply_text.")
        if not candidate.twitter_post_id:
            raise ValueError("Reply candidate belum memiliki twitter_post_id target.")

        try:
            reply_post_id = await post_reply(
                tweet_id=candidate.twitter_post_id,
                text=candidate.reply_text,
            )
        except Exception:
            logger.exception(
                "Failed to publish reply by id candidate_id=%s",
                candidate.id,
            )
            raise

        target_tweet_id = candidate.twitter_post_id
        candidate.replied_at = datetime.now()
        candidate.status = ReplyCandidateStatus.POSTED
        await session.commit()

    return {
        "id": str(candidate_uuid),
        "target_twitter_post_id": target_tweet_id,
        "posted_reply_id": reply_post_id,
        "status": ReplyCandidateStatus.POSTED.value,
    }


async def publish_approved_drafts() -> dict:
    from datetime import datetime

    from sqlalchemy import select

    from db.models import ContentDraft, ContentDraftStatus, PostLog, PostLogStatus
    from db.session import get_session
    from services.batch_status import sync_batch_status
    from services.twitter import post_tweet

    failed_ids: list = []
    success_count = 0

    async with get_session() as session:
        now = datetime.now()
        result = await session.execute(
            select(ContentDraft)
            .where(ContentDraft.status == ContentDraftStatus.APPROVED)
            .where(ContentDraft.scheduled_at <= now)
        )
        drafts = result.scalars().all()
        batch_ids: set = set()

        for draft in drafts:
            batch_ids.add(draft.batch_id)
            try:
                tweet_id = await post_tweet(text=draft.tweet_copy)
                log = PostLog(
                    draft_id=draft.id,
                    twitter_post_id=tweet_id,
                    status=PostLogStatus.SUCCESS,
                )
                draft.status = ContentDraftStatus.COMPLETED
                session.add(log)
                success_count += 1
            except Exception as e:
                logger.error("Failed to publish draft %s: %s", draft.id, e)
                failed_ids.append(draft.id)
                log = PostLog(
                    draft_id=draft.id,
                    twitter_post_id="",
                    status=PostLogStatus.FAILED,
                )
                session.add(log)

        for batch_id in batch_ids:
            await sync_batch_status(batch_id, session)

        await session.commit()

    return {
        "total": len(drafts),
        "success": success_count,
        "failed": failed_ids,
    }


async def publish_approved_replies() -> dict:
    from datetime import datetime

    from sqlalchemy import select

    from db.models import ReplyCandidate, ReplyCandidateStatus
    from db.session import get_session
    from services.twitter import post_reply

    failed_ids: list = []
    success_count = 0

    async with get_session() as session:
        result = await session.execute(
            select(ReplyCandidate)
            .where(ReplyCandidate.status == ReplyCandidateStatus.APPROVED)
            .where(ReplyCandidate.replied_at.is_(None))
        )
        candidates = result.scalars().all()

        for candidate in candidates:
            try:
                await post_reply(
                    tweet_id=candidate.twitter_post_id,
                    text=candidate.reply_text,
                )
                candidate.replied_at = datetime.now()
                candidate.status = ReplyCandidateStatus.POSTED
                success_count += 1
            except Exception as e:
                logger.error("Failed to publish reply %s: %s", candidate.id, e)
                failed_ids.append(candidate.id)

        await session.commit()

    return {
        "total": len(candidates),
        "success": success_count,
        "failed": failed_ids,
    }
