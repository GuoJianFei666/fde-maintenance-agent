"""Validate alarm events, tool inputs, and human approval."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

ShortText = Annotated[str, Field(min_length=2, max_length=300)]
DeviceId = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9-]{1,30}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AlarmEvent(InputModel):
    event_id: str = Field(min_length=1, max_length=100)
    device_id: DeviceId
    message: str = Field(min_length=3, max_length=2000)
    severity: Literal["info", "warning", "critical"] = "warning"


class DeviceQuery(InputModel):
    device_id: DeviceId


class ManualQuery(InputModel):
    query: str = Field(min_length=2, max_length=160)
    top_k: int = Field(default=3, ge=1, le=5)


class WorkOrderDraft(InputModel):
    summary: str = Field(min_length=5, max_length=200)
    priority: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    checks: list[ShortText] = Field(min_length=1, max_length=6)
    rationale: str = Field(min_length=5, max_length=1200)


class Approval(InputModel):
    approved: StrictBool
    proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str = Field(default="", max_length=500)


class NotFoundError(Exception):
    """A requested demo entity does not exist."""


class ConflictError(Exception):
    """A request conflicts with a stored event or decision."""


class MissingModelConfig(Exception):
    """No local model credential is configured."""


class ModelCallError(Exception):
    """A provider call failed; the message contains only a safe category."""


class ToolInputError(Exception):
    """A model-selected tool input violates a business constraint."""
