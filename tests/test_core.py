"""Dependency-free tests for NoHands' local routing and persistence."""

from pathlib import Path
import unittest
import threading
from unittest.mock import Mock

from nohands.audio import AudioIO
from nohands.codex import event_agent_message, event_thread_id, parse_event
from nohands.config import load_settings, write_default_config
from nohands.service import classify_control, spoken_excerpt
from nohands.store import Store


class CoreTests(unittest.TestCase):
    def test_control_phrases_and_normal_requests(self):
        self.assertEqual(classify_control("NoHands, cancel this run!"), "stop")
        self.assertEqual(classify_control("what is happening now"), "status")
        self.assertEqual(classify_control("say that again"), "repeat")
        self.assertEqual(classify_control("be quiet"), "quiet")
        self.assertIsNone(classify_control("Fix the failing test, but don't push"))

    def test_jsonl_event_parser(self):
        self.assertIsNone(parse_event("not json"))
        started = parse_event('{"type":"thread.started","thread_id":"t-123"}')
        completed = parse_event(
            '{"type":"item.completed","item":{"type":"agent_message","text":"Tests passed."}}'
        )
        self.assertEqual(event_thread_id(started), "t-123")
        self.assertEqual(event_agent_message(completed), "Tests passed.")

    def test_spoken_excerpt_removes_markdown_and_caps_length(self):
        self.assertEqual(spoken_excerpt("## Done\n\n`pytest` passed."), "Done pytest passed.")
        self.assertLessEqual(len(spoken_excerpt("word " * 300)), 421)

    def test_streaming_transcript_is_dispatched_only_when_capture_stops(self):
        audio = AudioIO.__new__(AudioIO)
        audio._lock = threading.Lock()
        audio._mic = Mock()
        audio._callback = Mock()
        audio._listening = False
        audio._pending_text = ""
        audio.start_listening()
        audio._on_line(type("Line", (), {"text": "Fix the tests"})())
        audio._on_line(type("Line", (), {"text": "Fix the tests and lint"})())
        audio._callback.assert_not_called()
        audio.stop_listening()
        audio._callback.assert_called_once_with("Fix the tests and lint")

    def test_settings_and_workspace_state_are_local(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = write_default_config(root / "config.toml")
            settings = load_settings(cfg)
            self.assertEqual(settings.language, "en")
            self.assertEqual(settings.model, "small_streaming")
            store = Store(root / "state.sqlite3")
            workspace = root / "repo"
            store.save_thread(workspace, "thread-1")
            store.save_exchange(workspace, "Run tests", "Tests passed.")
            self.assertEqual(store.thread_for(workspace), "thread-1")
            self.assertEqual(store.last_reply(workspace), "Tests passed.")
            store.close()


if __name__ == "__main__":
    unittest.main()
