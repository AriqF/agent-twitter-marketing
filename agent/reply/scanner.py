import logging
from datetime import datetime

from sqlalchemy import func, select

from config import (
    PRODUCT,
    REPLY_KEYWORDS_PER_CYCLE,
    REPLY_MAX_NEW_CANDIDATES,
    REPLY_SCAN_BACKLOG_THRESHOLD,
)
from db.models import ReplyCandidate
from db.session import get_session
from services.twitter import search_tweets

logger = logging.getLogger(__name__)


def _get_reply_keywords() -> list[str]:
    """Reply-specific keywords from product.yaml, with fallback to primary keywords."""
    reply_kw = PRODUCT.get("reply_keywords")
    if isinstance(reply_kw, list) and reply_kw:
        return reply_kw

    kw = PRODUCT.get("keywords", {})
    if isinstance(kw, list):
        return kw
    return kw.get("primary", [])


def _get_rotated_keywords(all_keywords: list[str], per_cycle: int) -> list[str]:
    if not all_keywords:
        return []

    now = datetime.now()
    cycle_slot = now.toordinal() * 24 + now.hour
    offset = cycle_slot % len(all_keywords)
    count = min(per_cycle, len(all_keywords))
    return [all_keywords[(offset + i) % len(all_keywords)] for i in range(count)]


async def _count_pending_candidates() -> int:
    async with get_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ReplyCandidate)
            .where(ReplyCandidate.react_decision.is_(None))
        )
        return result.scalar_one()


async def scan_for_reply_candidates() -> dict:
    pending = await _count_pending_candidates()
    if pending >= REPLY_SCAN_BACKLOG_THRESHOLD:
        logger.info(
            "Skipping reply scan: backlog %s >= threshold %s",
            pending,
            REPLY_SCAN_BACKLOG_THRESHOLD,
        )
        return {
            "scanned": False,
            "reason": "backlog_full",
            "pending": pending,
            "new_count": 0,
            "keywords": [],
        }

    keywords = _get_rotated_keywords(_get_reply_keywords(), REPLY_KEYWORDS_PER_CYCLE)
    if not keywords:
        logger.warning("No reply keywords configured, skipping scan")
        return {
            "scanned": False,
            "reason": "no_keywords",
            "pending": pending,
            "new_count": 0,
            "keywords": [],
        }

    new_count = 0
    async with get_session() as session:
        for keyword in keywords:
            if new_count >= REPLY_MAX_NEW_CANDIDATES:
                break

            tweets = await search_tweets(keyword, limit=10)
            for tweet in tweets:
                if new_count >= REPLY_MAX_NEW_CANDIDATES:
                    break

                existing = await session.execute(
                    select(ReplyCandidate).where(
                        ReplyCandidate.twitter_post_id == tweet["id"]
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                candidate = ReplyCandidate(
                    twitter_post_id=tweet["id"],
                    author_username=tweet["username"],
                    tweet_content=tweet["text"],
                    keyword_matched=keyword,
                )
                session.add(candidate)
                new_count += 1

        await session.commit()

    logger.info(
        "Reply scan complete: keywords=%s new_count=%s pending_before=%s",
        keywords,
        new_count,
        pending,
    )
    return {
        "scanned": True,
        "reason": None,
        "pending": pending,
        "new_count": new_count,
        "keywords": keywords,
    }
