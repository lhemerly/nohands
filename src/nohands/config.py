"""Small, dependency-free configuration and persistence helpers."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    language: str = "en"
    model: str = "small_streaming"
    voice: str = "kokoro_af_heart"
    codex_command: str = "codex"
    speech_enabled: bool = True
    default_workspace: Path = Path.cwd()


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nohands" / "config.toml"


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "nohands"


def load_settings(path: Path | None = None) -> Settings:
    cfg_path = path or config_path()
    if not cfg_path.exists():
        return Settings()
    with cfg_path.open("rb") as stream:
        raw = tomllib.load(stream)
    voice = raw.get("voice", {})
    codex = raw.get("codex", {})
    audio = raw.get("audio", {})
    return Settings(
        language=voice.get("language", "en"),
        model=voice.get("model", "small_streaming"),
        voice=voice.get("tts_voice", "kokoro_af_heart"),
        codex_command=codex.get("command", "codex"),
        speech_enabled=audio.get("speech_enabled", True),
        default_workspace=Path(codex.get("workspace", Path.cwd())).expanduser().resolve(),
    )


def write_default_config(path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    target.write_text(
        "# NoHands settings. The ASR and TTS models run locally.\n"
        "[voice]\n"
        'language = "en"\n'
        'model = "small_streaming" # tiny_streaming | small_streaming | medium_streaming\n'
        'tts_voice = "kokoro_af_heart"\n\n'
        "[audio]\n"
        "speech_enabled = true\n\n"
        "[codex]\n"
        'command = "codex"\n'
        f'workspace = "{Path.cwd()}"\n',
        encoding="utf-8",
    )
    return target
