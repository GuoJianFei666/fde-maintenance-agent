"""Extend the upstream message state with business and approval state."""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    run_id: str
    alarm: dict[str, Any]
    rounds: int
    status: str
    retrieved_ids: list[str]
    device_read: bool
    history_read: bool
    proposal: dict[str, Any]
    proposal_sha256: str
    approved: bool
    approval_note: str
    order: dict[str, Any]
    answer: str
    error_code: str
