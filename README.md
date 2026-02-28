#### Important
I think transparency is important and I hereby honestly state that this project is vibe-coded. I am not a programmer, just someone with creative ideas and I use LLMs to make those ideas possible. I tried to follow best practices regarding security (like storing secrets in separate files that are not committed to GitHub) but again, I’m not a programmer. Feel free to fork this project and improve it or submit PRs. Enjoy!

# Pico F1 Lap Display

MicroPython app for Raspberry Pi Pico W + Pico Display that connects to Wi-Fi, loads top drivers from session results on cold boot, polls OpenF1 lap-time data, and renders the latest laps on screen.

This project is based on a self-hosted version of the OpenF1 API. A self-hosted implementation is available on GitHub: [br-g/openf1](https://github.com/br-g/openf1). The official OpenF1 API at [openf1.org](https://openf1.org/) requires a subscription for live usage.

Example display line:

`HAM 01:37.154 +0.000 lap 12`

<img src="https://github.com/user-attachments/assets/9ecc3bc6-f215-4580-aef1-a9e39cf24149" width="400">

## What It Does

- Connects to Wi-Fi with retry and status feedback.
- On cold boot, fetches top 3 drivers from the session-result endpoint.
- Polls OpenF1 lap data every 5 seconds.
- Fetches meeting/session metadata every 60 seconds.
- Fetches driver and constructor championship standings from Jolpica.
- Uses memory-conscious tail parsing and streamed JSON parsing.
- Renders driver, lap time, gap-to-leader, and lap number in aligned columns.
- Shows empty lap placeholders when a driver has no lap data or the API is unavailable.
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

Use your self-hosted OpenF1-compatible base URL for `API_BASE_URL`.

2. Endpoints are built automatically from `API_BASE_URL` (OpenF1 endpoints):

- Lap endpoint: `/v1/laps?session_key=latest`
- Session-result endpoint: `/v1/session_result?session_key=latest`
- Meetings endpoint: `/v1/meetings?meeting_key=latest`
- Sessions endpoint: `/v1/sessions?session_key=latest`
- Driver standings endpoint: `https://api.jolpi.ca/ergast/f1/2025/last/driverstandings/?format=json`
- Constructor standings endpoint: `https://api.jolpi.ca/ergast/f1/2025/last/constructorstandings/?format=json`

3. Optional: edit initial startup drivers in `INITIAL_TRACKED_DRIVERS`.

Lap endpoint expected fields:

- `lap_duration` (required, latest non-null value is used)
- `driver_number` (required)
- `lap_number` (required key; `null` is shown as `lap --`)

Session-result endpoint expected fields:

- A list payload.
- Each entry must include `driver_number` and `position`.

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

## Controls

- Main screen:
  - `X`: open driver championship standings
  - `Y`: open constructor championship standings
  - `A`: open driver selection
  - `B`: toggle event/session info block
- Standings screens:
  - `X`: previous page
  - `Y`: next page
  - `A`: go back to the main screen
- Driver selection:
  - `X`/`Y`: move up/down
  - `B`: confirm/select
  - `A`: cancel and go back to main screen

## Behavior Notes

- Startup shows `Booting...` and network status.
- After Wi-Fi connects, startup attempts to load top 3 drivers from `SESSION_RESULT_URL`.
- Wi-Fi connection is retried until successful.
- If startup fetches fail, the app continues with `INITIAL_TRACKED_DRIVERS`.
- Event/session text (`meeting`, `session`, `circuit`, `country`) refreshes every 60 seconds.
- Main screen shows placeholders (`--:--.---`, `+--.---`, `lap --`) when no lap data is available.
- The display updates only when lap values, event/session info, or tracked drivers change.

## Troubleshooting

- Device has no Wi-Fi: Raspberry Pi Pico (non-W) is not supported for this project.
- `Wi-Fi Wrong password` / `Wi-Fi AP not found` / `Wi-Fi Connect failed`: verify credentials, Wi-Fi band (2.4GHz), and signal quality.
- `Timeout (<status>)` during Wi-Fi connect: check AP availability and DHCP/network stability.
- Standings screens returning `HTTP <code>`: verify internet connectivity and Jolpica API availability.
- Lap rows are empty: the selected driver may not have recent lap data, or OpenF1 may be offline/unreachable.

## Security

- Never commit real Wi-Fi credentials.
- Keep `secrets.py` local; it is ignored by `.gitignore`.
