import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BaseEntity:
    """Mixin providing created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.now, onupdate=datetime.now
    )


class WikiCategory(enum.Enum):
    APPROVED_PATTERN = "approved_pattern"
    REJECTION_PATTERN = "rejection_pattern"
    REVISION_PATTERN = "revision_pattern"
    PRODUCT = "product"


class ContentBatch(BaseEntity, Base):
    __tablename__ = "content_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    research_brief: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_plan: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending")
    scheduled_from: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    scheduled_to: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    drafts: Mapped[list["ContentDraft"]] = relationship(back_populates="batch")


class ContentDraft(BaseEntity, Base):
    __tablename__ = "content_drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_batches.id", ondelete="CASCADE")
    )
    tweet_copy: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending")
    revision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    batch: Mapped["ContentBatch"] = relationship(back_populates="drafts")


class PostLog(BaseEntity, Base):
    __tablename__ = "post_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_drafts.id"))
    twitter_post_id: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.now
    )
    status: Mapped[str] = mapped_column(Text, default="success")


class ReplyCandidate(BaseEntity, Base):
    __tablename__ = "reply_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    twitter_post_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    author_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    tweet_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_matched: Mapped[str | None] = mapped_column(Text, nullable=True)
    react_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    react_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    replied_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    scanned_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.now
    )


class AgentWiki(BaseEntity, Base):
    __tablename__ = "agent_wiki"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category: Mapped[WikiCategory] = mapped_column(
        Enum(
            WikiCategory,
            name="wikicategory",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids: Mapped[list | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True
    )
