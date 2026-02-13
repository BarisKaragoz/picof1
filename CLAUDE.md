# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MicroPython application for Raspberry Pi Pico W with a Pico Display. It connects to Wi-Fi, polls a Formula 1 lap-time API for tracked drivers, and renders latest lap times on the physical display. This runs on-device, not on a standard Python runtime.

## Key Constraints

- **MicroPython target**: Code must be compatible with MicroPython on Pico W. Standard CPython libraries are not available. Use memory-conscious patterns (chunked reads, bounded buffers, `gc.collect()`).
- **Single-file app**: All application logic lives in `main.py`. If the codebase grows, keep `main.py` as the entrypoint and extract reusable logic into small modules.
- **Hardware-dependent**: `picographics`, `network`, `urequests`, and `rp2` are device-only modules. Code using these cannot be tested on a desktop Python installation.
- **String formatting**: Use `str.format()` — f-strings are not supported in MicroPython.

## Commands

```bash
# Syntax check (the only validation possible without hardware)
python3 -m py_compile main.py

# Deploy to connected Pico W via mpremote
mpremote fs cp main.py :main.py
mpremote run main.py
mpremote soft-reset
```

There is no automated test suite. The minimum pre-commit check is `python3 -m py_compile main.py`.

## Architecture

`main.py` is the entire application, structured as:

1. **Configuration** (top): `API_BASE_URL`, `TRACKED_DRIVERS` list, `DRIVER_CODES` lookup, display/network constants. Wi-Fi credentials come from `secrets.py` (gitignored).
2. **Display** (`draw_lines`): Clears screen and renders lines of text with a given pen color.
3. **Wi-Fi** (`connect_wifi`): Handles scanning, connection, retry, and status display. Uses `network.WLAN`.
4. **API/Parsing** (`fetch_latest_lap_duration`, `lap_from_payload`, `lap_from_tail_json`): Fetches lap data per driver from the API. Uses a streaming tail-buffer approach to avoid loading full JSON responses into memory. Falls back to reverse-walking `{...}` slices when the tail isn't valid JSON on its own.
5. **Main loop** (`main`): Boots, connects Wi-Fi, then polls all tracked drivers every 5 seconds. Only redraws when results change.

## Style

- `snake_case` for functions/variables, `UPPER_CASE` for constants.
- 4-space indentation.
- Commit messages: short, imperative titles (e.g., "Add ...", "Fix ...").
