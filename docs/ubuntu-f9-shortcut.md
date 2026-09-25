# F9 Toggle Shortcut on Ubuntu

This guide configures an Ubuntu GNOME custom shortcut that uses F9 to start and stop nerd-dictation. Backend settings live in a user configuration file, so the shortcut command does not need to be changed when switching models.

## Prerequisites

Install nerd-dictation and make sure `nerd-dictation` is available on `PATH`:

```bash
command -v nerd-dictation
```

Create `~/.config/nerd-dictation/config` with the backend settings:

```bash
NERD_DICTATION_ASR_ENGINE=QWEN
NERD_DICTATION_QWEN_MODEL=message
```

Create an executable toggle command at `~/.local/bin/nerd-dictation-toggle`:

```bash
#!/usr/bin/env bash
set -euo pipefail

config_file="$HOME/.config/nerd-dictation/config"
if [[ -f "$config_file" ]]; then
  # shellcheck disable=SC1090
  source "$config_file"
fi

args=()
if [[ -n "${NERD_DICTATION_ASR_ENGINE:-}" ]]; then
  args+=(--asr-engine="$NERD_DICTATION_ASR_ENGINE")
fi
if [[ -n "${NERD_DICTATION_QWEN_MODEL:-}" ]]; then
  args+=(--qwen-model="$NERD_DICTATION_QWEN_MODEL")
fi

if pgrep -u "$(id -u)" -f '[n]erd-dictation begin' >/dev/null; then
  exec nerd-dictation end
fi

nohup nerd-dictation begin "${args[@]}" "$@" >/dev/null 2>&1 &
```

Make it executable:

```bash
chmod +x ~/.local/bin/nerd-dictation-toggle
```

If the shortcut does not use your login shell environment, use absolute paths and set `DASHSCOPE_API_KEY` through the user session environment rather than only in an interactive shell.

## GNOME Settings

1. Open **Settings**.
2. Open **Keyboard**.
3. Open **View and Customize Shortcuts**.
4. Open **Custom Shortcuts**.
5. Select **Add Custom Shortcut**.
6. Set **Name** to `Toggle nerd-dictation`.
7. Set **Command** to `/home/USER/.local/bin/nerd-dictation-toggle`.
8. Set the shortcut to `F9`.

Replace `USER` with the actual Ubuntu username. The wrapper reads the config file on every start, so changing the model does not require editing the GNOME shortcut.

## gsettings Method

The GUI method is less error-prone because it preserves existing custom shortcuts. For a system with no existing custom shortcuts, the following commands configure F9 directly:

```bash
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
PATH_KEY=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/nerd-dictation/

gsettings set "$SCHEMA" custom-keybindings "['$PATH_KEY']"
gsettings set "$SCHEMA.custom-keybinding:$PATH_KEY" name 'Toggle nerd-dictation'
gsettings set "$SCHEMA.custom-keybinding:$PATH_KEY" command '/home/USER/.local/bin/nerd-dictation-toggle'
gsettings set "$SCHEMA.custom-keybinding:$PATH_KEY" binding 'F9'
```

Before running the first command, inspect the existing value:

```bash
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
```

If the list is not empty, use the GUI or `dconf-editor` to append the new keybinding path instead of replacing the existing list.

## Backend Configuration

Keep the Ubuntu shortcut assigned only to F9. Change `~/.config/nerd-dictation/config` to select a backend or model:

```bash
# Qwen message model.
NERD_DICTATION_ASR_ENGINE=QWEN
NERD_DICTATION_QWEN_MODEL=message

# Qwen streaming model.
# NERD_DICTATION_ASR_ENGINE=QWEN
# NERD_DICTATION_QWEN_MODEL=streaming

# Local Vosk model.
# NERD_DICTATION_ASR_ENGINE=VOSK
```

Command-line arguments still override the config file when a one-off test is needed.

The second F9 press ends audio capture immediately but lets the active recognition task deliver its final corrections before the process exits. Do not terminate the process during this short finalization window, or the displayed partial text can remain uncorrected. An enhanced wrapper can reserve a third F9 press for a hard stop if finalization hangs. Do not assign the same key to more than one custom shortcut entry.

## Wayland and X11

The F9 shortcut itself works on both X11 and Wayland. Simulated text input is separate:

- X11 can use the default `--simulate-input-tool=XDOTOOL`.
- Wayland generally requires `--simulate-input-tool=YDOTOOL`, `DOTOOL`, `DOTOOLC`, or `WTYPE`.

Set the input tool in the config file when the shortcut runs under Wayland:

```bash
NERD_DICTATION_SIMULATE_INPUT_TOOL=YDOTOOL
```

## Troubleshooting

- Test the command in a terminal before assigning F9.
- Check `echo "$DASHSCOPE_API_KEY"` without printing the value: `test -n "$DASHSCOPE_API_KEY" && echo set`.
- Run `nerd-dictation begin --verbose=1 ...` and inspect standard error.
- If F9 is captured by another application, use the GNOME Keyboard panel to find or replace the conflicting shortcut.
- If text is not inserted in the focused application, verify the input simulation tool for the current display server.
