# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MicroPython application for Raspberry Pi Pico W with a Pico Display. It connects to Wi-Fi, polls a self-hosted OpenF1 lap-time API for tracked drivers, and renders latest lap times on the physical display. This runs on-device, not on a standard Python runtime.

## Key Constraints

- **MicroPython target**: Code must be compatible with MicroPython on Pico W. Standard CPython libraries are not available. Use memory-conscious patterns (chunked reads, bounded buffers, `gc.collect()`).
- **Single-file app**: All application logic lives in `main.py`. If the codebase grows, keep `main.py` as the entrypoint and extract reusable logic into small modules.
- **Hardware-dependent**: `picographics`, `network`, `urequests`, `uasyncio`, and `rp2` are device-only modules. Code using these cannot be tested on a desktop Python installation.
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
2. **Display** (`draw_lines`, `draw_lap_screen`): Clears screen and renders text with a given pen color. `draw_lap_screen` renders the main multi-column lap-time view with aligned columns.
3. **Wi-Fi** (`connect_wifi`): Handles scanning, connection, retry, and status display. Uses `network.WLAN`. Blocking — only runs at startup or on disconnect.
4. **Sync API/Parsing** (`fetch_latest_lap_duration`, `lap_from_tail_json`): Fetches lap data per driver using `urequests`. Uses a streaming tail-buffer approach to avoid loading full JSON responses into memory. Reverse-walks `{...}` slices to find the last lap entry with a non-null `lap_duration`. Kept for startup and sub-screen (driver selection refresh) contexts.
5. **Async API** (`async_fetch_latest_lap_duration`, `async_fetch_event_and_session_info`): Async versions of the fetch functions using `uasyncio.open_connection` and HTTP/1.0. These yield to the event loop during socket reads, keeping buttons responsive during network I/O. The low-level helper `_async_http_get` parses URLs, opens TCP (with optional SSL), sends the request, and returns `(status_code, reader, writer)`.
6. **Standings** (`standings_rows_from_stream`, `show_scrollable_standings_rows`): Streaming JSON parser for driver/constructor championship data from Jolpica API. Byte-level state machine avoids loading full payload. Standings screens have their own sync button loops.
7. **UI sub-screens** (`pick_from_list`, `select_driver_interactive`, `show_scrollable_standings_rows`): Scrollable list UIs with their own blocking button-poll loops. These run while `_polling_buttons = False` to avoid conflicts with the async button monitor.
8. **Button handling** (`_check_buttons_task`, `_handle_pending_button`): A `uasyncio` coroutine polls hardware buttons every 20ms and stores the pressed button letter in `_button_pressed`. The main loop checks `_handle_pending_button()` which reads this flag and dispatches to the appropriate sub-screen. `_polling_buttons` is set to `False` during sub-screens.
9. **Main loop** (`async_main`): Entry point via `uasyncio.run()`. Startup (Wi-Fi, initial fetch) is sync. Then starts `_check_buttons_task` and enters the async poll loop: fetches lap data with `await`, checks for pending button presses between fetches, and sleeps with `uasyncio.sleep_ms`.

## Button Controls

- **Main screen**: A=driver selection, B=toggle event info, X=driver standings, Y=constructor standings
- **Standings/scrollable**: X/Y=page up/down, A=back
- **Driver selection**: X/Y=move cursor, B=confirm, A=cancel

## Style

- `snake_case` for functions/variables, `UPPER_CASE` for constants.
- Prefix internal helpers with `_` (e.g., `_parse_url`, `_async_http_get`, `_button_pressed`).
- 4-space indentation.
- Commit messages: short, imperative titles (e.g., "Add ...", "Fix ...").
