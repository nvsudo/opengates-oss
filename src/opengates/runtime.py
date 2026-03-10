from __future__ import annotations

from .gates import GateLoader
from .providers import DecisionContext, DecisionProvider, HeuristicDecisionProvider
from .schemas import (
    Decision,
    InteractionEvent,
    ProcessedTurn,
    Sender,
    SenderProfile,
    Submission,
    SubmissionMetadata,
    Thread,
    ThreadMessage,
    ThreadView,
    utc_now,
)
from .storage import LocalStore


class GateRuntime:
    def __init__(
        self,
        gate_loader: GateLoader,
        store: LocalStore,
        provider: DecisionProvider | None = None,
    ):
        self.gate_loader = gate_loader
        self.store = store
        self.provider = provider or HeuristicDecisionProvider()

    def start_thread(
        self,
        gate_id: str,
        *,
        name: str = "",
        email: str = "",
        content: str,
        payment_status: str = "none",
        source: str = "web_thread",
    ) -> ProcessedTurn:
        gate = self.gate_loader.load(gate_id)
        provisional_sender_key = email.strip().lower() or name.strip().lower() or "anonymous"
        thread = Thread(
            gate_id=gate_id,
            source=source,
            sender_key=provisional_sender_key,
            sender_name=name,
            sender_email=email,
            max_clarification_rounds=gate.config.max_clarification_rounds,
            remaining_clarification_rounds=gate.config.max_clarification_rounds,
            status="open",
        )
        if provisional_sender_key == "anonymous":
            thread.sender_key = thread.thread_id

        sender = Sender(name=name, email=email)
        sender_message = ThreadMessage(
            thread_id=thread.thread_id,
            role="sender",
            channel=self._channel_from_source(source),
            content=content.strip(),
        )
        submission = Submission(
            gate_id=gate_id,
            thread_id=thread.thread_id,
            source=source,
            sender=sender,
            content=content.strip(),
            metadata=SubmissionMetadata(payment_status=payment_status),
        )
        profile = self._load_sender_profile(thread.sender_key, submission.metadata.submitted_at)
        self.store.save_thread(thread)
        return self._process_turn(thread, submission, sender_message, profile)

    def reply_to_thread(
        self,
        thread_id: str,
        *,
        content: str,
        payment_status: str = "none",
        source: str = "web_thread",
    ) -> ProcessedTurn:
        thread = self._require_thread(thread_id)
        if thread.status in {"declined", "escalated", "expired", "review"}:
            raise ValueError(f"thread '{thread_id}' is closed")

        sender = Sender(name=thread.sender_name, email=thread.sender_email)
        sender_message = ThreadMessage(
            thread_id=thread.thread_id,
            role="sender",
            channel=self._channel_from_source(source),
            content=content.strip(),
        )
        submission = Submission(
            gate_id=thread.gate_id,
            thread_id=thread.thread_id,
            source=source,
            sender=sender,
            content=content.strip(),
            metadata=SubmissionMetadata(payment_status=payment_status),
        )
        profile = self._load_sender_profile(thread.sender_key, submission.metadata.submitted_at)
        return self._process_turn(thread, submission, sender_message, profile)

    def get_thread_view(self, thread_id: str) -> ThreadView:
        thread = self._require_thread(thread_id)
        messages = self.store.load_thread_messages(thread_id)
        latest_decision = self.store.latest_decision_for_thread(thread_id)
        return ThreadView(thread=thread, messages=messages, latest_decision=latest_decision)

    def _process_turn(
        self,
        thread: Thread,
        submission: Submission,
        sender_message: ThreadMessage,
        profile: SenderProfile,
    ) -> ProcessedTurn:
        gate = self.gate_loader.load(thread.gate_id)
        thread.status = "evaluating"
        thread.updated_at = submission.metadata.submitted_at
        self.store.save_thread(thread)

        self.store.append_submission(submission)
        self.store.append_thread_message(sender_message)
        history = self.store.load_thread_messages(thread.thread_id)

        decision = self.provider.decide(
            DecisionContext(
                gate=gate,
                thread=thread,
                submission=submission,
                current_message=sender_message,
                thread_messages=history,
                sender_profile=profile,
            )
        )
        decision = self._apply_guardrails(gate.hidden_items, thread, decision)

        gate_message: ThreadMessage | None = None
        if decision.decision == "clarify":
            thread.remaining_clarification_rounds = max(0, thread.remaining_clarification_rounds - 1)
            decision.remaining_clarification_rounds = thread.remaining_clarification_rounds
            thread.status = "waiting_on_sender"
            gate_message = ThreadMessage(
                thread_id=thread.thread_id,
                role="gate",
                channel=self._channel_from_source(thread.source),
                content=decision.user_visible_reply or "",
            )
            self.store.append_thread_message(gate_message)
        elif decision.decision == "decline":
            decision.remaining_clarification_rounds = thread.remaining_clarification_rounds
            thread.status = "declined"
            gate_message = ThreadMessage(
                thread_id=thread.thread_id,
                role="gate",
                channel=self._channel_from_source(thread.source),
                content=decision.user_visible_reply or "",
            )
            self.store.append_thread_message(gate_message)
        else:
            decision.remaining_clarification_rounds = thread.remaining_clarification_rounds
            thread.status = "review" if decision.needs_review else "escalated"

        thread.turn_count += 1
        thread.updated_at = utc_now()
        self.store.save_thread(thread)
        self.store.append_decision(decision)
        self.store.append_event(
            InteractionEvent(
                thread_id=thread.thread_id,
                type="thread_message_processed",
                payload={"decision": decision.decision, "gate_id": thread.gate_id, "message_id": sender_message.message_id},
            )
        )
        self.store.save_sender_profile(profile)
        return ProcessedTurn(
            thread=thread,
            sender_message=sender_message,
            gate_message=gate_message,
            decision=decision,
            sender_profile=profile,
        )

    def _load_sender_profile(self, sender_key: str, seen_at) -> SenderProfile:
        profile = self.store.load_sender_profile(sender_key) or SenderProfile(sender_key=sender_key, first_seen_at=seen_at)
        profile.interaction_count += 1
        profile.last_seen_at = seen_at
        return profile

    def _require_thread(self, thread_id: str) -> Thread:
        thread = self.store.load_thread(thread_id)
        if thread is None:
            raise FileNotFoundError(f"thread '{thread_id}' was not found")
        return thread

    @staticmethod
    def _apply_guardrails(hidden_items: list[str], thread: Thread, decision: Decision) -> Decision:
        if decision.decision == "clarify" and thread.remaining_clarification_rounds <= 0:
            decision.decision = "escalate"
            decision.user_visible_reply = None
            decision.needs_review = True
            decision.private_reason = (
                f"{decision.private_reason} Clarification limit exhausted before the provider reached a final answer."
            )

        if decision.user_visible_reply:
            lowered = decision.user_visible_reply.lower()
            if any(item.lower() in lowered for item in hidden_items if item.strip()):
                if decision.decision == "clarify":
                    decision.user_visible_reply = (
                        "Thanks for the note. Could you share a bit more detail on the specific ask and current context?"
                    )
                else:
                    decision.user_visible_reply = (
                        "Thanks for reaching out. This is not a fit for this gate right now, so I will pass."
                    )
        return decision

    @staticmethod
    def _channel_from_source(source: str) -> str:
        if source in {"web_thread", "web_form", "api"}:
            return "web"
        return source
