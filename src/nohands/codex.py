"""Codex CLI adapter. Uses structured JSONL events and native session resume."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    thread_id: str | None
    message: str
    returncode: int


def parse_event(line: str) -> dict | None:
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    return event if isinstance(event, dict) else None


def event_thread_id(event: dict) -> str | None:
    if event.get("type") == "thread.started":
        return event.get("thread_id") or event.get("threadId")
    return None


def event_agent_message(event: dict) -> str | None:
    if event.get("type") != "item.completed":
        return None
    item = event.get("item", {})
    if not isinstance(item, dict) or item.get("type") not in {"agent_message", "assistant_message"}:
        return None
    text = item.get("text")
    return text if isinstance(text, str) else None


class CodexCLI:
    def __init__(self, executable: str = "codex"):
        self.executable = executable
        self.process: subprocess.Popen[str] | None = None

    def run(
        self,
        prompt: str,
        workspace: Path,
        thread_id: str | None,
        on_status: Callable[[str], None] | None = None,
    ) -> RunResult:
        command = [self.executable, "exec"]
        if thread_id:
            command += ["resume", thread_id]
        command += ["--json", "-"]
        self.process = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(prompt + "\n")
        self.process.stdin.close()
        active_thread = thread_id
        messages: list[str] = []
        announced_tools = False
        for raw_line in self.process.stdout:
            event = parse_event(raw_line)
            if event is None:
                continue
            active_thread = event_thread_id(event) or active_thread
            message = event_agent_message(event)
            if message:
                messages.append(message)
            if event.get("type") == "item.started" and not announced_tools:
                item = event.get("item", {})
                if isinstance(item, dict) and item.get("type") in {"command_execution", "mcp_tool_call"}:
                    announced_tools = True
                    if on_status:
                        on_status("Codex is working in the project now.")
        returncode = self.process.wait()
        stderr = self.process.stderr.read() if self.process.stderr else ""
        self.process = None
        output = "\n".join(m.strip() for m in messages if m.strip())
        if returncode and not output:
            output = stderr.strip() or f"Codex exited with status {returncode}."
        elif not output:
            output = "Codex finished, but did not return a final text message."
        return RunResult(active_thread, output, returncode)

    def cancel(self) -> bool:
        process = self.process
        if not process or process.poll() is not None:
            return False
        process.terminate()
        return True
