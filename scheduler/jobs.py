import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from agent.graph import agent_graph
from agent.reply.responder import process_reply_candidates
from agent.reply.scanner import scan_for_reply_candidates
from config import BATCH_CYCLE_DAYS, REPLY_TIMES, TIMEZONE

async def run_agent_graph():
    from agent.state import AgentState

    initial_state: AgentState = {
        "research_brief": {},
        "content_plan": [],
        "content_drafts": [],
        "batch_id": None,
        "approval_status": None,
        "error": None,
    }
    await agent_graph.ainvoke(initial_state)

def setup_scheduler() -> AsyncIOScheduler:
    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

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
        trigger=CronTrigger(minute="*/15"),
        id="publish_approved",
        name="Publish Approved Content",
        replace_existing=True,
    )

    return scheduler

async def run_reply_cycle() -> dict:
    scan_result = await scan_for_reply_candidates()
    await process_reply_candidates()
    return scan_result


async def run_publish_approved():
    await publish_approved_drafts()
    await publish_approved_replies()


async def publish_approved_drafts():
    from datetime import datetime

    from sqlalchemy import select

    from db.models import ContentDraft, PostLog
    from db.session import get_session
    from services.twitter import post_tweet

    async with get_session() as session:
        now = datetime.now()
        result = await session.execute(
            select(ContentDraft)
            .where(ContentDraft.status == "approved")
            .where(ContentDraft.scheduled_at <= now)
        )
        drafts = result.scalars().all()

        for draft in drafts:
            try:
                tweet_id = await post_tweet(text=draft.tweet_copy)
                log = PostLog(
                    draft_id=draft.id,
                    twitter_post_id=tweet_id,
                    status="success",
                )
                draft.status = "completed"
                session.add(log)
            except Exception:
                log = PostLog(
                    draft_id=draft.id,
                    twitter_post_id="",
                    status="failed",
                )
                session.add(log)

        await session.commit()


async def publish_approved_replies():
    from datetime import datetime

    from sqlalchemy import select

    from db.models import ReplyCandidate
    from db.session import get_session
    from services.twitter import post_reply

    async with get_session() as session:
        result = await session.execute(
            select(ReplyCandidate)
            .where(ReplyCandidate.status == "approved")
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
                candidate.status = "posted"
            except Exception:
                pass

        await session.commit()
