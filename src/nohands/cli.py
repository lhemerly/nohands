"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import signal
import subprocess
import sys
from pathlib import Path

from . import __version__
from .codex import CodexCLI
from .config import load_settings, state_dir, write_default_config
from .service import NoHandsService, send_control


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="nohands", description="Local voice control for Codex CLI")
    root.add_argument("--version", action="version", version=f"nohands {__version__}")
    sub = root.add_subparsers(dest="command", required=True)
    daemon = sub.add_parser("daemon", help="start the audio service")
    daemon.add_argument("--cwd", type=Path)
    for command in ("toggle", "status", "stop", "quiet", "repeat"):
        sub.add_parser(command, help=f"{command} the running audio service")
    run = sub.add_parser("run", help="send a typed prompt to Codex through NoHands")
    run.add_argument("prompt")
    run.add_argument("--cwd", type=Path, default=Path.cwd())
    sub.add_parser("init", help="write a default configuration file")
    sub.add_parser("doctor", help="check local dependencies and Codex login")
    return root


async def daemon(cwd: Path | None) -> None:
    settings = load_settings()
    workspace = (cwd or settings.default_workspace).expanduser().resolve()
    service = NoHandsService(settings, workspace)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(service.close()))
    await service.run()


def doctor() -> int:
    checks: list[tuple[str, list[str]]] = [
        ("Codex CLI", [load_settings().codex_command, "--version"]),
        ("Codex authentication", [load_settings().codex_command, "login", "status"]),
        ("PipeWire", ["pw-cli", "info", "0"]),
    ]
    failed = False
    for label, command in checks:
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
            ok = result.returncode == 0
            print(f"{'OK' if ok else 'FAIL'} {label}: {(result.stdout or result.stderr).strip()}")
            failed |= not ok
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print(f"FAIL {label}: {exc}")
            failed = True
    try:
        import moonshine_voice  # noqa: F401
        print("OK Moonshine Voice: installed")
    except ImportError:
        print("FAIL Moonshine Voice: install with pipx/uv from this project")
        failed = True
    return 1 if failed else 0


def main() -> None:
    args = parser().parse_args()
    if args.command == "init":
        print(write_default_config())
        return
    if args.command == "doctor":
        raise SystemExit(doctor())
    if args.command == "daemon":
        try:
            asyncio.run(daemon(args.cwd))
        except KeyboardInterrupt:
            pass
        return
    if args.command == "run":
        settings = load_settings()
        store_path = state_dir() / "state.sqlite3"
        from .store import Store
        store = Store(store_path)
        result = CodexCLI(settings.codex_command).run(args.prompt, args.cwd.resolve(), store.thread_for(args.cwd.resolve()))
        if result.thread_id:
            store.save_thread(args.cwd.resolve(), result.thread_id)
        store.save_exchange(args.cwd.resolve(), args.prompt, result.message)
        print(result.message)
        store.close()
        raise SystemExit(result.returncode)
    try:
        print(asyncio.run(send_control(args.command)))
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        print(f"NoHands daemon is not running: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
