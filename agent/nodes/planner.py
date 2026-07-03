import json
import logging
from datetime import datetime

from agent.state import AgentState
from config import PRODUCT
from db.models import WikiCategory
from services.llm import invoke, parse_json
from services.wiki_writer import get_wiki_context

logger = logging.getLogger(__name__)


async def planner_node(state: AgentState) -> AgentState:
    logger.info("planner_node start")
    try:
        research_brief = state["research_brief"]
        now = datetime.now()

        wiki_context = await get_wiki_context(
            categories=[WikiCategory.APPROVED_PATTERN, WikiCategory.REJECTION_PATTERN]
        )

        tone = PRODUCT.get("tone_of_voice", {})
        tone_style = tone.get("style", tone) if isinstance(tone, dict) else tone

        audience = PRODUCT.get("target_audience", {})
        audience_primary = (
            audience.get("primary", audience) if isinstance(audience, dict) else audience
        )

        cta = PRODUCT.get("cta", {})
        cta_primary = cta.get("primary", cta) if isinstance(cta, dict) else cta

        prompt = f"""
    Kamu adalah content strategist untuk {PRODUCT['name']}.
    Tone: {tone_style}
    Target audience: {audience_primary}
    CTA: {cta_primary}

    Research brief: {json.dumps(research_brief)}

    {wiki_context}

    Buat content plan text-only untuk 3 hari ke depan mulai dari {now.strftime('%Y-%m-%d')}.
    Setiap hari maksimal 2 post. Total maksimal 6 post.

    Untuk setiap post tentukan:
    - topic: topik spesifik
    - angle: sudut pandang atau hook
    - best_time: waktu posting ideal dalam format HH:MM (WIB)
    - day_offset: 0, 1, atau 2 (hari ke berapa dari sekarang)

    Respond HANYA dengan JSON array. Contoh:
    [
      {{"topic": "...", "angle": "...", "best_time": "08:00", "day_offset": 0}},
      ...
    ]
    """

        response = await invoke(prompt)
        content_plan = parse_json(response)

        logger.info("planner_node done slots=%d", len(content_plan))
        return {**state, "content_plan": content_plan}
    except Exception:
        logger.exception("planner_node failed")
        raise
