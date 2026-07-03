import logging

from sqlalchemy import select

from config import PRODUCT
from db.models import ReplyCandidate, ReplyCandidateStatus, ReplyDecision
from db.session import get_session
from services.llm import invoke, parse_json
from services.telegram import send_reply_for_approval

logger = logging.getLogger(__name__)


def _get_outreach_context() -> str:
    context = PRODUCT.get("outreach_context")
    if isinstance(context, str) and context.strip():
        return context.strip()
    raise ValueError("product.yaml: outreach_context must be a non-empty string")


def _get_outreach_reply_rules() -> list[str]:
    rules = PRODUCT.get("outreach_reply_rules")
    if isinstance(rules, list) and rules:
        return rules
    raise ValueError("product.yaml: outreach_reply_rules must be a non-empty list")


def _format_numbered_list(items: list[str]) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))


async def process_reply_candidates():
    tone = PRODUCT.get("tone_of_voice", {})
    tone_style = tone.get("style", tone) if isinstance(tone, dict) else tone

    audience = PRODUCT.get("target_audience", {})
    audience_primary = (
        audience.get("primary", audience) if isinstance(audience, dict) else audience
    )

    outreach_context = _get_outreach_context()
    outreach_rules = _format_numbered_list(_get_outreach_reply_rules())
    website = PRODUCT.get("links", {}).get("website", "")

    async with get_session() as session:
        result = await session.execute(
            select(ReplyCandidate)
            .where(ReplyCandidate.react_decision.is_(None))
            .limit(10)
        )
        candidates = result.scalars().all()

        for candidate in candidates:
            prompt = f"""
            Kamu adalah social media manager untuk outreach reply di Twitter/X.
            Target audience: {audience_primary}.
            Tone: {tone_style}.

            ## Konteks produk
            {outreach_context}

            ## Aturan reply
            {outreach_rules}

            ## Tweet kandidat
            Keyword pencarian: {candidate.keyword_matched or '-'}
            Author: @{candidate.author_username}
            Tweet:
            "{candidate.tweet_content}"

            ## Tugas
            REASONING: Apakah tweet ini layak direply? Tweet ini sudah lolos scoring outreach
            (intent, pain point, buying signal, atau question pattern).

            ACTION: Jika layak, tulis reply text sesuai dengan aturan reply yang telah didefinisikan

            Respond dalam JSON:
            {{
            "reasoning": "...",
            "decision": "reply" atau "skip",
            "reply_text": "..." atau null
            }}

            Website (mention hanya jika sangat relevan): {website}
            """

            response = await invoke(prompt)
            result_json = parse_json(response)

            candidate.react_reasoning = result_json["reasoning"]
            candidate.react_decision = ReplyDecision(result_json["decision"])
            candidate.reply_text = result_json.get("reply_text")

            if (
                candidate.react_decision == ReplyDecision.REPLY
                and result_json.get("reply_text")
            ):
                candidate.status = ReplyCandidateStatus.PENDING
                try:
                    await send_reply_for_approval(candidate)
                except Exception as e:
                    logger.error(
                        "Failed to send reply candidate %s to Telegram: %s",
                        candidate.id,
                        e,
                    )
            else:
                candidate.status = ReplyCandidateStatus.SKIPPED

        await session.commit()
