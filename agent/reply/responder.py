import logging

from sqlalchemy import select

from config import PRODUCT
from db.models import ReplyCandidate
from db.session import get_session
from services.llm import invoke, parse_json
from services.telegram import send_reply_for_approval

logger = logging.getLogger(__name__)


async def process_reply_candidates():
    tone = PRODUCT.get("tone_of_voice", {})
    tone_style = tone.get("style", tone) if isinstance(tone, dict) else tone

    audience = PRODUCT.get("target_audience", {})
    audience_primary = audience.get("primary", audience) if isinstance(audience, dict) else audience

    async with get_session() as session:
        result = await session.execute(
            select(ReplyCandidate)
            .where(ReplyCandidate.react_decision.is_(None))
            .limit(10)
        )
        candidates = result.scalars().all()

        for candidate in candidates:
            prompt = f"""
            Kamu adalah social media manager untuk {PRODUCT['name']} — {PRODUCT['tagline']}.
            Target audience: {audience_primary}.
            Tone: {tone_style}.

            Ada tweet berikut dari @{candidate.author_username}:
            "{candidate.tweet_content}"

            REASONING: Apakah tweet ini relevan untuk direply sebagai marketing {PRODUCT['name']}?
            Pertimbangkan (policy konservatif — skip jika ragu):
            1. Apakah user membutuhkan solusi yang {PRODUCT['name']} tawarkan?
            2. Apakah reply akan terasa natural dan helpful, bukan spammy?
            3. Apakah ini momentum yang tepat untuk mention produk?

            ACTION: Jika layak, tulis reply text yang:
            - Natural dan helpful, bukan hard-sell
            - Maksimal 200 karakter
            - Mention {PRODUCT['links']['website']} hanya jika sangat relevan
            - Bahasa Indonesia

            Respond dalam JSON:
            {{
              "reasoning": "...",
              "decision": "reply" atau "skip",
              "reply_text": "..." atau null
            }}
            """

            response = await invoke(prompt)
            result_json = parse_json(response)

            candidate.react_reasoning = result_json["reasoning"]
            candidate.react_decision = result_json["decision"]
            candidate.reply_text = result_json.get("reply_text")

            if result_json["decision"] == "reply" and result_json.get("reply_text"):
                candidate.status = "pending"
                try:
                    await send_reply_for_approval(candidate)
                except Exception as e:
                    logger.error(
                        "Failed to send reply candidate %s to Telegram: %s",
                        candidate.id,
                        e,
                    )
            else:
                candidate.status = "skipped"

        await session.commit()
