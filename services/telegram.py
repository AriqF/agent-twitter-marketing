import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from sqlalchemy import func, select

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID
from db.models import ContentBatch, ContentDraft, ReplyCandidate
from db.session import get_session
from services.wiki_writer import process_feedback

logger = logging.getLogger(__name__)

_bot = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


def _parse_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def _md(text: str | None) -> str:
    if not text:
        return ""
    return escape_markdown(text, version=1)


def _md_code_block(text: str | None) -> str:
    safe = (text or "").replace("```", "'''")
    return f"```\n{safe}\n```"


_DRAFT_HEADERS = {
    None: "📝 *Draft Konten*\n\n",
    "approved": "✅ *Draft Konten — Approved*\n\n",
    "revised": "✏️ *Draft Konten — Revisi*\n\n",
    "rejected": "❌ *Draft Konten — Rejected*\n\n",
}

_REPLY_HEADERS = {
    None: "💬 *Reply Candidate*\n\n",
    "approved": "✅ *Reply Candidate — Approved*\n\n",
    "revised": "✏️ *Reply Candidate — Revisi*\n\n",
    "rejected": "❌ *Reply Candidate — Rejected*\n\n",
}


def _format_draft_message(draft, *, status: str | None = None) -> str:
    schedule = draft.scheduled_at.strftime("%d %b %Y %H:%M")
    header = _DRAFT_HEADERS.get(status, _DRAFT_HEADERS[None])

    footers = {
        "approved": f"\n\n✅ *Approved* — publish: {schedule} WIB",
        "revised": "\n\n✏️ *Menunggu catatan revisi* — ketik catatan revisi di chat.",
        "rejected": "\n\n❌ *Rejected* — draft tidak akan dipublish.",
    }
    footer = footers.get(status, "")

    return (
        f"{header}"
        f"📅 Jadwal: {schedule} WIB\n\n"
        f"{_md_code_block(draft.tweet_copy)}"
        f"{footer}"
    )


async def send_batch_for_approval(batch_id: str, drafts: list):
    bot = get_bot()
    for draft in drafts:
        text = _format_draft_message(draft)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve", callback_data=f"approve:{draft.id}"
                    ),
                    InlineKeyboardButton(
                        "✏️ Revisi", callback_data=f"revise:{draft.id}"
                    ),
                    InlineKeyboardButton(
                        "❌ Reject", callback_data=f"reject:{draft.id}"
                    ),
                ]
            ]
        )

        await bot.send_message(
            chat_id=TELEGRAM_OWNER_CHAT_ID,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


def _format_reply_message(candidate, *, status: str | None = None) -> str:
    header = _REPLY_HEADERS.get(status, _REPLY_HEADERS[None])

    footers = {
        "approved": "\n\n✅ *Approved* — akan dipublish pada cycle berikutnya.",
        "revised": "\n\n✏️ *Menunggu teks reply revisi* — ketik teks reply baru di chat.",
        "rejected": "\n\n❌ *Rejected* — reply tidak akan dipublish.",
    }
    footer = footers.get(status, "")

    return (
        f"{header}"
        f"👤 @{_md(candidate.author_username)}\n"
        f"🔍 Keyword: {_md(candidate.keyword_matched)}\n\n"
        f"*Original tweet:*\n{_md_code_block(candidate.tweet_content)}\n\n"
        f"*AI reasoning:*\n{_md_code_block(candidate.react_reasoning)}\n\n"
        f"*Suggested reply:*\n{_md_code_block(candidate.reply_text)}"
        f"{footer}"
    )


async def send_reply_for_approval(candidate: ReplyCandidate):
    bot = get_bot()
    text = _format_reply_message(candidate)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve", callback_data=f"reply_approve:{candidate.id}"
                ),
                InlineKeyboardButton(
                    "✏️ Revisi", callback_data=f"reply_revise:{candidate.id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject", callback_data=f"reply_reject:{candidate.id}"
                ),
            ]
        ]
    )

    await bot.send_message(
        chat_id=TELEGRAM_OWNER_CHAT_ID,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, entity_id = query.data.split(":", 1)
    entity_uuid = _parse_uuid(entity_id)

    async with get_session() as session:
        if action in ("approve", "revise", "reject"):
            draft = await session.get(ContentDraft, entity_uuid)

            if action == "approve":
                draft.status = "approved"
                draft.approved_at = datetime.now()
                await query.edit_message_text(
                    text=_format_draft_message(draft, status="approved"),
                    parse_mode="Markdown",
                    reply_markup=None,
                )
                asyncio.create_task(
                    process_feedback(
                        source_id=draft.id,
                        source_type="draft",
                        action="approve",
                        content=draft.tweet_copy,
                    )
                )

            elif action == "revise":
                draft.status = "revised"
                await query.edit_message_text(
                    text=_format_draft_message(draft, status="revised"),
                    parse_mode="Markdown",
                    reply_markup=None,
                )
                context.user_data["pending_revision"] = {
                    "type": "draft",
                    "id": entity_id,
                    "content": draft.tweet_copy,
                }

            elif action == "reject":
                draft.status = "rejected"
                await query.edit_message_text(
                    text=_format_draft_message(draft, status="rejected"),
                    parse_mode="Markdown",
                    reply_markup=None,
                )
                asyncio.create_task(
                    process_feedback(
                        source_id=draft.id,
                        source_type="draft",
                        action="reject",
                        content=draft.tweet_copy,
                    )
                )

        elif action in ("reply_approve", "reply_revise", "reply_reject"):
            candidate = await session.get(ReplyCandidate, entity_uuid)

            if action == "reply_approve":
                candidate.status = "approved"
                candidate.approved_at = datetime.now()
                await query.edit_message_text(
                    text=_format_reply_message(candidate, status="approved"),
                    parse_mode="Markdown",
                    reply_markup=None,
                )
                asyncio.create_task(
                    process_feedback(
                        source_id=candidate.id,
                        source_type="reply",
                        action="approve",
                        content=candidate.reply_text,
                    )
                )

            elif action == "reply_revise":
                candidate.status = "revised"
                await query.edit_message_text(
                    text=_format_reply_message(candidate, status="revised"),
                    parse_mode="Markdown",
                    reply_markup=None,
                )
                context.user_data["pending_revision"] = {
                    "type": "reply",
                    "id": entity_id,
                    "content": candidate.reply_text,
                }

            elif action == "reply_reject":
                candidate.status = "rejected"
                await query.edit_message_text(
                    text=_format_reply_message(candidate, status="rejected"),
                    parse_mode="Markdown",
                    reply_markup=None,
                )
                asyncio.create_task(
                    process_feedback(
                        source_id=candidate.id,
                        source_type="reply",
                        action="reject",
                        content=candidate.reply_text,
                    )
                )

        await session.commit()


async def handle_revision_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = context.user_data.get("pending_revision")
    if not pending:
        return

    revision_note = update.message.text

    async with get_session() as session:
        if pending["type"] == "draft":
            draft = await session.get(ContentDraft, _parse_uuid(pending["id"]))
            draft.revision_note = revision_note
            draft.status = "pending"
            await update.message.reply_text(
                "Catatan revisi tersimpan. Draft akan diregenerate pada cycle berikutnya."
            )
            asyncio.create_task(
                process_feedback(
                    source_id=draft.id,
                    source_type="draft",
                    action="revise",
                    content=pending.get("content", ""),
                    revision_note=revision_note,
                )
            )

        elif pending["type"] == "reply":
            candidate = await session.get(ReplyCandidate, _parse_uuid(pending["id"]))
            old_content = pending.get("content", "")
            candidate.reply_text = revision_note
            candidate.status = "pending"
            await session.commit()
            await send_reply_for_approval(candidate)
            await update.message.reply_text(
                "Reply direvisi. Silakan approve dari pesan baru di atas."
            )
            asyncio.create_task(
                process_feedback(
                    source_id=candidate.id,
                    source_type="reply",
                    action="revise",
                    content=old_content,
                    revision_note=revision_note,
                )
            )
            context.user_data.pop("pending_revision", None)
            return

        await session.commit()

    context.user_data.pop("pending_revision", None)


# ─── OWNER GUARD ─────────────────────────────────────────────────────────────


def _is_owner(update: Update) -> bool:
    chat_id = update.effective_chat.id
    return str(chat_id) == str(TELEGRAM_OWNER_CHAT_ID)


# ─── COMMAND HANDLERS ────────────────────────────────────────────────────────


async def cmd_create_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /create_plan command. Runs full agent graph cycle."""
    if not _is_owner(update):
        await update.message.reply_text("Unauthorized.")
        return

    await update.message.reply_text(
        "Sedang membuat content plan... Ini mungkin memakan waktu beberapa menit."
    )

    async def _run_and_notify():
        from scheduler.jobs import run_agent_graph

        try:
            await run_agent_graph()
            bot = get_bot()
            await bot.send_message(
                chat_id=TELEGRAM_OWNER_CHAT_ID,
                text="Content plan berhasil dibuat! Draft sudah dikirim untuk approval.",
            )
        except Exception as e:
            bot = get_bot()
            await bot.send_message(
                chat_id=TELEGRAM_OWNER_CHAT_ID,
                text=f"Gagal membuat content plan: {str(e)[:200]}",
            )

    asyncio.create_task(_run_and_notify())


def _format_view_plan_message(batch, drafts: list) -> str:
    slots_by_day: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    for i, slot in enumerate(batch.content_plan):
        day = slot.get("day_offset", 0)
        slots_by_day[day].append((i, slot))

    lines = [
        "*Content Plan Terbaru*",
        f"Batch: `{batch.id}`",
        f"Status: {batch.status}",
        f"Dibuat: {batch.created_at.strftime('%d %b %Y %H:%M')} WIB",
        "",
    ]

    base_date = batch.created_at.date()
    for day_offset in sorted(slots_by_day.keys()):
        day_num = day_offset + 1
        post_date = base_date + timedelta(days=day_offset)
        lines.append(f"*Hari {day_num} — {post_date.strftime('%d %b %Y')}*")

        day_slots = sorted(
            slots_by_day[day_offset],
            key=lambda x: x[1].get("best_time", "00:00"),
        )
        for slot_idx, slot in day_slots:
            best_time = slot.get("best_time", "-")
            topic = _md(slot.get("topic", "-"))
            angle = _md(slot.get("angle", "-"))
            draft_status = drafts[slot_idx].status if slot_idx < len(drafts) else "-"

            lines.append(f"{best_time} WIB | {draft_status}")
            lines.append(f"Topik: {topic}")
            lines.append(f"Angle: {angle}")
            lines.append("")

    status_counts: dict[str, int] = {}
    for d in drafts:
        status_counts[d.status] = status_counts.get(d.status, 0) + 1
    status_summary = ", ".join(f"{k}: {v}" for k, v in status_counts.items())
    lines.append("---")
    lines.append(f"Drafts: {len(drafts)} total ({status_summary})")

    return "\n".join(lines)


async def cmd_view_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /view_plan command. Shows latest content batch."""
    if not _is_owner(update):
        await update.message.reply_text("Unauthorized.")
        return

    async with get_session() as session:
        result = await session.execute(
            select(ContentBatch).order_by(ContentBatch.created_at.desc()).limit(1)
        )
        batch = result.scalar_one_or_none()

        if not batch:
            await update.message.reply_text("Belum ada content plan.")
            return

        drafts_result = await session.execute(
            select(ContentDraft)
            .where(ContentDraft.batch_id == batch.id)
            .order_by(ContentDraft.created_at)
        )
        drafts = drafts_result.scalars().all()

    text = _format_view_plan_message(batch, drafts)
    if len(text) > 4000:
        text = text[:4000] + "\n... (truncated)"

    await update.message.reply_text(text, parse_mode="Markdown")


def _format_reply_cycle_message(scan_result: dict) -> str:
    if not scan_result.get("scanned"):
        reason = scan_result.get("reason")
        pending = scan_result.get("pending", 0)
        if reason == "backlog_full":
            return (
                f"Reply cycle selesai. Scan dilewati — backlog {pending} candidate "
                "belum dianalisis. Proses backlog tetap dijalankan."
            )
        if reason == "no_keywords":
            return "Reply cycle selesai. Scan dilewati — tidak ada reply_keywords dikonfigurasi."
        return "Reply cycle selesai. Scan dilewati."

    keywords = scan_result.get("keywords", [])
    new_count = scan_result.get("new_count", 0)
    keyword_list = ", ".join(keywords) if keywords else "-"
    return (
        f"Reply cycle selesai!\n"
        f"Scan: {len(keywords)} keyword ({keyword_list})\n"
        f"Candidate baru: {new_count}\n"
        f"Reply candidates dikirim ke Telegram untuk approval (jika ada)."
    )


async def cmd_search_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /search_reply command. Runs full reply cycle."""
    if not _is_owner(update):
        await update.message.reply_text("Unauthorized.")
        return

    await update.message.reply_text(
        "Sedang scan & analisis tweet untuk direply... Ini mungkin memakan waktu."
    )

    async def _run_and_notify():
        from scheduler.jobs import run_reply_cycle

        try:
            scan_result = await run_reply_cycle()
            bot = get_bot()
            await bot.send_message(
                chat_id=TELEGRAM_OWNER_CHAT_ID,
                text=_format_reply_cycle_message(scan_result),
            )
        except Exception as e:
            bot = get_bot()
            await bot.send_message(
                chat_id=TELEGRAM_OWNER_CHAT_ID,
                text=f"Gagal scan reply: {str(e)[:200]}",
            )

    asyncio.create_task(_run_and_notify())
