# Changelog

All notable changes to **LocalDictate** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-11-23

### Added
- **Studio 2.0 Flagship Desktop Interface (`StudioWindow`, `960×640`)**: Studio Graphite + Electric Violet (`#8B5CF6`) UI with a 218px sidebar rail and 3 dedicated tabs:
  - **Studio (Dictation & Modes)**: Top command bar, 24-bar real-time rolling `LiveWaveformBar`, latency stage badges (`VAD · STT · LLM · Paste`), Raw vs Refined split scratchpad, 7 Quick Mode pills (`Clean`, `Formal`, `Concise`, `Code`, `Notes`, `Git Commit`, `TR→EN`), and Privacy/Routing switches.
  - **History & Snippets**: 4 productivity KPIs, debounced Turkish diacritic-insensitive search, mode/pin filters, rich wrapped history cards, 1-click export (`.md`, `.csv`, `.txt`, `.json`), and an integrated Personal Dictionary & Dynamic Snippets panel with 1-click Starter Packs (`Developer`, `Business EN`, `Business TR`).
  - **Settings & Telemetry**: Live hardware summary + 4 `TelemetryCard` KPIs, microphone live VU tester, OS-aware hotkey presets + macOS TCC Accessibility status indicator, Whisper model cache inspector, non-blocking async LLM connection probe, live EN/TR UI retranslation, GitHub SemVer auto-updater, and built-in local benchmark runner.
- **Floating HUD 2.0 (`FloatingOverlay`)**: Smooth 20-bar rolling waveform, active `MODE · LANG` micro-pill, native macOS Cocoa `setHidesOnDeactivate_(False)` + `NSStatusWindowLevel` + `CanJoinAllSpaces` support, and 64-bit safe Win32 `WS_EX_NOACTIVATE | WS_EX_TRANSPARENT`.
- **Cross-Platform Engine (Windows x64, macOS Apple Silicon, Linux X11/Wayland)**:
  - Native auto-paste across Windows (`SendInput` 64-bit `argtypes`), macOS (Quartz `CGEventCreateKeyboardEvent` + `osascript` fallback + `AXIsProcessTrusted` check), Linux X11 (`xdotool`/`pynput` with `Ctrl+Shift+V` terminal detection), and Linux Wayland (`wtype`/`ydotool`).
  - **App-Aware Auto-Mode Routing**: Automatically detects foreground application (`VS Code/Cursor/Terminal → code`, `Mail/Outlook → formal`, `Slack/Discord → concise`, `Notion/Obsidian → bullet_notes`).
  - **Voice-to-Translate Mode**: Native Whisper `task="translate"` (speak Turkish or any language → paste fluent English).
  - **Smart Voice Commands & Dynamic Snippets**: Spoken formatting (`new line`/`yeni satır`, `new paragraph`/`yeni paragraf`, `comma`/`virgül`, `period`/`nokta`) and dynamic variables (`{{date}}`, `{{iso_date}}`, `{{time}}`, `{{clipboard}}`).
  - **Offline Audio File Drop Transcriber**: Drag-and-drop `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg` files into Studio for offline transcription.
  - **Multi-Backend LLM Refinement + Air-Gapped Offline Lock**: Language-aware EN/TR prompts, Ollama + OpenAI-compatible local servers (LM Studio / llama.cpp), and default localhost-only `offline_only=True` lock.
  - **Cross-Platform Autostart & Native Data Paths**: Windows Registry (`%APPDATA%\LocalDictate`), macOS LaunchAgent (`~/Library/Application Support/LocalDictate`), Linux XDG Autostart (`$XDG_DATA_HOME/localdictate`).
  - **Single-Instance IPC Lock & Crash Logger**: Prevents duplicate instances via `QLocalServer` and writes tracebacks to `crash.log`.
- **Full Packaging & CI/CD**: 3-OS GitHub Actions CI (`ruff` + `unittest`) & unified Release workflow, PyInstaller builders (`build_exe.py`, `build_macos.py`, `build_linux.py`), Inno Setup, Homebrew Cask, Scoop, Winget, Linux AppDir/desktop manifests.

### Fixed
- **Clipboard Safety Bug**: Never restores previous clipboard if OS paste fails; increases default restore delay to `450 ms` for Electron apps (VS Code, Slack, Notion).
- **macOS Hotkey Keycode Corruption**: Guarded Win32 VK numeric mappings strictly to `win32`, added macOS Carbon keycode table (fixing `Option+Space` and preventing `vk=49` from mapping to `'1'`), switched macOS defaults to `alt+space` / `alt_r`, and added stuck-key stale modifier pruning.
- **PortAudio Thread Safety & Sample-Rate Resilience**: Eliminated Qt signal emission from PortAudio's C callback thread (replaced with 30 Hz main-thread `QTimer` polling), added automatic sample-rate negotiation (`16000 → default → 48000 → 44100`) with polyphase resampling, eliminated start-chime bleed into mic capture, and added 5-minute max duration + optional hands-free silence auto-stop.
- **Regex & Backslash Safety in Dictionary Replacements**: Special technical terms (`C++`, `C#`, `node.js`, `.env`) and replacement strings containing backslashes (`C:\Users\...`) are now matched and substituted safely without `re.error`.
- **SQLite Schema Auto-Migration**: Seamlessly upgrades v0.1/v0.2 `history.db` tables with `target_app`, `mode`, `pinned`, and `search_norm` columns while keeping persistent WAL connections thread-safe.

---

## [0.2.0] — 2026-03-01

### Added
- Optional local Ollama LLM refinement, personal vocabulary & replacement rules, SQLite dictation history dialog, subtle synthesized audio cues, Windows autostart, and initial PyInstaller script.

## [0.1.0] — 2026-02-15

### Added
- Initial LocalDictate MVP with `faster-whisper` INT8, Silero VAD, global hotkeys, Windows `SendInput` auto-paste, floating overlay pill, and system tray icon.
