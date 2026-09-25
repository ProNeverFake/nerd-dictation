#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Test the model-independent text output worker and Qwen event adapter.
"""

import importlib.machinery
import importlib.util
import os
import queue
import sys
import threading
import time
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


class TestTextOutputProgressiveBehavior(unittest.TestCase):
    def test_replaces_stale_suffix(self) -> None:
        sink = nerd_dictation.FakeTextSink()

        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=False,
        )

        text_output.update("hello wer", False)
        self.assertTrue(sink.wait_for_events(1))
        text_output.update("hello world", False)
        self.assertTrue(sink.wait_for_events(2))
        text_output.update("hello world", True)
        text_output.update("next", True)
        text_output.close(flush=True)

        self.assertEqual(
            sink.events,
            [
                (0, "hello wer"),
                (2, "orld"),
                (0, " next"),
            ],
        )

    def test_deferred_output_ignores_partials(self) -> None:
        sink = nerd_dictation.FakeTextSink()

        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text.upper(),
            progressive=False,
            progressive_continuous=False,
        )

        text_output.update("hello", False)
        text_output.update("hello world", True)
        text_output.close(flush=True)

        self.assertEqual(sink.events, [(0, "HELLO WORLD")])

    def test_stable_partial_prefix_defers_unstable_tail(self) -> None:
        sink = nerd_dictation.FakeTextSink()

        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=False,
            stable_partial_prefix=True,
        )

        text_output.update("hel", False)
        self.assertTrue(sink.wait_for_events(1))
        text_output.update("hell", False)
        self.assertTrue(sink.wait_for_events(2))
        text_output.update("hello", False)
        self.assertTrue(sink.wait_for_events(3))
        text_output.update("hello world", True)
        text_output.close(flush=True)

        self.assertEqual(
            sink.events,
            [
                (0, "h"),
                (0, "el"),
                (0, "l"),
                (0, "o world"),
            ],
        )


class BlockingTextSink(nerd_dictation.FakeTextSink):
    def __init__(self) -> None:
        super().__init__()
        self.write_started = threading.Event()
        self.write_release = threading.Event()

    def type_text(self, delete_prev_chars: int, text: str) -> None:
        self.write_started.set()
        if not self.write_release.wait(timeout=2.0):
            raise TimeoutError("test sink was not released")
        super().type_text(delete_prev_chars, text)


class TestTextOutput(unittest.TestCase):
    def test_deferred_partial_does_not_mark_output_as_handled(self) -> None:
        sink = nerd_dictation.FakeTextSink()
        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=False,
            progressive_continuous=False,
        )
        text_output.update("partial", False)
        self.assertFalse(text_output.handled_any)
        text_output.close(flush=True)
        self.assertEqual(sink.events, [])

    def test_delayed_fake_sink_does_not_block_update(self) -> None:
        sink = nerd_dictation.FakeTextSink(delay_seconds=0.3)
        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=True,
        )
        try:
            started = time.monotonic()
            text_output.update("hello", True)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.1)
        finally:
            text_output.close(flush=True)

        self.assertEqual(sink.events, [(0, "hello")])

    def test_partials_coalesce_latest_wins(self) -> None:
        sink = BlockingTextSink()
        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=True,
        )
        try:
            text_output.update("in-flight", True)
            self.assertTrue(sink.write_started.wait(timeout=1.0))
            for i in range(100):
                text_output.update("partial-{:d}".format(i), False)
        finally:
            sink.write_release.set()
            text_output.close(flush=True)

        self.assertEqual(sink.events, [(0, "in-flight"), (0, "partial-99")])

    def test_finals_stay_ordered_and_complete(self) -> None:
        sink = BlockingTextSink()
        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=True,
        )
        try:
            text_output.update("first", True)
            self.assertTrue(sink.write_started.wait(timeout=1.0))
            text_output.update("second", True)
            text_output.update("third", True)
        finally:
            sink.write_release.set()
            text_output.close(flush=True)

        self.assertEqual(sink.events, [(0, "first"), (0, "second"), (0, "third")])

    def test_close_flush_waits_for_pending_output(self) -> None:
        sink = BlockingTextSink()
        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=True,
        )
        text_output.update("hello", True)
        self.assertTrue(sink.write_started.wait(timeout=1.0))

        close_finished = threading.Event()

        def close_output() -> None:
            text_output.close(flush=True)
            close_finished.set()

        close_thread = threading.Thread(target=close_output)
        close_thread.start()
        self.assertFalse(close_finished.wait(timeout=0.05))
        sink.write_release.set()
        self.assertTrue(close_finished.wait(timeout=1.0))
        close_thread.join(timeout=1.0)

        self.assertEqual(sink.events, [(0, "hello")])

    def test_cancel_drops_pending_output(self) -> None:
        sink = BlockingTextSink()
        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=True,
            progressive_continuous=True,
        )
        text_output.update("in-flight", True)
        self.assertTrue(sink.write_started.wait(timeout=1.0))
        text_output.update("dropped-1", True)
        text_output.update("dropped-2", True)

        errors = []

        def close_output() -> None:
            try:
                text_output.close(flush=False)
            except BaseException as ex:
                errors.append(ex)

        close_thread = threading.Thread(target=close_output)
        close_thread.start()
        time.sleep(0.02)
        sink.write_release.set()
        close_thread.join(timeout=1.0)

        self.assertFalse(close_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sink.events, [(0, "in-flight")])

    def test_sink_errors_propagate_from_close(self) -> None:
        sink = nerd_dictation.FakeTextSink(error=RuntimeError("sink failed"))
        text_output = nerd_dictation.TextOutput(
            sink=sink,
            process_fn=lambda text: text,
            progressive=False,
            progressive_continuous=False,
        )
        text_output.update("hello", True)

        with self.assertRaisesRegex(RuntimeError, "sink failed"):
            text_output.close(flush=True)


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
            nerd_dictation.QWEN_DEFAULT_MODEL,
            "qwen-audio-3.1-asr-flash-streaming",
        )
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
