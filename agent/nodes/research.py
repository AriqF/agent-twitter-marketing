import logging
from datetime import datetime

from agent.state import AgentState
from config import PRODUCT
from services.llm import invoke, parse_json
from services.twitter import search_tweets

logger = logging.getLogger(__name__)

_RESEARCH_OUTPUT_SCHEMA = """
{
  "trends": ["..."],
  "pain_points": ["..."],
  "competitor_insights": ["..."],
  "keywords_and_hashtags": ["..."],
  "content_gaps": ["..."],
  "content_opportunities": ["..."],
  "product_alignment": ["..."],
  "recommended_hooks_angles": ["..."],
  "recommended_tone": "...",
  "prioritization": ["rekomendasi prioritas 1", "prioritas 2", "..."]
}
"""


def _get_rotated_keywords(all_keywords: list[str], count: int) -> list[str]:
    if not all_keywords:
        return []

    now = datetime.now()
    cycle_slot = now.toordinal() * 24 + now.hour
    offset = cycle_slot % len(all_keywords)
    pick = min(count, len(all_keywords))
    return [all_keywords[(offset + i) % len(all_keywords)] for i in range(pick)]


def _get_research_search_keywords() -> list[str]:
    """Pick rotated keywords from research.trending_topics + product_related + 1 competitor."""
    kw = PRODUCT.get("keywords") or {}
    research = kw.get("research") or {}

    trending = research.get("trending_topics") or []
    product_related = research.get("product_related") or []
    competitor = research.get("competitor") or []

    selected: list[str] = []
    selected.extend(_get_rotated_keywords(trending, 2))
    selected.extend(_get_rotated_keywords(product_related, 1))

    if competitor:
        comp_pick = _get_rotated_keywords(competitor, 1)
        selected.extend(comp_pick)

    # dedupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in selected:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    if not unique:
        raise ValueError(
            "product.yaml: keywords.research must define trending_topics and/or product_related"
        )
    return unique


def _get_research_context() -> str:
    context = PRODUCT.get("research_context")
    if isinstance(context, str) and context.strip():
        return context.strip()
    raise ValueError("product.yaml: research_context must be a non-empty string")


def _get_research_briefs() -> list[str]:
    briefs = PRODUCT.get("research_brief")
    if isinstance(briefs, list) and briefs:
        return briefs
    raise ValueError("product.yaml: research_brief must be a non-empty list")


def _get_research_output_rules() -> list[str]:
    rules = PRODUCT.get("research_output_rules")
    if isinstance(rules, list) and rules:
        return rules
    raise ValueError("product.yaml: research_output_rules must be a non-empty list")


def _format_tweet_samples(tweets: list[dict], limit: int = 20) -> str:
    if not tweets:
        return "(tidak ada tweet ditemukan)"
    lines = []
    for tweet in tweets[:limit]:
        text = (tweet.get("text") or "")[:280]
        lines.append(f"- @{tweet.get('username', 'unknown')}: {text}")
    return "\n".join(lines)


def _format_numbered_list(items: list[str]) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))


async def research_node(state: AgentState) -> AgentState:
    logger.info("research_node start")
    try:
        keywords = _get_research_search_keywords()
        logger.info("research_node keywords=%s", keywords)

        tweets = []
        for keyword in keywords:
            results = await search_tweets(keyword, limit=10)
            tweets.extend(results)

        prompt = f"""
        Kamu adalah research analyst. Tugasmu menganalisis percakapan di media sosial
        dan menghasilkan research brief berdasarkan konteks produk, sample tweet,
        serta instruksi di bawah.

        ## Konteks produk
        {_get_research_context()}

        ## Tugas analisis
        Berdasarkan sample tweet X/Twitter dan konteks produk di atas, buat research brief.
        Setiap poin di bawah WAJIB dianalisis dan dirangkum dalam output JSON:

        {_format_numbered_list(_get_research_briefs())}

        ## Sample tweet (7 hari terakhir)
        {_format_tweet_samples(tweets)}

        ## Aturan output
        {_format_numbered_list(_get_research_output_rules())}

        Respond HANYA dengan JSON valid:
        {_RESEARCH_OUTPUT_SCHEMA.strip()}
        """

        response = await invoke(prompt)
        research_brief = parse_json(response)

        logger.info("research_node done tweets=%d keywords=%d", len(tweets), len(keywords))
        return {**state, "research_brief": research_brief}
    except Exception:
        logger.exception("research_node failed")
        raise
