import logging
from datetime import datetime, timedelta

from agent.state import AgentState
from config import PRODUCT
from db.models import WikiCategory
from services.llm import invoke
from services.wiki_writer import get_wiki_context

logger = logging.getLogger(__name__)


async def creator_node(state: AgentState) -> AgentState:
    logger.info("creator_node start")
    try:
        content_plan = state["content_plan"]
        drafts = []
        now = datetime.now()

        wiki_context = await get_wiki_context(
            categories=[WikiCategory.PRODUCT, WikiCategory.REVISION_PATTERN]
        )

        tone = PRODUCT.get("tone_of_voice", {})
        tone_style = tone.get("style", tone) if isinstance(tone, dict) else tone

        cta = PRODUCT.get("cta", {})
        cta_primary = cta.get("primary", cta) if isinstance(cta, dict) else cta

        for slot in content_plan:
            prompt = f"""
        Tulis tweet untuk produk {PRODUCT['name']} — {PRODUCT['tagline']}.
        Website: {PRODUCT['links']['website']}
        Tone: {tone_style}

        Topik: {slot['topic']}
        Angle: {slot['angle']}

        {wiki_context}

        Ketentuan:
        - Maksimal 280 karakter
        - Sertakan CTA subtle: {cta_primary}
        - Gunakan 1-2 hashtag relevan
        - Bahasa Indonesia
        - Jangan terlalu promotional, utamakan value

        Respond HANYA dengan teks tweet, tanpa penjelasan tambahan.
        """

            tweet_copy = (await invoke(prompt)).strip()

            day_offset = slot.get("day_offset", 0)
            best_time = slot.get("best_time", "09:00")
            hour, minute = map(int, best_time.split(":"))
            scheduled_at = (now + timedelta(days=day_offset)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

            drafts.append(
                {
                    "tweet_copy": tweet_copy,
                    "scheduled_at": scheduled_at.isoformat(),
                    "topic": slot["topic"],
                }
            )

        logger.info("creator_node done drafts=%d", len(drafts))
        return {**state, "content_drafts": drafts}
    except Exception:
        logger.exception("creator_node failed")
        raise
