# Pico F1 Lap Display

MicroPython app for Raspberry Pi Pico W + Pico Display that connects to Wi-Fi, loads top drivers from session results on cold boot, polls a lap-time API, and renders the latest laps on screen.

Example display line:

`HAM 01:37.154`

## What It Does

- Connects to Wi-Fi with retry and status feedback.
- On cold boot, fetches top 3 drivers from the session-result endpoint.
- Polls an API endpoint every 5 seconds.
- Parses both JSON list and single-object payloads.
- Uses memory-conscious tail parsing for larger responses.
- Displays fetch/network errors without crashing.
- Lets you edit tracked drivers on-device via buttons.

## Project Layout

- `main.py`: Main application entrypoint.
- `secrets.py`: Local Wi-Fi + API settings (ignored by git).
- `.micropico`: MicroPico project marker.
- `.vscode/`: Workspace settings.

## Requirements

- Raspberry Pi Pico W (required)
- Pico-compatible display supported by `picographics`
- MicroPython firmware with:
  - `network`
  - `urequests`
  - `picographics`
- One of:
  - Thonny
  - VS Code with a Pi Pico extension (for example MicroPico)

## Configuration

1. Create or update `secrets.py` in repo root:

```python
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
WIFI_COUNTRY = "US"  # Optional country code
API_BASE_URL = "http://example.com"  # Base URL or IP (no trailing slash needed)
```

2. Endpoints are built automatically from `API_BASE_URL`:

- Lap endpoint: `/v1/laps?session_key=latest`
- Session-result endpoint: `/v1/session_result?session_key=latest`

3. Optional: edit fallback startup drivers in `DEFAULT_TRACKED_DRIVERS`.

Lap endpoint expected fields:

- `lap_duration` (required)
- `driver_number` (optional, falls back to URL `driver_number`)
- `lap_number` (optional)

Session-result endpoint expected fields:

- A list payload, or a dict containing a list (for example `results`, `data`, `classification`).
- Each entry should include a driver number (`driver_number`, `driverNumber`, `number`, or nested `driver`) and preferably a position (`position`, `pos`, `rank`, etc.).

## Local Validation

Run a fast syntax check before deploying:

```bash
python3 -m py_compile main.py
```

## Upload and Run on Pico W (Thonny)

1. Connect the Pico W board over USB.
2. Open `main.py` and `secrets.py` in Thonny.
3. Select interpreter: `MicroPython (Raspberry Pi Pico)`.
4. Save both files to the Pico filesystem as `main.py` and `secrets.py`.
5. Run `main.py` from Thonny.

## Upload and Run on Pico W (VS Code + Pi Pico Extension)

1. Connect the Pico W board over USB.
2. Open this project folder in VS Code.
3. Use your Pi Pico extension to connect to the board.
4. Upload `main.py` and `secrets.py` to the device root.
5. Run or reset the device from the extension controls.

## Behavior Notes

- Startup shows `Booting...` and network status.
- After Wi-Fi connects, startup attempts to load top 3 drivers from `SESSION_RESULT_URL`.
- Wi-Fi connection is retried until successful.
- If session-result fetch fails, fallback drivers are used.
- API or parse errors are shown as `Fetch error` and the loop continues.
- Main screen button controls:
  - `A`: open driver selection
- Driver selection controls:
  - `X`/`Y`: move up/down
  - `B`: confirm/select
  - `A`: cancel and go back to main screen
- The display updates only when lap values or tracked drivers change.

## Troubleshooting

- Device has no Wi-Fi: Raspberry Pi Pico (non-W) is not supported for this project.
- `SSID not found (2.4GHz?)`: Ensure the network is 2.4GHz and in range.
- `Session result error`: Check `SESSION_RESULT_URL`, server status, and response payload shape.
- `HTTP <code>`: Check `API_BASE_URL`, server status, and network route from Pico.
- `No lap_duration values yet`: API response is valid but missing expected data.
- `No lap data`: Endpoint returned an empty payload.

## Security

- Never commit real Wi-Fi credentials.
- Keep `secrets.py` local; it is ignored by `.gitignore`.
