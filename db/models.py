import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, TIMESTAMP, TypeDecorator
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


class EnumAsText(TypeDecorator):
    """Store Python enums as VARCHAR(50); load back as enum members."""

    impl = String(50)
    cache_ok = True

    def __init__(self, enum_cls: type[enum.Enum]):
        super().__init__()
        self.enum_cls = enum_cls

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self.enum_cls(value)


class WikiCategory(enum.Enum):
    APPROVED_PATTERN = "approved_pattern"
    REJECTION_PATTERN = "rejection_pattern"
    REVISION_PATTERN = "revision_pattern"
    PRODUCT = "product"
    OUTREACH_SAMPLE = "outreach_sample"


class ContentBatchStatus(enum.Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    PARTIALLY_APPROVED = "partially_approved"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ContentDraftStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"
    COMPLETED = "completed"


class PostLogStatus(enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"


class ReplyCandidateStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"
    SKIPPED = "skipped"
    POSTED = "posted"


class ReplyDecision(enum.Enum):
    REPLY = "reply"
    SKIP = "skip"


class ContentBatch(BaseEntity, Base):
    __tablename__ = "content_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    research_brief: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_plan: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[ContentBatchStatus] = mapped_column(
        EnumAsText(ContentBatchStatus),
        default=ContentBatchStatus.PENDING,
    )
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
    status: Mapped[ContentDraftStatus] = mapped_column(
        EnumAsText(ContentDraftStatus),
        default=ContentDraftStatus.PENDING,
    )
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
    status: Mapped[PostLogStatus] = mapped_column(
        EnumAsText(PostLogStatus),
        default=PostLogStatus.SUCCESS,
    )


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
    react_decision: Mapped[ReplyDecision | None] = mapped_column(
        EnumAsText(ReplyDecision),
        nullable=True,
    )
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ReplyCandidateStatus | None] = mapped_column(
        EnumAsText(ReplyCandidateStatus),
        nullable=True,
    )
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
        EnumAsText(WikiCategory),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids: Mapped[list | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True
    )
