"""Local daemon, Unix-socket controls, speech routing and Codex runs."""

from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import threading
from pathlib import Path

from .audio import AudioIO
from .codex import CodexCLI
from .config import Settings, state_dir
from .store import Store


def socket_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "nohands.sock"


def classify_control(text: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    normalized = " ".join(normalized.split())
    if re.fullmatch(r"(nohands )?(stop|cancel|abort)( codex| the run| this run)?", normalized):
        return "stop"
    if re.fullmatch(r"(nohands )?(status|what is happening|what are you doing)( now)?", normalized):
        return "status"
    if re.fullmatch(r"(nohands )?(repeat|say that again|repeat that)", normalized):
        return "repeat"
    if re.fullmatch(r"(nohands )?(be quiet|stop talking|quiet)", normalized):
        return "quiet"
    return None


class NoHandsService:
    def __init__(self, settings: Settings, workspace: Path):
        self.settings = settings
        self.workspace = workspace.resolve()
        self.store = Store(state_dir() / "state.sqlite3")
        self.codex = CodexCLI(settings.codex_command)
        self.audio = AudioIO(
            settings.language, settings.model, settings.voice, settings.speech_enabled
        )
        self.audio.set_callback(self._on_transcript_from_audio)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._busy = False
        self._listening = False
        self._last_status = "Idle. Press your NoHands shortcut to speak."
        self._run_lock = threading.Lock()

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.audio.set_context(self._workspace_context())
        await asyncio.to_thread(self.audio.load)
        path = socket_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(self._handle_socket, path=str(path))
        os.chmod(path, 0o600)
        self._last_status = f"Ready in {self.workspace.name}. Press the shortcut to speak."
        print(f"NoHands ready. Control socket: {path}", flush=True)
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.audio.close()
        self.store.close()
        socket_path().unlink(missing_ok=True)

    def _on_transcript_from_audio(self, transcript: str) -> None:
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self.handle_transcript(transcript), self._loop)

    async def handle_transcript(self, transcript: str) -> None:
        self.store.save_exchange(self.workspace, transcript)
        action = classify_control(transcript)
        if action == "stop":
            stopped = self.codex.cancel()
            self._last_status = "Stopped the Codex run." if stopped else "There is no active Codex run."
            self.audio.say_async(self._last_status)
            return
        if action == "status":
            self.audio.say_async(self._last_status)
            return
        if action == "repeat":
            self.audio.say_async(self.store.last_reply(self.workspace) or "I have no previous reply to repeat.")
            return
        if action == "quiet":
            self.audio.stop_speaking()
            return
        if self._busy:
            self._last_status = "A Codex turn is already running. Say stop, or wait for it to finish."
            self.audio.say_async(self._last_status)
            return
        asyncio.create_task(self._run_codex(transcript))

    async def _run_codex(self, transcript: str) -> None:
        if self._busy:
            return
        self._busy = True
        self._last_status = "Working on your request."
        self.audio.say_async(self._last_status)
        thread_id = self.store.thread_for(self.workspace)
        prompt = (
            f"{transcript}\n\n"
            "This request was spoken. Preserve its full intent and all constraints. "
            "Keep the final response concise and suitable for audio: report what changed, "
            "what verification ran and its result, and any action still needed."
        )
        try:
            result = await asyncio.to_thread(
                self.codex.run,
                prompt,
                self.workspace,
                thread_id,
                self._codex_status,
            )
            if result.thread_id:
                self.store.save_thread(self.workspace, result.thread_id)
            self.store.save_exchange(self.workspace, transcript, result.message)
            if result.returncode == 0:
                self._last_status = "Codex finished. " + spoken_excerpt(result.message)
            else:
                self._last_status = "Codex stopped or reported an error. " + spoken_excerpt(result.message)
            self.audio.say_async(self._last_status)
        except FileNotFoundError:
            self._last_status = "I could not find the Codex command. Check the configured path."
            self.audio.say_async(self._last_status)
        except Exception as exc:  # Keep daemon alive and report the problem.
            self._last_status = f"The Codex connection failed: {exc}"
            self.audio.say_async(self._last_status)
        finally:
            self._busy = False

    def _codex_status(self, text: str) -> None:
        self._last_status = text
        self.audio.say_async(text)

    async def control(self, command: str) -> str:
        if command == "toggle":
            if self._listening:
                await asyncio.to_thread(self.audio.stop_listening)
                self._listening = False
                self._last_status = "Listening stopped."
                self.audio.say_async("Listening stopped.")
            else:
                self.audio.say("Listening.")
                await asyncio.to_thread(self.audio.start_listening)
                self._listening = True
                self._last_status = "Listening for your request."
            return self._last_status
        if command == "status":
            return self._last_status
        if command == "stop":
            stopped = self.codex.cancel()
            self._last_status = "Stopped the Codex run." if stopped else "There is no active Codex run."
            self.audio.say_async(self._last_status)
            return self._last_status
        if command == "quiet":
            self.audio.stop_speaking()
            return "Stopped speech playback."
        if command == "repeat":
            message = self.store.last_reply(self.workspace) or "No reply is available yet."
            self.audio.say_async(spoken_excerpt(message))
            return message
        return "Unknown command. Use toggle, status, stop, quiet, or repeat."

    async def _handle_socket(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            command = (await asyncio.wait_for(reader.readline(), timeout=4)).decode().strip()
            response = await self.control(command)
            writer.write((response.replace("\n", " ") + "\n").encode())
            await writer.drain()
        except Exception as exc:
            writer.write((f"error: {exc}\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _workspace_context(self) -> str:
        parts = [self.workspace.name]
        try:
            remote = subprocess.run(
                ["git", "remote", "get-url", "origin"], cwd=self.workspace,
                text=True, capture_output=True, timeout=2, check=False,
            ).stdout.strip()
            if remote:
                parts.append(remote)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return " ".join(parts)


def spoken_excerpt(text: str, limit: int = 420) -> str:
    clean = re.sub(r"```.*?```", " code block omitted. ", text, flags=re.DOTALL)
    clean = re.sub(r"[`*_#>]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) <= limit:
        return clean
    sentence = re.split(r"(?<=[.!?])\s+", clean)
    excerpt = " ".join(sentence[:3])
    return (excerpt[:limit].rsplit(" ", 1)[0] + "…") if len(excerpt) > limit else excerpt + "…"


async def send_control(command: str) -> str:
    reader, writer = await asyncio.open_unix_connection(str(socket_path()))
    writer.write((command + "\n").encode())
    await writer.drain()
    reply = (await reader.readline()).decode().strip()
    writer.close()
    await writer.wait_closed()
    return reply
