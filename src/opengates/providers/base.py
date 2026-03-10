from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..gates import GateBundle
from ..schemas import Decision, SenderProfile, Submission, Thread, ThreadMessage


@dataclass
class DecisionContext:
    gate: GateBundle
    thread: Thread
    submission: Submission
    current_message: ThreadMessage
    thread_messages: list[ThreadMessage]
    sender_profile: SenderProfile


class DecisionProvider(ABC):
    @abstractmethod
    def decide(self, context: DecisionContext) -> Decision:
        raise NotImplementedError
