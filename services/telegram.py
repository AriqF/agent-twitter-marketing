import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from telegram.request import HTTPXRequest

from sqlalchemy import func, select

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID, TELEGRAM_REQUEST_TIMEOUT
from db.models import (
    ContentBatch,
    ContentDraft,
    ContentDraftStatus,
    ReplyCandidate,
    ReplyDecision,
    ReplyCandidateStatus,
)
from db.session import get_session
from services.alerts import notify_owner
from services.batch_status import sync_batch_status
from services.wiki_writer import process_feedback

logger = logging.getLogger(__name__)

_bot = None
_MAX_VIEW_ITEMS = 10
_TELEGRAM_TEXT_LIMIT = 4000
_BOT_INTRO = (
    "Bot ini membantu owner agent untuk mengelola content plan, "
    "reply candidate, approval, dan publish langsung dari Telegram."
)
_COMMAND_CATALOG = [
    {
        "name": "/start",
        "usage": "/start",
        "description": "Intro singkat bot dan status akses akun Telegram Anda.",
        "owner_only": False,
    },
    {
        "name": "/help",
        "usage": "/help",
        "description": "Lihat daftar command yang tersedia beserta fungsi singkatnya.",
        "owner_only": False,
    },
    {
        "name": "/create_plan",
        "usage": "/create_plan",
        "description": "Jalankan siklus pembuatan content plan dan draft baru.",
        "owner_only": True,
    },
    {
        "name": "/view_plan",
        "usage": "/view_plan",
        "description": "Lihat content plan terbaru beserta ringkasan status draft-nya.",
        "owner_only": True,
    },
        {
        "name": "/view_replies",
        "usage": "/view_replies <status>",
        "description": "Lihat reply candidate dengan react decision reply, bisa difilter status.",
        "owner_only": True,
    },
    {
        "name": "/publish_reply",
        "usage": "/publish_reply <id>",
        "description": "Publish satu reply candidate APPROVED langsung berdasarkan id.",
        "owner_only": True,
    },
    {
        "name": "/view_content",
        "usage": "/view_content <status>",
        "description": "Lihat draft content minggu ini berdasarkan scheduled at.",
        "owner_only": True,
    },
    {
        "name": "/publish_content",
        "usage": "/publish_content <id>",
        "description": "Publish satu draft content APPROVED langsung berdasarkan id.",
        "owner_only": True,
    },
    {
        "name": "/search_reply",
        "usage": "/search_reply",
        "description": "Scan tweet baru untuk outreach reply dan kirim kandidat ke Telegram.",
        "owner_only": True,
    }
]


def _build_request() -> HTTPXRequest:
    timeout = TELEGRAM_REQUEST_TIMEOUT
    return HTTPXRequest(
        connect_timeout=timeout,
        read_timeout=timeout,
        write_timeout=timeout,
        pool_timeout=timeout,
    )


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN, request=_build_request())
    return _bot


def set_bot(bot: Bot) -> None:
    """Use the Application's bot instance (shared timeouts/session)."""
    global _bot
    _bot = bot


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
    "pending": "🕒 *Draft Konten — Pending*\n\n",
    "approved": "✅ *Draft Konten — Approved*\n\n",
    "revised": "✏️ *Draft Konten — Revisi*\n\n",
    "rejected": "❌ *Draft Konten — Rejected*\n\n",
    "completed": "📤 *Draft Konten — Completed*\n\n",
}

_REPLY_HEADERS = {
    None: "💬 *Reply Candidate*\n\n",
    "pending": "🕒 *Reply Candidate — Pending*\n\n",
    "approved": "✅ *Reply Candidate — Approved*\n\n",
    "revised": "✏️ *Reply Candidate — Revisi*\n\n",
    "rejected": "❌ *Reply Candidate — Rejected*\n\n",
    "skipped": "⏭️ *Reply Candidate — Skipped*\n\n",
    "posted": "📤 *Reply Candidate — Posted*\n\n",
}


def _status_key(status) -> str | None:
    if status is None:
        return None
    return status.value if hasattr(status, "value") else str(status)


def _truncate_message(text: str, *, limit: int = _TELEGRAM_TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 17] + "\n... (truncated)"


def _allowed_statuses(enum_cls) -> str:
    return ", ".join(member.value for member in enum_cls)


def _parse_status_arg(raw_value: str | None, enum_cls):
    if not raw_value:
        return None

    normalized = raw_value.strip().lower()
    if normalized == "all":
        return None

    try:
        return enum_cls(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Status tidak valid: `{normalized}`. Pilihan: {_allowed_statuses(enum_cls)}, all."
        ) from exc


def _current_week_range() -> tuple[datetime, datetime]:
    now = datetime.now()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return week_start, week_start + timedelta(days=7)


async def _send_formatted_items(
    update: Update,
    *,
    summary_lines: list[str],
    items: list,
    formatter,
) -> None:
    await update.message.reply_text("\n".join(summary_lines), parse_mode="Markdown")

    for item in items:
        text = _truncate_message(formatter(item, status=item.status))
        await update.message.reply_text(text, parse_mode="Markdown")


def _format_help_message(*, is_owner: bool) -> str:
    public_commands = [entry for entry in _COMMAND_CATALOG if not entry["owner_only"]]
    owner_commands = [entry for entry in _COMMAND_CATALOG if entry["owner_only"]]

    lines = [
        "*Daftar Command Telegram*",
        "",
        "*Umum*",
    ]
    for entry in public_commands:
        lines.append(f"`{entry['usage']}`")
        lines.append(entry["description"])
        lines.append("")

    lines.append("*Owner only*")
    for entry in owner_commands:
        description = entry["description"]
        if not is_owner:
            description += " _(hanya untuk owner)_"
        lines.append(f"`{entry['usage']}`")
        lines.append(description)
        lines.append("")

    if not is_owner:
        lines.append("Akun Telegram ini bukan owner, jadi command operasional tidak bisa dijalankan.")
    else:
        lines.append("Akun Telegram ini terdaftar sebagai owner agent.")

    return _truncate_message("\n".join(lines))


def _format_start_message(*, is_owner: bool) -> str:
    access_label = "OWNER" if is_owner else "NON-OWNER"
    lines = [
        "*AI Marketing Agent Bot*",
        "",
        _BOT_INTRO,
        "",
        f"Status akses: *{access_label}*",
    ]
    if is_owner:
        lines.append("Anda bisa menjalankan command operasional seperti approval, review, dan publish langsung.")
    else:
        lines.append("Akun ini tidak memiliki akses untuk command operasional owner.")
    lines.extend(
        [
            "",
            "Gunakan `/help` untuk melihat daftar command yang tersedia.",
        ]
    )
    return _truncate_message("\n".join(lines))


def _format_draft_message(draft, *, status: str | ContentDraftStatus | None = None) -> str:
    status_key = _status_key(status)
    schedule = draft.scheduled_at.strftime("%d %b %Y %H:%M")
    header = _DRAFT_HEADERS.get(status_key, _DRAFT_HEADERS[None])

    footers = {
        "approved": f"\n\n✅ *Approved* — publish: {schedule} WIB",
        "revised": "\n\n✏️ *Menunggu catatan revisi* — ketik catatan revisi di chat.",
    }
    if status_key == "rejected":
        if draft.revision_note:
            footer = f"\n\n❌ *Rejected*\nAlasan: {_md(draft.revision_note)}"
        else:
            footer = (
                "\n\n❌ *Rejected* — ketik alasan di chat (opsional) atau Lewati."
            )
    else:
        footer = footers.get(status_key, "")

    return (
        f"{header}"
        f"📅 Jadwal: {schedule} WIB\n\n"
        f"{_md_code_block(draft.tweet_copy)}"
        f"{footer}"
    )


async def send_batch_for_approval(batch_id: str, drafts: list):
    bot = get_bot()
    for draft in drafts:
        try:
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
        except Exception:
            logger.exception("Failed to send draft approval draft_id=%s", draft.id)


def _format_reply_message(
    candidate, *, status: str | ReplyCandidateStatus | None = None
) -> str:
    status_key = _status_key(status)
    header = _REPLY_HEADERS.get(status_key, _REPLY_HEADERS[None])

    footers = {
        "approved": "\n\n✅ *Approved* — akan dipublish pada cycle berikutnya.",
        "revised": "\n\n✏️ *Menunggu teks reply revisi* — ketik teks reply baru di chat.",
    }
    if status_key == "rejected":
        if candidate.revision_note:
            footer = f"\n\n❌ *Rejected*\nAlasan: {_md(candidate.revision_note)}"
        else:
            footer = (
                "\n\n❌ *Rejected* — ketik alasan di chat (opsional) atau Lewati."
            )
    else:
        footer = footers.get(status_key, "")

    return (
        f"{header}"
        f"👤 @{_md(candidate.author_username)}\n"
        f"🔍 Keyword: {_md(candidate.keyword_matched)}\n\n"
        f"*Original tweet:*\nhttps://x.com/{candidate.author_username}/status/{candidate.twitter_post_id}\n{_md_code_block(candidate.tweet_content)}\n\n"
        f"*AI reasoning:*\n{_md_code_block(candidate.react_reasoning)}\n\n"
        f"*Suggested reply:*\n{_md_code_block(candidate.reply_text)}"
        f"{footer}"
    )


async def send_reply_for_approval(candidate: ReplyCandidate):
    try:
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
    except Exception:
        logger.exception(
            "Failed to send reply approval candidate_id=%s", candidate.id
        )


async def _send_reject_reason_prompt(entity_type: str, entity_id: str) -> None:
    bot = get_bot()
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Lewati",
                    callback_data=f"reject_skip:{entity_type}:{entity_id}",
                )
            ]
        ]
    )
    await bot.send_message(
        chat_id=TELEGRAM_OWNER_CHAT_ID,
        text="Berikan alasan reject (opsional). Ketik di chat atau Lewati.",
        reply_markup=keyboard,
    )


def _pending_matches(pending: dict | None, entity_type: str, entity_id: str) -> bool:
    return (
        pending is not None
        and pending.get("type") == entity_type
        and pending.get("id") == entity_id
        and pending.get("action") == "reject"
    )


async def _complete_reject_feedback(
    pending: dict,
    *,
    revision_note: str | None,
) -> None:
    asyncio.create_task(
        process_feedback(
            source_id=_parse_uuid(pending["id"]),
            source_type=pending["type"],
            action="reject",
            content=pending.get("content", ""),
            revision_note=revision_note,
        )
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        if query.data.startswith("reject_skip:"):
            _, entity_type, entity_id = query.data.split(":", 2)
            pending = context.user_data.get("pending_feedback")
            if not _pending_matches(pending, entity_type, entity_id):
                await query.answer("Reject sudah diproses atau tidak valid.", show_alert=True)
                return

            await query.answer()
            await _complete_reject_feedback(pending, revision_note=None)
            context.user_data.pop("pending_feedback", None)
            await query.edit_message_text("Reject tanpa alasan — diproses ke Agent Wiki.")
            return

        await query.answer()

        action, entity_id = query.data.split(":", 1)
        entity_uuid = _parse_uuid(entity_id)

        async with get_session() as session:
            if action in ("approve", "revise", "reject"):
                draft = await session.get(ContentDraft, entity_uuid)

                if action == "approve":
                    draft.status = ContentDraftStatus.APPROVED
                    draft.approved_at = datetime.now()
                    await query.edit_message_text(
                        text=_format_draft_message(
                            draft, status=ContentDraftStatus.APPROVED
                        ),
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
                    await sync_batch_status(draft.batch_id, session)

                elif action == "revise":
                    draft.status = ContentDraftStatus.REVISED
                    await query.edit_message_text(
                        text=_format_draft_message(
                            draft, status=ContentDraftStatus.REVISED
                        ),
                        parse_mode="Markdown",
                        reply_markup=None,
                    )
                    context.user_data["pending_feedback"] = {
                        "type": "draft",
                        "action": "revise",
                        "id": entity_id,
                        "content": draft.tweet_copy,
                    }
                    await sync_batch_status(draft.batch_id, session)

                elif action == "reject":
                    draft.status = ContentDraftStatus.REJECTED
                    await query.edit_message_text(
                        text=_format_draft_message(
                            draft, status=ContentDraftStatus.REJECTED
                        ),
                        parse_mode="Markdown",
                        reply_markup=None,
                    )
                    context.user_data["pending_feedback"] = {
                        "type": "draft",
                        "action": "reject",
                        "id": entity_id,
                        "content": draft.tweet_copy,
                    }
                    await sync_batch_status(draft.batch_id, session)
                    await session.commit()
                    await _send_reject_reason_prompt("draft", entity_id)
                    return

            elif action in ("reply_approve", "reply_revise", "reply_reject"):
                candidate = await session.get(ReplyCandidate, entity_uuid)

                if action == "reply_approve":
                    candidate.status = ReplyCandidateStatus.APPROVED
                    candidate.approved_at = datetime.now()
                    await query.edit_message_text(
                        text=_format_reply_message(
                            candidate, status=ReplyCandidateStatus.APPROVED
                        ),
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
                    candidate.status = ReplyCandidateStatus.REVISED
                    await query.edit_message_text(
                        text=_format_reply_message(
                            candidate, status=ReplyCandidateStatus.REVISED
                        ),
                        parse_mode="Markdown",
                        reply_markup=None,
                    )
                    context.user_data["pending_feedback"] = {
                        "type": "reply",
                        "action": "revise",
                        "id": entity_id,
                        "content": candidate.reply_text,
                    }

                elif action == "reply_reject":
                    candidate.status = ReplyCandidateStatus.REJECTED
                    await query.edit_message_text(
                        text=_format_reply_message(
                            candidate, status=ReplyCandidateStatus.REJECTED
                        ),
                        parse_mode="Markdown",
                        reply_markup=None,
                    )
                    context.user_data["pending_feedback"] = {
                        "type": "reply",
                        "action": "reject",
                        "id": entity_id,
                        "content": candidate.reply_text,
                    }
                    await session.commit()
                    await _send_reject_reason_prompt("reply", entity_id)
                    return

            await session.commit()
    except Exception:
        logger.exception("handle_callback failed data=%s", query.data)
        await query.answer("Terjadi error. Coba lagi.", show_alert=True)


async def handle_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return

    pending = context.user_data.get("pending_feedback")
    if not pending:
        return

    try:
        feedback_text = (update.message.text or "").strip()
        feedback_action = pending.get("action")

        async with get_session() as session:
            if pending["type"] == "draft":
                draft = await session.get(ContentDraft, _parse_uuid(pending["id"]))

                if feedback_action == "revise":
                    draft.revision_note = feedback_text
                    draft.status = ContentDraftStatus.PENDING
                    await sync_batch_status(draft.batch_id, session)
                    await update.message.reply_text(
                        "Catatan revisi tersimpan. Draft akan diregenerate pada cycle berikutnya."
                    )
                    asyncio.create_task(
                        process_feedback(
                            source_id=draft.id,
                            source_type="draft",
                            action="revise",
                            content=pending.get("content", ""),
                            revision_note=feedback_text,
                        )
                    )

                elif feedback_action == "reject":
                    revision_note = feedback_text or None
                    if revision_note:
                        draft.revision_note = revision_note
                    await update.message.reply_text(
                        "Alasan reject tersimpan — diproses ke Agent Wiki."
                        if revision_note
                        else "Reject tanpa alasan — diproses ke Agent Wiki."
                    )
                    await _complete_reject_feedback(
                        pending, revision_note=revision_note
                    )

            elif pending["type"] == "reply":
                candidate = await session.get(
                    ReplyCandidate, _parse_uuid(pending["id"])
                )
                old_content = pending.get("content", "")

                if feedback_action == "revise":
                    candidate.reply_text = feedback_text
                    candidate.status = ReplyCandidateStatus.PENDING
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
                            revision_note=feedback_text,
                        )
                    )
                    context.user_data.pop("pending_feedback", None)
                    return

                elif feedback_action == "reject":
                    revision_note = feedback_text or None
                    if revision_note:
                        candidate.revision_note = revision_note
                    await session.commit()
                    await update.message.reply_text(
                        "Alasan reject tersimpan — diproses ke Agent Wiki."
                        if revision_note
                        else "Reject tanpa alasan — diproses ke Agent Wiki."
                    )
                    await _complete_reject_feedback(
                        pending, revision_note=revision_note
                    )

            await session.commit()

        context.user_data.pop("pending_feedback", None)
    except Exception:
        logger.exception("handle_feedback_message failed pending=%s", pending)
        await update.message.reply_text(
            "Terjadi error saat menyimpan feedback. Coba lagi."
        )


# ─── OWNER GUARD ─────────────────────────────────────────────────────────────


def _is_owner(update: Update) -> bool:
    chat_id = update.effective_chat.id
    return str(chat_id) == str(TELEGRAM_OWNER_CHAT_ID)


# ─── COMMAND HANDLERS ────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    await update.message.reply_text(
        _format_start_message(is_owner=_is_owner(update)),
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    await update.message.reply_text(
        _format_help_message(is_owner=_is_owner(update)),
        parse_mode="Markdown",
    )


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

        result = await run_agent_graph()
        if result is not None:
            await notify_owner(
                "Content plan berhasil dibuat! Draft sudah dikirim untuk approval."
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
        f"Status: {_status_key(batch.status)}",
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
            draft_status = (
                _status_key(drafts[slot_idx].status)
                if slot_idx < len(drafts)
                else "-"
            )

            lines.append(f"{best_time} WIB | {draft_status}")
            lines.append(f"Topik: {topic}")
            lines.append(f"Angle: {angle}")
            lines.append("")

    status_counts: dict[str, int] = {}
    for d in drafts:
        key = _status_key(d.status) or "-"
        status_counts[key] = status_counts.get(key, 0) + 1
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


async def cmd_view_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        await update.message.reply_text("Unauthorized.")
        return

    try:
        reply_status = _parse_status_arg(
            context.args[0] if context.args else None,
            ReplyCandidateStatus,
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc), parse_mode="Markdown")
        return

    filters = [ReplyCandidate.react_decision == ReplyDecision.REPLY]
    if reply_status is not None:
        filters.append(ReplyCandidate.status == reply_status)

    async with get_session() as session:
        count_result = await session.execute(
            select(func.count()).select_from(ReplyCandidate).where(*filters)
        )
        total_count = count_result.scalar_one()

        result = await session.execute(
            select(ReplyCandidate)
            .where(*filters)
            .order_by(ReplyCandidate.created_at.desc())
            .limit(_MAX_VIEW_ITEMS)
        )
        candidates = result.scalars().all()

    status_label = reply_status.value if reply_status else "semua status"
    if not candidates:
        await update.message.reply_text(
            (
                "Tidak ada reply candidate ditemukan.\n"
                f"Filter status: {status_label}\n"
                "Kondisi tetap membatasi ke react_decision=reply."
            )
        )
        return

    summary_lines = [
        "*Reply Candidates*",
        f"Filter status: `{status_label}`",
        f"Total: {total_count}",
        f"Menampilkan: {len(candidates)} terbaru",
    ]
    if total_count > len(candidates):
        summary_lines.append(
            f"Ada {total_count - len(candidates)} item lain yang tidak ditampilkan."
        )

    await _send_formatted_items(
        update,
        summary_lines=summary_lines,
        items=candidates,
        formatter=_format_reply_message,
    )


async def cmd_view_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        await update.message.reply_text("Unauthorized.")
        return

    try:
        draft_status = _parse_status_arg(
            context.args[0] if context.args else None,
            ContentDraftStatus,
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc), parse_mode="Markdown")
        return

    week_start, week_end = _current_week_range()
    filters = [
        ContentDraft.scheduled_at >= week_start,
        ContentDraft.scheduled_at < week_end,
    ]
    if draft_status is not None:
        filters.append(ContentDraft.status == draft_status)

    async with get_session() as session:
        count_result = await session.execute(
            select(func.count()).select_from(ContentDraft).where(*filters)
        )
        total_count = count_result.scalar_one()

        result = await session.execute(
            select(ContentDraft)
            .where(*filters)
            .order_by(ContentDraft.scheduled_at, ContentDraft.created_at)
            .limit(_MAX_VIEW_ITEMS)
        )
        drafts = result.scalars().all()

    status_label = draft_status.value if draft_status else "semua status"
    week_label = (
        f"{week_start.strftime('%d %b %Y')} - "
        f"{(week_end - timedelta(days=1)).strftime('%d %b %Y')}"
    )
    if not drafts:
        await update.message.reply_text(
            (
                "Tidak ada draft content ditemukan.\n"
                f"Week: {week_label}\n"
                f"Filter status: {status_label}"
            )
        )
        return

    summary_lines = [
        "*Content Drafts Minggu Ini*",
        f"Week: `{week_label}`",
        f"Filter status: `{status_label}`",
        f"Total: {total_count}",
        f"Menampilkan: {len(drafts)} item",
    ]
    if total_count > len(drafts):
        summary_lines.append(
            f"Ada {total_count - len(drafts)} item lain yang tidak ditampilkan."
        )

    await _send_formatted_items(
        update,
        summary_lines=summary_lines,
        items=drafts,
        formatter=_format_draft_message,
    )


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
            return "Reply cycle selesai. Scan dilewati — tidak ada conversation_keywords dikonfigurasi."
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

        scan_result = await run_reply_cycle()
        if scan_result is not None:
            await notify_owner(_format_reply_cycle_message(scan_result))

    asyncio.create_task(_run_and_notify())


def _parse_required_id_arg(args: list[str], command_name: str) -> uuid.UUID:
    if not args:
        raise ValueError(f"Gunakan /{command_name} <id>")

    try:
        return _parse_uuid(args[0])
    except ValueError as exc:
        raise ValueError(f"ID tidak valid untuk /{command_name}.") from exc


async def cmd_publish_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        await update.message.reply_text("Unauthorized.")
        return

    try:
        candidate_id = _parse_required_id_arg(context.args, "publish_reply")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        f"Sedang publish reply `{candidate_id}` secara langsung...",
        parse_mode="Markdown",
    )

    async def _run_and_notify():
        from scheduler.jobs import publish_reply_by_id

        try:
            result = await publish_reply_by_id(candidate_id)
        except ValueError as exc:
            await update.message.reply_text(f"Gagal publish reply: {exc}")
            return
        except Exception as exc:
            logger.exception("cmd_publish_reply failed candidate_id=%s", candidate_id)
            await update.message.reply_text(
                f"Terjadi error saat publish reply {candidate_id}: {str(exc)[:200]}"
            )
            return

        await update.message.reply_text(
            (
                "Reply berhasil dipublish.\n"
                f"ID: `{result['id']}`\n"
                f"Reply Tweet ID: `{result['posted_reply_id']}`\n"
                f"Target Tweet: `{result['target_twitter_post_id']}`\n"
                f"Status: `{result['status']}`"
            ),
            parse_mode="Markdown",
        )

    asyncio.create_task(_run_and_notify())


async def cmd_publish_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        await update.message.reply_text("Unauthorized.")
        return

    try:
        draft_id = _parse_required_id_arg(context.args, "publish_content")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        f"Sedang publish draft `{draft_id}` secara langsung...",
        parse_mode="Markdown",
    )

    async def _run_and_notify():
        from scheduler.jobs import publish_draft_by_id

        try:
            result = await publish_draft_by_id(draft_id)
        except ValueError as exc:
            await update.message.reply_text(f"Gagal publish draft: {exc}")
            return
        except Exception as exc:
            logger.exception("cmd_publish_content failed draft_id=%s", draft_id)
            await update.message.reply_text(
                f"Terjadi error saat publish draft {draft_id}: {str(exc)[:200]}"
            )
            return

        await update.message.reply_text(
            (
                "Draft content berhasil dipublish.\n"
                f"ID: `{result['id']}`\n"
                f"Tweet ID: `{result['twitter_post_id']}`\n"
                f"Status: `{result['status']}`"
            ),
            parse_mode="Markdown",
        )

    asyncio.create_task(_run_and_notify())
