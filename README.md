# Pico F1 Lap Display

MicroPython app for Raspberry Pi Pico + Pico Display that connects to Wi-Fi, polls a lap-time API, and renders the latest lap on screen.

Example display line:

`HAM - 01:37.154`

## What It Does

- Connects to Wi-Fi with retry and status feedback.
- Polls an API endpoint every 5 seconds.
- Parses both JSON list and single-object payloads.
- Uses memory-conscious tail parsing for larger responses.
- Displays fetch/network errors without crashing.

## Project Layout

- `main.py`: Main application entrypoint.
- `secrets.py`: Local Wi-Fi settings (ignored by git).
- `.micropico`: MicroPico project marker.
- `.vscode/`: Workspace settings.

## Requirements

- Raspberry Pi Pico / Pico W
- Pico-compatible display supported by `picographics`
- MicroPython firmware with:
  - `network`
  - `urequests`
  - `picographics`
- `mpremote` installed on your workstation (optional but recommended)

## Configuration

1. Create or update `secrets.py` in repo root:

```python
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
WIFI_COUNTRY = "US"  # Optional country code
```

2. Edit `API_URL` in `main.py` to your lap API endpoint.

Current expected fields:

- `lap_duration` (required)
- `driver_number` (optional, falls back to URL `driver_number`)
- `lap_number` (optional)

## Local Validation

Run a fast syntax check before deploying:

```bash
python3 -m py_compile main.py
```

## Deploy and Run on Pico

```bash
mpremote fs cp main.py :main.py
mpremote fs cp secrets.py :secrets.py
mpremote run main.py
```

To restart the board:

```bash
mpremote soft-reset
```

## Behavior Notes

- Startup shows `Booting...` and network status.
- Wi-Fi connection is retried until successful.
- API or parse errors are shown as `Fetch error` and the loop continues.
- The display updates only when lap value/driver changes.

## Troubleshooting

- `SSID not found (2.4GHz?)`: Ensure the network is 2.4GHz and in range.
- `HTTP <code>`: Check API URL, server status, and network route from Pico.
- `No lap_duration values yet`: API response is valid but missing expected data.
- `No lap data`: Endpoint returned an empty payload.

## Security

- Never commit real Wi-Fi credentials.
- Keep `secrets.py` local; it is ignored by `.gitignore`.
