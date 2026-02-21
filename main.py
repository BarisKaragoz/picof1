import time

import gc
import network
import picographics as pg # type: ignore
from pimoroni import Button  # type: ignore
import urequests
import ujson as json


INITIAL_TRACKED_DRIVERS = [44, 81, 3]
TRACKED_DRIVERS = list(INITIAL_TRACKED_DRIVERS)
TRACKED_DRIVER_COUNT = 3

from secrets import WIFI_SSID, WIFI_PASSWORD, WIFI_COUNTRY, API_BASE_URL

# Set API_BASE_URL in secrets.py (example: http://example.com).
BASE_URL = API_BASE_URL.rstrip("/")
LAPS_BASE_URL = BASE_URL + "/v1/laps?session_key=latest"
SESSION_RESULT_URL = BASE_URL + "/v1/session_result?session_key=latest"
MEETINGS_URL = BASE_URL + "/v1/meetings?meeting_key=latest"
SESSIONS_URL = BASE_URL + "/v1/sessions?session_key=latest"
DRIVER_STANDINGS_URL = (
    "https://api.jolpi.ca/ergast/f1/2025/last/driverstandings/?format=json&limit=10"
)
CONSTRUCTOR_STANDINGS_URL = (
    "https://api.jolpi.ca/ergast/f1/2025/last/constructorstandings/?format=json&limit=10"
)

POLL_INTERVAL_SECONDS = 5
STARTUP_DELAY_SECONDS = 1.5
HTTP_READ_CHUNK_BYTES = 256
HTTP_TAIL_BYTES = 4096
STANDINGS_READ_CHUNK_BYTES = 128
STANDINGS_ENTRY_LIMIT = 10
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

CONSTRUCTOR_SHORT_NAME_PAIRS = (
    ("mclaren", "MCL"),
    ("ferrari", "FER"),
    ("red_bull", "RBR"),
    ("mercedes", "MER"),
    ("williams", "WIL"),
    ("aston_martin", "AST"),
    ("alpine", "ALP"),
    ("rb", "RBT"),
    ("haas", "HAA"),
    ("sauber", "SAU"),
)


DISPLAY_TYPE = pg.DISPLAY_PICO_DISPLAY_2

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
MAIN_SCREEN_DRIVER_GAP = 1
STANDINGS_POS_NAME_GAP = 12
STANDINGS_NAME_POINTS_GAP = 6
CONSTRUCTOR_STANDINGS_NAME_POINTS_GAP = 10


def event_info_snapshot():
    return (event_name, session_type_name, circuit_short_name, country_name)


def format_driver_code(driver_number):
    return DRIVER_CODES[int(driver_number)]


def api_url_for_driver(driver_number):
    return LAPS_BASE_URL + "&driver_number={}".format(driver_number)



def top_drivers_from_session_payload(payload, limit=TRACKED_DRIVER_COUNT):
    if not isinstance(payload, list):
        raise RuntimeError("Bad session_result payload")

    entries = payload
    ranked = []

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        driver_number = int(entry["driver_number"])
        position = int(entry["position"])
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

    return top_drivers[:limit]


def fetch_top_session_drivers(limit=TRACKED_DRIVER_COUNT):
    response = None
    gc.collect()
    try:
        response = urequests.get(SESSION_RESULT_URL, stream=True)
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
        response = urequests.get(MEETINGS_URL, stream=True)
        if response.status_code != 200:
            raise RuntimeError("HTTP {}".format(response.status_code))
        payload = json.loads(response.text)
        event_name = str(payload[-1]["meeting_name"])
    finally:
        if response is not None:
            response.close()
        gc.collect()

    response = None
    gc.collect()
    try:
        response = urequests.get(SESSIONS_URL, stream=True)
        if response.status_code != 200:
            raise RuntimeError("HTTP {}".format(response.status_code))
        payload = json.loads(response.text)
        session = payload[-1]
        st = str(session["session_type"])
        sn = str(session["session_name"])
        session_type_name = "{} - {}".format(st, sn)
        circuit_short_name = str(session["circuit_short_name"])
        country_name = str(session["country_name"])
    finally:
        if response is not None:
            response.close()
        gc.collect()


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


def constructor_short_name_from_entry(entry):
    raw_constructor_id = str(entry["Constructor"]["constructorId"])
    for constructor_id, short_name in CONSTRUCTOR_SHORT_NAME_PAIRS:
        if raw_constructor_id == constructor_id:
            return short_name

    raw_name = str(entry["Constructor"]["name"])
    return ellipsize(raw_name.upper(), 8)


def format_driver_standing_entry(entry):
    position = int(entry["position"])
    points_text = compact_number_text(entry["points"])
    wins_text = compact_number_text(entry["wins"])
    code = str(entry["Driver"]["code"]).upper()
    row = ("P{:02d}".format(position), code, points_text, "W{}".format(wins_text))
    return row, position


def format_constructor_standing_entry(entry):
    position = int(entry["position"])
    points_text = compact_number_text(entry["points"])
    wins_text = compact_number_text(entry["wins"])
    short_name = constructor_short_name_from_entry(entry)
    row = ("P{:02d}".format(position), short_name, points_text, "W{}".format(wins_text))
    return row, position


def standings_rows_from_stream(raw_stream, entry_key, format_fn, limit=STANDINGS_ENTRY_LIMIT):
    key_bytes = '"{}"'.format(entry_key).encode("utf-8")
    header = bytearray()
    key_found = False
    array_started = False

    in_string = False
    escape = False
    object_depth = 0
    object_bytes = bytearray()

    ranked = []
    def finalize_object():
        nonlocal object_bytes, ranked
        entry = json.loads(object_bytes.decode("utf-8"))
        row, position = format_fn(entry)
        object_bytes = bytearray()
        ranked.append((position, row))
        if limit > 0 and len(ranked) > limit:
            ranked.sort()
            del ranked[limit:]

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
                if limit > 0:
                    ranked = ranked[:limit]
                return [row for _position, row in ranked]

    if not ranked:
        raise RuntimeError("No standings data")
    ranked.sort()
    if limit > 0:
        ranked = ranked[:limit]
    return [row for _position, row in ranked]


def aggressive_gc():
    gc.collect()
    gc.collect()


def fetch_standing_rows(url, entry_key, format_fn, limit=STANDINGS_ENTRY_LIMIT):
    response = None
    aggressive_gc()
    try:
        response = urequests.get(url, stream=True)
        if response.status_code != 200:
            raise RuntimeError("HTTP {}".format(response.status_code))

        raw_stream = getattr(response, "raw", None)
        if raw_stream is None:
            raise RuntimeError("No streamed standings response")
        return standings_rows_from_stream(raw_stream, entry_key, format_fn, limit)
    finally:
        if response is not None:
            response.close()
        aggressive_gc()


def fetch_driver_standing_lines():
    return fetch_standing_rows(
        DRIVER_STANDINGS_URL,
        "DriverStandings",
        format_driver_standing_entry,
        STANDINGS_ENTRY_LIMIT,
    )


def fetch_constructor_standing_lines():
    return fetch_standing_rows(
        CONSTRUCTOR_STANDINGS_URL,
        "ConstructorStandings",
        format_constructor_standing_entry,
        STANDINGS_ENTRY_LIMIT,
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


def page_scroll_start(current_start, count, page_size, direction):
    if page_size <= 0:
        page_size = 1

    max_start = count - page_size
    if max_start < 0:
        max_start = 0

    if direction < 0:
        if current_start <= 0:
            return max_start
        next_start = current_start - page_size
        if next_start < 0:
            next_start = 0
        return next_start

    if current_start >= max_start:
        return 0

    next_start = current_start + page_size
    if next_start > max_start:
        next_start = max_start
    return next_start


def show_scrollable_lines(title, lines):
    count = len(lines)
    page_size = max(1, VISIBLE_ROWS)
    window_start = 0

    while True:
        max_window_start = max(0, count - page_size)
        if window_start > max_window_start:
            window_start = max_window_start

        display.set_pen(BLACK)
        display.clear()

        display.set_pen(WHITE)
        display.text(title, 8, 12, WIDTH - 16, 2)

        for i in range(page_size):
            idx = window_start + i
            if idx >= count:
                break
            y = 12 + (i + 1) * ROW_HEIGHT
            display.set_pen(WHITE)
            display.text("  {}".format(lines[idx]), 8, y, WIDTH - 16, 2)

        display.update()

        while True:
            if BUTTON_A.read():
                wait_for_release()
                return
            if BUTTON_X.read():
                window_start = page_scroll_start(window_start, count, page_size, -1)
                wait_for_release()
                break
            if BUTTON_Y.read():
                window_start = page_scroll_start(window_start, count, page_size, 1)
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


def show_scrollable_standings_rows(title, rows, name_points_gap=STANDINGS_NAME_POINTS_GAP):
    display.set_font("bitmap8")

    count = len(rows)
    page_size = max(1, VISIBLE_ROWS)
    window_start = 0

    left_margin = 8
    right_margin = 8
    marker_width = 0
    pos_name_gap = STANDINGS_POS_NAME_GAP
    col_gap = name_points_gap

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
    name_x = pos_x + pos_col_width + pos_name_gap
    points_x = name_x + name_col_width + col_gap
    wins_x = points_x + points_col_width + col_gap

    used_width = wins_x + wins_col_width + right_margin
    if used_width > WIDTH:
        overflow = used_width - WIDTH
        min_name_width = text_pixel_width("AAA", 2)
        name_col_width = max(min_name_width, name_col_width - overflow)
        points_x = name_x + name_col_width + col_gap
        wins_x = points_x + points_col_width + col_gap

    while True:
        max_window_start = max(0, count - page_size)
        if window_start > max_window_start:
            window_start = max_window_start

        display.set_pen(BLACK)
        display.clear()

        display.set_pen(WHITE)
        display.text(title, 8, 12, WIDTH - 16, 2)

        for i in range(page_size):
            idx = window_start + i
            if idx >= count:
                break

            y = 12 + (i + 1) * ROW_HEIGHT
            pos_text, name_text, points_text, wins_text = rows[idx]
            name_draw = fit_text_to_width(name_text, max(1, points_x - name_x - col_gap), 2)

            display.set_pen(WHITE)

            display.text(pos_text, pos_x, y, pos_col_width, 2)
            display.text(name_draw, name_x, y, max(1, points_x - name_x - col_gap), 2)
            display.text(points_text, points_x, y, points_col_width, 2)
            display.text(wins_text, wins_x, y, wins_col_width, 2)

        display.update()

        while True:
            if BUTTON_A.read():
                wait_for_release()
                return
            if BUTTON_X.read():
                window_start = page_scroll_start(window_start, count, page_size, -1)
                wait_for_release()
                break
            if BUTTON_Y.read():
                window_start = page_scroll_start(window_start, count, page_size, 1)
                wait_for_release()
                break
            time.sleep(BUTTON_POLL_SECONDS)


def show_standings_screen(title, fetch_lines_fn, name_points_gap=STANDINGS_NAME_POINTS_GAP):
    draw_lines([title, "Loading..."], CYAN)
    gc.collect()
    rows_or_lines = fetch_lines_fn()
    gc.collect()

    show_scrollable_standings_rows(title, rows_or_lines, name_points_gap)


def empty_lap_results():
    results = {}
    for dn in TRACKED_DRIVERS:
        results[dn] = (None, None)
    return results


def has_lap_data(lap_results):
    for dn in TRACKED_DRIVERS:
        lap_result = lap_results.get(dn)
        if lap_result is None:
            continue
        if lap_result[0] is not None:
            return True
    return False


def build_lap_rows(lap_results):
    rows = []
    leader_duration = None
    if TRACKED_DRIVERS:
        leader_result = lap_results.get(TRACKED_DRIVERS[0])
        if leader_result is not None and leader_result[0] is not None:
            leader_duration = float(leader_result[0])

    for dn in TRACKED_DRIVERS:
        lap_result = lap_results.get(dn)
        if lap_result is None:
            duration = None
            lap_number = None
        else:
            duration, lap_number = lap_result

        if duration is None:
            duration_text = "--:--.---"
            gap_text = "+--.---"
        else:
            duration_text = format_lap_duration(duration)
            if leader_duration is None:
                gap_text = "+--.---"
            else:
                gap_text = format_gap_to_leader(duration, leader_duration)

        if lap_number is None:
            lap_text = "lap --"
        else:
            lap_text = format_lap_number(lap_number)
        rows.append((format_driver_code(dn), duration_text, gap_text, lap_text))
    return rows


def text_pixel_width(text, scale=2):
    return display.measure_text(str(text), scale)


def draw_lap_screen(lap_results, color=WHITE):
    rows = build_lap_rows(lap_results)
    # Measure and render lap rows using a fixed font so column spacing
    # does not depend on whatever screen was shown previously.
    display.set_font("bitmap8")

    left_margin = 8
    right_margin = 8
    driver_gap = MAIN_SCREEN_DRIVER_GAP
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
    draw_lap_screen(lap_results, GREEN)


def handle_home_buttons(last_lap_results):
    global show_event_info

    if BUTTON_X.read():
        wait_for_release()
        aggressive_gc()
        show_standings_screen("Latest Driver Standings", fetch_driver_standing_lines)
        draw_cached_main_screen(last_lap_results)
        return True, last_lap_results

    if BUTTON_Y.read():
        wait_for_release()
        aggressive_gc()
        show_standings_screen(
            "Latest Constructors Standings",
            fetch_constructor_standing_lines,
            CONSTRUCTOR_STANDINGS_NAME_POINTS_GAP,
        )
        draw_cached_main_screen(last_lap_results)
        return True, last_lap_results

    if BUTTON_A.read():
        wait_for_release()
        selection_changed = select_driver_interactive()
        if selection_changed:
            refreshed_results = {}
            for dn in TRACKED_DRIVERS:
                lap_duration, lap_number, _ = fetch_latest_lap_duration(dn)
                refreshed_results[dn] = (lap_duration, lap_number)
            last_lap_results = refreshed_results
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
        import rp2
        rp2.country(WIFI_COUNTRY)

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(pm=0xA11140)  # Disable power save to avoid flaky station links.

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

    wlan.disconnect()

    wlan.connect(ssid, password)

    start = time.ticks_ms()
    shown_second = -1
    negative_status = None
    negative_since_ms = None
    negative_status_grace_ms = 2000
    while not wlan.isconnected():
        status = wlan.status()
        if status < 0:
            now_ms = time.ticks_ms()
            if status != negative_status:
                negative_status = status
                negative_since_ms = now_ms
            elif negative_since_ms is not None:
                if time.ticks_diff(now_ms, negative_since_ms) >= negative_status_grace_ms:
                    reason = status_map.get(status, "status {}".format(status))
                    wlan.disconnect()
                    raise RuntimeError("Wi-Fi {}".format(reason))
        else:
            negative_status = None
            negative_since_ms = None

        elapsed = time.ticks_diff(time.ticks_ms(), start) // 1000
        if elapsed != shown_second:
            shown_second = elapsed
            draw_lines(
                ["Wi-Fi", "Connecting {}s".format(elapsed), "st {}".format(status)],
                CYAN,
            )

        if time.ticks_diff(time.ticks_ms(), start) > timeout_seconds * 1000:
            reason = status_map.get(wlan.status(), "status {}".format(wlan.status()))
            wlan.disconnect()
            raise RuntimeError("Timeout ({})".format(reason))

        time.sleep(0.25)

    draw_lines(["Wi-Fi connected", wlan.ifconfig()[0]], GREEN)
    time.sleep(1)
    return wlan


def lap_from_tail_json(tail_text):
    end = len(tail_text)
    while True:
        end = tail_text.rfind("}", 0, end)
        if end < 0:
            break
        start = tail_text.rfind("{", 0, end)
        if start < 0:
            break
        candidate = json.loads(tail_text[start : end + 1])
        lap_duration = candidate["lap_duration"]
        if lap_duration is not None:
            lap_number = candidate["lap_number"]
            driver_number = candidate["driver_number"]
            return lap_duration, lap_number, driver_number
        end = start

    raise RuntimeError("No lap_duration rows")


def fetch_latest_lap_duration(driver_number):
    url = api_url_for_driver(driver_number)
    response = None
    gc.collect()
    try:
        response = urequests.get(url, stream=True)
        if response.status_code != 200:
            raise RuntimeError("HTTP {}".format(response.status_code))

        raw_stream = getattr(response, "raw", None)
        if raw_stream is None:
            raise RuntimeError("No streamed lap response")

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
    lap_duration, lap_number, _ = lap_from_tail_json(tail_text)
    return lap_duration, lap_number, driver_number


def format_lap_duration(value):
    total_seconds = float(value)

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
    gap_seconds = float(duration) - leader_duration
    sign = "+" if gap_seconds >= 0 else "-"
    gap_seconds = abs(gap_seconds)

    whole_seconds = int(gap_seconds)
    millis = int(round((gap_seconds - whole_seconds) * 1000))

    if millis == 1000:
        whole_seconds += 1
        millis = 0

    return "{}{}.{:03d}".format(sign, whole_seconds, millis)


def format_lap_number(value):
    return "lap {:02d}".format(int(value))


def main():
    global show_event_info
    draw_lines(["Booting...", "Starting network"], CYAN)
    time.sleep(STARTUP_DELAY_SECONDS)

    if WIFI_SSID == "YOUR_WIFI_SSID":
        draw_lines(["Set Wi-Fi creds", "in main.py"], RED)
        while True:
            time.sleep(1)

    wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD)

    last_lap_results = empty_lap_results()
    try:
        TRACKED_DRIVERS[:] = fetch_top_session_drivers(TRACKED_DRIVER_COUNT)
        fetch_event_and_session_info()

        startup_results = {}
        for dn in TRACKED_DRIVERS:
            lap_duration, lap_number, _ = fetch_latest_lap_duration(dn)
            startup_results[dn] = (lap_duration, lap_number)
        last_lap_results = startup_results
    except Exception:
        pass

    startup_color = GREEN if has_lap_data(last_lap_results) else CYAN
    draw_lap_screen(last_lap_results, startup_color)

    last_event_info = event_info_snapshot()

    while True:
        handled_button, last_lap_results = handle_home_buttons(last_lap_results)
        if handled_button:
            continue

        if not wlan.isconnected():
            try:
                wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD)
            except Exception:
                empty_results = empty_lap_results()
                if empty_results != last_lap_results:
                    draw_lap_screen(empty_results, CYAN)
                    last_lap_results = empty_results
                time.sleep(1)
                continue

        try:
            fetch_event_and_session_info()
            current_event_info = event_info_snapshot()
        except Exception:
            current_event_info = last_event_info

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
                lap_results[dn] = (None, None)

        if skip_fetch_cycle:
            continue

        if has_lap_data(lap_results):
            if lap_results != last_lap_results or current_event_info != last_event_info:
                draw_lap_screen(lap_results, GREEN)
                last_lap_results = lap_results
                last_event_info = current_event_info
        else:
            empty_results = empty_lap_results()
            if empty_results != last_lap_results:
                draw_lap_screen(empty_results, CYAN)
                last_lap_results = empty_results

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
