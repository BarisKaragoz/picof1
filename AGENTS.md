# Repository Guidelines

## Project Structure & Module Organization
This repository is intentionally small and device-focused.

- `main.py`: Main MicroPython application (Wi-Fi connection, API polling, lap parsing, and display rendering).
- `secrets.py`: Local Wi-Fi + API base URL settings (ignored by `.gitignore`).
- `.vscode/`: Workspace settings and recommended extensions for Python/Pico development.
- `.micropico`: Project marker file used by MicroPico tooling.
- `__pycache__/`: Local bytecode artifacts (ignored via `.gitignore`).

If the codebase grows, keep `main.py` as the entrypoint and move reusable logic into small modules.

## Build, Test, and Development Commands
Use these commands from the repository root:

- `python3 -m py_compile main.py`: Fast syntax validation before committing.
- `mpremote fs cp main.py :main.py`: Copy updated script to the connected Pico (if `mpremote` is installed).
- `mpremote fs cp secrets.py :secrets.py`: Copy local configuration to the connected Pico.
- `mpremote run main.py`: Run the script on-device from your workstation.
- `mpremote soft-reset`: Restart the board after updates.

## Coding Style & Naming Conventions
- Use 4-space indentation and keep functions focused and short.
- Follow existing naming: `snake_case` for functions/variables, `UPPER_CASE` for constants.
- Keep output formatting consistent with current code style (e.g., `str.format(...)` patterns already in use).
- Prefer memory-conscious patterns compatible with MicroPython (chunked reads, bounded buffers, explicit cleanup when needed).

## Testing Guidelines
There is no formal automated test suite yet.

- Minimum check: `python3 -m py_compile main.py`.
- Hardware smoke test on Pico should verify Wi-Fi connects and retries cleanly on failure.
- Hardware smoke test on Pico should verify API fetch errors are shown without crashing.
- Hardware smoke test on Pico should verify display format (e.g., `HAM 01:37.154 lap 12`).
- When changing parsing logic, test with both list and single-object JSON payloads.

## Commit & Pull Request Guidelines
Git history in this repo uses short, imperative commit titles (examples: `Add ...`, `Remove ...`).

- Keep commit subjects concise and action-oriented.
- In PRs, include what changed, why it changed, and what was tested on hardware.
- For display/UI text changes, include a photo or clear before/after notes.
- Never commit real secrets; replace `WIFI_SSID`, `WIFI_PASSWORD`, `API_BASE_URL`, and sensitive URLs with safe values before pushing.
