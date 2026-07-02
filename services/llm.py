import json
import re

from langchain_openai import ChatOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

_llm = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY)
    return _llm


async def invoke(prompt: str) -> str:
    response = await get_llm().ainvoke(prompt)
    return response.content


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())
