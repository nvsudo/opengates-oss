from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

DecisionKind = Literal["decline", "clarify", "escalate"]
PaymentStatus = Literal["none", "paid"]
ThreadStatus = Literal["open", "waiting_on_sender", "evaluating", "escalated", "declined", "expired", "review"]
MessageRole = Literal["sender", "gate", "system"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Sender(BaseModel):
    name: str = ""
    email: str = ""


class SubmissionMetadata(BaseModel):
    payment_status: PaymentStatus = "none"
    submitted_at: datetime = Field(default_factory=utc_now)


class Submission(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    submission_id: str = Field(default_factory=lambda: f"sub_{uuid4().hex[:12]}")
    gate_id: str
    thread_id: str
    source: str = "web_thread"
    sender: Sender = Field(default_factory=Sender)
    content: str
    metadata: SubmissionMetadata = Field(default_factory=SubmissionMetadata)


class Thread(BaseModel):
    thread_id: str = Field(default_factory=lambda: f"thr_{uuid4().hex[:12]}")
    gate_id: str
    source: str = "web_thread"
    sender_key: str
    sender_name: str = ""
    sender_email: str = ""
    status: ThreadStatus = "open"
    turn_count: int = 0
    max_clarification_rounds: int = 3
    remaining_clarification_rounds: int = 3
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ThreadMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: f"msg_{uuid4().hex[:12]}")
    thread_id: str
    role: MessageRole
    channel: str = "web"
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class Decision(BaseModel):
    decision_id: str = Field(default_factory=lambda: f"dec_{uuid4().hex[:12]}")
    thread_id: str
    message_id: str
    gate_id: str
    decision: DecisionKind
    confidence: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    private_reason: str
    user_visible_reply: Optional[str] = None
    needs_review: bool = False
    remaining_clarification_rounds: int = 0

    @model_validator(mode="after")
    def validate_reply_requirements(self) -> "Decision":
        if self.decision in {"decline", "clarify"} and not self.user_visible_reply:
            raise ValueError("decline and clarify decisions require user_visible_reply")
        if self.remaining_clarification_rounds < 0:
            raise ValueError("remaining_clarification_rounds cannot be negative")
        return self


class InteractionEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    thread_id: str
    type: str
    timestamp: datetime = Field(default_factory=utc_now)
    payload: dict = Field(default_factory=dict)


class SenderProfile(BaseModel):
    sender_key: str
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    interaction_count: int = 0
    notes: list[str] = Field(default_factory=list)


class ApiThreadCreateRequest(BaseModel):
    name: str = ""
    email: str = ""
    content: str
    payment_status: PaymentStatus = "none"


class ApiSubmissionRequest(ApiThreadCreateRequest):
    pass


class ApiThreadReplyRequest(BaseModel):
    content: str
    payment_status: PaymentStatus = "none"


class ProcessedTurn(BaseModel):
    thread: Thread
    sender_message: ThreadMessage
    gate_message: Optional[ThreadMessage] = None
    decision: Decision
    sender_profile: SenderProfile


class ThreadView(BaseModel):
    thread: Thread
    messages: list[ThreadMessage]
    latest_decision: Optional[Decision] = None
