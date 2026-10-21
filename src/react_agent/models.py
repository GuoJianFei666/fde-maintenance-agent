"""Validate alarm events, tool inputs, and human approval."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

ShortText = Annotated[str, Field(min_length=2, max_length=300)]
DeviceId = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9-]{1,30}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AlarmEvent(InputModel):
    event_id: str = Field(min_length=1, max_length=100)
    device_id: DeviceId
    message: str = Field(min_length=3, max_length=2000)
    severity: Literal["info", "warning", "critical"] = "warning"


class MaintenanceText(AlarmEvent):
    message: str = Field(min_length=3, max_length=500)
    source_record_id: str | None = Field(default=None, pattern=r"^MAINTIE-GOLD-\d{4}$")

    @model_validator(mode="after")
    def check_token_limit(self):
        if len(tokenize_text(self.message)) > 160:
            raise ValueError("maintenance_text_exceeds_160_tokens")
        return self


def tokenize_text(text):
    return re.findall(r"<(?:id|num|date|sensitive)>|[A-Za-z0-9]+(?:[-'.][A-Za-z0-9]+)*|[\u4e00-\u9fff]|[^\w\s]",
                      text)


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
