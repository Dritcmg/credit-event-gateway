from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class CreditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: Identifier
    application_id: Identifier
    sequence: Annotated[int, Field(ge=1, le=2147483647)]
    event_type: Literal["submitted", "approved", "declined", "funded"]
    occurred_at: AwareDatetime


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    application_id: str
    sequence: int
    event_type: str
    status: str
    attempts: int
    reason: str | None
    created_at: datetime


class ApplicationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    application_id: str
    status: str
    last_sequence: int
