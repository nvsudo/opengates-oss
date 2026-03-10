from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<item>.+?)\s*$")


class GateConfig(BaseModel):
    gate_id: str
    title: str = ""
    public_path: str | None = None
    payment_enabled: bool = False
    charge_enabled: bool = False
    charge_amount_usd: float | None = None
    clarify_threshold: float = 0.55
    escalate_threshold: float = 0.8
    escalation_channel: str = "log"
    max_clarification_rounds: int = Field(default=3, ge=0, le=10)
    thread_expiry_hours: int = Field(default=168, ge=1)
    outbound_notifications: list[str] = Field(default_factory=list)


@dataclass
class GateBundle:
    gate_id: str
    path: Path
    config: GateConfig
    focus_text: str
    standards_text: str
    voice_text: str
    examples_text: str
    focus_items: list[str] = field(default_factory=list)
    standards_sections: dict[str, list[str]] = field(default_factory=dict)
    voice_sections: dict[str, list[str]] = field(default_factory=dict)
    example_sections: dict[str, list[str]] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.config.title or self.gate_id.replace("-", " ").title()

    @property
    def public_path(self) -> str:
        return self.config.public_path or f"/g/{self.gate_id}"

    @property
    def hidden_items(self) -> list[str]:
        items: list[str] = []
        for key, section_items in self.standards_sections.items():
            if "hidden" in key.lower():
                items.extend(section_items)
        return items

    def prompt_pack(self) -> str:
        return "\n\n".join(
            [
                self._section("Focus", self.focus_text),
                self._section("Standards", self.standards_text),
                self._section("Voice", self.voice_text),
                self._section("Examples", self.examples_text),
            ]
        ).strip()

    @staticmethod
    def _section(title: str, raw_text: str) -> str:
        stripped = raw_text.strip()
        if stripped.startswith("#"):
            return stripped
        return f"# {title}\n\n{stripped}"


class GateLoader:
    REQUIRED_FILES = ("focus.md", "standards.md", "voice.md", "examples.md")

    def __init__(self, gates_dir: Path):
        self.gates_dir = gates_dir

    def list_gates(self) -> list[str]:
        if not self.gates_dir.exists():
            return []
        return sorted(path.name for path in self.gates_dir.iterdir() if path.is_dir())

    def load(self, gate_id: str) -> GateBundle:
        gate_path = self.gates_dir / gate_id
        missing = [name for name in self.REQUIRED_FILES if not (gate_path / name).exists()]
        if missing:
            missing_text = ", ".join(missing)
            raise FileNotFoundError(f"gate '{gate_id}' is missing required files: {missing_text}")

        focus_text = (gate_path / "focus.md").read_text(encoding="utf-8")
        standards_text = (gate_path / "standards.md").read_text(encoding="utf-8")
        voice_text = (gate_path / "voice.md").read_text(encoding="utf-8")
        examples_text = (gate_path / "examples.md").read_text(encoding="utf-8")

        config_path = gate_path / "gate.yaml"
        config_data = {"gate_id": gate_id}
        if config_path.exists():
            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            config_data.update(parsed)

        config = GateConfig.model_validate(config_data)
        return GateBundle(
            gate_id=gate_id,
            path=gate_path,
            config=config,
            focus_text=focus_text,
            standards_text=standards_text,
            voice_text=voice_text,
            examples_text=examples_text,
            focus_items=parse_bullets(focus_text),
            standards_sections=parse_sections(standards_text),
            voice_sections=parse_sections(voice_text),
            example_sections=parse_sections(examples_text),
        )


def parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "root"
    sections[current] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        section_match = SECTION_RE.match(line)
        if section_match:
            current = section_match.group("title")
            sections.setdefault(current, [])
            continue

        bullet_match = BULLET_RE.match(line)
        if bullet_match:
            sections.setdefault(current, []).append(bullet_match.group("item"))
        elif line.strip():
            sections.setdefault(current, []).append(line.strip())

    return {key: value for key, value in sections.items() if value}


def parse_bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        match = BULLET_RE.match(line)
        if match:
            items.append(match.group("item"))
    return items
