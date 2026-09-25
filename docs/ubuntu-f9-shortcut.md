# F9 Toggle Shortcut on Ubuntu

This guide configures an Ubuntu GNOME custom shortcut that uses F9 to start and stop nerd-dictation. The same shortcut can be used with the Vosk or Qwen backend.

## Prerequisites

Install nerd-dictation and make sure `nerd-dictation` is available on `PATH`:

```bash
command -v nerd-dictation
```

Create an executable toggle command at `~/.local/bin/nerd-dictation-toggle`:

```bash
#!/usr/bin/env bash
set -euo pipefail

if pgrep -u "$(id -u)" -f '[n]erd-dictation begin' >/dev/null; then
  exec nerd-dictation end
fi

nohup nerd-dictation begin "$@" >/dev/null 2>&1 &
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
7. Set **Command** to one of the commands below.
8. Set the shortcut to `F9`.

For the Qwen message model:

```bash
/home/USER/.local/bin/nerd-dictation-toggle --asr-engine=QWEN --qwen-model=message
```

For the Qwen streaming model:

```bash
/home/USER/.local/bin/nerd-dictation-toggle --asr-engine=QWEN --qwen-model=streaming
```

For local Vosk recognition:

```bash
/home/USER/.local/bin/nerd-dictation-toggle
```

Replace `USER` with the actual Ubuntu username. Using an absolute command path avoids differences between desktop and login shell environments.

## gsettings Method

The GUI method is less error-prone because it preserves existing custom shortcuts. For a system with no existing custom shortcuts, the following commands configure F9 directly:

```bash
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
PATH_KEY=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/nerd-dictation/

gsettings set "$SCHEMA" custom-keybindings "['$PATH_KEY']"
gsettings set "$SCHEMA.custom-keybinding:$PATH_KEY" name 'Toggle nerd-dictation'
gsettings set "$SCHEMA.custom-keybinding:$PATH_KEY" command '/home/USER/.local/bin/nerd-dictation-toggle --asr-engine=QWEN --qwen-model=message'
gsettings set "$SCHEMA.custom-keybinding:$PATH_KEY" binding 'F9'
```

Before running the first command, inspect the existing value:

```bash
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
```

If the list is not empty, use the GUI or `dconf-editor` to append the new keybinding path instead of replacing the existing list.

## Model Switching During Testing

Keep the Ubuntu shortcut assigned only to F9. To test another backend, update the F9 command or run the toggle command manually with a different `--qwen-model` value.

The wrapper starts each session in its own process group and performs a bounded hard stop on the second F9 press. This keeps F9 responsive even if recognition or keyboard output is blocked. Do not assign the same key to more than one custom shortcut entry.

## Wayland and X11

The F9 shortcut itself works on both X11 and Wayland. Simulated text input is separate:

- X11 can use the default `--simulate-input-tool=XDOTOOL`.
- Wayland generally requires `--simulate-input-tool=YDOTOOL`, `DOTOOL`, `DOTOOLC`, or `WTYPE`.

Add the input tool option to the shortcut command. For example:

```bash
/home/USER/.local/bin/nerd-dictation-toggle --asr-engine=QWEN --qwen-model=message --simulate-input-tool=YDOTOOL
```

## Troubleshooting

- Test the command in a terminal before assigning F9.
- Check `echo "$DASHSCOPE_API_KEY"` without printing the value: `test -n "$DASHSCOPE_API_KEY" && echo set`.
- Run `nerd-dictation begin --verbose=1 ...` and inspect standard error.
- If F9 is captured by another application, use the GNOME Keyboard panel to find or replace the conflicting shortcut.
- If text is not inserted in the focused application, verify the input simulation tool for the current display server.
