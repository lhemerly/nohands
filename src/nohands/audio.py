"""Moonshine microphone capture and Kokoro speech output."""

from __future__ import annotations

import threading
from collections.abc import Callable


class AudioIO:
    def __init__(
        self,
        language: str = "en",
        model: str = "small_streaming",
        voice: str = "kokoro_af_heart",
        speech_enabled: bool = True,
    ):
        try:
            from moonshine_voice import MicTranscriber, ModelArch, TextToSpeech
        except ImportError as exc:
            raise RuntimeError(
                "Moonshine Voice is not installed. Install NoHands with: pipx install ."
            ) from exc
        self._mic = MicTranscriber().language(language)
        arch = getattr(ModelArch, model.upper(), None)
        if arch is None:
            raise ValueError(f"Unsupported Moonshine model profile: {model}")
        self._mic.model_arch(arch)
        self._speech_enabled = speech_enabled
        self._tts = TextToSpeech().language("en-us").voice(voice) if speech_enabled else None
        self._callback: Callable[[str], None] | None = None
        self._mic.on_line(self._on_line)
        self._loaded = False
        self._listening = False
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._loaded:
            return
        self._mic.load()
        if self._tts:
            self._tts.load()
        self._loaded = True

    def set_callback(self, callback: Callable[[str], None]) -> None:
        self._callback = callback

    def set_context(self, context: str) -> None:
        setter = getattr(self._mic, "set_context", None)
        if callable(setter):
            setter(context)

    def start_listening(self) -> None:
        with self._lock:
            if self._listening:
                return
            self._mic.start()
            self._listening = True

    def stop_listening(self) -> None:
        with self._lock:
            if not self._listening:
                return
            self._mic.stop()
            self._listening = False

    def say(self, text: str) -> None:
        if not self._speech_enabled or not text.strip():
            return
        assert self._tts is not None
        self._tts.say(text)
        self._tts.wait()

    def say_async(self, text: str) -> None:
        if self._speech_enabled and text.strip():
            assert self._tts is not None
            self._tts.say(text)

    def stop_speaking(self) -> None:
        if self._speech_enabled:
            assert self._tts is not None
            self._tts.stop()

    def close(self) -> None:
        self.stop_listening()
        close = getattr(self._tts, "close", None)
        if callable(close):
            close()

    def _on_line(self, line: object) -> None:
        text = getattr(line, "text", "")
        callback = self._callback
        if self._listening and callback and isinstance(text, str) and text.strip():
            callback(text.strip())
