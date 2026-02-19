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

POLL_INTERVAL_SECONDS = 5
STARTUP_DELAY_SECONDS = 1.5
HTTP_READ_CHUNK_BYTES = 256
HTTP_TAIL_BYTES = 4096
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
                if val:
                    circuit_short_name = str(val)
                val = payload.get("country_name", "")
                if val:
                    country_name = str(val)
    except Exception:
        pass
    finally:
        if response is not None:
            response.close()
        gc.collect()


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

    while True:
        try:
            if not wlan.isconnected():
                wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD)

            lap_results = {}
            for dn in TRACKED_DRIVERS:
                try:
                    lap_duration, lap_number, _ = fetch_latest_lap_duration(dn)
                    lap_results[dn] = (lap_duration, lap_number)
                except Exception:
                    lap_results[dn] = None

            if lap_results != last_lap_results:
                draw_lap_screen(lap_results, GREEN)
                last_lap_results = lap_results
        except Exception as exc:
            draw_lines(["Fetch error", str(exc)], RED)

        # Sleep in short steps so Button A stays responsive.
        poll_remaining = int(POLL_INTERVAL_SECONDS / BUTTON_POLL_SECONDS)
        while poll_remaining > 0:
            if BUTTON_A.read():
                wait_for_release()
                selection_changed = select_driver_interactive()
                if selection_changed and last_lap_results is not None:
                    last_lap_results = {dn: last_lap_results.get(dn) for dn in TRACKED_DRIVERS}
                draw_cached_main_screen(last_lap_results)
                # After returning from selection, keep polling inputs instead
                # of jumping immediately into network fetches.
                poll_remaining = int(POLL_INTERVAL_SECONDS / BUTTON_POLL_SECONDS)
                continue
            if BUTTON_B.read():
                wait_for_release()
                show_event_info = not show_event_info
                draw_cached_main_screen(last_lap_results)
                poll_remaining = int(POLL_INTERVAL_SECONDS / BUTTON_POLL_SECONDS)
                continue
            time.sleep(BUTTON_POLL_SECONDS)
            poll_remaining -= 1


main()
