from agent.state import AgentState
from config import PRODUCT
from services.llm import invoke, parse_json
from services.twitter import search_tweets


def _get_research_keywords() -> list[str]:
    """Flatten keywords from product.yaml (handles both list and dict formats)."""
    kw = PRODUCT.get("keywords", {})
    if isinstance(kw, list):
        return kw
    return kw.get("primary", []) + kw.get("secondary", []) + kw.get("long_tail", [])


async def research_node(state: AgentState) -> AgentState:
    keywords = _get_research_keywords()

    tweets = []
    for keyword in keywords[:3]:
        results = await search_tweets(keyword, limit=10)
        tweets.extend(results)

    prompt = f"""
    Kamu adalah research analyst untuk produk: {PRODUCT['name']} — {PRODUCT['tagline']}.

    Berdasarkan tweets berikut tentang CPNS dan data produk, buat research brief yang berisi:
    1. Tren topik yang sedang ramai dibicarakan
    2. Pain points yang sering muncul dari calon peserta CPNS
    3. Peluang konten yang relevan untuk dipromosikan
    4. Tone dan angle yang cocok untuk minggu ini

    Tweets sample: {tweets[:20]}

    Respond dalam format JSON dengan keys: trends, pain_points, content_opportunities, recommended_tone
    """

    response = await invoke(prompt)
    research_brief = parse_json(response)

    return {**state, "research_brief": research_brief}
