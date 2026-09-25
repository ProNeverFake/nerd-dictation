# Qwen ASR Backend

The Qwen backend is optional and leaves Vosk as the default recognizer. It sends 16-bit mono PCM audio over a WebSocket to Alibaba Cloud Model Studio (DashScope).

## Requirements

- A DashScope API key in `DASHSCOPE_API_KEY`.
- The `websockets` Python package, version 13 or newer.
- Network access to the configured WebSocket endpoint.

Install the optional dependency from the Python package directory:

```bash
pip install -e 'package/python[qwen]'
```

When running directly from the repository, install the dependency separately:

```bash
pip install 'websockets>=13'
```

## Quick Start

The default model is the general real-time streaming model:

```bash
export DASHSCOPE_API_KEY='sk-...'
./nerd-dictation begin --asr-engine=QWEN --qwen-model=streaming
# Speak, then run:
./nerd-dictation end
```

Test the message model, which is optimized for voice messages and input methods:

```bash
./nerd-dictation begin --asr-engine=QWEN --qwen-model=message
# Speak, then run:
./nerd-dictation end
```

The aliases expand to:

```text
streaming -> qwen-audio-3.1-asr-flash-streaming
message   -> qwen-audio-3.1-asr-flash-message
```

A full model id can also be passed to `--qwen-model`.

## Audio and Output

- The backend defaults to 16000 Hz, mono, signed 16-bit PCM.
- The message model requires 16000 Hz. The streaming model accepts other sample rates.
- Audio is split into 3200-byte chunks, approximately 100 ms per chunk.
- Recording starts before the WebSocket connection is ready. Audio is queued during connection setup so the first words are not discarded.
- `--qwen-polish` enables native polish for the message model. It is disabled by default to reduce visible text rewrites.
- `--qwen-heartbeat` keeps a long-running task alive while silence is sent.
- `--qwen-max-sentence-silence=800` can reduce the VAD sentence boundary delay.
- `--qwen-final-timeout=10` controls how long the backend waits for final results after recording stops.

The WebSocket URL can be changed with `--qwen-base-url`. The generic endpoint is:

```text
wss://dashscope.aliyuncs.com/api-ws/v1/inference
```

Workspace-specific endpoints are recommended by Alibaba Cloud when available:

```text
wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference
wss://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference
```

## Progressive Text

Both Qwen models return sentence updates with `sentence_id` and `sentence_end`. The backend converts those events into the same `(text, is_final)` interface used by Vosk.

Text rendering runs in a dedicated output worker. `TextOutput.update()` only records pending state and never performs keyboard I/O, so a slow input command cannot block audio capture or WebSocket event handling. Consecutive partials are coalesced latest-wins, while finalized sentences remain ordered and are flushed during bounded shutdown.

The existing progressive output path calculates the longest common prefix between the previous displayed text and the new text. It sends backspaces for the changed suffix and types the corrected suffix. This is how nerd-dictation can replace an earlier partial recognition result while the user is still speaking.

The Qwen adapter keeps the same behavior while handling these differences:

- Message partials require `intermediate_result_enabled=true`.
- Streaming partials are returned by default.
- Heartbeat events are ignored.
- Queued partials are coalesced so obsolete results are not typed after a slow update.
- The last two characters of a partial remain speculative until the next partial confirms them.
- Events from a sentence older than the last finalized sentence are ignored.
- A remaining partial result is committed when the task finishes.
- Long sessions rotate to a new WebSocket task after 6000 tokens at a finalized sentence boundary. The 8192-token context limit is therefore not reached during normal dictation.

## Fallback and Privacy

Vosk remains available by omitting `--asr-engine=QWEN`. This allows side-by-side testing and provides a local fallback if the network or API is unavailable.

Qwen audio is sent to Alibaba Cloud. The Qwen backend is therefore online speech recognition, not an offline replacement for Vosk.

See [ubuntu-f9-shortcut.md](ubuntu-f9-shortcut.md) for an F9 push-to-talk setup.
