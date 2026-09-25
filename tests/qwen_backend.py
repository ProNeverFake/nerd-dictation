#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Test the model-independent progressive text output and Qwen event adapter.
"""

import importlib.machinery
import importlib.util
import os
import queue
import sys
import unittest

from types import ModuleType


def load_nerd_dictation() -> ModuleType:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filepath = os.path.join(root_dir, "nerd-dictation")
    loader = importlib.machinery.SourceFileLoader("nerd_dictation_test", filepath)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


nerd_dictation = load_nerd_dictation()


class TestProgressiveTextOutput(unittest.TestCase):
    def test_replaces_stale_suffix(self) -> None:
        output = []

        def handle_fn(delete_prev_chars: int, text: str) -> None:
            output.append((delete_prev_chars, text))

        text_output = nerd_dictation.ProgressiveTextOutput(
            handle_fn=handle_fn,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=False,
        )

        text_output.handle("hello wer", True)
        text_output.handle("hello world", True)
        text_output.handle("hello world", False)
        text_output.handle("next", True)

        self.assertEqual(
            output,
            [
                (0, "hello wer"),
                (2, "orld"),
                (0, " next"),
            ],
        )

    def test_deferred_output_ignores_partials(self) -> None:
        output = []

        def handle_fn(delete_prev_chars: int, text: str) -> None:
            output.append((delete_prev_chars, text))

        text_output = nerd_dictation.ProgressiveTextOutput(
            handle_fn=handle_fn,
            process_fn=lambda text: text.upper(),
            progressive=False,
            progressive_continuous=False,
        )

        text_output.handle("hello", True)
        text_output.handle("hello world", False)
        text_output.emit_deferred()

        self.assertEqual(output, [(0, "HELLO WORLD")])

    def test_stable_partial_prefix_defers_unstable_tail(self) -> None:
        output = []

        def handle_fn(delete_prev_chars: int, text: str) -> None:
            output.append((delete_prev_chars, text))

        text_output = nerd_dictation.ProgressiveTextOutput(
            handle_fn=handle_fn,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=False,
            stable_partial_prefix=True,
        )

        text_output.handle("hel", True)
        text_output.handle("hell", True)
        text_output.handle("hello", True)
        text_output.handle("hello world", False)

        self.assertEqual(
            output,
            [
                (0, "h"),
                (0, "el"),
                (0, "l"),
                (0, "o world"),
            ],
        )


class TestQwenTranscriptState(unittest.TestCase):
    def test_partial_and_final_updates(self) -> None:
        state = nerd_dictation.QwenTranscriptState()

        self.assertEqual(
            state.consume({"sentence_id": 1, "text": "hello", "sentence_end": False}),
            ("hello", False),
        )
        self.assertEqual(
            state.consume({"sentence_id": 1, "text": "hello.", "sentence_end": True}),
            ("hello.", True),
        )
        self.assertEqual(
            state.consume({"sentence_id": 2, "text": "world", "sentence_end": False}),
            ("world", False),
        )
        self.assertIsNone(
            state.consume({"sentence_id": 1, "text": "stale", "sentence_end": False})
        )
        self.assertEqual(state.finish(), ("world", True))

    def test_heartbeat_is_ignored(self) -> None:
        state = nerd_dictation.QwenTranscriptState()
        self.assertIsNone(
            state.consume({"heartbeat": True, "sentence_id": 0, "text": ""})
        )


class TestQwenEventCoalescing(unittest.TestCase):
    def test_obsolete_partials_are_not_rendered(self) -> None:
        events = queue.Queue()
        state = nerd_dictation.QwenTranscriptState()

        for sentence in (
            {"sentence_id": 1, "text": "hel", "sentence_end": False},
            {"sentence_id": 1, "text": "hello", "sentence_end": False},
            {"sentence_id": 1, "text": "hello.", "sentence_end": True},
            {"sentence_id": 2, "text": "world", "sentence_end": False},
        ):
            events.put(
                (
                    "result",
                    {
                        "payload": {
                            "output": {"sentence": sentence},
                            "usage": {"total_tokens": 42},
                        }
                    },
                )
            )
        events.put(("finished", {"payload": {"usage": {"total_tokens": 50}}}))

        updates, finished, error, total_tokens = nerd_dictation.qwen_drain_event_queue(events, state)

        self.assertEqual(
            updates,
            [
                (1, "hello.", True),
                (2, "world", False),
            ],
        )
        self.assertTrue(finished)
        self.assertEqual(error, "")
        self.assertEqual(total_tokens, 50)

    def test_session_rotation_waits_for_a_final_result(self) -> None:
        threshold = nerd_dictation.QWEN_CONTEXT_ROTATE_TOKENS
        self.assertFalse(
            nerd_dictation.qwen_should_rotate_session(
                threshold,
                [(1, "partial", False)],
                False,
            )
        )
        self.assertTrue(
            nerd_dictation.qwen_should_rotate_session(
                threshold,
                [(1, "final", True)],
                False,
            )
        )


class TestQwenRequest(unittest.TestCase):
    def test_message_request_enables_intermediate_results(self) -> None:
        payload = nerd_dictation.qwen_run_task_payload(
            model="qwen-audio-3.1-asr-flash-message",
            sample_rate=16000,
            polish=False,
            heartbeat=False,
            max_sentence_silence=None,
            task_id="task",
        )
        parameters = payload["payload"]["parameters"]
        self.assertTrue(parameters["intermediate_result_enabled"])
        self.assertNotIn("disfluency_removal_enabled", parameters)

    def test_streaming_request_does_not_use_message_only_options(self) -> None:
        payload = nerd_dictation.qwen_run_task_payload(
            model="qwen-audio-3.1-asr-flash-streaming",
            sample_rate=16000,
            polish=True,
            heartbeat=True,
            max_sentence_silence=800,
            task_id="task",
        )
        parameters = payload["payload"]["parameters"]
        self.assertNotIn("intermediate_result_enabled", parameters)
        self.assertNotIn("disfluency_removal_enabled", parameters)
        self.assertTrue(parameters["heartbeat"])
        self.assertEqual(parameters["max_sentence_silence"], 800)

    def test_model_aliases(self) -> None:
        self.assertEqual(
            nerd_dictation.qwen_model_id_from_arg("message"),
            "qwen-audio-3.1-asr-flash-message",
        )
        self.assertEqual(
            nerd_dictation.qwen_model_id_from_arg("streaming"),
            "qwen-audio-3.1-asr-flash-streaming",
        )

    def test_audio_chunking(self) -> None:
        chunks = nerd_dictation.qwen_audio_chunks(b"12345678", chunk_size=3)
        self.assertEqual(chunks, [b"123", b"456", b"78"])

    def test_xdotool_typing_has_no_default_delay(self) -> None:
        calls = []
        original = nerd_dictation.run_command_or_exit_on_failure
        nerd_dictation.run_command_or_exit_on_failure = calls.append
        try:
            nerd_dictation.simulate_typing_with_xdotool(0, "hello")
        finally:
            nerd_dictation.run_command_or_exit_on_failure = original

        self.assertEqual(
            calls,
            [
                [
                    "xdotool",
                    "type",
                    "--clearmodifiers",
                    "--delay",
                    "0",
                    "--",
                    "hello",
                ]
            ],
        )

    def test_xdotool_backspaces_have_no_default_delay(self) -> None:
        calls = []
        original = nerd_dictation.run_command_or_exit_on_failure
        nerd_dictation.run_command_or_exit_on_failure = calls.append
        try:
            nerd_dictation.simulate_typing_with_xdotool(3, "")
        finally:
            nerd_dictation.run_command_or_exit_on_failure = original

        self.assertEqual(
            calls,
            [
                [
                    "xdotool",
                    "key",
                    "--delay",
                    "0",
                    "--",
                    "BackSpace",
                    "BackSpace",
                    "BackSpace",
                ]
            ],
        )


if __name__ == "__main__":
    unittest.main()
