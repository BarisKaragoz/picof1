import time

import gc
import network
import picographics as pg # type: ignore
import urequests

try:
    import ujson as json
except ImportError:
    import json


# If your API runs on another device, replace localhost with that device's LAN IP.
API_BASE_URL = "http://192.168.26.249:8000/v1/laps?session_key=latest"
TRACKED_DRIVERS = [44, 81, 3]  # HAM, PIA, VER

from secrets import WIFI_SSID, WIFI_PASSWORD, WIFI_COUNTRY

POLL_INTERVAL_SECONDS = 5
STARTUP_DELAY_SECONDS = 1.5
HTTP_READ_CHUNK_BYTES = 256
HTTP_TAIL_BYTES = 4096
DISPLAY_BRIGHTNESS = 0.4

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


def format_driver_code(driver_number):
    if driver_number is None:
        return "?"

    try:
        driver_number = int(driver_number)
    except Exception:
        return str(driver_number)

    return DRIVER_CODES.get(driver_number, str(driver_number))


def api_url_for_driver(driver_number):
    return API_BASE_URL + "&driver_number={}".format(driver_number)



def draw_lines(lines, color=WHITE):
    display.set_pen(BLACK)
    display.clear()

    display.set_pen(color)
    y = 12
    for line in lines:
        display.text(str(line), 8, y, WIDTH - 16, 2)
        y += 28

    display.update()


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


def main():
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

    last_lap_results = None

    while True:
        try:
            if not wlan.isconnected():
                wlan = connect_wifi(WIFI_SSID, WIFI_PASSWORD)

            lap_results = {}
            for dn in TRACKED_DRIVERS:
                try:
                    lap_duration, _lap_number, _ = fetch_latest_lap_duration(dn)
                    lap_results[dn] = lap_duration
                except Exception:
                    lap_results[dn] = None

            if lap_results != last_lap_results:
                lines = ["Latest lap times"]
                for dn in TRACKED_DRIVERS:
                    duration = lap_results.get(dn)
                    if duration is not None:
                        lines.append("{} {}".format(
                            format_driver_code(dn),
                            format_lap_duration(duration),
                        ))
                    else:
                        lines.append("{} --:--.---".format(format_driver_code(dn)))
                draw_lines(lines, GREEN)
                last_lap_results = lap_results
        except Exception as exc:
            draw_lines(["Fetch error", str(exc)], RED)

        time.sleep(POLL_INTERVAL_SECONDS)


main()
