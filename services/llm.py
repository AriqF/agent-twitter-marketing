import json
import logging
import re

from langchain_openai import ChatOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

_llm = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY)
    return _llm


async def invoke(prompt: str) -> str:
    try:
        logger.info("LLM Invoke start")
        response = await get_llm().ainvoke(prompt)
        return response.content
    except Exception:
        logger.exception("LLM invoke failed")
        raise


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        snippet = text[:100].replace("\n", " ")
        raise ValueError(f"Invalid JSON from LLM: {snippet}") from e
