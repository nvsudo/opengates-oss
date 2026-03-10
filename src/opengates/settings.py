from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    gates_dir: Path
    data_dir: Path
    provider_name: str
    openai_api_key: str | None
    openai_model: str
    debug_prompts: bool


def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    file_env = _read_env_file(project_root / ".env")
    file_env.update(_read_env_file(project_root / ".env.local"))
    gates_dir = Path(os.getenv("OPENGATES_GATES_DIR", project_root / "gates"))
    data_dir = Path(os.getenv("OPENGATES_DATA_DIR", project_root / "data"))
    provider_name = os.getenv("OPENGATES_PROVIDER", file_env.get("OPENGATES_PROVIDER", "heuristic"))
    openai_api_key = os.getenv("OPENAI_API_KEY", file_env.get("OPENAI_API_KEY"))
    openai_model = os.getenv("OPENGATES_OPENAI_MODEL", file_env.get("OPENGATES_OPENAI_MODEL", "gpt-5-mini"))
    debug_prompts = _as_bool(os.getenv("OPENGATES_DEBUG_PROMPTS", file_env.get("OPENGATES_DEBUG_PROMPTS", "0")))
    return Settings(
        project_root=project_root,
        gates_dir=gates_dir,
        data_dir=data_dir,
        provider_name=provider_name,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        debug_prompts=debug_prompts,
    )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _as_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
