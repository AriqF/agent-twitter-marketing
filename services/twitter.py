import asyncio
import logging

import tweepy

from config import (
    X_ACCESS_TOKEN,
    X_ACCESS_TOKEN_SECRET,
    X_API_KEY,
    X_API_SECRET,
    X_BEARER_TOKEN,
)

logger = logging.getLogger(__name__)

_user_client = None
_app_client = None


def get_user_client() -> tweepy.Client:
    """Get client with OAuth 1.0a User Context (for posting)."""
    global _user_client
    if _user_client is None:
        _user_client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_TOKEN_SECRET,
            wait_on_rate_limit=False,
        )
    return _user_client


def get_app_client() -> tweepy.Client:
    """Get client with Bearer Token (for search - App-Only auth)."""
    global _app_client
    if _app_client is None:
        _app_client = tweepy.Client(
            bearer_token=X_BEARER_TOKEN,
            wait_on_rate_limit=False,
        )
    return _app_client


def _get_full_tweet_text(tweet) -> str:
    """Return full tweet text, using note_tweet for long-form posts."""
    note = getattr(tweet, "note_tweet", None)
    if note and getattr(note, "text", None):
        return note.text
    return tweet.text or ""


def _search_tweets_sync(keyword: str, limit: int) -> list[dict]:
    """Synchronous search implementation using App-Only auth."""
    client = get_app_client()
    clamped_limit = max(10, min(limit, 100))
    query = f"{keyword} -is:retweet"

    try:
        response = client.search_recent_tweets(
            query=query,
            max_results=clamped_limit,
            tweet_fields=["created_at", "author_id", "note_tweet", "public_metrics"],
            expansions=["author_id"],
            user_fields=["username"],
        )
    except tweepy.TooManyRequests:
        logger.warning("Rate limit hit for search_tweets, returning empty list")
        return []
    except tweepy.Forbidden as e:
        logger.error("Forbidden error in search_tweets: %s", e)
        return []
    except tweepy.Unauthorized as e:
        logger.error("Unauthorized error in search_tweets (check bearer token): %s", e)
        return []

    if not response.data:
        return []

    users_map = {}
    if response.includes and "users" in response.includes:
        for user in response.includes["users"]:
            users_map[user.id] = user.username

    results = []
    for tweet in response.data:
        username = users_map.get(tweet.author_id, "unknown")
        metrics = getattr(tweet, "public_metrics", None) or {}
        if hasattr(metrics, "like_count"):
            likes = metrics.like_count or 0
            retweets = metrics.retweet_count or 0
            replies = metrics.reply_count or 0
        else:
            likes = metrics.get("like_count", 0)
            retweets = metrics.get("retweet_count", 0)
            replies = metrics.get("reply_count", 0)
        results.append({
            "id": str(tweet.id),
            "username": username,
            "text": _get_full_tweet_text(tweet),
            "created_at": str(tweet.created_at) if tweet.created_at else "",
            "public_metrics": {
                "likes": likes,
                "retweets": retweets,
                "replies": replies,
            },
        })
    return results


async def search_tweets(keyword: str, limit: int = 20) -> list[dict]:
    """Search recent tweets (last 7 days) matching keyword."""
    return await asyncio.to_thread(_search_tweets_sync, keyword, limit)


def _post_tweet_sync(text: str) -> str:
    """Synchronous post implementation using User Context auth."""
    client = get_user_client()

    try:
        response = client.create_tweet(text=text)
    except tweepy.TooManyRequests as e:
        logger.error("Rate limit hit for post_tweet: %s", e)
        raise
    except tweepy.Forbidden as e:
        logger.error("Forbidden error in post_tweet: %s", e)
        raise
    except tweepy.Unauthorized as e:
        logger.error("Unauthorized error in post_tweet (check credentials): %s", e)
        raise

    return str(response.data["id"])


async def post_tweet(text: str) -> str:
    """Create a new tweet."""
    return await asyncio.to_thread(_post_tweet_sync, text)


def _post_reply_sync(tweet_id: str, text: str) -> str:
    """Synchronous reply implementation using User Context auth."""
    client = get_user_client()

    try:
        response = client.create_tweet(
            text=text,
            in_reply_to_tweet_id=tweet_id,
        )
    except tweepy.TooManyRequests as e:
        logger.error("Rate limit hit for post_reply: %s", e)
        raise
    except tweepy.Unauthorized as e:
        logger.error("Unauthorized error in post_reply (check credentials): %s", e)
        raise
    except tweepy.Forbidden as e:
        logger.error("Forbidden error in post_reply: %s", e)
        raise

    return str(response.data["id"])


async def post_reply(tweet_id: str, text: str) -> str:
    """Reply to an existing tweet."""
    return await asyncio.to_thread(_post_reply_sync, tweet_id, text)
