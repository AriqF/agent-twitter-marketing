from typing import Optional, TypedDict


class AgentState(TypedDict):
    research_brief: dict
    content_plan: list[dict]
    content_drafts: list[dict]
    batch_id: Optional[str]
    approval_status: Optional[str]
    error: Optional[str]
