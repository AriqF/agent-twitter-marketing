import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from config import PRODUCT
from db.models import AgentWiki, WikiCategory
from db.session import get_session
from services.llm import invoke, parse_json

logger = logging.getLogger(__name__)


# ─── SEED ────────────────────────────────────────────────────────────────────


async def seed_product_wiki_if_empty() -> None:
    """Seed product wiki dari product.yaml jika belum ada entry category product."""
    async with get_session() as session:
        result = await session.execute(
            select(AgentWiki.id)
            .where(AgentWiki.category == WikiCategory.PRODUCT)
            .limit(1)
        )
        if result.scalar_one_or_none():
            return

        for key, content in _build_product_wiki_entries().items():
            session.add(
                AgentWiki(
                    category=WikiCategory.PRODUCT,
                    key=key,
                    content=content,
                    source_ids=None,
                )
            )
        await session.commit()


def _build_product_wiki_entries() -> dict[str, str]:
    """Build 3 wiki entries dari PRODUCT config."""
    return {
        "product_overview": _build_overview_content(),
        "product_features": _build_features_content(),
        "product_audience_keywords": _build_audience_keywords_content(),
    }


def _build_overview_content() -> str:
    lines = []

    if desc := PRODUCT.get("description"):
        lines.append(f"Deskripsi: {desc.strip()}")

    if vp := PRODUCT.get("value_proposition"):
        lines.append(f"\nValue Proposition Utama: {vp.get('primary', '')}")
        if secondary := vp.get("secondary"):
            lines.append("Value Proposition Tambahan:")
            for item in secondary:
                lines.append(f"  - {item}")

    if pain_points := PRODUCT.get("pain_points_addressed"):
        lines.append("\nPain Points yang Dijawab:")
        for pp in pain_points:
            lines.append(f"  - Problem: {pp.get('problem', '')}")
            lines.append(f"    Solusi: {pp.get('solution', '')}")

    if diff := PRODUCT.get("competitor_differentiation"):
        lines.append("\nDiferensiasi vs Kompetitor:")
        for key, value in diff.items():
            lines.append(f"  - {key}: {value}")

    return "\n".join(lines)


def _build_features_content() -> str:
    lines = []

    if features := PRODUCT.get("key_features"):
        lines.append("Fitur Utama:")
        for f in features:
            lines.append(f"  - {f.get('title', '')}: {f.get('description', '')}")

    if exam := PRODUCT.get("exam_structure"):
        lines.append(f"\nStruktur Ujian: {exam.get('type', '')}")
        lines.append(f"Total Soal: {exam.get('total_questions', '')} soal")
        lines.append(f"Durasi: {exam.get('duration_minutes', '')} menit")
        if sections := exam.get("sections"):
            lines.append("Section:")
            for s in sections:
                subsec = f" ({', '.join(s['subsections'])})" if s.get("subsections") else ""
                lines.append(
                    f"  - {s.get('key', '')}: {s.get('questions', '')} soal, "
                    f"passing grade {s.get('passing_grade', '')}{subsec}"
                )
        if cond := exam.get("pass_condition"):
            lines.append(f"Syarat Lulus: {cond}")

    if sp := PRODUCT.get("social_proof"):
        lines.append("\nSocial Proof:")
        if lb := sp.get("leaderboard"):
            lines.append(f"  - Leaderboard: {lb}")
        if ts := sp.get("trust_signals"):
            for signal in ts:
                lines.append(f"  - {signal}")

    return "\n".join(lines)


def _build_audience_keywords_content() -> str:
    lines = []

    if ta := PRODUCT.get("target_audience"):
        lines.append(f"Target Audience Utama: {ta.get('primary', '')}")
        if segments := ta.get("segments"):
            lines.append("Segmen:")
            for seg in segments:
                lines.append(f"  - {seg}")
        if chars := ta.get("characteristics"):
            lines.append("Karakteristik:")
            for c in chars:
                lines.append(f"  - {c}")

    if kw := PRODUCT.get("keywords"):
        lines.append("\nKeywords untuk Konten:")
        research = kw.get("research") or {}
        if trending := research.get("trending_topics"):
            lines.append(f"  Research trending: {', '.join(trending[:5])}")
        if product_related := research.get("product_related"):
            lines.append(f"  Research product: {', '.join(product_related[:5])}")
        outreach = kw.get("outreach") or {}
        if conv := outreach.get("conversation_keywords"):
            lines.append(f"  Outreach conversation: {', '.join(conv)}")

    if tov := PRODUCT.get("tone_of_voice"):
        lines.append(f"\nTone of Voice: {tov.get('style', '')}")
        if do := tov.get("do"):
            lines.append("DO:")
            for item in do:
                lines.append(f"  - {item}")
        if dont := tov.get("dont"):
            lines.append("DON'T:")
            for item in dont:
                lines.append(f"  - {item}")

    if hooks := PRODUCT.get("messaging_hooks"):
        lines.append("\nMessaging Hooks:")
        if headlines := hooks.get("headlines"):
            lines.append("Headlines:")
            for h in headlines:
                lines.append(f"  - {h}")
        if subtitles := hooks.get("subtitles"):
            lines.append("Subtitles:")
            for s in subtitles:
                lines.append(f"  - {s}")

    return "\n".join(lines)


# ─── READ ────────────────────────────────────────────────────────────────────


async def get_wiki_context(categories: list[WikiCategory]) -> str:
    """
    Fetch wiki entries by categories dan format sebagai string
    yang siap diinject ke dalam prompt LLM.
    Mengembalikan string kosong jika wiki masih kosong.
    """
    async with get_session() as session:
        result = await session.execute(
            select(AgentWiki).where(AgentWiki.category.in_(categories))
        )
        entries = result.scalars().all()

    if not entries:
        return ""

    lines = ["=== Learned Lessons dari Feedback Sebelumnya ==="]
    for entry in entries:
        lines.append(f"[{entry.category.value}] {entry.key}:\n{entry.content}")

    return "\n\n".join(lines)


# ─── WRITE ───────────────────────────────────────────────────────────────────


async def process_feedback(
    source_id: uuid.UUID,
    source_type: str,
    action: str,
    content: str,
    revision_note: str = None,
):
    """
    Dipanggil setelah owner memberikan feedback via Telegram.
    LLM membaca wiki existing lalu memutuskan apakah perlu
    membuat atau memperbarui learned lesson.
    """
    category = _action_to_category(action)

    async with get_session() as session:
        result = await session.execute(
            select(AgentWiki).where(AgentWiki.category == category)
        )
        existing_entries = result.scalars().all()

    existing_wiki_text = _format_existing_wiki(existing_entries)

    feedback_context = _build_feedback_context(
        action=action,
        source_type=source_type,
        content=content,
        revision_note=revision_note,
    )

    prompt = f"""
    Kamu adalah sistem self-improvement untuk AI marketing agent.
    Tugasmu adalah mempelajari feedback dari owner dan menyimpan learned lessons
    agar agent bisa berperforma lebih baik ke depannya.

    === Feedback Baru ===
    {feedback_context}

    === Wiki Existing (category: {category.value}) ===
    {existing_wiki_text if existing_wiki_text else "Belum ada entry untuk category ini."}

    === Tugasmu ===
    Analisis feedback ini dan tentukan:
    1. Apakah feedback ini menghasilkan insight yang signifikan dan belum tercakup di wiki?
    2. Jika ada entry wiki yang relevan, apakah perlu diperbarui/diperkuat?
    3. Apakah perlu membuat entry baru?
    {"4. Untuk reject: prioritaskan alasan owner sebagai sumber utama pola rejection." if action == "reject" else ""}

    Jangan buat entry jika feedback tidak menghasilkan insight baru yang actionable.
    Konsolidasikan pola yang sama ke satu entry, jangan duplikasi.
    Jika memperkuat entry existing, update content-nya dengan informasi baru (termasuk frekuensi).

    Respond dalam JSON:
    {{
      "should_update": true atau false,
      "reasoning": "penjelasan singkat keputusanmu",
      "entries": [
        {{
          "key": "snake_case_key yang deskriptif",
          "content": "learned lesson yang jelas dan actionable untuk agent",
          "is_update": true jika update entry existing, false jika entry baru
        }}
      ]
    }}

    Jika should_update false, entries boleh array kosong [].
    """

    response = await invoke(prompt)

    try:
        result_json = parse_json(response)
    except Exception as e:
        logger.warning("process_feedback JSON parse failed source_id=%s: %s", source_id, e)
        return

    if not result_json.get("should_update"):
        return

    async with get_session() as session:
        for entry_data in result_json.get("entries", []):
            key = entry_data.get("key", "").strip()
            content_text = entry_data.get("content", "").strip()
            if not key or not content_text:
                continue

            existing = await session.execute(
                select(AgentWiki).where(AgentWiki.key == key)
            )
            existing_entry = existing.scalar_one_or_none()

            if existing_entry:
                existing_entry.content = content_text
                existing_entry.source_ids = list(
                    set((existing_entry.source_ids or []) + [source_id])
                )
                existing_entry.updated_at = datetime.now()
            else:
                new_entry = AgentWiki(
                    category=category,
                    key=key,
                    content=content_text,
                    source_ids=[source_id],
                )
                session.add(new_entry)

        await session.commit()


async def record_outreach_sample(
    twitter_post_id: str,
    author_username: str | None,
    tweet_content: str,
    keyword_matched: str,
    score: int,
    signals: list[str],
) -> bool:
    """Record low-score outreach tweet as wiki learning sample. Returns True if saved."""
    key = f"outreach_sample_{twitter_post_id}"
    async with get_session() as session:
        existing = await session.execute(
            select(AgentWiki).where(AgentWiki.key == key)
        )
        if existing.scalar_one_or_none():
            return False

        content = "\n".join(
            [
                f"Tweet ID: {twitter_post_id}",
                f"Author: @{author_username or 'unknown'}",
                f"Query keyword: {keyword_matched}",
                f"Score: {score} (below reply threshold)",
                f"Signals: {', '.join(signals)}",
                f"Content:\n{tweet_content}",
            ]
        )
        session.add(
            AgentWiki(
                category=WikiCategory.OUTREACH_SAMPLE,
                key=key,
                content=content,
                source_ids=None,
            )
        )
        await session.commit()
    return True


# ─── HELPERS ─────────────────────────────────────────────────────────────────


def _action_to_category(action: str) -> WikiCategory:
    return {
        "approve": WikiCategory.APPROVED_PATTERN,
        "reject": WikiCategory.REJECTION_PATTERN,
        "revise": WikiCategory.REVISION_PATTERN,
    }.get(action, WikiCategory.APPROVED_PATTERN)


def _format_existing_wiki(entries: list) -> str:
    if not entries:
        return ""
    return "\n\n".join(f"key: {e.key}\ncontent: {e.content}" for e in entries)


def _build_feedback_context(
    action: str,
    source_type: str,
    content: str,
    revision_note: str = None,
) -> str:
    action_label = {
        "approve": "DIAPPROVE oleh owner",
        "reject": "DIREJECT oleh owner",
        "revise": "DIMINTA REVISI oleh owner",
    }.get(action, action.upper())

    lines = [
        f"Tipe konten: {source_type}",
        f"Status: {action_label}",
        f"Konten:\n{content}",
    ]
    if action == "reject":
        if revision_note:
            lines.append(f"Alasan reject dari owner: {revision_note}")
        else:
            lines.append("Alasan reject: (tidak diberikan owner)")
    elif revision_note:
        lines.append(f"Catatan revisi dari owner: {revision_note}")

    return "\n".join(lines)
