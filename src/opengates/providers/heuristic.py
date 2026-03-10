from __future__ import annotations

import re
from collections import Counter

from ..schemas import Decision
from .base import DecisionContext, DecisionProvider


SPAM_MARKERS = {
    "seo",
    "guest post",
    "link exchange",
    "backlink",
    "guaranteed leads",
    "buy followers",
    "cold outreach agency",
}

UNSERIOUS_MARKERS = {
    "hahaha",
    "lmao",
    "rofl",
    "just give me money",
    "get your money",
    "your money",
}

ROLE_CONFUSION_MARKERS = {
    "resume",
    "cv",
    "job application",
    "ea position",
    "executive assistant",
    "assistant role",
}


class HeuristicDecisionProvider(DecisionProvider):
    def decide(self, context: DecisionContext) -> Decision:
        content = " ".join(context.current_message.content.split())
        lowered = content.lower()
        focus_hits = self._match_focus(context.gate.focus_items, lowered)
        clarify_rules = self._section_items(context, "clarify")
        escalate_rules = self._section_items(context, "escalate")

        obvious_reject = self.obvious_reject(context)
        if obvious_reject is not None:
            return obvious_reject

        signal_score = self._signal_score(lowered, focus_hits)
        clarify_reason = self._clarify_reason(lowered, clarify_rules)

        if signal_score >= context.gate.config.escalate_threshold or (
            focus_hits and self._matches_any(lowered, escalate_rules)
        ):
            return self._build_decision(
                context,
                decision="escalate",
                confidence=min(0.99, signal_score),
                tags=sorted(set(focus_hits or ["high-signal"])),
                private_reason=self._private_reason(focus_hits, "clear fit with enough concrete detail"),
            )

        if focus_hits or clarify_reason:
            if context.thread.remaining_clarification_rounds <= 0:
                return self._build_decision(
                    context,
                    decision="escalate",
                    confidence=max(0.55, signal_score),
                    tags=sorted(set(focus_hits or ["needs-review"])),
                    private_reason=self._private_reason(
                        focus_hits,
                        "clarification limit exhausted before a confident final decision; escalate for review",
                    ),
                    needs_review=True,
                )
            return self._build_decision(
                context,
                decision="clarify",
                confidence=max(0.55, signal_score),
                tags=sorted(set(focus_hits or ["needs-context"])),
                private_reason=self._private_reason(focus_hits, clarify_reason or "potential fit but missing specifics"),
                user_visible_reply=self._clarify_reply(context, clarify_reason),
            )

        return self._build_decision(
            context,
            decision="decline",
            confidence=0.84,
            tags=["out-of-scope"],
            private_reason="Did not match focus areas strongly enough.",
            user_visible_reply=self._decline_reply(context),
        )

    def obvious_reject(self, context: DecisionContext) -> Decision | None:
        content = " ".join(context.current_message.content.split())
        lowered = content.lower()
        focus_hits = self._match_focus(context.gate.focus_items, lowered)
        reject_rules = self._section_items(context, "reject")
        if (
            self._matches_any(lowered, SPAM_MARKERS)
            or self._matches_any(lowered, reject_rules)
            or self._is_unserious_or_bad_faith(lowered)
            or self._is_role_confused_for_gate(context, lowered, focus_hits)
        ):
            return self._build_decision(
                context,
                decision="decline",
                confidence=0.93,
                tags=["low-signal", "reject"],
                private_reason="Matched explicit reject or spam rule.",
                user_visible_reply=self._decline_reply(context),
            )
        return None

    def _build_decision(
        self,
        context: DecisionContext,
        *,
        decision: str,
        confidence: float,
        tags: list[str],
        private_reason: str,
        user_visible_reply: str | None = None,
        needs_review: bool = False,
    ) -> Decision:
        return Decision(
            thread_id=context.thread.thread_id,
            message_id=context.current_message.message_id,
            gate_id=context.gate.gate_id,
            decision=decision,  # type: ignore[arg-type]
            confidence=confidence,
            tags=tags,
            private_reason=private_reason,
            user_visible_reply=user_visible_reply,
            needs_review=needs_review,
            remaining_clarification_rounds=context.thread.remaining_clarification_rounds,
        )

    def _signal_score(self, lowered: str, focus_hits: list[str]) -> float:
        score = 0.15
        if focus_hits:
            score += min(0.45, len(focus_hits) * 0.15)
        if re.search(r"\b\d+(k|m|b|%)?\b", lowered):
            score += 0.15
        if "http://" in lowered or "https://" in lowered:
            score += 0.1
        if any(token in lowered for token in ("revenue", "arr", "mrr", "users", "customers", "growth", "traction")):
            score += 0.15
        if any(token in lowered for token in ("paying customers", "design partners", "pilots", "mrr", "arr")):
            score += 0.1
        if any(token in lowered for token in ("warm intro", "introduction", "mutual", "referred")):
            score += 0.1
        if "network" in lowered and "suggested" in lowered:
            score += 0.1
        if len(lowered) < 120:
            score -= 0.15
        return max(0.05, min(score, 0.99))

    def _clarify_reason(self, lowered: str, clarify_rules: list[str]) -> str | None:
        if self._matches_any(lowered, clarify_rules):
            return "matched a clarification rule"
        if any(token in lowered for token in ("startup", "company", "raising", "founder")) and not any(
            token in lowered for token in ("revenue", "arr", "mrr", "users", "customers", "traction", "growth")
        ):
            return "missing traction details"
        if "podcast" in lowered and not any(token in lowered for token in ("audience", "listeners", "topic", "episode")):
            return "missing audience and topic details"
        if len(lowered) < 220:
            return "request is too generic"
        return None

    @staticmethod
    def _is_unserious_or_bad_faith(lowered: str) -> bool:
        if any(marker in lowered for marker in UNSERIOUS_MARKERS):
            if not HeuristicDecisionProvider._contains_structured_signal(lowered):
                return True
        if "pitch" in lowered and "money" in lowered and not HeuristicDecisionProvider._contains_structured_signal(lowered):
            return True
        return False

    @staticmethod
    def _is_role_confused_for_gate(context: DecisionContext, lowered: str, focus_hits: list[str]) -> bool:
        gate_text = " ".join(context.gate.focus_items).lower()
        if any(token in gate_text for token in ("hiring", "recruit", "candidate", "executive assistant", "ea")):
            return False
        if any(marker in lowered for marker in ROLE_CONFUSION_MARKERS):
            return True
        if "hiring" in lowered and not focus_hits and not HeuristicDecisionProvider._contains_structured_signal(lowered):
            return True
        return False

    @staticmethod
    def _contains_structured_signal(lowered: str) -> bool:
        return any(
            token in lowered
            for token in (
                "problem",
                "customer",
                "customers",
                "user",
                "users",
                "product",
                "company",
                "startup",
                "founder",
                "revenue",
                "mrr",
                "arr",
                "traction",
                "growth",
                "pilot",
                "deck",
                "intro",
                "market",
            )
        )

    @staticmethod
    def _match_focus(focus_items: list[str], lowered: str) -> list[str]:
        matched: list[str] = []
        for item in focus_items:
            candidate = item.lower()
            words = [word for word in re.split(r"[\s,/]+", candidate) if len(word) > 3]
            if candidate in lowered or any(word in lowered for word in words):
                matched.append(item)
        return [item for item, _count in Counter(matched).most_common()]

    @staticmethod
    def _matches_any(lowered: str, phrases: set[str] | list[str]) -> bool:
        return any(phrase.lower() in lowered for phrase in phrases if phrase.strip())

    @staticmethod
    def _section_items(context: DecisionContext, section_name: str) -> list[str]:
        values: list[str] = []
        for heading, items in context.gate.standards_sections.items():
            if section_name in heading.lower():
                values.extend(items)
        return values

    @staticmethod
    def _private_reason(focus_hits: list[str], reason: str) -> str:
        if focus_hits:
            return f"Matched focus areas: {', '.join(focus_hits[:3])}. {reason}."
        return reason.capitalize() + "."

    @staticmethod
    def _decline_reply(context: DecisionContext) -> str:
        opening = "Thanks for reaching out."
        if "warm" in context.gate.voice_text.lower():
            opening = "Thanks for reaching out and for the note."
        return f"{opening} This is not a fit for this gate right now, so I will pass. I appreciate the outreach."

    @staticmethod
    def _clarify_reply(context: DecisionContext, clarify_reason: str | None) -> str:
        if clarify_reason == "missing traction details":
            question = "Could you share your current traction and the specific ask?"
        elif clarify_reason == "missing audience and topic details":
            question = "Could you share the audience, topic, and why this is a fit now?"
        else:
            question = "Could you share a bit more detail on the specific ask and why this is relevant now?"
        opener = "Thanks for the note."
        if "direct" in context.gate.voice_text.lower():
            opener = "Thanks."
        return f"{opener} {question}"
