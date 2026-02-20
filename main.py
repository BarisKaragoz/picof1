import time

import gc
import network
import picographics as pg # type: ignore
from pimoroni import Button  # type: ignore
import urequests

try:
    import ujson as json
except ImportError:
    import json


DEFAULT_TRACKED_DRIVERS = [44, 81, 3]  # fallback if startup ranking fetch fails
TRACKED_DRIVERS = list(DEFAULT_TRACKED_DRIVERS)
TRACKED_DRIVER_COUNT = 3

from secrets import WIFI_SSID, WIFI_PASSWORD, WIFI_COUNTRY

try:
    from secrets import API_BASE_URL
except ImportError:
    API_BASE_URL = "http://192.168.26.249:8000"

# Set API_BASE_URL in secrets.py (example: http://example.com).
BASE_URL = API_BASE_URL.rstrip("/")
LAPS_BASE_URL = BASE_URL + "/v1/laps?session_key=latest"
SESSION_RESULT_URL = BASE_URL + "/v1/session_result?session_key=latest"
MEETINGS_URL = BASE_URL + "/v1/meetings?meeting_key=latest"
SESSIONS_URL = BASE_URL + "/v1/sessions?session_key=latest"
DRIVER_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/2025/driverstandings.json"
CONSTRUCTOR_STANDINGS_URL = "https://api.jolpi.ca/ergast/f1/2025/constructorStandings.json"
DRIVER_STANDINGS_FALLBACK_URLS = (
    DRIVER_STANDINGS_URL,
    "http://api.jolpi.ca/ergast/f1/2025/driverstandings.json",
)
CONSTRUCTOR_STANDINGS_FALLBACK_URLS = (
    CONSTRUCTOR_STANDINGS_URL,
    "http://api.jolpi.ca/ergast/f1/2025/constructorStandings.json",
)

POLL_INTERVAL_SECONDS = 5
STARTUP_DELAY_SECONDS = 1.5
HTTP_READ_CHUNK_BYTES = 256
HTTP_TAIL_BYTES = 4096
STANDINGS_READ_CHUNK_BYTES = 128
STANDINGS_RETRY_COUNT = 2
DISPLAY_BRIGHTNESS = 0.4
BUTTON_POLL_SECONDS = 0.02
BUTTON_RELEASE_POLL_SECONDS = 0.01
BUTTON_RELEASE_DEBOUNCE_SECONDS = 0.03

DRIVER_CODES = {
    1: "NOR",
    3: "VER",
    5: "BOR",
    6: "HAD",
    10: "GAS",
    11: "PER",
    12: "ANT",
    14: "ALO",
    16: "LEC",
    18: "STR",
    23: "ALB",
    27: "HUL",
    30: "LAW",
    31: "OCO",
    41: "LIN",
    43: "COL",
    44: "HAM",
    55: "SAI",
    63: "RUS",
    77: "BOT",
    81: "PIA",
    87: "BEAR",
}


DISPLAY_TYPE = getattr(pg, "DISPLAY_PICO_DISPLAY_2", None)
if DISPLAY_TYPE is None:
    DISPLAY_TYPE = pg.DISPLAY_PICO_DISPLAY

display = pg.PicoGraphics(display=DISPLAY_TYPE)
display.set_backlight(DISPLAY_BRIGHTNESS)

WIDTH, HEIGHT = display.get_bounds()

BLACK = display.create_pen(0, 0, 0)
WHITE = display.create_pen(255, 255, 255)
GREEN = display.create_pen(80, 240, 120)
RED = display.create_pen(255, 80, 80)
CYAN = display.create_pen(80, 220, 255)

event_name = ""
session_type_name = ""
circuit_short_name = ""
country_name = ""
show_event_info = True

BUTTON_A = Button(12)
BUTTON_B = Button(13)
BUTTON_X = Button(14)
BUTTON_Y = Button(15)

ROW_HEIGHT = 28
VISIBLE_ROWS = (HEIGHT - 12) // ROW_HEIGHT - 1  # minus title row


def event_info_snapshot():
    return (event_name, session_type_name, circuit_short_name, country_name)


def format_driver_code(driver_number):
    if driver_number is None:
        return "?"

    try:
        driver_number = int(driver_number)
    except Exception:
        return str(driver_number)

    return DRIVER_CODES.get(driver_number, str(driver_number))


def api_url_for_driver(driver_number):
    return LAPS_BASE_URL + "&driver_number={}".format(driver_number)



def to_int(value):
    try:
        return int(value)
    except Exception:
        return None


def to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def driver_number_from_result_entry(entry):
    if isinstance(entry, (int, float, str)):
        return to_int(entry)
    if not isinstance(entry, dict):
        return None

    raw_driver = entry.get("driver_number")
    if raw_driver is None:
        raw_driver = entry.get("driverNumber")
    if raw_driver is None:
        raw_driver = entry.get("number")
    if raw_driver is None:
        raw_driver = entry.get("driver")

    if isinstance(raw_driver, dict):
        nested = raw_driver.get("driver_number")
        if nested is None:
            nested = raw_driver.get("driverNumber")
        if nested is None:
            nested = raw_driver.get("number")
        if nested is None:
            nested = raw_driver.get("id")
        raw_driver = nested

    return to_int(raw_driver)


def position_from_result_entry(entry, fallback_position):
    if not isinstance(entry, dict):
        return fallback_position

    for key in (
        "position",
        "pos",
        "rank",
        "classification_position",
        "final_position",
        "placement",
        "order",
    ):
        value = to_int(entry.get(key))
        if value is not None:
            return value
    return fallback_position


def result_entries_from_payload(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in (
            "results",
            "data",
            "session_result",
            "session_results",
            "classification",
            "items",
            "drivers",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]

    return []


def top_drivers_from_session_payload(payload, limit=TRACKED_DRIVER_COUNT):
    entries = result_entries_from_payload(payload)
    ranked = []

    for idx, entry in enumerate(entries):
        driver_number = driver_number_from_result_entry(entry)
        if driver_number is None:
            continue
        position = position_from_result_entry(entry, idx + 1)
        ranked.append((position, idx, driver_number))

    if not ranked:
        raise RuntimeError("No drivers in session_result")

    ranked.sort()
    top_drivers = []
    seen = set()
    for _position, _idx, driver_number in ranked:
        if driver_number in seen:
            continue
        seen.add(driver_number)
        top_drivers.append(driver_number)
        if len(top_drivers) >= limit:
            break

    for driver_number in DEFAULT_TRACKED_DRIVERS:
        if len(top_drivers) >= limit:
            break
        if driver_number not in seen:
            seen.add(driver_number)
            top_drivers.append(driver_number)

    if not top_drivers:
        raise RuntimeError("No usable drivers in session_result")

    return top_drivers[:limit]


def fetch_top_session_drivers(limit=TRACKED_DRIVER_COUNT):
    response = None
    gc.collect()
    try:
        response = urequests.get(SESSION_RESULT_URL)
        if response.status_code != 200:
            raise RuntimeError("HTTP {}".format(response.status_code))
        payload = json.loads(response.text)
        return top_drivers_from_session_payload(payload, limit)
    finally:
        if response is not None:
            response.close()
        gc.collect()


def fetch_event_and_session_info():
    global event_name, session_type_name, circuit_short_name, country_name
    response = None
    gc.collect()
    try:
        response = urequests.get(MEETINGS_URL)
        if response.status_code == 200:
            payload = json.loads(response.text)
            if isinstance(payload, list) and payload:
                payload = payload[-1]
            if isinstance(payload, dict):
                event_name = payload.get("meeting_name", "")
    except Exception:
        pass
    finally:
        if response is not None:
            response.close()
        gc.collect()

    response = None
    gc.collect()
    try:
        response = urequests.get(SESSIONS_URL)
        if response.status_code == 200:
            payload = json.loads(response.text)
            if isinstance(payload, list) and payload:
                payload = payload[-1]
            if isinstance(payload, dict):
                st = payload.get("session_type", "")
                sn = payload.get("session_name", "")
                parts = []
                if st:
                    parts.append(str(st))
                if sn:
                    parts.append(str(sn))
                session_type_name = " - ".join(parts)
                val = payload.get("circuit_short_name", "")
                circuit_short_name = str(val) if val else ""
                val = payload.get("country_name", "")
                country_name = str(val) if val else ""
    except Exception:
        pass
    finally:
        if response is not None:
            response.close()
        gc.collect()


def standings_lists_from_payload(payload):
    current = payload
    if isinstance(current, dict):
        mr_data = current.get("MRData")
        if isinstance(mr_data, dict):
            current = mr_data
    if isinstance(current, dict):
        table = current.get("StandingsTable")
        if isinstance(table, dict):
            current = table

    if isinstance(current, dict):
        lists = current.get("StandingsLists")
        if isinstance(lists, list):
            return lists
        if isinstance(lists, dict):
            return [lists]

    if isinstance(current, list):
        return current

    return []


def standings_entries_from_payload(payload, entry_key):
    standings_lists = standings_lists_from_payload(payload)
    for standings in reversed(standings_lists):
        if not isinstance(standings, dict):
            continue
        entries = standings.get(entry_key)
        if isinstance(entries, list):
            return entries
        if isinstance(entries, dict):
            return [entries]
    return []


def ellipsize(text, max_len):
    value = str(text)
    if len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 3] + "..."


def compact_number_text(value):
    text = str(value)
    if text.endswith(".0"):
        return text[:-2]
    return text


def format_driver_standing_entry(entry, fallback_position):
    if not isinstance(entry, dict):
        return None, fallback_position

    position = to_int(entry.get("position"))
    if position is None:
        position = fallback_position

    points = entry.get("points")
    if points is None:
        points = "?"
    points_text = compact_number_text(points)

    wins = entry.get("wins")
    if wins is None:
        wins = "?"
    wins_text = compact_number_text(wins)

    driver = entry.get("Driver")
    code = ""
    family_name = ""
    if isinstance(driver, dict):
        raw_code = driver.get("code")
        if raw_code:
            code = str(raw_code).upper()

        raw_family_name = driver.get("familyName")
        if raw_family_name:
            family_name = str(raw_family_name).upper()

        if not code:
            raw_driver_id = driver.get("driverId")
            if raw_driver_id:
                parts = str(raw_driver_id).replace("-", "_").split("_")
                code = parts[-1][:3].upper()

    if not code:
        code = family_name[:3] if family_name else "DRV"

    row = ("P{:02d}".format(position), code, points_text, "W{}".format(wins_text))
    return row, position


def format_constructor_standing_entry(entry, fallback_position):
    if not isinstance(entry, dict):
        return None, fallback_position

    position = to_int(entry.get("position"))
    if position is None:
        position = fallback_position

    points = entry.get("points")
    if points is None:
        points = "?"
    points_text = compact_number_text(points)

    wins = entry.get("wins")
    if wins is None:
        wins = "?"
    wins_text = compact_number_text(wins)

    name = "TEAM"
    constructor = entry.get("Constructor")
    if isinstance(constructor, dict):
        raw_name = constructor.get("name")
        if raw_name:
            name = str(raw_name).upper()

    short_name = ellipsize(name, 8)
    row = ("P{:02d}".format(position), short_name, points_text, "W{}".format(wins_text))
    return row, position


def standings_lines_from_entries(entries, format_fn):
    ranked = []
    for idx, entry in enumerate(entries):
        row, position = format_fn(entry, idx + 1)
        if row is None:
            continue
        ranked.append((position, idx, row))

    if not ranked:
        raise RuntimeError("No standings data")

    ranked.sort()
    return [row for _position, _idx, row in ranked]


def standings_rows_from_stream(raw_stream, entry_key, format_fn):
    key_bytes = '"{}"'.format(entry_key).encode("utf-8")
    header = bytearray()
    key_found = False
    array_started = False

    in_string = False
    escape = False
    object_depth = 0
    object_bytes = bytearray()

    ranked = []
    object_count = 0

    def finalize_object():
        nonlocal object_bytes, object_count, ranked
        object_count += 1
        try:
            entry = json.loads(object_bytes.decode("utf-8"))
        except Exception:
            object_bytes = bytearray()
            return

        row, position = format_fn(entry, object_count)
        object_bytes = bytearray()
        if row is None:
            return
        ranked.append((position, object_count, row))

    while True:
        chunk = raw_stream.read(STANDINGS_READ_CHUNK_BYTES)
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            chunk = str(chunk).encode("utf-8")

        data = chunk
        if not array_started:
            header.extend(data)
            if not key_found:
                key_index = header.find(key_bytes)
                if key_index < 0:
                    keep_bytes = len(key_bytes) * 2
                    if len(header) > keep_bytes:
                        header = header[-keep_bytes:]
                    continue
                key_found = True
                header = header[key_index + len(key_bytes):]

            array_index = header.find(b"[")
            if array_index < 0:
                if len(header) > 64:
                    header = header[-64:]
                continue

            array_started = True
            data = header[array_index + 1 :]
            header = bytearray()

        for byte in data:
            if in_string:
                if object_depth > 0:
                    object_bytes.append(byte)
                if escape:
                    escape = False
                elif byte == 92:  # backslash
                    escape = True
                elif byte == 34:  # quote
                    in_string = False
                continue

            if byte == 34:  # quote
                in_string = True
                if object_depth > 0:
                    object_bytes.append(byte)
                continue

            if byte == 123:  # {
                if object_depth == 0:
                    object_bytes = bytearray()
                object_depth += 1
                object_bytes.append(byte)
                continue

            if byte == 125:  # }
                if object_depth > 0:
                    object_depth -= 1
                    object_bytes.append(byte)
                    if object_depth == 0:
                        finalize_object()
                continue

            if object_depth > 0:
                object_bytes.append(byte)
                continue

            if byte == 93:  # ]
                if not ranked:
                    raise RuntimeError("No standings data")
                ranked.sort()
                return [row for _position, _idx, row in ranked]

    if not ranked:
        raise RuntimeError("No standings data")
    ranked.sort()
    return [row for _position, _idx, row in ranked]


def is_enomem_error(exc):
    if not isinstance(exc, OSError):
        return False
    if not exc.args:
        return False
    try:
        return int(exc.args[0]) == 12
    except Exception:
        return False


def aggressive_gc():
    gc.collect()
    gc.collect()


def fetch_standing_rows(url_candidates, entry_key, format_fn):
    if isinstance(url_candidates, str):
        url_candidates = (url_candidates,)

    last_error = None

    for url in url_candidates:
        for attempt in range(STANDINGS_RETRY_COUNT):
            response = None
            aggressive_gc()
            try:
                response = urequests.get(url)
                if response.status_code != 200:
                    raise RuntimeError("HTTP {}".format(response.status_code))

                raw_stream = getattr(response, "raw", None)
                if raw_stream is not None:
                    return standings_rows_from_stream(raw_stream, entry_key, format_fn)

                # Fallback for unusual urequests implementations.
                payload = json.loads(response.text)
                entries = standings_entries_from_payload(payload, entry_key)
                return standings_lines_from_entries(entries, format_fn)
            except Exception as exc:
                last_error = exc
                if is_enomem_error(exc) and attempt + 1 < STANDINGS_RETRY_COUNT:
                    time.sleep(0.2)
                    aggressive_gc()
                    continue
                break
            finally:
                if response is not None:
                    response.close()
                aggressive_gc()

    if last_error is not None:
        raise last_error
    raise RuntimeError("No standings source available")


def fetch_driver_standing_lines():
    return fetch_standing_rows(
        DRIVER_STANDINGS_FALLBACK_URLS, "DriverStandings", format_driver_standing_entry
    )


def fetch_constructor_standing_lines():
    return fetch_standing_rows(
        CONSTRUCTOR_STANDINGS_FALLBACK_URLS, "ConstructorStandings", format_constructor_standing_entry
    )


def draw_lines(lines, color=WHITE):
    display.set_pen(BLACK)
    display.clear()

    display.set_pen(color)
    y = 12
    for line in lines:
        display.text(str(line), 8, y, WIDTH - 16, 2)
        y += 28

    display.update()


def wait_for_release(debounce_seconds=BUTTON_RELEASE_DEBOUNCE_SECONDS):
    """Block until all buttons are released, with a short debounce."""
    while (BUTTON_A.read() or BUTTON_B.read() or
           BUTTON_X.read() or BUTTON_Y.read()):
        time.sleep(BUTTON_RELEASE_POLL_SECONDS)
    if debounce_seconds > 0:
        time.sleep(debounce_seconds)


def pick_from_list(title, items, format_fn):
    """Show a scrollable list and return selected index, or None on cancel."""
    cursor = 0
    count = len(items)
    window_start = 0

    while True:
        # Keep cursor visible within the window
        if cursor < window_start:
            window_start = cursor
        if cursor >= window_start + VISIBLE_ROWS:
            window_start = cursor - VISIBLE_ROWS + 1

        display.set_pen(BLACK)
        display.clear()

        # Title
        display.set_pen(WHITE)
        display.text(title, 8, 12, WIDTH - 16, 2)

        # List items
        for i in range(VISIBLE_ROWS):
            idx = window_start + i
            if idx >= count:
                break
            label = format_fn(items[idx])
            y = 12 + (i + 1) * ROW_HEIGHT
            if idx == cursor:
                display.set_pen(CYAN)
                display.text("> {}".format(label), 8, y, WIDTH - 16, 2)
            else:
                display.set_pen(WHITE)
                display.text("  {}".format(label), 8, y, WIDTH - 16, 2)

        display.update()

        # Wait for a button press
        while True:
            if BUTTON_A.read():
                wait_for_release()
                return None
            if BUTTON_X.read():
                cursor = (cursor - 1) % count
                wait_for_release()
                break
            if BUTTON_Y.read():
                cursor = (cursor + 1) % count
                wait_for_release()
                break
            if BUTTON_B.read():
                wait_for_release()
                return cursor
            time.sleep(BUTTON_POLL_SECONDS)


def select_driver_interactive():
    """Two-step interactive driver selection; A cancels back to main screen."""
    all_numbers = sorted(DRIVER_CODES.keys())

    new_idx = pick_from_list(
        "Pick driver",
        all_numbers,
        lambda n: "{} #{}".format(DRIVER_CODES[n], n),
    )
    if new_idx is None:
        return False
    new_driver = all_numbers[new_idx]

    slot_idx = pick_from_list(
        "Replace who?",
        TRACKED_DRIVERS,
        lambda n: "{} #{}".format(format_driver_code(n), n),
    )
    if slot_idx is None:
        return False
    TRACKED_DRIVERS[slot_idx] = new_driver
    return True


def show_scrollable_lines(title, lines):
    if not lines:
        lines = ["No data"]

    cursor = 0
    count = len(lines)
    window_start = 0

    while True:
        # Keep cursor visible within the window.
        if cursor < window_start:
            window_start = cursor
        if cursor >= window_start + VISIBLE_ROWS:
            window_start = cursor - VISIBLE_ROWS + 1

        display.set_pen(BLACK)
        display.clear()

        display.set_pen(WHITE)
        display.text(title, 8, 12, WIDTH - 16, 2)

        for i in range(VISIBLE_ROWS):
            idx = window_start + i
            if idx >= count:
                break
            y = 12 + (i + 1) * ROW_HEIGHT
            if idx == cursor:
                display.set_pen(CYAN)
                display.text("> {}".format(lines[idx]), 8, y, WIDTH - 16, 2)
            else:
                display.set_pen(WHITE)
                display.text("  {}".format(lines[idx]), 8, y, WIDTH - 16, 2)

        display.set_font("bitmap6")
        display.set_pen(CYAN)
        display.text("X up   Y down   A back", 8, HEIGHT - 12, WIDTH - 16, 1)
        display.set_font("bitmap8")
        display.update()

        while True:
            if BUTTON_A.read():
                wait_for_release()
                return
            if BUTTON_X.read():
                cursor = (cursor - 1) % count
                wait_for_release()
                break
            if BUTTON_Y.read():
                cursor = (cursor + 1) % count
                wait_for_release()
                break
            time.sleep(BUTTON_POLL_SECONDS)


def fit_text_to_width(text, max_width, scale=2):
    value = str(text)
    if max_width <= 0:
        return ""

    if text_pixel_width(value, scale) <= max_width:
        return value

    ellipsis = "..."
    ellipsis_width = text_pixel_width(ellipsis, scale)
    if ellipsis_width >= max_width:
        return ""

    while value and text_pixel_width(value + ellipsis, scale) > max_width:
        value = value[:-1]
    return value + ellipsis


def show_scrollable_standings_rows(title, rows):
    if not rows:
        rows = [("P--", "N/A", "?", "W?")]

    display.set_font("bitmap8")

    cursor = 0
    count = len(rows)
    window_start = 0

    left_margin = 8
    right_margin = 8
    marker_width = text_pixel_width(">", 2) + 4
    gap = 6

    pos_col_width = text_pixel_width("P00", 2)
    name_col_width = text_pixel_width("TEAM", 2)
    points_col_width = text_pixel_width("0000", 2)
    wins_col_width = text_pixel_width("W00", 2)

    for pos_text, name_text, points_text, wins_text in rows:
        pos_col_width = max(pos_col_width, text_pixel_width(pos_text, 2))
        name_col_width = max(name_col_width, text_pixel_width(name_text, 2))
        points_col_width = max(points_col_width, text_pixel_width(points_text, 2))
        wins_col_width = max(wins_col_width, text_pixel_width(wins_text, 2))

    pos_x = left_margin + marker_width
    name_x = pos_x + pos_col_width + gap
    points_x = name_x + name_col_width + gap
    wins_x = points_x + points_col_width + gap

    used_width = wins_x + wins_col_width + right_margin
    if used_width > WIDTH:
        overflow = used_width - WIDTH
        min_name_width = text_pixel_width("AAA", 2)
        name_col_width = max(min_name_width, name_col_width - overflow)
        points_x = name_x + name_col_width + gap
        wins_x = points_x + points_col_width + gap

    while True:
        # Keep cursor visible within the window.
        if cursor < window_start:
            window_start = cursor
        if cursor >= window_start + VISIBLE_ROWS:
            window_start = cursor - VISIBLE_ROWS + 1

        display.set_pen(BLACK)
        display.clear()

        display.set_pen(WHITE)
        display.text(title, 8, 12, WIDTH - 16, 2)

        for i in range(VISIBLE_ROWS):
            idx = window_start + i
            if idx >= count:
                break

            y = 12 + (i + 1) * ROW_HEIGHT
            pos_text, name_text, points_text, wins_text = rows[idx]
            name_draw = fit_text_to_width(name_text, max(1, points_x - name_x - gap), 2)

            if idx == cursor:
                display.set_pen(CYAN)
                display.text(">", left_margin, y, marker_width, 2)
            else:
                display.set_pen(WHITE)

            display.text(pos_text, pos_x, y, pos_col_width, 2)
            display.text(name_draw, name_x, y, max(1, points_x - name_x - gap), 2)
            display.text(points_text, points_x, y, points_col_width, 2)
            display.text(wins_text, wins_x, y, wins_col_width, 2)

        display.set_font("bitmap6")
        display.set_pen(CYAN)
        display.text("X up   Y down   A back", 8, HEIGHT - 12, WIDTH - 16, 1)
        display.set_font("bitmap8")
        display.update()

        while True:
            if BUTTON_A.read():
                wait_for_release()
                return
            if BUTTON_X.read():
                cursor = (cursor - 1) % count
                wait_for_release()
                break
            if BUTTON_Y.read():
                cursor = (cursor + 1) % count
                wait_for_release()
                break
            time.sleep(BUTTON_POLL_SECONDS)


def show_standings_screen(title, fetch_lines_fn):
    draw_lines([title, "Loading..."], CYAN)
    gc.collect()
    try:
        rows_or_lines = fetch_lines_fn()
    except Exception as exc:
        rows_or_lines = ["Load error", str(exc), "Check Wi-Fi/API"]
    gc.collect()

    if rows_or_lines and isinstance(rows_or_lines[0], tuple) and len(rows_or_lines[0]) == 4:
        show_scrollable_standings_rows(title, rows_or_lines)
        return

    show_scrollable_lines(title, rows_or_lines)


def build_lap_rows(lap_results):
    rows = []
    leader_duration = None
    if TRACKED_DRIVERS:
        leader_result = lap_results.get(TRACKED_DRIVERS[0])
        if leader_result is not None:
            leader_duration = to_float(leader_result[0])

    for dn in TRACKED_DRIVERS:
        lap_result = lap_results.get(dn)
        if lap_result is not None:
            duration, lap_number = lap_result
            duration_text = format_lap_duration(duration)
            gap_text = format_gap_to_leader(duration, leader_duration)
            lap_text = format_lap_number(lap_number)
        else:
            duration_text = "--:--.---"
            gap_text = "+--.---"
            lap_text = "lap --"
        rows.append((format_driver_code(dn), duration_text, gap_text, lap_text))
    return rows


def text_pixel_width(text, scale=2):
    try:
        return display.measure_text(str(text), scale)
    except Exception:
        return len(str(text)) * 8 * scale


def draw_lap_screen(lap_results, color=WHITE):
    rows = build_lap_rows(lap_results)
    # Measure and render lap rows using a fixed font so column spacing
    # does not depend on whatever screen was shown previously.
    display.set_font("bitmap8")

    left_margin = 8
    right_margin = 8
    driver_gap = 8
    gap_gap = 6
    lap_gap = 6

    driver_col_width = text_pixel_width("WWW", 2)
    for driver_code, _duration_text, _gap_text, _lap_text in rows:
        code_width = text_pixel_width(driver_code, 2)
        if code_width > driver_col_width:
            driver_col_width = code_width

    duration_col_width = text_pixel_width("88:88.888", 2)
    gap_col_width = text_pixel_width("+88.888", 2)
    for _driver_code, _duration_text, gap_text, _lap_text in rows:
        gap_width = text_pixel_width(gap_text, 2)
        if gap_width > gap_col_width:
            gap_col_width = gap_width

    lap_col_width = text_pixel_width("lap 88", 2)

    duration_x = left_margin + driver_col_width + driver_gap
    gap_x = duration_x + duration_col_width + gap_gap
    lap_x = gap_x + gap_col_width + lap_gap

    # Keep everything on-screen on narrower displays.
    max_lap_x = WIDTH - right_margin - lap_col_width
    if lap_x > max_lap_x:
        lap_x = max_lap_x
        gap_x = lap_x - lap_gap - gap_col_width
        duration_x = gap_x - gap_gap - duration_col_width

    min_duration_x = left_margin + driver_col_width + 2
    if duration_x < min_duration_x:
        duration_x = min_duration_x
        gap_x = duration_x + duration_col_width + gap_gap
        lap_x = gap_x + gap_col_width + lap_gap

    driver_wrap = max(1, duration_x - left_margin - driver_gap)
    duration_wrap = max(1, gap_x - duration_x - gap_gap)
    gap_wrap = max(1, lap_x - gap_x - lap_gap)
    lap_wrap = max(1, WIDTH - lap_x - right_margin)

    display.set_pen(BLACK)
    display.clear()
    display.set_pen(color)
    display.text("Latest lap times", left_margin, 12, WIDTH - 16, 2)

    y = 12 + ROW_HEIGHT
    for driver_code, duration_text, gap_text, lap_text in rows:
        display.text(driver_code, left_margin, y, driver_wrap, 2)
        display.text(duration_text, duration_x, y, duration_wrap, 2)
        display.text(gap_text, gap_x, y, gap_wrap, 2)
        display.text(lap_text, lap_x, y, lap_wrap, 2)
        y += ROW_HEIGHT

    if show_event_info:
        info_y = y + 16
        info_scale = 2
        info_row_height = 18
        display.set_font("bitmap6")
        display.set_pen(CYAN)
        for info_text in (event_name, session_type_name, circuit_short_name, country_name):
            if info_text:
                tw = text_pixel_width(info_text, info_scale)
                info_x = (WIDTH - tw) // 2
                if info_x < 0:
                    info_x = 0
                display.text(info_text, info_x, info_y, WIDTH - info_x, info_scale)
                info_y += info_row_height

    display.set_font("bitmap8")

    display.update()


def draw_cached_main_screen(lap_results):
    if lap_results is not None:
        draw_lap_screen(lap_results, GREEN)
    else:
        draw_lap_screen({}, CYAN)


def handle_home_buttons(last_lap_results):
    global show_event_info

    if BUTTON_X.read():
        wait_for_release()
        show_standings_screen("Driver standings", fetch_driver_standing_lines)
        draw_cached_main_screen(last_lap_results)
        return True, last_lap_results

    if BUTTON_Y.read():
        wait_for_release()
        show_standings_screen("Constructor standings", fetch_constructor_standing_lines)
        draw_cached_main_screen(last_lap_results)
        return True, last_lap_results

    if BUTTON_A.read():
        wait_for_release()
        selection_changed = select_driver_interactive()
        if selection_changed and last_lap_results is not None:
            last_lap_results = {dn: last_lap_results.get(dn) for dn in TRACKED_DRIVERS}
        draw_cached_main_screen(last_lap_results)
        return True, last_lap_results

    if BUTTON_B.read():
        wait_for_release()
        show_event_info = not show_event_info
        draw_cached_main_screen(last_lap_results)
        return True, last_lap_results

    return False, last_lap_results


def connect_wifi(ssid, password, timeout_seconds=20):
    if WIFI_COUNTRY:
        try:
            import rp2

            rp2.country(WIFI_COUNTRY)
        except Exception:
            pass

    wlan = network.WLAN(network.STA_IF)
    try:
        wlan.active(False)
        time.sleep(0.2)
    except Exception:
        pass

    wlan.active(True)

    try:
        wlan.config(pm=0xA11140)  # Disable power save to avoid flaky station links.
    except Exception:
        pass

    status_map = {
        -3: "Wrong password",
        -2: "AP not found",
        -1: "Connect failed",
        0: "Idle",
        1: "Connecting",
        2: "No IP yet",
        3: "Connected",
    }

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        draw_lines(["Wi-Fi", "Already connected", ip], GREEN)
        time.sleep(1)
        return wlan

    try:
        wlan.disconnect()
    except Exception:
        pass

    # Pre-scan so we can distinguish "can't see AP" from auth failures.
    ap_found = False
    scan_ok = False
    ap_rssi = None
    try:
        draw_lines(["Wi-Fi", "Scanning...", ssid], CYAN)
        scan_ok = True
        for ap in wlan.scan():
            raw_ssid = ap[0]
            ap_name = raw_ssid.decode("utf-8", "ignore") if isinstance(raw_ssid, bytes) else str(raw_ssid)
            if ap_name == ssid:
                ap_found = True
                ap_rssi = ap[3]
                break
    except Exception:
        # Some firmware builds may fail scan while still allowing connect.
        pass

    if scan_ok and not ap_found:
        raise RuntimeError("SSID not found (2.4GHz?)")

    wlan.connect(ssid, password)

    def fail_connect(message):
        # Ensure failed attempts don't finish in the background and confuse
        # the next retry with an "Already connected" state.
        try:
            wlan.disconnect()
        except Exception:
            pass
        raise RuntimeError(message)

    start = time.ticks_ms()
    shown_second = -1
    while not wlan.isconnected():
        status = wlan.status()
        if status < 0:
            reason = status_map.get(status, "status {}".format(status))
            fail_connect("Wi-Fi {}".format(reason))

        elapsed = time.ticks_diff(time.ticks_ms(), start) // 1000
        if elapsed != shown_second:
            shown_second = elapsed
            rssi_text = "rssi {}".format(ap_rssi) if ap_rssi is not None else "rssi ?"
            draw_lines(
                ["Wi-Fi", "Connecting {}s".format(elapsed), "st {} {}".format(status, rssi_text)],
                CYAN,
            )

        if time.ticks_diff(time.ticks_ms(), start) > timeout_seconds * 1000:
            reason = status_map.get(wlan.status(), "status {}".format(wlan.status()))
            fail_connect("Timeout ({})".format(reason))

        time.sleep(0.25)

    draw_lines(["Wi-Fi connected", wlan.ifconfig()[0]], GREEN)
    time.sleep(1)
    return wlan


def lap_from_payload(payload):
    if isinstance(payload, list):
        for lap in reversed(payload):
            if not isinstance(lap, dict):
                continue
            lap_duration = lap.get("lap_duration")
            if lap_duration is not None:
                return lap_duration, lap.get("lap_number"), lap.get("driver_number")
        return None, None, None

    if isinstance(payload, dict):
        lap_duration = payload.get("lap_duration")
        if lap_duration is not None:
            return lap_duration, payload.get("lap_number"), payload.get("driver_number")

    return None, None, None


def lap_from_tail_json(tail_text):
    # Walk backwards through object-shaped slices so we can parse without
    # materializing the full JSON array in memory.
    end = len(tail_text)
    while True:
        end = tail_text.rfind("}", 0, end)
        if end < 0:
            break
        start = tail_text.rfind("{", 0, end)
        if start < 0:
            break
        try:
            candidate = json.loads(tail_text[start : end + 1])
        except Exception:
            end = start
            continue

        lap_duration, lap_number, dn = lap_from_payload(candidate)
        if lap_duration is not None:
            return lap_duration, lap_number, dn

        end = start

    raise RuntimeError("No lap_duration values yet")


def fetch_latest_lap_duration(driver_number):
    url = api_url_for_driver(driver_number)
    response = None
    gc.collect()
    try:
        response = urequests.get(url)
        if response.status_code != 200:
            raise RuntimeError("HTTP {}".format(response.status_code))

        raw_stream = getattr(response, "raw", None)
        if raw_stream is None:
            # Fallback for unusual urequests implementations.
            payload = json.loads(response.text)
            lap_duration, lap_number, dn = lap_from_payload(payload)
            if lap_duration is not None:
                return lap_duration, lap_number, driver_number
            raise RuntimeError("No lap_duration values yet")

        tail = bytearray()
        while True:
            chunk = raw_stream.read(HTTP_READ_CHUNK_BYTES)
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray)):
                chunk = str(chunk).encode("utf-8")
            tail.extend(chunk)
            if len(tail) > HTTP_TAIL_BYTES:
                overflow = len(tail) - HTTP_TAIL_BYTES
                tail = tail[overflow:]
    finally:
        if response is not None:
            response.close()
        gc.collect()

    if not tail:
        raise RuntimeError("No lap data")

    tail_text = tail.decode("utf-8", "ignore")
    try:
        payload = json.loads(tail_text)
    except Exception:
        payload = None

    if payload is not None:
        lap_duration, lap_number, dn = lap_from_payload(payload)
        if lap_duration is not None:
            return lap_duration, lap_number, driver_number

    lap_duration, lap_number, _ = lap_from_tail_json(tail_text)
    return lap_duration, lap_number, driver_number


def format_lap_duration(value):
    try:
        total_seconds = float(value)
    except Exception:
        return str(value)

    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    millis = int(round((total_seconds - int(total_seconds)) * 1000))

    if millis == 1000:
        seconds += 1
        millis = 0
    if seconds == 60:
        minutes += 1
        seconds = 0

    return "{:02d}:{:02d}.{:03d}".format(minutes, seconds, millis)


def format_gap_to_leader(duration, leader_duration):
    if leader_duration is None:
        return "+--.---"

    duration_seconds = to_float(duration)
    if duration_seconds is None:
        return "+--.---"

    gap_seconds = duration_seconds - leader_duration
    sign = "+" if gap_seconds >= 0 else "-"
    gap_seconds = abs(gap_seconds)

    whole_seconds = int(gap_seconds)
    millis = int(round((gap_seconds - whole_seconds) * 1000))

    if millis == 1000:
        whole_seconds += 1
        millis = 0

    return "{}{}.{:03d}".format(sign, whole_seconds, millis)


def format_lap_number(value):
    if value is None:
        return "lap --"
    try:
        return "lap {:02d}".format(int(value))
    except Exception:
        return "lap {}".format(value)


def main():
    global show_event_info
    draw_lines(["Booting...", "Starting network"], CYAN)
    time.sleep(STARTUP_DELAY_SECONDS)

    if WIFI_SSID == "YOUR_WIFI_SSID":
        draw_lines(["Set Wi-Fi creds", "in main.py"], RED)
        while True:
            time.sleep(1)

    wlan = None
    wifi_attempt = 0
    while wlan is None:
        try:
            wifi_attempt += 1
            wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD)
        except Exception as exc:
            draw_lines(["Wi-Fi error", "try #{}".format(wifi_attempt), str(exc)], RED)
            time.sleep(5)

    try:
        TRACKED_DRIVERS[:] = fetch_top_session_drivers(TRACKED_DRIVER_COUNT)
    except Exception as exc:
        TRACKED_DRIVERS[:] = list(DEFAULT_TRACKED_DRIVERS)
        draw_lines(["Session result error", str(exc)], RED)
        time.sleep(1.5)

    try:
        fetch_event_and_session_info()
    except Exception:
        pass

    last_lap_results = None
    last_event_info = event_info_snapshot()

    while True:
        handled_button, last_lap_results = handle_home_buttons(last_lap_results)
        if handled_button:
            continue

        try:
            if not wlan.isconnected():
                wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD)

            try:
                fetch_event_and_session_info()
            except Exception:
                pass
            current_event_info = event_info_snapshot()

            lap_results = {}
            skip_fetch_cycle = False
            for dn in TRACKED_DRIVERS:
                handled_button, last_lap_results = handle_home_buttons(last_lap_results)
                if handled_button:
                    skip_fetch_cycle = True
                    break
                try:
                    lap_duration, lap_number, _ = fetch_latest_lap_duration(dn)
                    lap_results[dn] = (lap_duration, lap_number)
                except Exception:
                    lap_results[dn] = None

            if skip_fetch_cycle:
                continue

            if lap_results != last_lap_results or current_event_info != last_event_info:
                draw_lap_screen(lap_results, GREEN)
                last_lap_results = lap_results
                last_event_info = current_event_info
        except Exception as exc:
            draw_lines(["Fetch error", str(exc)], RED)

        poll_deadline = time.ticks_add(time.ticks_ms(), int(POLL_INTERVAL_SECONDS * 1000))
        while time.ticks_diff(poll_deadline, time.ticks_ms()) > 0:
            handled_button, last_lap_results = handle_home_buttons(last_lap_results)
            if handled_button:
                # Keep the home screen interactive for a full poll interval
                # after handling a button.
                poll_deadline = time.ticks_add(time.ticks_ms(), int(POLL_INTERVAL_SECONDS * 1000))
                continue
            time.sleep(BUTTON_POLL_SECONDS)


main()
