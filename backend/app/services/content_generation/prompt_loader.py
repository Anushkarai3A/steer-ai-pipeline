from __future__ import annotations

"""Versioned prompt loading.

Prompt files live in pipeline/prompts/<name>_v<N>.md so judges can read exactly
what each stage sends to a model. load_prompt(name, version) resolves the file
and returns (text, prompt_version).
"""

from pathlib import Path

from app.core.config import PROMPTS_DIR


class PromptError(Exception):
    pass


def list_versions(name: str) -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob(f"{name}_v*.md"))


def latest_version(name: str) -> str:
    versions = list_versions(name)
    if not versions:
        raise PromptError(f"No prompt files found for '{name}' in {PROMPTS_DIR}")
    return versions[-1]


def load_prompt(name: str, version: str | None = None) -> tuple[str, str]:
    version = version or latest_version(name)
    path = PROMPTS_DIR / f"{name}_{version}.md"
    if not path.exists():
        raise PromptError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8"), f"{name}_{version}"
