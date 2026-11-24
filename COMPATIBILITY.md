# Compatibility Matrix

**LocalDictate v1.0.0** runs natively across **Windows 10/11**, **macOS (Apple Silicon & Intel)**, and **Linux (X11 & Wayland)** with **0 MB GPU VRAM** (100% CPU CTranslate2 INT8 with automatic `float32` fallback).

## Operating Systems & Display Servers

| Platform | Global Hotkeys | Auto-Paste | App-Aware Routing | Floating HUD 2.0 | Autostart | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Windows 10 / 11 (x64)** | `Ctrl+Alt+Space` / `Right Ctrl` | Win32 `SendInput` (`Ctrl+V`) | `GetForegroundWindow` + process name | `WS_EX_NOACTIVATE` + click-through | HKCU `Run` Registry | **Full** |
| **macOS 12–15 (Apple Silicon M1–M4)** | `Option+Space` / `Right Option` | Quartz `CGEvent` (`Cmd+V`) + AppleScript fallback | `NSWorkspace` / System Events | Cocoa `NSStatusWindowLevel` + `CanJoinAllSpaces` | `~/Library/LaunchAgents` plist | **Full** *(requires Accessibility)* |
| **macOS 12–15 (Intel x86_64)** | `Option+Space` / `Right Option` | Quartz `CGEvent` (`Cmd+V`) | `NSWorkspace` / System Events | Cocoa floating HUD | `LaunchAgents` plist | **Full** *(requires Accessibility)* |
| **Linux X11 (Ubuntu / Arch / Fedora)** | `Ctrl+Alt+Space` / `Right Ctrl` | `xdotool` / `pynput` (`Ctrl+Shift+V` in terminals) | `xdotool` / `xprop` `WM_CLASS` | Frameless stay-on-top | `~/.config/autostart/*.desktop` | **Full** |
| **Linux Wayland (GNOME / KDE / Sway)** | Studio button or compositor shortcut | `wtype` or `ydotool` (auto clipboard fallback) | Manual / Studio mode selector | Frameless stay-on-top | XDG Autostart | **Supported** *(install `wtype` or `ydotool`)* |

## Target Applications & App-Aware Routing

| Application | Auto-Selected Mode | Auto-Paste Notes |
| :--- | :---: | :--- |
| **VS Code / Cursor / Windsurf / JetBrains IDEs** | `code` | 450 ms clipboard restore delay tuned for Electron |
| **Terminal / iTerm2 / Alacritty / Kitty / WezTerm / Windows Terminal** | `code` | Uses `Ctrl+Shift+V` automatically on Linux terminals |
| **Apple Mail / Outlook / Gmail / Thunderbird** | `formal` | Full Unicode & Turkish diacritic support |
| **Slack / Discord / Microsoft Teams / Messages** | `concise` | Safe Electron clipboard timing |
| **Notion / Obsidian / Apple Notes / Logseq** | `bullet_notes` | Supports spoken `new line` / `new paragraph` |

## Audio Hardware & Sample Rates

LocalDictate automatically negotiates device-native sample rates (`16 kHz → device default → 48 kHz → 44.1 kHz`) and resamples cleanly via polyphase filtering (`scipy.signal.resample_poly`):
- Built-in laptop microphones (MacBook, ThinkPad, Surface)
- USB studio microphones (Blue Yeti, Shure MV7, Elgato Wave, HyperX SoloCast)
- Bluetooth headsets (AirPods, Sony WH-1000XM, Jabra — 16 kHz HFP & 48 kHz profiles)
- Linux PipeWire / PulseAudio / ALSA (`sudo apt install libportaudio2`)

## CPU & Compute-Type Fallback

- **Modern x86_64 (AVX2 / AVX-512 / VNNI)** & **Apple Silicon (ARM64 NEON / dotprod)**: Uses `CTranslate2 INT8` automatically.
- **Older x86_64 CPUs without INT8 support**: Automatically probes `ctranslate2.get_supported_compute_types("cpu")` and falls back gracefully to `int8_float32` → `float32`.
- **Optional Apple Silicon `mlx-whisper`**: Detected automatically in `hardware.py` when installed.
