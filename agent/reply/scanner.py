import logging
from datetime import datetime

from sqlalchemy import func, select

from config import (
    REPLY_KEYWORDS_PER_CYCLE,
    REPLY_MAX_NEW_CANDIDATES,
    REPLY_SCAN_BACKLOG_THRESHOLD,
)
from db.models import ReplyCandidate
from db.session import get_session
from services.outreach_scoring import (
    get_conversation_query_keywords,
    get_reply_threshold,
    has_negative_keyword,
    is_brand_account,
    score_outreach_candidate,
)
from services.twitter import search_tweets
from services.wiki_writer import record_outreach_sample

logger = logging.getLogger(__name__)


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
    logger.debug("Start checking reply candidates")
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
            "wiki_samples": 0,
            "keywords": [],
        }

    keywords = _get_rotated_keywords(
        get_conversation_query_keywords(), REPLY_KEYWORDS_PER_CYCLE
    )
    logger.debug("fetched keywords: %s", ", ".join(keywords))
    if not keywords:
        logger.warning("No conversation_keywords configured, skipping scan")
        return {
            "scanned": False,
            "reason": "no_keywords",
            "pending": pending,
            "new_count": 0,
            "wiki_samples": 0,
            "keywords": [],
        }

    reply_threshold = get_reply_threshold()
    new_count = 0
    wiki_samples = 0
    seen_content: set[str] = set()

    async with get_session() as session:
        for keyword in keywords:
            if new_count >= REPLY_MAX_NEW_CANDIDATES:
                logger.debug("new count already exceed threshold of max new candidates")
                break

            tweets = await search_tweets(keyword, limit=10)
            logger.debug("scanned tweets contains %s tweets", len(tweets))
            
            for tweet in tweets:
                logger.debug("start scoring tweet candidate: %s", tweet)
                if new_count >= REPLY_MAX_NEW_CANDIDATES:
                    break

                tweet_id = tweet["id"]
                username = tweet.get("username")
                text = tweet.get("text") or ""

                existing = await session.execute(
                    select(ReplyCandidate).where(
                        ReplyCandidate.twitter_post_id == tweet_id
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                if is_brand_account(username):
                    logger.debug("Skip brand account @%s tweet=%s", username, tweet_id)
                    continue

                if has_negative_keyword(text):
                    logger.debug("Skip negative keyword tweet=%s", tweet_id)
                    continue

                normalized_content = text.strip().lower()
                is_dup_content = normalized_content in seen_content
                if normalized_content:
                    seen_content.add(normalized_content)

                score, signals = score_outreach_candidate(
                    text,
                    public_metrics=tweet.get("public_metrics"),
                    is_duplicate_content=is_dup_content,
                )
                logger.debug(
                    "Outreach score tweet=%s score=%s signals=%s",
                    tweet_id,
                    score,
                    signals,
                )

                if score >= reply_threshold:
                    candidate = ReplyCandidate(
                        twitter_post_id=tweet_id,
                        author_username=username,
                        tweet_content=text,
                        keyword_matched=keyword,
                    )
                    session.add(candidate)
                    new_count += 1
                else:
                    saved = await record_outreach_sample(
                        twitter_post_id=tweet_id,
                        author_username=username,
                        tweet_content=text,
                        keyword_matched=keyword,
                        score=score,
                        signals=signals,
                    )
                    if saved:
                        wiki_samples += 1

        await session.commit()

    logger.info(
        "Reply scan complete: keywords=%s new_count=%s wiki_samples=%s pending_before=%s threshold=%s",
        keywords,
        new_count,
        wiki_samples,
        pending,
        reply_threshold,
    )
    return {
        "scanned": True,
        "reason": None,
        "pending": pending,
        "new_count": new_count,
        "wiki_samples": wiki_samples,
        "keywords": keywords,
    }
