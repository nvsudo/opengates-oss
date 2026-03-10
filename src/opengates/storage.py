from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schemas import Decision, InteractionEvent, SenderProfile, Submission, Thread, ThreadMessage


class LocalStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.history_dir = data_dir / "history"
        self.profiles_dir = data_dir / "profiles"
        self.threads_dir = data_dir / "threads"
        self.thread_messages_dir = data_dir / "thread_messages"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.threads_dir.mkdir(parents=True, exist_ok=True)
        self.thread_messages_dir.mkdir(parents=True, exist_ok=True)

    def append_submission(self, submission: Submission) -> None:
        self._append_json_line(self.history_dir / "submissions.jsonl", submission.model_dump_json())

    def append_decision(self, decision: Decision) -> None:
        self._append_json_line(self.history_dir / "decisions.jsonl", decision.model_dump_json())

    def append_event(self, event: InteractionEvent) -> None:
        self._append_json_line(self.history_dir / "events.jsonl", event.model_dump_json())

    def save_thread(self, thread: Thread) -> None:
        path = self.threads_dir / f"{thread.thread_id}.json"
        path.write_text(thread.model_dump_json(indent=2), encoding="utf-8")

    def load_thread(self, thread_id: str) -> Thread | None:
        path = self.threads_dir / f"{thread_id}.json"
        if not path.exists():
            return None
        return Thread.model_validate_json(path.read_text(encoding="utf-8"))

    def append_thread_message(self, message: ThreadMessage) -> None:
        self._append_json_line(self.thread_messages_dir / f"{message.thread_id}.jsonl", message.model_dump_json())

    def load_thread_messages(self, thread_id: str) -> list[ThreadMessage]:
        path = self.thread_messages_dir / f"{thread_id}.jsonl"
        if not path.exists():
            return []
        return [ThreadMessage.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def latest_decision_for_thread(self, thread_id: str) -> Decision | None:
        decisions_path = self.history_dir / "decisions.jsonl"
        if not decisions_path.exists():
            return None
        for line in reversed(decisions_path.read_text(encoding="utf-8").splitlines()):
            if not line:
                continue
            decision = Decision.model_validate_json(line)
            if decision.thread_id == thread_id:
                return decision
        return None

    def load_sender_profile(self, sender_key: str) -> SenderProfile | None:
        profile_path = self.profiles_dir / f"{self._safe_key(sender_key)}.json"
        if not profile_path.exists():
            return None
        return SenderProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))

    def save_sender_profile(self, profile: SenderProfile) -> None:
        profile_path = self.profiles_dir / f"{self._safe_key(profile.sender_key)}.json"
        profile_path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")

    def recent_events(self, limit: int = 20) -> list[dict]:
        events_path = self.history_dir / "events.jsonl"
        if not events_path.exists():
            return []
        lines = events_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:]]

    @staticmethod
    def _append_json_line(path: Path, payload: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")

    @staticmethod
    def _safe_key(sender_key: str) -> str:
        return hashlib.sha1(sender_key.encode("utf-8")).hexdigest()
